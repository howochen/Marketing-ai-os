"""Dormant real HTTP wiring. No runtime setting or approval can unlock this release."""
import os
from datetime import datetime
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import SpendAuthorization,Credential,RateVersion,now
from .durable_gate import batch_for,attempt_for,worker_access,utc
from .openai_provider import OpenAIProvider,ProviderFailure,upper_bound,CARDS
from .providers import rate_id,enabled


def require_execution_release() -> None:
    # P1.4 has no spending authority; replace only after separately reviewed P1.5 authorization.
    raise ProviderFailure('LIVE_EXECUTION_NOT_AUTHORIZED',unknown=False)


class LockedHTTPTransport(httpx.BaseTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        require_execution_release()
        return self._send_once(request)

    def _send_once(self, request: httpx.Request) -> httpx.Response:
        require_execution_release()
        # Private wiring exercised only with a substituted MockTransport in offline tests.
        if (request.method!='POST' or str(request.url)!='https://api.openai.com/v1/responses'
                or not os.getenv('OPENAI_API_KEY') or os.getenv('MOS_ENV')!='test'
                or request.headers.get('Authorization')!='Bearer '+os.environ['OPENAI_API_KEY']):
            raise ProviderFailure('INVALID_LIVE_TRANSPORT_CONTEXT',unknown=False)
        try:
            request.extensions['timeout']={'connect':5.0,'read':20.0,'write':20.0,'pool':5.0}
            with httpx.HTTPTransport(retries=0,trust_env=False) as transport:
                response=transport.handle_request(request)
                response.read()
                return response
        except httpx.TimeoutException:
            raise ProviderFailure('TIMEOUT') from None
        except httpx.HTTPError:
            raise ProviderFailure('TRANSPORT') from None


class ControlledOpenAIProvider(OpenAIProvider):
    """Not wired to any endpoint; durable executor integration stays locked for this release."""
    def check_offline(self) -> None:
        require_execution_release()

    def generate(self,prompt: str,max_output_tokens: int) -> dict:
        require_execution_release()
        result=super().generate(prompt,max_output_tokens)
        cost=result['actual_micro'];raw=result['provider_usage']
        result.update(evidence_origin='PROVIDER_REPORTED_UNVERIFIED',receipt_status='UNVERIFIED')
        result['measurement'].update(provider_reported_tokens=raw,synthetic_provider_usage=None,
            simulated_cost_micro_usd=None,provider_estimated_billable_cost_micro_usd=cost,
            real_api_cost_micro_usd=None,provider_called=True)
        if not result['output_valid'] or result['unpriced_features'] or result['usage_exceeds_limits']:
            result.update(receipt_status='RECONCILIATION_REQUIRED',outcome='RECONCILIATION_REQUIRED')
        return result


def prepare_live_provider(s: Session,c: Credential,bid: str,aid: str,approval_id: str) -> ControlledOpenAIProvider:
    """Internal durable boundary, not an HTTP route and not an execution authorization."""
    from .main import lock_tenant
    tenant=lock_tenant(s,c.tenant_id);b=batch_for(s,c.tenant_id,bid);a=attempt_for(s,c.tenant_id,bid,aid)
    worker_access(s,c,b)
    approval=s.scalar(select(SpendAuthorization).where(SpendAuthorization.id==approval_id,
        SpendAuthorization.tenant_id==c.tenant_id,SpendAuthorization.batch_id==bid))
    if (not approval or a.state!='DISPATCHING' or a.reserved_by!=c.id or tenant.budget_paused
            or b.paused or b.uncertain_request_count or b.closed_at or utc(b.deadline)<=now()
            or c.revoked or utc(c.expires_at)<=now()):
        raise ProviderFailure('INVALID_DURABLE_LIVE_CONTEXT',unknown=False)
    terms=approval.terms
    actor=s.get(Credential,approval.approver_id)
    rate=s.get(RateVersion,a.rate_version)
    effective=datetime.fromisoformat(terms['effective_at'])
    deadline=datetime.fromisoformat(terms['deadline'])
    if (not actor or actor.revoked or actor.role!='owner' or actor.tenant_id!=c.tenant_id
            or utc(actor.expires_at)<=now() or actor.environment!='test'
            or not enabled() or os.getenv('MOS_ENV')!='test' or not os.getenv('OPENAI_API_KEY')
            or not effective<=now()<deadline or terms['environment']!='controlled-test'
            or tenant.spent_micro+tenant.reserved_micro>tenant.budget_micro
            or b.environment!='test' or b.authorization_status=='SYNTHETIC_TEST_AUTHORIZATION'
            or approval.status!='EXECUTION_AUTHORIZED' or not terms.get('execution_authorized')
            or not terms.get('consent_verified') or terms.get('account_access')!='VERIFIED'
            or a.model not in terms['allowed_model_ids'] or a.model not in b.allowed_model_ids
            or rate is None or rate.snapshot!=a.rate_snapshot or rate_id(a.rate_snapshot)!=a.rate_version
            or a.rate_snapshot!=CARDS.get(a.model) or not a.rate_snapshot.get('live_cost_bound_verified')
            or a.reserved_micro_usd>terms['maximum_request_micro_usd']
            or a.reserved_micro_usd>b.maximum_request_micro_usd
            or b.request_count>terms['maximum_requests']
            or b.reserved_micro_usd+b.estimated_spent_micro_usd>terms['maximum_total_micro_usd']
            or b.reserved_micro_usd+b.estimated_spent_micro_usd>b.maximum_total_micro_usd
            or upper_bound(a.rate_snapshot,a.request_payload['max_output_tokens'])>a.reserved_micro_usd):
        raise ProviderFailure('SPEND_AUTHORITY_OR_COST_BOUND_NOT_VERIFIED',unknown=False)
    # Synthetic batches and INTERNAL_APPROVAL_ONLY are never convertible into paid authority.
    require_execution_release()
    provider=ControlledOpenAIProvider(a.model,LockedHTTPTransport(),snapshot=a.rate_snapshot)
    provider.generation_request_id=a.id
    return provider
