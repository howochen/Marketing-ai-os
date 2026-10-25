"""Official-contract synthetic HTTP only. No real account, tokens or publication."""
import json
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs,urlsplit
import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select,text,insert,update
from sqlalchemy.exc import DBAPIError
from app.main import app
from app.database import SessionLocal,scope,engine
from app.models import ThreadsConnection,ThreadsOAuthState,Publication,Credential,now
from app.security import digest
from app import threads_routes as routes,threads_publisher as publisher
from app.threads_api import ThreadsAPI,ThreadsFailure,seal,unseal,SCOPES
from conftest import tenant,task
from test_agent_runtime import run,offline


@pytest.fixture
def mock_threads(monkeypatch):
    monkeypatch.setenv('MOS_THREADS_APP_ID','12345');monkeypatch.setenv('MOS_THREADS_APP_SECRET','synthetic-app-secret')
    monkeypatch.setenv('MOS_THREADS_REDIRECT_URI','https://testserver/threads/oauth/callback')
    monkeypatch.setenv('MOS_THREADS_TOKEN_KEY',Fernet.generate_key().decode())
    monkeypatch.setenv('MOS_THREADS_PUBLISH_ENABLED','true')
    state={'calls':[],'text':'','scenario':'normal','account':'10001','read_fail':False}
    def respond(request):
        path=request.url.path;method=request.method;state['calls'].append((method,path))
        if path=='/oauth/access_token':return httpx.Response(200,json={'access_token':'synthetic-short-token','user_id':'10001'})
        if path in {'/access_token','/refresh_access_token'}:return httpx.Response(200,json={'access_token':'synthetic-long-token','expires_in':5184000})
        if path=='/me':return httpx.Response(200,json={'id':state['account'],'username':'synthetic_brand'})
        if path=='/debug_token':return httpx.Response(200,json={'data':{'is_valid':True,'user_id':state['account'],'app_id':'12345',
            'scopes':sorted(SCOPES) if state['scenario']!='permission' else ['threads_basic'],'expires_at':int((now()+timedelta(days=50)).timestamp())}})
        if path.endswith('/threads_publishing_limit'):return httpx.Response(200,json={'data':[{'quota_usage':0,'config':{'quota_total':250}}]})
        if method=='POST' and path.endswith('/threads'):
            data=parse_qs(request.content.decode());assert data['media_type']==['TEXT'] and 'auto_publish_text' not in data
            state['text']=data['text'][0]
            if state['scenario']=='create_timeout':raise httpx.ReadTimeout('synthetic-secret-never-log')
            if state['scenario']=='create_crash':raise KeyboardInterrupt('synthetic-worker-exit')
            return httpx.Response(200,json={'id':'20001'})
        if method=='GET' and path=='/20001':return httpx.Response(200,json={'id':'20001','status':state.get('container_status','FINISHED')})
        if method=='POST' and path.endswith('/threads_publish'):
            assert parse_qs(request.content.decode())['creation_id']==['20001']
            if state['scenario']=='publish_timeout':raise httpx.ReadTimeout('synthetic-secret-never-log')
            if state['scenario']=='publish_crash':raise KeyboardInterrupt('synthetic-worker-exit')
            if state['scenario']=='server':return httpx.Response(503,json={'error':{'message':'synthetic-long-token'}})
            if state['scenario']=='rate':return httpx.Response(429,json={'error':{'code':4}})
            if state['scenario']=='invalid_id':return httpx.Response(200,json={'id':'not-an-id'})
            if state['scenario']=='same_id':return httpx.Response(200,json={'id':'20001'})
            return httpx.Response(200,json={'id':'30001'},headers={'x-fb-trace-id':'trace001'})
        if path=='/30001':
            if state['read_fail']:return httpx.Response(503,json={'error':{}})
            return httpx.Response(200,json={'id':'30001','owner':{'id':'10001'},'username':'synthetic_brand',
                'text':state['text'] if state['scenario']!='mismatch' else 'different',
                'permalink':'https://www.threads.com/@synthetic_brand/post/SYNTHETIC','timestamp':'2026-10-26T00:00:00+00:00','media_type':'TEXT_POST'})
        raise AssertionError('Unexpected official-contract path '+path)
    client=ThreadsAPI(httpx.MockTransport(respond))
    app.dependency_overrides[routes.api]=lambda:client
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',lambda *a:(_ for _ in ()).throw(AssertionError('Real HTTP forbidden')))
    yield state
    app.dependency_overrides.pop(routes.api,None)


