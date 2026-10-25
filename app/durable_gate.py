"""Synthetic-only durable admission and settlement, sharing the tenant ledger transaction."""
import copy
import os
from datetime import datetime,timedelta,timezone
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field,AwareDatetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import db
from .models import TestBatch,BatchAttempt,ReconciliationEvidence,Credential,RateVersion,Task,Tenant,ReceiptStatus,now
from .security import require,uid,audit
from .revisions import hashed
from .providers import enabled,rate_id,usage_cost
from .openai_provider import CARDS,upper_bound,normalized_usage,OpenAIUsage,OpenAIProvider,ProviderFailure
from .agent_schemas import CopyRequest,Draft
from .agent_runtime import build_prompt
from .batch_mock import mock_provider

router=APIRouter()
Scenario=Literal['normal','refusal','timeout','server_error','truncated','unknown_receipt','unknown_cost','overrun']


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def offline(executing: bool=False) -> None:
    if os.getenv('MOS_ENV')!='test' or os.getenv('MOS_LIVE_TESTS','false').lower()!='false':
        raise HTTPException(403,'Synthetic controlled-test environment required')
    if os.getenv('OPENAI_API_KEY') or os.getenv('ANTHROPIC_API_KEY'):
        raise HTTPException(403,'No environment provider keys accepted by durable gate')
    if executing and not enabled():raise HTTPException(503,'Model calls disabled, including mock')


def batch_for(s: Session,tid: str,bid: str) -> TestBatch:
    batch=s.scalar(select(TestBatch).where(TestBatch.tenant_id==tid,TestBatch.id==bid).execution_options(populate_existing=True))
    if not batch:raise HTTPException(404,'Batch not found')
    return batch


def attempt_for(s: Session,tid: str,bid: str,aid: str) -> BatchAttempt:
    item=s.scalar(select(BatchAttempt).where(BatchAttempt.tenant_id==tid,BatchAttempt.batch_id==bid,BatchAttempt.id==aid).execution_options(populate_existing=True))
    if not item:raise HTTPException(404,'Attempt not found')
    return item


def worker_access(s: Session,c: Credential,batch: TestBatch) -> None:
    if c.role!='worker' or 'execute' not in c.scopes or c.id not in batch.worker_ids:
        raise HTTPException(403,'Assigned tenant worker required')


def gate(s: Session,batch: TestBatch,tenant: Tenant,model: str) -> dict:
    offline(True)
    actor=s.scalar(select(Credential).where(Credential.id==batch.authorized_by,Credential.tenant_id==batch.tenant_id))
    if not actor or actor.revoked or actor.role!='owner' or actor.environment!='test' or utc(actor.expires_at)<=now():
        raise HTTPException(403,'Synthetic authorizing operator no longer valid')
    if batch.authorization_status!='SYNTHETIC_TEST_AUTHORIZATION' or batch.environment!='test':
        raise HTTPException(403,'No spend authorization exists')
    if batch.closed_at or utc(batch.deadline)<=now():raise HTTPException(409,'Batch expired or closed')
    if tenant.budget_paused or batch.paused or batch.uncertain_request_count:
        raise HTTPException(402,'Batch or tenant frozen')
    if model not in batch.allowed_model_ids:raise HTTPException(422,'Model not authorized for batch')
    card=batch.immutable_rate_snapshot[model]
    rate=s.get(RateVersion,rate_id(card))
    if not rate or rate.snapshot!=card or card!=CARDS.get(model):
        raise HTTPException(409,'Rate or bounded request contract changed')
    return dict(card)


class BatchCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    worker_ids: list[str]=Field(min_length=1,max_length=8)
    allowed_model_ids: list[str]=Field(min_length=1,max_length=2)
    maximum_total_micro_usd: int=Field(gt=0,le=100000000,strict=True)
    maximum_request_micro_usd: int=Field(gt=0,le=1000000,strict=True)
    maximum_requests: int=Field(gt=0,le=24,strict=True)
    deadline: AwareDatetime


class AttemptCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    idempotency_key: str=Field(min_length=8,max_length=128)
    model: str
    request: CopyRequest
    scenario: Scenario='normal'


class ReceiptImport(BaseModel):
    model_config=ConfigDict(extra='forbid')
    idempotency_key: str=Field(min_length=8,max_length=128)
    source: Literal['MOCK']='MOCK'
    response_id: str=Field(min_length=8,max_length=160)
    usage: OpenAIUsage
    draft: Draft


def batch_view(b: TestBatch) -> dict:
    return {key:getattr(b,key) for key in ('id','tenant_id','environment','authorization_reference','authorization_status',
        'authorized_by','worker_ids','allowed_model_ids','immutable_rate_snapshot','maximum_total_micro_usd',
        'maximum_request_micro_usd','maximum_requests','reserved_micro_usd','estimated_spent_micro_usd','request_count',
        'uncertain_request_count','deadline','paused','created_at','closed_at')}


def attempt_view(a: BatchAttempt) -> dict:
    return {key:getattr(a,key) for key in ('id','batch_id','tenant_id','task_id','model','rate_version','reserved_micro_usd',
        'estimated_cost_micro_usd','state','receipt_status','client_request_id','request_id','response_id','usage_missing_reason',
        'error_category','created_at','dispatched_at','result_recorded_at','settled_at','lease_expires_at','elapsed_ms')}


