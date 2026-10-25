import os
import tempfile
from pathlib import Path
import pytest
from alembic import command
from alembic.config import Config

os.environ.setdefault('DATABASE_URL', 'sqlite:///' + str(Path(tempfile.mkdtemp()) / 'test.db'))
os.environ['MOS_ADMIN_KEY'] = 'test-admin-key-at-least-thirty-characters'
os.environ['MOS_MODEL_CALLS_ENABLED'] = 'false'
os.environ['MOS_ENV'] = 'test'
command.upgrade(Config('alembic.ini'), 'head')

from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    from app.database import SessionLocal
    from app.models import RateLimit
    from sqlalchemy import delete
    with SessionLocal() as session:
        session.execute(delete(RateLimit))
        session.commit()
    with TestClient(app) as client:
        yield client


ADMIN = {'x-admin-key': os.environ['MOS_ADMIN_KEY']}


def bearer(token):
    return {'Authorization': 'Bearer ' + token}


def tenant(client, name='Agency', budget='1'):
    response = client.post('/admin/tenants', headers=ADMIN,
                           json={'name': name, 'budget_usd': budget})
    assert response.status_code == 201, response.text
    tid = response.json()['id']
    challenge = client.post('/admin/login-challenges', headers=ADMIN,
                            json={'tenant_id': tid, 'subject': 'verified-owner'}).json()['token']
    owner = client.post('/auth/login', json={'token': challenge})
    assert owner.status_code == 200, owner.text
    worker = client.post('/admin/worker-credentials', headers=ADMIN,
                         json={'tenant_id': tid, 'subject': 'trusted-worker'}).json()['api_key']
    return tid, bearer(owner.json()['access_token']), bearer(worker), bearer(response.json()['api_key'])


def task(client, owner):
    response = client.post('/tasks', headers=owner,
                           json={'title': 'Threads copy', 'brief': 'A short post', 'agent_id': 'A09'})
    assert response.status_code == 201, response.text
    return response.json()['id']


def reserve(client, owner, task_id, amount='0.25', key='reserve-12345'):
    return client.post(f'/tasks/{task_id}/reserve', headers=owner,
                       json={'estimate_usd': amount, 'idempotency_key': key})


def receipt(receipt_id='receipt-12345', amount='0.1'):
    from app.providers import MODEL
    return {'idempotency_key': receipt_id, 'actual_usd': amount, 'output': 'Draft for review',
            'receipt': {'provider': 'anthropic', 'model': MODEL['model'], 'receipt_id': receipt_id,
                        'input_tokens': 100000, 'output_tokens': 0}}


def settle(client, worker, task_id, receipt_id='receipt-12345'):
    assert client.post(f'/tasks/{task_id}/claim', headers=worker).status_code == 200
    return client.post(f'/tasks/{task_id}/settle', headers=worker, json=receipt(receipt_id))
