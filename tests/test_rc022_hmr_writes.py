import asyncio

import pytest

from scripts.rc022_hmr_writes_probe import observe


@pytest.mark.asyncio
async def test_actual_partial_writes_atomic_editor_replacement_and_pending_disposal(tmp_path):
    rows = {row['name']:row for row in await observe(tmp_path/'writes')}
    assert rows['plain']['early'] == ['part-1', 'part-2-longer']
    assert rows['plain']['added'] == ['add-2-longer']
    assert rows['stable'] == dict(name='stable', early=[], complete=['part-2-longer'],
                                 added=[], changed=['after-add'])
    assert rows['stable-dispose'] == dict(name='stable-dispose', early=[], after=[])
    for name in ('atomic-default','atomic-window'):
        assert rows[name]['events'] == ['replaced']
    for name in ('atomic-disabled','atomic-expired','editor-default'):
        assert rows[name]['events'] == []
    assert rows['editor-disabled']['events'] == ['edited']


def test_original_write_stability_defaults_and_polling_atomic_default():
    from dsh.cordis.hmr_root_watch import write_finish, atomic_delay
    assert write_finish(dict(awaitWriteFinish=True)) == dict(stabilityThreshold=2000,pollInterval=100)
    assert write_finish(dict(awaitWriteFinish={})) == dict(stabilityThreshold=2000,pollInterval=100)
    assert write_finish(dict(awaitWriteFinish=False)) is None
    assert atomic_delay({}) == .1
    assert atomic_delay(dict(usePolling=True)) == 0
    assert atomic_delay(dict(usePolling=True, atomic=200)) == .2
