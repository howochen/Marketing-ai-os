"""AUTO-002 logout, one-shot spending and creative evidence through isolated HTTP/DB."""
import copy,json,uuid
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import httpx,pytest
from sqlalchemy import select,text
from sqlalchemy.exc import DBAPIError
from conftest import tenant,ADMIN,bearer
from test_content_workbench import BRIEF,DRAFT
from test_threads_publisher import mock_threads
from test_automation import env,setup_policy,tick,entries
from app import automation as auto,single_ai_test as single,threads_routes
from app.main import app
from app.database import SessionLocal,scope,engine
from app.models import AutomationPolicy,AutomationSlot,AutomationAttempt,Credential,Task,Tenant,now
from app.providers import MockLLMProvider,MODEL,usage_cost
from app.semantic_review import SemanticProvider,segments
from app.revisions import hashed

NOVEL={'draft_text':'今天想把午後留給一杯茶嗎？\n把今天的忙碌先放一旁。\n合成茶室提供台灣茶。\n留言聊聊你今天想怎麼放慢腳步。',
    'hook':'今天想把午後留給一杯茶嗎？','call_to_action':'留言聊聊你今天想怎麼放慢腳步。'}
FACTS=[{'id':'tea','text':'合成茶室提供台灣茶。','source':'Owner supplied synthetic brand fact v1'}]


def relogin(client,tid):
    r=client.post('/admin/login-challenges',headers=ADMIN,json={'tenant_id':tid,'subject':'verified-owner'})
    return bearer(client.post('/auth/login',json={'token':r.json()['token']}).json()['access_token'])


def test_logout_ends_session_but_policy_survives_worker_restart(client,env,monkeypatch):
    from app import automation_worker
    tid,owner,w,p,_=setup_policy(client)
    assert client.delete('/ui/session',headers=owner).status_code==200
    assert client.get('/automation/policies',headers=owner).status_code==401
    monkeypatch.setenv('MOS_AUTOMATION_TENANT_ID',tid)
    monkeypatch.setattr(automation_worker,'ThreadsAPI',app.dependency_overrides[threads_routes.api])
    assert automation_worker.run_once()==1 and automation_worker.run_once()==1
    with SessionLocal() as s:
        scope(s,tid);a=s.scalar(select(AutomationSlot));assert a.state=='PUBLISHED'
        issuer=s.get(Credential,s.get(AutomationPolicy,p['id']).owner_id)
        assert issuer.revoked and issuer.logged_out_at and issuer.role=='owner'
    owner2=relogin(client,tid)
    assert len(entries(client,owner2))==1
    assert client.post('/automation/policies/'+p['id']+'/revoke',headers=owner2).status_code==200
    assert tick(client,w).status_code==403


def test_security_revoke_after_logout_still_stops_policy(client,env):
    tid,owner,w,p,_=setup_policy(client)
    with SessionLocal() as s:scope(s,tid);issuer=s.get(AutomationPolicy,p['id']).owner_id
    assert client.delete('/ui/session',headers=owner).status_code==200
    second=relogin(client,tid)
    assert client.delete('/credentials/'+issuer,headers=second).status_code==200
    with SessionLocal() as s:scope(s,tid);assert s.get(Credential,issuer).logged_out_at is None
    assert tick(client,w).status_code==403


def test_concurrent_logout_cannot_undo_security_revocation(client,env):
    tid,owner,w,p,_=setup_policy(client);second=relogin(client,tid)
    with SessionLocal() as s:scope(s,tid);issuer=s.get(AutomationPolicy,p['id']).owner_id
    with ThreadPoolExecutor(max_workers=2) as pool:
        f=pool.submit(client.delete,'/ui/session',headers=owner)
        g=pool.submit(client.delete,'/credentials/'+issuer,headers=second)
        assert f.result().status_code in {200,401};assert g.result().status_code==200
    assert tick(client,w).status_code==403


