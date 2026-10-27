"""Callback-first order, resumability and native Tk widgets; no live setup or account changes."""
import copy
import os
import sys
import time
from pathlib import Path
import pytest
if __name__=='__main__':sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import threads_setup as setup
NATIVE_SAVE=setup.save
NATIVE_LOGIN=setup.login_window


def synthetic_state():
    value={'project':setup.PROJECT,'admin':'synthetic-admin','postgres':'preserve-postgres','app':'preserve-app',
        'migration':'preserve-migration','token_key':'preserve-token-key','tenant_id':'synthetic-tenant',**setup.certificate()}
    return value


@pytest.fixture
def state(monkeypatch):
    monkeypatch.setattr(setup,'save',lambda v:None)
    return synthetic_state()


def prepared(monkeypatch,state,old=None,new='https://new.ngrok-free.app'):
    calls=[]
    if old:state['public_url']=old;state['meta_redirect_confirmed_for']=old+'/threads/oauth/callback'
    monkeypatch.setattr(setup,'compose',lambda v,*args:calls.append(('compose',args)))
    monkeypatch.setattr(setup,'wait_ready',lambda v:calls.append(('ready',None)))
    monkeypatch.setattr(setup,'tunnel',lambda v:new)
    monkeypatch.setattr(setup,'probe_public',lambda url:{'schema':'0014','ui_available':True,'callback_reachable':True})
    return setup.prepare_install(state),calls


def test_first_phase_needs_no_app_credentials(monkeypatch,state):
    before=copy.deepcopy(state)
    result,calls=prepared(monkeypatch,state)
    assert result['callback']=='https://new.ngrok-free.app/threads/oauth/callback'
    assert not result['changed'] and 'app_secret' not in state and 'app_id' not in state
    assert all(state[k]==v for k,v in before.items())
    assert len([c for c in calls if c[0]=='compose'])==2


def test_changed_origin_invalidates_confirmation_preserves_keys(monkeypatch,state):
    state.update(app_id='123456',app_secret='synthetic-preserve-secret')
    before=copy.deepcopy(state)
    result,_=prepared(monkeypatch,state,'https://old.ngrok-free.app')
    assert result['changed'] and 'meta_redirect_confirmed_for' not in state
    assert all(state[k]==v for k,v in before.items() if k not in {'public_url','meta_redirect_confirmed_for'})
    assert setup.environment(state)['MOS_THREADS_HTTP_ENABLED']=='false'


def test_rerun_same_origin_keeps_existing_configuration(monkeypatch,state):
    result,calls=prepared(monkeypatch,state,'https://new.ngrok-free.app')
    assert not result['changed'] and state['meta_redirect_confirmed_for']==result['callback']
    assert len([c for c in calls if c[0]=='compose'])==1


def test_callback_requires_current_tunnel_and_explicit_action(monkeypatch,state):
    state['public_url']='https://new.ngrok-free.app'
    with pytest.raises(setup.SetupError,match='CONFIRM_META_CALLBACK_FIRST'):setup.credentials(state,'123456','synthetic-secret')
    monkeypatch.setattr(setup,'tunnel',lambda v:'https://different.ngrok-free.app')
    with pytest.raises(setup.SetupError,match='CALLBACK_CHANGED'):setup.confirm_callback(state,state['public_url']+'/threads/oauth/callback')
    assert 'meta_redirect_confirmed_for' not in state
    monkeypatch.setattr(setup,'tunnel',lambda v:state['public_url'])
    setup.confirm_callback(state,state['public_url']+'/threads/oauth/callback')
    original=copy.deepcopy(state);setup.credentials(state,'123456','synthetic-secret')
    assert all(state[k]==v for k,v in original.items())
    assert setup.environment(state)['MOS_THREADS_HTTP_ENABLED']=='true'


