from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from app.database import SessionLocal, scope, engine
from app.models import Task, CostEvent, Tenant, Audit, now
from app.providers import MODEL, usage_cost
from app.adapters import ADAPTERS
from conftest import ADMIN, bearer, tenant, task, reserve, receipt, settle


def test_tenant_security_budget_and_manual_publishing(client):
    c = client
    assert c.get('/agents').status_code == 401
    assert c.post('/admin/tenants', json={'name': 'No auth'}).status_code == 403
    tid, a, worker, bootstrap = tenant(c)
    _, b, other_worker, _ = tenant(c)
    assert c.get('/agents', headers=a).json()['count'] == 24
    assert c.post('/tasks', headers=bootstrap, json={'title': 'x', 'brief': 'x'}).status_code == 403
    t = task(c, a)
    assert c.get('/tasks', headers=b).json() == []
    for suffix, payload in [('reserve', {'estimate_usd': '.1'}), ('release', {'idempotency_key': 'release-123'}),
                            ('approve', None), ('publication-request', {'platform': 'threads', 'idempotency_key': 'post-12345'})]:
        assert c.post(f'/tasks/{t}/{suffix}', headers=b, json=payload).status_code == 404
    assert c.post(f'/tasks/{t}/claim', headers=other_worker).status_code == 404
    assert c.post(f'/tasks/{t}/settle', headers=other_worker, json=receipt()).status_code == 404
    assert reserve(c, a, t, '1.01').status_code == 402
    publication = {'platform': 'threads', 'idempotency_key': 'post-123456'}
    assert c.post(f'/tasks/{t}/publication-request', headers=a, json=publication).status_code == 409
    assert reserve(c, a, t).status_code == 200
    assert reserve(c, a, t).json()['deduplicated']
    assert reserve(c, a, t, key='different-key').status_code == 409
    assert c.post(f'/tasks/{t}/settle', headers=a, json=receipt()).status_code == 403
    assert settle(c, worker, t).status_code == 200
    assert c.post(f'/tasks/{t}/approve', headers=worker).status_code == 403
    assert c.post(f'/tasks/{t}/approve', headers=a).status_code == 200
    first = c.post(f'/tasks/{t}/publication-request', headers=a, json=publication).json()
    second = c.post(f'/tasks/{t}/publication-request', headers=a, json=publication).json()
    assert first['status'] == 'MANUAL_REQUIRED' and second['deduplicated']
    assert float(c.get('/budget', headers=a).json()['spent_usd']) == .1
    assert float(c.get('/budget', headers=b).json()['spent_usd']) == 0
    assert c.get('/health').json()['publishing_enabled'] is False
    assert c.get('/audit', headers=b).json() != c.get('/audit', headers=a).json()


def test_passwordless_replay_expiry_and_scope(client):
    tid, owner, worker, _ = tenant(client)
    challenge = client.post('/admin/login-challenges', headers=ADMIN,
                            json={'tenant_id': tid, 'subject': 'owner'}).json()['token']
    assert client.post('/auth/login', json={'token': challenge}).status_code == 200
    assert client.post('/auth/login', json={'token': challenge}).status_code == 401
    assert client.post('/auth/login', json={'token': 'x' * 40}).status_code == 401
    assert client.post('/credentials', headers=owner,
                       json={'role': 'worker', 'subject': 'fake', 'scopes': ['settle']}).status_code == 422
    assert client.post('/credentials', headers=owner,
                       json={'role': 'manager', 'subject': 'x', 'scopes': ['approve']}).status_code == 422
    created = client.post('/credentials', headers=owner,
                          json={'role': 'manager', 'subject': 'x', 'scopes': ['read']}).json()
    limited = bearer(created['api_key'])
    assert client.get('/tasks', headers=limited).status_code == 200
    assert client.post('/tasks', headers=limited, json={'title': 'x', 'brief': 'x'}).status_code == 403
    assert client.delete('/credentials/' + created['id'], headers=owner).status_code == 200
    assert client.get('/tasks', headers=limited).status_code == 401
    from app.models import Credential, LoginChallenge
    challenge = client.post('/admin/login-challenges', headers=ADMIN,
                            json={'tenant_id': tid, 'subject': 'expired'}).json()['token']
    from app.security import digest
    with SessionLocal() as s:
        scope(s, tid)
        s.execute(update(LoginChallenge).where(LoginChallenge.token_hash == digest(challenge)).values(expires_at=now()-timedelta(seconds=1)))
        s.execute(update(Credential).where(Credential.token_hash == digest(worker['Authorization'][7:])).values(expires_at=now()-timedelta(seconds=1)))
        s.commit()
    assert client.post('/auth/login', json={'token': challenge}).status_code == 401
    assert client.get('/tasks', headers=worker).status_code == 401


