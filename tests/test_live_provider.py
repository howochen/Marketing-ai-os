import pytest


@pytest.mark.live
def test_live_provider_receipt():
    pytest.skip('P1.2: live transport disabled; P1.5 requires separate spending authorization and gate review')