@pytest.fixture
def creative(env,monkeypatch):
    state={'writes':0,'reviews':0,'scenario':'pass'}
    def write(self,prompt,limit):
        state['writes']+=1;draft=copy.deepcopy(NOVEL)
        if state['scenario']=='rewrite' and state['writes']==1:draft['draft_text']+='保證有效'
        if state['scenario']=='qa_fail':draft['draft_text']+='神藥'
        if state['scenario']=='unsupported_brand':draft['draft_text']=draft['draft_text'].replace('合成茶室提供台灣茶。','合成茶室在全台設有五間門市。')
        if state['scenario']=='mechanical':draft['draft_text']=draft['hook']+'\n'+draft['hook']+'\n'+FACTS[0]['text']+'\n'+draft['call_to_action']
        if state['scenario']=='claim':draft['draft_text']=draft['draft_text'].replace('合成茶室提供台灣茶。','合成茶室的茶可以改善掉髮。')
        raw=json.dumps(draft,ensure_ascii=False);count=len(prompt.encode());usage={'input_tokens':count,'output_tokens':len(raw.encode())}
        return {'provider':'mock','model':'mock-a09-v1','receipt_id':'mock_'+uuid.uuid4().hex,'usage':usage,'actual_micro':usage_cost(usage,MODEL),'output':raw}
    monkeypatch.setattr(MockLLMProvider,'generate',write)
    def reviewer(policy):
        def respond(req):
            if req.url.path.endswith('input_tokens'):return httpx.Response(200,json={'input_tokens':333})
            state['reviews']+=1
            if state['scenario']=='timeout':raise httpx.ReadTimeout('synthetic-review-timeout')
            data=json.loads(json.loads(req.content)['input'].rsplit('\n',1)[1]);draft=data['draft']
            parts=[{'text':x,'kind':'FACT' if x==FACTS[0]['text'] else 'CREATIVE','fact_id':'tea' if x==FACTS[0]['text'] else None} for x in segments(draft['draft_text'])]
            if state['scenario']=='unsupported_brand':
                for segment in parts:
                    if '五間' in segment['text']:segment.update(kind='FACT',fact_id='tea')
            review={'draft_sha256':hashed(draft),'policy_hash':data['policy_hash'],'verdict':'PASS','topic_in_scope':True,'segments':parts,'reasons':[]}
            if state['scenario']=='stale':review['draft_sha256']='0'*64
            if state['scenario']=='negative':review['verdict']='REVIEW'
            output=json.dumps(review,ensure_ascii=False)
            return httpx.Response(200,json={'id':'resp_'+uuid.uuid4().hex,'model':'gpt-6-luna','status':'completed',
                'usage':{'input_tokens':1000,'output_tokens':300,'total_tokens':1300,'input_tokens_details':{'cached_tokens':0},'output_tokens_details':{'reasoning_tokens':0}},
                'output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':output}]}]})
        return SemanticProvider(policy,httpx.MockTransport(respond))
    monkeypatch.setattr(auto,'semantic_provider',reviewer)
    return state


def brand_policy(client,**changes):
    return setup_policy(client,creative_mode='BRAND_GUIDED',knowledge_facts=FACTS,semantic_reviewer='MODEL_REQUIRED',approved_copy=[],**changes)


def test_brand_guided_creates_novel_hook_cta_with_evidence_and_cost(client,creative):
    tid,owner,w,p,_=brand_policy(client)
    r=tick(client,w);assert r.status_code==200,r.text
    a=entries(client,owner)[0];assert a['state']=='PUBLISHED',a
    assert a['draft']==NOVEL['draft_text'] and NOVEL['hook'] not in p['terms']['approved_copy']
    history=client.get('/automation/slots/'+a['id']+'/attempts',headers=owner).json()
    assert {x['kind'] for x in history['attempts']}=={'WRITE','SEMANTIC'} and not history['external_fact_verification']
    with SessionLocal() as s:
        scope(s,tid);total=auto.monthly_total(s,tid,now())
        assert total==sum(s.get(Task,x['task_id']).actual_micro for x in history['attempts'])
    assert creative['writes']==1 and creative['reviews']==1


