"""P0.5 offline infrastructure regressions; never accesses a live provider."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import logging
import json
import pytest
import httpx
from sqlalchemy import select, update, text
from sqlalchemy.exc import DBAPIError
from app.database import SessionLocal, scope
from app.models import RateVersion, Task, Tenant, CostEvent, now
from app.providers import MODEL, rate_id, usage_cost
from app.limits import consume
from app.operations import validate_deployment, emit
from app.scheduler import run_once
from conftest import tenant, task, reserve, settle, ADMIN


def test_shared_rate_limits_atomic_and_expire(client, monkeypatch):
    def attempt(_):
        with SessionLocal() as session:
            return consume(session, 'concurrent-limit-test', 3)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(16))) == 3
    import app.limits
    current = app.limits.time.time()
    monkeypatch.setattr(app.limits.time, 'time', lambda: current + 61)
    assert attempt(0)


def test_login_replay_throttled_and_admin_worker_separation(client):
    tid, owner, worker, _ = tenant(client)
    assert client.post('/admin/worker-credentials', headers=worker,
                       json={'tenant_id': tid, 'subject': 'forged'}).status_code == 403
    t = task(client, owner)
    assert client.post(f'/tasks/{t}/claim', headers=ADMIN).status_code == 401
    results = [client.post('/auth/login', json={'token': 'invalid-challenge-' * 3}).status_code for _ in range(12)]
    assert 401 in results and results[-1] == 429
    assert client.get('/health').status_code == 200


def test_environment_bound_credentials(client, monkeypatch):
    _, owner, _, _ = tenant(client)
    assert client.get('/tasks', headers=owner).status_code == 200
    monkeypatch.setenv('MOS_ENV', 'development')
    assert client.get('/tasks', headers=owner).status_code == 401


def test_rate_snapshot_is_immutable_and_receipts_unverified(client, monkeypatch):
    tid, owner, worker, _ = tenant(client)
    t = task(client, owner)
    assert reserve(client, owner, t).status_code == 200
    with SessionLocal() as session:
        scope(session, tid)
        captured = session.get(Task, t).rate_snapshot
        assert rate_id(captured) == rate_id(MODEL)
        assert session.get(RateVersion, rate_id(captured)).source_url.startswith('https://')
        with pytest.raises(DBAPIError):
            session.execute(text("UPDATE rate_versions SET provider='forged'"))
        session.rollback()
        with pytest.raises(DBAPIError):
            session.execute(text("UPDATE tasks SET rate_snapshot='{}' WHERE id=:id"), {'id': t})
        session.rollback()
    # Config rollover does not reprice already-reserved work.
    monkeypatch.setitem(MODEL, 'input_usd_per_million', '999')
    assert usage_cost({'input_tokens': 100000}, captured) == 100000
    assert settle(client, worker, t, 'unverified-' + t).status_code == 200
    with SessionLocal() as session:
        scope(session, tid)
        record = session.get(Task, t)
        assert record.receipt_status == 'UNVERIFIED'
        assert record.receipt_source == 'TRUSTED_WORKER_ASSERTION'
        assert session.get(Tenant, tid).spent_micro == 100000
        entries = session.scalars(select(CostEvent).where(CostEvent.task_id == t)).all()
        assert all(e.rate_version == rate_id(captured) for e in entries)
        assert all(e.receipt_status == 'UNVERIFIED' for e in entries)


def test_scheduler_restart_recovery_and_kill_switch(client):
    tid, owner, worker, _ = tenant(client)
    a, b = task(client, owner), task(client, owner)
    assert reserve(client, owner, a).status_code == 200
    assert reserve(client, owner, b).status_code == 200
    assert client.post(f'/tasks/{b}/claim', headers=worker).status_code == 200
    with SessionLocal() as session:
        scope(session, tid)
        session.execute(update(Task).where(Task.tenant_id == tid).values(expires_at=now()-timedelta(seconds=1)))
        session.commit()
    def handler(request):
        response = client.post('/maintenance/recover', headers=worker)
        return httpx.Response(response.status_code, json=response.json())
    with httpx.Client(transport=httpx.MockTransport(handler), base_url='http://recovery') as scheduler:
        assert run_once(scheduler) == {'released': 1, 'held_for_reconciliation': 1}
    # New scheduler process/client does not duplicate releases or retry unknown work.
    with httpx.Client(transport=httpx.MockTransport(handler), base_url='http://recovery') as restarted:
        assert run_once(restarted) == {'released': 0, 'held_for_reconciliation': 0}
    with SessionLocal() as session:
        scope(session, tid)
        assert session.get(Task, b).receipt_status == 'RECONCILIATION_REQUIRED'
        assert session.get(Tenant, tid).reserved_micro == 250000
    assert client.put('/budget/kill-switch', headers=owner, json={'paused': True}).status_code == 200
    c = task(client, owner)
    assert reserve(client, owner, c).status_code == 402


def test_scheduler_failure_safe():
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(401)), base_url='http://recovery') as scheduler:
        with pytest.raises(httpx.HTTPStatusError):
            run_once(scheduler)


def test_production_configuration_and_https_boundary(client, monkeypatch):
    monkeypatch.setenv('MOS_ENV', 'production')
    with pytest.raises(RuntimeError, match='dedicated admin'):
        validate_deployment()
    import secrets
    monkeypatch.setenv('MOS_ADMIN_KEY', secrets.token_urlsafe(48))
    monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://runtime@db/mos')
    monkeypatch.setenv('MOS_PUBLIC_URL', 'http://unsafe.example')
    with pytest.raises(RuntimeError, match='HTTPS'):
        validate_deployment()
    monkeypatch.setenv('MOS_PUBLIC_URL', 'https://pilot.example')
    monkeypatch.setenv('MOS_TRUSTED_PROXIES', '172.20.0.2/32')
    validate_deployment()
    assert client.get('/health', headers={'x-forwarded-proto': 'https'}).status_code == 403
    monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED', 'true')
    with pytest.raises(RuntimeError, match='remain disabled'):
        validate_deployment()


def test_ready_and_body_size(client):
    assert client.get('/ready').json()['schema'] == '0007'
    assert client.post('/auth/login', content='x'*65537).status_code == 413


def test_operational_events_exclude_arbitrary_secrets(caplog):
    caplog.set_level(logging.WARNING, logger='mos.events')
    emit('security.denied', status=403)
    entry = json.loads(caplog.records[-1].message)
    assert set(entry) == {'event','status','count'}
    with pytest.raises(ValueError):
        emit('synthetic-secret-must-not-log')
    assert 'synthetic-secret-must-not-log' not in caplog.text


def test_log_redaction_including_exception(client, monkeypatch, caplog):
    import logging
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'synthetic-runtime-provider-secret')
    caplog.set_level(logging.WARNING)
    try:
        raise RuntimeError('synthetic-runtime-provider-secret')
    except RuntimeError:
        logging.getLogger('mos.events').exception('Bearer fake-sensitive-bearer postgresql://user:secret-password@db/mos')
    assert 'synthetic-runtime-provider-secret' not in caplog.text
    assert 'fake-sensitive-bearer' not in caplog.text
    assert 'secret-password' not in caplog.text
    assert '[REDACTED]' in caplog.text


def test_receipt_verification_states_are_explicit():
    from app.models import ReceiptStatus
    assert {s.value for s in ReceiptStatus} == {'UNVERIFIED', 'VERIFIED', 'RECONCILIATION_REQUIRED'}
    with pytest.raises(ValueError):
        ReceiptStatus('BILLED_AND_VERIFIED_BY_CLIENT')


def test_rate_limit_storage_failure_is_closed(client, monkeypatch):
    import app.limits
    from sqlalchemy.exc import OperationalError
    def unavailable(*args):
        raise OperationalError('synthetic sql', {}, RuntimeError('synthetic-private-failure'))
    monkeypatch.setattr(app.limits, 'consume', unavailable)
    response = client.post('/auth/login', json={'token': 'invalid-token-' * 3})
    assert response.status_code == 503
    assert 'synthetic-private-failure' not in response.text
    assert client.get('/health').status_code == 200
