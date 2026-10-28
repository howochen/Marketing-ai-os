"""Windows Task Scheduler one-shot recovery. Never rebuild, migrate, rotate URLs or start workers."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.request
from . import threads_setup as setup

ROOT=setup.ROOT
PRIVATE=setup.PRIVATE/'runtime-recovery'
FLAGS=('MOS_MODEL_CALLS_ENABLED','MOS_THREADS_PUBLISH_ENABLED','MOS_AUTOMATION_ENABLED','MOS_AUTOMATION_LIVE_ENABLED','MOS_SINGLE_AI_TEST_ENABLED','MOS_PHONE_SETUP_ENABLED','MOS_THREADS_MAINTENANCE_ENABLED')
NAMES=('mos-threads-local-db-1','mos-threads-local-api-1')


def run(args):
    try:p=subprocess.run(args,capture_output=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except (OSError,subprocess.TimeoutExpired):raise RuntimeError('COMMAND_UNAVAILABLE') from None
    if p.returncode:raise RuntimeError('COMMAND_FAILED')
    return p.stdout


def write(name,data):
    path=PRIVATE/name
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)


def admit(state,component,clock):
    row=state.setdefault('attempts',{}).setdefault(component,{'times':[],'paused':False})
    row['times']=[x for x in row['times'] if clock-x<3600]
    if row['paused'] or len(row['times'])>=3:
        row['paused']=True
        return False
    row['times'].append(clock)
    return True


def attempt(state,component):
    allowed=admit(state,component,time.time())
    write('status.json',state)
    if not allowed:raise RuntimeError('RECOVERY_PAUSED_'+component.upper())


def inspect(name):
    return json.loads(run(['docker','inspect',name]))[0]


def validate(item,expected):
    if item['Id']!=expected['id'] or item['Image']!=expected['image']:raise RuntimeError('CONTAINER_CHANGED_RECONFIGURE_REQUIRED')
    env=dict(x.split('=',1) for x in item['Config']['Env'] if '=' in x)
    if any(env.get(k,'false')!='false' for k in FLAGS):raise RuntimeError('LIVE_SWITCH_NOT_CLOSED')
    volumes=[m['Name'] for m in item['Mounts'] if m['Type']=='volume']
    if volumes!=expected['volumes']:raise RuntimeError('DATABASE_VOLUME_CHANGED')


def tunnel():
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(setup.AGENT+'/api/tunnels',timeout=3) as response:
            return setup.select_tunnel(json.load(response),starting=True)
    except (OSError,ValueError):return None


def start_tunnel(vault,state,url):
    attempt(state,'ngrok')
    config=PRIVATE/'ngrok-runtime.yml'
    config.write_text('version: "2"\nweb_addr: 127.0.0.1:4041\nauthtoken: '+json.dumps(vault['ngrok_token'])+'\n',encoding='utf-8')
    process=None
    try:
        process=subprocess.Popen([shutil.which('ngrok'),'http',setup.LOCAL,'--url='+url,'--config',str(config),'--inspect=false','--log=false',
            '--upstream-tls-verify=true','--upstream-tls-verify-cas='+str(setup.PRIVATE/'upstream.crt')],
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        for _ in range(25):
            if process.poll() is not None:
                raw=process.communicate(timeout=2)[0].decode(errors='replace')
                codes=sorted(set(re.findall(r'ERR_NGROK_\d+',raw)))
                raise RuntimeError(','.join(codes) or 'NGROK_START_FAILED')
            current=tunnel()
            if current:
                if current!=url:raise RuntimeError('NGROK_URL_CHANGED_NOT_ADOPTED')
                state['ngrok_pid']=process.pid;state['ngrok_created']=setup.agent_process(process.pid)
                return
            time.sleep(1)
        raise RuntimeError('NGROK_START_TIMEOUT')
    except Exception:
        if process and process.poll() is None:process.terminate()
        raise
    finally:config.unlink(missing_ok=True)


def configure():
    setup.protect_directory();PRIVATE.mkdir(exist_ok=True)
    vault=json.loads(setup.dpapi((setup.PRIVATE/'vault.dpapi').read_bytes(),decrypt=True))
    items={name:inspect(name) for name in NAMES}
    for name,item in items.items():
        if item['Config']['Labels'].get('com.docker.compose.project')!='mos-threads-local':raise RuntimeError('WRONG_PROJECT')
    config={'url':setup.public_url(vault['public_url']),'containers':{name:{'id':i['Id'],'image':i['Image'],
        'volumes':[m['Name'] for m in i['Mounts'] if m['Type']=='volume']} for name,i in items.items()}}
    for name,item in items.items():validate(item,config['containers'][name])
    if (PRIVATE/'config.json').exists():
        if json.loads((PRIVATE/'config.json').read_text(encoding='utf-8'))!=config:raise RuntimeError('CONFIG_CHANGED_REVIEW_REQUIRED')
        return
    (PRIVATE/'containers-before.dpapi').write_bytes(setup.dpapi(json.dumps(items).encode()))
    write('config.json',config);write('status.json',{'attempts':{},'status':'CONFIGURED_NOT_YET_CHECKED'})
    for name in NAMES:run(['docker','update','--restart=on-failure:3',name])


def tick():
    config=json.loads((PRIVATE/'config.json').read_text(encoding='utf-8'))
    state=json.loads((PRIVATE/'status.json').read_text(encoding='utf-8'))
    state['checked_at']=time.strftime('%Y-%m-%d %H:%M:%S %z')
    try:
        vault=json.loads(setup.dpapi((setup.PRIVATE/'vault.dpapi').read_bytes(),decrypt=True))
        if vault['public_url']!=config['url']:raise RuntimeError('CALLBACK_CHANGED_RECONFIGURE_REQUIRED')
        try:run(['docker','info','--format','{{.ServerVersion}}'])
        except RuntimeError:
            attempt(state,'docker')
            subprocess.Popen([str(Path(os.environ['ProgramFiles'])/'Docker/Docker/Docker Desktop.exe')],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            for _ in range(10):
                time.sleep(5)
                try:run(['docker','info','--format','{{.ServerVersion}}']);break
                except RuntimeError:pass
            else:raise RuntimeError('DOCKER_NOT_READY')
        for name in NAMES:
            item=inspect(name);validate(item,config['containers'][name])
            if not item['State']['Running']:
                attempt(state,name);run(['docker','start',name])
        try:setup.request(setup.LOCAL,vault=vault,path='/ready')
        except Exception:
            attempt(state,'api_health');run(['docker','restart','mos-threads-local-api-1'])
            time.sleep(3);setup.request(setup.LOCAL,vault=vault,path='/ready')
        current=tunnel()
        if current and current!=config['url']:raise RuntimeError('NGROK_URL_CHANGED_NOT_ADOPTED')
        if not current:start_tunnel(vault,state,config['url'])
        state['status']='LOCAL_AND_TUNNEL_READY'
        for row in state.get('attempts',{}).values():
            if row['paused']:row.update(times=[],paused=False)
        if time.time()-state.get('public_checked_at',0)>900:
            state['public_checked_at']=time.time()
            try:setup.request(config['url'],path='/ready');state['public_status']='HTTPS_READY'
            except Exception:state['public_status']='EXTERNAL_UNREACHABLE_NO_RESTART_STORM'
        write('status.json',state)
    except Exception as exc:
        state['status']=str(exc) if isinstance(exc,RuntimeError) else 'LOCAL_CHECK_FAILED_'+type(exc).__name__
        write('status.json',state)
    text='Marketing AI OS 自動恢復狀態\n\n'+state['checked_at']+'\n'+state['status']+'\n'+config['url']+'/app/automation\n\n'+state.get('public_status','未檢查公開入口')+'\n\n每項每小時最多3次恢復，超限暫停；修復後手動啟動服務再由排程確認。\n不會更換網址、啟動Worker、付費AI或發文。'
    (PRIVATE/'status.txt').write_text(text,encoding='utf-8-sig')
    return 0 if state['status']=='LOCAL_AND_TUNNEL_READY' else 2


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--configure',action='store_true');args=parser.parse_args()
    if args.configure:configure();return 0
    import msvcrt
    with (setup.PRIVATE/'setup.lock').open('a+b') as lock:
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:return 0
        try:return tick()
        finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)


if __name__=='__main__':raise SystemExit(main())