@pytest.mark.parametrize('app,secret',[('facebook-app','synthetic-secret'),('123456','bad\nsecret'),('123456','short')])
def test_invalid_credential_never_written(monkeypatch,state,app,secret):
    state.update(public_url='https://new.ngrok-free.app',meta_redirect_confirmed_for='https://new.ngrok-free.app/threads/oauth/callback')
    writes=[];monkeypatch.setattr(setup,'save',lambda v:writes.append(v))
    with pytest.raises(setup.SetupError):setup.credentials(state,app,secret)
    assert not writes and 'app_secret' not in state


def test_failed_dpapi_save_does_not_mutate_existing_credentials(monkeypatch,state):
    state.update(public_url='https://new.ngrok-free.app',meta_redirect_confirmed_for='https://new.ngrok-free.app/threads/oauth/callback',app_id='123456',app_secret='synthetic-before')
    def fail(v):raise OSError('synthetic disk failure')
    monkeypatch.setattr(setup,'save',fail)
    with pytest.raises(OSError):setup.credentials(state,'987654','synthetic-after')
    assert state['app_secret']=='synthetic-before' and state['app_id']=='123456'


@pytest.mark.parametrize('ready',[True,False])
def test_finish_requires_backend_checks(monkeypatch,state,ready):
    state.update(public_url='https://new.ngrok-free.app',meta_redirect_confirmed_for='https://new.ngrok-free.app/threads/oauth/callback',app_id='123456',app_secret='synthetic-secret')
    calls=[];monkeypatch.setattr(setup,'tunnel',lambda v:state['public_url'])
    monkeypatch.setattr(setup,'compose',lambda v,*args:calls.append(args));monkeypatch.setattr(setup,'wait_ready',lambda v:None)
    monkeypatch.setattr(setup,'diagnose',lambda v:{'SETUP_READY':ready,'publishing_enabled':False})
    if ready:assert setup.finish_install(state)['SETUP_READY']
    else:
        with pytest.raises(setup.SetupError,match='BACKEND_CONFIGURATION'):setup.finish_install(state)
    assert calls==[('up','-d','api')]


def test_public_phase_failure_does_not_request_credentials(monkeypatch,state):
    prepared(monkeypatch,state)
    monkeypatch.setattr(setup,'probe_public',lambda url:{'schema':'0014','ui_available':True,'callback_reachable':False})
    with pytest.raises(setup.SetupError,match='HTTPS_CALLBACK'):setup.prepare_install(state)
    assert 'app_secret' not in state


def test_cmd_defaults_to_desktop_module_not_mobile():
    text=Path('Setup-Threads.cmd').read_text(encoding='utf-8')
    assert '-m scripts.threads_setup %*' in text and '--mobile' not in text


@pytest.mark.skipif(sys.platform!='win32',reason='Actual Windows cmd.exe parsing')
def test_windows_launcher_parses_and_prints_help():
    import subprocess
    data=Path('Setup-Threads.cmd').read_bytes()
    assert b'\n' not in data.replace(b'\r\n',b'')
    result=subprocess.run(['cmd.exe','/d','/c','Setup-Threads.cmd --help'],capture_output=True,timeout=20)
    assert result.returncode==0,result.stderr.decode(errors='replace')
    assert b'usage:' in result.stdout and b'--diagnose' in result.stdout


def native_order(monkeypatch,state):
    from scripts.threads_setup_ui import Wizard
    monkeypatch.setattr(setup,'prepare_install',lambda v,p:{'vault':v,'callback':'https://new.ngrok-free.app/threads/oauth/callback','changed':False})
    state['public_url']='https://new.ngrok-free.app'
    monkeypatch.setattr(setup,'tunnel',lambda v:state['public_url'])
    wizard=Wizard(lambda:state,lambda:None);wizard.root.withdraw()
    def pump():
        deadline=time.monotonic()+3
        while wizard.busy and time.monotonic()<deadline:wizard.root.update();time.sleep(.02)
        wizard.root.update()
    try:
        wizard.prepare();pump()
        assert not hasattr(wizard,'secret') and not wizard.confirmed.get()
        wizard.next.invoke();assert not hasattr(wizard,'secret') and '請先' in wizard.status.get()
        wizard.confirm.invoke();wizard.next.invoke();pump()
        assert wizard.secret.cget('show')=='*' and wizard.secret.get()==''
        assert 'meta_redirect_confirmed_for' in state
        wizard.secret.insert(0,'synthetic-only-secret')
        wizard.app_id.insert(0,'invalid');wizard.save_credentials()
        assert wizard.secret.get()=='' and 'app_secret' not in state
    finally:wizard.busy=False;wizard.close()


