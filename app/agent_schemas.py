"""Strict data contracts; identity/approval/provider authority is server-owned."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field

Term = Annotated[str, Field(min_length=1, max_length=60)]


class BrandProfile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=1, max_length=400)
    forbidden_terms: list[Term] = Field(max_length=12)


class CopyConstraints(BaseModel):
    model_config = ConfigDict(extra='forbid')
    forbidden_terms: list[Term] = Field(max_length=12)
    required_terms: list[Term] = Field(max_length=12)
    max_chars: int = Field(ge=20, le=500)


class CopyRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    task_id: str = Field(min_length=1, max_length=36)
    idempotency_key: str = Field(min_length=8, max_length=128)
    agent_id: str = Field(min_length=3, max_length=8)
    platform: str = Field(min_length=1, max_length=30)
    industry: str = Field(min_length=1, max_length=80)
    brand_profile: BrandProfile
    target_audience: str = Field(min_length=1, max_length=160)
    campaign_goal: str = Field(min_length=1, max_length=160)
    tone: str = Field(min_length=1, max_length=80)
    brief: str = Field(min_length=1, max_length=1200)
    constraints: CopyConstraints
    model: Literal['mock-a09-v1'] = 'mock-a09-v1'
    tools: list[str] = Field(default_factory=list, max_length=0)
    max_output_tokens: int = Field(default=1024, ge=32, le=1024)


class Draft(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    draft_text: str = Field(min_length=1, max_length=2000)
    hook: str = Field(min_length=1, max_length=500)
    call_to_action: str = Field(min_length=1, max_length=500)


class QAResult(BaseModel):
    passed: bool
    reasons: list[str]
    certification: Literal['RULE_CHECK_ONLY'] = 'RULE_CHECK_ONLY'


class CopyOutput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal['1.0'] = '1.0'
    task_id: str
    agent_id: Literal['A09'] = 'A09'
    platform: Literal['threads'] = 'threads'
    draft_text: str
    hook: str
    call_to_action: str
    warnings: list[str]
    qa_result: QAResult
    approval_required: Literal[True] = True
    prompt_version: Literal['a09-1'] = 'a09-1'
    provider: Literal['mock'] = 'mock'
    model: Literal['mock-a09-v1'] = 'mock-a09-v1'
    usage: dict[str, int]
    cost_micro_usd: int = Field(ge=0)
    receipt_id: str
    receipt_source: Literal['MOCK'] = 'MOCK'
    receipt_status: Literal['UNVERIFIED'] = 'UNVERIFIED'
    estimated_cost_micro_usd: int = Field(ge=0)
    elapsed_ms: int = Field(ge=0)
    measurement: dict | None = None
