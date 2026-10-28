"""Synthetic OAuth redirects, token exchange, refresh and free eligibility; never Live."""
import base64
import hashlib
import json
from datetime import timedelta
from urllib.parse import parse_qs,urlsplit
import httpx
import pytest
from sqlalchemy import select
from conftest import ADMIN,tenant,bearer
from test_threads_publisher import mock_threads
from test_automation import env
from test_gemini import google,configured,KEY,PROJECT
from app import google_oauth as oauth
from app.database import SessionLocal,scope
from app.models import AITestPermit,AutomationPolicy,ThreadsConnection,now
from app.main import app
from app.openai_provider import ProviderFailure

CLIENT='12345-synthetic.apps.googleusercontent.com'
SECRET='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et'
ACCESS='ya29.synthetic-google-access-token'
REFRESH='1//synthetic-google-refresh-token'


@pytest.fixture
def oauth_http(monkeypatch):
    state={'requests':[],'error':None}
    def handle(r):
        assert r.url==httpx.URL('https://oauth2.googleapis.com/token') and r.method=='POST'
        assert SECRET not in str(r.url) and ACCESS not in str(r.url) and REFRESH not in str(r.url)
        data={k:v[0] for k,v in parse_qs(r.content.decode()).items()};state['requests'].append(data)
        if state.get('hook'):state['hook']()
        if state['error']:return httpx.Response(400,json={'error':state['error'],'error_description':SECRET})
        result={'access_token':ACCESS,'expires_in':3600,'token_type':'Bearer','scope':' '.join(sorted(oauth.SCOPES))}
        if data['grant_type']=='authorization_code':result['refresh_token']=REFRESH
        return httpx.Response(200,json=result)
    http=oauth.GoogleHTTP(httpx.MockTransport(handle));original=oauth.google
    app.dependency_overrides[original]=lambda:http;monkeypatch.setattr(oauth,'google',lambda:http)
    yield state,http
    app.dependency_overrides.pop(original,None)


def setup(client,env,google):
    tid,owner,p,old=configured(client,env,google);client.base_url='https://testserver'
    r=client.post('/ui/admin/google-client',headers=ADMIN,json={'tenant_id':tid,'client_id':CLIENT,'client_secret':SECRET})
    assert r.status_code==200 and SECRET not in r.text
    return tid,owner,p,old


def start(client,owner,p):
    r=client.post('/automation/policies/'+p['id']+'/google-start',headers=owner,json={});assert r.status_code==200,r.text
    q={k:v[0] for k,v in parse_qs(urlsplit(r.json()['authorization_url']).query).items()}
    assert q['access_type']=='offline' and q['code_challenge_method']=='S256' and set(q['scope'].split())==oauth.SCOPES
    assert SECRET not in r.text and KEY not in r.text and ACCESS not in r.text
    return q


def connect(client,owner,p):
    q=start(client,owner,p)
    r=client.get('/google/oauth/callback',headers=owner,params={'state':q['state'],'code':'synthetic-new-auth-code'},follow_redirects=False)
    assert r.status_code==303 and 'CONNECTED' in r.headers['location'],r.text
    return q


def test_official_oauth_exchange_encryption_and_automatic_free_check(client,env,google,oauth_http):
    tid,owner,p,_=setup(client,env,google);q=connect(client,owner,p)
    sent=oauth_http[0]['requests'][0]
    assert sent['client_secret']==SECRET and sent['redirect_uri']=='https://testserver/google/oauth/callback'
    challenge=base64.urlsafe_b64encode(hashlib.sha256(sent['code_verifier'].encode()).digest()).decode().rstrip('=')
    assert challenge==q['code_challenge']
    status=client.get('/automation/policies/'+p['id']+'/google-status',headers=owner).json();assert status['connected']
    checked=client.post('/automation/policies/'+p['id']+'/google-verify',headers=owner,json={})
    assert checked.status_code==200 and checked.json()['free_tier_status']=='CONFIRMED'
    assert all(method=='GET' for method,_,_ in google[0]['calls'])
    with SessionLocal() as s:
        scope(s,tid);rows=s.scalars(select(AITestPermit).where(AITestPermit.terms['kind'].as_string().in_(['GEMINI_GOOGLE_CLIENT','GEMINI_GOOGLE_AUTH','GEMINI_GOOGLE_GRANT']))).all()
        for row in rows:
            stored=json.dumps(row.outcome);assert ACCESS not in stored and REFRESH not in stored and SECRET not in stored
            visible=client.get('/ai-tests/'+row.id,headers=owner);assert visible.status_code==200
            assert all(value not in visible.text for value in [ACCESS,REFRESH,SECRET,'ciphertext'])


