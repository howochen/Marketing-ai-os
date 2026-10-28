"""Repeatable Windows-only, isolated Threads setup. Never prints provider or backend secrets."""
import argparse
import base64
import ctypes
from ctypes import wintypes
import csv
from datetime import datetime,timedelta,timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import ssl
import subprocess
import sys
import time
from urllib.parse import urlsplit
import urllib.request
import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT=Path(__file__).resolve().parents[1]
PRIVATE=ROOT/'.threads-local'
PROJECT='mos-threads-local'
LOCAL='https://127.0.0.1:18080'
AGENT='http://127.0.0.1:4041'


class SetupError(Exception):pass


def command(args,*,env=None):
    result=subprocess.run(args,cwd=ROOT,env=env,capture_output=True,timeout=600)
    if result.returncode:raise SetupError('COMMAND_FAILED:'+Path(args[0]).stem)
    return result.stdout.decode('utf-8',errors='replace')


def protect_directory():
    PRIVATE.mkdir(exist_ok=True)
    if PRIVATE.is_symlink() or PRIVATE.is_junction():raise SetupError('PRIVATE_DIRECTORY_MUST_NOT_BE_LINK')
    row=list(csv.reader(command(['whoami','/user','/fo','csv','/nh']).strip().splitlines()))[0]
    sid=row[-1]
    if not re.fullmatch(r'S-1-\d+(?:-\d+)+',sid):raise SetupError('WINDOWS_IDENTITY_UNKNOWN')
    library=ctypes.WinDLL('advapi32',use_last_error=True)
    descriptor=ctypes.c_void_p()
    convert=library.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,ctypes.POINTER(ctypes.c_void_p),ctypes.c_void_p]
    convert.restype=wintypes.BOOL
    apply=library.SetFileSecurityW
    apply.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,ctypes.c_void_p];apply.restype=wintypes.BOOL
    if not convert(f'D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;{sid})',1,ctypes.byref(descriptor),None):raise SetupError('DACL_FAILED')
    try:
        if not apply(str(PRIVATE),0x80000004,descriptor):raise SetupError('DACL_FAILED')
    finally:
        free=ctypes.WinDLL('kernel32').LocalFree;free.argtypes=[ctypes.c_void_p];free(descriptor)


class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]


def dpapi(data,*,decrypt=False):
    if os.name!='nt':raise SetupError('WINDOWS_DPAPI_REQUIRED')
    buffer=ctypes.create_string_buffer(data)
    source=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));target=Blob()
    library=ctypes.WinDLL('crypt32',use_last_error=True)
    action=library.CryptUnprotectData if decrypt else library.CryptProtectData
    action.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    action.restype=wintypes.BOOL
    if not action(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target)):
        raise SetupError('DPAPI_FAILED')
    try:return ctypes.string_at(target.data,target.size)
    finally:
        free=ctypes.WinDLL('kernel32').LocalFree;free.argtypes=[ctypes.c_void_p];free.restype=ctypes.c_void_p
        free(target.data)


def save(vault):
    temporary=PRIVATE/'vault.new'
    temporary.write_bytes(dpapi(json.dumps(vault).encode()))
    temporary.replace(PRIVATE/'vault.dpapi')


def certificate():
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'MOS local Threads upstream')])
    cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(minutes=5))
          .not_valid_after(datetime.now(timezone.utc)+timedelta(days=90))
          .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
          .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True).sign(key,hashes.SHA256()))
    return {'tls_cert':cert.public_bytes(serialization.Encoding.PEM).decode(),
            'tls_key':key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()}


def load():
    path=PRIVATE/'vault.dpapi'
    if path.exists():
        vault=json.loads(dpapi(path.read_bytes(),decrypt=True))
        if vault.get('project')!=PROJECT:raise SetupError('VAULT_PROJECT_MISMATCH')
        return vault
    if command(['docker','volume','ls','--filter',f'label=com.docker.compose.project={PROJECT}','--format','{{.Name}}']).strip():
        raise SetupError('EXISTING_VOLUME_WITHOUT_VAULT: refuse to replace database credentials')
    vault={'project':PROJECT,**{name:secrets.token_urlsafe(36) for name in ('admin','postgres','app','migration')},
           'token_key':base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),**certificate()}
    save(vault);return vault


