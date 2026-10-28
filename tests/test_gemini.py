"""Synthetic Google HTTP only; no real keys, inference, billing or public posts."""
import copy
import json
import httpx
import pytest
from sqlalchemy import select
from conftest import tenant
from test_automation import env,setup_policy
from test_threads_publisher import mock_threads
from test_content_workbench import DRAFT
from app import gemini_policy as gp
from app.gemini_provider import GeminiProvider,CARD,MODEL_ID
from app.openai_provider import ProviderFailure
from app.database import SessionLocal,scope
from app.models import AutomationPolicy,Task,CostEvent,Tenant,AITestPermit

KEY='AIza'+'synthetic_not_a_real_api_key_123456789'
TOKEN='ya29.synthetic-read-only-token'
PROJECT={'project_id':'synthetic-free-project','key_resource':'projects/123456789/locations/global/keys/synthetic-key'}


@pytest.fixture
def google(monkeypatch):
    state={'calls':[],'paid':False,'key':KEY,'status':200,'finish':'STOP','draft':copy.deepcopy(DRAFT),'usage':{'promptTokenCount':100,'candidatesTokenCount':200,'thoughtsTokenCount':10,'totalTokenCount':310}}
    def send(r):
        assert KEY not in str(r.url) and TOKEN not in str(r.url)
        state['calls'].append((r.method,r.url.host,r.url.path))
        if r.url.host=='cloudresourcemanager.googleapis.com':return httpx.Response(200,json={'projectId':PROJECT['project_id'],'name':'projects/123456789','state':'ACTIVE'})
        if r.url.host=='apikeys.googleapis.com':return httpx.Response(200,json={'keyString':state['key']})
        if r.url.host=='cloudbilling.googleapis.com':return httpx.Response(200,json={'projectId':PROJECT['project_id'],'billingEnabled':state['paid'],'billingAccountName':'billingAccounts/paid' if state['paid'] else ''})
        if r.method=='GET':return httpx.Response(200,json={'name':'models/'+MODEL_ID,'inputTokenLimit':1048576,'outputTokenLimit':65536,'supportedGenerationMethods':['generateContent']})
        body=json.loads(r.content)
        if r.url.path.endswith(':countTokens'):
            assert 'generateContentRequest' in body and 'responseJsonSchema' in body['generateContentRequest']['generationConfig']
            return httpx.Response(200,json={'totalTokens':100})
        assert r.url.path.endswith(':generateContent') and r.headers['x-goog-api-key']==KEY
        assert not body.get('tools') and body['generationConfig']['candidateCount']==1 and body['generationConfig']['maxOutputTokens']==1024
        if state['status']=='timeout':raise httpx.ReadTimeout('synthetic '+KEY,request=r)
        if state['status']!=200:return httpx.Response(state['status'],json={'error':{'message':KEY}})
        return httpx.Response(200,headers={'x-request-id':'synthetic-request'},json={'modelVersion':MODEL_ID,'responseId':'synthetic-response',
            'usageMetadata':state['usage'],'candidates':[{'finishReason':state['finish'],'content':{'role':'model','parts':[{'text':json.dumps(state['draft'],ensure_ascii=False)}]}}]})
    transport=httpx.MockTransport(send)
    original_provider=gp.provider_for
    def provider(p,token=''):
        base=original_provider(p,token)
        return GeminiProvider(base.key,base.project_id,base.key_resource,token,transport)
    monkeypatch.setattr(gp,'provider_for',provider);monkeypatch.setenv('MOS_ENV','test')
    return state,transport


def configured(client,env,google):
    tid,owner,_,original,_=setup_policy(client)
    copied=client.post('/automation/policies/'+original['id']+'/gemini-copy',headers=owner,json={})
    assert copied.status_code==201
    p=copied.json();base='/automation/policies/'+p['id']
    assert client.post(base+'/provider-key',headers=owner,json={'api_key':KEY,'model':MODEL_ID}).status_code==200
    assert client.post(base+'/gemini-project',headers=owner,json=PROJECT).status_code==200
    return tid,owner,p,original


