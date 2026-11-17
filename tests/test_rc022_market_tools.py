"""Shared-read cancellation and optional market tool lifecycle boundaries."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from dsh.core.abort import AbortController,NEVER_ABORTED
from dsh.boot.plugin_market_tools import until_aborted,english,version_result
from scripts.rc022_market_tools_probe import observe


@pytest.mark.asyncio
@pytest.mark.parametrize('reason',[RuntimeError('cancelled by user'),'plain reason'])
async def test_aborted_waiter_leaves_shared_read_live_and_observed(reason):
    controller=AbortController();future=asyncio.get_running_loop().create_future()
    waiting=asyncio.create_task(until_aborted(future,controller.signal))
    for _ in range(3):await asyncio.sleep(0)
    controller.abort(reason)
    with pytest.raises(RuntimeError,match='cancelled by user' if isinstance(reason,Exception) else 'Aborted') as caught:await waiting
    if isinstance(reason,Exception):assert caught.value is reason
    assert not future.cancelled() and controller.signal._listeners==[]
    future.set_result(dict(cached=True));await asyncio.sleep(0);await asyncio.sleep(0)
    assert future.result()==dict(cached=True)


@pytest.mark.asyncio
async def test_one_cancelled_waiter_does_not_cancel_another():
    controller=AbortController();future=asyncio.get_running_loop().create_future()
    one=asyncio.create_task(until_aborted(future,controller.signal));two=asyncio.create_task(until_aborted(future,NEVER_ABORTED))
    for _ in range(3):await asyncio.sleep(0)
    one.cancel()
    with pytest.raises(asyncio.CancelledError):await one
    assert not future.cancelled();future.set_result('shared');assert await two=='shared'
    assert controller.signal._listeners==[]


@pytest.mark.asyncio
async def test_source_derived_dispatch_observations(tmp_path):
    rows=await observe();(tmp_path/'market-tools-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert rows[0]==dict(name='absent',visible=False) and rows[-1]==dict(name='withdrawn',visible=False)
    page=json.loads(rows[3]['value']['value']);assert page['entries'][0]['versionCount']==7
    assert page['entries'][0]['title'].endswith('\ud83d…') and 'description' not in page['entries'][0]
    assert page['entries'][1]['defaultVersion'] is None


def test_english_truncates_utf16_units_and_date_supports_extended_years():
    assert english('x'*300)=='x'*300
    assert english('x'*299+'😀')=='x'*299+'\ud83d…'
    def version(stamp):return version_result(dict(version='1',publishTimestamp=stamp,compatibility={},install=dict(spec='bundle')))['published']
    assert version(-62167219200)=='0000-01-01T00:00:00.000Z'
    assert version(253402300800)=='+010000-01-01T00:00:00.000Z'