def test_concurrent_reserve_settle_publication(client):
    tid, owner, worker, _ = tenant(client)
    t = task(client, owner)
    def parallel(fn):
        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(lambda _: fn(), range(8)))
    responses = parallel(lambda: reserve(client, owner, t))
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert client.post(f'/tasks/{t}/claim', headers=worker).status_code == 200
    responses = parallel(lambda: client.post(f'/tasks/{t}/settle', headers=worker, json=receipt('concurrent-receipt')))
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert client.post(f'/tasks/{t}/approve', headers=owner).status_code == 200
    responses = parallel(lambda: client.post(f'/tasks/{t}/publication-request', headers=owner,
                                             json={'platform': 'threads', 'idempotency_key': 'concurrent-post'}))
    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()['id'] for r in responses}) == 1
    with SessionLocal() as s:
        scope(s, tid)
        events = s.scalars(select(CostEvent).where(CostEvent.task_id == t)).all()
        assert sorted(e.type for e in events) == ['RESERVE', 'SETTLE']
        balance = s.get(Tenant, tid)
        assert (balance.spent_micro, balance.reserved_micro) == (100000, 0)
    altered = receipt('concurrent-receipt'); altered['output'] = 'changed'
    assert client.post(f'/tasks/{t}/settle', headers=worker, json=altered).status_code == 409
    assert client.post(f'/tasks/{t}/settle', headers=worker, json=receipt('different-receipt')).status_code == 409


def test_concurrent_budget_competition_and_release(client):
    tid, owner, worker, _ = tenant(client)
    ids = [task(client, owner) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda t: reserve(client, owner, t, '.3'), ids))
    assert sorted(r.status_code for r in responses) == [200]*3 + [402]*5
    t = next(t for t, r in zip(ids, responses) if r.status_code == 200)
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: client.post(f'/tasks/{t}/release', headers=owner,
                                                        json={'idempotency_key': 'release-concurrent'}), range(8)))
    assert all(r.status_code == 200 for r in responses)
    assert float(client.get('/budget', headers=owner).json()['reserved_usd']) == .6


def test_timeout_kill_switch_and_receipt_overrun(client):
    tid, owner, worker, _ = tenant(client)
    t, running = task(client, owner), task(client, owner)
    assert reserve(client, owner, t).status_code == 200
    assert reserve(client, owner, running, '.01').status_code == 200
    assert client.post(f'/tasks/{running}/claim', headers=worker).status_code == 200
    with SessionLocal() as s:
        scope(s, tid)
        s.execute(update(Task).where(Task.tenant_id == tid).values(expires_at=now()-timedelta(seconds=1)))
        s.commit()
    assert client.post('/maintenance/recover', headers=worker).json() == {'released': 1, 'held_for_reconciliation': 1}
    assert client.post('/maintenance/recover', headers=worker).json() == {'released': 0, 'held_for_reconciliation': 0}
    assert client.post(f'/tasks/{running}/release', headers=owner,
                       json={'idempotency_key': 'release-unsafe'}).status_code == 409
    assert client.post(f'/tasks/{running}/settle', headers=worker, json=receipt('overrun-receipt')).status_code == 200
    assert client.get('/budget', headers=owner).json()['paused'] is True
    new = task(client, owner)
    assert reserve(client, owner, new).status_code == 402
    assert client.put('/budget/kill-switch', headers=owner, json={'paused': False}).status_code == 200
    assert reserve(client, owner, new).status_code == 200
    assert client.put('/budget/kill-switch', headers=owner, json={'paused': True}).status_code == 200
    assert client.post(f'/tasks/{new}/claim', headers=worker).status_code == 402


