"""Fixed synthetic scenarios; transport and credential cannot be supplied by an API caller."""
import json
import hashlib
import httpx
from .openai_provider import OpenAIProvider


def mock_provider(model: str,scenario: str,snapshot: dict) -> OpenAIProvider:
    def respond(request: httpx.Request) -> httpx.Response:
        payload=json.loads(request.content)
        if str(request.url).endswith('input_tokens'):return httpx.Response(200,json={'input_tokens':333})
        if scenario=='timeout':raise httpx.ReadTimeout('synthetic unknown outcome')
        if scenario=='server_error':return httpx.Response(503,json={'error':'synthetic server error'})
        context=json.loads(payload['input'].rsplit('\n[REQUEST_DATA_JSON]\n',1)[1])['request']
        name=context['brand_profile']['name'];cta='留言討論。'
        draft={'draft_text':name+' 合成草稿。'+cta,'hook':name,'call_to_action':cta}
        usage: dict={'input_tokens':1000,'input_tokens_details':{'cached_tokens':0},
               'output_tokens':200,'output_tokens_details':{'reasoning_tokens':50},'total_tokens':1200}
        if scenario=='overrun':usage.update(input_tokens=5000,output_tokens=4000,total_tokens=9000)
        if scenario=='unknown_receipt':usage['input_tokens']='unknown'
        if scenario=='unknown_cost':usage['unknown_paid_feature']=1
        data: dict={'id':'resp_'+hashlib.sha256(request.content).hexdigest(),'model':model,'status':'completed','usage':usage,
              'output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':json.dumps(draft,ensure_ascii=False)}]}]}
        if scenario=='refusal':data['output'][0]['content']=[{'type':'refusal','refusal':'Synthetic refusal'}]
        if scenario=='truncated':data['status']='incomplete';data['incomplete_details']={'reason':'max_output_tokens'}
        return httpx.Response(200,json=data,headers={'x-request-id':'req_synthetic_p13'})
    return OpenAIProvider(model,httpx.MockTransport(respond),snapshot=snapshot,synthetic_only=True)