def checked(client,owner,p):
    r=client.post('/automation/policies/'+p['id']+'/gemini-check',headers=owner,json={'verification_access_token':TOKEN})
    assert r.status_code==200 and r.json()['free_tier_verified'],r.text
    assert KEY not in r.text and TOKEN not in r.text


def permit(client,owner,p,key='synthetic-consent-001'):
    r=client.post('/automation/policies/'+p['id']+'/gemini-test',headers=owner,json={'confirm_one_generation_only':True,'idempotency_key':key})
    assert r.status_code==201,r.text
    return r.json()


def test_copy_preserves_openai_policy_brand_and_key(client,env,google):
    tid,owner,p,old=configured(client,env,google)
    all=client.get('/automation/policies',headers=owner).json()['policies'];original=next(x for x in all if x['id']==old['id'])
    assert original['state']=='ACTIVE' and original['terms']==old['terms']
    assert p['terms']['brief']['brand']==old['terms']['brief']['brand'] and p['state']=='DRAFT' and not p['key_present']
    with SessionLocal() as s:
        scope(s,tid);record=s.get(AutomationPolicy,p['id']);assert KEY not in record.key_ciphertext and record.key_ciphertext


def test_connection_is_read_only_and_rotation_invalidates_proof(client,env,google):
    _,owner,p,_=configured(client,env,google);checked(client,owner,p)
    assert all(method=='GET' for method,_,_ in google[0]['calls'])
    assert client.post('/automation/policies/'+p['id']+'/provider-key',headers=owner,json={'api_key':KEY+'rotated','model':MODEL_ID}).status_code==200
    assert not client.get('/automation/policies/'+p['id']+'/gemini-status',headers=owner).json()['free_tier_verified']


@pytest.mark.parametrize('mutation,category',[('paid','GEMINI_PAID_OR_UNKNOWN_PROJECT_BLOCKED'),('key','GEMINI_PROJECT_KEY_MISMATCH')])
def test_wrong_project_or_billing_never_generates(client,env,google,mutation,category):
    _,owner,p,_=configured(client,env,google);google[0][mutation]=True if mutation=='paid' else 'wrong-key'
    r=client.post('/automation/policies/'+p['id']+'/gemini-check',headers=owner,json={'verification_access_token':TOKEN})
    assert not r.json()['free_tier_verified'] and r.json()['last_error']==category
    assert all(method=='GET' for method,_,_ in google[0]['calls'])
    assert client.post('/automation/policies/'+p['id']+'/gemini-test',headers=owner,json={'confirm_one_generation_only':True,'idempotency_key':'blocked-consent'}).status_code==409


def test_no_confirmation_or_switch_never_generates(client,env,google,monkeypatch):
    _,owner,p,_=configured(client,env,google);checked(client,owner,p)
    assert client.post('/automation/policies/'+p['id']+'/gemini-test',headers=owner,json={'confirm_one_generation_only':False,'idempotency_key':'not-approved'}).status_code==403
    test=permit(client,owner,p);monkeypatch.setenv('MOS_SINGLE_AI_TEST_ENABLED','false')
    r=client.post('/ai-tests/'+test['id']+'/execute',headers=owner,json={'verification_access_token':TOKEN})
    assert r.status_code==403 and all(m=='GET' for m,_,_ in google[0]['calls'])


