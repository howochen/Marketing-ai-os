"""Reuse the existing Responses parser; real transport remains independently release-locked."""
import os
from datetime import datetime
import httpx
from sqlalchemy import select
from .database import SessionLocal,scope
from .models import Task,Tenant,Credential,Audit,now
from .durable_gate import utc
from .revisions import hashed
from .openai_provider import upper_bound
from .openai_provider import OpenAIProvider,ProviderFailure
from .live_transport import require_execution_release
from .threads_api import unseal
from .models import AutomationPolicy


class AutomationOpenAIProvider(OpenAIProvider):
    def __init__(self,policy: AutomationPolicy,transport: httpx.MockTransport | None=None) -> None:
        super().__init__(policy.terms['model'],transport,synthetic_only=type(transport) is httpx.MockTransport)
        self.policy=policy

    def authorization(self) -> str:
        if type(self.transport) is httpx.MockTransport:return 'synthetic-auto-no-account'
        if not self.policy.key_ciphertext:raise ProviderFailure('PROVIDER_KEY_MISSING',unknown=False)
        return unseal(self.policy.key_ciphertext,self.policy.tenant_id,'automation-key:'+self.policy.id)

    def check_offline(self) -> None:
        if os.getenv('MOS_MODEL_CALLS_ENABLED','false')!='true':raise ProviderFailure('MODEL_CALLS_DISABLED',unknown=False)
        if type(self.transport) is httpx.MockTransport:
            if os.getenv('MOS_ENV')!='test':raise ProviderFailure('MOCK_TEST_ONLY',unknown=False)
            return
        if self.policy.terms.get('execution_mode')!='LIVE':require_execution_release()
        if os.getenv('CI') or os.getenv('PYTEST_CURRENT_TEST'):raise ProviderFailure('LIVE_TEST_TRANSPORT_FORBIDDEN',unknown=False)
        self.live_context()

    def live_context(self) -> dict:
        from .automation_live import require_live
        with SessionLocal() as s:
            scope(s,self.policy.tenant_id)
            p=s.get(AutomationPolicy,self.policy.id,populate_existing=True)
            tenant=s.get(Tenant,self.policy.tenant_id)
            actor=s.get(Credential,p.owner_id) if p else None
            if (os.getenv('MOS_AUTOMATION_ENABLED','false')!='true' or not p or p.terms_hash!=self.policy.terms_hash or p.state!='ACTIVE' or not tenant or tenant.disabled or tenant.budget_paused
                    or tenant.spent_micro+tenant.reserved_micro>tenant.budget_micro or not actor or actor.role!='owner'
                    or (actor.revoked and actor.logged_out_at is None) or actor.environment!=os.getenv('MOS_ENV')
                    or not utc(datetime.fromisoformat(p.terms['starts_at']))<=now()<utc(datetime.fromisoformat(p.terms['expires_at']))):
                raise ProviderFailure('AUTOMATION_POLICY_STOPPED',unknown=False)
            b=require_live(s,p)
            return b.terms

    def context_headers(self) -> dict[str,str]:
        if type(self.transport) is httpx.MockTransport:return {}
        terms=self.live_context()
        return {'OpenAI-Organization':terms['account_id'],'OpenAI-Project':terms['project_id']}

    def request(self,path: str,payload: dict) -> tuple[dict,str | None]:
        if type(self.transport) is not httpx.MockTransport or self.policy.terms.get('execution_mode')=='LIVE':
            self.check_offline()
            self.live_context()
            if not self.generation_request_id:raise ProviderFailure('PERSISTED_AUTOMATION_ATTEMPT_REQUIRED',unknown=False)
            with SessionLocal() as s:
                scope(s,self.policy.tenant_id);task=s.get(Task,self.generation_request_id)
                prompt=payload.get('input');expected=self.payload(prompt,1024) if isinstance(prompt,str) else {}
                run=(task.agent_run or {}) if task else {}
                issuer=s.scalar(select(Audit.actor_id).where(Audit.tenant_id==self.policy.tenant_id,Audit.resource_id==self.generation_request_id,Audit.action=='task.claimed'))
                worker=s.get(Credential,issuer) if issuer else None
                if path=='responses/input_tokens':expected={k:expected[k] for k in ('model','input','text','tools','reasoning')} if expected else {}
                if (path not in {'responses','responses/input_tokens'} or not task or task.status!='RUNNING' or task.settle_key or not task.expires_at or utc(task.expires_at)<=now()
                        or not worker or worker.role!='automation_worker' or worker.revoked or utc(worker.expires_at)<=now()
                        or 'policy:'+self.policy.id not in worker.scopes or worker.environment!=os.getenv('MOS_ENV')
                        or run.get('automation_policy_id')!=self.policy.id
                        or run.get('policy_hash')!=self.policy.terms_hash or run.get('prompt_hash')!=hashed({'prompt':prompt})
                        or task.reserved_micro<upper_bound(self.card,1024) or payload!=expected):
                    raise ProviderFailure('PERSISTED_AUTOMATION_ATTEMPT_REQUIRED',unknown=False)
            sent: set[tuple[str | None,str]]=getattr(self,'_sent',set());key=(self.generation_request_id,path)
            if key in sent or (path=='responses' and (self.generation_request_id,'responses/input_tokens') not in sent):
                raise ProviderFailure('AUTOMATION_NO_REDISPATCH',unknown=False)
            self._sent=sent|{key}
        return super().request(path,payload)

    def payload(self,prompt: str,max_output_tokens: int) -> dict:
        payload=super().payload(prompt,max_output_tokens)
        payload.pop('prompt_cache_options',None)
        return payload

    def generate(self,prompt: str,max_output_tokens: int) -> dict:
        receipt=super().generate(prompt,max_output_tokens)
        if type(self.transport) is not httpx.MockTransport:
            receipt['evidence_origin']='PROVIDER_REPORTED_UNVERIFIED'
            receipt['measurement'].update(provider_called=True,synthetic_provider_usage=None,
                provider_reported_tokens=receipt['provider_usage'],simulated_cost_micro_usd=None,
                provider_estimated_billable_cost_micro_usd=receipt['actual_micro'],real_api_cost_micro_usd=None)
        return receipt