def native_dpapi(monkeypatch,state,tmp_path):
    from scripts.threads_setup_ui import Wizard
    monkeypatch.setattr(setup,'PRIVATE',tmp_path);monkeypatch.setattr(setup,'save',NATIVE_SAVE)
    state.update(public_url='https://new.ngrok-free.app',meta_redirect_confirmed_for='https://new.ngrok-free.app/threads/oauth/callback')
    wizard=Wizard(lambda:state,lambda:None);wizard.root.withdraw();wizard.root.after_cancel(wizard.auto);wizard.auto=None
    wizard.vault=state;wizard.callback=state['meta_redirect_confirmed_for'];wizard.credentials_page()
    monkeypatch.setattr(setup,'finish_install',lambda v:{'SETUP_READY':True,'publishing_enabled':False})
    calls=[];monkeypatch.setattr(setup,'login_window',lambda *a,**kw:calls.append('login'))
    def pump():
        deadline=time.monotonic()+4
        while wizard.busy and time.monotonic()<deadline:wizard.root.update();time.sleep(.02)
        wizard.root.update()
    try:
        wizard.app_id.insert(0,'123456');wizard.secret.insert(0,'synthetic-native-only');wizard.save_credentials();pump()
        encrypted=(tmp_path/'vault.dpapi').read_bytes();assert b'synthetic-native-only' not in encrypted
        loaded=setup.load();assert loaded['app_secret']=='synthetic-native-only' and loaded['token_key']==state['token_key']
        assert wizard.ready and not calls
        monkeypatch.setattr(setup,'diagnose',lambda v:{'SETUP_READY':False,'publishing_enabled':False})
        wizard.open_login();pump();assert not calls and not wizard.ready
        wizard.ready_page({'SETUP_READY':True})
        monkeypatch.setattr(setup,'diagnose',lambda v:{'SETUP_READY':True,'publishing_enabled':False})
        wizard.open_login();pump();assert calls==['login']
        monkeypatch.setattr(setup,'request',lambda *a,**kw:{'token':'synthetic-login-code'})
        import webbrowser
        monkeypatch.setattr(webbrowser,'open',lambda url:None)
        import tkinter as tk
        def close_code():
            for child in wizard.root.winfo_children():
                if isinstance(child,tk.Toplevel):child.destroy()
        wizard.root.after(100,close_code)
        NATIVE_LOGIN(state,parent=wizard.root)
        assert not any(isinstance(child,tk.Toplevel) for child in wizard.root.winfo_children())
    finally:wizard.busy=False;wizard.close()


@pytest.mark.skipif(sys.platform!='win32',reason='Windows native Tk/DPAPI; each GUI owns one Tcl interpreter')
@pytest.mark.parametrize('case',['order','dpapi'])
def test_native_windows_isolated(case,tmp_path):
    import subprocess
    env={**os.environ,'PYTHONUTF8':'1'}
    for key in ('TCL_LIBRARY','TK_LIBRARY','MOS_THREADS_APP_SECRET'):env.pop(key,None)
    result=subprocess.run([sys.executable,str(Path(__file__).resolve()),case,str(tmp_path)],env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr


if __name__=='__main__':
    with pytest.MonkeyPatch.context() as patches:
        patches.setattr(setup,'save',lambda v:None)
        value=synthetic_state()
        if sys.argv[1]=='order':native_order(patches,value)
        else:native_dpapi(patches,value,Path(sys.argv[2]))
