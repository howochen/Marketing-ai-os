"""Synthetic signed forms through real HTTP/database. Never evidence of Meta delivery."""
import base64
import hashlib
import hmac
import json
import os
import itertools
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import urlencode,urlsplit
import pytest
from sqlalchemy import select,text
from sqlalchemy.exc import DBAPIError
from conftest import tenant,ADMIN
from test_threads_publisher import mock_threads,connect
from test_content_workbench import BRIEF,DRAFT
from app import threads_privacy as privacy
from app.database import SessionLocal,scope,engine
from app.models import ThreadsConnection,ThreadsPrivacyAction,ThreadsPrivacyRequest,Publication,now
from app.threads_api import ThreadsFailure
from app import threads_routes

BASE='/threads/privacy/'
SEQUENCE=itertools.count(1)


def form(user='10001',issued=None,secret=None,**extra):
    data={'algorithm':'HMAC-SHA256','user_id':user,'issued_at':int(os.environ.get('MOS_PRIVACY_TEST_ISSUED',str(int(now().timestamp())))) if issued is None else issued,**extra}
    payload=base64.urlsafe_b64encode(json.dumps(data,separators=(',',':')).encode()).decode().rstrip('=')
    sig=hmac.new((secret or os.environ['MOS_THREADS_APP_SECRET']).encode(),payload.encode(),hashlib.sha256).digest()
    signed=base64.urlsafe_b64encode(sig).decode().rstrip('=')+'.'+payload
    return {'signed_request':signed}


def post(client,kind='data-deletion',body=None):
    return client.post(BASE+kind,content=urlencode(body or form()),headers={'Content-Type':'application/x-www-form-urlencoded'})


@pytest.fixture
def privacy_env(mock_threads,monkeypatch):
    monkeypatch.setenv('MOS_PUBLIC_URL','https://testserver')
    monkeypatch.setenv('MOS_PRIVACY_TEST_ISSUED',str(int(now().timestamp())+next(SEQUENCE)))
    return mock_threads


def ready(client,owner,worker,cid):
    task=client.post('/ui/content/tasks',headers=owner,json={'brief':BRIEF,'idempotency_key':'privacy-manual-task'}).json()['id']
    r=client.post('/ui/content/tasks/'+task+'/manual-draft',headers=owner,json={'draft':DRAFT,'idempotency_key':'privacy-manual-draft'}).json()
    rid=r['revision_id'];assert client.post(f'/tasks/{task}/revisions/{rid}/approve',headers=owner).status_code==200
    p=client.post(f'/tasks/{task}/publication-request',headers=owner,json={'platform':'threads','revision_id':rid,'idempotency_key':'privacy-publication'}).json()
    from app.threads_publisher import content_hash
    consent={'connection_id':cid,'threads_user_id':'10001','revision_id':rid,'content_sha256':content_hash(DRAFT['draft_text']),'confirm_public_post':True}
    result=client.post('/threads/publications/'+p['id']+'/authorize',headers=owner,json=consent);assert result.status_code==200,result.text
    return p['id'],task,consent


def test_three_urls_and_safe_get(client,privacy_env):
    assert privacy.urls('https://testserver')=={'redirect':'https://testserver/threads/oauth/callback','deauthorize':'https://testserver'+BASE+'deauthorize','data_deletion':'https://testserver'+BASE+'data-deletion'}
    for path in ('deauthorize','data-deletion'):
        r=client.get(BASE+path);assert r.status_code==200 and r.json()['get_does_not_revoke_or_delete']
        assert r.headers['cache-control']=='no-store'


@pytest.mark.parametrize('change',[{'secret':'not-the-app-secret'},{'app_id':'99999'},{'algorithm':'none'},
    {'user':'not-numeric'},{'issued':True},{'issued':-1},{'issued':99999999999},{'issued':1}])