def connect(client,owner):
    result=client.post('/threads/oauth/start',headers=owner);assert result.status_code==200,result.text
    state=parse_qs(urlsplit(result.json()['authorization_url']).query)['state'][0]
    browser=result.cookies['mos_threads_browser']
    result=client.get('/threads/oauth/callback',params={'state':state,'code':'synthetic-code'},headers={'Cookie':'mos_threads_browser='+browser})
    assert result.status_code==200,result.text
    return result.json(),state,browser


def ready(client,owner,worker,cid):
    t=task(client,owner);result=run(client,worker,t);assert result.status_code==200,result.text
    history=client.get(f'/tasks/{t}/revisions',headers=owner).json();rid=history['latest_revision_id']
    assert client.post(f'/tasks/{t}/approve',headers=owner,json={'revision_id':rid}).status_code==200
    p=client.post(f'/tasks/{t}/publication-request',headers=owner,json={'platform':'threads','idempotency_key':'threads-'+t,'revision_id':rid}).json()
    text=history['revisions'][0]['after_text']
    consent={'connection_id':cid,'threads_user_id':'10001','revision_id':rid,'content_sha256':publisher.content_hash(text),'confirm_public_post':True}
    result=client.post(f'/threads/publications/{p["id"]}/authorize',headers=owner,json=consent)
    assert result.status_code==200,result.text
    return p['id'],t,consent


def test_oauth_binding_encryption_replay_and_local_revoke(client,mock_threads,caplog):
    tid,owner,worker,_=tenant(client);item,state,browser=connect(client,owner)
    assert item['evidence_source']=='MOCK' and not item['publishing_enabled']
    assert 'token_ciphertext' not in item and 'access_token' not in json.dumps(item)
    assert client.get('/threads/oauth/callback',params={'state':state,'code':'synthetic-code'},headers={'Cookie':'mos_threads_browser='+browser}).status_code==400
    with SessionLocal() as s:
        scope(s,tid);record=s.get(ThreadsConnection,item['id'])
        assert 'synthetic-long-token' not in record.token_ciphertext
        assert unseal(record.token_ciphertext,tid,record.id)=='synthetic-long-token'
        with pytest.raises(ThreadsFailure):unseal(record.token_ciphertext,'other-tenant',record.id)
    assert client.delete('/threads/connections/'+item['id'],headers=worker).status_code==403
    assert client.delete('/threads/connections/'+item['id'],headers=owner).json()['provider_revocation_verified'] is False
    with SessionLocal() as s:
        scope(s,tid);record=s.get(ThreadsConnection,item['id']);assert record.token_ciphertext is None and record.revoked_at
    assert 'synthetic-long-token' not in caplog.text and 'synthetic-code' not in caplog.text


def test_oauth_state_cookie_expiration_and_actor_revocation(client,mock_threads,monkeypatch):
    tid,owner,worker,_=tenant(client)
    result=client.post('/threads/oauth/start',headers=owner);query=parse_qs(urlsplit(result.json()['authorization_url']).query)
    state=query['state'][0];browser=result.cookies['mos_threads_browser']
    assert client.get('/threads/oauth/callback',params={'state':state,'code':'x'},headers={'Cookie':'mos_threads_browser=wrong'}).status_code==400
    future=now()+timedelta(minutes=11);monkeypatch.setattr(routes,'now',lambda:future)
    assert client.get('/threads/oauth/callback',params={'state':state,'code':'x'},headers={'Cookie':'mos_threads_browser='+browser}).status_code==400
    assert mock_threads['calls']==[]