def public_url(value):
    parsed=urlsplit(value)
    if (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443)
            or parsed.path not in ('','/') or parsed.query or parsed.fragment
            or not parsed.hostname.endswith(('.ngrok-free.app','.ngrok-free.dev','.ngrok.app','.ngrok.dev'))):
        raise SetupError('UNTRUSTED_TUNNEL_URL')
    return value.rstrip('/')


def environment(vault):
    public=public_url(vault['public_url']) if vault.get('public_url') else ''
    authority=''
    if vault.get('phone_setup',{}).get('authority_key'):
        from app.phone_crypto import public as public_key
        authority=public_key(serialization.load_pem_private_key(vault['phone_setup']['authority_key'].encode(),password=None))
    return {'POSTGRES_PASSWORD':vault['postgres'],'MOS_APP_PASSWORD':vault['app'],'MOS_MIGRATION_PASSWORD':vault['migration'],
            'MOS_ADMIN_KEY':vault['admin'],'MOS_SETUP_TLS_CERT':base64.b64encode(vault['tls_cert'].encode()).decode(),
            'MOS_SETUP_TLS_KEY':base64.b64encode(vault['tls_key'].encode()).decode(),
            'MOS_THREADS_TOKEN_KEY':vault['token_key'],'MOS_THREADS_APP_ID':vault.get('app_id',''),
            'MOS_THREADS_APP_SECRET':vault.get('app_secret',''),'MOS_ENV':'test','MOS_PUBLIC_URL':public,
            'MOS_THREADS_REDIRECT_URI':public+'/threads/oauth/callback' if public else '',
            'MOS_TRUSTED_PROXIES':'','MOS_THREADS_HTTP_ENABLED':'true' if vault.get('app_id') and vault.get('app_secret') and public and vault.get('meta_redirect_confirmed_for')==public+'/threads/oauth/callback' else 'false',
            'MOS_MODEL_CALLS_ENABLED':'false','MOS_LIVE_TESTS':'false','MOS_THREADS_PUBLISH_ENABLED':'false','MOS_PHONE_SETUP_ENABLED':'false',
            'MOS_THREADS_MAINTENANCE_ENABLED':'false','MOS_PHONE_SETUP_AUTHORITY':authority}


def compose(vault,*args):
    values=environment(vault)
    path=PRIVATE/'runtime.env'
    # This directory has a current-user/SYSTEM DACL before any secret is materialized.
    try:
        with path.open('w',encoding='utf-8',newline='\n') as stream:
            for key,value in values.items():
                if '\n' in value or '\r' in value or '$' in value or "'" in value:raise SetupError('INVALID_CONFIGURATION_VALUE')
                stream.write(f"{key}='{value}'\n")
        child={key:value for key,value in os.environ.items() if not key.startswith(('MOS_','COMPOSE_')) and key not in values}
        child['COMPOSE_DISABLE_ENV_FILE']='true'
        return command(['docker','compose','--env-file',str(path),'-p',PROJECT,'-f','compose.yaml','-f','compose.threads-local.yaml',*args],env=child)
    finally:path.unlink(missing_ok=True)


def request(url,*,vault=None,path='',payload=None,admin=False):
    headers={'Content-Type':'application/json','ngrok-skip-browser-warning':'1'}
    if admin:headers['X-Admin-Key']=vault['admin']
    if url!=LOCAL:
        if admin or payload is not None:raise SetupError('PUBLIC_DIAGNOSTICS_MUST_NOT_SEND_CREDENTIALS')
        with httpx.Client(timeout=10,trust_env=False,follow_redirects=False) as client:
            response=client.get(url+path,headers=headers);response.raise_for_status();return response.json()
    context=ssl.create_default_context(cadata=vault['tls_cert']) if url==LOCAL else ssl.create_default_context()
    req=urllib.request.Request(url+path,data=json.dumps(payload).encode() if payload is not None else None,headers=headers)
    with urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=context)).open(req,timeout=10) as response:
        return json.load(response)