def test_db_isolation_and_immutable_audit(client):
    aid, a, _, _ = tenant(client)
    bid, b, _, _ = tenant(client)
    at, bt = task(client, a), task(client, b)
    assert reserve(client, a, at).status_code == 200
    with SessionLocal() as s:
        scope(s, aid)
        assert s.scalar(select(Task).where(Task.id == bt)) is None
        assert s.scalar(select(Task).where(Task.id == at)) is not None
        s.add(Task(id='cross-tenant-write', tenant_id=bid, title='bad', brief='bad', agent_id='A09'))
        with pytest.raises(ValueError, match='Cross-tenant'):
            s.commit()
        s.rollback()
        for table in ('audit_logs', 'cost_events'):
            with pytest.raises(DBAPIError):
                s.execute(text(f"UPDATE {table} SET id = id"))
            s.rollback()
            with pytest.raises(DBAPIError):
                s.execute(text(f"DELETE FROM {table}"))
            s.rollback()
    if engine.dialect.name == 'postgresql':
        with engine.begin() as conn:
            conn.execute(text("SELECT set_config('mos.tenant_id', :tid, true)"), {'tid': aid})
            assert conn.scalar(text('SELECT count(*) FROM tasks WHERE id=:id'), {'id': bt}) == 0
            assert conn.execute(text('UPDATE tasks SET title=title WHERE id=:id'), {'id': bt}).rowcount == 0
            with pytest.raises(DBAPIError):
                conn.execute(text('INSERT INTO tasks (id, tenant_id, title, brief, agent_id, status, reserved_micro, created_at) '
                                  "VALUES ('forged', :tid, 'bad', 'bad', 'A09', 'DRAFT', 0, CURRENT_TIMESTAMP)"), {'tid': bid})
        with engine.begin() as conn:
            assert conn.scalar(text('SELECT count(*) FROM tasks')) == 0


@pytest.mark.parametrize('platform', ADAPTERS)
def test_platform_fails_closed(platform):
    adapter = ADAPTERS[platform]
    assert adapter.capabilities()['mode'] == 'manual_only'
    assert adapter.authorize({'verified': True})['can_publish'] is False
    for approved, verified in ((False, False), (True, False), (False, True), (True, True)):
        with pytest.raises(PermissionError):
            adapter.publish('post', owner_approved=approved, permissions_verified=verified)
    assert adapter.check_status('unknown')['posted'] is False
    assert adapter.revoke()['revoked']


def test_money_and_validation(client):
    _, owner, worker, _ = tenant(client)
    t = task(client, owner)
    for amount in ('NaN', 'Infinity', '-1', '0.0000001'):
        assert reserve(client, owner, t, amount).status_code == 422
    assert usage_cost({'input_tokens': 1, 'output_tokens': 1, 'cache_read_input_tokens': 1}) == 7
    assert reserve(client, owner, t, '.1').status_code == 200
    assert client.post(f'/tasks/{t}/claim', headers=worker).status_code == 200
    bad = receipt('bad-amount', '.2')
    assert client.post(f'/tasks/{t}/settle', headers=worker, json=bad).status_code == 422
    bad = receipt('bad-model'); bad['receipt']['model'] = 'invented'
    assert client.post(f'/tasks/{t}/settle', headers=worker, json=bad).status_code == 422
    assert client.post(f'/tasks/{t}/execute', headers=worker,
                       json={'idempotency_key': 'execute-disabled'}).status_code == 503


