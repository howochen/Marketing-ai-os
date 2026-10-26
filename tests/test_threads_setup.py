"""Installer policy and secret handling without ngrok, Docker or provider network calls."""
import base64
from datetime import datetime,timezone
import json
import os
import io
import urllib.error
import sys
import types
from pathlib import Path
import pytest
from cryptography import x509
from scripts import threads_setup as setup
from app import local_https


@pytest.fixture
def vault():
    return {'admin':'synthetic-admin','postgres':'synthetic-postgres','app':'synthetic-app','migration':'synthetic-migration',
            'token_key':'synthetic-key','project':setup.PROJECT,**setup.certificate()}


@pytest.mark.parametrize('url',['http://x.ngrok-free.app','https://x.example','https://user:secret@x.ngrok.app',
                              'https://x.ngrok.app/path','https://x.ngrok.app?code=secret','https://x.ngrok.app:444'])
def test_tunnel_origin_rejects_untrusted_configuration(url):
    with pytest.raises(setup.SetupError):setup.public_url(url)


def test_policy_forces_safe_environment_despite_host_flags(vault,monkeypatch):
    monkeypatch.setenv('MOS_THREADS_PUBLISH_ENABLED','true')
    vault.update(public_url='https://example.ngrok-free.app',app_id='123456',app_secret='synthetic-secret')
    values=setup.environment(vault)
    assert values['MOS_THREADS_PUBLISH_ENABLED']==values['MOS_MODEL_CALLS_ENABLED']=='false'
    assert values['MOS_TRUSTED_PROXIES']=='' and values['MOS_ENV']=='test'
    assert values['MOS_THREADS_HTTP_ENABLED']=='true'
    assert values['MOS_THREADS_REDIRECT_URI']=='https://example.ngrok-free.app/threads/oauth/callback'
    del vault['app_secret']
    assert setup.environment(vault)['MOS_THREADS_HTTP_ENABLED']=='false'


def test_local_certificate_has_verified_loopback_identity(vault):
    cert=x509.load_pem_x509_certificate(vault['tls_cert'].encode())
    assert cert.not_valid_after_utc>datetime.now(timezone.utc)
    san=cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert str(san.get_values_for_type(x509.IPAddress)[0])=='127.0.0.1'


def test_ngrok_startup_empty_list_is_transient_not_another_tunnel():
    assert setup.select_tunnel({'tunnels':[]},starting=True) is None
    with pytest.raises(setup.SetupError):setup.select_tunnel({'tunnels':[]})
    data={'tunnels':[{'config':{'addr':setup.LOCAL,'inspect':False},'public_url':'https://test.ngrok-free.app'}]}
    assert setup.select_tunnel(data)=='https://test.ngrok-free.app'
    data['tunnels'][0]['config']['inspect']=True
    with pytest.raises(setup.SetupError):setup.select_tunnel(data)


def test_public_probe_uses_strict_tls_without_environment_proxy(monkeypatch):
    calls=[]
    def handler(req):
        calls.append(req)
        return setup.httpx.Response(200,json={'schema':'0010'})
    original=setup.httpx.Client
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        assert kwargs.get('verify',True) is True
        return original(**kwargs,transport=setup.httpx.MockTransport(handler))
    monkeypatch.setattr(setup.httpx,'Client',client)
    assert setup.request('https://test.ngrok-free.app',path='/ready')=={'schema':'0010'}
    assert 'X-Admin-Key' not in calls[0].headers
    with pytest.raises(setup.SetupError,match='MUST_NOT_SEND_CREDENTIALS'):
        setup.request('https://test.ngrok-free.app',vault={'admin':'synthetic'},admin=True)


