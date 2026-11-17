import asyncio
import json

import pytest

from dsh.boot import market_index_022 as market
from dsh.core.abort import AbortController
from dsh.javascript.runtime import JavaScriptRuntimeError
from scripts.rc022_market_body_probe import cases, URL


@pytest.mark.asyncio
async def test_utf8_and_json_acceptance():
    rows = [await market.parse_index_body(body, URL) for body in cases()]
    assert len(rows) == 41
    assert rows[0] == rows[1]
    assert rows[0]['ok']
    assert all(row['reason'] == 'must be UTF-8' for row in rows[11:27])
    assert rows[34]['ok'] and rows[34]['index']['format'] == 1
    assert rows[35]['index']['title'] == '\ud800'
    assert rows[36]['index']['title'] == '\0'
    assert rows[37]['ok'] and rows[38]['ok']
    assert rows[-1]['reason'].startswith('must be JSON: ')


@pytest.mark.asyncio
async def test_async_worker_matches_sync_without_blocking_host():
    operation = dict(kind='parse', value=dict(format=1, title='Market', plugins=[]), url=URL)
    ticks = []
    async def tick():
        while not ticks or len(ticks) < 2:
            ticks.append(1); await asyncio.sleep(0)
    counter = asyncio.create_task(tick())
    rows = await market.observe_market_operations_async([operation])
    await counter
    assert rows == market.observe_market_operations([operation])
    assert len(ticks) == 2


@pytest.mark.asyncio
async def test_already_aborted_never_spawns(monkeypatch):
    controller = AbortController(); reason = RuntimeError('gone'); controller.abort(reason)
    def forbidden(): raise AssertionError('must not bootstrap')
    monkeypatch.setattr(market, 'market_bootstrap', forbidden)
    with pytest.raises(RuntimeError) as caught: await market.parse_index_body(b'\xff', URL, controller.signal)
    assert caught.value is reason


@pytest.mark.asyncio
async def test_signal_abort_terminates_actual_child(monkeypatch):
    original = asyncio.create_subprocess_exec; spawned = []; entered = asyncio.Event()
    async def spawn(*args, **kwargs):
        process = await original(*args, **kwargs); spawned.append(process); entered.set(); return process
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setattr(market, 'market_bootstrap', lambda: 'globalThis.__receive=()=>{};globalThis.__drive=()=>{while(true){}};')
    controller = AbortController(); reason = RuntimeError('stop parsing')
    task = asyncio.create_task(market.observe_market_operations_async([], controller.signal))
    await entered.wait(); await asyncio.sleep(0); controller.abort(reason)
    with pytest.raises(RuntimeError) as caught: await task
    assert caught.value is reason
    assert spawned[0].returncode is not None
    assert not controller.signal._listeners


@pytest.mark.asyncio
async def test_repeated_cancel_during_spawn_waits_for_owned_child(monkeypatch):
    original = asyncio.create_subprocess_exec; spawned = []; entered, release = asyncio.Event(), asyncio.Event()
    async def spawn(*args, **kwargs):
        process = await original(*args, **kwargs); spawned.append(process); entered.set(); await release.wait(); return process
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    task = asyncio.create_task(market.observe_market_operations_async([]))
    await entered.wait(); task.cancel(); await asyncio.sleep(0); task.cancel(); await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError): await task
    assert spawned[0].returncode is not None


@pytest.mark.asyncio
async def test_bad_worker_protocol_fails_and_reaps_child(monkeypatch):
    monkeypatch.setattr(market, 'market_bootstrap', lambda:
        'globalThis.__receive=()=>{};globalThis.__drive=()=>__emit(JSON.stringify({type:"terminal",result:{}}));')
    with pytest.raises(JavaScriptRuntimeError, match='Market worker failed'):
        await market.observe_market_operations_async([])


@pytest.mark.asyncio
async def test_body_requires_bytes():
    with pytest.raises(TypeError, match='must be bytes'):
        await market.parse_index_body(bytearray(b'{}'), URL)
