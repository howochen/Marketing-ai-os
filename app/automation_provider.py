"""Reuse the existing Responses parser; real transport remains independently release-locked."""
import os
import httpx
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
        # Neither environment flags, a stored key nor a policy can unlock paid transport in this release.
        require_execution_release()

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