@router.post('/batches',status_code=201)
def create_batch(payload: BatchCreate,c: Credential=Depends(require('budget')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    offline();lock_tenant(s,c.tenant_id)
    if c.role!='owner':raise HTTPException(403,'Trusted tenant owner required')
    if not now()<payload.deadline<=min(now()+timedelta(hours=24),utc(c.expires_at)):
        raise HTTPException(422,'Deadline must be future and within operator authorization lifetime')
    if payload.maximum_request_micro_usd>payload.maximum_total_micro_usd or not set(payload.allowed_model_ids)<=set(CARDS):
        raise HTTPException(422,'Invalid caps or model allowlist')
    for wid in payload.worker_ids:
        worker=s.scalar(select(Credential).where(Credential.tenant_id==c.tenant_id,Credential.id==wid))
        if not worker or worker.role!='worker' or 'execute' not in worker.scopes or worker.revoked or utc(worker.expires_at)<=now() or worker.environment!='test':
            raise HTTPException(422,'Assigned worker not active in this tenant/environment')
    b=TestBatch(id=uid(),tenant_id=c.tenant_id,environment='test',authorization_reference='synthetic:'+uid(),
        authorization_status='SYNTHETIC_TEST_AUTHORIZATION',authorized_by=c.id,worker_ids=sorted(set(payload.worker_ids)),
        allowed_model_ids=sorted(set(payload.allowed_model_ids)),immutable_rate_snapshot={m:copy.deepcopy(CARDS[m]) for m in payload.allowed_model_ids},
        maximum_total_micro_usd=payload.maximum_total_micro_usd,maximum_request_micro_usd=payload.maximum_request_micro_usd,
        maximum_requests=payload.maximum_requests,deadline=payload.deadline)
    s.add(b);audit(s,c.tenant_id,'batch.synthetic_authorized',b.id,c.id);s.commit()
    return batch_view(b)


@router.get('/batches/{bid}')
def read_batch(bid: str,c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    return batch_view(batch_for(s,c.tenant_id,bid))


@router.get('/batches/{bid}/attempts')
def read_attempts(bid: str,c: Credential=Depends(require('read')),s: Session=Depends(db)) -> list[dict]:
    batch_for(s,c.tenant_id,bid)
    return [attempt_view(a) for a in s.scalars(select(BatchAttempt).where(BatchAttempt.tenant_id==c.tenant_id,BatchAttempt.batch_id==bid))]


@router.post('/batches/{bid}/close')
def close_batch(bid: str,c: Credential=Depends(require('budget')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    offline();lock_tenant(s,c.tenant_id);b=batch_for(s,c.tenant_id,bid)
    b.paused=True
    if not b.closed_at:b.closed_at=now();audit(s,c.tenant_id,'batch.closed',b.id,c.id)
    recover_attempts(s,c,bid)
    s.commit();return batch_view(b)


@router.post('/batches/{bid}/attempts',status_code=201)
def reserve_attempt(bid: str,payload: AttemptCreate,c: Credential=Depends(require('execute')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant,task_for,reserve_funds,ReserveRequest,dollars
    tenant=lock_tenant(s,c.tenant_id);b=batch_for(s,c.tenant_id,bid);worker_access(s,c,b)
    digest=hashed(payload.model_dump(mode='json'))
    prior=s.scalar(select(BatchAttempt).where(BatchAttempt.tenant_id==c.tenant_id,BatchAttempt.batch_id==bid,BatchAttempt.idempotency_key==payload.idempotency_key))
    if prior:
        if prior.request_hash!=digest:raise HTTPException(409,'Attempt idempotency conflict')
        return attempt_view(prior)
    card=gate(s,b,tenant,payload.model)
    context=payload.request
    if context.agent_id!='A09' or context.platform!='threads' or context.tools:raise HTTPException(422,'Only bounded A09 Threads without tools')
    task=task_for(s,c.tenant_id,context.task_id)
    if task.agent_id!='A09' or task.status!='DRAFT' or s.scalar(select(BatchAttempt.id).where(BatchAttempt.tenant_id==c.tenant_id,BatchAttempt.task_id==task.id)):
        raise HTTPException(409,'Task is already bound or dispatched')
    bound=upper_bound(card,context.max_output_tokens)
    if bound>b.maximum_request_micro_usd or b.reserved_micro_usd+b.estimated_spent_micro_usd+bound>b.maximum_total_micro_usd or b.request_count>=b.maximum_requests:
        raise HTTPException(402,'Batch request, amount or execution cap reached')
    reserve_funds(s,c,task.id,ReserveRequest(estimate_usd=dollars(bound),idempotency_key=payload.idempotency_key,rate_version=rate_id(card)))
    aid=uid();a=BatchAttempt(id=aid,tenant_id=c.tenant_id,batch_id=b.id,task_id=task.id,reserved_by=c.id,model=payload.model,
        rate_version=rate_id(card),rate_snapshot=card,idempotency_key=payload.idempotency_key,request_hash=digest,
        request_payload=context.model_dump(),scenario=payload.scenario,reserved_micro_usd=bound,state='RESERVED',
        lease_expires_at=now()+timedelta(seconds=120))
    s.add(a);b.reserved_micro_usd+=bound;b.request_count+=1
    audit(s,c.tenant_id,'attempt.reserved',aid,c.id);s.commit()
    return attempt_view(a)


def freeze(s: Session,c: Credential,b: TestBatch,a: BatchAttempt,category: str) -> None:
    if a.state!='RECONCILIATION_REQUIRED':b.uncertain_request_count+=1
    a.state='RECONCILIATION_REQUIRED';a.receipt_status='RECONCILIATION_REQUIRED';a.error_category=category
    a.usage_missing_reason=category if not a.provider_result else None
    if a.dispatched_at:a.elapsed_ms=max(0,int((now()-utc(a.dispatched_at)).total_seconds()*1000))
    task=s.get(Task,a.task_id);assert task is not None
    task.status='RECONCILIATION_REQUIRED';task.receipt_status=ReceiptStatus.RECONCILIATION_REQUIRED
    audit(s,c.tenant_id,'attempt.reconciliation_required',a.id,c.id)


def settle_attempt(s: Session,c: Credential,b: TestBatch,a: BatchAttempt) -> None:
    from .main import settle_receipt
    receipt=a.reconciliation_result or a.provider_result
    if not receipt:raise HTTPException(409,'Durable receipt required; no resend permitted')
    was_uncertain=a.receipt_status=='RECONCILIATION_REQUIRED'
    settle_receipt(s,c,a.task_id,a.idempotency_key,receipt,'MOCK_HTTP',commit=False)
    b.reserved_micro_usd-=a.reserved_micro_usd;b.estimated_spent_micro_usd+=receipt['actual_micro']
    if was_uncertain:b.uncertain_request_count-=1
    a.estimated_cost_micro_usd=receipt['actual_micro'];a.state='SETTLED';a.receipt_status='MOCK';a.settled_at=now();a.usage_missing_reason=None
    if a.dispatched_at:a.elapsed_ms=max(0,int((utc(a.result_recorded_at or now())-utc(a.dispatched_at)).total_seconds()*1000))
    if (receipt['actual_micro']>a.reserved_micro_usd or b.estimated_spent_micro_usd+b.reserved_micro_usd>b.maximum_total_micro_usd
            or receipt.get('usage_exceeds_limits') or receipt.get('unpriced_features')):
        b.paused=True;a.error_category='COST_OR_USAGE_ANOMALY'
    audit(s,c.tenant_id,'attempt.settled',a.id,c.id)


def record_result(s: Session,c: Credential,b: TestBatch,a: BatchAttempt,receipt: dict) -> None:
    a.provider_result=receipt;a.state='PROVIDER_RESULT_RECORDED';a.result_recorded_at=now()
    if not receipt.get('output_valid',True):a.error_category='OUTPUT_REVIEW_REQUIRED'
    a.request_id=receipt.get('request_id');a.response_id=receipt['receipt_id']
    audit(s,c.tenant_id,'attempt.provider_result_recorded',a.id,c.id);s.commit()


def cancel_reserved(s: Session,c: Credential,b: TestBatch,a: BatchAttempt,tenant: Tenant) -> None:
    from .main import release_reserved
    task=s.get(Task,a.task_id)
    release_reserved(s,tenant,task,'batch-recovery:'+a.id,c.id)
    b.reserved_micro_usd-=a.reserved_micro_usd;a.state='CANCELLED_BEFORE_DISPATCH';a.elapsed_ms=0
    a.usage_missing_reason='NOT_DISPATCHED';a.error_category='CANCELLED_BEFORE_DISPATCH'
    audit(s,c.tenant_id,'attempt.cancelled_before_dispatch',a.id,c.id)


def book_discrepancy(s: Session,c: Credential,b: TestBatch,a: BatchAttempt,tenant: Tenant,receipt: dict,eid: str) -> None:
    from .main import event
    previous=a.estimated_cost_micro_usd or 0;difference=receipt['actual_micro']-previous
    if difference>0:
        tenant.spent_micro+=difference;b.estimated_spent_micro_usd+=difference;a.estimated_cost_micro_usd=receipt['actual_micro']
        task=s.get(Task,a.task_id);assert task is not None and task.actual_micro is not None
        task.actual_micro+=difference
        event(s,c.tenant_id,task,'SETTLE',difference,{**receipt,'receipt_id':'mock-adjustment:'+eid,'actual_micro':difference,
            'adjustment_of_attempt':a.id,'previous_estimate_micro_usd':previous,'reported_total_micro_usd':receipt['actual_micro'],'difference_micro_usd':difference})
    freeze(s,c,b,a,'RECEIPT_DISCREPANCY');b.paused=True;tenant.budget_paused=True


@router.post('/batches/{bid}/attempts/{aid}/execute')
def execute_attempt(bid: str,aid: str,c: Credential=Depends(require('execute')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant,claim
    tenant=lock_tenant(s,c.tenant_id);b=batch_for(s,c.tenant_id,bid);worker_access(s,c,b);a=attempt_for(s,c.tenant_id,bid,aid)
    if a.state=='SETTLED':return attempt_view(a)
    if a.state=='PROVIDER_RESULT_RECORDED':settle_attempt(s,c,b,a);s.commit();return attempt_view(a)
    if a.state!='RESERVED':raise HTTPException(409,'Outcome may be unknown; automatic resend forbidden')
    gate(s,b,tenant,a.model)
    payload=CopyRequest.model_validate(a.request_payload);prompt=build_prompt(payload,c.tenant_id)
    provider=mock_provider(a.model,a.scenario,a.rate_snapshot)
    try:
        count=provider.count_tokens(prompt)
        if count>a.rate_snapshot['max_input_tokens']:raise ProviderFailure('INPUT_LIMIT',unknown=False)
    except ProviderFailure:
        cancel_reserved(s,c,b,a,tenant);s.commit()
        raise HTTPException(422,'Count failed before generation; slot retained, reservation released') from None
    gate(s,b,tenant,a.model)
    claim(s,c,a.task_id,commit=False)
    a.state='DISPATCHING';a.dispatched_at=now();a.lease_expires_at=now()+timedelta(seconds=120);a.client_request_id=a.id
    audit(s,c.tenant_id,'attempt.dispatching',a.id,c.id);s.commit()
    provider.generation_request_id=a.id
    try:
        receipt=provider.generate(prompt,payload.max_output_tokens)
        receipt={**receipt,'request_context':a.request_payload,'request_hash':a.request_hash,'prompt_version':'a09-1',
                 'input_count':{'value':count,'source':'MOCK_HTTP_FULL_REQUEST_COUNT'},'reserved_upper_bound_micro':a.reserved_micro_usd}
        lock_tenant(s,c.tenant_id);b=batch_for(s,c.tenant_id,bid);a=attempt_for(s,c.tenant_id,bid,aid)
        if a.state not in {'DISPATCHING','RECONCILIATION_REQUIRED'} or a.estimated_cost_micro_usd is not None:
            # A competing trusted import may have settled already; preserve the late response for review.
            eid=uid()
            s.add(ReconciliationEvidence(id=eid,tenant_id=c.tenant_id,batch_id=bid,attempt_id=aid,actor_id=c.id,
                status='RECONCILIATION_REQUIRED',idempotency_key='late:'+a.id,request_hash=hashed(receipt),receipt=receipt,
                previous_estimate_micro_usd=a.estimated_cost_micro_usd,reported_micro_usd=receipt['actual_micro'],
                difference_micro_usd=receipt['actual_micro']-(a.estimated_cost_micro_usd or 0)))
            tenant=lock_tenant(s,c.tenant_id);book_discrepancy(s,c,b,a,tenant,receipt,eid);s.commit()
            raise HTTPException(409,'Late receipt preserved; trusted review required')
        record_result(s,c,b,a,receipt)
        lock_tenant(s,c.tenant_id);b=batch_for(s,c.tenant_id,bid);a=attempt_for(s,c.tenant_id,bid,aid)
        settle_attempt(s,c,b,a);s.commit();return attempt_view(a)
    except Exception as exc:
        s.rollback();lock_tenant(s,c.tenant_id);b=batch_for(s,c.tenant_id,bid);a=attempt_for(s,c.tenant_id,bid,aid)
        if a.state=='DISPATCHING':
            a.request_id=provider.last_request_id;a.response_id=provider.last_response_id
            freeze(s,c,b,a,exc.category if isinstance(exc,ProviderFailure) else 'UNKNOWN_EXECUTION_FAILURE')
        audit(s,c.tenant_id,'attempt.execution_interrupted',a.id,c.id);s.commit()
        raise HTTPException(502,'Durable outcome requires recovery/reconciliation; no retry') from None


def recover_attempts(s: Session,c: Credential,bid: str | None=None) -> dict:
    from .main import lock_tenant
    tenant=lock_tenant(s,c.tenant_id);counts={'settled':0,'cancelled':0,'uncertain':0}
    for a in s.scalars(select(BatchAttempt).where(BatchAttempt.tenant_id==c.tenant_id,BatchAttempt.state.in_(['RESERVED','DISPATCHING','PROVIDER_RESULT_RECORDED']))).all():
        b=batch_for(s,c.tenant_id,a.batch_id)
        if bid and b.id!=bid:continue
        if c.id not in b.worker_ids and not (bid and c.role=='owner' and 'budget' in c.scopes):continue
        if a.state=='PROVIDER_RESULT_RECORDED':settle_attempt(s,c,b,a);counts['settled']+=1
        elif utc(a.lease_expires_at)<=now() or (a.state=='RESERVED' and (utc(b.deadline)<=now() or b.closed_at)):
            if a.state=='RESERVED':
                cancel_reserved(s,c,b,a,tenant);counts['cancelled']+=1
            else:freeze(s,c,b,a,'DISPATCH_LEASE_EXPIRED');counts['uncertain']+=1
    return counts


@router.post('/batches/{bid}/attempts/{aid}/reconcile')
def import_receipt(bid: str,aid: str,payload: ReceiptImport,c: Credential=Depends(require('budget')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    offline();tenant=lock_tenant(s,c.tenant_id);b=batch_for(s,c.tenant_id,bid);a=attempt_for(s,c.tenant_id,bid,aid)
    if c.role!='owner':raise HTTPException(403,'Trusted owner receipt importer required')
    if not payload.response_id.startswith('mock-import:') or not OpenAIProvider.safe_id(payload.response_id):
        raise HTTPException(422,'Only synthetic receipt references accepted')
    digest=hashed(payload.model_dump(mode='json'))
    prior=s.scalar(select(ReconciliationEvidence).where(ReconciliationEvidence.tenant_id==c.tenant_id,ReconciliationEvidence.attempt_id==aid,ReconciliationEvidence.idempotency_key==payload.idempotency_key))
    if prior:
        if prior.request_hash!=digest:raise HTTPException(409,'Reconciliation idempotency conflict')
        return {'evidence_id':prior.id,'status':prior.status,'difference_micro_usd':prior.difference_micro_usd}
    if a.state not in {'RECONCILIATION_REQUIRED','SETTLED'}:raise HTTPException(409,'Attempt not awaiting receipt review')
    usage=normalized_usage(payload.usage.model_dump());cost=usage_cost(usage,a.rate_snapshot)
    previous=a.estimated_cost_micro_usd;difference=cost-previous if previous is not None else None
    receipt={'provider':'openai','model':a.model,'receipt_id':payload.response_id,'usage':usage,'provider_usage':payload.usage.model_dump(),
        'actual_micro':cost,'output':payload.draft.model_dump_json(),'draft':payload.draft.model_dump(),'request_context':a.request_payload,
        'prompt_version':'a09-1','evidence_origin':'MOCK_HTTP','verified_invoice_cost_micro_usd':None,'provider_called':False}
    eid=uid();status='RECONCILIATION_REQUIRED' if difference else 'MOCK'
    evidence=ReconciliationEvidence(id=eid,tenant_id=c.tenant_id,batch_id=bid,attempt_id=aid,actor_id=c.id,
        status=status,idempotency_key=payload.idempotency_key,request_hash=digest,receipt=receipt,
        previous_estimate_micro_usd=previous,reported_micro_usd=cost,difference_micro_usd=difference)
    s.add(evidence)
    if previous is None:
        a.reconciliation_result=receipt;a.state='PROVIDER_RESULT_RECORDED';a.result_recorded_at=now()
        settle_attempt(s,c,b,a)
    elif difference:
        book_discrepancy(s,c,b,a,tenant,receipt,eid)
    audit(s,c.tenant_id,'attempt.mock_receipt_imported',eid,c.id);s.commit()
    return {'evidence_id':eid,'status':status,'difference_micro_usd':difference}


@router.get('/batches/{bid}/attempts/{aid}/evidence')
def read_evidence(bid: str,aid: str,c: Credential=Depends(require('read')),s: Session=Depends(db)) -> list[dict]:
    batch_for(s,c.tenant_id,bid);attempt_for(s,c.tenant_id,bid,aid)
    records=s.scalars(select(ReconciliationEvidence).where(ReconciliationEvidence.tenant_id==c.tenant_id,ReconciliationEvidence.attempt_id==aid)).all()
    return [{'evidence_id':e.id,'source':e.source,'status':e.status,'actor_id':e.actor_id,'receipt':e.receipt,
             'previous_estimate_micro_usd':e.previous_estimate_micro_usd,'reported_micro_usd':e.reported_micro_usd,
             'difference_micro_usd':e.difference_micro_usd,'created_at':e.created_at} for e in records]
