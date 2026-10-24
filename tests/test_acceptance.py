"""MOS-P0-009 offline acceptance regressions. No live account or model calls."""
import logging
from datetime import timedelta
import pytest
from sqlalchemy import select, update
from app.database import SessionLocal, scope
from app.models import Task, Tenant, CostEvent, Publication, now
from app.providers import AnthropicProvider, MODEL
from app.registry import AGENTS
from conftest import tenant, task, reserve, receipt, settle, bearer


def test_registry_and_illegal_transitions(client):
    _, owner, worker, reviewer = tenant(client)
    assert len(AGENTS) == 24
    assert set(AGENTS) == {f'A{i:02}' for i in range(1, 25)}
    assert all(a['status'] == 'REGISTERED_NOT_EXECUTING' for a in AGENTS.values())
    assert client.post('/tasks', headers=owner, json={'title': 'x', 'brief': 'x', 'agent_id': 'unknown'}).status_code == 422
    t = task(client, owner)
    key = {'idempotency_key': 'invalid-state-key'}
    assert client.post(f'/tasks/{t}/claim', headers=worker).status_code == 409
    assert client.post(f'/tasks/{t}/settle', headers=worker, json=receipt()).status_code == 409
    assert client.post(f'/tasks/{t}/approve', headers=owner).status_code == 409
    assert client.post(f'/tasks/{t}/release', headers=owner, json=key).status_code == 409
    manager = client.post('/credentials', headers=owner, json={
        'role': 'manager', 'subject': 'manager', 'scopes': ['read', 'publish']}).json()
    for headers in (bearer(manager['api_key']), reviewer, worker):
        assert client.post(f'/tasks/{t}/approve', headers=headers).status_code == 403
    assert reserve(client, owner, t).status_code == 200
    assert settle(client, worker, t, 'state-' + t).status_code == 200
    assert client.post(f'/tasks/{t}/claim', headers=worker).status_code == 409
    assert client.post(f'/tasks/{t}/release', headers=owner, json=key).status_code == 409


@pytest.mark.parametrize('tokens,amount', [(MODEL['max_input_tokens'] + 1, '.1'), (10, '.000001')])
def test_token_or_money_limit_prevents_generation(client, monkeypatch, tokens, amount):
    tid, owner, worker, _ = tenant(client)
    t = task(client, owner)
    assert reserve(client, owner, t, amount).status_code == 200
    monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED', 'true')
    monkeypatch.setattr(AnthropicProvider, 'count_tokens', lambda *_: tokens)
    calls = []
    monkeypatch.setattr(AnthropicProvider, 'generate', lambda *_: calls.append(True))
    assert client.post(f'/tasks/{t}/execute', headers=worker, json={'idempotency_key': 'budget-refused'}).status_code == 402
    assert calls == []
    with SessionLocal() as s:
        scope(s, tid)
        assert s.get(Tenant, tid).spent_micro == 0
        assert s.get(Task, t).status == 'RESERVED'


@pytest.mark.parametrize('changed', ['RECONCILIATION_REQUIRED', 'PENDING_APPROVAL', 'EXPIRED'])
def test_no_generation_after_state_changes_during_estimate(client, monkeypatch, changed):
    tid, owner, worker, _ = tenant(client)
    t = task(client, owner)
    assert reserve(client, owner, t, '.01').status_code == 200
    monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED', 'true')
    def count(*args):
        with SessionLocal() as s:
            scope(s, tid)
            values = {'expires_at': now() - timedelta(seconds=1)} if changed == 'EXPIRED' else {'status': changed}
            s.execute(update(Task).where(Task.id == t).values(**values))
            s.commit()
        return 10
    monkeypatch.setattr(AnthropicProvider, 'count_tokens', count)
    calls = []
    monkeypatch.setattr(AnthropicProvider, 'generate', lambda *_: calls.append(True))
    result = client.post(f'/tasks/{t}/execute', headers=worker, json={'idempotency_key': 'stale-claim-rejected'})
    assert result.status_code == 409, result.text
    assert calls == []
    with SessionLocal() as s:
        scope(s, tid)
        expected = 'RECONCILIATION_REQUIRED' if changed == 'EXPIRED' else changed
        assert s.get(Task, t).status == expected
        assert s.get(Tenant, tid).spent_micro == 0


