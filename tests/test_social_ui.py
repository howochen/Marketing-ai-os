"""Browser session, setup, consent and bounded credential maintenance. All providers are Mock."""
import os
from datetime import timedelta
import pytest
from sqlalchemy import select
from app.database import SessionLocal,scope
from app.models import ThreadsConnection,Publication,now
from app.main import app
from app import threads_routes as routes
from app.browser_session import USER_COOKIE,ADMIN_COOKIE
from conftest import tenant,ADMIN
from test_agent_runtime import offline
from test_threads_publisher import mock_threads,connect,ready

ORIGIN={'Origin':'http://testserver'}


def ui_login(client,tid):
    challenge=client.post('/admin/login-challenges',headers=ADMIN,json={'tenant_id':tid,'subject':'ui-owner'}).json()['token']
    result=client.post('/ui/session',headers=ORIGIN,json={'token':challenge})
    assert result.status_code==200,result.text
    session=client.get('/ui/session').json()
    return {**ORIGIN,'X-CSRF-Token':session['csrf']},challenge,result


def test_browser_login_cookie_csrf_expiry_logout(client):
    tid,_,_,_=tenant(client);headers,challenge,result=ui_login(client,tid)
    assert result.json()=={'signed_in':True} and 'access_token' not in result.text
    assert 'HttpOnly' in result.headers['set-cookie'] and 'SameSite=lax' in result.headers['set-cookie']
    assert result.headers['cache-control']=='no-store'
    assert client.get('/ui/session').json()['tenant_id']==tid
    assert client.post('/ui/session',headers=ORIGIN,json={'token':challenge}).status_code==401
    assert client.delete('/ui/session').status_code==403
    assert client.delete('/ui/session',headers={**headers,'Origin':'https://attacker.test'}).status_code==403
    assert client.delete('/ui/session',headers=headers).status_code==200
    assert client.get('/ui/session').status_code==401


def test_login_requires_same_origin_and_shell_has_no_secrets(client):
    tid,_,_,_=tenant(client)
    assert client.post('/ui/session',json={'token':'x'*48}).status_code==403
    r=client.get('/app/threads');assert r.status_code==200
    assert 'script-src \'self\'' in r.headers['content-security-policy']
    assert 'frame-ancestors \'none\'' in r.headers['content-security-policy']
    assert 'no-store' in r.headers['cache-control']
    assert os.environ['MOS_ADMIN_KEY'] not in r.text


def test_admin_setup_is_separate_and_only_returns_presence(client,monkeypatch):
    tid,owner,_,_=tenant(client)
    assert client.get('/ui/admin/status',headers=owner).status_code==403
    secret=os.environ['MOS_ADMIN_KEY']
    response=client.post('/ui/admin/login',headers=ORIGIN,json={'secret':secret})
    assert response.status_code==200 and secret not in response.text
    token=response.json()['csrf'];headers={**ORIGIN,'X-CSRF-Token':token}
    monkeypatch.setenv('MOS_THREADS_APP_SECRET','synthetic-ui-secret')
    monkeypatch.setenv('MOS_PUBLIC_URL','https://controlled.example')
    monkeypatch.setenv('MOS_THREADS_REDIRECT_URI','https://controlled.example/threads/oauth/callback')
    data=client.get('/ui/admin/status').json()
    assert data['redirect_uri']=='https://controlled.example/threads/oauth/callback'
    assert data['checks']['app_secret'] and data['secret_store_database_ready']
    assert 'synthetic-ui-secret' not in str(data) and secret not in str(data)
    assert data['app_review']=='NOT_VERIFIED' and data['external_callback_reachability']=='NOT_VERIFIED'
    assert client.post('/ui/admin/diagnostics',headers={**headers,'Origin':'https://controlled.example'}).json()['external_probe']=='NOT_RUN_IN_TESTS'
    assert client.delete('/ui/admin/session',headers={**headers,'Origin':'https://controlled.example'}).status_code==200
    assert client.get('/ui/admin/status').status_code==403


def test_cookie_oauth_same_browser_returns_ui_not_tokens(client,mock_threads):
    tid,owner,_,_=tenant(client);headers,_,_=ui_login(client,tid)
    from urllib.parse import urlsplit,parse_qs
    start=client.post('/threads/oauth/start',headers=headers)
    assert start.status_code==200,start.text
    state=parse_qs(urlsplit(start.json()['authorization_url']).query)['state'][0]
    nonce=start.cookies['mos_threads_browser']
    r=client.get('/threads/oauth/callback',params={'state':state,'code':'synthetic-code'},headers={'Cookie':f'{USER_COOKIE}={client.cookies[USER_COOKIE]}; mos_threads_browser={nonce}'},follow_redirects=False)
    assert r.status_code==303 and r.headers['location']=='/app/threads?connected=1'
    assert 'synthetic-long-token' not in r.text
    assert client.get('/threads/connections').json()[0]['threads_user_id']=='10001'
    bad=client.get('/threads/oauth/callback',params={'state':'bad','code':'sensitive-code'},follow_redirects=False)
    assert bad.status_code==303 and 'sensitive-code' not in bad.headers['location']


def test_ui_preview_never_dispatches_and_tenant_filter(client,mock_threads,offline):
    tid,owner,worker,_=tenant(client);conn,_,_=connect(client,owner)
    pid,_,_=ready(client,owner,worker,conn['id'])
    headers,_,_=ui_login(client,tid)
    before=list(mock_threads['calls'])
    data=client.get('/ui/publications').json()['publications']
    assert len(data)==1 and data[0]['id']==pid and data[0]['content_approved']
    assert client.get('/app/publications').status_code==200 and mock_threads['calls']==before
    assert client.get('/ui/setup').json()['publishing_enabled'] is True
    other_tid,other,_,_=tenant(client,'Other UI')
    assert client.get('/ui/publications',headers=other).json()['publications']==[]


