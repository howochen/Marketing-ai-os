"""Loopback-only real UI/API/database integration server with synthetic tenancy."""
import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
PRIVATE=ROOT/'.content-test';PRIVATE.mkdir(exist_ok=True)
os.environ['DATABASE_URL']='sqlite:///'+str(PRIVATE/'browser.db')
os.environ.pop('MIGRATION_DATABASE_URL',None)
os.environ['MOS_PUBLIC_URL']='http://127.0.0.1:8892'
for key in ('MOS_PHONE_SETUP_ENABLED','MOS_MODEL_CALLS_ENABLED','MOS_THREADS_PUBLISH_ENABLED','MOS_THREADS_HTTP_ENABLED','MOS_THREADS_MAINTENANCE_ENABLED'):
    os.environ[key]='false'
from conftest import tenant,ADMIN
from app.main import app
from fastapi.testclient import TestClient
with TestClient(app) as client:
    tid,_,_,_=tenant(client,'合成茶室・內容驗收工作區')
    challenge=client.post('/admin/login-challenges',headers=ADMIN,json={'tenant_id':tid,'subject':'offline-browser-owner'}).json()['token']
(PRIVATE/'browser-access.json').write_text(json.dumps({'challenge':challenge,'tenant_id':tid}),encoding='utf-8')
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8892,access_log=False)
