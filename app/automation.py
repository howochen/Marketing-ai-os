"""Owner policy delegation over existing Task, A09, A21, ledger and publisher."""
import difflib
import json
import os
import re
from datetime import datetime,timedelta,time,timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,ConfigDict,Field,AwareDatetime,SecretStr,model_validator
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from .database import db
from .models import AutomationPolicy,AutomationSlot,Credential,Task,DraftRevision,Publication,RateVersion,ReceiptStatus,AutomationAttempt,now
from .security import require,audit,uid,issue
from .content_workbench import Brief
from .durable_gate import utc
from .revisions import hashed,context,revision_for
from .agent_runtime import qa,build_prompt
from .threads_routes import owner,connection,token_for,api,refresh_connection,connection_failure
from .threads_api import ThreadsAPI,seal
from .providers import MockLLMProvider,MODEL,usage_cost,rate_id,LLMProvider
from .openai_provider import OpenAIProvider,CARDS,upper_bound,ProviderFailure
from .semantic_review import BrandFact,evidence_check,SemanticProvider,review_prompt

router=APIRouter(prefix='/automation')
TAIPEI=ZoneInfo('Asia/Taipei')


class Terms(BaseModel):
    model_config=ConfigDict(extra='forbid')
    mode: str=Field(pattern='^(MANUAL|REVIEW|FULL)$')
    connection_id: str
    brief: Brief
    topics: list[str]=Field(min_length=1,max_length=60)
    approved_copy: list[str]=Field(default_factory=list,max_length=60)
    creative_mode: str=Field(default='MATERIALS',pattern='^(MATERIALS|BRAND_GUIDED)$')
    knowledge_facts: list[BrandFact]=Field(default_factory=list,max_length=30)
    semantic_reviewer: str=Field(default='HUMAN_REQUIRED',pattern='^(HUMAN_REQUIRED|MODEL_REQUIRED)$')
    semantic_model: str=Field(default='gpt-6-luna',pattern='^gpt-6-luna$')
    max_rewrites: int=Field(default=0,ge=0,le=1,strict=True)
    sensitive_terms: list[str]=Field(default_factory=list,max_length=30)
    weekdays: list[int]=Field(min_length=1,max_length=7)
    times: list[str]=Field(min_length=1,max_length=10)
    daily_max: int=Field(ge=1,le=10)
    monthly_budget_micro: int=Field(ge=1,le=100_000_000)
    model: str=Field(pattern='^(mock-a09-v1|gpt-6-luna)$')
    starts_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode='after')
    def limits(self) -> 'Terms':
        if self.expires_at<=self.starts_at or self.expires_at-self.starts_at>timedelta(days=90):raise ValueError('Policy duration must be 1..90 days')
        if len(set(self.times))!=len(self.times) or any(not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',x) for x in self.times):raise ValueError('Unique HH:MM times required')
        if any(type(x) is not int or not 0<=x<=6 for x in self.weekdays) or len(set(self.weekdays))!=len(self.weekdays):raise ValueError('Weekdays are Monday=0..Sunday=6')
        if any(not 1<=len(x.strip())<=500 for x in self.topics+self.approved_copy+self.sensitive_terms):raise ValueError('Invalid policy text')
        if self.creative_mode=='BRAND_GUIDED' and (not self.knowledge_facts or len({f.id for f in self.knowledge_facts})!=len(self.knowledge_facts)):raise ValueError('Unique owner facts required')
        if self.mode=='FULL' and self.creative_mode=='MATERIALS' and len(self.approved_copy)<3:raise ValueError('Full mode requires owner-approved copy blocks, including Hook and CTA')
        return self


class CreatePolicy(BaseModel):
    model_config=ConfigDict(extra='forbid')
    terms: Terms
    supersedes: str | None=None


class Confirm(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    terms_hash: str
    confirm_delegated_publication: bool


class KeyInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    api_key: SecretStr=Field(min_length=20,max_length=512)


def policy_for(s: Session,tid: str,pid: str) -> AutomationPolicy:
    p=s.scalar(select(AutomationPolicy).where(AutomationPolicy.tenant_id==tid,AutomationPolicy.id==pid).execution_options(populate_existing=True))
    if not p:raise HTTPException(404,'POLICY_NOT_FOUND')
    return p


def policy_view(p: AutomationPolicy) -> dict:
    return {'id':p.id,'terms':p.terms,'terms_hash':p.terms_hash,'state':p.state,'supersedes':p.supersedes,
        'key_present':bool(p.key_ciphertext),'created_at':p.created_at,'live_execution_enabled':False}


@router.get('/policies')
def policies(c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    return {'policies':[policy_view(p) for p in s.scalars(select(AutomationPolicy).where(AutomationPolicy.tenant_id==c.tenant_id).order_by(AutomationPolicy.created_at.desc()))],
        'enabled':os.getenv('MOS_AUTOMATION_ENABLED','false')=='true','live_execution_enabled':False,'timezone':'Asia/Taipei'}


@router.post('/policies',status_code=201)
def create(body: CreatePolicy,c: Credential=Depends(require('credentials')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    owner(c);lock_tenant(s,c.tenant_id);conn=connection(s,c.tenant_id,body.terms.connection_id)
    token_for(conn)
    if body.terms.expires_at<=now():raise HTTPException(422,'POLICY_ALREADY_EXPIRED')
    if body.supersedes:
        previous=policy_for(s,c.tenant_id,body.supersedes);previous.state='REVOKED'
        audit(s,c.tenant_id,'automation.superseded',previous.id,c.id)
    terms=body.terms.model_dump(mode='json');p=AutomationPolicy(id=uid(),tenant_id=c.tenant_id,terms=terms,terms_hash=hashed(terms),owner_id=c.id,supersedes=body.supersedes,state='DRAFT')
    s.add(p);audit(s,c.tenant_id,'automation.created',p.id,c.id);s.commit();return policy_view(p)


@router.post('/policies/{pid}/activate')
def activate(pid: str,body: Confirm,c: Credential=Depends(require('credentials')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    owner(c);lock_tenant(s,c.tenant_id);p=policy_for(s,c.tenant_id,pid)
    if p.state=='REVOKED' or p.owner_id!=c.id or not body.confirm_delegated_publication or body.terms_hash!=p.terms_hash:raise HTTPException(403,'EXACT_OWNER_POLICY_CONSENT_REQUIRED')
    t=Terms.model_validate(p.terms)
    if t.expires_at<=now():raise HTTPException(409,'POLICY_EXPIRED')
    token_for(connection(s,c.tenant_id,t.connection_id))
    if not p.worker_ciphertext:
        token,worker=issue(s,c.tenant_id,'automation:'+p.id,'automation_worker',['automation','policy:'+p.id],hours=1)
        worker.expires_at=t.expires_at;p.worker_ciphertext=seal(token,c.tenant_id,'automation-worker:'+p.id)
    p.state='ACTIVE';audit(s,c.tenant_id,'automation.activated',p.id,c.id);s.commit();return policy_view(p)


@router.post('/pause-all')
def pause_all(c: Credential=Depends(require('credentials')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    owner(c);lock_tenant(s,c.tenant_id);count=0
    for p in s.scalars(select(AutomationPolicy).where(AutomationPolicy.tenant_id==c.tenant_id,AutomationPolicy.state=='ACTIVE')):
        p.state='PAUSED';audit(s,c.tenant_id,'automation.paused',p.id,c.id);count+=1
    s.commit();return {'paused':count}


@router.post('/policies/{pid}/revoke')
def revoke(pid: str,c: Credential=Depends(require('credentials')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    owner(c);lock_tenant(s,c.tenant_id);p=policy_for(s,c.tenant_id,pid);p.state='REVOKED'
    audit(s,c.tenant_id,'automation.revoked',p.id,c.id);s.commit();return policy_view(p)


@router.post('/policies/{pid}/provider-key')
def store_key(pid: str,body: KeyInput,request: Request,c: Credential=Depends(require('credentials')),s: Session=Depends(db)) -> dict:
    from .browser_session import transport_allowed
    from .main import lock_tenant
    transport_allowed(request);owner(c);lock_tenant(s,c.tenant_id);p=policy_for(s,c.tenant_id,pid)
    if p.owner_id!=c.id or p.state!='DRAFT':raise HTTPException(409,'KEY_CONFIGURATION_REQUIRES_DRAFT_POLICY')
    p.key_ciphertext=seal(body.api_key.get_secret_value(),c.tenant_id,'automation-key:'+p.id)
    audit(s,c.tenant_id,'automation.key_configured',p.id,c.id);s.commit();return {'key_present':True}


@router.post('/policies/{pid}/worker-credential')
def worker_credential(pid: str,c: Credential=Depends(require('credentials')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    owner(c);lock_tenant(s,c.tenant_id);p=policy_for(s,c.tenant_id,pid);t=Terms.model_validate(p.terms)
    if p.owner_id!=c.id or p.state!='ACTIVE' or t.expires_at<=now():raise HTTPException(409,'ACTIVE_OWNER_POLICY_REQUIRED')
    # Dedicated principal cannot call generic execute/settle/admin endpoints or impersonate an owner.
    token,w=issue(s,c.tenant_id,'automation:'+p.id,'automation_worker',['automation','policy:'+p.id],hours=1)
    w.expires_at=t.expires_at;audit(s,c.tenant_id,'automation.worker_issued',p.id,c.id);s.commit()
    return {'token':token,'expires_at':w.expires_at,'policy_id':p.id}


@router.get('/slots')
def slots(c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    rows=s.scalars(select(AutomationSlot).where(AutomationSlot.tenant_id==c.tenant_id).order_by(AutomationSlot.scheduled_at.desc()).limit(200)).all()
    result=[]
    for a in rows:
        p=s.get(Publication,a.publication_id) if a.publication_id else None;t=s.get(Task,a.task_id) if a.task_id else None
        result.append({'id':a.id,'policy_id':a.policy_id,'scheduled_at':utc(a.scheduled_at),'state':a.state,'error':a.error,'task_id':a.task_id,
            'revision_id':a.revision_id,'publication_id':a.publication_id,'draft':t.output if t else None,
            'qa':revision_for(s,c.tenant_id,a.task_id or '',a.revision_id).qa_result if a.revision_id else None,
            'cost_micro':t.actual_micro if t else None,'receipt_source':t.receipt_source if t else None,
            'permalink':p.permalink if p else None,'media_id':p.published_media_id if p else None,'verification':p.verification_status if p else None})
    return {'slots':result,'timezone':'Asia/Taipei'}


def worker_policy(s: Session,c: Credential,pid: str) -> AutomationPolicy:
    from .main import lock_tenant
    tenant=lock_tenant(s,c.tenant_id);s.refresh(c);p=policy_for(s,c.tenant_id,pid);t=Terms.model_validate(p.terms)
    actor=s.get(Credential,p.owner_id,populate_existing=True)
    if (os.getenv('MOS_AUTOMATION_ENABLED','false')!='true' or c.role!='automation_worker' or 'automation' not in c.scopes
            or 'policy:'+p.id not in c.scopes or c.revoked or utc(c.expires_at)<=now() or c.environment!=os.getenv('MOS_ENV')
            or p.state!='ACTIVE' or not t.starts_at<=now()<t.expires_at or tenant.disabled or tenant.budget_paused
            or not actor or actor.tenant_id!=c.tenant_id or actor.role!='owner' or (actor.revoked and actor.logged_out_at is None) or actor.environment!=c.environment):
        raise HTTPException(403,'AUTOMATION_POLICY_OR_WORKER_STOPPED')
    # Explicit, expiring policy survives login expiry; revocation of its trusted issuer still stops it.
    conn=connection(s,c.tenant_id,t.connection_id);token_for(conn)
    if conn.authorized_at is None:raise HTTPException(403,'AUTHORIZATION_TIME_UNKNOWN_REAUTHORIZE')
    return p


def auto_qa(draft: dict,t: Terms) -> list[str]:
    text=str(draft.get('draft_text',''));reasons=[]
    if any(x.casefold() in text.casefold() for x in t.sensitive_terms):reasons.append('SENSITIVE_TOPIC_REQUIRES_HUMAN')
    if re.search(r'治療|療效|診斷|醫療|治癒|投資|保證|報酬|療程',text):reasons.append('PROFESSIONAL_REVIEW_REQUIRED')
    if t.mode=='FULL' and t.creative_mode=='MATERIALS' and any(line.strip() not in t.approved_copy for line in text.splitlines() if line.strip()):
        reasons.append('FACTS_OR_SEMANTICS_UNEVALUATED_OWNER_REVIEW_REQUIRED')
    return reasons


def publication_authority(s: Session,c: Credential,p: Publication) -> None:
    policy=worker_policy(s,c,p.automation_policy_id or '');t=Terms.model_validate(policy.terms)
    a=s.scalar(select(AutomationSlot).where(AutomationSlot.tenant_id==c.tenant_id,AutomationSlot.policy_id==policy.id,AutomationSlot.publication_id==p.id))
    task=s.get(Task,p.task_id,populate_existing=True)
    if (not a or a.revision_id!=p.revision_id or not task or task.latest_revision_id!=p.revision_id
            or p.platform_account_id!=t.connection_id or now()<utc(a.scheduled_at) or now()>utc(a.scheduled_at)+timedelta(minutes=3)):
        raise HTTPException(409,'POLICY_SLOT_REVISION_OR_TIME_MISMATCH')
    record=revision_for(s,c.tenant_id,p.task_id,p.revision_id or '')
    _,checked=qa(json.dumps(record.draft),context(task))
    if not checked.passed or p.content_snapshot!=record.after_text:raise HTTPException(409,'POLICY_QA_OR_SNAPSHOT_BLOCKED')
    if t.mode=='FULL':
        if auto_qa(record.draft,t):raise HTTPException(409,'AUTOMATION_REQUIRES_HUMAN_REVIEW')
        if t.creative_mode=='BRAND_GUIDED' and semantic_issues(s,task,record.draft,policy,t):raise HTTPException(409,'SEMANTIC_EVIDENCE_REQUIRED')
    elif t.mode=='REVIEW':
        from .models import RevisionApproval
        approval=s.scalar(select(RevisionApproval).where(RevisionApproval.tenant_id==c.tenant_id,RevisionApproval.revision_id==record.id))
        reviewer=s.get(Credential,approval.reviewer_id,populate_existing=True) if approval else None
        if task.approved_revision_id!=record.id or not reviewer or reviewer.role!='owner' or (reviewer.revoked and reviewer.logged_out_at is None) or reviewer.tenant_id!=c.tenant_id:raise HTTPException(403,'EXACT_OWNER_REVISION_APPROVAL_REQUIRED')
    else:raise HTTPException(403,'MANUAL_POLICY_CANNOT_DISPATCH')


def monthly_total(s: Session,tid: str,when: datetime) -> int:
    start=when.astimezone(TAIPEI).replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    end=(start.replace(day=28)+timedelta(days=4)).replace(day=1)
    slots=list(s.scalars(select(AutomationSlot).where(AutomationSlot.tenant_id==tid,AutomationSlot.scheduled_at>=start,AutomationSlot.scheduled_at<end)))
    ids={a.task_id for a in slots if a.task_id}
    ids.update(s.scalars(select(AutomationAttempt.task_id).where(AutomationAttempt.tenant_id==tid,AutomationAttempt.slot_id.in_([a.id for a in slots]))))
    records=s.execute(select(Task.actual_micro,Task.reserved_micro,Task.settle_key,Task.status).where(Task.tenant_id==tid,Task.id.in_(ids))).all()
    return sum((actual or 0) if settled else reserved if state in {'RESERVED','RUNNING','RECONCILIATION_REQUIRED'} else 0 for actual,reserved,settled,state in records)


def semantic_provider(p: AutomationPolicy) -> SemanticProvider:
    return SemanticProvider(p)


def semantic_issues(s: Session,task: Task,draft: dict,p: AutomationPolicy,t: Terms) -> list[str]:
    if t.semantic_reviewer!='MODEL_REQUIRED':return ['HUMAN_SEMANTIC_REVIEW_REQUIRED']
    run=task.agent_run or {};rid=run.get('semantic_task_id')
    review=s.get(Task,rid,populate_existing=True) if rid else None
    if not review or review.tenant_id!=task.tenant_id or review.status=='RECONCILIATION_REQUIRED' or not review.receipt or not review.settle_key:
        return ['SEMANTIC_REVIEW_REQUIRED']
    if run.get('draft_sha256')!=hashed(draft) or run.get('policy_hash')!=p.terms_hash:return ['STALE_SEMANTIC_EVIDENCE']
    return evidence_check(draft,p.terms_hash,t.knowledge_facts,review.receipt.get('semantic_review'))


def review_draft(s: Session,c: Credential,p: AutomationPolicy,a: AutomationSlot,task: Task,draft: dict,t: Terms,ordinal: int) -> list[str]:
    from .main import reserve_funds,ReserveRequest,dollars,claim,settle_receipt,lock_tenant
    if t.semantic_reviewer!='MODEL_REQUIRED':return ['HUMAN_SEMANTIC_REVIEW_REQUIRED']
    provider=semantic_provider(p);card=provider.card;bound=upper_bound(card,1024)
    if monthly_total(s,c.tenant_id,utc(a.scheduled_at))+bound>t.monthly_budget_micro:return ['MONTHLY_REVIEW_BUDGET_EXCEEDED']
    worker_policy(s,c,p.id)
    review=Task(id=uid(),tenant_id=c.tenant_id,agent_id='A21',title='Semantic review',brief='No external fact verification',
        content_brief=task.content_brief,status='DRAFT',agent_run={'writer_task_id':task.id,'draft_sha256':hashed(draft),'policy_hash':p.terms_hash,'review_version':'a21-semantic-1'})
    s.add(review);s.flush();s.add(AutomationAttempt(id=uid(),tenant_id=c.tenant_id,slot_id=a.id,task_id=review.id,kind='SEMANTIC',ordinal=ordinal))
    task.agent_run={**(task.agent_run or {}),'semantic_task_id':review.id,'draft_sha256':hashed(draft),'policy_hash':p.terms_hash}
    reserve_funds(s,c,review.id,ReserveRequest(estimate_usd=dollars(bound),idempotency_key=review.id,rate_version=rate_id(card)))
    claim(s,c,review.id,commit=False);s.commit()
    try:
        prompt=review_prompt(draft,p.terms,p.terms_hash);provider.check_offline()
        if provider.count_tokens(prompt)>card['max_input_tokens']:raise ProviderFailure('SEMANTIC_INPUT_CAP',unknown=False)
        provider.generation_request_id=review.id;receipt=provider.generate(prompt,1024)
        lock_tenant(s,c.tenant_id)
        source='MOCK_SEMANTIC' if receipt.get('evidence_origin')=='MOCK_HTTP' else 'PROVIDER_REPORTED_UNVERIFIED'
        settle_receipt(s,c,review.id,review.id,receipt,source,commit=False)
        if not receipt.get('output_valid') or receipt.get('unpriced_features') or receipt.get('usage_exceeds_limits'):
            review.status='RECONCILIATION_REQUIRED';review.receipt_status=ReceiptStatus.RECONCILIATION_REQUIRED
            if receipt.get('unpriced_features') or receipt.get('usage_exceeds_limits'):lock_tenant(s,c.tenant_id).budget_paused=True
    except Exception as exc:
        s.rollback();lock_tenant(s,c.tenant_id)
        failed=s.get(Task,review.id,populate_existing=True)
        if failed and not failed.settle_key:
            failed.status='RECONCILIATION_REQUIRED';failed.receipt_status=ReceiptStatus.RECONCILIATION_REQUIRED
            failed.receipt_source='MOCK_SEMANTIC' if provider.synthetic_only else 'PROVIDER_REPORTED_UNVERIFIED'
            failed.agent_run={**(failed.agent_run or {}),'outcome':'RECONCILIATION_REQUIRED',
                'error_category':exc.category if isinstance(exc,ProviderFailure) else 'LOCAL_REVIEW_FAILURE',
                'request_id':provider.last_request_id,'response_id':provider.last_response_id}
            audit(s,c.tenant_id,'automation.semantic_unknown',review.id,c.id);s.commit()
        raise

    return semantic_issues(s,task,draft,p,t)



def generate_slot(s: Session,c: Credential,p: AutomationPolicy,a: AutomationSlot,provider: LLMProvider) -> None:
    from .main import reserve_funds,ReserveRequest,dollars,claim,settle_receipt,lock_tenant
    from .revisions import ensure_original
    t=Terms.model_validate(p.terms)
    if os.getenv('MOS_MODEL_CALLS_ENABLED','false')!='true':
        a.state='BLOCKED';a.error='MODEL_CALLS_DISABLED';s.commit();return
    ordinal=s.scalar(select(func.count()).select_from(AutomationAttempt).where(AutomationAttempt.tenant_id==c.tenant_id,AutomationAttempt.slot_id==a.id,AutomationAttempt.kind=='WRITE')) or 0
    if ordinal>t.max_rewrites:a.state='REVIEW_REQUIRED';a.error='REWRITE_LIMIT_REACHED';s.commit();return
    prior=s.scalars(select(AutomationSlot).where(AutomationSlot.tenant_id==c.tenant_id,AutomationSlot.scheduled_at>=now()-timedelta(days=30))).all()
    choices=[x for x in t.topics if hashed({'brand':t.brief.brand.name,'topic':x.casefold()}) not in {r.topic_hash for r in prior}]
    previous=s.get(Task,a.task_id) if a.task_id else None
    if not choices and not previous:a.state='SKIPPED';a.error='NO_NEW_TOPIC';s.commit();return
    topic=previous.title if previous else choices[0];a.topic_hash=hashed({'brand':t.brief.brand.name,'topic':topic.casefold()})
    guidance=('Write original non-factual questions and invitations plus ONLY the exact owner fact statements. Do not invent any factual premise. Owner knowledge: '+json.dumps([f.model_dump() for f in t.knowledge_facts],ensure_ascii=False)) if t.creative_mode=='BRAND_GUIDED' else 'Only use these owner-approved copy blocks, one per line: '+json.dumps(t.approved_copy,ensure_ascii=False)
    brief=t.brief.model_copy(update={'topic':topic})
    # Keep the original brief validation and selected industry loader, not a second brand store.
    payload=brief.request(uid());payload=payload.model_copy(update={'brief':topic+' '+brief.supplementary[:900]})
    card=MODEL if t.model=='mock-a09-v1' else CARDS[t.model]
    if previous:guidance+=' Rewrite ordinal '+str(ordinal)+'; correct previous issues: '+json.dumps((previous.agent_run or {}).get('quality_reasons',[]))
    prompt=guidance+'\n'+build_prompt(payload,c.tenant_id)
    if isinstance(provider,MockLLMProvider):
        bound=usage_cost({'input_tokens':provider.count_tokens(prompt),'output_tokens':1024},card)
    elif isinstance(provider,OpenAIProvider):bound=upper_bound(card,1024)
    else:raise HTTPException(503,'PROVIDER_NOT_CONFIGURED')
    extra=upper_bound(CARDS[t.semantic_model],1024) if t.creative_mode=='BRAND_GUIDED' and t.semantic_reviewer=='MODEL_REQUIRED' else 0
    if monthly_total(s,c.tenant_id,utc(a.scheduled_at))+bound+extra>t.monthly_budget_micro:
        a.state='BLOCKED';a.error='MONTHLY_BUDGET_EXCEEDED';s.commit();return
    task=Task(id=payload.task_id,tenant_id=c.tenant_id,agent_id='A09',title=topic,brief=topic,content_brief=brief.model_dump(),status='DRAFT',agent_run={'automation_policy_id':p.id,'policy_hash':p.terms_hash,'prompt_hash':hashed({'prompt':prompt}),'prompt_version':'a09-1','rewrite_ordinal':ordinal})
    s.add(task);s.flush();s.add(AutomationAttempt(id=uid(),tenant_id=c.tenant_id,slot_id=a.id,task_id=task.id,kind='WRITE',ordinal=ordinal))
    a.task_id=task.id;a.state='GENERATING';a.started_at=now()
    reserve_funds(s,c,task.id,ReserveRequest(estimate_usd=dollars(bound),idempotency_key=task.id,rate_version=rate_id(card)))
    claim(s,c,task.id,commit=False);s.commit()
    try:
        worker_policy(s,c,p.id);s.commit()
        if isinstance(provider,OpenAIProvider):
            provider.check_offline()
            if provider.count_tokens(prompt)>card['max_input_tokens']:raise RuntimeError('Input limit')
            provider.generation_request_id=task.id
        receipt=provider.generate(prompt,1024)
        lock_tenant(s,c.tenant_id);loaded=s.get(Task,a.task_id,populate_existing=True)
        if loaded is None:raise RuntimeError('Task missing')
        task=loaded
        draft,checked=qa(receipt['output'],context(task))
        receipt={**receipt,'request_context':payload.model_dump(),'draft':draft.model_dump() if draft else {},'prompt_version':'a09-1'}
        source='MOCK_HTTP' if isinstance(provider,OpenAIProvider) and receipt.get('evidence_origin')=='MOCK_HTTP' else 'PROVIDER_REPORTED_UNVERIFIED' if isinstance(provider,OpenAIProvider) else 'MOCK'
        settle_receipt(s,c,task.id,task.id,receipt,source,commit=False)
        record=ensure_original(s,task,c);a.revision_id=record.id;task.output=record.after_text
        issues=auto_qa(record.draft,t)
        if checked.passed and not issues and t.creative_mode=='BRAND_GUIDED':issues+=review_draft(s,c,p,a,task,record.draft,t,ordinal)
        same_slot=list(s.scalars(select(AutomationAttempt.task_id).where(AutomationAttempt.tenant_id==c.tenant_id,AutomationAttempt.slot_id==a.id)))
        recent=s.scalars(select(Task).where(Task.tenant_id==c.tenant_id,Task.id.not_in(same_slot),Task.agent_id=='A09',Task.created_at>=now()-timedelta(days=30),Task.output.is_not(None))).all()
        if any(difflib.SequenceMatcher(None,task.output or '',other.output or '').ratio()>=.92 for other in recent):issues.append('DUPLICATE_CONTENT')
        if not checked.passed or issues or task.status=='RECONCILIATION_REQUIRED':
            a.state='REVIEW_REQUIRED';a.error=','.join(checked.reasons+issues)[:80] or 'BILLING_RECONCILIATION_REQUIRED'
        else:a.state='WAITING_APPROVAL' if t.mode in {'REVIEW','MANUAL'} else 'SCHEDULED'
        task.agent_run={**(task.agent_run or {}),'quality_reasons':issues,'prompt_version':'a09-1','rewrite_ordinal':ordinal}
        audit(s,c.tenant_id,'automation.generated',a.id,c.id);s.commit()
        retryable=(checked.reasons+issues) and not any('BUDGET' in x or 'HUMAN_' in x or 'RECONCILIATION' in x or x=='SEMANTIC_REVIEW_REQUIRED' for x in issues)
        if a.state=='REVIEW_REQUIRED' and retryable and ordinal<t.max_rewrites:
            worker_policy(s,c,p.id);a.state='CREATED';a.error=None;s.commit();generate_slot(s,c,p,a,provider)
    except Exception:
        s.rollback();lock_tenant(s,c.tenant_id);loaded_slot=s.get(AutomationSlot,a.id,populate_existing=True)
        if loaded_slot:
            a=loaded_slot
            a.state='RECONCILIATION_REQUIRED';a.error='UNKNOWN_GENERATION_NO_RETRY'
            failed_task=s.get(Task,a.task_id)
            if failed_task and not failed_task.settle_key:failed_task.status='RECONCILIATION_REQUIRED';failed_task.receipt_status=ReceiptStatus.RECONCILIATION_REQUIRED
            audit(s,c.tenant_id,'automation.unknown_generation',a.id,c.id);s.commit()


def generation_provider(p: AutomationPolicy) -> LLMProvider:
    if p.terms['model']=='mock-a09-v1':
        if os.getenv('MOS_ENV') not in {'development','test'}:raise HTTPException(403,'MOCK_OFFLINE_ONLY')
        return MockLLMProvider()
    from .automation_provider import AutomationOpenAIProvider
    provider=AutomationOpenAIProvider(p);provider.check_offline();return provider


def process_slot(s: Session,c: Credential,p: AutomationPolicy,a: AutomationSlot,client: ThreadsAPI) -> None:
    from .main import lock_tenant
    from . import threads_publisher as publisher
    t=Terms.model_validate(p.terms)
    if a.state=='GENERATING':
        if a.started_at and now()-utc(a.started_at)>timedelta(seconds=60):
            a.state='RECONCILIATION_REQUIRED';a.error='WORKER_INTERRUPTED_NO_RETRY';s.commit()
        return
    if a.state in {'RECONCILIATION_REQUIRED','BLOCKED','SKIPPED','MISSED','REVIEW_REQUIRED','PUBLISHED'}:return
    if a.state=='CREATED':
        try:provider=generation_provider(p)
        except ProviderFailure as exc:
            a.state='BLOCKED';a.error=exc.category;s.commit();return
        generate_slot(s,c,p,a,provider)
    worker_policy(s,c,p.id)
    if a.state not in {'SCHEDULED','WAITING_APPROVAL','DISPATCHING'} or now()<utc(a.scheduled_at):return
    if not a.revision_id or not a.task_id:return
    task=s.get(Task,a.task_id,populate_existing=True)
    if t.mode=='MANUAL':return
    if t.mode=='REVIEW' and (not task or task.approved_revision_id!=a.revision_id):return
    if not a.publication_id:
        record=revision_for(s,c.tenant_id,a.task_id,a.revision_id)
        ppub=Publication(id=uid(),tenant_id=c.tenant_id,task_id=a.task_id,platform='threads',idempotency_key='automation:'+a.id,
            revision_id=record.id,content_snapshot=record.after_text,status='MANUAL_REQUIRED',publish_status='MANUAL_REQUIRED')
        a.publication_id=ppub.id;s.flush();ppub.automation_policy_id=p.id
        s.add(ppub);s.flush();ppub.platform_account_id=t.connection_id;ppub.immutable_content_hash=publisher.content_hash(record.after_text)
        publication_authority(s,c,ppub);ppub.publish_status='APPROVED';s.flush();ppub.publish_status='READY_TO_PUBLISH'
        a.state='DISPATCHING';audit(s,c.tenant_id,'automation.policy_publication',ppub.id,c.id);s.commit()
    ppub=publisher.publication_for(s,c.tenant_id,a.publication_id)
    if ppub.publish_status in {'CREATING_CONTAINER','PUBLISHING'}:
        publisher.recover_publications(s,c);s.commit();return
    if ppub.publish_status in {'RESULT_UNKNOWN','RECONCILIATION_REQUIRED'}:
        a.state='RECONCILIATION_REQUIRED';a.error='UNKNOWN_PUBLICATION_NO_RETRY';s.commit();return
    if not ppub.published_media_id:publisher.execute(ppub.id,c,s,client)
    elif ppub.verification_status not in {'OFFICIAL_READBACK_VERIFIED','MOCK_READBACK_PASSED'}:publisher.readback(s,c,ppub,client)
    lock_tenant(s,c.tenant_id);ppub=publisher.publication_for(s,c.tenant_id,ppub.id)
    a.state='PUBLISHED' if ppub.verification_status in {'OFFICIAL_READBACK_VERIFIED','MOCK_READBACK_PASSED'} else 'DISPATCHING' if ppub.publish_status=='CONTAINER_CREATED' else 'RECONCILIATION_REQUIRED'
    a.error=ppub.last_error_category;s.commit()


@router.post('/tick')
def tick(c: Credential=Depends(require('automation')),s: Session=Depends(db),client: ThreadsAPI=Depends(api)) -> dict:
    from .main import lock_tenant
    allowed=[x[7:] for x in c.scopes if x.startswith('policy:')]
    if len(allowed)!=1:raise HTTPException(403,'ONE_POLICY_WORKER_REQUIRED')
    p=worker_policy(s,c,allowed[0]);t=Terms.model_validate(p.terms)
    if client.source!='MOCK':
        from .live_transport import require_execution_release
        require_execution_release()
    if t.mode=='MANUAL':return {'processed':0,'state':'MANUAL'}
    conn=connection(s,c.tenant_id,t.connection_id)
    if utc(conn.token_expires_at)<now()+timedelta(days=7) and now()-utc(conn.token_issued_at)>=timedelta(hours=24):
        if conn.maintenance_error=='MAINTENANCE_IN_PROGRESS':raise HTTPException(409,'REFRESH_RESULT_UNKNOWN')
        conn.maintenance_error='MAINTENANCE_IN_PROGRESS';s.commit();worker_policy(s,c,p.id)
        try:refresh_connection(conn,client);audit(s,c.tenant_id,'automation.token_refreshed',conn.id,c.id);s.commit()
        except Exception:
            s.rollback();lock_tenant(s,c.tenant_id);conn=connection(s,c.tenant_id,t.connection_id)
            connection_failure(s,c,conn,'REFRESH_FAILED_OR_UNKNOWN');s.commit();raise HTTPException(409,'ACCOUNT_REFRESH_STOPPED') from None
    for old in s.scalars(select(AutomationSlot).where(AutomationSlot.tenant_id==c.tenant_id,AutomationSlot.policy_id==p.id,AutomationSlot.scheduled_at<now()-timedelta(minutes=3))):
        if old.state in {'CREATED','SCHEDULED','WAITING_APPROVAL'}:old.state='MISSED';old.error='NO_CATCH_UP'
        elif old.state in {'GENERATING','DISPATCHING'}:old.state='RECONCILIATION_REQUIRED';old.error='WORKER_INTERRUPTED_NO_RETRY'
    s.commit();worker_policy(s,c,p.id)
    local=now().astimezone(TAIPEI);today=local.date()
    if today.weekday() not in t.weekdays:return {'processed':0,'state':'OUTSIDE_WEEKDAY'}
    for value in sorted(t.times)[:t.daily_max]:
        worker_policy(s,c,p.id)
        scheduled=datetime.combine(today,time.fromisoformat(value),TAIPEI).astimezone(timezone.utc)
        if not t.starts_at<=scheduled<t.expires_at or now()<scheduled-timedelta(minutes=10):continue
        a=s.scalar(select(AutomationSlot).where(AutomationSlot.tenant_id==c.tenant_id,AutomationSlot.policy_id==p.id,AutomationSlot.scheduled_at==scheduled))
        if not a:
            start=datetime.combine(today,time(),TAIPEI)
            daily=s.scalar(select(func.count()).select_from(AutomationSlot).join(AutomationPolicy,AutomationPolicy.id==AutomationSlot.policy_id).where(
                AutomationSlot.tenant_id==c.tenant_id,AutomationSlot.scheduled_at>=start,AutomationSlot.scheduled_at<start+timedelta(days=1),
                AutomationPolicy.terms_hash.is_not(None))) or 0
            if daily>=t.daily_max:continue
            a=AutomationSlot(id=uid(),tenant_id=c.tenant_id,policy_id=p.id,scheduled_at=scheduled,state='CREATED')
            s.add(a);s.flush()
        if now()>scheduled+timedelta(minutes=3):
            if a.state not in {'PUBLISHED','RECONCILIATION_REQUIRED'}:a.state='MISSED';a.error='NO_CATCH_UP';s.commit()
            continue
        unknown=s.scalar(select(AutomationSlot.id).where(AutomationSlot.tenant_id==c.tenant_id,AutomationSlot.id!=a.id,AutomationSlot.state.in_(['RECONCILIATION_REQUIRED','GENERATING'])))
        if unknown:raise HTTPException(409,'ACCOUNT_UNKNOWN_RESULT_FREEZE')
        process_slot(s,c,p,a,client)
    return {'processed':1,'policy_id':p.id,'live_execution':False}

@router.get('/slots/{sid}/attempts')
def attempt_history(sid: str,c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    slot=s.scalar(select(AutomationSlot).where(AutomationSlot.tenant_id==c.tenant_id,AutomationSlot.id==sid))
    if slot is None:raise HTTPException(404,'SLOT_NOT_FOUND')
    records=s.scalars(select(AutomationAttempt).where(AutomationAttempt.tenant_id==c.tenant_id,AutomationAttempt.slot_id==sid).order_by(AutomationAttempt.created_at,AutomationAttempt.id)).all()
    result=[]
    for a in records:
        task=s.get(Task,a.task_id)
        result.append({'task_id':a.task_id,'kind':a.kind,'ordinal':a.ordinal,'created_at':utc(a.created_at),'policy_id':slot.policy_id,
            'revision_id':task.latest_revision_id if task else None,'cost_micro':task.actual_micro if task else None,
            'receipt_source':task.receipt_source if task else None,'receipt_status':task.receipt_status if task else None,'reserved_micro':task.reserved_micro if task else None,'task_status':task.status if task else None,
            'review':task.receipt.get('semantic_review') if task and task.receipt else None,'provenance':task.agent_run if task else None})
    return {'attempts':result,'external_fact_verification':False}
