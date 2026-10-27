"""Responses API contract parser. The default provider permits MockTransport only."""
import copy
import json
import os
import uuid
from pathlib import Path
from typing import Annotated
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from .agent_schemas import Draft
from .providers import enabled, usage_cost, rate_id
from .operations import redact

CARDS=json.loads((Path(__file__).resolve().parent.parent/'config/openai-readiness.json').read_text())
Count=Annotated[int,Field(strict=True,ge=0)]


class ProviderFailure(RuntimeError):
    def __init__(self, category: str, *, unknown: bool=True) -> None:
        self.category=category
        self.outcome_unknown=unknown
        super().__init__('Provider '+category+'; no automatic retry')


class CacheWrites(BaseModel):
    model_config=ConfigDict(extra='forbid')
    ttl_30m_tokens: Count
    ttl_12h_tokens: Count


class InputDetails(BaseModel):
    model_config=ConfigDict(extra='forbid')
    cached_tokens: Count
    cache_write_tokens: Count=0
    cache_write_tokens_details: CacheWrites | None=None


class OutputDetails(BaseModel):
    model_config=ConfigDict(extra='forbid')
    reasoning_tokens: Count


class OpenAIUsage(BaseModel):
    model_config=ConfigDict(extra='forbid')
    input_tokens: Count
    output_tokens: Count
    total_tokens: Count
    input_tokens_details: InputDetails
    output_tokens_details: OutputDetails


def normalized_usage(raw: dict) -> dict[str,int]:
    usage=OpenAIUsage.model_validate(raw)
    details=usage.input_tokens_details
    writes=details.cache_write_tokens_details
    w30=writes.ttl_30m_tokens if writes else 0
    w12=writes.ttl_12h_tokens if writes else 0
    if (w30+w12!=details.cache_write_tokens or details.cached_tokens+w30+w12>usage.input_tokens
            or usage.output_tokens_details.reasoning_tokens>usage.output_tokens
            or usage.total_tokens!=usage.input_tokens+usage.output_tokens):
        raise ValueError('Inconsistent usage')
    return {'input_tokens':usage.input_tokens-details.cached_tokens-w30-w12,
            'cache_read_input_tokens':details.cached_tokens,'cache_write_30m_tokens':w30,
            'cache_write_12h_tokens':w12,'output_tokens':usage.output_tokens}


def upper_bound(card: dict, max_output_tokens: int) -> int:
    if type(max_output_tokens) is not int or not 1<=max_output_tokens<=card['max_output_tokens']:
        raise ValueError('Output limit not allowed')
    # All counted input at the most expensive supported write tier; output includes reasoning.
    return usage_cost({'cache_write_12h_tokens':card['max_input_tokens'],'output_tokens':max_output_tokens},card)


