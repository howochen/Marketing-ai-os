"""MVP offline contracts. Seeded B/C metadata below is NOT a real acceptance record."""
import copy,json
from datetime import timedelta
import httpx,pytest
from sqlalchemy import select
from fastapi import HTTPException
from app.database import SessionLocal,scope
from app.models import AITestPermit,Task,Publication,ThreadsConnection,AutomationPolicy,Credential,AutomationSlot,now
from app.security import uid,audit
from app.revisions import hashed
from app.openai_provider import CARDS,ProviderFailure,upper_bound
from app.automation_provider import AutomationOpenAIProvider
from app.automation_live import require_live
from app import automation as auto
from conftest import ADMIN,bearer
from test_automation import env,setup_policy,tick,entries
from test_threads_publisher import mock_threads
from test_content_workbench import drafted,DRAFT
from test_auto_core import creative,brand_policy,NOVEL
from app.providers import MockLLMProvider,usage_cost,MODEL


@pytest.fixture
def staged(client,env):
    from app.main import app
    from app.threads_routes import api
    # Test-only official-shaped provenance; transport remains MockTransport and real HTTP is forbidden.
    app.dependency_overrides[api]().source='OFFICIAL_API'
    tid,owner,w,p,conn=setup_policy(client)
    t,r=drafted(client,owner)
    assert client.post('/tasks/'+t['id']+'/revisions/'+r['revision_id']+'/approve',headers=owner).status_code==200
    published=client.post('/tasks/'+t['id']+'/publication-request',headers=owner,json={'platform':'threads','idempotency_key':uid(),'revision_id':r['revision_id']})
    assert published.status_code==200,published.text
    cid=published.json()['id']
    from app.threads_publisher import content_hash
    assert client.post('/threads/publications/'+cid+'/authorize',headers=owner,json={'connection_id':conn['id'],'threads_user_id':conn['threads_user_id'],
        'revision_id':r['revision_id'],'content_sha256':content_hash(DRAFT['draft_text']),'confirm_public_post':True}).status_code==200
    worker=client.post('/admin/worker-credentials',headers=ADMIN,json={'tenant_id':tid,'subject':'synthetic-smoke-worker'}).json()['api_key']
    assert client.post('/threads/publications/'+cid+'/execute',headers=bearer(worker)).status_code==200
    bid=uid();btid=uid()
    with SessionLocal() as s:
        scope(s,tid);original=s.get(AutomationPolicy,p['id']);actor=original.owner_id
        s.add(Task(id=btid,tenant_id=tid,agent_id='A09',title='synthetic B evidence',brief='fixture only',status='PENDING_APPROVAL',
            settle_key=uid(),receipt_source='PROVIDER_REPORTED_UNVERIFIED'))
        s.flush()
        s.add(AITestPermit(id=bid,tenant_id=tid,owner_id=actor,state='SETTLED',request_count=1,task_id=btid,
            created_at=now()-timedelta(minutes=5),
            terms={'model':'gpt-6-luna','rate_snapshot':copy.deepcopy(CARDS['gpt-6-luna']),'account_id':'org-synthetic','project_id':'proj_synthetic'},
            terms_hash='f'*64,approval={'count_endpoint_confirmed_free':True},
            outcome={'provider_called':True,'generation_status':'GENERATED_QA_PASS','receipt':{'evidence_origin':'PROVIDER_REPORTED_UNVERIFIED','request_id':'req_fixture','receipt_id':'resp_fixture'}}))
        s.flush()
        s.commit()
    terms={**p['terms'],'execution_mode':'LIVE','model':'gpt-6-luna','live_ai_test_id':bid,'live_publication_id':cid}
    result=client.post('/automation/policies',headers=owner,json={'terms':terms});assert result.status_code==201,result.text
    policy=result.json()
    assert client.post('/automation/policies/'+policy['id']+'/provider-key',headers=owner,json={'api_key':'synthetic-provider-key-not-live'}).status_code==200
    return tid,owner,w,policy,conn


def consent(client,owner,p,**extra):
    return client.post('/automation/policies/'+p['id']+'/activate',headers=owner,
        json={'terms_hash':p['terms_hash'],'confirm_delegated_publication':True,**extra})


def test_b_c_cannot_replace_separate_d_consent(client,staged,monkeypatch):
    tid,owner,w,p,_=staged
    assert consent(client,owner,p).status_code==403
    assert consent(client,owner,p,confirm_live_execution=True).status_code==200
    with SessionLocal() as s:
        scope(s,tid);policy=s.get(AutomationPolicy,p['id'])
        with pytest.raises(HTTPException):require_live(s,policy)
        monkeypatch.setenv('MOS_AUTOMATION_LIVE_ENABLED','true')
        assert require_live(s,policy).id==p['terms']['live_ai_test_id']
    assert client.delete('/ui/session',headers=owner).status_code==200
    with SessionLocal() as s:
        scope(s,tid);assert require_live(s,s.get(AutomationPolicy,p['id']))