def test_owner_logout_does_not_destroy_google_refresh_authority(client,env,google,oauth_http,monkeypatch):
    tid,owner,p,_=setup(client,env,google);connect(client,owner,p)
    future=now()+timedelta(hours=2);monkeypatch.setattr(oauth,'now',lambda:future)
    assert client.delete('/ui/session',headers=owner).status_code==200
    with SessionLocal() as s:
        scope(s,tid);policy=s.get(AutomationPolicy,p['id']);assert oauth.access_token(s,policy)==ACCESS
        assert oauth.access_token(s,policy)==ACCESS
    assert len(oauth_http[0]['requests'])==2 and oauth_http[0]['requests'][-1]['grant_type']=='refresh_token'


def test_revoked_refresh_requires_reconnect_without_clearing_key(client,env,google,oauth_http,monkeypatch):
    tid,owner,p,_=setup(client,env,google);connect(client,owner,p);oauth_http[0]['error']='invalid_grant'
    future=now()+timedelta(hours=2);monkeypatch.setattr(oauth,'now',lambda:future)
    with SessionLocal() as s:
        scope(s,tid);policy=s.get(AutomationPolicy,p['id']);cipher=policy.key_ciphertext
        with pytest.raises(ProviderFailure,match='GOOGLE_RECONNECT_REQUIRED'):oauth.access_token(s,policy)
        assert s.get(AutomationPolicy,p['id']).key_ciphertext==cipher
        with pytest.raises(ProviderFailure):oauth.access_token(s,policy)
    assert len(oauth_http[0]['requests'])==2
    state=client.get('/automation/policies/'+p['id']+'/google-status',headers=owner).json();assert not state['connected'] and state['phase']=='RECONNECT_REQUIRED'


def test_denied_consent_and_replay_never_exchange_again(client,env,google,oauth_http):
    _,owner,p,_=setup(client,env,google);q=start(client,owner,p)
    r=client.get('/google/oauth/callback',headers=owner,params={'state':q['state'],'error':'access_denied','error_description':SECRET},follow_redirects=False)
    assert r.status_code==303 and 'GOOGLE_ACCESS_DENIED' in r.headers['location'] and SECRET not in r.headers['location']
    assert not oauth_http[0]['requests']
    assert client.get('/google/oauth/callback',headers=owner,params={'state':q['state'],'code':'replayed-code'},follow_redirects=False).status_code==303


def test_callback_binds_browser_tenant_and_one_use_state(client,env,google,oauth_http):
    _,owner,p,_=setup(client,env,google);q=start(client,owner,p);saved=client.cookies.get(oauth.COOKIE);_,other,_,_=tenant(client,name='Other Google tenant')
    assert client.get('/google/oauth/callback',headers=other,params={'state':q['state'],'code':'wrong-tenant'},follow_redirects=False).status_code==303
    client.cookies.clear()
    assert client.get('/google/oauth/callback',headers=owner,params={'state':q['state'],'code':'wrong-browser'},follow_redirects=False).status_code==303
    client.cookies.set(oauth.COOKIE,saved,path=oauth.CALLBACK)
    r=client.get('/google/oauth/callback',headers=owner,params={'state':q['state'],'code':'valid-new-code'},follow_redirects=False);assert r.status_code==303 and 'CONNECTED' in r.headers['location']
    assert client.get('/google/oauth/callback',headers=owner,params={'state':q['state'],'code':'replay'},follow_redirects=False).status_code==303
    assert len(oauth_http[0]['requests'])==1


