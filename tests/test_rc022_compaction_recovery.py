import pytest

from scripts.rc022_compaction_recovery_probe import observe


@pytest.mark.asyncio
async def test_region_recovery_interleavings_and_cancellation():
    rows = await observe()
    assert len(rows) == 28
    for row in rows[:20]:
        case = row['case']
        allowed = case['mutation'] == 'none' or case['manual'] and case['mutation'] in ('append', 'outside')
        assert ('result' in row) == allowed, row
        assert len(row['checkpoints']) == int(allowed)
        assert row['trace'][-1] == 'flush'
        recoveries = [item for item in row['trace'] if isinstance(item, dict) and 'recover' in item]
        assert len(recoveries) == int(case['retry'] and allowed)
    cancelled = rows[20:22]
    assert all(row['error']['message'] == 'cancelled by caller' for row in cancelled)
    assert all(len([item for item in row['trace'] if isinstance(item, dict) and 'summary' in item]) == 1 for row in cancelled)
    assert rows[22]['error']['code'] == 'persistence'
    assert rows[23]['error']['cause']['message'] == 'summary is not smaller than the shadowed content (100 estimated framed tokens >= 100)'
    assert rows[24]['error']['code'] == rows[25]['error']['code'] == 'busy'
    assert rows[26]['error']['code'] == 'changed'
    assert rows[27]['events'][-1]['type'] == 'user/message'
