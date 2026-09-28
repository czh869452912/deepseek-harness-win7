import asyncio
import pytest

from dsh.core.abort import AbortController
from dsh.session.session_query import SessionQueryService, SessionQueryError
from test_session_live_persistence import backend, turn
from test_prepared_persistence import persisted


@pytest.mark.asyncio
async def test_cold_observation_retains_exact_cut_across_resume(backend):
    ctx, _, persistence = await persisted(backend)
    query = SessionQueryService(ctx, open_at='never')
    try:
        cut = await query.observeSession('s')
        retained = cut.retain()
        assert cut.source == 'prepared' and cut.cursor == 1
        assert persistence.prepared().pool.entries['s'].pins == 1
        cut.dispose()
        with pytest.raises(RuntimeError):
            cut.retain()
        prepared = await persistence.prepare('s')
        session = prepared.session
        ctx.get('sessions').enter(session)
        ctx.get('sessions').announce(session)
        prepared.dispose()
        turn(session, 2)
        live = await query.observeSession('s', {'projectionMode': 'none'})
        assert live.source == 'live' and live.cursor > retained.cursor
        assert len(retained.events) == 2
        with pytest.raises(TypeError):
            retained.events[0]['data']['turn'] = 99
        retained.dispose()
        retained.dispose()
        live.dispose()
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_observation_cancel_does_not_cancel_shared_loader(backend):
    ctx, _, persistence = await persisted(backend)
    query = SessionQueryService(ctx, open_at='never')
    original = persistence._inspect_unshared
    entered, gate = asyncio.Event(), asyncio.Event()
    calls = []
    async def blocked(sid):
        calls.append(sid)
        entered.set()
        await gate.wait()
        return await original(sid)
    persistence._inspect_unshared = blocked
    abort = AbortController()
    first = asyncio.create_task(query.observeSession('s', {'signal': abort.signal}))
    await entered.wait()
    second = asyncio.create_task(query.observeSession('s'))
    abort.abort(ValueError('cancel observation'))
    try:
        with pytest.raises(SessionQueryError) as error:
            await first
        assert error.value.code == 'SESSION_QUERY_ABORTED'
        gate.set()
        cut = await second
        assert calls == ['s'] and cut.cursor == 1
        cut.dispose()
        assert persistence.prepared().pool.entries['s'].pins == 0
    finally:
        gate.set()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_publication_during_cold_read_prefers_live(backend):
    ctx, _, persistence = await persisted(backend)
    original = persistence.borrowSession
    async def publishing(sid, signal=None):
        borrowed = await original(sid, signal)
        prepared = await persistence.prepare(sid)
        session = prepared.session
        ctx.get('sessions').enter(session)
        ctx.get('sessions').announce(session)
        prepared.dispose()
        turn(session, 2)
        return borrowed
    persistence.borrowSession = publishing
    try:
        cut = await SessionQueryService(ctx, open_at='never').observeSession('s')
        assert cut.source == 'live' and cut.cursor > 1
        cut.dispose()
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_external_revision_change_refreshes_cut_without_mutating_retained_view(backend):
    ctx, _, persistence = await persisted(backend)
    query = SessionQueryService(ctx, open_at='never')
    try:
        old = await query.observeSession('s')
        await persistence._append('s', [dict(type='turn/start', seq=2, time=3, data=dict(turn=2))])
        fresh = await query.observeSession('s')
        assert fresh.revision != old.revision and fresh.cursor > old.cursor
        assert len(old.events) == 2
        old.dispose()
        fresh.dispose()
        with pytest.raises(SessionQueryError) as error:
            await query.observeSession('missing')
        assert error.value.code == 'SESSION_QUERY_SESSION_NOT_FOUND'
        assert isinstance(error.value.cause, FileNotFoundError)
    finally:
        await ctx.fiber.dispose()