def test_provider_token_guard_and_uncertain_outcome(client, monkeypatch):
    from app.providers import AnthropicProvider
    _, owner, worker, _ = tenant(client)
    t = task(client, owner)
    assert reserve(client, owner, t, '.01').status_code == 200
    monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED', 'true')
    monkeypatch.setattr(AnthropicProvider, 'count_tokens', lambda *_: MODEL['max_input_tokens'] + 1)
    calls = []
    monkeypatch.setattr(AnthropicProvider, 'generate', lambda *_: calls.append(True))
    payload = {'idempotency_key': 'execute-token-limit'}
    assert client.post(f'/tasks/{t}/execute', headers=worker, json=payload).status_code == 402
    assert calls == []
    monkeypatch.setattr(AnthropicProvider, 'count_tokens', lambda *_: 10)
    def timeout(*args):
        raise TimeoutError('ambiguous timeout')
    monkeypatch.setattr(AnthropicProvider, 'generate', timeout)
    assert client.post(f'/tasks/{t}/execute', headers=worker, json=payload).status_code == 502
    assert client.post(f'/tasks/{t}/execute', headers=worker, json=payload).status_code == 409
    assert float(client.get('/budget', headers=owner).json()['reserved_usd']) == .01


def test_execute_receipt_metadata_and_idempotency(client, monkeypatch):
    from app.providers import AnthropicProvider
    tid, owner, worker, _ = tenant(client)
    t = task(client, owner)
    assert reserve(client, owner, t, '.01').status_code == 200
    monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED', 'true')
    monkeypatch.setattr(AnthropicProvider, 'count_tokens', lambda *_: 10)
    calls = []
    provider_receipt = {'provider': 'anthropic', 'model': MODEL['model'], 'receipt_id': 'generated-' + t,
                        'usage': {'input_tokens': 10, 'output_tokens': 1},
                        'actual_micro': 15, 'output': 'A real adapter-shaped mock, not posted'}
    def generate(*args):
        calls.append(True)
        return provider_receipt
    monkeypatch.setattr(AnthropicProvider, 'generate', generate)
    payload = {'idempotency_key': 'execute-idempotent'}
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: client.post(f'/tasks/{t}/execute', headers=worker, json=payload), range(8)))
    assert all(r.status_code in (200, 409) for r in responses)
    assert any(r.status_code == 200 for r in responses)
    assert client.post(f'/tasks/{t}/execute', headers=worker, json=payload).json()['deduplicated']
    assert calls == [True]
    with SessionLocal() as s:
        scope(s, tid)
        assert s.get(Task, t).receipt == provider_receipt
        assert s.get(Tenant, tid).spent_micro == 15


def test_duplicate_receipt_rolls_back_whole_transaction(client):
    tid, owner, worker, _ = tenant(client)
    a, b = task(client, owner), task(client, owner)
    assert reserve(client, owner, a).status_code == 200
    assert reserve(client, owner, b).status_code == 200
    unique_receipt = 'duplicate-' + a
    assert settle(client, worker, a, unique_receipt).status_code == 200
    assert client.post(f'/tasks/{b}/claim', headers=worker).status_code == 200
    assert client.post(f'/tasks/{b}/settle', headers=worker, json=receipt(unique_receipt)).status_code == 409
    with SessionLocal() as s:
        scope(s, tid)
        balance = s.get(Tenant, tid)
        assert (balance.spent_micro, balance.reserved_micro) == (100000, 250000)
        assert s.get(Task, b).status == 'RUNNING'


