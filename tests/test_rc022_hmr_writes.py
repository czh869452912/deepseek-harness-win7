import asyncio
import json
import os

import pytest

from scripts.rc022_hmr_writes_probe import observe


@pytest.mark.asyncio
async def test_actual_partial_writes_atomic_editor_replacement_and_pending_disposal(tmp_path):
    rows = {row['name']:row for row in await observe(tmp_path/'writes')}
    (tmp_path/'hmr-writes-observations.json').write_text(json.dumps(rows), encoding='utf-8')
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


@pytest.mark.asyncio
@pytest.mark.parametrize('first_scan_delay', [.06, .12])
async def test_plain_write_fixture_waits_for_observed_changes_before_next_write(tmp_path, monkeypatch, first_scan_delay):
    from dsh.cordis import hmr_root_watch
    from scripts import rc022_hmr_writes_probe as probe
    original = hmr_root_watch.scan
    delayed_once = set()
    async def delayed(hmr, initial=False):
        if not initial and id(hmr) not in delayed_once:
            delayed_once.add(id(hmr))
            await asyncio.sleep(first_scan_delay)
        return await original(hmr, initial)
    monkeypatch.setattr(hmr_root_watch, 'scan', delayed)
    monkeypatch.setattr(probe, 'CASES', [dict(name='plain')])
    rows = await probe.observe(tmp_path/'delayed-plain')
    (tmp_path/'hmr-delayed-plain-observations.json').write_text(json.dumps(rows), encoding='utf-8')
    assert rows == [dict(name='plain', early=['part-1', 'part-2-longer'],
                         complete=['part-1', 'part-2-longer'],
                         added=['add-2-longer'], changed=['after-add'])]


@pytest.mark.asyncio
async def test_atomic_unlink_fixture_waits_for_delayed_watch_inventory(tmp_path, monkeypatch):
    from dsh.cordis import hmr_root_watch
    from scripts import rc022_hmr_writes_probe as probe
    original = hmr_root_watch.scan
    async def delayed(hmr, initial=False):
        if not initial and any(not os.path.exists(path) for path in hmr._root_mtimes):
            await asyncio.sleep(.12)
        return await original(hmr, initial)
    monkeypatch.setattr(hmr_root_watch, 'scan', delayed)
    monkeypatch.setattr(probe, 'CASES', [dict(name='atomic-disabled', gap=60, atomic=False)])
    rows = await probe.observe(tmp_path/'delayed')
    (tmp_path/'hmr-delayed-inventory-observations.json').write_text(json.dumps(rows), encoding='utf-8')
    assert rows == [dict(name='atomic-disabled', events=[])]


def test_original_write_stability_defaults_and_polling_atomic_default():
    from dsh.cordis.hmr_root_watch import write_finish, atomic_delay
    assert write_finish(dict(awaitWriteFinish=True)) == dict(stabilityThreshold=2000,pollInterval=100)
    assert write_finish(dict(awaitWriteFinish={})) == dict(stabilityThreshold=2000,pollInterval=100)
    assert write_finish(dict(awaitWriteFinish=False)) is None
    assert atomic_delay({}) == .1
    assert atomic_delay(dict(usePolling=True)) == 0
    assert atomic_delay(dict(usePolling=True, atomic=200)) == .2
