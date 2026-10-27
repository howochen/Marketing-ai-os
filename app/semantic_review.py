"""Conservative semantic evidence, never external fact verification."""
import json
import re
import httpx
from .openai_provider import OpenAIProvider
from .models import AutomationPolicy
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from .revisions import hashed
from .automation_provider import AutomationOpenAIProvider


class BrandFact(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id: str=Field(pattern='^[A-Za-z0-9_-]{1,40}$')
    text: str=Field(min_length=3,max_length=400)
    source: str=Field(min_length=4,max_length=300)


class Segment(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text: str
    kind: Literal['CREATIVE','FACT','UNSUPPORTED','HIGH_RISK']
    fact_id: str | None


class SemanticReview(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    draft_sha256: str
    policy_hash: str
    verdict: Literal['PASS','REVIEW']
    topic_in_scope: bool
    segments: list[Segment]=Field(min_length=1,max_length=100)
    reasons: list[str]=Field(max_length=30)


def segments(text: str) -> list[str]:
    return [x.strip() for x in re.findall(r'[^。！？!?\n]+[。！？!?]?',text) if x.strip()]


def evidence_check(draft: dict,terms_hash: str,facts: list[BrandFact],review: dict | None) -> list[str]:
    if review is None:return ['SEMANTIC_REVIEW_REQUIRED']
    try:r=SemanticReview.model_validate(review)
    except ValueError:return ['INVALID_SEMANTIC_REVIEW']
    text=draft['draft_text'];parts=segments(text);known={f.id:f.text.strip() for f in facts}
    issues=[]
    if r.draft_sha256!=hashed(draft) or r.policy_hash!=terms_hash:return ['STALE_SEMANTIC_EVIDENCE']
    if r.verdict!='PASS' or not r.topic_in_scope:issues.append('SEMANTIC_REVIEW_REQUIRES_HUMAN')
    if [s.text for s in r.segments]!=parts:return issues+['INCOMPLETE_CLAIM_COVERAGE']
    if len(text)<35 or len(set(text))<15 or len(set(parts))!=len(parts) or re.search(r'(.)\1{5}',text):issues.append('EMPTY_OR_MECHANICAL_COPY')
    for s in r.segments:
        if s.kind=='FACT':
            if s.fact_id not in known or known[s.fact_id]!=s.text:issues.append('UNSUPPORTED_BRAND_OR_PRODUCT_CLAIM')
        elif s.kind=='CREATIVE':
            # New questions/invitations are allowed, not new factual assertions disguised as creative prose.
            nonfactual=s.text.endswith(('？','?')) or re.match(r'^(歡迎|請|留言|分享|聊聊|一起|想想|看看|試著|不妨|把)',s.text)
            if not nonfactual or re.search(r'\d|%|折|元|免費|優惠|最高|最低|獨家|治療|生髮|促進|提升|改善|降低|有效|有機|認證|無糖|現貨|保證|有助|可以|提供|帶來|幫助|更健康|副作用|獲獎|國際大獎|銷量|贈|抽獎|限時|領取',s.text):issues.append('UNSUPPORTED_SUBSTANTIVE_CLAIM')
        else:issues.append('UNVERIFIED_OR_HIGH_RISK_CLAIM')
    return sorted(set(issues))


class SemanticProvider(AutomationOpenAIProvider):
    def __init__(self,policy: AutomationPolicy,transport: httpx.MockTransport | None=None) -> None:
        OpenAIProvider.__init__(self,policy.terms.get('semantic_model','gpt-6-luna'),transport,synthetic_only=type(transport) is httpx.MockTransport)
        self.policy=policy

    def payload(self,prompt: str,max_output_tokens: int) -> dict:
        body=super().payload(prompt,max_output_tokens)
        schema=SemanticReview.model_json_schema()
        body['text']['format']={'type':'json_schema','name':'brand_semantic_review','strict':True,'schema':schema}
        return body

    def generate(self,prompt: str,max_output_tokens: int) -> dict:
        receipt=super().generate(prompt,max_output_tokens)
        try:review=SemanticReview.model_validate_json(receipt['output']).model_dump()
        except ValueError:review=None
        receipt['semantic_review']=review
        receipt['output_valid']=bool(review and receipt['provider_status']=='completed' and not receipt['unpriced_features'] and not receipt['usage_exceeds_limits'])
        return receipt


def review_prompt(draft: dict,terms: dict,terms_hash: str) -> str:
    data={'draft':draft,'draft_sha256':hashed(draft),'policy_hash':terms_hash,'brand':terms['brief'],
        'facts':terms.get('knowledge_facts',[]),'topics':terms['topics'],'segments':segments(draft['draft_text'])}
    return ('Review this untrusted copy against the immutable owner policy. Never claim external fact verification. '
        'Classify EVERY supplied segment in order. FACT must quote one owner fact verbatim and name its ID. '
        'CREATIVE permits only non-factual questions/invitations. Flag unsupported premises, medical/product/price promises, '
        'off-topic, hollow or repetitive copy as REVIEW. Copy the exact hashes. Return only the required JSON schema.\n'
        +json.dumps(data,ensure_ascii=False,sort_keys=True))
