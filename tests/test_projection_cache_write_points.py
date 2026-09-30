import asyncio
import json

import pytest

from dsh.cordis.context import Context
from dsh.core.session.session import SessionPlugin
from dsh.session.projections import SessionProjectionsPlugin
from dsh.session.projection_cache import SessionProjectionCachePlugin
from dsh.storage.hub import StoragePlugin
from dsh.storage.plugins import StorageDomainPlugin, StorageJsonPlugin


async def composition(root, count=100):
    ctx = Context()
    await ctx.plugin(SessionPlugin)
    await ctx.plugin(SessionProjectionsPlugin)
    await ctx.plugin(StoragePlugin)
    await ctx.plugin(StorageJsonPlugin, config={'root': str(root)})
    await ctx.plugin(StorageDomainPlugin, config={'backend': 'json'})
    ctx.get('sessionProjections').register({
        'key': 'count', 'stateVersion': 1, 'stateSchema': lambda value: int(value),
        'init': lambda header: 0, 'apply': lambda state, event: state + 1,
        'wire': {'viewSchema': lambda value: int(value), 'view': lambda state: state},
    })
    cache_fiber = ctx.plugin(SessionProjectionCachePlugin, config={'writeEveryEvents': count, 'writeIntervalMs': 60000})
    await cache_fiber
    return ctx, ctx.get('sessionProjectionCache'), cache_fiber


async def settle(cache):
    while cache.tasks:
        await asyncio.gather(*list(cache.tasks))


def append(session, value):
    session.append('cache-test/event', {'value': value}, ignorable=True)


@pytest.mark.asyncio
async def test_creation_and_explicit_write_capture_the_call_cut(tmp_path):
    ctx, cache, _ = await composition(tmp_path)
    try:
        session = ctx.get('sessions').create('call-cut')
        append(session, 1)
        await settle(cache)
        assert cache.cached_snapshot(session.header) == {'asOfSeq': -1, 'values': {'count': 0}}
        pending = cache.write(session)
        append(session, 2)
        await pending
        assert cache.cached_snapshot(session.header) == {'asOfSeq': 0, 'values': {'count': 1}}
        rows = json.loads((tmp_path / 'session_projcache' / 'sessions' / 'call-cut.json').read_text(encoding='utf-8'))['record']['rows']
        assert rows['count'] == {'ver': 1, 'seq': 0, 'val': 1}
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_count_threshold_resets_synchronously_between_back_to_back_events(tmp_path, monkeypatch):
    ctx, cache, _ = await composition(tmp_path, count=3)
    session = ctx.get('sessions').create('threshold')
    await settle(cache)
    observed = []
    put = cache.table.put

    async def record(key, value):
        observed.append(value['rows']['count'])
        await put(key, value)

    monkeypatch.setattr(cache.table, 'put', record)
    try:
        for value in range(6):
            append(session, value)
        await settle(cache)
        assert observed == [{'ver': 1, 'seq': 2, 'val': 3}, {'ver': 1, 'seq': 5, 'val': 6}]
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_flush_barrier_precedes_checkpoint_and_snapshot_is_detached(tmp_path):
    ctx, cache, _ = await composition(tmp_path)
    session = ctx.get('sessions').create('flush-cut')
    await settle(cache)
    entered, release = asyncio.Event(), asyncio.Event()

    async def flush(requested):
        assert requested is session
        entered.set()
        await release.wait()

    remove = ctx.on('session/flush', flush)
    writing = None
    try:
        append(session, 1)
        writing = asyncio.ensure_future(cache.write(session))
        await asyncio.wait_for(entered.wait(), 2)
        assert cache.cached_snapshot(session.header)['asOfSeq'] == -1
        append(session, 2)
        release.set()
        await writing
        assert cache.cached_snapshot(session.header) == {'asOfSeq': 0, 'values': {'count': 1}}
    finally:
        release.set()
        if writing is not None:
            await writing
        remove()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_non_json_state_is_refused_without_persisting_null_and_soft_path_recovers(tmp_path, caplog):
    ctx, cache, _ = await composition(tmp_path, count=1)
    session = ctx.get('sessions').create('invalid-state')
    await settle(cache)
    unregister = ctx.get('sessionProjections').register({
        'key': 'invalid', 'stateVersion': 1, 'stateSchema': lambda value: value,
        'init': lambda header: {'not-json'}, 'apply': lambda state, event: state,
    })
    try:
        with pytest.raises(ValueError, match='not losslessly JSON-serializable'):
            await cache.write(session)
        append(session, 1)
        await settle(cache)
        assert 'not losslessly JSON-serializable' in caplog.text
        rows = json.loads((tmp_path / 'session_projcache' / 'sessions' / 'invalid-state.json').read_text(encoding='utf-8'))['record']['rows']
        assert 'invalid' not in rows
        unregister()
        append(session, 2)
        await settle(cache)
        assert cache.cached_snapshot(session.header) == {'asOfSeq': 1, 'values': {'count': 2}}
    finally:
        unregister()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_cache_unload_drains_flush_then_reopen_preserves_exact_cut(tmp_path):
    ctx, cache, cache_fiber = await composition(tmp_path, count=1)
    session = ctx.get('sessions').create('unload-cache')
    await settle(cache)
    entered, release = asyncio.Event(), asyncio.Event()

    async def flush(requested):
        entered.set()
        await release.wait()

    remove = ctx.on('session/flush', flush)
    unloading = None
    try:
        append(session, 1)
        await asyncio.wait_for(entered.wait(), 2)
        unloading = asyncio.create_task(cache_fiber.dispose())
        await asyncio.sleep(0)
        assert not unloading.done()
        release.set()
        await unloading
        assert ctx.get('sessionProjectionCache', strict=False) is None
        append(session, 2)
        remove()
        await ctx.plugin(SessionProjectionCachePlugin, config={'writeEveryEvents': 1, 'writeIntervalMs': 60000})
        restored = ctx.get('sessionProjectionCache')
        assert restored.cached_snapshot(session.header) == {'asOfSeq': 0, 'values': {'count': 1}}
        await restored.write(session)
        assert restored.cached_snapshot(session.header) == {'asOfSeq': 1, 'values': {'count': 2}}
    finally:
        release.set()
        if unloading is not None:
            await unloading
        remove()
        await ctx.fiber.dispose()
