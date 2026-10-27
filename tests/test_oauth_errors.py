"""OAuth errors retain safe diagnostics, never provider text or authorization material."""
from urllib.parse import urlsplit,parse_qs
import httpx,pytest
from sqlalchemy import select,func
from conftest import tenant
from test_threads_publisher import mock_threads,connect
from test_social_ui import ui_login
from app.main import app
from app import threads_routes as routes
from app.threads_api import ThreadsAPI,ThreadsFailure
from app.database import SessionLocal,scope
from app.models import Audit,ThreadsOAuthState,ThreadsConnection
from app.browser_session import USER_COOKIE


@pytest.mark.parametrize('path,stage,code',[('/oauth/access_token','TOKEN_EXCHANGE',100),('/access_token','LONG_TOKEN',100),('/access_token','LONG_TOKEN',452),('/me','PROFILE',100),('/debug_token','PERMISSIONS',100)])
def test_browser_oauth_failure_is_specific_safe_and_not_replayed(client,mock_threads,monkeypatch,caplog,path,stage,code):
    monkeypatch.delenv('MOS_PUBLIC_URL',raising=False)
    tid,_,_,_=tenant(client);h,_,login=ui_login(client,tid)
    original=app.dependency_overrides[routes.api]();calls=[]
    secret='synthetic-provider-secret-code-and-token-never-output'
    def respond(req):
        calls.append(req.url.path)
        if req.url.path==path:return httpx.Response(400,json={'error':{'code':code,'error_subcode':99,'type':'OAuthException','fbtrace_id':'synthetic-trace','message':secret}})
        return original.transport.handle_request(req)
    app.dependency_overrides[routes.api]=lambda:ThreadsAPI(httpx.MockTransport(respond))
    started=client.post('/threads/oauth/start',headers=h);assert started.status_code==200,started.text
    state=parse_qs(urlsplit(started.json()['authorization_url']).query)['state'][0]
    cookies=USER_COOKIE+'='+login.cookies[USER_COOKIE]+'; mos_threads_browser='+started.cookies['mos_threads_browser']
    r=client.get('/threads/oauth/callback',params={'state':state,'code':'synthetic-one-use-code'},headers={'Cookie':cookies},follow_redirects=False)
    assert r.status_code==303
    assert parse_qs(urlsplit(r.headers['location']).query)=={'oauth_error':[stage],'meta_error':[str(code)]}
    assert secret not in r.text+str(r.headers)+caplog.text and state not in r.headers['location']
    assert 'mos_threads_browser=""' in r.headers['set-cookie']
    with SessionLocal() as s:
        scope(s,tid)
        row=s.scalar(select(ThreadsOAuthState).where(ThreadsOAuthState.tenant_id==tid));assert row.used_at
        failures=s.scalars(select(Audit.action).where(Audit.action.like('threads.oauth_failed.%'))).all()
        assert failures==['threads.oauth_failed.'+stage+'.CONTENT_REJECTED.'+str(code)]
        actions=s.scalars(select(Audit.action)).all()
        assert {'threads.oauth_subcode.99','threads.oauth_type.OAuthException','threads.oauth_trace.synthetic-trace'}<=set(actions)
        assert secret not in str(actions)
        assert s.scalar(select(func.count()).select_from(ThreadsConnection))==0
    count=len(calls)
    replay=client.get('/threads/oauth/callback',params={'state':state,'code':'synthetic-one-use-code'},headers={'Cookie':cookies},follow_redirects=False)
    assert replay.status_code==303 and parse_qs(urlsplit(replay.headers['location']).query)['oauth_error']==['SESSION_INVALID']
    assert len(calls)==count


def test_browser_binding_error_is_not_labeled_provider_failure(client):
    tid,_,_,_=tenant(client);_,_,login=ui_login(client,tid)
    r=client.get('/threads/oauth/callback',headers={'Cookie':USER_COOKIE+'='+login.cookies[USER_COOKIE]},follow_redirects=False)
    assert r.status_code==303 and parse_qs(urlsplit(r.headers['location']).query)=={'oauth_error':['BROWSER_BINDING']}


@pytest.mark.parametrize('code',[True,'synthetic-secret',-1,10000000000,{'message':'synthetic-secret'}])
def test_only_bounded_integer_provider_code_is_exposed(code):
    assert ThreadsFailure('CONTENT_REJECTED',provider_code=code).provider_code is None


def test_long_exchange_uses_official_query_token_and_keeps_encrypted_connection(client,mock_threads,caplog):
    tid,owner,_,_=tenant(client)
    original=app.dependency_overrides[routes.api]();exchanges=[]
    def respond(req):
        if req.url.path=='/access_token':
            assert req.method=='GET' and req.url.host=='graph.threads.com'
            assert req.url.params['grant_type']=='th_exchange_token'
            assert req.url.params['client_secret']=='synthetic-app-secret'
            assert req.url.params['access_token']=='synthetic-short-token'
            assert 'authorization' not in req.headers
            exchanges.append(True)
        return original.transport.handle_request(req)
    app.dependency_overrides[routes.api]=lambda:ThreadsAPI(httpx.MockTransport(respond))
    record,_,_=connect(client,owner)
    assert record['threads_user_id']=='10001' and len(exchanges)==1
    with SessionLocal() as s:
        scope(s,tid)
        row=s.scalar(select(ThreadsConnection).where(ThreadsConnection.tenant_id==tid))
        assert row.token_ciphertext and 'synthetic' not in row.token_ciphertext
        assert row.publishing_enabled is False
    assert 'synthetic-short-token' not in caplog.text and 'synthetic-app-secret' not in caplog.text


def test_diagnostic_fields_reject_unbounded_or_unsafe_values():
    error={'error_subcode':True,'type':'secret\nheader','fbtrace_id':'x'*49}
    assert ThreadsFailure('CONTENT_REJECTED',provider_error=error).provider_details=={}


@pytest.mark.parametrize('change,reason',[
    ({'is_valid':False},'TOKEN_NOT_VALID'),
    ({'app_id':None},'DEBUG_APP_ID_MISSING'),
    ({'app_id':'other-app'},'APP_ID_MISMATCH'),
    ({'user_id':'other-user'},'USER_ID_MISMATCH'),
    ({'scopes':'threads_basic'},'SCOPES_SCHEMA_INVALID'),
    ({'scopes':['threads_basic']},'REQUIRED_SCOPES_MISSING'),
])
def test_debug_validation_reason_is_exact_without_weakening_checks(client,mock_threads,change,reason):
    original=app.dependency_overrides[routes.api]()
    def respond(req):
        response=original.transport.handle_request(req)
        if req.url.path=='/debug_token':
            assert req.url.params['access_token']==req.url.params['input_token']=='synthetic-long-token'
            assert 'authorization' not in req.headers
            body=response.json();body['data'].update(change)
            if change.get('app_id',False) is None:body['data'].pop('app_id')
            return httpx.Response(200,json=body)
        return response
    api=ThreadsAPI(httpx.MockTransport(respond))
    with pytest.raises(ThreadsFailure) as failure:api.inspect('synthetic-long-token')
    assert failure.value.category=='PERMISSION_DENIED'
    assert failure.value.provider_details=={'type':reason}
