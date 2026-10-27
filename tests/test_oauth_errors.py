"""OAuth errors retain safe diagnostics, never provider text or authorization material."""
from urllib.parse import urlsplit,parse_qs
import httpx,pytest
from sqlalchemy import select,func
from conftest import tenant
from test_threads_publisher import mock_threads
from test_social_ui import ui_login
from app.main import app
from app import threads_routes as routes
from app.threads_api import ThreadsAPI,ThreadsFailure
from app.database import SessionLocal,scope
from app.models import Audit,ThreadsOAuthState,ThreadsConnection
from app.browser_session import USER_COOKIE


@pytest.mark.parametrize('path,stage',[('/oauth/access_token','TOKEN_EXCHANGE'),('/access_token','LONG_TOKEN'),('/me','PROFILE'),('/debug_token','PERMISSIONS')])
def test_browser_oauth_failure_is_specific_safe_and_not_replayed(client,mock_threads,monkeypatch,caplog,path,stage):
    monkeypatch.delenv('MOS_PUBLIC_URL',raising=False)
    tid,_,_,_=tenant(client);h,_,login=ui_login(client,tid)
    original=app.dependency_overrides[routes.api]();calls=[]
    secret='synthetic-provider-secret-code-and-token-never-output'
    def respond(req):
        calls.append(req.url.path)
        if req.url.path==path:return httpx.Response(400,json={'error':{'code':100,'message':secret}})
        return original.transport.handle_request(req)
    app.dependency_overrides[routes.api]=lambda:ThreadsAPI(httpx.MockTransport(respond))
    started=client.post('/threads/oauth/start',headers=h);assert started.status_code==200,started.text
    state=parse_qs(urlsplit(started.json()['authorization_url']).query)['state'][0]
    cookies=USER_COOKIE+'='+login.cookies[USER_COOKIE]+'; mos_threads_browser='+started.cookies['mos_threads_browser']
    r=client.get('/threads/oauth/callback',params={'state':state,'code':'synthetic-one-use-code'},headers={'Cookie':cookies},follow_redirects=False)
    assert r.status_code==303
    assert parse_qs(urlsplit(r.headers['location']).query)=={'oauth_error':[stage],'meta_error':['100']}
    assert secret not in r.text+str(r.headers)+caplog.text and state not in r.headers['location']
    assert 'mos_threads_browser=""' in r.headers['set-cookie']
    with SessionLocal() as s:
        scope(s,tid)
        row=s.scalar(select(ThreadsOAuthState).where(ThreadsOAuthState.tenant_id==tid));assert row.used_at
        failures=s.scalars(select(Audit.action).where(Audit.action.like('threads.oauth_failed.%'))).all()
        assert failures==['threads.oauth_failed.'+stage+'.CONTENT_REJECTED.100']
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