class OpenAIProvider:
    def __init__(self, model: str, transport: httpx.BaseTransport | None=None, *, snapshot: dict | None=None, synthetic_only: bool=False) -> None:
        if model not in CARDS: raise ValueError('Model not allowlisted')
        self.card=copy.deepcopy(snapshot if snapshot is not None else CARDS[model])
        if self.card['model']!=model or rate_id(self.card)!=rate_id(CARDS[model]):
            raise ValueError('Unreviewed rate snapshot')
        self.model=model
        self.transport=transport
        self.synthetic_only=synthetic_only
        self.last_client_request_id: str | None=None
        self.last_request_id: str | None=None
        self.last_response_id: str | None=None
        self.generation_request_id: str | None=None

    def check_offline(self) -> None:
        if not enabled(): raise RuntimeError('Model calls disabled')
        if os.getenv('MOS_ENV')!='test' or os.getenv('MOS_LIVE_TESTS','false').lower()!='false':
            raise RuntimeError('Only offline controlled tests are permitted')
        if self.synthetic_only:
            if os.getenv('OPENAI_API_KEY') or os.getenv('ANTHROPIC_API_KEY'):
                raise RuntimeError('Batch executor rejects all environment provider keys')
        elif not os.getenv('OPENAI_API_KEY'): raise RuntimeError('Provider key missing')
        if type(self.transport) is not httpx.MockTransport:
            raise RuntimeError('Live transport is disabled in P1.2')

    def payload(self, prompt: str, max_output_tokens: int) -> dict:
        upper_bound(self.card,max_output_tokens)
        # Explicit schema subset: no SDK-only helpers, tools, background work, or conversation state.
        schema={'type':'object','properties':{k:{'type':'string'} for k in ('draft_text','hook','call_to_action')},
                'required':['draft_text','hook','call_to_action'],'additionalProperties':False}
        return {'model':self.model,'input':prompt,'max_output_tokens':max_output_tokens,
                'text':{'format':{'type':'json_schema','name':'threads_draft','strict':True,'schema':schema}},
                'tools':[],'store':False,'service_tier':'default','reasoning':{'effort':'low'},
                'prompt_cache_options':{'mode':'explicit','ttl':'30m'}}

    def context_headers(self) -> dict[str,str]:
        return {}

    def authorization(self) -> str:
        return 'synthetic-p13-no-account' if self.synthetic_only else os.environ['OPENAI_API_KEY']

    def request(self, path: str, payload: dict) -> tuple[dict,str | None]:
        self.check_offline()
        if path not in {'responses','responses/input_tokens'}: raise ValueError('Endpoint not allowed')
        if payload.get('model')!=self.model or payload.get('tools')!=[]:
            raise ValueError('Model/tools not allowlisted')
        self.last_client_request_id=self.generation_request_id if path=='responses' and self.generation_request_id else str(uuid.uuid4())
        self.last_request_id=None;self.last_response_id=None
        try:
            with httpx.Client(transport=self.transport,timeout=httpx.Timeout(20,connect=5),
                              follow_redirects=False,trust_env=False) as client:
                response=client.post('https://api.openai.com/v1/'+path,json=payload,
                    headers={'Authorization':'Bearer '+self.authorization(),'X-Client-Request-Id':self.last_client_request_id,**self.context_headers()})
        except httpx.TimeoutException:
            raise ProviderFailure('TIMEOUT') from None
        except httpx.HTTPError:
            raise ProviderFailure('TRANSPORT') from None
        self.last_request_id=self.safe_id(response.headers.get('x-request-id'))
        if response.status_code>=300:
            category={400:'INVALID_REQUEST',401:'AUTH',403:'ACCESS',429:'RATE_LIMIT'}.get(response.status_code,'SERVER_OR_PROTOCOL')
            raise ProviderFailure(category,unknown=response.status_code not in {400,401,403,429})
        try:
            data=response.json()
            if not isinstance(data,dict): raise ValueError()
        except (ValueError,TypeError):
            raise ProviderFailure('INVALID_JSON') from None
        self.last_response_id=self.safe_id(data.get('id'))
        return data,self.last_request_id

    @staticmethod
    def safe_id(value: object) -> str | None:
        return value if isinstance(value,str) and 0<len(value)<=200 and value.isascii() and value.isprintable() and redact(value)==value else None

    def count_tokens(self, prompt: str) -> int:
        full=self.payload(prompt,1)
        count,_=self.request('responses/input_tokens',{k:full[k] for k in ('model','input','text','tools','reasoning')})
        value=count.get('input_tokens')
        if type(value) is not int or value<0: raise ProviderFailure('INVALID_COUNT')
        return value  # Mock HTTP's provider-schema count, never bytes or a verified local estimate.

    def generate(self, prompt: str, max_output_tokens: int) -> dict:
        data,request_id=self.request('responses',self.payload(prompt,max_output_tokens))
        try:
            if data.get('model')!=self.model or not self.last_response_id:
                raise ValueError()
            raw=data['usage'];usage=normalized_usage(raw)
            cost=usage_cost(usage,self.card)
        except (ValueError,TypeError,KeyError,ValidationError):
            raise ProviderFailure('INVALID_USAGE_OR_RECEIPT') from None
        texts=[]
        unpriced=data.get('service_tier','default')!='default'
        valid=data.get('status')=='completed' and not data.get('error') and not data.get('incomplete_details')
        items=data.get('output',[])
        if not isinstance(items,list): items=[];valid=False
        for item in items:
            if not isinstance(item,dict): valid=False;continue
            if item.get('type')=='reasoning': continue
            if item.get('type')!='message': valid=False;unpriced=True;continue
            if item.get('role')!='assistant' or item.get('status','completed')!='completed': valid=False
            contents=item.get('content',[])
            if not isinstance(contents,list):valid=False;continue
            for content in contents:
                if not isinstance(content,dict):valid=False;continue
                if content.get('type')=='output_text' and isinstance(content.get('text'),str):texts.append(content['text'])
                else:valid=False
        output=''.join(texts)
        try:
            draft=Draft.model_validate_json(output)
        except (ValidationError,ValueError):
            draft=None;valid=False
        return {'provider':'openai','model':self.model,'receipt_id':data['id'],'request_id':request_id,'client_request_id':self.last_client_request_id,
                'usage':usage,'provider_usage':raw,'actual_micro':cost,'output':output,
                'draft':draft.model_dump() if valid and draft else {'draft_text':'','hook':'','call_to_action':''},
                'output_valid':valid,'provider_status':data.get('status'),'outcome':'COMPLETE' if valid else 'OUTPUT_REVIEW_REQUIRED',
                'unpriced_features':unpriced,
                'usage_exceeds_limits':raw['input_tokens']>self.card['max_input_tokens'] or raw['output_tokens']>max_output_tokens,
                'rate_version':rate_id(self.card),'evidence_origin':'MOCK_HTTP','receipt_status':'UNVERIFIED',
                'measurement':{'mock_bytes':None,'local_estimated_tokens':None,'provider_reported_tokens':None,
                    'synthetic_provider_usage':raw,'simulated_cost_micro_usd':cost,
                    'provider_estimated_billable_cost_micro_usd':None,'verified_invoice_cost_micro_usd':None,
                    'real_api_cost_micro_usd':0,'provider_called':False,'reconciled':False}}