def test_duplicate_webhooks_refused_and_publication_key_conflict(client):
    tid, owner, worker, _ = tenant(client)
    t = task(client, owner)
    assert reserve(client, owner, t).status_code == 200
    assert settle(client, worker, t, 'webhook-' + t).status_code == 200
    assert client.post(f'/tasks/{t}/approve', headers=owner).status_code == 200
    payload = {'platform': 'threads', 'idempotency_key': 'publication-hook-key'}
    first = client.post(f'/tasks/{t}/publication-request', headers=owner, json=payload)
    assert first.json()['status'] == 'MANUAL_REQUIRED'
    for _ in range(3):
        assert client.post('/webhooks/threads', json={'event_id': 'duplicate-event', 'task_id': t}).status_code == 404
        assert client.post(f'/tasks/{t}/publication-request', headers=owner, json=payload).json()['id'] == first.json()['id']
    payload['platform'] = 'instagram'
    assert client.post(f'/tasks/{t}/publication-request', headers=owner, json=payload).status_code == 409
    with SessionLocal() as s:
        scope(s, tid)
        assert len(s.scalars(select(Publication)).all()) == 1


def test_provider_failure_does_not_charge_or_log_secrets(client, monkeypatch, caplog, capsys):
    import os
    caplog.set_level(logging.INFO)
    tid, owner, worker, bootstrap = tenant(client)
    t = task(client, owner)
    assert reserve(client, owner, t, '.01').status_code == 200
    monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED', 'true')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'synthetic-provider-secret-for-log-test')
    monkeypatch.setattr(AnthropicProvider, 'count_tokens', lambda *_: 10)
    calls = []
    def fail(*args):
        calls.append(True)
        raise TimeoutError(os.environ['ANTHROPIC_API_KEY'])
    monkeypatch.setattr(AnthropicProvider, 'generate', fail)
    payload = {'idempotency_key': 'failure-no-double-bill'}
    result = client.post(f'/tasks/{t}/execute', headers=worker, json=payload)
    assert result.status_code == 502
    assert client.post(f'/tasks/{t}/execute', headers=worker, json=payload).status_code == 409
    assert calls == [True]
    audit = str(client.get('/audit', headers=owner).json())
    captured = capsys.readouterr()
    logs = caplog.text + captured.out + captured.err + result.text + audit
    for value in (owner['Authorization'][7:], worker['Authorization'][7:], bootstrap['Authorization'][7:],
                  os.environ['ANTHROPIC_API_KEY'], os.environ['MOS_ADMIN_KEY']):
        assert value not in logs
    with SessionLocal() as s:
        scope(s, tid)
        assert s.get(Tenant, tid).spent_micro == 0
        assert [e.type for e in s.scalars(select(CostEvent)).all()] == ['RESERVE']


def test_unmanaged_legacy_database_is_not_overwritten(tmp_path):
    import os
    import subprocess
    import sys
    from sqlalchemy import create_engine, text
    legacy_url = 'sqlite:///' + str(tmp_path / 'legacy.db')
    legacy = create_engine(legacy_url)
    with legacy.begin() as connection:
        connection.execute(text('CREATE TABLE tenants (id TEXT PRIMARY KEY, budget_usd FLOAT)'))
        connection.execute(text("INSERT INTO tenants VALUES ('legacy-example', 1.25)"))
    result = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'],
                            env={**os.environ, 'DATABASE_URL': legacy_url, 'MIGRATION_DATABASE_URL': legacy_url},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert 'Unmanaged prototype schema detected' in result.stderr
    with legacy.connect() as connection:
        assert connection.execute(text('SELECT id, budget_usd FROM tenants')).all() == [('legacy-example', 1.25)]
    legacy.dispose()