def test_google_client_requires_admin_and_expires_state(client,env,google,oauth_http,monkeypatch):
    tid,owner,p,_=configured(client,env,google)
    assert client.post('/automation/policies/'+p['id']+'/google-start',headers=owner,json={}).status_code==503
    assert client.post('/ui/admin/google-client',headers=owner,json={'tenant_id':tid,'client_id':CLIENT,'client_secret':SECRET}).status_code==403
    client.base_url='https://testserver';assert client.post('/ui/admin/google-client',headers=ADMIN,json={'tenant_id':tid,'client_id':CLIENT,'client_secret':SECRET}).status_code==200
    q=start(client,owner,p);future=now()+timedelta(minutes=11);monkeypatch.setattr(oauth,'now',lambda:future)
    assert client.get('/google/oauth/callback',headers=owner,params={'state':q['state'],'code':'expired'},follow_redirects=False).status_code==303
    assert not oauth_http[0]['requests']


def test_disconnect_preserves_threads_and_gemini_key_and_blocks_free_status(client,env,google,oauth_http):
    tid,owner,p,_=setup(client,env,google);connect(client,owner,p)
    client.post('/automation/policies/'+p['id']+'/google-verify',headers=owner,json={})
    with SessionLocal() as s:
        scope(s,tid);key=s.get(AutomationPolicy,p['id']).key_ciphertext;threads=[(x.id,x.token_ciphertext) for x in s.scalars(select(ThreadsConnection))]
    r=client.post('/automation/policies/'+p['id']+'/google-disconnect',headers=owner,json={});assert r.status_code==200
    assert client.get('/automation/policies/'+p['id']+'/gemini-status',headers=owner).json()['free_tier_status']=='PENDING'
    with SessionLocal() as s:
        scope(s,tid);assert s.get(AutomationPolicy,p['id']).key_ciphertext==key
        assert [(x.id,x.token_ciphertext) for x in s.scalars(select(ThreadsConnection))]==threads
        with pytest.raises(ProviderFailure):oauth.access_token(s,s.get(AutomationPolicy,p['id']))


def test_google_verification_survives_new_owner_browser_session(client,env,google,oauth_http):
    tid,owner,p,_=setup(client,env,google);assert client.delete('/ui/session',headers=owner).status_code==200
    challenge=client.post('/admin/login-challenges',headers=ADMIN,json={'tenant_id':tid,'subject':'verified-owner'}).json()['token']
    replacement=bearer(client.post('/auth/login',json={'token':challenge}).json()['access_token'])
    connect(client,replacement,p)
    checked=client.post('/automation/policies/'+p['id']+'/google-verify',headers=replacement,json={})
    assert checked.status_code==200 and checked.json()['free_tier_status']=='CONFIRMED'


def test_single_generation_uses_server_google_grant_without_token_body(client,env,google,oauth_http,monkeypatch):
    from test_gemini import permit
    _,owner,p,_=setup(client,env,google);connect(client,owner,p)
    assert client.post('/automation/policies/'+p['id']+'/google-verify',headers=owner,json={}).json()['free_tier_status']=='CONFIRMED'
    test=permit(client,owner,p);monkeypatch.setenv('MOS_GEMINI_FREE_CALLS_ENABLED','true');monkeypatch.setenv('MOS_THREADS_PUBLISH_ENABLED','false')
    result=client.post('/ai-tests/'+test['id']+'/execute',headers=owner,json={})
    assert result.status_code==200 and result.json()['state']=='SETTLED'
    assert all(x not in result.text for x in [SECRET,ACCESS,REFRESH]) and not result.json()['threads_publication_authorized']


def test_disconnect_during_code_exchange_cannot_reactivate_grant(client,env,google,oauth_http):
    from app.models import Credential
    tid,owner,p,_=setup(client,env,google);q=start(client,owner,p)
    def revoke():
        with SessionLocal() as s:
            scope(s,tid);flow=oauth.record(s,tid,'GEMINI_GOOGLE_AUTH',p['id']);actor=s.get(Credential,flow.owner_id)
            oauth.disconnect(p['id'],actor,s)
    oauth_http[0]['hook']=revoke
    response=client.get('/google/oauth/callback',headers=owner,params={'state':q['state'],'code':'new-code'},follow_redirects=False)
    assert response.status_code==303 and 'GOOGLE_OPERATOR_REVOKED' in response.headers['location']
    assert not client.get('/automation/policies/'+p['id']+'/google-status',headers=owner).json()['connected']
