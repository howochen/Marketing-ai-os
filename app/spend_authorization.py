"""Trusted internal approvals, deliberately insufficient to authorize external spending."""
from datetime import timedelta
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field,AwareDatetime,model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import db
from .models import SpendAuthorization,Credential,now
from .security import admin,require,uid,audit
from .revisions import hashed
from .durable_gate import batch_for,offline,utc
from .openai_provider import CARDS,upper_bound

router=APIRouter()


class AuthorizationTerms(BaseModel):
    model_config=ConfigDict(extra='forbid')
    environment: Literal['controlled-test']
    account_id: str=Field(pattern=r'^(?:acct_|org-)[A-Za-z0-9_-]{4,80}$')
    project_id: str=Field(pattern=r'^proj_[A-Za-z0-9_-]{4,80}$')
    consent_evidence_sha256: str=Field(pattern=r'^[0-9a-f]{64}$')
    allowed_model_ids: list[str]=Field(min_length=1,max_length=2)
    maximum_request_micro_usd: int=Field(gt=0,le=1000000,strict=True)
    maximum_total_micro_usd: int=Field(gt=0,le=100000000,strict=True)
    maximum_requests: int=Field(gt=0,le=24,strict=True)
    effective_at: AwareDatetime
    deadline: AwareDatetime
    round: Literal['SMOKE','BENCHMARK']
    stop_conditions: list[Literal['UNKNOWN_RESULT','COST_ANOMALY','KILL_SWITCH','QA_FAILURE']]=Field(min_length=4,max_length=4)

    @model_validator(mode='after')
    def consistent(self) -> 'AuthorizationTerms':
        if (self.maximum_request_micro_usd>self.maximum_total_micro_usd
                or self.deadline<=self.effective_at or self.deadline-self.effective_at>timedelta(hours=24)
                or len(set(self.allowed_model_ids))!=len(self.allowed_model_ids)
                or not set(self.allowed_model_ids)<=set(CARDS)
                or set(self.stop_conditions)!={'UNKNOWN_RESULT','COST_ANOMALY','KILL_SWITCH','QA_FAILURE'}
                or (self.round=='SMOKE' and self.maximum_requests>2)):
            raise ValueError('Invalid bounded authorization terms')
        return self


class ApprovalCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    idempotency_key: str=Field(min_length=8,max_length=128)
    terms: AuthorizationTerms


def view(item: SpendAuthorization) -> dict:
    return {key:getattr(item,key) for key in ('id','tenant_id','batch_id','approver_id','status','terms','created_at')}


@router.post('/admin/batches/{bid}/spend-approvals',status_code=201,dependencies=[Depends(admin)])
def create_approval(bid: str,payload: ApprovalCreate,c: Credential=Depends(require('budget')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    offline();lock_tenant(s,c.tenant_id)
    b=batch_for(s,c.tenant_id,bid)
    terms=payload.terms
    body=terms.model_dump(mode='json');digest=hashed({'batch_id':bid,'terms':body})
    prior=s.scalar(select(SpendAuthorization).where(SpendAuthorization.tenant_id==c.tenant_id,SpendAuthorization.idempotency_key==payload.idempotency_key))
    if prior:
        if prior.request_hash!=digest:raise HTTPException(409,'Approval idempotency conflict')
        return view(prior)
    if (b.closed_at or utc(b.deadline)<=now() or b.authorized_by!=c.id or c.revoked or utc(c.expires_at)<=now()
            or terms.deadline<=now() or terms.effective_at>now()+timedelta(hours=24)
            or terms.deadline>utc(b.deadline) or terms.deadline>utc(c.expires_at)
            or terms.maximum_total_micro_usd>b.maximum_total_micro_usd
            or terms.maximum_request_micro_usd>b.maximum_request_micro_usd
            or terms.maximum_requests>b.maximum_requests
            or not set(terms.allowed_model_ids)<=set(b.allowed_model_ids)):
        raise HTTPException(409,'Approval exceeds trusted batch or operator constraints')
    for model in terms.allowed_model_ids:
        if upper_bound(b.immutable_rate_snapshot[model],b.immutable_rate_snapshot[model]['max_output_tokens'])>terms.maximum_request_micro_usd:
            raise HTTPException(422,'Request bound exceeds approval')
    item=SpendAuthorization(id=uid(),tenant_id=c.tenant_id,batch_id=b.id,approver_id=c.id,
        status='INTERNAL_APPROVAL_ONLY',idempotency_key=payload.idempotency_key,request_hash=digest,
        terms={**body,'rate_snapshots':b.immutable_rate_snapshot,'account_access':'ACCOUNT_ACCESS_NOT_VERIFIED',
               'consent_verified':False,'execution_authorized':False})
    s.add(item);audit(s,c.tenant_id,'spend.internal_approval_only',item.id,c.id);s.commit()
    return view(item)


@router.get('/batches/{bid}/spend-approvals/{approval_id}')
def read_approval(bid: str,approval_id: str,c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    batch_for(s,c.tenant_id,bid)
    item=s.scalar(select(SpendAuthorization).where(SpendAuthorization.id==approval_id,
        SpendAuthorization.tenant_id==c.tenant_id,SpendAuthorization.batch_id==bid))
    if not item:raise HTTPException(404,'Approval not found')
    return view(item)
