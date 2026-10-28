"""Gemini controls over the existing policy, encrypted key and single-test records."""
import copy
import hashlib
import os
from datetime import timedelta
import httpx
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,ConfigDict,SecretStr,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import db
from .models import AITestPermit,AutomationPolicy,Credential,Tenant,RateVersion,now
from .security import require,audit,uid
from .threads_api import unseal
from .threads_routes import owner
from .browser_session import transport_allowed
from .automation import policy_for,Terms,policy_view
from .gemini_provider import GeminiProvider,CARD,MODEL_ID
from .openai_provider import ProviderFailure
from .providers import rate_id
from .durable_gate import utc
from .revisions import hashed

router=APIRouter(prefix='/automation/policies')


class Verification(BaseModel):
    model_config=ConfigDict(extra='forbid')
    verification_access_token: SecretStr=Field(min_length=20,max_length=4096)


class Consent(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    confirm_one_generation_only: bool
    idempotency_key: str=Field(min_length=8,max_length=128)


def secret(p: AutomationPolicy) -> str:
    if not p.key_ciphertext:raise ProviderFailure('PROVIDER_KEY_MISSING',unknown=False)
    return unseal(p.key_ciphertext,p.tenant_id,'automation-key:'+p.id)


def fingerprint(p: AutomationPolicy) -> str:
    return hashlib.sha256(secret(p).encode()).hexdigest()


def provider_for(p: AutomationPolicy,token: str='') -> GeminiProvider:
    from .database import SessionLocal,scope
    with SessionLocal() as s:
        scope(s,p.tenant_id);config=latest(s,p,'GEMINI_CONFIGURATION')
        if not config:return GeminiProvider(secret(p),'','',token)
        return GeminiProvider(secret(p),config.terms['project_id'],config.terms['key_resource'],token)


def owned(s: Session,c: Credential,pid: str) -> AutomationPolicy:
    owner(c);p=policy_for(s,c.tenant_id,pid)
    if p.owner_id!=c.id or p.state!='DRAFT' or p.terms['model']!=MODEL_ID:raise HTTPException(409,'GEMINI_OWN_DRAFT_REQUIRED')
    return p


def latest(s: Session,p: AutomationPolicy,kind: str) -> AITestPermit | None:
    return s.scalar(select(AITestPermit).where(AITestPermit.tenant_id==p.tenant_id,AITestPermit.terms['kind'].as_string()==kind,
        AITestPermit.terms['policy_id'].as_string()==p.id,AITestPermit.state!='REVOKED').order_by(AITestPermit.created_at.desc()))


def connection_valid(record: AITestPermit | None,p: AutomationPolicy,s: Session) -> bool:
    config=latest(s,p,'GEMINI_CONFIGURATION')
    return bool(record and record.state=='REQUESTED' and (record.outcome or {}).get('connection_verified') is True and record.terms.get('policy_hash')==p.terms_hash and config and record.terms.get('configuration_id')==config.id
        and record.terms.get('key_fingerprint')==fingerprint(p) and utc(record.created_at)+timedelta(minutes=10)>now())


@router.post('/{pid}/gemini-copy',status_code=201)
def copy_policy(pid: str,c: Credential=Depends(require('credentials')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    owner(c);lock_tenant(s,c.tenant_id);original=policy_for(s,c.tenant_id,pid);terms=copy.deepcopy(original.terms)
    terms.update(model=MODEL_ID,semantic_model=MODEL_ID,execution_mode='OFFLINE',live_ai_test_id=None,live_publication_id=None)
    terms['brief']['constraints']['max_chars']=min(480,terms['brief']['constraints']['max_chars'])
    terms=Terms.model_validate(terms).model_dump(mode='json')
    p=AutomationPolicy(id=uid(),tenant_id=c.tenant_id,owner_id=c.id,terms=terms,terms_hash=hashed(terms),state='DRAFT')
    s.add(p);audit(s,c.tenant_id,'gemini.brand_copied',p.id,c.id);s.commit();return policy_view(p)


class Project(BaseModel):
    model_config=ConfigDict(extra='forbid')
    project_id: str=Field(pattern=r'^[a-z][a-z0-9-]{4,28}[a-z0-9]$')
    key_resource: str=Field(pattern=r'^projects/[0-9]{1,30}/locations/global/keys/[A-Za-z0-9_-]{1,100}$')


@router.post('/{pid}/gemini-project')
def project(pid: str,body: Project,request: Request,c: Credential=Depends(require('credentials')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    transport_allowed(request);lock_tenant(s,c.tenant_id);p=owned(s,c,pid)
    terms={'kind':'GEMINI_CONFIGURATION','policy_id':p.id,**body.model_dump()}
    r=AITestPermit(id=uid(),tenant_id=c.tenant_id,owner_id=c.id,terms=terms,terms_hash=hashed(terms),state='REQUESTED')
    s.add(r);audit(s,c.tenant_id,'gemini.project_configured',r.id,c.id);s.commit();return {'configured':True}


@router.get('/{pid}/gemini-status')
def status(pid: str,c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    p=policy_for(s,c.tenant_id,pid)
    if p.terms['model']!=MODEL_ID:raise HTTPException(409,'GEMINI_POLICY_REQUIRED')
    config=latest(s,p,'GEMINI_CONFIGURATION')
    proof=latest(s,p,'GEMINI_CONNECTION');test=latest(s,p,'GEMINI_SINGLE_TEST');key_test=latest(s,p,'GEMINI_KEY_CHECK')
    verified=bool(p.key_ciphertext and connection_valid(proof,p,s))
    current=bool(proof and config and p.key_ciphertext and proof.terms.get('configuration_id')==config.id and proof.terms.get('policy_hash')==p.terms_hash
        and proof.terms.get('key_fingerprint')==fingerprint(p) and utc(proof.created_at)+timedelta(minutes=10)>now())
    eligibility='CONFIRMED' if verified else 'NOT_ELIGIBLE' if current and proof and (proof.outcome or {}).get('category')=='GEMINI_PAID_PROJECT_BLOCKED' else 'PENDING'
    return {'provider':'Google Gemini','model':MODEL_ID,'key_present':bool(p.key_ciphertext),'project_id':config.terms['project_id'] if config else '',
        'key_resource':config.terms['key_resource'] if config else '','free_tier_verified':verified,'verification_source':(proof.outcome or {}).get('source') if verified and proof else None,
        'verification_expires_at':(utc(proof.created_at)+timedelta(minutes=10)).isoformat() if verified and proof else None,
        'connection_status':'FREE_PROJECT_AND_MODEL_VERIFIED' if verified else 'FREE_TIER_NOT_VERIFIED','free_tier_status':eligibility,
        'key_connection':key_test.outcome if key_test and p.key_ciphertext and key_test.terms.get('key_fingerprint')==fingerprint(p) else None,
        'last_error':(proof.outcome or {}).get('category') if current and proof else None,'test_id':test.id if test else None,
        'test_state':test.state if test else 'NOT_RUN','test_result':test.outcome if test else None,
        'generation_enabled':os.getenv('MOS_GEMINI_FREE_CALLS_ENABLED','false')=='true',
        'threads_publication_authorized':False}


@router.post('/{pid}/gemini-projects')
def projects(pid: str,body: Verification,request: Request,c: Credential=Depends(require('credentials')),s: Session=Depends(db)) -> dict:
    transport_allowed(request);p=owned(s,c,pid)
    return provider_for(p,body.verification_access_token.get_secret_value()).projects()


class Discovery(Verification):
    project_id: str=Field(pattern=r'^[a-z][a-z0-9-]{4,28}[a-z0-9]$')


@router.post('/{pid}/gemini-discover')
def discover(pid: str,body: Discovery,request: Request,c: Credential=Depends(require('credentials')),s: Session=Depends(db)) -> dict:
    from .limits import consume
    transport_allowed(request);p=owned(s,c,pid)
    if not consume(s,'gemini-discovery:'+p.tenant_id+':'+c.id,5,300):raise HTTPException(429,'Rate limit exceeded')
    found=provider_for(p,body.verification_access_token.get_secret_value()).discover(body.project_id)
    project(pid,Project.model_validate(found),request,c,s)
    return check(pid,Verification(verification_access_token=body.verification_access_token),request,c,s)


@router.post('/{pid}/gemini-key-check')
def key_check(pid: str,request: Request,c: Credential=Depends(require('credentials')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    transport_allowed(request);lock_tenant(s,c.tenant_id);p=owned(s,c,pid)
    terms={'kind':'GEMINI_KEY_CHECK','policy_id':p.id,'key_fingerprint':fingerprint(p)}
    r=AITestPermit(id=uid(),tenant_id=c.tenant_id,owner_id=c.id,terms=terms,terms_hash=hashed(terms),state='REQUESTED')
    try:r.outcome=provider_for(p).model_access()
    except ProviderFailure as e:r.outcome={'category':e.category,'generation_called':False}
    s.add(r);audit(s,c.tenant_id,'gemini.key_connection_checked',r.id,c.id);s.commit();return status(pid,c,s)


@router.post('/{pid}/gemini-check')
def check(pid: str,body: Verification,request: Request,c: Credential=Depends(require('credentials')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    transport_allowed(request);lock_tenant(s,c.tenant_id);p=owned(s,c,pid)
    config=latest(s,p,'GEMINI_CONFIGURATION')
    if not config:raise HTTPException(409,'GEMINI_PROJECT_CONFIGURATION_REQUIRED')
    r=AITestPermit(id=uid(),tenant_id=c.tenant_id,owner_id=c.id,terms={'kind':'GEMINI_CONNECTION','configuration_id':config.id,'policy_id':p.id,'policy_hash':p.terms_hash,
        'key_fingerprint':fingerprint(p),'model':MODEL_ID},terms_hash=p.terms_hash,state='REQUESTED')
    s.add(r);s.commit()
    try:
        result=provider_for(p,body.verification_access_token.get_secret_value()).connection()
        r.outcome=result
    except ProviderFailure as e:r.outcome={'category':e.category,'generation_called':False}
    audit(s,c.tenant_id,'gemini.connection_checked',r.id,c.id);s.commit();return status(pid,c,s)


@router.post('/{pid}/gemini-test',status_code=201)
def permit(pid: str,body: Consent,request: Request,c: Credential=Depends(require('budget')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    from .single_ai_test import view
    transport_allowed(request);lock_tenant(s,c.tenant_id);p=owned(s,c,pid)
    if not body.confirm_one_generation_only:raise HTTPException(403,'GEMINI_EXPLICIT_TEST_CONSENT_REQUIRED')
    previous=s.scalar(select(AITestPermit).where(AITestPermit.tenant_id==c.tenant_id,AITestPermit.terms['kind'].as_string()=='GEMINI_SINGLE_TEST',
        AITestPermit.terms['idempotency_key'].as_string()==body.idempotency_key))
    if previous:
        if previous.terms.get('policy_id')!=pid or previous.owner_id!=c.id:raise HTTPException(409,'GEMINI_IDEMPOTENCY_CONFLICT')
        return view(previous)
    proof=latest(s,p,'GEMINI_CONNECTION')
    if not connection_valid(proof,p,s):raise HTTPException(409,'GEMINI_FREE_TIER_NOT_VERIFIED')
    terms={'kind':'GEMINI_SINGLE_TEST','policy_id':p.id,'policy_hash':p.terms_hash,'brief':p.terms['brief'],'model':MODEL_ID,
        'key_fingerprint':fingerprint(p),'configuration_id':proof.terms['configuration_id'] if proof else None,'maximum_input_tokens':4096,'maximum_output_tokens':1024,'maximum_micro_usd':0,
        'deadline':(now()+timedelta(minutes=10)).isoformat(),'rate_snapshot':copy.deepcopy(CARD),'rate_version':rate_id(CARD),
        'reserved_upper_bound_micro':1,'maximum_generations':1,'maximum_count_requests':1,'idempotency_key':body.idempotency_key}
    record=AITestPermit(id=uid(),tenant_id=c.tenant_id,owner_id=c.id,terms=terms,terms_hash=hashed(terms),state='APPROVED')
    record.approval={'confirm_one_generation_only':True,'terms_hash':record.terms_hash,'count_endpoint_confirmed_free':True,
        'source':'OWNER_FREE_TEST_CONSENT','connection_evidence_id':proof.id if proof else None}
    if not s.get(RateVersion,rate_id(CARD)):raise HTTPException(503,'GEMINI_RATE_NOT_INSTALLED')
    s.add(record);audit(s,c.tenant_id,'gemini.single_test_consented',record.id,c.id);s.commit();return view(record)


class SingleGeminiProvider(GeminiProvider):
    def __init__(self,p: AITestPermit,s: Session,token: str) -> None:
        policy=policy_for(s,p.tenant_id,p.terms['policy_id']);base=provider_for(policy,token)
        super().__init__(base.key,base.project_id,base.key_resource,base.verification_token,base.transport)
        self.permit=p;self.session=s

    def check_offline(self) -> None:
        super().check_offline();s=self.session;p=self.permit;s.refresh(p)
        policy=policy_for(s,p.tenant_id,p.terms['policy_id']);config=latest(s,policy,'GEMINI_CONFIGURATION');actor=s.get(Credential,p.owner_id,populate_existing=True);tenant=s.get(Tenant,p.tenant_id,populate_existing=True)
        free_enabled=os.getenv('MOS_GEMINI_FREE_CALLS_ENABLED','false')=='true'
        mock_enabled=self.synthetic_only and os.getenv('MOS_SINGLE_AI_TEST_ENABLED')=='true'
        if (not (free_enabled or mock_enabled) or os.getenv('MOS_THREADS_PUBLISH_ENABLED','false')!='false'
                or p.state not in {'APPROVED','DISPATCHING'} or p.terms['rate_snapshot']!=CARD or p.terms.get('policy_hash')!=policy.terms_hash
                or policy.state!='DRAFT' or not config or config.id!=p.terms.get('configuration_id') or p.terms.get('key_fingerprint')!=fingerprint(policy) or not p.approval or p.approval.get('terms_hash')!=p.terms_hash
                or not p.approval.get('confirm_one_generation_only') or utc(p.created_at)+timedelta(minutes=10)<=now()
                or not actor or actor.revoked or utc(actor.expires_at)<=now() or not tenant or tenant.disabled or tenant.budget_paused):
            raise ProviderFailure('GEMINI_SINGLE_TEST_GATE_CLOSED',unknown=False)
        unknown=s.scalar(select(AITestPermit.id).where(AITestPermit.tenant_id==p.tenant_id,AITestPermit.id!=p.id,AITestPermit.state.in_(['DISPATCHING','RECONCILIATION_REQUIRED'])))
        if unknown:raise ProviderFailure('UNKNOWN_AI_TEST_RESULT_FREEZE',unknown=False)

    def request(self,path: str,payload: dict) -> dict:
        from .models import Task
        self.check_offline();p=self.permit;task=self.session.get(Task,p.task_id) if p.task_id else None
        request=payload.get('generateContentRequest',payload)
        prompt=request.get('contents',[{}])[0].get('parts',[{}])[0].get('text')
        expected=self.payload(prompt,1024) if isinstance(prompt,str) else {}
        if path=='countTokens':expected={'generateContentRequest':{'model':'models/'+self.model,**expected}}
        if (p.state!='DISPATCHING' or p.request_count!=1 or not task or task.status!='RUNNING' or task.settle_key
                or (task.agent_run or {}).get('prompt_hash')!=hashed({'prompt':prompt}) or payload!=expected):
            raise ProviderFailure('GEMINI_PERSISTED_REQUEST_REQUIRED',unknown=False)
        return super().request(path,payload)


class AutomationGeminiProvider(GeminiProvider):
    def __init__(self,p: AutomationPolicy,transport: httpx.MockTransport | None=None) -> None:
        base=provider_for(p,os.getenv('MOS_GOOGLE_READONLY_ACCESS_TOKEN',''))
        super().__init__(base.key,base.project_id,base.key_resource,base.verification_token,transport)
        self.policy=p

    def check_offline(self) -> None:
        super().check_offline()
        if self.synthetic_only:return
        from .automation_provider import automation_context
        automation_context(self.policy)

    def request(self,path: str,payload: dict) -> dict:
        from .database import SessionLocal,scope
        from .models import Task,Audit
        from .providers import rate_id
        self.check_offline()
        if not self.synthetic_only:
            with SessionLocal() as s:
                scope(s,self.policy.tenant_id);task=s.get(Task,self.generation_request_id) if self.generation_request_id else None
                issuer=s.scalar(select(Audit.actor_id).where(Audit.tenant_id==self.policy.tenant_id,Audit.resource_id==self.generation_request_id,Audit.action=='task.claimed'))
                worker=s.get(Credential,issuer) if issuer else None
                body=payload.get('generateContentRequest',payload);prompt=body.get('contents',[{}])[0].get('parts',[{}])[0].get('text')
                expected=self.payload(prompt,1024) if isinstance(prompt,str) else {}
                if path=='countTokens':expected={'generateContentRequest':{'model':'models/'+self.model,**expected}}
                if (not task or task.status!='RUNNING' or task.settle_key or not task.expires_at or utc(task.expires_at)<=now()
                        or not worker or worker.role!='automation_worker' or worker.revoked or utc(worker.expires_at)<=now()
                        or 'policy:'+self.policy.id not in worker.scopes or worker.environment!=os.getenv('MOS_ENV')
                        or (task.agent_run or {}).get('automation_policy_id')!=self.policy.id or (task.agent_run or {}).get('policy_hash')!=self.policy.terms_hash
                        or (task.agent_run or {}).get('prompt_hash')!=hashed({'prompt':prompt}) or task.rate_snapshot!=CARD or payload!=expected):
                    raise ProviderFailure('GEMINI_PERSISTED_REQUEST_REQUIRED',unknown=False)
        return super().request(path,payload)