@pytest.mark.parametrize('source,accepted',[('MOCK',True),('OFFICIAL_API',True),('OFFICIAL_API',False)])
def test_diagnosis_requires_fresh_official_identity_and_never_publishes(vault,monkeypatch,source,accepted):
    uri='https://test.ngrok-free.app/threads/oauth/callback'
    vault.update(public_url='https://test.ngrok-free.app',tenant_id='synthetic',meta_redirect_confirmed_for=uri)
    def request(url,*,path,**kwargs):
        if path=='/ui/admin/status':return {'missing':[],'http_enabled':True,'publishing_enabled':False,'redirect_uri':uri}
        if path=='/admin/login-challenges':return {'token':'synthetic-code'}
        if path=='/auth/login':return {'access_token':'synthetic-owner'}
        return {'schema':'0010'}
    connection={'id':'synthetic-id','evidence_source':source,'connection_status':'ACTIVE','threads_user_id':'10001',
                'username':'synthetic','granted_scopes':['threads_basic','threads_content_publish'],
                'token_expires_at':'2099-01-01T00:00:00+00:00','last_verified_at':'synthetic-before'}
    calls=[]
    class Opener:
        def open(self,req,**kwargs):
            calls.append((req.get_method(),req.full_url))
            if req.full_url.endswith('/check'):
                if not accepted:raise urllib.error.HTTPError(req.full_url,409,'synthetic rejection',{},None)
                return io.StringIO(json.dumps({**connection,'last_verified_at':'synthetic-fresh'}))
            return io.StringIO(json.dumps([connection] if req.full_url.endswith('/connections') else {}))
    monkeypatch.setattr(setup,'request',request)
    monkeypatch.setattr(setup,'probe_public',lambda url:{'schema':'0010','ui_available':True,'callback_reachable':True})
    monkeypatch.setattr(setup.urllib.request,'build_opener',lambda *args:Opener())
    report=setup.diagnose(vault)
    assert report['SETUP_READY'] and not report['PUBLISH_VERIFIED']
    assert report['OAUTH_VERIFIED']==(source=='OFFICIAL_API' and accepted)
    assert calls[-1]==('DELETE',setup.LOCAL+'/ui/session')
    assert all('publish' not in url for method,url in calls)
    if report['OAUTH_VERIFIED']:assert report['accounts'][0]['last_verified_at']=='synthetic-fresh'


def test_compose_secret_file_removed_and_inherited_flags_scrubbed(vault,monkeypatch,tmp_path):
    monkeypatch.setattr(setup,'PRIVATE',tmp_path)
    monkeypatch.setenv('MOS_THREADS_PUBLISH_ENABLED','true')
    monkeypatch.setenv('COMPOSE_FILE','attacker.yml')
    def command(args,*,env):
        values=(tmp_path/'runtime.env').read_text(encoding='utf-8')
        assert "MOS_THREADS_PUBLISH_ENABLED='false'" in values
        assert 'COMPOSE_FILE' not in env and 'MOS_THREADS_PUBLISH_ENABLED' not in env
        assert setup.PROJECT in args
        raise setup.SetupError('synthetic failure')
    monkeypatch.setattr(setup,'command',command)
    with pytest.raises(setup.SetupError):setup.compose(vault,'up','-d')
    assert not (tmp_path/'runtime.env').exists()


def test_compose_rejects_environment_injection(vault,monkeypatch,tmp_path):
    monkeypatch.setattr(setup,'PRIVATE',tmp_path);vault['app_secret']='secret\nMOS_THREADS_PUBLISH_ENABLED=true'
    with pytest.raises(setup.SetupError,match='INVALID_CONFIGURATION'):setup.compose(vault,'up')
    assert not (tmp_path/'runtime.env').exists()


def test_existing_volume_without_vault_is_never_adopted(monkeypatch,tmp_path):
    monkeypatch.setattr(setup,'PRIVATE',tmp_path);monkeypatch.setattr(setup,'command',lambda args:'existing-volume')
    with pytest.raises(setup.SetupError,match='EXISTING_VOLUME_WITHOUT_VAULT'):setup.load()


def test_login_requires_a_prepared_workspace():
    with pytest.raises(setup.SetupError,match='RUN_SETUP_BEFORE_LOGIN'):setup.login_window({})


@pytest.mark.parametrize('mobile',[True,False])
def test_phone_handoff_reuses_login_without_browser_or_secret_url(monkeypatch,mobile):
    texts=[];opened=[];calls=[]
    class Widget:
        def __init__(self,*args,**kwargs):texts.append(kwargs.get('text',''))
        def pack(self,**kwargs):pass
        def insert(self,index,value):texts.append(value)
        def configure(self,**kwargs):pass
        def title(self,value):texts.append(value)
        def mainloop(self):pass
    monkeypatch.setitem(sys.modules,'tkinter',types.SimpleNamespace(Tk=Widget,Label=Widget,Entry=Widget,Button=Widget))
    import webbrowser
    monkeypatch.setattr(webbrowser,'open',opened.append)
    def request(*args,**kwargs):calls.append(kwargs['path']);return {'token':'synthetic-one-time-code'}
    monkeypatch.setattr(setup,'request',request)
    setup.login_window({'tenant_id':'synthetic','public_url':'https://test.ngrok-free.app'},mobile=mobile)
    assert calls==['/admin/login-challenges']
    assert opened==([] if mobile else ['https://test.ngrok-free.app/app'])
    if mobile:assert 'https://test.ngrok-free.app/app/threads' in texts
    assert all('synthetic-one-time-code' not in value for value in texts if value.startswith('https://'))