def wait_ready(vault):
    for _ in range(45):
        try:
            if request(LOCAL,vault=vault,path='/ready').get('schema')=='0015':return
        except (OSError,ValueError):pass
        time.sleep(1)
    raise SetupError('API_TLS_READINESS_FAILED')


def select_tunnel(data,starting=False):
    for item in data.get('tunnels',[]):
        if item.get('config',{}).get('addr')==LOCAL and item['config'].get('inspect') is False:
            return public_url(item['public_url'])
    if starting and not data.get('tunnels'):return None
    raise SetupError('AGENT_PORT_IN_USE_BY_OTHER_TUNNEL')


def tunnel(vault):
    def current(starting=False):
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            data=json.load(opener.open(AGENT+'/api/tunnels',timeout=2))
        except (OSError,ValueError):return None
        return select_tunnel(data,starting)
    existing=current()
    if existing:return existing
    config=PRIVATE/'ngrok-runtime.yml'
    config.write_text('version: "2"\nweb_addr: 127.0.0.1:4041\n'+('authtoken: '+json.dumps(vault['ngrok_token'])+'\n' if vault.get('ngrok_token') else ''),encoding='utf-8')
    args=['ngrok','http',LOCAL,'--inspect=false','--log=false','--upstream-tls-verify=true','--upstream-tls-verify-cas='+str(PRIVATE/'upstream.crt')]
    if vault.get('public_url','').endswith('.ngrok-free.dev'):args+=['--url='+public_url(vault['public_url'])]
    original=Path(os.environ.get('LOCALAPPDATA',''))/'ngrok/ngrok.yml'
    if original.exists() and not vault.get('ngrok_token'):args+=['--config',str(original)]
    args+=['--config',str(config)]
    process=subprocess.Popen(args,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    vault['ngrok_pid']=process.pid;vault['ngrok_created']=agent_process(process.pid);save(vault)
    try:
        for _ in range(40):
            if process.poll() is not None:
                text=process.communicate(timeout=2)[0].decode(errors='replace')
                codes=sorted(set(re.findall(r'ERR_NGROK_\d+',text)))
                raise SetupError('NGROK_START_FAILED:'+(','.join(codes) or 'CHECK_ACCOUNT_CONFIGURATION'))
            value=current(starting=True)
            if value:
                vault['ngrok_pid']=process.pid;save(vault);return value
            time.sleep(1)
        process.terminate();raise SetupError('NGROK_START_TIMEOUT')
    finally:config.unlink(missing_ok=True)


def agent_process(pid,expected_creation=None):
    library=ctypes.WinDLL('kernel32',use_last_error=True)
    library.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];library.OpenProcess.restype=wintypes.HANDLE
    library.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    library.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT];library.CloseHandle.argtypes=[wintypes.HANDLE]
    library.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
    handle=library.OpenProcess(0x1001,False,int(pid))
    if not handle:return
    try:
        buffer=ctypes.create_unicode_buffer(32768);length=wintypes.DWORD(len(buffer))
        if library.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(length)) and Path(buffer.value).resolve()==Path(shutil.which('ngrok')).resolve():
            times=[wintypes.FILETIME() for _ in range(4)]
            if not library.GetProcessTimes(handle,*[ctypes.byref(value) for value in times]):raise SetupError('PROCESS_IDENTITY_UNAVAILABLE')
            creation=(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
            if expected_creation is not None and creation==expected_creation:library.TerminateProcess(handle,0)
            return creation
    finally:library.CloseHandle(handle)


def stop_agent(vault):
    if vault.get('ngrok_pid') and vault.get('ngrok_created'):
        agent_process(vault['ngrok_pid'],vault['ngrok_created'])


def probe_public(url):
    public_url(url)
    try:
        with httpx.Client(timeout=10,trust_env=False,follow_redirects=False,headers={'ngrok-skip-browser-warning':'1'}) as client:
            ready=client.get(url+'/ready');ready.raise_for_status()
            page=client.get(url+'/app')
            callback=client.get(url+'/threads/oauth/callback')
            return {'schema':ready.json().get('schema'),'ui_available':page.status_code==200 and "script-src 'self'" in page.headers.get('content-security-policy',''),
                    'callback_reachable':callback.status_code==400 and callback.json().get('detail')=='Invalid OAuth state/browser binding'}
    except (httpx.HTTPError,ValueError) as exc:
        return {'error':type(exc).__name__,'ui_available':False,'callback_reachable':False}


def diagnose(vault):
    ready=request(LOCAL,vault=vault,path='/ready')
    status=request(LOCAL,vault=vault,path='/ui/admin/status',admin=True)
    external=probe_public(vault['public_url']) if vault.get('public_url') else {}
    probe=external.get('schema')==ready.get('schema') and bool(external.get('ui_available')) and bool(external.get('callback_reachable'))
    connections=[]
    if vault.get('tenant_id'):
        # Owner authentication is obtained locally; this GET never publishes or starts OAuth.
        code=request(LOCAL,vault=vault,path='/admin/login-challenges',admin=True,payload={'tenant_id':vault['tenant_id'],'subject':'local-install-owner'})['token']
        credential=request(LOCAL,vault=vault,path='/auth/login',payload={'token':code})['access_token']
        headers={'Authorization':'Bearer '+credential}
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ssl.create_default_context(cadata=vault['tls_cert'])))
        req=urllib.request.Request(LOCAL+'/threads/connections',headers=headers)
        try:
            connections=json.load(opener.open(req,timeout=10))
            for connection in connections:
                if connection['evidence_source']!='OFFICIAL_API' or connection['connection_status']!='ACTIVE':continue
                check=urllib.request.Request(LOCAL+'/threads/connections/'+connection['id']+'/check',headers=headers,data=b'')
                try:
                    with opener.open(check,timeout=50) as response:connection.update(json.load(response))
                except urllib.error.HTTPError:
                    connection['connection_status']='REAUTH_REQUIRED'
        finally:
            # Revoke the temporary diagnostic credential even when validation fails.
            req=urllib.request.Request(LOCAL+'/ui/session',headers=headers,method='DELETE')
            opener.open(req,timeout=10).close()
    from app.threads_api import SCOPES
    official=[]
    for c in connections:
        try:
            valid=(c['evidence_source']=='OFFICIAL_API' and c['connection_status']=='ACTIVE'
                and isinstance(c['threads_user_id'],str) and c['threads_user_id'].isascii() and c['threads_user_id'].isdigit()
                and bool(c['username']) and SCOPES.issubset(c['granted_scopes'])
                and datetime.fromisoformat(c['token_expires_at'].replace('Z','+00:00'))>datetime.now(timezone.utc))
            if valid:official.append(c)
        except (KeyError,TypeError,ValueError):continue
    confirmed=vault.get('meta_redirect_confirmed_for')==status['redirect_uri'] and bool(status['redirect_uri'])
    return {'SETUP_READY':bool(probe and not status['missing'] and status['http_enabled'] and confirmed),
            'LOCAL_SETUP_READY':bool(probe),'meta_redirect_confirmation':'USER_CONFIRMED_NOT_PROVIDER_VERIFIED' if confirmed else 'MANUAL_HANDOFF_REQUIRED',
            'https_verified':probe,'tls_upstream_verified':True,'trusted_proxies':[],
            'external_checks':external,
            'redirect_uri':status['redirect_uri'],'missing':status['missing'],
            'callback_urls':status.get('callback_urls',{}),
            'meta_privacy_callback_confirmation':'USER_CONFIRMED_NOT_PROVIDER_VERIFIED' if vault.get('meta_privacy_callbacks_confirmed_for')==vault.get('public_url') else 'MANUAL_HANDOFF_REQUIRED',
            'OAUTH_VERIFIED':bool(official),'oauth_evidence':'fresh official identity/scope/expiry check; Mock excluded',
            'accounts':[{k:c[k] for k in ('threads_user_id','username','granted_scopes','token_expires_at','last_verified_at')} for c in official],
            'PUBLISH_VERIFIED':False,'publishing_enabled':status['publishing_enabled'],
            'publish_evidence':'NOT_RUN_INSTALLER_NEVER_PUBLISHES',
            'production_ready':False}


