"""Free-only Gemini adapter. Project billing is checked before every inference request."""
import copy
import hmac
import json
import os
import re
from pathlib import Path
import httpx
from .agent_schemas import Draft
from .openai_provider import ProviderFailure
from .providers import rate_id

CARD=json.loads((Path(__file__).resolve().parent.parent/'config/gemini-free.json').read_text())
MODEL_ID=CARD['model']


class GeminiProvider:
    def __init__(self,key: str,project_id: str,key_resource: str,verification_token: str='',transport: httpx.MockTransport | None=None) -> None:
        if (project_id or key_resource) and (not re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]',project_id) or not re.fullmatch(r'projects/[0-9]{1,30}/locations/global/keys/[A-Za-z0-9_-]{1,100}',key_resource)):
            raise ProviderFailure('GEMINI_PROJECT_CONFIGURATION_REQUIRED',unknown=False)
        self.key=key;self.project_id=project_id;self.key_resource=key_resource;self.verification_token=verification_token
        self.transport=transport;self.synthetic_only=type(transport) is httpx.MockTransport
        self.card=copy.deepcopy(CARD);self.model=MODEL_ID
        self.last_request_id: str | None=None;self.last_response_id: str | None=None
        self.generation_request_id: str | None=None
        self.count_calls=0;self.generate_calls=0;self.schema=Draft.model_json_schema();self.semantic=False

    def http(self,method: str,url: str,*,headers: dict,payload: dict | None=None) -> dict:
        if (self.synthetic_only and os.getenv('MOS_ENV')!='test') or (not self.synthetic_only and (os.getenv('CI') or os.getenv('PYTEST_CURRENT_TEST'))):
            raise ProviderFailure('GEMINI_LIVE_TEST_TRANSPORT_FORBIDDEN',unknown=False)
        try:
            with httpx.Client(transport=self.transport,timeout=httpx.Timeout(20,connect=5),follow_redirects=False,trust_env=False) as client:
                response=client.request(method,url,headers=headers,json=payload) if payload is not None else client.request(method,url,headers=headers)
            self.last_request_id=None
            rid=response.headers.get('x-request-id')
            if rid and re.fullmatch(r'[A-Za-z0-9_-]{1,120}',rid):self.last_request_id=rid
            if response.status_code==429:raise ProviderFailure('GEMINI_QUOTA_EXHAUSTED',unknown=False)
            if response.status_code in {401,403}:raise ProviderFailure('GEMINI_KEY_OR_VERIFICATION_PERMISSION_DENIED',unknown=False)
            if response.status_code>=500:raise ProviderFailure('GEMINI_PROVIDER_UNAVAILABLE')
            if response.status_code!=200:raise ProviderFailure('GEMINI_REQUEST_REJECTED',unknown=False)
            value=response.json()
            if not isinstance(value,dict):raise ValueError()
            return value
        except httpx.TimeoutException:raise ProviderFailure('GEMINI_TIMEOUT') from None
        except httpx.HTTPError:raise ProviderFailure('GEMINI_TRANSPORT') from None
        except (ValueError,TypeError):raise ProviderFailure('GEMINI_INVALID_RESPONSE') from None

    def verify_free(self) -> dict:
        if not self.key or not self.verification_token or not self.project_id or not self.key_resource:raise ProviderFailure('GEMINI_FREE_TIER_NOT_VERIFIED',unknown=False)
        headers={'Authorization':'Bearer '+self.verification_token}
        project=self.http('GET','https://cloudresourcemanager.googleapis.com/v3/projects/'+self.project_id,headers=headers)
        number=self.key_resource.split('/')[1]
        if project.get('projectId')!=self.project_id or project.get('name')!='projects/'+number or project.get('state')!='ACTIVE':
            raise ProviderFailure('GEMINI_PROJECT_KEY_MISMATCH',unknown=False)
        remote=self.http('GET','https://apikeys.googleapis.com/v2/'+self.key_resource+'/keyString',headers=headers)
        if not isinstance(remote.get('keyString'),str) or not hmac.compare_digest(remote['keyString'],self.key):
            raise ProviderFailure('GEMINI_PROJECT_KEY_MISMATCH',unknown=False)
        billing=self.http('GET','https://cloudbilling.googleapis.com/v1/projects/'+self.project_id+'/billingInfo',headers=headers)
        # An inactive linked account is not accepted as a permanent no-billing guarantee.
        if billing.get('projectId')!=self.project_id or billing.get('billingEnabled') is not False or billing.get('billingAccountName') not in {None,''}:
            raise ProviderFailure('GEMINI_PAID_OR_UNKNOWN_PROJECT_BLOCKED',unknown=False)
        return {'project_id':self.project_id,'project_number':number,'billing_enabled':False,'billing_account_linked':False,
                'source':'MOCK' if self.synthetic_only else 'GOOGLE_CLOUD_READ_ONLY','model':self.model}

    def connection(self) -> dict:
        proof=self.verify_free()
        self.model_access()
        return {**proof,'connection_verified':True,'generation_called':False}

    def model_access(self) -> dict:
        info=self.http('GET','https://generativelanguage.googleapis.com/v1beta/models/'+self.model,headers={'x-goog-api-key':self.key})
        if (info.get('name')!='models/'+self.model or 'generateContent' not in info.get('supportedGenerationMethods',[]) or
                type(info.get('inputTokenLimit')) is not int or info['inputTokenLimit']<CARD['max_input_tokens'] or
                type(info.get('outputTokenLimit')) is not int or info['outputTokenLimit']<CARD['max_output_tokens']):
            raise ProviderFailure('GEMINI_MODEL_ACCESS_NOT_VERIFIED',unknown=False)
        return {'model':self.model,'model_access_verified':True,'source':'MOCK' if self.synthetic_only else 'GOOGLE_MODEL_METADATA','generation_called':False}

    def check_offline(self) -> None:
        free_enabled=os.getenv('MOS_GEMINI_FREE_CALLS_ENABLED','false')=='true'
        mock_enabled=self.synthetic_only and os.getenv('MOS_MODEL_CALLS_ENABLED','false')=='true'
        if not free_enabled and not mock_enabled:raise ProviderFailure('MODEL_CALLS_DISABLED',unknown=False)
        if os.getenv('MOS_ENV')!='test':raise ProviderFailure('GEMINI_CONTROLLED_ENVIRONMENT_REQUIRED',unknown=False)

    def authorization(self) -> str:
        if not self.key:raise ProviderFailure('PROVIDER_KEY_MISSING',unknown=False)
        return self.key

    def payload(self,prompt: str,max_output_tokens: int) -> dict:
        if type(max_output_tokens) is not int or not 32<=max_output_tokens<=CARD['max_output_tokens'] or len(prompt.encode())>60000:
            raise ProviderFailure('GEMINI_REQUEST_CAP',unknown=False)
        return {'contents':[{'role':'user','parts':[{'text':prompt}]}],
                'generationConfig':{'candidateCount':1,'maxOutputTokens':max_output_tokens,'responseMimeType':'application/json',
                    'responseJsonSchema':self.schema,'thinkingConfig':{'thinkingLevel':'minimal'}}}

    def request(self,path: str,payload: dict) -> dict:
        self.check_offline();self.verify_free()
        if path=='countTokens':
            if self.count_calls:raise ProviderFailure('GEMINI_COUNT_ALREADY_ATTEMPTED',unknown=False)
            self.count_calls+=1
        elif path=='generateContent':
            if self.generate_calls or self.count_calls!=1:raise ProviderFailure('GEMINI_NO_REDISPATCH',unknown=False)
            self.generate_calls+=1
        else:raise ProviderFailure('GEMINI_ENDPOINT_DENIED',unknown=False)
        return self.http('POST','https://generativelanguage.googleapis.com/v1beta/models/'+self.model+':'+path,
                         headers={'x-goog-api-key':self.authorization()},payload=payload)

    def count_tokens(self,prompt: str) -> int:
        value=self.request('countTokens',{'generateContentRequest':{'model':'models/'+self.model,**self.payload(prompt,1024)}})
        count=value.get('totalTokens')
        if type(count) is not int or not 0<=count<=CARD['max_input_tokens']:raise ProviderFailure('GEMINI_INPUT_TOKEN_CAP',unknown=False)
        return count

    def generate(self,prompt: str,max_output_tokens: int) -> dict:
        data=self.request('generateContent',self.payload(prompt,max_output_tokens))
        try:
            raw=data['usageMetadata'];allowed={'promptTokenCount','candidatesTokenCount','thoughtsTokenCount','totalTokenCount','cachedContentTokenCount','toolUsePromptTokenCount','promptTokensDetails','candidatesTokensDetails','cacheTokensDetails','toolUsePromptTokensDetails','serviceTier'}
            if not isinstance(raw,dict) or raw.keys()-allowed:raise ValueError()
            counts={k:raw.get(k,0) for k in ('promptTokenCount','candidatesTokenCount','thoughtsTokenCount','totalTokenCount','cachedContentTokenCount','toolUsePromptTokenCount')}
            if any(type(v) is not int or v<0 for v in counts.values()) or not {'promptTokenCount','candidatesTokenCount','totalTokenCount'}<=raw.keys():raise ValueError()
            if counts['totalTokenCount']!=counts['promptTokenCount']+counts['candidatesTokenCount']+counts['thoughtsTokenCount']+counts['toolUsePromptTokenCount']:raise ValueError()
            rid=data['responseId'];version=data['modelVersion']
            if not isinstance(rid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',rid) or version!=self.model:raise ValueError()
            self.last_response_id=rid
        except (KeyError,ValueError,TypeError):raise ProviderFailure('GEMINI_INVALID_USAGE_OR_RECEIPT') from None
        candidates=data.get('candidates',[]);candidate=candidates[0] if isinstance(candidates,list) and len(candidates)==1 and isinstance(candidates[0],dict) else {}
        content=candidate.get('content',{});content=content if isinstance(content,dict) else {}
        parts=content.get('parts',[]);parts=parts if isinstance(parts,list) else [];texts=[];unpriced=bool(counts['cachedContentTokenCount'] or counts['toolUsePromptTokenCount'] or raw.get('serviceTier') not in {None,'STANDARD','SERVICE_TIER_UNSPECIFIED'})
        valid=candidate.get('finishReason')=='STOP' and not data.get('promptFeedback',{}).get('blockReason')
        for part in parts:
            if not isinstance(part,dict) or part.keys()-{'text','thought','thoughtSignature'}:valid=False;unpriced=True;continue
            if part.get('thought'):continue
            if isinstance(part.get('text'),str):texts.append(part['text'])
            else:valid=False
        if candidate.get('groundingMetadata') or candidate.get('urlContextMetadata'):unpriced=True
        output=''.join(texts).replace(self.key,'[REDACTED]').replace(self.verification_token,'[REDACTED]') if self.verification_token else ''.join(texts).replace(self.key,'[REDACTED]')
        try:
            if self.semantic:
                from .semantic_review import SemanticReview
                parsed=SemanticReview.model_validate_json(output).model_dump()
            else:parsed=Draft.model_validate_json(output).model_dump()
        except ValueError:parsed={};valid=False
        usage={'input_tokens':counts['promptTokenCount'],'output_tokens':counts['candidatesTokenCount']+counts['thoughtsTokenCount']}
        return {'provider':'google','model':self.model,'receipt_id':rid,'request_id':self.last_request_id,'provider_usage':raw,
            'usage':usage,'actual_micro':0,'output':output,'draft':parsed if not self.semantic else {},'semantic_review':parsed if self.semantic else None,
            'output_valid':valid and not unpriced,'provider_status':'completed' if valid else 'incomplete','unpriced_features':unpriced,
            'usage_exceeds_limits':usage['input_tokens']>CARD['max_input_tokens'] or usage['output_tokens']>max_output_tokens,
            'rate_version':rate_id(self.card),'evidence_origin':'MOCK_HTTP' if self.synthetic_only else 'PROVIDER_REPORTED_UNVERIFIED','receipt_status':'UNVERIFIED',
            'measurement':{'provider_called':not self.synthetic_only,'mock_bytes':None,'local_estimated_tokens':None,'provider_reported_tokens':None if self.synthetic_only else raw,
                'synthetic_provider_usage':raw if self.synthetic_only else None,'simulated_cost_micro_usd':0 if self.synthetic_only else None,
                'provider_estimated_billable_cost_micro_usd':None if self.synthetic_only else 0,'verified_invoice_cost_micro_usd':None,'reconciled':False,
                'pricing_basis':'VERIFIED_UNLINKED_BILLING_PROJECT_FREE_TIER','real_api_cost_micro_usd':0 if self.synthetic_only else None}}
