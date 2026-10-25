"""Validate a future live test plan. This module cannot authorize a network request."""
from pydantic import BaseModel, ConfigDict, Field
from .openai_provider import CARDS


class LiveTestPlan(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    environment: str
    separate_user_spend_authorization: str=Field(min_length=10)
    per_request_cap_micro: int=Field(gt=0)
    batch_cap_micro: int=Field(gt=0)
    max_executions: int=Field(gt=0,le=24)
    models: list[str]=Field(min_length=2,max_length=2)
    cost_bound_verified: bool=False
    tools: bool=False
    fallback: bool=False
    retries: int=0
    social_publishing: bool=False

    def validate_attempt(self,model: str,*,bound_micro: int | None,spent_micro: int,reserved_micro: int,
                         executions: int,paused: bool,unknown_outcome: bool) -> dict:
        if self.environment!='controlled-test' or set(self.models)!=set(CARDS) or model not in self.models:
            raise ValueError('Controlled environment and exact model allowlist required')
        if self.tools or self.fallback or self.retries!=0 or self.social_publishing:
            raise ValueError('Tools, fallback, retry and publishing forbidden')
        if not self.cost_bound_verified or bound_micro is None or type(bound_micro) is not int or bound_micro<=0:
            raise ValueError('Reliable cost upper bound required before any request')
        if min(spent_micro,reserved_micro,executions)<0 or paused or unknown_outcome:
            raise ValueError('Stop condition requires reconciliation')
        if (bound_micro>self.per_request_cap_micro or spent_micro+reserved_micro+bound_micro>self.batch_cap_micro
                or executions>=self.max_executions):
            raise ValueError('Per-request, batch or execution cap reached')
        return {'plan_valid':True,'live_transport_enabled':False,'authorization':'PLAN_ONLY_NOT_EXECUTION_AUTHORIZATION'}

    def enable_live(self) -> None:
        raise RuntimeError('P1.2 live tests are disabled; P1.5 requires separate user authorization and implementation review')
