"""One explicitly approved generation, using existing rate snapshots and Tenant Ledger only."""
import os
from datetime import timedelta
import httpx
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field,AwareDatetime,SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import db
from .models import AITestPermit,Credential,Task,ReceiptStatus,now
from .security import require,admin,uid,audit
from .threads_routes import owner
from .content_workbench import Brief
from .agent_runtime import build_prompt,qa
from .revisions import hashed
from .openai_provider import OpenAIProvider,CARDS,upper_bound,ProviderFailure
from .providers import rate_id
from .durable_gate import utc

router=APIRouter()


class TestTerms(BaseModel):
    model_config=ConfigDict(extra='forbid')
    brief: Brief
    model: str=Field(pattern='^gpt-6-luna$')
    account_id: str=Field(pattern='^org-[A-Za-z0-9_-]{4,80}$')
    project_id: str=Field(pattern='^proj_[A-Za-z0-9_-]{4,80}$')
    maximum_input_tokens: int=Field(ge=1,le=4096,strict=True)
    maximum_output_tokens: int=Field(ge=32,le=1024,strict=True)
    maximum_micro_usd: int=Field(ge=1,le=10000,strict=True)
    deadline: AwareDatetime


class Approve(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    terms_hash: str
    user_consent_evidence_sha256: str=Field(pattern='^[a-f0-9]{64}$')
    account_access_evidence_sha256: str=Field(pattern='^[a-f0-9]{64}$')
    cost_bound_evidence_sha256: str=Field(pattern='^[a-f0-9]{64}$')
    count_endpoint_confirmed_free: bool
    confirm_one_generation_only: bool


def permit_for(s: Session,tid: str,pid: str) -> AITestPermit:
    p=s.scalar(select(AITestPermit).where(AITestPermit.tenant_id==tid,AITestPermit.id==pid).execution_options(populate_existing=True))
    if p is None:raise HTTPException(404,'AI_TEST_NOT_FOUND')
    return p


def view(p: AITestPermit) -> dict:
    return {'id':p.id,'terms':p.terms,'terms_hash':p.terms_hash,'state':p.state,'request_count':p.request_count,
        'task_id':p.task_id,'outcome':p.outcome,'approval_source':p.approval.get('source','OWNER_AND_ADMIN_ATTESTATION') if p.approval else None,
        'invoice_verified':False,'threads_publication_authorized':False}


@router.post('/ai-tests',status_code=201)
def create(body: TestTerms,c: Credential=Depends(require('budget')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    owner(c);lock_tenant(s,c.tenant_id)
    if not now()<body.deadline<=min(now()+timedelta(minutes=30),utc(c.expires_at)):raise HTTPException(422,'AI_TEST_DEADLINE_INVALID')
    card=CARDS[body.model];bound=upper_bound(card,body.maximum_output_tokens)
    if bound>body.maximum_micro_usd:raise HTTPException(402,'AI_TEST_COST_BOUND_EXCEEDS_CAP')
    terms={**body.model_dump(mode='json'),'rate_snapshot':dict(card),'rate_version':rate_id(card),'reserved_upper_bound_micro':bound,
        'maximum_generations':1,'maximum_count_requests':1,'tools':[],'service_tier':'default'}
    pid=uid();p=AITestPermit(id=pid,tenant_id=c.tenant_id,owner_id=c.id,terms=terms,terms_hash=hashed({'permit_id':pid,'terms':terms}),state='REQUESTED')
    s.add(p);audit(s,c.tenant_id,'ai_test.requested',p.id,c.id);s.commit();return view(p)


@router.post('/admin/ai-tests/{pid}/approve',dependencies=[Depends(admin)])
def approve(pid: str,body: Approve,c: Credential=Depends(require('budget')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    owner(c);lock_tenant(s,c.tenant_id);p=permit_for(s,c.tenant_id,pid)
    if p.terms.get('kind','').startswith('GEMINI_'):raise HTTPException(403,'GEMINI_REQUIRES_ITS_OWN_EXPLICIT_CONSENT')
    if p.owner_id!=c.id or p.terms_hash!=body.terms_hash or not body.confirm_one_generation_only or not body.count_endpoint_confirmed_free or utc(TestTerms.model_validate({k:p.terms[k] for k in TestTerms.model_fields}).deadline)<=now():
        raise HTTPException(403,'EXACT_SPEND_CONSENT_REQUIRED')
    proof=body.model_dump()
    if p.approval:
        if p.approval!=proof:raise HTTPException(409,'AI_TEST_APPROVAL_IMMUTABLE')
        return view(p)
    reused=s.scalar(select(AITestPermit.id).where(AITestPermit.tenant_id==c.tenant_id,AITestPermit.id!=p.id,AITestPermit.approval['user_consent_evidence_sha256'].as_string()==body.user_consent_evidence_sha256))
    if reused:raise HTTPException(409,'SPEND_CONSENT_ALREADY_USED')
    if p.state!='REQUESTED':raise HTTPException(409,'AI_TEST_NOT_APPROVABLE')
    p.approval=proof;p.state='APPROVED';audit(s,c.tenant_id,'ai_test.operator_approved',p.id,c.id);s.commit();return view(p)


@router.get('/ai-tests/{pid}')
def details(pid: str,c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    return view(permit_for(s,c.tenant_id,pid))


@router.post('/ai-tests/{pid}/revoke')
def revoke(pid: str,c: Credential=Depends(require('budget')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    owner(c);lock_tenant(s,c.tenant_id);p=permit_for(s,c.tenant_id,pid)
    if p.request_count:raise HTTPException(409,'AI_TEST_ALREADY_ADMITTED_NO_RETRY')
    p.state='REVOKED';audit(s,c.tenant_id,'ai_test.revoked',p.id,c.id);s.commit();return view(p)


class SingleTestProvider(OpenAIProvider):
    def __init__(self,p: AITestPermit,s: Session,transport: httpx.MockTransport | None=None) -> None:
        super().__init__(p.terms['model'],transport,snapshot=p.terms['rate_snapshot'],synthetic_only=type(transport) is httpx.MockTransport)
        self.permit=p;self.session=s;self.count_calls=0;self.generate_calls=0

    def context_headers(self) -> dict[str,str]:
        return {'OpenAI-Organization':self.permit.terms['account_id'],'OpenAI-Project':self.permit.terms['project_id']}

    def check_offline(self) -> None:
        from .models import Tenant,RateVersion
        p=self.permit;s=self.session;s.refresh(p)
        c=s.get(Credential,p.owner_id,populate_existing=True);tenant=s.get(Tenant,p.tenant_id,populate_existing=True)
        card=s.get(RateVersion,p.terms['rate_version'])
        try:proof=Approve.model_validate(p.approval or {})
        except ValueError:raise ProviderFailure('SPEND_PROOF_MISSING',unknown=False) from None
        if proof.terms_hash!=p.terms_hash or not proof.confirm_one_generation_only or not proof.count_endpoint_confirmed_free:raise ProviderFailure('SPEND_PROOF_MISMATCH',unknown=False)
        if (p.state not in {'APPROVED','DISPATCHING'} or not p.approval or not c or c.revoked or c.role!='owner' or utc(c.expires_at)<=now()
                or not tenant or tenant.disabled or tenant.budget_paused or tenant.spent_micro+tenant.reserved_micro>tenant.budget_micro or TestTerms.model_validate({k:p.terms[k] for k in TestTerms.model_fields}).deadline<=now()
                or os.getenv('MOS_SINGLE_AI_TEST_ENABLED','false')!='true' or os.getenv('MOS_MODEL_CALLS_ENABLED','false')!='true'
                or os.getenv('MOS_ENV')!='test' or os.getenv('MOS_THREADS_PUBLISH_ENABLED','false')!='false'
                or p.terms['rate_snapshot']!=CARDS.get(self.model) or not card or card.snapshot!=self.card):
            raise ProviderFailure('SINGLE_AI_TEST_GATE_CLOSED',unknown=False)
        pending=s.scalar(select(AITestPermit.id).where(AITestPermit.tenant_id==p.tenant_id,AITestPermit.id!=p.id,AITestPermit.state.in_(['DISPATCHING','RECONCILIATION_REQUIRED'])))
        if pending:raise ProviderFailure('UNKNOWN_AI_TEST_RESULT_FREEZE',unknown=False)
        if type(self.transport) is httpx.MockTransport:return
        if (os.getenv('CI') or os.getenv('PYTEST_CURRENT_TEST') or not os.getenv('OPENAI_API_KEY')
                or os.getenv('MOS_OPENAI_ACCOUNT_ID')!=p.terms['account_id'] or os.getenv('MOS_OPENAI_PROJECT_ID')!=p.terms['project_id']):
            raise ProviderFailure('SINGLE_AI_TEST_ACCOUNT_OR_ENVIRONMENT_DENIED',unknown=False)

    def request(self,path: str,payload: dict) -> tuple[dict,str | None]:
        self.check_offline()
        if self.permit.state!='DISPATCHING' or self.permit.request_count!=1:raise ProviderFailure('SINGLE_AI_TEST_NOT_ADMITTED',unknown=False)
        task=self.session.get(Task,self.permit.task_id)
        prompt=payload.get('input')
        if not task or not isinstance(prompt,str) or (task.agent_run or {}).get('prompt_hash')!=hashed({'prompt':prompt}):raise ProviderFailure('REQUEST_SNAPSHOT_MISMATCH',unknown=False)
        expected=self.payload(prompt,self.permit.terms['maximum_output_tokens'])
        if path=='responses/input_tokens':expected={k:expected[k] for k in ('model','input','text','tools','reasoning')}
        if payload!=expected:raise ProviderFailure('REQUEST_CAP_OR_SCHEMA_MISMATCH',unknown=False)
        if path=='responses/input_tokens':
            if self.count_calls:raise ProviderFailure('COUNT_ALREADY_ATTEMPTED',unknown=False)
            self.count_calls+=1
        elif path=='responses':
            if self.generate_calls or self.count_calls!=1:raise ProviderFailure('GENERATION_ALREADY_ATTEMPTED',unknown=False)
            self.generate_calls+=1
        else:raise ProviderFailure('ENDPOINT_NOT_ALLOWED',unknown=False)
        return super().request(path,payload)

    def payload(self,prompt: str,max_output_tokens: int) -> dict:
        body=super().payload(prompt,max_output_tokens);body.pop('prompt_cache_options',None);return body


def provider_for(p: AITestPermit,s: Session) -> SingleTestProvider:
    return SingleTestProvider(p,s)


class GeminiExecution(BaseModel):
    model_config=ConfigDict(extra='forbid')
    verification_access_token: SecretStr=Field(min_length=20,max_length=4096)


@router.post('/ai-tests/{pid}/execute')
def execute(pid: str,body: GeminiExecution | None=None,c: Credential=Depends(require('budget')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant,reserve_funds,ReserveRequest,dollars,claim,settle_receipt
    owner(c);lock_tenant(s,c.tenant_id);p=permit_for(s,c.tenant_id,pid)
    if p.state=='SETTLED':return view(p)
    if p.state!='APPROVED' or p.request_count or p.owner_id!=c.id:raise HTTPException(409,'AI_TEST_NOT_ADMISSIBLE_NO_RETRY')
    if p.terms.get('kind')=='GEMINI_SINGLE_TEST':
        from .gemini_policy import SingleGeminiProvider
        if not body:raise HTTPException(403,'GEMINI_FREE_TIER_NOT_VERIFIED')
        provider: SingleTestProvider | SingleGeminiProvider=SingleGeminiProvider(p,s,body.verification_access_token.get_secret_value())
    else:provider=provider_for(p,s)
    try:provider.check_offline();provider.authorization()
    except (ProviderFailure,KeyError):raise HTTPException(403,'SINGLE_AI_TEST_GATE_CLOSED') from None
    brief=Brief.model_validate(p.terms['brief']);payload=brief.request(uid());prompt=build_prompt(payload,c.tenant_id)
    task=Task(id=payload.task_id,tenant_id=c.tenant_id,agent_id='A09',title='Single controlled AI test',brief=brief.topic,content_brief=brief.model_dump(),status='DRAFT',agent_run={'single_ai_test':p.id,'prompt_version':'a09-1','prompt_hash':hashed({'prompt':prompt})})
    s.add(task);s.flush();p.task_id=task.id
    reserve_funds(s,c,task.id,ReserveRequest(estimate_usd=dollars(p.terms['reserved_upper_bound_micro']),idempotency_key=p.id,rate_version=p.terms['rate_version']))
    claim(s,c,task.id,commit=False);p.state='DISPATCHING';p.request_count=1;audit(s,c.tenant_id,'ai_test.admitted',p.id,c.id);s.commit()
    try:
        count=provider.count_tokens(prompt)
        if count>p.terms['maximum_input_tokens']:raise ProviderFailure('INPUT_TOKEN_CAP_EXCEEDED',unknown=False)
        task.agent_run={**(task.agent_run or {}),'input_count':count,'count_request_id':provider.last_request_id}
        s.commit()
        provider.generation_request_id=p.id
        receipt=provider.generate(prompt,p.terms['maximum_output_tokens'])
        if receipt['provider_usage'].get('input_tokens',receipt['provider_usage'].get('promptTokenCount',0))>p.terms['maximum_input_tokens']:receipt['usage_exceeds_limits']=True
        draft,checked=qa(receipt['output'],payload)
        mock=type(provider.transport) is httpx.MockTransport
        receipt={**receipt,'request_context':payload.model_dump(),'draft':draft.model_dump() if draft else {},'prompt_version':'a09-1',
            'evidence_origin':'MOCK_HTTP' if mock else 'PROVIDER_REPORTED_UNVERIFIED'}
        if not mock:
            receipt['measurement'].update(provider_called=True,provider_reported_tokens=receipt['provider_usage'],synthetic_provider_usage=None,
                simulated_cost_micro_usd=None,provider_estimated_billable_cost_micro_usd=receipt['actual_micro'],real_api_cost_micro_usd=None)
        lock_tenant(s,c.tenant_id);settle_receipt(s,c,task.id,p.id,receipt,'MOCK_HTTP' if mock else 'PROVIDER_REPORTED_UNVERIFIED',commit=False)
        if receipt['actual_micro']>p.terms['maximum_micro_usd'] or receipt['unpriced_features'] or receipt['usage_exceeds_limits']:
            tenant=lock_tenant(s,c.tenant_id);tenant.budget_paused=True;p.state='RECONCILIATION_REQUIRED'
        else:p.state='SETTLED'
        p.outcome={'receipt':receipt,'qa':checked.model_dump(),'input_count':count,'provider_called':not mock,'invoice_verified':False,
            'threads_publication_authorized':False,'count_requests':provider.count_calls,'generation_requests':provider.generate_calls,
            'generation_status':'GENERATED_QA_PASS' if receipt['output_valid'] and checked.passed else 'OUTPUT_REVIEW_REQUIRED'}
        audit(s,c.tenant_id,'ai_test.result_recorded',p.id,c.id);s.commit();return view(p)
    except Exception as exc:
        s.rollback();lock_tenant(s,c.tenant_id);p=permit_for(s,c.tenant_id,pid);failed_task=s.get(Task,p.task_id)
        if failed_task and not failed_task.settle_key:failed_task.status='RECONCILIATION_REQUIRED';failed_task.receipt_status=ReceiptStatus.RECONCILIATION_REQUIRED
        p.state='RECONCILIATION_REQUIRED';p.outcome={'category':exc.category if isinstance(exc,ProviderFailure) else 'LOCAL_OR_UNKNOWN_FAILURE',
            'request_id':provider.last_request_id,'response_id':provider.last_response_id,'provider_called':type(provider.transport) is not httpx.MockTransport,
            'invoice_verified':False,'no_retry':True,'count_requests':provider.count_calls,'generation_requests':provider.generate_calls}
        audit(s,c.tenant_id,'ai_test.unknown_or_stopped',p.id,c.id);s.commit();return view(p)
