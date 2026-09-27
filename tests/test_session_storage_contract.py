"""Public storage cases derived from upstream persistence contract/coordinator."""
import asyncio
from pathlib import Path
import pytest
from dsh.core.session import SessionHeader
from dsh.core.abort import AbortController
from dsh.session.persistence import SessionFormatUnsupportedError
from test_session_live_persistence import backend, mount


def event(seq=0, kind='session/end-seed', data=None):
    return dict(type=kind, seq=seq, time=seq + 1, data={} if data is None else data)


@pytest.mark.asyncio
async def test_lazy_create_detaches_metadata_and_blocks_duplicate_any_scope(backend):
    ctx, _, p = await mount(backend)
    try:
        meta = SessionHeader('s', created_at=1)
        await p.create(meta)
        meta.created_at = 20
        assert await p.list() == []
        with pytest.raises(FileNotFoundError): await p.read_from('s', 0)
        with pytest.raises(ValueError, match='already'): await p.create(SessionHeader('s', cwd=str(Path.cwd())))
        await p.append('s', [event()])
        assert (await p.read_from('s', 0)).meta.created_at == 1
        fresh = backend[2]()
        try:
            with pytest.raises(ValueError, match='persisted'): await fresh.create(SessionHeader('s', cwd=str(Path.cwd())))
        finally:
            if hasattr(fresh, 'close'): fresh.close()
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_whole_batch_cursor_rejection_and_retry(backend):
    ctx, _, p = await mount(backend)
    try:
        await p.create(SessionHeader('s'))
        with pytest.raises(ValueError, match='seq mismatch'): await p.append('s', [event(), event(2)])
        assert await p.list() == []
        await p.append('s', [event()])
        for seq in (0, 2, True):
            with pytest.raises(ValueError, match='seq mismatch'): await p.append('s', [event(seq)])
        assert len((await p.read_from('s', 0)).events) == 1
        await p.append('s', [event(1)])
        assert [e['seq'] for e in (await p.read_from('s', 0)).events] == [0, 1]
        with pytest.raises(FileNotFoundError): await p.append('missing', [event()])
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_cold_append_repairs_before_cursor_adoption(backend):
    ctx, _, p = await mount(backend)
    try:
        await p.create(SessionHeader('s'))
        await p.append('s', [event(kind='turn/start', data={'turn': 1})])
        fresh = backend[2]()
        try:
            await fresh.append('s', [event(2)])
            assert [e['type'] for e in (await fresh.read_from('s', 0)).events] == ['turn/start', 'turn/end', 'session/end-seed']
        finally:
            if hasattr(fresh, 'close'): fresh.close()
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_empty_live_materialization_and_public_cursor_share_state(backend):
    ctx, _, p = await mount(backend)
    try:
        session = ctx.get('sessions').create('s')
        await p.ensure_materialized(session)
        await p.ensure_materialized(session)
        assert (await p.read_from('s', 0)).events == []
        session.append('turn/start', {'turn': 1})
        await session.flush()
        assert [e['seq'] for e in (await p.read_from('s', 0)).events] == [0]
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,data', [('mode/set', {}), ('request/header-delta', {}), ('request/header', {'reason': 'fallback'})])
async def test_retired_vocabulary_rejects_write_without_materialization(backend, kind, data):
    ctx, _, p = await mount(backend)
    try:
        await p.create(SessionHeader('s'))
        with pytest.raises(ValueError, match='legacy'): await p.append('s', [event(kind=kind, data=data)])
        assert await p.list() == []
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_unknown_event_writes_but_reads_fail_closed(backend):
    ctx, _, p = await mount(backend)
    try:
        await p.create(SessionHeader('s'))
        await p.append('s', [event(kind='future/plugin')])
        for read in (p.load, p.inspect, lambda sid: p.read_from(sid, 0)):
            with pytest.raises(SessionFormatUnsupportedError, match='raw log'): await read('s')
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_cold_schema_refuses_before_repair(backend):
    ctx, _, p = await mount(backend)
    try:
        await p.create(SessionHeader('s'))
        invalid = event(kind='turn/start', data={'turn': 1}); invalid['time'] = 'bad'
        await p.append('s', [invalid])
        for read in (p.inspect, p.load):
            with pytest.raises(ValueError, match='envelope'): await read('s')
        assert len((await p.read_from('s', 0)).events) == 1
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_queued_append_snapshots_and_read_abort_does_not_mutate_storage(backend):
    ctx, _, p = await mount(backend)
    try:
        await p.create(SessionHeader('s'))
        lock = p.storage_lock('s'); await lock.acquire()
        events = [event()]; append = asyncio.create_task(p.append('s', events))
        await asyncio.sleep(0); events[0]['data']['changed'] = True
        controller = AbortController(); reason = ValueError('cancel queued read')
        read = asyncio.create_task(p.read_from('s', 0, controller.signal))
        await asyncio.sleep(0); controller.abort(reason)
        with pytest.raises(ValueError) as raised: await asyncio.wait_for(read, 1)
        assert raised.value is reason
        lock.release(); await append
        assert (await p.read_from('s', 0)).events == [event()]
    finally: await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_cold_append_does_not_repair_invalid_seed(backend):
    ctx, _, p = await mount(backend)
    try:
        await p.create(SessionHeader('s'))
        ev = event(kind='turn/start', data={'turn': 1}); ev['time'] = 'invalid'
        await p.append('s', [ev])
        fresh = backend[2]()
        try:
            with pytest.raises(ValueError, match='envelope'): await fresh.append('s', [event(2)])
            assert len((await fresh.read_from('s', 0)).events) == 1
        finally:
            if hasattr(fresh, 'close'): fresh.close()
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_first_batch_competing_backends_cannot_clobber_artifact(backend):
    first = backend[2](); second = backend[2]()
    try:
        await first.create(SessionHeader('s', created_at=1))
        await second.create(SessionHeader('s', created_at=2))
        await first.append('s', [event()])
        with pytest.raises(Exception): await second.append('s', [event(kind='turn/start', data={'turn': 1})])
        saved = await first.read_from('s', 0)
        assert saved.meta.created_at == 1 and saved.events == [event()]
        assert second.storage().states['s']['cursor'] == 0
        if hasattr(first, 'root'): assert not list(Path(first.root).rglob('*.tmp'))
    finally:
        for p in (first, second):
            if hasattr(p, 'close'): p.close()


@pytest.mark.asyncio
async def test_jsonl_failed_first_fsync_leaves_no_artifact_and_retries(tmp_path, monkeypatch):
    import os
    from dsh.session.persistence_jsonl import JsonlSessionPersistence
    p = JsonlSessionPersistence(str(tmp_path)); meta = SessionHeader('s'); await p.create(meta)
    original = os.fsync
    def fail(fd): raise OSError('first fsync')
    monkeypatch.setattr(os, 'fsync', fail)
    with pytest.raises(OSError, match='first fsync'): await p.append('s', [event()])
    assert await p.list() == [] and not list(tmp_path.rglob('*.tmp'))
    monkeypatch.setattr(os, 'fsync', original)
    await p.append('s', [event()])
    assert (await p.read_from('s', 0)).events == [event()]