def test_contract_publish_readback_not_live_claim_and_deduplicate(client,mock_threads,offline):
    tid,owner,worker,_=tenant(client);conn,_,_=connect(client,owner)
    assert client.post(f'/threads/connections/{conn["id"]}/publishing',headers=owner,json={'enabled':True}).status_code==200
    pid,_,_=ready(client,owner,worker,conn['id'])
    result=client.post(f'/threads/publications/{pid}/execute',headers=worker);assert result.status_code==200,result.text
    data=result.json();assert data['container_id']=='20001' and data['published_media_id']=='30001'
    assert data['publish_status']=='PUBLISHED_UNVERIFIED' and data['verification_status']=='MOCK_READBACK_PASSED'
    assert data['verified_at'] is None
    assert client.post(f'/threads/publications/{pid}/execute',headers=worker).json()==data
    assert mock_threads['calls'].count(('POST','/10001/threads'))==1
    assert mock_threads['calls'].count(('POST','/10001/threads_publish'))==1


@pytest.mark.parametrize('scenario',['create_timeout','publish_timeout','server','rate','invalid_id','same_id'])
def test_uncertain_post_never_resends_after_new_session(client,mock_threads,offline,scenario):
    tid,owner,worker,_=tenant(client);conn,_,_=connect(client,owner)
    client.post(f'/threads/connections/{conn["id"]}/publishing',headers=owner,json={'enabled':True})
    pid,_,_=ready(client,owner,worker,conn['id']);mock_threads['scenario']=scenario
    result=client.post(f'/threads/publications/{pid}/execute',headers=worker)
    assert result.status_code==200,result.text
    assert result.json()['publish_status']=='RESULT_UNKNOWN'
    before=list(mock_threads['calls'])
    assert client.post(f'/threads/publications/{pid}/execute',headers=worker).status_code==409
    assert mock_threads['calls']==before
    assert client.post(f'/threads/publications/{pid}/retry-preflight',headers=owner).status_code==409
    assert client.post(f'/threads/publications/{pid}/reconcile',headers=worker).json()['publish_status']=='RECONCILIATION_REQUIRED'
    assert all(method=='GET' for method,path in mock_threads['calls'][len(before):])


@pytest.mark.parametrize('scenario',['create_crash','publish_crash'])
def test_worker_crash_durable_marker_no_resend(client,mock_threads,offline,scenario,monkeypatch):
    tid,owner,worker,_=tenant(client);conn,_,_=connect(client,owner)
    client.post(f'/threads/connections/{conn["id"]}/publishing',headers=owner,json={'enabled':True})
    pid,_,_=ready(client,owner,worker,conn['id']);mock_threads['scenario']=scenario
    # Call coordinator directly to model process interruption without TestClient BaseException handling.
    worker_hash=digest(worker['Authorization'][7:])
    with SessionLocal() as s:
        scope(s,tid);c=s.scalar(select(Credential).where(Credential.token_hash==worker_hash))
        with pytest.raises(KeyboardInterrupt):publisher.execute(pid,c,s,app.dependency_overrides[routes.api]())
        s.rollback()
    before=list(mock_threads['calls'])
    assert client.post(f'/threads/publications/{pid}/execute',headers=worker).status_code==409
    assert before==mock_threads['calls']
    future=now()+timedelta(seconds=61);monkeypatch.setattr(publisher,'now',lambda:future)
    assert client.post('/maintenance/recover',headers=worker).json()['held_for_reconciliation']==1
    assert client.post('/maintenance/recover',headers=worker).json()['held_for_reconciliation']==0
    assert before==mock_threads['calls']


def test_two_workers_one_publication(client,mock_threads,offline):
    tid,owner,worker,_=tenant(client);conn,_,_=connect(client,owner)
    client.post(f'/threads/connections/{conn["id"]}/publishing',headers=owner,json={'enabled':True})
    pid,_,_=ready(client,owner,worker,conn['id'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:client.post(f'/threads/publications/{pid}/execute',headers=worker),range(2)))
    assert all(r.status_code in {200,409} for r in results)
    assert mock_threads['calls'].count(('POST','/10001/threads'))==1 and mock_threads['calls'].count(('POST','/10001/threads_publish'))==1


