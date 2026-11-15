import pytest
from scripts.rc022_executor_composition_probe import observe


@pytest.mark.asyncio
async def test_actual_loader_owns_default_optional_and_failed_executor_activation():
    rows = {row['action']:row for row in await observe()}
    for action in ('native', 'env-ptc', 'mode-null'):
        assert rows[action] == dict(action=action, failed=[], names=[], code=None, runtime=True)
    for action in ('ptc', 'env-native'):
        assert rows[action] == dict(action=action, failed=[], names=['run_code'], code=None, runtime=True)
    assert rows['missing']['code'] == 'TOOL_EXECUTOR_UNAVAILABLE'
    assert rows['duplicate']['failed'] == ['tool-executor-ptc']
    for action in ('mode-native', 'parallel'):
        assert rows[action]['failed'] == ['tools']
        assert rows[action]['names'] is None