@pytest.mark.parametrize('scenario',['qa_fail','claim','unsupported_brand','mechanical','stale','negative','timeout'])
def test_creative_gate_fails_closed(client,creative,scenario):
    creative['scenario']=scenario
    _,owner,w,_,_=brand_policy(client)
    tick(client,w);a=entries(client,owner)[0]
    assert a['state'] in {'REVIEW_REQUIRED','RECONCILIATION_REQUIRED'} and not a['publication_id'],a
    before=(creative['writes'],creative['reviews']);tick(client,w)
    assert before==(creative['writes'],creative['reviews'])


def test_bounded_rewrite_keeps_all_versions_and_all_costs(client,creative):
    creative['scenario']='rewrite'
    tid,owner,w,_,_=brand_policy(client,max_rewrites=1)
    tick(client,w);a=entries(client,owner)[0]
    assert a['state']=='PUBLISHED',a
    history=client.get('/automation/slots/'+a['id']+'/attempts',headers=owner).json()['attempts']
    assert len([x for x in history if x['kind']=='WRITE'])==2
    assert creative['writes']==2 and creative['reviews']==1
    with SessionLocal() as s:
        scope(s,tid);assert auto.monthly_total(s,tid,now())==sum(s.get(Task,x['task_id']).actual_micro for x in history)


def test_creative_requires_human_when_configured_and_budget_reserves_review(client,creative):
    tid,owner,w,p,_=setup_policy(client,creative_mode='BRAND_GUIDED',knowledge_facts=FACTS,approved_copy=[],semantic_reviewer='HUMAN_REQUIRED')
    tick(client,w);assert entries(client,owner)[0]['state']=='REVIEW_REQUIRED' and creative['reviews']==0
    _,owner2,w2,_,_=brand_policy(client,monthly_budget_micro=1)
    tick(client,w2);assert entries(client,owner2)[0]['state']=='BLOCKED'


@pytest.fixture
def ai_env(monkeypatch):
    monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED','true');monkeypatch.setenv('MOS_SINGLE_AI_TEST_ENABLED','true')
    monkeypatch.setenv('MOS_THREADS_PUBLISH_ENABLED','false')
    state={'calls':[],'scenario':'normal'}
    def factory(p,s):
        def reply(req):
            state['calls'].append(req.url.path)
            if req.url.path.endswith('input_tokens'):return httpx.Response(200,json={'input_tokens':333})
            if state['scenario']=='timeout':raise httpx.ReadTimeout('synthetic secret do not log')
            usage={'input_tokens':1000,'output_tokens':200,'total_tokens':1200,'input_tokens_details':{'cached_tokens':0},'output_tokens_details':{'reasoning_tokens':0}}
            if state['scenario']=='overrun':usage.update(input_tokens=5000,output_tokens=4000,total_tokens=9000)
            if state['scenario']=='bad_usage':usage['input_tokens']='invalid'
            return httpx.Response(200,json={'id':'resp_'+uuid.uuid4().hex,'model':'gpt-6-luna','status':'completed','usage':usage,
                'output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':json.dumps(DRAFT,ensure_ascii=False)}]}]},headers={'x-request-id':'req_synthetic_auto2'})
        return single.SingleTestProvider(p,s,httpx.MockTransport(reply))
    monkeypatch.setattr(single,'provider_for',factory)
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Real HTTP forbidden')))
    return state


def request_permit(client,owner,approve=True,**changes):
    terms={'brief':BRIEF,'model':'gpt-6-luna','account_id':'org-synthetic','project_id':'proj_synthetic','maximum_input_tokens':4096,
        'maximum_output_tokens':512,'maximum_micro_usd':2000,'deadline':(now()+timedelta(minutes=10)).isoformat(),**changes}
    r=client.post('/ai-tests',headers=owner,json=terms);assert r.status_code==201,r.text
    p=r.json()
    if approve:
        proof={'terms_hash':p['terms_hash'],'user_consent_evidence_sha256':hashed({'consent':p['id']}),'account_access_evidence_sha256':'b'*64,
            'cost_bound_evidence_sha256':'c'*64,'confirm_one_generation_only':True,'count_endpoint_confirmed_free':True}
        r=client.post('/admin/ai-tests/'+p['id']+'/approve',headers={**owner,**ADMIN},json=proof);assert r.status_code==200,r.text
    return p