def test_postgres_all_tables_raw_isolation(client):
    if engine.dialect.name != 'postgresql':
        pytest.skip('Database-enforced RLS requires PostgreSQL')
    from app.models import Base
    from app.security import uid
    aid, owner, _, _ = tenant(client)
    bid, b, worker, _ = tenant(client)
    t = task(client, b)
    assert reserve(client, b, t).status_code == 200
    assert settle(client, worker, t, 'raw-isolation-' + t).status_code == 200
    assert client.post(f'/tasks/{t}/approve', headers=b).status_code == 200
    assert client.post(f'/tasks/{t}/publication-request', headers=b,
                       json={'platform': 'threads', 'idempotency_key': 'raw-isolation-post'}).status_code == 200
    for name in ('tenants', 'tasks', 'credentials', 'login_challenges', 'publications', 'cost_events', 'audit_logs'):
        table = Base.metadata.tables[name]
        column = table.c.id if name == 'tenants' else table.c.tenant_id
        with engine.begin() as conn:
            conn.execute(text("SELECT set_config('mos.tenant_id', :tid, true)"), {'tid': bid})
            record = dict(conn.execute(select(table).where(column == bid)).mappings().first())
        record['id'] = uid()
        if 'token_hash' in record:
            record['token_hash'] = uid()
        if record.get('receipt_id'):
            record['receipt_id'] = uid()
        with engine.begin() as conn:
            conn.execute(text("SELECT set_config('mos.tenant_id', :tid, true)"), {'tid': aid})
            assert conn.execute(select(table).where(column == bid)).first() is None, name
            if name in ('cost_events', 'audit_logs'):
                with pytest.raises(DBAPIError):
                    conn.execute(table.update().where(column == bid).values(id=table.c.id))
            else:
                assert conn.execute(table.update().where(column == bid).values(id=table.c.id)).rowcount == 0, name
        with engine.begin() as conn:
            conn.execute(text("SELECT set_config('mos.tenant_id', :tid, true)"), {'tid': aid})
            with pytest.raises(DBAPIError):
                conn.execute(table.insert().values(**record))
        with engine.begin() as conn:
            assert conn.execute(select(table)).first() is None, name
    with engine.begin() as conn:
        with pytest.raises(DBAPIError):
            conn.execute(text('ALTER TABLE tasks DISABLE ROW LEVEL SECURITY'))
    with engine.begin() as conn:
        with pytest.raises(DBAPIError):
            conn.execute(text('TRUNCATE audit_logs'))


def test_provider_http_contract_and_explicit_opt_in(monkeypatch):
    import httpx
    from app.providers import AnthropicProvider
    provider = AnthropicProvider()
    with pytest.raises(RuntimeError, match='disabled'):
        provider.generate('test', 10)
    monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED', 'true')
    monkeypatch.delenv('MOS_LIVE_TESTS', raising=False)
    with pytest.raises(RuntimeError, match='integration tests'):
        provider.generate('test', 10)
    monkeypatch.setenv('MOS_LIVE_TESTS', 'true')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'synthetic-key-never-sent')
    requests = []
    def post(url, *, timeout, headers, json):
        requests.append((url, json))
        assert timeout == 60
        assert headers['anthropic-version'] == '2023-06-01'
        if url.endswith('count_tokens'):
            return httpx.Response(200, json={'input_tokens': 10}, request=httpx.Request('POST', url))
        return httpx.Response(200, json={
            'model': MODEL['model'], 'id': 'mock-provider-message',
            'usage': {'input_tokens': 10, 'output_tokens': 2, 'cache_read_input_tokens': 10},
            'content': [{'type': 'text', 'text': 'Test output'}],
        }, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx, 'post', post)
    assert provider.count_tokens('test') == 10
    result = provider.generate('test', 10)
    assert result['actual_micro'] == 21
    assert result['receipt_id'] == 'mock-provider-message'
    assert result['output'] == 'Test output'
    assert requests[-1][1]['max_tokens'] == 10
    assert requests[-1][1]['model'] == MODEL['model']
