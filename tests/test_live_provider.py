import os
import pytest
from conftest import tenant, task, reserve


@pytest.mark.live
def test_live_provider_receipt(client, monkeypatch):
    if os.getenv('MOS_LIVE_TESTS') != 'true' or not os.getenv('ANTHROPIC_API_KEY'):
        pytest.skip('Requires MOS_LIVE_TESTS=true and explicit ANTHROPIC_API_KEY')
    monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED', 'true')
    _, owner, worker, _ = tenant(client)
    task_id = task(client, owner)
    assert reserve(client, owner, task_id, '.02').status_code == 200
    response = client.post(f'/tasks/{task_id}/execute', headers=worker,
                           json={'idempotency_key': 'live-provider-request'})
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'PENDING_APPROVAL'
    assert float(client.get('/budget', headers=owner).json()['spent_usd']) > 0