def test_one_shot_records_usage_ledger_and_never_publishes(client,ai_env):
    tid,owner,_,_=tenant(client);p=request_permit(client,owner)
    result=client.post('/ai-tests/'+p['id']+'/execute',headers=owner);assert result.status_code==200,result.text
    r=result.json();assert r['state']=='SETTLED' and r['request_count']==1 and not r['outcome']['provider_called']
    assert not r['invoice_verified'] and not r['threads_publication_authorized']
    assert client.post('/ai-tests/'+p['id']+'/execute',headers=owner).json()==r
    assert ai_env['calls']==['/v1/responses/input_tokens','/v1/responses']
    with SessionLocal() as s:
        scope(s,tid);t=s.get(Task,r['task_id']);assert t.actual_micro>0 and t.receipt_source=='MOCK_HTTP' and t.approved_revision_id is None


@pytest.mark.parametrize('scenario',['timeout','bad_usage','overrun'])
def test_single_unknown_overrun_never_retries_or_truncates(client,ai_env,scenario):
    ai_env['scenario']=scenario;tid,owner,_,_=tenant(client);p=request_permit(client,owner)
    r=client.post('/ai-tests/'+p['id']+'/execute',headers=owner).json();assert r['state']=='RECONCILIATION_REQUIRED'
    calls=len(ai_env['calls']);assert client.post('/ai-tests/'+p['id']+'/execute',headers=owner).status_code==409
    assert len(ai_env['calls'])==calls
    if scenario=='overrun':
        with SessionLocal() as s:
            scope(s,tid);t=s.get(Task,r['task_id']);assert t.actual_micro>2000 and s.get(Tenant,tid).budget_paused


def test_single_requires_two_authorities_flags_and_exact_tenant(client,ai_env,monkeypatch):
    _,owner,_,_=tenant(client);p=request_permit(client,owner,approve=False)
    assert client.post('/ai-tests/'+p['id']+'/execute',headers=owner).status_code==409
    proof={'terms_hash':p['terms_hash'],'user_consent_evidence_sha256':hashed({'consent':p['id']}),'account_access_evidence_sha256':'b'*64,'cost_bound_evidence_sha256':'c'*64,'confirm_one_generation_only':True,'count_endpoint_confirmed_free':True}
    assert client.post('/admin/ai-tests/'+p['id']+'/approve',headers=owner,json=proof).status_code==403
    assert client.post('/admin/ai-tests/'+p['id']+'/approve',headers={**owner,**ADMIN},json=proof).status_code==200
    monkeypatch.setenv('MOS_SINGLE_AI_TEST_ENABLED','false');assert client.post('/ai-tests/'+p['id']+'/execute',headers=owner).status_code==403
    _,other,_,_=tenant(client)
    assert client.get('/ai-tests/'+p['id'],headers=other).status_code==404
    assert not ai_env['calls']


def test_single_real_factory_cannot_send_under_pytest_or_enable_threads(client,ai_env,monkeypatch):
    _,owner,_,_=tenant(client);p=request_permit(client,owner)
    monkeypatch.setattr(single,'provider_for',lambda p,s:single.SingleTestProvider(p,s))
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-key-never-real');monkeypatch.setenv('MOS_OPENAI_ACCOUNT_ID','org-synthetic');monkeypatch.setenv('MOS_OPENAI_PROJECT_ID','proj_synthetic')
    assert client.post('/ai-tests/'+p['id']+'/execute',headers=owner).status_code==403
    assert not ai_env['calls']

def test_review_policy_keeps_exact_approval_after_logout(client,env):
    tid,owner,w,p,_=setup_policy(client,'REVIEW');tick(client,w)
    a=entries(client,owner)[0]
    assert client.post(f"/tasks/{a['task_id']}/revisions/{a['revision_id']}/approve",headers=owner).status_code==200
    assert client.delete('/ui/session',headers=owner).status_code==200
    assert tick(client,w).status_code==200
    with SessionLocal() as s:scope(s,tid);assert s.get(AutomationSlot,a['id']).state=='PUBLISHED'