def test_readback_failure_keeps_unverified_and_only_get_reconciliation(client,mock_threads,offline):
    tid,owner,worker,_=tenant(client);conn,_,_=connect(client,owner)
    client.post(f'/threads/connections/{conn["id"]}/publishing',headers=owner,json={'enabled':True})
    pid,_,_=ready(client,owner,worker,conn['id']);mock_threads['read_fail']=True
    data=client.post(f'/threads/publications/{pid}/execute',headers=worker).json()
    assert data['publish_status']=='PUBLISHED_UNVERIFIED' and data['verification_status']=='NOT_VERIFIED'
    n=len(mock_threads['calls']);mock_threads['read_fail']=False
    assert client.post(f'/threads/publications/{pid}/reconcile',headers=worker).json()['verification_status']=='MOCK_READBACK_PASSED'
    assert all(m=='GET' for m,p in mock_threads['calls'][n:])


def test_tenant_rbac_kill_snapshot_guards(client,mock_threads,offline,monkeypatch):
    tid,owner,worker,_=tenant(client);conn,_,_=connect(client,owner)
    client.post(f'/threads/connections/{conn["id"]}/publishing',headers=owner,json={'enabled':True})
    pid,t,consent=ready(client,owner,worker,conn['id'])
    assert client.post(f'/threads/publications/{pid}/execute',headers=owner).status_code==403
    monkeypatch.setenv('MOS_THREADS_PUBLISH_ENABLED','false');n=len(mock_threads['calls'])
    assert client.post(f'/threads/publications/{pid}/execute',headers=worker).status_code==403
    assert len(mock_threads['calls'])==n
    with SessionLocal() as s:
        scope(s,tid)
        for query in ("UPDATE publications SET content_snapshot='swapped' WHERE id=:id",
                      "UPDATE publications SET immutable_content_hash='swapped' WHERE id=:id",
                      "UPDATE publications SET publish_status='PUBLISHED_VERIFIED' WHERE id=:id"):
            with pytest.raises(DBAPIError):s.execute(text(query),{'id':pid})
            s.rollback()


def test_pytest_cannot_enable_real_transport(monkeypatch):
    monkeypatch.setenv('MOS_ENV','test');monkeypatch.setenv('MOS_THREADS_HTTP_ENABLED','true')
    with pytest.raises(ThreadsFailure,match='LIVE_THREADS_DISABLED'):ThreadsAPI().request('POST','10001/threads',data={'text':'must not send'})


def test_missing_platform_configuration_no_http(client,monkeypatch):
    _,owner,_,_=tenant(client);monkeypatch.delenv('MOS_THREADS_APP_ID',raising=False)
    assert client.post('/threads/oauth/start',headers=owner).status_code==503


def test_tenant_account_publication_and_native_rls_isolation(client,mock_threads,offline):
    tid,owner,worker,_=tenant(client);conn,_,_=connect(client,owner)
    client.post(f'/threads/connections/{conn["id"]}/publishing',headers=owner,json={'enabled':True})
    pid,_,consent=ready(client,owner,worker,conn['id'])
    other_tid,other,other_worker,_=tenant(client,'Other tenant')
    assert client.get('/threads/connections',headers=other).json()==[]
    for path in (f'/threads/publications/{pid}/execute',f'/threads/publications/{pid}/reconcile'):
        assert client.post(path,headers=other_worker).status_code==404
    assert client.post(f'/threads/publications/{pid}/authorize',headers=other,json=consent).status_code==404
    assert client.delete(f'/threads/connections/{conn["id"]}',headers=other).status_code==404
    with SessionLocal() as s:
        scope(s,other_tid)
        assert s.get(ThreadsConnection,conn['id']) is None
        if engine.dialect.name=='postgresql':
            assert s.execute(text('SELECT id FROM threads_connections WHERE id=:id'),{'id':conn['id']}).first() is None
            assert s.execute(text('SELECT id FROM threads_oauth_states WHERE tenant_id=:tid'),{'tid':tid}).first() is None
            with pytest.raises(DBAPIError) as denied:
                s.execute(insert(ThreadsOAuthState.__table__).values(id='cross-tenant-state',tenant_id=tid,actor_id='forged',
                    token_hash='f'*64,browser_hash='c'*64,redirect_uri='https://invalid.test',expires_at=now()+timedelta(minutes=1),created_at=now()))
            assert denied.value.orig.sqlstate=='42501';s.rollback()


