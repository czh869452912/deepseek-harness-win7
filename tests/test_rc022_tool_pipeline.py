import pytest
from scripts.rc022_tool_pipeline_probe import observe


@pytest.mark.asyncio
async def test_real_pipeline_projection_policy_and_failure_boundaries():
    rows = {row['action']: row for row in await observe()}
    assert all(row['exactResult'] and row['executionFrozen'] and row['schemaPrivate'] for row in rows.values())
    assert rows['project']['trace'] == ['pre','body','project','post:prepared','final','result']
    assert rows['replace']['content'][0]['text'] == 'final:policy'
    assert rows['arguments']['value'] == 'original'
    assert rows['nested-meta']['meta'] == dict(shown='original')
    assert 'post:prepared' not in rows['project-fails']['trace']
    assert rows['project-fails']['content'][0]['text'] == 'final:Error: projection failed'
    assert rows['pre-fails']['trace'] == ['pre','final','result']
    assert rows['guard-info']['error']['info']['code'] == 'GUARD'
    assert rows['deny-info']['error']['info']['code'] == 'POLICY'
    assert rows['cancel']['error']['info']['code'] == 'ABORTED_BEFORE_DISPATCH'
    assert rows['unload']['error']['info']['code'] == 'UNKNOWN_TOOL'