def test_ui_explicit_publish_reuses_worker_and_is_idempotent(client,mock_threads,offline):
    tid,owner,worker,_=tenant(client);conn,_,_=connect(client,owner)
    client.post(f'/threads/connections/{conn["id"]}/publishing',headers=owner,json={'enabled':True})
    pid,_,consent=ready(client,owner,worker,conn['id'])
    headers,_,_=ui_login(client,tid)
    assert client.post(f'/ui/publications/{pid}/publish',json=consent).status_code==403
    false={**consent,'confirm_public_post':False}
    assert client.post(f'/ui/publications/{pid}/publish',headers=headers,json=false).status_code==422
    r=client.post(f'/ui/publications/{pid}/publish',headers=headers,json=consent)
    assert r.status_code==200,r.text
    assert r.json()['verification_status']=='MOCK_READBACK_PASSED'
    assert client.post(f'/ui/publications/{pid}/publish',headers=headers,json=consent).status_code==200
    assert mock_threads['calls'].count(('POST','/10001/threads_publish'))==1


def test_connection_failure_immediately_disables_publish(client,mock_threads):
    tid,owner,_,_=tenant(client);conn,_,_=connect(client,owner)
    client.post(f'/threads/connections/{conn["id"]}/publishing',headers=owner,json={'enabled':True})
    mock_threads['scenario']='permission'
    assert client.post(f'/threads/connections/{conn["id"]}/check',headers=owner).status_code==409
    with SessionLocal() as s:
        scope(s,tid);item=s.get(ThreadsConnection,conn['id'])
        assert not item.publishing_enabled and item.connection_status=='REAUTH_REQUIRED' and item.maintenance_error=='PERMISSION_DENIED'


@pytest.mark.parametrize('scenario',['normal','permission'])
def test_maintenance_bounded_and_never_publishes(client,mock_threads,monkeypatch,scenario):
    tid,owner,worker,_=tenant(client);conn,_,_=connect(client,owner)
    monkeypatch.setenv('MOS_THREADS_MAINTENANCE_ENABLED','true')
    with SessionLocal() as s:
        scope(s,tid);item=s.get(ThreadsConnection,conn['id'])
        item.token_issued_at=now()-timedelta(hours=25);item.token_expires_at=now()+timedelta(days=2);item.next_maintenance_at=None;s.commit()
    mock_threads['scenario']=scenario
    result=client.post('/maintenance/threads',headers=worker)
    assert result.status_code==200,result.text
    assert result.json()['refreshed' if scenario=='normal' else 'failed']==1
    n=len(mock_threads['calls'])
    assert client.post('/maintenance/threads',headers=worker).status_code==200 and len(mock_threads['calls'])==n
    assert not any(path.endswith('/threads_publish') or path.endswith('/threads') for method,path in mock_threads['calls'])


def test_maintenance_interruption_freezes_instead_of_retries(client,mock_threads,monkeypatch):
    tid,owner,worker,_=tenant(client);conn,_,_=connect(client,owner)
    monkeypatch.setenv('MOS_THREADS_MAINTENANCE_ENABLED','true')
    with SessionLocal() as s:
        scope(s,tid);item=s.get(ThreadsConnection,conn['id']);item.token_issued_at=now()-timedelta(hours=25)
        item.token_expires_at=now()+timedelta(days=2);item.next_maintenance_at=now()-timedelta(seconds=1);item.maintenance_error='MAINTENANCE_IN_PROGRESS';s.commit()
    n=len(mock_threads['calls'])
    assert client.post('/maintenance/threads',headers=worker).json()['failed']==1
    assert len(mock_threads['calls'])==n


def test_untrusted_public_url_not_reflected_as_redirect(client,monkeypatch):
    monkeypatch.setenv('MOS_PUBLIC_URL','https://user:secret@attacker.example/path')
    response=client.get('/ui/admin/status',headers=ADMIN)
    assert response.json()['redirect_uri'] is None
    assert 'secret@attacker' not in response.text


def test_forged_admin_cookie_and_cross_tenant_connection_denied(client,mock_threads):
    tid,owner,worker,_=tenant(client);conn,_,_=connect(client,owner)
    other,_,_,_=tenant(client,'Other synthetic workspace')
    headers,_,_=ui_login(client,other)
    assert client.post(f'/threads/connections/{conn["id"]}/check',headers=headers).status_code==404
    assert client.delete(f'/threads/connections/{conn["id"]}',headers=headers).status_code==404
    client.cookies.set(ADMIN_COOKIE,'1:forged-nonce:forged-signature')
    assert client.get('/ui/admin/status').status_code==403
    assert client.post(f'/threads/connections/{conn["id"]}/check',headers=worker).status_code==403


def test_expired_connection_stops_publishing_without_provider_call(client,mock_threads):
    tid,owner,_,_=tenant(client);conn,_,_=connect(client,owner)
    with SessionLocal() as s:
        scope(s,tid);item=s.get(ThreadsConnection,conn['id']);item.token_expires_at=now()-timedelta(seconds=1);item.publishing_enabled=True;s.commit()
    calls=len(mock_threads['calls'])
    assert client.post(f'/threads/connections/{conn["id"]}/check',headers=owner).status_code==409
    assert len(mock_threads['calls'])==calls
    with SessionLocal() as s:
        scope(s,tid);item=s.get(ThreadsConnection,conn['id']);assert not item.publishing_enabled and item.connection_status=='REAUTH_REQUIRED'