def test_forged_wrong_app_or_stale_is_rejected(client,privacy_env,change):
    _,owner,_,_=tenant(client);conn,_,_=connect(client,owner)
    r=post(client,body=form(**change));assert r.status_code==403,r.text
    with SessionLocal() as s:
        scope(s,conn['tenant_id']);c=s.get(ThreadsConnection,conn['id']);assert c.token_ciphertext and c.connection_status=='ACTIVE'


@pytest.mark.parametrize('body',['signed_request=bad','signed_request=a.b&signed_request=a.b','signed_request=a.b&tenant_id=x'])
def test_bad_form_does_not_echo_secrets(client,privacy_env,body,caplog):
    r=client.post(BASE+'data-deletion',content=body,headers={'Content-Type':'application/x-www-form-urlencoded'})
    assert r.status_code==403 and body not in r.text
    assert os.environ['MOS_THREADS_APP_SECRET'] not in caplog.text


def test_deauthorize_disables_exact_app_account_and_pending_work(client,privacy_env):
    tid,owner,worker,_=tenant(client);conn,_,_=connect(client,owner);pid,taskid,_=ready(client,owner,worker,conn['id'])
    _,other,_,_=tenant(client);other_conn,_,_=connect(client,other)
    with SessionLocal() as s:
        scope(s,other_conn['tenant_id']);c=s.get(ThreadsConnection,other_conn['id']);c.meta_app_id='other-app';c.callback_lookup=privacy.lookup('other-app','10001');s.commit()
    r=post(client,'deauthorize');assert r.status_code==200,r.text
    with SessionLocal() as s:
        scope(s,tid);c=s.get(ThreadsConnection,conn['id']);p=s.get(Publication,pid)
        assert c.token_ciphertext is None and c.connection_status=='REVOKED' and not c.publishing_enabled
        assert p.publish_status=='AUTH_REQUIRED' and c.username=='synthetic_brand'
        scope(s,other_conn['tenant_id']);assert s.get(ThreadsConnection,other_conn['id']).token_ciphertext
    assert client.post('/threads/publications/'+pid+'/execute',headers=worker).status_code in (403,409)
    assert not any('threads_publish' in path for method,path in privacy_env['calls'])


def test_deletion_status_idempotency_and_no_false_completion(client,privacy_env):
    tid,owner,_,_=tenant(client);conn,_,_=connect(client,owner);body=form()
    first=post(client,body=body);assert first.status_code==200,first.text
    receipt=first.json();assert set(receipt)=={'url','confirmation_code'}
    assert post(client,body=body).json()==receipt
    path=urlsplit(receipt['url']).path
    status=client.get(path,headers={'Accept':'application/json'});assert status.status_code==200
    assert status.json()['status']=='REVIEW_REQUIRED' and not status.json()['complete_data_erasure']
    assert '10001' not in status.text and tid not in status.text
    page=client.get(path);assert page.status_code==200 and '未宣稱完整刪除' in page.text
    assert page.headers['referrer-policy']=='no-referrer'
    with SessionLocal() as s:
        scope(s,tid);c=s.get(ThreadsConnection,conn['id'])
        assert c.token_ciphertext is None and not c.username and c.granted_scopes==[] and c.threads_user_id.startswith('deleted:')
        assert len(s.scalars(select(ThreadsPrivacyAction)).all())==1
    assert client.get(BASE+'status/'+'a'*64).status_code==404
    assert client.post('/ui/admin/threads/privacy/lookup',headers=owner,json={'confirmation_code':receipt['confirmation_code']}).status_code==403
    inspected=client.post('/ui/admin/threads/privacy/lookup',headers=ADMIN,json={'confirmation_code':receipt['confirmation_code']})
    assert inspected.status_code==200 and inspected.json()['signature']=='APP_SECRET_HMAC_VERIFIED'
    assert not inspected.json()['official_origin_attested']


