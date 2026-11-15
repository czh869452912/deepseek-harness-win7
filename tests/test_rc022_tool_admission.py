import pytest
from scripts.rc022_tool_admission_probe import observe


@pytest.mark.asyncio
async def test_resolved_admission_and_real_dispatch():
    rows = {row['action']: row for row in await observe()}
    for row in rows.values():
        if row['action'].startswith('scoped-') or row['action']=='late-restriction':
            continue
        assert row['inspect'] == ['echo', 'plain']
        assert row['outside'] is False
        assert len(row['conditions']) == (0 if row['action'] == 'abort-before' else 1)
        assert all(all(call.values()) for call in row['conditions'])
    for key in ('enabled', 'once', 'dispatch'):
        assert rows[key]['admitted'] == ['echo', 'plain']
    for key in ('removed', 'replace', 'disabled'):
        assert rows[key]['admitted'] == ['plain']
    for key in ('closed', 'foreign'):
        assert rows[key]['admitted'] == []
    for key in ('abort-before', 'abort-after', 'abort-reject'):
        assert rows[key]['error']['reason']
    assert rows['reject']['error']['code'] == 'TOOL_ACTIVATION_FAILED'
    assert rows['reject']['error']['cause']
    assert rows['dispatch']['results'] == ['UNKNOWN_TOOL', 'ok', 'UNKNOWN_TOOL']
    assert rows['dispatch']['bodies'] == [True]
    assert rows['scoped-shadow']['before'] == rows['scoped-shadow']['after'] == []
    assert rows['scoped-unload']['before'] == ['scoped']
    assert rows['scoped-unload']['after'] == []
    assert rows['late-restriction'] == dict(action='late-restriction', before=['global'], after=[], restored=['global'])
