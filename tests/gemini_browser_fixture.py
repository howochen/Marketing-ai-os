"""Loopback synthetic browser fixture; all model HTTP uses MockTransport."""
import json,os,secrets,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path[:0]=[str(root),str(root/'tests')]
private=root/'.threads-callback-test';private.mkdir(exist_ok=True)
os.environ.update(DATABASE_URL='sqlite:///'+str(private/('gemini-browser-'+secrets.token_hex(4)+'.db')),MOS_ENV='test',MOS_PUBLIC_URL='http://127.0.0.1:18786',MOS_THREADS_HTTP_ENABLED='false',MOS_THREADS_PUBLISH_ENABLED='false',MOS_PHONE_SETUP_ENABLED='false',MOS_AUTOMATION_ENABLED='false',MOS_AUTOMATION_LIVE_ENABLED='false',MOS_SINGLE_AI_TEST_ENABLED='false',MOS_MODEL_CALLS_ENABLED='false')
os.environ.pop('MIGRATION_DATABASE_URL',None)
import pytest
from conftest import ADMIN
from fastapi.testclient import TestClient
from app.main import app
from test_threads_publisher import mock_threads
from test_automation import env,setup_policy
from test_gemini import google
patch=pytest.MonkeyPatch();threads=mock_threads.__wrapped__(patch);state=next(threads);env.__wrapped__(state,patch);google.__wrapped__(patch)
with TestClient(app) as client:
    tid,_,_,_,_=setup_policy(client)
    challenge=client.post('/admin/login-challenges',headers=ADMIN,json={'tenant_id':tid,'subject':'verified-owner'}).json()['token']
(private/'gemini-browser-access.json').write_text(json.dumps({'tenant_id':tid,'challenge':challenge,'origin':'http://127.0.0.1:18786'}),encoding='utf-8')
os.environ.update(MOS_PUBLIC_URL='http://127.0.0.1:18786',MOS_AUTOMATION_ENABLED='false',MOS_SINGLE_AI_TEST_ENABLED='true',MOS_THREADS_PUBLISH_ENABLED='false',MOS_GEMINI_FREE_CALLS_ENABLED='true')
import uvicorn
uvicorn.run(app,host='127.0.0.1',port=18786,access_log=False,log_level='warning')