def test_public_tls_failure_is_reported_without_disabling_verification(monkeypatch):
    def fail(**kwargs):raise setup.httpx.ConnectError('synthetic TLS failure with sensitive detail')
    monkeypatch.setattr(setup.httpx,'Client',fail)
    result=setup.probe_public('https://test.ngrok-free.app')
    assert result=={'error':'ConnectError','ui_available':False,'callback_reachable':False}


@pytest.mark.skipif(os.name!='nt',reason='Installer requires Windows current-user DPAPI')
def test_dpapi_encrypts_and_reloads_without_rotating(vault,monkeypatch,tmp_path):
    monkeypatch.setattr(setup,'PRIVATE',tmp_path)
    setup.save(vault)
    encrypted=(tmp_path/'vault.dpapi').read_bytes()
    assert vault['admin'].encode() not in encrypted and vault['tls_key'].encode() not in encrypted
    assert setup.load()==vault


@pytest.mark.skipif(os.name!='nt',reason='Installer lock requires Windows msvcrt')
def test_readonly_login_window_does_not_hold_setup_lock(vault,monkeypatch,tmp_path):
    import msvcrt
    monkeypatch.delenv('CI',raising=False);monkeypatch.delenv('PYTEST_CURRENT_TEST',raising=False)
    monkeypatch.setattr(setup,'PRIVATE',tmp_path)
    monkeypatch.setattr(setup.shutil,'which',lambda name:'synthetic-tool')
    monkeypatch.setattr(setup,'command',lambda args:'synthetic-version')
    monkeypatch.setattr(setup,'protect_directory',lambda:None)
    monkeypatch.setattr(setup,'load',lambda:vault)
    checked=[]
    def login(*args,**kwargs):
        with (tmp_path/'setup.lock').open('r+b') as other:
            msvcrt.locking(other.fileno(),msvcrt.LK_NBLCK,1)
            checked.append(True)
            msvcrt.locking(other.fileno(),msvcrt.LK_UNLCK,1)
    monkeypatch.setattr(setup,'login_window',login)
    args=types.SimpleNamespace(stop=False,non_interactive=False,diagnose=False,login=True,mobile=True)
    setup.run(args)
    assert checked==[True]


@pytest.mark.parametrize('flag,value',[('MOS_ENV','production'),('MOS_LOCAL_SETUP_ENABLED','false'),
                                     ('MOS_MODEL_CALLS_ENABLED','true'),('MOS_THREADS_PUBLISH_ENABLED','true')])
def test_https_entrypoint_refuses_unsafe_modes(monkeypatch,flag,value):
    for key,setting in {'MOS_ENV':'test','MOS_LOCAL_SETUP_ENABLED':'true','MOS_MODEL_CALLS_ENABLED':'false','MOS_THREADS_PUBLISH_ENABLED':'false'}.items():
        monkeypatch.setenv(key,setting)
    monkeypatch.setenv(flag,value)
    with pytest.raises(RuntimeError):local_https.main()


def test_https_key_only_materialized_in_restricted_temporary_file(vault,monkeypatch):
    for key,value in {'MOS_ENV':'test','MOS_LOCAL_SETUP_ENABLED':'true','MOS_MODEL_CALLS_ENABLED':'false','MOS_THREADS_PUBLISH_ENABLED':'false',
                      'MOS_SETUP_TLS_CERT':base64.b64encode(vault['tls_cert'].encode()).decode(),
                      'MOS_SETUP_TLS_KEY':base64.b64encode(vault['tls_key'].encode()).decode()}.items():monkeypatch.setenv(key,value)
    paths=[]
    def uvicorn(*args,**kwargs):
        assert not kwargs['proxy_headers'] and not kwargs['access_log']
        key=Path(kwargs['ssl_keyfile']);paths.append(key)
        assert key.read_text()==vault['tls_key'] and 'MOS_SETUP_TLS_KEY' not in os.environ
    monkeypatch.setattr(local_https.uvicorn,'run',uvicorn)
    local_https.main()
    assert not paths[0].exists()
