"""Real recovery process restart smoke test, restricted to the synthetic Docker project."""
import json
import os
import subprocess
import time
from pathlib import Path


def command(*args, env=None):
    result = subprocess.run(list(args), capture_output=True, text=True, timeout=60, env=env)
    if result.returncode:
        raise RuntimeError('Smoke operation failed (command output deliberately omitted)')
    return result.stdout


def main():
    for container in ('mos-p05-api', 'mos-p05-test-db-1'):
        labels = json.loads(command('docker', 'inspect', container))[0]['Config']['Labels']
        assert labels['com.docker.compose.project'] == 'mos-p05-test'
    seed = '''
import json, urllib.request
from datetime import timedelta
from fastapi.testclient import TestClient
from sqlalchemy import update
from app.main import app
from app.database import SessionLocal, scope
from app.models import Tenant, Task, now
from app.security import uid, issue, ROLES
assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/ready'))['schema']=='0004'
assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/health'))['model_calls_enabled'] is False
tid=uid()
with SessionLocal() as s:
    scope(s,tid)
    s.add(Tenant(id=tid,name='Synthetic scheduler drill',budget_micro=1000000))
    s.flush()
    owner,_=issue(s,tid,'smoke-owner','owner',ROLES['owner'])
    worker,_=issue(s,tid,'smoke-worker','worker',ROLES['worker'])
    s.commit()
with TestClient(app) as c:
    headers={'Authorization':'Bearer '+owner}
    ids=[]
    for i in range(2):
        response=c.post('/tasks',headers=headers,json={'title':'Synthetic task','brief':'No model calls'})
        assert response.status_code==201
        task=response.json()['id']; ids.append(task)
        assert c.post('/tasks/'+task+'/reserve',headers=headers,json={'estimate_usd':'.25'}).status_code==200
    assert c.post('/tasks/'+ids[1]+'/claim',headers={'Authorization':'Bearer '+worker}).status_code==200
with SessionLocal() as s:
    scope(s,tid)
    s.execute(update(Task).where(Task.tenant_id==tid).values(expires_at=now()-timedelta(seconds=1)))
    s.commit()
print(json.dumps({'tenant':tid,'worker':worker}))
'''
    # The captured synthetic worker secret is never printed or written to evidence.
    data = json.loads(command('docker','exec','mos-p05-api','python','-c',seed))
    env = {**os.environ, 'MOS_WORKER_TOKEN': data['worker'],
           'MOS_ADMIN_KEY': 'p05-isolated-test-admin-at-least-thirty-characters',
           'POSTGRES_PASSWORD': 'p05-isolated-postgres', 'MOS_APP_PASSWORD':'p05-isolated-app',
           'MOS_MIGRATION_PASSWORD':'p05-isolated-migrator'}
    command('docker','compose','-p','mos-p05-test','--profile','recovery','run','--no-deps','-d',
            '--name','mos-p05-recovery','recovery', env=env)
    def completed():
        result = subprocess.run(['docker','logs','mos-p05-recovery'], capture_output=True, text=True, timeout=10)
        return (result.stdout+result.stderr).count('scheduler.completed')
    deadline = time.monotonic()+30
    while completed()<1 and time.monotonic()<deadline:
        time.sleep(.2)
    assert completed()>=1
    command('docker','restart','mos-p05-recovery')
    deadline=time.monotonic()+30
    while completed()<2 and time.monotonic()<deadline:
        time.sleep(.2)
    assert completed()>=2
    check = '''
import json,sys
from sqlalchemy import select
from app.database import SessionLocal,scope
from app.models import Tenant,Task,CostEvent
with SessionLocal() as s:
    scope(s,sys.argv[1])
    t=s.get(Tenant,sys.argv[1])
    states=sorted(x.status for x in s.scalars(select(Task)))
    events=[x.type for x in s.scalars(select(CostEvent))]
    assert states==['RECONCILIATION_REQUIRED','RELEASED']
    assert events.count('RELEASE')==1 and (t.reserved_micro,t.spent_micro)==(250000,0)
print(json.dumps({'result':'PASS','process_restarts':1,'release_events':1,'held_micro':250000,'actual_model_calls':0}))
'''
    report=json.loads(command('docker','exec','mos-p05-api','python','-c',check,data['tenant']))
    Path('docs/p05/scheduler-process.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':
    main()