def test_known_replay_does_not_revoke_a_new_connection(client,privacy_env):
    tid,owner,_,_=tenant(client);connect(client,owner);body=form()
    receipt=post(client,body=body).json()
    fresh,_,_=connect(client,owner)
    assert post(client,body=body).json()==receipt
    with SessionLocal() as s:
        scope(s,tid);assert s.get(ThreadsConnection,fresh['id']).token_ciphertext


@pytest.mark.parametrize('setting',['MOS_THREADS_APP_ID','MOS_THREADS_APP_SECRET','MOS_PUBLIC_URL'])
def test_unconfigured_app_never_accepts_callback(client,privacy_env,monkeypatch,setting):
    body=form();monkeypatch.delenv(setting)
    assert post(client,body=body).status_code==503


def test_json_body_is_not_a_signed_form(client,privacy_env):
    r=client.post(BASE+'data-deletion',json=form());assert r.status_code==415


def test_one_verified_user_revokes_all_own_tenants_but_no_other_user(client,privacy_env):
    records=[]
    for _ in range(2):
        tid,owner,_,_=tenant(client);c,_,_=connect(client,owner);records.append((tid,c['id']))
    from app.models import RateLimit
    from sqlalchemy import delete
    with SessionLocal() as s:s.execute(delete(RateLimit));s.commit()
    _,third,_,_=tenant(client);different,_,_=connect(client,third)
    with SessionLocal() as s:
        scope(s,different['tenant_id']);c=s.get(ThreadsConnection,different['id']);c.threads_user_id='10002';c.callback_lookup=privacy.lookup('12345','10002');s.commit()
    assert post(client).status_code==200
    for tid,cid in records:
        with SessionLocal() as s:
            scope(s,tid);assert s.get(ThreadsConnection,cid).token_ciphertext is None
    with SessionLocal() as s:
        scope(s,different['tenant_id']);assert s.get(ThreadsConnection,different['id']).token_ciphertext


def test_parallel_duplicates_do_not_repeat_processing(client,privacy_env):
    tid,owner,_,_=tenant(client);connect(client,owner);body=form()
    with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(lambda _:post(client,body=body),range(2)))
    assert all(r.status_code==200 for r in responses),[r.text for r in responses]
    assert responses[0].json()==responses[1].json()
    with SessionLocal() as s:
        scope(s,tid);assert len(s.scalars(select(ThreadsPrivacyAction)).all())==1


def test_newer_authorization_is_not_removed_by_old_event(client,privacy_env):
    tid,owner,_,_=tenant(client);conn,_,_=connect(client,owner)
    issued=int(now().timestamp())-5
    assert post(client,body=form(issued=issued)).status_code==200
    with SessionLocal() as s:
        scope(s,tid);assert s.get(ThreadsConnection,conn['id']).token_ciphertext
        a=s.scalar(select(ThreadsPrivacyAction));assert a.state=='NEW_AUTHORIZATION_PRESERVED'


def test_inflight_results_preserved_not_falsely_cancelled(client,privacy_env):
    tid,owner,worker,_=tenant(client);conn,_,_=connect(client,owner);pid,_,_=ready(client,owner,worker,conn['id'])
    with SessionLocal() as s:
        scope(s,tid);p=s.get(Publication,pid);p.publish_status='CREATING_CONTAINER';p.dispatch_at=now();p.attempt_count=1;s.commit()
    assert post(client).status_code==200
    with SessionLocal() as s:
        scope(s,tid);p=s.get(Publication,pid);assert p.publish_status=='RECONCILIATION_REQUIRED' and p.attempt_count==1


def test_legacy_app_identity_requires_review_not_unverified_deletion(client,privacy_env):
    tid,owner,_,_=tenant(client);conn,_,_=connect(client,owner)
    with SessionLocal() as s:
        scope(s,tid);c=s.get(ThreadsConnection,conn['id']);c.meta_app_id=None;c.callback_lookup=None;s.commit()
        with pytest.raises(ThreadsFailure):threads_routes.token_for(c)
    assert post(client).status_code==200
    with SessionLocal() as s:
        scope(s,tid);assert s.get(ThreadsConnection,conn['id']).token_ciphertext
        assert s.scalar(select(ThreadsPrivacyAction)).state=='APP_BINDING_REVIEW_REQUIRED'
    assert client.post('/threads/connections/'+conn['id']+'/check',headers=owner).status_code==200
    with SessionLocal() as s:
        scope(s,tid);assert s.get(ThreadsConnection,conn['id']).meta_app_id=='12345'