def login_window(vault,*,mobile=False,parent=None):
    if not vault.get('tenant_id') or not vault.get('public_url'):raise SetupError('RUN_SETUP_BEFORE_LOGIN')
    try:import tkinter as tk
    except ImportError:raise SetupError('PYTHON_TKINTER_REQUIRED') from None
    import webbrowser
    code=request(LOCAL,vault=vault,path='/admin/login-challenges',admin=True,payload={'tenant_id':vault['tenant_id'],'subject':'local-install-owner'})['token']
    window=tk.Toplevel(parent) if parent is not None else tk.Tk()
    window.title('Marketing AI OS — 手機登入' if mobile else 'Marketing AI OS — 本機登入')
    if mobile:
        tk.Label(window,text='請用 iPhone Safari 開啟下方網址；勿在不同瀏覽器間切換。',padx=20,pady=12).pack()
        address=tk.Entry(window,width=85);address.insert(0,vault['public_url']+'/app/threads');address.configure(state='readonly');address.pack(padx=20,pady=10)
        if not vault.get('app_id') or not vault.get('app_secret'):
            tk.Label(window,text='目前可登入 MOS；Threads 尚缺管理員配置 App ID／Secret，還不能完成官方授權。',padx=20,pady=10).pack()
    tk.Label(window,text='十分鐘內有效的一次性工作區登入碼；不會記錄至檔案。',padx=20,pady=12).pack()
    entry=tk.Entry(window,width=65);entry.insert(0,code);entry.configure(state='readonly');entry.pack(padx=20,pady=10)
    def copy():window.clipboard_clear();window.clipboard_append(code);window.update()
    tk.Button(window,text='複製登入碼',command=copy).pack(pady=10)
    tk.Button(window,text='已複製，關閉登入碼視窗並返回驗證',command=lambda:window.destroy()).pack(padx=20,pady=10)
    if not mobile:webbrowser.open(vault['public_url']+'/app/threads')
    if parent is not None:
        window.transient(parent);window.grab_set();parent.wait_window(window)
    else:window.mainloop()