def test_once_through_existing_ledger_qa_and_idempotency(client,env,google,monkeypatch):
    tid,owner,p,_=configured(client,env,google);checked(client,owner,p);test=permit(client,owner,p)
    assert permit(client,owner,p)['id']==test['id']
    monkeypatch.setenv('MOS_SINGLE_AI_TEST_ENABLED','true');monkeypatch.setenv('MOS_THREADS_PUBLISH_ENABLED','false')
    r=client.post('/ai-tests/'+test['id']+'/execute',headers=owner,json={'verification_access_token':TOKEN})
    assert r.status_code==200,r.text
    data=r.json();assert data['state']=='SETTLED' and data['outcome']['qa']['passed'] and data['outcome']['generation_requests']==1
    assert not data['outcome']['provider_called'] and not data['invoice_verified'] and not data['threads_publication_authorized']
    again=client.post('/ai-tests/'+test['id']+'/execute',headers=owner,json={'verification_access_token':TOKEN});assert again.json()==data
    assert len([x for x in google[0]['calls'] if x[2].endswith(':generateContent')])==1
    with SessionLocal() as s:
        scope(s,tid);task=s.get(Task,data['task_id']);assert task.actual_micro==0 and task.reserved_micro==1
        assert task.rate_snapshot==CARD and s.scalar(select(CostEvent).where(CostEvent.task_id==task.id,CostEvent.type=='SETTLE_MOCK'))
        assert not s.get(Tenant,tid).budget_paused


@pytest.mark.parametrize('failure',[429,500,'timeout','usage','truncated'])
def test_failures_stop_without_fallback_or_retry(client,env,google,monkeypatch,failure):
    _,owner,p,_=configured(client,env,google);checked(client,owner,p);test=permit(client,owner,p)
    monkeypatch.setenv('MOS_SINGLE_AI_TEST_ENABLED','true');monkeypatch.setenv('MOS_THREADS_PUBLISH_ENABLED','false')
    if failure=='usage':google[0]['usage']['unknownCharge']=99
    elif failure=='truncated':google[0]['finish']='MAX_TOKENS'
    else:google[0]['status']=failure
    r=client.post('/ai-tests/'+test['id']+'/execute',headers=owner,json={'verification_access_token':TOKEN})
    assert r.status_code==200 and KEY not in r.text and TOKEN not in r.text
    assert r.json()['state']=='RECONCILIATION_REQUIRED' if failure!='truncated' else r.json()['outcome']['generation_status']=='OUTPUT_REVIEW_REQUIRED'
    count=len(google[0]['calls']);client.post('/ai-tests/'+test['id']+'/execute',headers=owner,json={'verification_access_token':TOKEN})
    assert len(google[0]['calls'])==count and all(host.endswith('googleapis.com') for _,host,_ in google[0]['calls'])


def test_cross_tenant_and_secret_validation(client,env,google):
    _,owner,p,_=configured(client,env,google);_,other,_,_=tenant(client,name='Other tenant')
    assert client.get('/automation/policies/'+p['id']+'/gemini-status',headers=other).status_code==404
    assert client.post('/automation/policies/'+p['id']+'/gemini-check',headers=other,json={'verification_access_token':TOKEN}).status_code==404
    r=client.post('/automation/policies/'+p['id']+'/provider-key',headers=owner,json={'api_key':KEY*30,'model':MODEL_ID})
    assert r.status_code==422 and KEY not in r.text and 'input' not in r.json()['detail'][0]
    from app.operations import redact
    assert KEY not in redact(KEY) and TOKEN not in redact(TOKEN)


def test_provider_disabled_does_not_send(google,monkeypatch):
    monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED','false');p=GeminiProvider(KEY,**PROJECT,verification_token=TOKEN,transport=google[1])
    with pytest.raises(ProviderFailure,match='MODEL_CALLS_DISABLED'):p.count_tokens('test')
    assert not google[0]['calls']


def test_gemini_semantics_cannot_fallback_to_openai(client,env,google):
    from app.automation import Terms
    from pydantic import ValidationError
    _,_,p,_=configured(client,env,google)
    terms=copy.deepcopy(p['terms']);terms.update(model=MODEL_ID,semantic_reviewer='MODEL_REQUIRED',semantic_model='gpt-6-luna')
    with pytest.raises(ValidationError,match='Gemini forbids'):Terms.model_validate(terms)


def test_key_metadata_check_does_not_claim_free_tier(client,env,google):
    _,owner,p,_=configured(client,env,google)
    r=client.post('/automation/policies/'+p['id']+'/gemini-key-check',headers=owner,json={})
    assert r.status_code==200 and r.json()['key_connection']['model_access_verified']
    assert not r.json()['free_tier_verified'] and all(m=='GET' for m,_,_ in google[0]['calls'])