def test_review_is_owner_scoped_append_once_and_not_completion(client,privacy_env):
    tid,owner,_,reviewer=tenant(client);_,other,_,_=tenant(client);connect(client,owner);post(client)
    entry=client.get(BASE+'actions',headers=owner).json()['actions'][0]
    path=BASE+'actions/'+entry['id']+'/review';body={'reason':'Review only: retained tenant content and backups require administrator policy.'}
    assert client.post(path,headers=reviewer,json=body).status_code==403
    assert client.post(path,headers=other,json=body).status_code==404
    r=client.post(path,headers=owner,json=body);assert r.status_code==200 and not r.json()['complete_data_erasure']
    assert client.post(path,headers=owner,json=body).status_code==409
    assert client.get(BASE+'actions',headers=other).json()['actions']==[]


def test_crash_recovery_uses_persisted_scope_and_is_idempotent(client,privacy_env,monkeypatch):
    tid,owner,_,_=tenant(client);conn,_,_=connect(client,owner)
    original=privacy.disable
    def fail(*args,**kwargs):raise RuntimeError('secret-never-echo')
    monkeypatch.setattr(privacy,'disable',fail)
    issued=int(os.environ['MOS_PRIVACY_TEST_ISSUED'])
    r=post(client,body=form(issued=issued));assert r.status_code==503 and 'secret-never-echo' not in r.text
    event=privacy.digest(json.dumps(['12345','deletion',privacy.lookup('12345','10001'),issued],separators=(',',':')))
    with SessionLocal() as s:
        scope(s,token_hash=event)
        record=s.scalar(select(ThreadsPrivacyRequest).where(ThreadsPrivacyRequest.request_hash==event));assert record.state=='RECONCILIATION_REQUIRED'
    monkeypatch.setattr(privacy,'disable',original)
    path='/ui/admin/threads/privacy/recover'
    assert client.post(path,headers=owner,json={'request_hash':event}).status_code==403
    assert client.post(path,headers=ADMIN,json={'request_hash':event}).status_code==200
    assert client.post(path,headers=ADMIN,json={'request_hash':event}).status_code==200
    with SessionLocal() as s:
        scope(s,tid);assert s.get(ThreadsConnection,conn['id']).token_ciphertext is None


def test_raw_rls_and_immutable_request_binding(client,privacy_env):
    tid,owner,_,_=tenant(client);connect(client,owner);result=post(client).json()
    with SessionLocal() as s:
        scope(s,tid);a=s.scalar(select(ThreadsPrivacyAction));aid=a.id
        event=a.request_hash;rid=a.request_id
        with pytest.raises(DBAPIError):s.execute(text('UPDATE threads_privacy_actions SET connection_id=:id WHERE id=:aid'),{'id':'forged','aid':aid})
        s.rollback()
        scope(s,token_hash=event)
        with pytest.raises(DBAPIError):s.execute(text("UPDATE threads_privacy_requests SET app_id='forged' WHERE id=:id"),{'id':rid})
        s.rollback();scope(s,token_hash=event)
        with pytest.raises(DBAPIError):s.execute(text("UPDATE threads_privacy_requests SET state='COMPLETED' WHERE id=:id"),{'id':rid})
        s.rollback()
    if engine.dialect.name=='postgresql':
        with SessionLocal() as s:
            scope(s,'unrelated');assert s.execute(text('SELECT id FROM threads_privacy_actions WHERE id=:id'),{'id':aid}).first() is None
            assert s.execute(text('SELECT id FROM threads_privacy_requests')).first() is None
