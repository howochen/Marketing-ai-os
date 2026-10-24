import os
import tempfile
from pathlib import Path
path=Path(tempfile.mkdtemp())/'test.db'
os.environ['DATABASE_URL']=f'sqlite:///{path}'
os.environ['MOS_ADMIN_KEY']='test-admin-key-not-for-production'
from fastapi.testclient import TestClient
from app.main import app

def make_tenant(c,name):
    r=c.post('/admin/tenants',headers={'x-admin-key':'test-admin-key-not-for-production'},json={'name':name,'budget_usd':1.0})
    assert r.status_code==201,r.text
    return {'Authorization':'Bearer '+r.json()['api_key']}

def test_tenant_security_budget_and_manual_publishing():
    with TestClient(app) as c:
        assert c.get('/agents').status_code==401
        assert c.post('/admin/tenants',json={'name':'No auth'}).status_code==403
        a=make_tenant(c,'Agency A'); b=make_tenant(c,'Agency B')
        assert c.get('/agents',headers=a).json()['count']==24
        task=c.post('/tasks',headers=a,json={'title':'Threads copy','brief':'Beauty post','agent_id':'A09'}).json()['id']
        assert c.get('/tasks',headers=b).json()==[]
        assert c.post(f'/tasks/{task}/reserve',headers=b,json={'estimate_usd':0.1}).status_code==404
        assert c.post(f'/tasks/{task}/reserve',headers=a,json={'estimate_usd':1.01}).status_code==402
        assert c.post(f'/tasks/{task}/publication-request',headers=a,json={'platform':'threads','idempotency_key':'post-123456'}).status_code==409
        r=c.post(f'/tasks/{task}/reserve',headers=a,json={'estimate_usd':0.25}); assert r.status_code==200
        assert c.post(f'/tasks/{task}/reserve',headers=a,json={'estimate_usd':0.25}).status_code==409
        r=c.post(f'/tasks/{task}/settle',headers=a,json={'actual_usd':0.1,'output':'Draft for manual review'});assert r.status_code==200
        assert c.post(f'/tasks/{task}/approve',headers=a).status_code==200
        body={'platform':'threads','idempotency_key':'post-123456'}
        first=c.post(f'/tasks/{task}/publication-request',headers=a,json=body).json()
        second=c.post(f'/tasks/{task}/publication-request',headers=a,json=body).json()
        assert first['status']=='MANUAL_REQUIRED' and second['deduplicated']
        assert c.get('/budget',headers=a).json()['spent_usd']==0.1
        assert c.get('/budget',headers=b).json()['spent_usd']==0.0
        assert c.get('/health').json()['publishing_enabled'] is False