def initialize():
    if not shutil.which('docker') or not shutil.which('ngrok'):raise SetupError('INSTALL_DOCKER_AND_NGROK_FIRST')
    command(['docker','info','--format','{{.ServerVersion}}'])
    for name in ('runtime.env','ngrok-runtime.yml'):(PRIVATE/name).unlink(missing_ok=True)
    vault=load()
    cert=x509.load_pem_x509_certificate(vault['tls_cert'].encode())
    if cert.not_valid_after_utc<=datetime.now(timezone.utc)+timedelta(days=1):
        stop_agent(vault);vault.update(certificate());save(vault)
    (PRIVATE/'upstream.crt').write_text(vault['tls_cert'],encoding='utf-8')
    return vault


def prepare_install(vault,progress=lambda message:None):
    progress('正在檢查 Docker 並啟動專用 HTTPS 後端；第一次建置可能需要數分鐘。')
    compose(vault,'up','--build','-d','db','migrate','api');wait_ready(vault)
    if not vault.get('tenant_id'):
        tenant=request(LOCAL,vault=vault,path='/admin/tenants',admin=True,payload={'name':'Threads 受控連線工作區','budget_usd':'0.000001'})
        vault['tenant_id']=tenant['id'];save(vault)
    progress('正在取得／重用 ngrok HTTPS 網址；不需要 App ID 或 Secret。')
    public=tunnel(vault);previous=vault.get('public_url')
    changed=bool(previous and public!=previous)
    if public!=previous:
        vault['public_url']=public;vault.pop('meta_redirect_confirmed_for',None);save(vault)
        compose(vault,'up','-d','api');wait_ready(vault)
    checks=probe_public(public)
    if not checks.get('ui_available') or not checks.get('callback_reachable') or checks.get('schema')!='0015':
        raise SetupError('HTTPS_CALLBACK_NOT_READY')
    return {'vault':vault,'callback':public+'/threads/oauth/callback','changed':changed}