def test_existing_schedule_uses_gemini_qa_ledger_without_paid_fallback(client,env,google,monkeypatch):
    from app import automation as auto
    from test_automation import tick,entries
    tid,owner,p,_=configured(client,env,google)
    current=next(x for x in client.get('/automation/policies',headers=owner).json()['policies'] if x['id']==p['id'])
    activated=client.post('/automation/policies/'+p['id']+'/activate',headers=owner,json={'terms_hash':current['terms_hash'],'confirm_delegated_publication':True})
    assert activated.status_code==200,activated.text
    monkeypatch.setattr(auto,'generation_provider',lambda policy:GeminiProvider(KEY,**PROJECT,verification_token=TOKEN,transport=google[1]))
    from conftest import bearer
    token=client.post('/automation/policies/'+p['id']+'/worker-credential',headers=owner).json()['token']
    assert tick(client,bearer(token)).status_code==200
    slots=entries(client,owner);slot=next(x for x in slots if x['policy_id']==p['id'])
    assert slot['state']=='PUBLISHED' and slot['verification']=='MOCK_READBACK_PASSED' and slot['qa']['passed']
    assert slot['cost_micro']==0 and all(host.endswith('googleapis.com') for _,host,_ in google[0]['calls'])


def test_changed_billing_is_rechecked_before_any_inference(client,env,google,monkeypatch):
    _,owner,p,_=configured(client,env,google);checked(client,owner,p);test=permit(client,owner,p)
    google[0]['paid']=True;monkeypatch.setenv('MOS_SINGLE_AI_TEST_ENABLED','true');monkeypatch.setenv('MOS_THREADS_PUBLISH_ENABLED','false')
    r=client.post('/ai-tests/'+test['id']+'/execute',headers=owner,json={'verification_access_token':TOKEN})
    assert r.json()['state']=='RECONCILIATION_REQUIRED' and r.json()['outcome']['category']=='GEMINI_PAID_OR_UNKNOWN_PROJECT_BLOCKED'
    assert all(m=='GET' for m,_,_ in google[0]['calls'])


def test_budget_pause_and_unapproved_claim_never_publish(client,env,google,monkeypatch):
    tid,owner,p,_=configured(client,env,google);checked(client,owner,p);test=permit(client,owner,p)
    monkeypatch.setenv('MOS_SINGLE_AI_TEST_ENABLED','true');monkeypatch.setenv('MOS_THREADS_PUBLISH_ENABLED','false')
    with SessionLocal() as s:
        scope(s,tid);s.get(Tenant,tid).budget_paused=True;s.commit()
    count=len(google[0]['calls']);assert client.post('/ai-tests/'+test['id']+'/execute',headers=owner,json={'verification_access_token':TOKEN}).status_code==403
    assert len(google[0]['calls'])==count
    with SessionLocal() as s:
        scope(s,tid);s.get(Tenant,tid).budget_paused=False;s.commit()
    google[0]['draft']['draft_text']='保證生髮！'+DRAFT['draft_text']
    result=client.post('/ai-tests/'+test['id']+'/execute',headers=owner,json={'verification_access_token':TOKEN}).json()
    assert result['outcome']['generation_status']=='OUTPUT_REVIEW_REQUIRED' and not result['outcome']['qa']['passed']
    assert not result['threads_publication_authorized']


def test_two_concurrent_executions_only_dispatch_once(client,env,google,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    _,owner,p,_=configured(client,env,google);checked(client,owner,p);test=permit(client,owner,p)
    monkeypatch.setenv('MOS_SINGLE_AI_TEST_ENABLED','true');monkeypatch.setenv('MOS_THREADS_PUBLISH_ENABLED','false')
    def execute():return client.post('/ai-tests/'+test['id']+'/execute',headers=owner,json={'verification_access_token':TOKEN})
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:execute(),range(2)))
    assert all(r.status_code in {200,409} for r in results) and any(r.status_code==200 for r in results)
    assert len([x for x in google[0]['calls'] if x[2].endswith(':generateContent')])==1