@pytest.mark.parametrize('failure',['expired','permission','revoked','changed_account','content_revision'])
def test_changed_security_evidence_blocks_new_posts(client,mock_threads,offline,failure):
    tid,owner,worker,manager=tenant(client);conn,_,_=connect(client,owner)
    client.post(f'/threads/connections/{conn["id"]}/publishing',headers=owner,json={'enabled':True})
    pid,t,consent=ready(client,owner,worker,conn['id'])
    assert client.post(f'/threads/publications/{pid}/authorize',headers=manager,json=consent).status_code==403
    if failure=='expired':
        with SessionLocal() as s:
            scope(s,tid);item=s.get(ThreadsConnection,conn['id']);item.token_expires_at=now()-timedelta(seconds=1);s.commit()
    elif failure=='permission':mock_threads['scenario']='permission'
    elif failure=='revoked':client.delete(f'/threads/connections/{conn["id"]}',headers=owner)
    elif failure=='changed_account':mock_threads['account']='99999'
    else:
        from test_quality_revisions import edit_payload
        r=client.get(f'/tasks/{t}/revisions',headers=owner).json()['revisions'][0]
        assert client.post(f'/tasks/{t}/revisions',headers=owner,json=edit_payload(r)).status_code==201
    before=mock_threads['calls'].count(('POST','/10001/threads'))
    response=client.post(f'/threads/publications/{pid}/execute',headers=worker)
    assert response.status_code in {200,403,409}
    assert mock_threads['calls'].count(('POST','/10001/threads'))==before


def test_oauth_operator_revoked_and_state_immutable(client,mock_threads):
    tid,owner,worker,_=tenant(client)
    result=client.post('/threads/oauth/start',headers=owner);state=parse_qs(urlsplit(result.json()['authorization_url']).query)['state'][0]
    browser=result.cookies['mos_threads_browser']
    with SessionLocal() as s:
        scope(s,tid);c=s.scalar(select(Credential).where(Credential.token_hash==digest(owner['Authorization'][7:])))
        c.revoked=True;s.commit()
    assert client.get('/threads/oauth/callback',params={'state':state,'code':'x'},headers={'Cookie':'mos_threads_browser='+browser}).status_code==400
    assert mock_threads['calls']==[]


def test_tokens_and_oauth_parameters_redacted(monkeypatch):
    from app.operations import redact
    monkeypatch.setenv('MOS_THREADS_APP_SECRET','synthetic-app-secret')
    value=redact('https://example.test/callback?code=secret-code&state=secret-state&access_token=secret-token&client_secret=synthetic-app-secret')
    assert all(x not in value for x in ['secret-code','secret-state','secret-token','synthetic-app-secret'])


def test_long_token_refresh_age_and_bound_identity(client,mock_threads):
    tid,owner,worker,_=tenant(client);conn,_,_=connect(client,owner)
    n=len(mock_threads['calls'])
    assert client.post(f'/threads/connections/{conn["id"]}/refresh',headers=owner).status_code==409
    assert len(mock_threads['calls'])==n
    with SessionLocal() as s:
        scope(s,tid);item=s.get(ThreadsConnection,conn['id']);item.token_issued_at=now()-timedelta(hours=25);s.commit()
    assert client.post(f'/threads/connections/{conn["id"]}/refresh',headers=owner).status_code==200
    assert ('GET','/refresh_access_token') in mock_threads['calls']


