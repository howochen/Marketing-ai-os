"""Isolated loopback-only synthetic browser fixture, excluded from the runtime Docker image."""
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
PRIVATE=ROOT/'.ui-preview';PRIVATE.mkdir(exist_ok=True)
os.environ['DATABASE_URL']='sqlite:///'+str(PRIVATE/'browser.db')
os.environ['MOS_ENV']='test';os.environ['MOS_PUBLIC_URL']=''
os.environ['MOS_ADMIN_KEY']='synthetic-ui-admin-not-for-deployment-123456789'
os.environ['MOS_THREADS_HTTP_ENABLED']='false';os.environ['MOS_THREADS_MAINTENANCE_ENABLED']='false'
from alembic import command
from alembic.config import Config
command.upgrade(Config(str(ROOT/'alembic.ini')),'head')
from fastapi.testclient import TestClient
from app.main import app,login_challenge,LoginCreate
from app.database import SessionLocal

if '--issue-code' in sys.argv:
    data=json.loads((PRIVATE/'access.json').read_text(encoding='utf-8'))
    with SessionLocal() as s:data['challenge']=login_challenge(LoginCreate(tenant_id=data['tenant_id'],subject='青禾品牌管理員'),s)['token']
    (PRIVATE/'access.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');sys.exit(0)

import pytest
from test_threads_publisher import mock_threads,connect,ready
from conftest import tenant
patch=pytest.MonkeyPatch()
fixture=mock_threads.__wrapped__(patch);mock_state=next(fixture)
os.environ['MOS_MODEL_CALLS_ENABLED']='true'
with TestClient(app) as client:
    tid,owner,worker,_=tenant(client,'青禾品牌工作室・合成工作區')
    conn,_,_=connect(client,owner)
    assert client.post(f'/threads/connections/{conn["id"]}/publishing',headers=owner,json={'enabled':True}).status_code==200
    pid,task_id,consent=ready(client,owner,worker,conn['id'])
    with SessionLocal() as s:challenge=login_challenge(LoginCreate(tenant_id=tid,subject='青禾品牌管理員'),s)['token']
    (PRIVATE/'access.json').write_text(json.dumps({'tenant_id':tid,'challenge':challenge,'admin_secret':os.environ['MOS_ADMIN_KEY'],
        'publication_id':pid,'connection_id':conn['id']},ensure_ascii=False),encoding='utf-8')
os.environ['MOS_MODEL_CALLS_ENABLED']='false'
import uvicorn
if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=8787,access_log=False)