def test_single_input_and_tenant_budget_cap_prevent_generation(client,ai_env):
    tid,owner,_,_=tenant(client);p=request_permit(client,owner,maximum_input_tokens=100)
    result=client.post('/ai-tests/'+p['id']+'/execute',headers=owner).json()
    assert result['state']=='RECONCILIATION_REQUIRED' and result['outcome']['generation_requests']==0
    assert ai_env['calls']==['/v1/responses/input_tokens']
    with SessionLocal() as s:scope(s,tid);t=s.get(Tenant,tid);t.budget_paused=True;s.commit()
    p2=request_permit(client,owner)
    assert client.post('/ai-tests/'+p2['id']+'/execute',headers=owner).status_code==403
    assert ai_env['calls']==['/v1/responses/input_tokens']

def test_one_shot_duplicate_consent_and_unknown_freeze_other_permit(client,ai_env):
    _,owner,_,_=tenant(client);p=request_permit(client,owner);p2=request_permit(client,owner,approve=False)
    proof={'terms_hash':p2['terms_hash'],'user_consent_evidence_sha256':hashed({'consent':p['id']}),
        'account_access_evidence_sha256':'b'*64,'cost_bound_evidence_sha256':'c'*64,'confirm_one_generation_only':True,'count_endpoint_confirmed_free':True}
    assert client.post('/admin/ai-tests/'+p2['id']+'/approve',headers={**owner,**ADMIN},json=proof).status_code==409
    proof['user_consent_evidence_sha256']=hashed({'consent':p2['id']})
    assert client.post('/admin/ai-tests/'+p2['id']+'/approve',headers={**owner,**ADMIN},json=proof).status_code==200
    ai_env['scenario']='timeout';assert client.post('/ai-tests/'+p['id']+'/execute',headers=owner).json()['state']=='RECONCILIATION_REQUIRED'
    assert client.post('/ai-tests/'+p2['id']+'/execute',headers=owner).status_code==403
    assert len(ai_env['calls'])==2


def test_unverified_count_endpoint_cost_cannot_be_approved(client,ai_env):
    _,owner,_,_=tenant(client);p=request_permit(client,owner,approve=False)
    proof={'terms_hash':p['terms_hash'],'user_consent_evidence_sha256':'a'*64,'account_access_evidence_sha256':'b'*64,
        'cost_bound_evidence_sha256':'c'*64,'confirm_one_generation_only':True,'count_endpoint_confirmed_free':False}
    assert client.post('/admin/ai-tests/'+p['id']+'/approve',headers={**owner,**ADMIN},json=proof).status_code==403
    assert client.post('/ai-tests/'+p['id']+'/execute',headers=owner).status_code==409
    assert not ai_env['calls']


def test_new_execution_evidence_is_immutable_and_tenant_scoped(client,creative):
    tid,owner,w,_,_=brand_policy(client);tick(client,w)
    p=request_permit(client,owner,approve=False)
    slot=entries(client,owner)[0]
    with SessionLocal() as s:
        scope(s,tid)
        with pytest.raises(DBAPIError):
            s.execute(text('UPDATE ai_test_permits SET terms_hash=:h WHERE id=:id'),{'h':'f'*64,'id':p['id']});s.commit()
        s.rollback()
        with pytest.raises(DBAPIError):
            s.execute(text('DELETE FROM automation_attempts WHERE slot_id=:id'),{'id':slot['id']});s.commit()
        s.rollback()
    if engine.dialect.name=='postgresql':
        with engine.connect() as c:
            c.execute(text("SELECT set_config('mos.tenant_id','another-tenant',true)"))
            assert c.scalar(text('SELECT count(*) FROM ai_test_permits WHERE id=:id'),{'id':p['id']})==0
            assert c.scalar(text('SELECT count(*) FROM automation_attempts WHERE slot_id=:id'),{'id':slot['id']})==0


def test_parallel_single_permit_never_dispatches_twice(client,ai_env):
    _,owner,_,_=tenant(client);p=request_permit(client,owner)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:client.post('/ai-tests/'+p['id']+'/execute',headers=owner),range(2)))
    assert all(r.status_code in {200,409} for r in results)
    assert ai_env['calls']==['/v1/responses/input_tokens','/v1/responses']
    assert client.get('/ai-tests/'+p['id'],headers=owner).json()['request_count']==1