def test_consumed_state_cannot_be_reset_and_ciphertext_tamper_fails(client,mock_threads):
    tid,owner,worker,_=tenant(client);conn,state,_=connect(client,owner)
    with SessionLocal() as s:
        scope(s,tid)
        with pytest.raises(DBAPIError):s.execute(text('UPDATE threads_oauth_states SET used_at=NULL WHERE token_hash=:hash'),{'hash':digest(state)})
        s.rollback();item=s.get(ThreadsConnection,conn['id'])
        bad=item.token_ciphertext[:-10]+'invalid___'
        with pytest.raises(ThreadsFailure):unseal(bad,tid,item.id)


@pytest.mark.parametrize('confirmation',[False,1,'true',None])
def test_public_post_requires_explicit_boolean_confirmation(confirmation):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):publisher.Consent.model_validate({'connection_id':'c','threads_user_id':'1',
        'revision_id':'r','content_sha256':'h','confirm_public_post':confirmation})


def test_pending_container_resumes_same_id_without_second_creation(client,mock_threads,offline):
    tid,owner,worker,_=tenant(client);conn,_,_=connect(client,owner)
    client.post(f'/threads/connections/{conn["id"]}/publishing',headers=owner,json={'enabled':True})
    pid,_,_=ready(client,owner,worker,conn['id']);mock_threads['container_status']='IN_PROGRESS'
    assert client.post(f'/threads/publications/{pid}/execute',headers=worker).json()['publish_status']=='CONTAINER_CREATED'
    assert mock_threads['calls'].count(('POST','/10001/threads_publish'))==0
    mock_threads['container_status']='FINISHED'
    assert client.post(f'/threads/publications/{pid}/execute',headers=worker).json()['published_media_id']=='30001'
    assert mock_threads['calls'].count(('POST','/10001/threads'))==1
    assert mock_threads['calls'].count(('POST','/10001/threads_publish'))==1


@pytest.mark.parametrize('status,expected',[('EXPIRED','MANUAL_REQUIRED'),('ERROR','MANUAL_REQUIRED'),('PUBLISHED','RECONCILIATION_REQUIRED')])
def test_nonpublishable_container_never_reposts(client,mock_threads,offline,status,expected):
    tid,owner,worker,_=tenant(client);conn,_,_=connect(client,owner)
    client.post(f'/threads/connections/{conn["id"]}/publishing',headers=owner,json={'enabled':True})
    pid,_,_=ready(client,owner,worker,conn['id']);mock_threads['container_status']=status
    assert client.post(f'/threads/publications/{pid}/execute',headers=worker).json()['publish_status']==expected
    assert mock_threads['calls'].count(('POST','/10001/threads_publish'))==0


@pytest.mark.parametrize('changed',['worker','owner','task_approval'])
def test_rechecks_committed_security_after_dispatch_marker(client,mock_threads,offline,monkeypatch,changed):
    from app.models import Task
    tid,owner,worker,_=tenant(client);conn,_,_=connect(client,owner)
    client.post(f'/threads/connections/{conn["id"]}/publishing',headers=owner,json={'enabled':True})
    pid,t,_=ready(client,owner,worker,conn['id'])
    original=publisher.preflight;calls=[]
    def change_before_send(s,c,p,api):
        calls.append(1)
        if len(calls)==2:
            # Core UPDATE leaves existing ORM identities stale, reproducing a commit-boundary revocation.
            if changed=='task_approval':s.execute(update(Task.__table__).where(Task.id==t).values(status='PENDING_APPROVAL'))
            else:
                actor=c.id if changed=='worker' else p.authorized_by
                s.execute(update(Credential.__table__).where(Credential.id==actor).values(revoked=True))
        return original(s,c,p,api)
    monkeypatch.setattr(publisher,'preflight',change_before_send)
    assert client.post(f'/threads/publications/{pid}/execute',headers=worker).status_code in {403,409}
    assert mock_threads['calls'].count(('POST','/10001/threads'))==0