@pytest.mark.parametrize('failure',['model','account','mock','unverified','unknown'])
def test_live_evidence_fails_closed(client,staged,monkeypatch,failure):
    tid,owner,w,p,conn=staged
    if failure=='model':
        with SessionLocal() as s:
            scope(s,tid);s.get(AutomationPolicy,p['id']).key_ciphertext=None;s.commit()
    elif failure in {'account','mock'}:
        with SessionLocal() as s:
            scope(s,tid);c=s.get(ThreadsConnection,conn['id'])
            if failure=='account':c.publishing_enabled=False
            else:c.evidence_source='MOCK'
            s.commit()
    elif failure=='unverified':
        p=client.post('/automation/policies',headers=owner,json={'terms':{**p['terms'],'live_publication_id':uid()}}).json()
        assert client.post('/automation/policies/'+p['id']+'/provider-key',headers=owner,json={'api_key':'synthetic-provider-key-not-live'}).status_code==200
    else:
        assert consent(client,owner,p,confirm_live_execution=True).status_code==200
        with SessionLocal() as s:
            scope(s,tid);s.add(AutomationSlot(id=uid(),tenant_id=tid,policy_id=p['id'],scheduled_at=now(),state='RECONCILIATION_REQUIRED'));s.commit()
        monkeypatch.setenv('MOS_AUTOMATION_LIVE_ENABLED','true')
        with SessionLocal() as s:
            scope(s,tid)
            with pytest.raises(HTTPException,match='UNKNOWN_RESULT'):require_live(s,s.get(AutomationPolicy,p['id']))
        return
    assert consent(client,owner,p,confirm_live_execution=True).status_code==409


def test_ci_and_key_flags_never_send_real_http(client,staged,monkeypatch):
    tid,owner,w,p,_=staged
    assert consent(client,owner,p,confirm_live_execution=True).status_code==200
    monkeypatch.setenv('MOS_AUTOMATION_LIVE_ENABLED','true')
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Real HTTP forbidden')))
    with SessionLocal() as s:
        scope(s,tid);provider=AutomationOpenAIProvider(s.get(AutomationPolicy,p['id']))
        with pytest.raises(ProviderFailure,match='LIVE_TEST_TRANSPORT_FORBIDDEN'):provider.generate('synthetic',1024)


def test_reused_direction_still_creates_fresh_copy_without_daily_approval(client,creative,monkeypatch):
    clock=now().astimezone(auto.TAIPEI)
    times=[(clock-timedelta(minutes=1)).strftime('%H:%M'),clock.strftime('%H:%M')]
    assert len(set(times))==2
    original=MockLLMProvider.generate
    def generate(self,prompt,limit):
        r=original(self,prompt,limit)
        if creative['writes']>1:
            draft={'hook':'你想用哪一種節奏迎接今天？','draft_text':'你想用哪一種節奏迎接今天？\n不妨把螢幕暫時放下，留一點空白給自己。\n合成茶室提供台灣茶。\n分享你最想留給自己的安靜片刻吧。','call_to_action':'分享你最想留給自己的安靜片刻吧。'}
            r['output']=json.dumps(draft,ensure_ascii=False);r['usage']['output_tokens']=len(r['output'].encode());r['actual_micro']=usage_cost(r['usage'],MODEL)
        return r
    monkeypatch.setattr(MockLLMProvider,'generate',generate)
    tid,owner,w,p,_=brand_policy(client,topics=['午後茶款介紹'],times=times,daily_max=2,starts_at=(now()-timedelta(minutes=3)).isoformat())
    assert tick(client,w).status_code==200
    rows=entries(client,owner)
    assert len(rows)==2 and all(x['state']=='PUBLISHED' and x['verification']=='MOCK_READBACK_PASSED' for x in rows),rows
    assert len({x['draft'] for x in rows})==2 and creative['writes']==2
    assert tick(client,w).status_code==200 and creative['writes']==2


def test_reserved_policy_provider_path_with_mock_http_and_no_redispatch(client,staged,monkeypatch):
    tid,owner,w,p,_=staged
    assert consent(client,owner,p,confirm_live_execution=True).status_code==200
    monkeypatch.setenv('MOS_AUTOMATION_LIVE_ENABLED','true');calls=[]
    def reply(req):
        calls.append(req.url.path)
        if req.url.path.endswith('input_tokens'):return httpx.Response(200,json={'input_tokens':333})
        return httpx.Response(200,json={'id':'resp_mvp_fixture','model':'gpt-6-luna','status':'completed',
            'usage':{'input_tokens':333,'output_tokens':200,'total_tokens':533,'input_tokens_details':{'cached_tokens':0},'output_tokens_details':{'reasoning_tokens':0}},
            'output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':json.dumps(DRAFT,ensure_ascii=False)}]}]})
    with SessionLocal() as s:
        scope(s,tid);policy=s.get(AutomationPolicy,p['id']);c=s.scalar(select(Credential).where(Credential.subject=='automation:'+p['id']))
        provider=AutomationOpenAIProvider(policy,httpx.MockTransport(reply))
        with pytest.raises(ProviderFailure,match='PERSISTED_AUTOMATION_ATTEMPT_REQUIRED'):provider.count_tokens('unreserved')
        slot=AutomationSlot(id=uid(),tenant_id=tid,policy_id=p['id'],scheduled_at=now(),state='CREATED');s.add(slot);s.commit()
        auto.generate_slot(s,c,policy,slot,provider)
        assert slot.state=='REVIEW_REQUIRED' and 'DUPLICATE_CONTENT' in slot.error and calls==['/v1/responses/input_tokens','/v1/responses']
        assert s.get(Task,slot.task_id).receipt_source=='MOCK_HTTP'
        with pytest.raises(ProviderFailure):provider.count_tokens('redispatch')
        assert len(calls)==2