def confirm_callback(vault,uri):
    if uri!=vault.get('public_url','')+'/threads/oauth/callback' or tunnel(vault)!=vault.get('public_url'):
        vault.pop('meta_redirect_confirmed_for',None);save(vault);raise SetupError('CALLBACK_CHANGED_RECHECK')
    vault['meta_redirect_confirmed_for']=uri;save(vault)


def credentials(vault,app_id,secret):
    if not re.fullmatch(r'[0-9]{3,40}',app_id) or not re.fullmatch(r'[A-Za-z0-9_-]{8,256}',secret):raise SetupError('INVALID_THREADS_CREDENTIALS')
    if vault.get('meta_redirect_confirmed_for')!=vault.get('public_url','')+'/threads/oauth/callback':raise SetupError('CONFIRM_META_CALLBACK_FIRST')
    # Existing database, token encryption, authority and certificate keys remain untouched.
    updated={**vault,'app_id':app_id,'app_secret':secret};save(updated);vault.update(updated)


def finish_install(vault):
    if not vault.get('app_id') or not vault.get('app_secret'):raise SetupError('THREADS_CREDENTIALS_REQUIRED')
    confirm_callback(vault,vault.get('meta_redirect_confirmed_for',''))
    compose(vault,'up','-d','api');wait_ready(vault)
    report=diagnose(vault)
    if not report['SETUP_READY'] or report['publishing_enabled']:raise SetupError('BACKEND_CONFIGURATION_NOT_READY')
    return report


def run(args):
    if os.name!='nt':raise SetupError('WINDOWS_ONLY')
    if os.getenv('CI') or os.getenv('PYTEST_CURRENT_TEST'):raise SetupError('INTERACTIVE_SETUP_NOT_ALLOWED_IN_CI')
    protect_directory()
    import msvcrt
    with (PRIVATE/'setup.lock').open('a+b') as lock:
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise SetupError('SETUP_ALREADY_RUNNING') from None
        locked=True
        def release():
            nonlocal locked
            if locked:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);locked=False
        try:
            if not any((args.stop,args.non_interactive,args.diagnose,args.login)):
                from scripts.threads_setup_ui import Wizard
                Wizard(initialize,release,mobile=args.mobile).run();return
            vault=initialize()
            if args.stop:
                compose(vault,'stop');stop_agent(vault);print('已停止專用 Docker 與本安裝器的 ngrok，資料卷及加密金鑰保留。');return
            if args.login:
                if not diagnose(vault)['SETUP_READY']:raise SetupError('FINISH_SETUP_BEFORE_LOGIN')
                release();login_window(vault,mobile=args.mobile);return
            if not args.diagnose:prepare_install(vault)
            report=diagnose(vault)
            (PRIVATE/'status.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(report,ensure_ascii=False,indent=2))
        finally:release()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Threads Windows 首次安裝：DPAPI + 獨立 Docker + ngrok HTTPS；永不發布')
    parser.add_argument('--mobile',action='store_true',help='使用既有登入碼與 /app/threads，交接至 iPhone；不開 Windows 瀏覽器')
    modes=parser.add_mutually_exclusive_group()
    for mode in ('non-interactive','diagnose','login','stop'):modes.add_argument('--'+mode,action='store_true')
    try:run(parser.parse_args())
    except (SetupError,OSError,ValueError,subprocess.SubprocessError,httpx.HTTPError) as exc:
        # Never dump command output, request URLs, payloads or exception messages containing secrets.
        print('安裝未完成：'+(str(exc) if isinstance(exc,SetupError) else type(exc).__name__),file=sys.stderr);sys.exit(1)
