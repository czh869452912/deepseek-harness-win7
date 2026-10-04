import asyncio

import pytest

from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.cordis.errors import ThrownValueError
from dsh.core.abort import AbortController
from dsh.core.session import SessionHeader, SessionPlugin
from dsh.session.query_engine import SqliteSessionQueryEngine, SqliteSessionQueryPlugin, decode_cursor, encode_cursor
from dsh.session.session_query import SessionQueryError
from test_session_live_persistence import backend, mount


def message(text, seq=0, time=1):
    return dict(type='user/message', seq=seq, time=time, surfaceOp='append',
                data=dict(id='message-'+str(seq), role='user', content=[dict(type='text', text=text)], source=dict(kind='user')))


@pytest.mark.asyncio
async def test_query_engine_actual_durable_search_incremental_revision_and_live_preference(backend):
    context, _, persistence = await mount(backend)
    await persistence.create(SessionHeader('stored', created_at=1))
    await persistence.append('stored', [message('needle durable')])
    query = SqliteSessionQueryEngine(context, dict(path=':memory:', openAt='first-search', defaultLimit=1, maxLimit=2))
    try:
        result = await query.searchSessions(dict(query='needle'))
        assert [(item['header'].id, item['live'], item['persisted'], item['bestMatch']['snippet'])
                for item in result['items']] == [('stored', False, True, 'needle durable')]
        generation = query._global_generation
        assert await query.searchSessions(dict(query='needle')) == result
        assert query._global_generation == generation
        await persistence.append('stored', [message('needle needle next', 1, 2)])
        updated = await query.searchEvents(dict(sessionId='stored', query='needle', limit=1))
        assert updated['items'][0]['seq'] == 1 and 'nextCursor' in updated
        await persistence.append('stored', [message('needle newest', 2, 3)])
        with pytest.raises(SessionQueryError) as stale:
            await query.searchEvents(dict(sessionId='stored', query='needle', limit=1, cursor=updated['nextCursor']))
        assert stale.value.code == 'SESSION_QUERY_STALE_CURSOR'
        assert context.get('sessions').get('stored') is None
    finally:
        await query.close()
        await context.fiber.dispose()


@pytest.mark.asyncio
async def test_query_engine_actual_live_events_page_rank_owned_request_and_filter_budgets():
    context = Context()
    await context.plugin(SessionPlugin)
    sessions = context.get('sessions')
    first = sessions.create('alpha')
    first.append('user/message', message('needle long long')['data'], surface_op='append')
    first.append('user/message', message('needle needle')['data'], surface_op='append')
    second = sessions.create('beta')
    second.append('user/message', message('needle')['data'], surface_op='append')
    query = SqliteSessionQueryEngine(context, dict(path=':memory:', openAt='first-search', defaultLimit=1, maxLimit=2))
    try:
        request = dict(query='needle', sessionFilters=[dict(kind='id', values=['alpha', 'beta'])])
        accepted = query.searchSessions(request)
        request['sessionFilters'][0]['values'].clear()
        result = await accepted
        assert result['items'][0]['header'].id == 'alpha'
        assert result['items'][0]['bestMatch']['seq'] == 1
        continuation = await query.searchSessions(dict(query='needle', sessionFilters=[dict(kind='id', values=['beta', 'alpha'])],
                                                       cursor=result['nextCursor']))
        assert continuation['items'][0]['header'].id == 'beta' and 'nextCursor' not in continuation
        events = await query.searchEvents(dict(sessionId='alpha', query='needle', limit=2))
        assert [item['seq'] for item in events['items']] == [1, 0]
        with pytest.raises(SessionQueryError) as failure:
            await query.searchEvents(dict(sessionId='alpha', query='needle', filters=[dict(kind='seq', **{'from': 0})] * 14))
        assert failure.value.code == 'SESSION_QUERY_INVALID_FILTER'
        assert (await query.searchSessions(dict(query='needle', limit=2)))['items'][0]['header'].id == 'alpha'
    finally:
        await query.close()
        await context.fiber.dispose()


@pytest.mark.asyncio
async def test_query_engine_shared_readiness_abort_and_close_drain(monkeypatch):
    context = Context()
    await context.plugin(SessionPlugin)
    query = SqliteSessionQueryEngine(context, dict(path=':memory:', openAt='first-search'))
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    original = query._open
    async def blocked():
        calls.append('open')
        entered.set()
        await release.wait()
        await original()
    monkeypatch.setattr(query, '_open', blocked)
    controller = AbortController()
    try:
        first = query.searchSessions(dict(query='needle'), dict(signal=controller.signal))
        await entered.wait()
        second = query.searchSessions(dict(query='needle'))
        controller.abort(TypeError('caller reason'))
        with pytest.raises(SessionQueryError) as failure:
            await first
        assert failure.value.code == 'SESSION_QUERY_ABORTED'
        assert not query._ready.cancelled()
        release.set()
        assert await second == dict(items=[])
        assert calls == ['open']
        closing = query.close()
        assert query.close() is closing
        await closing
        with pytest.raises(SessionQueryError) as failure:
            await query.searchSessions(dict(query='needle'))
        assert failure.value.message == 'session-search SQLite index is closed'
        assert query._db is None
    finally:
        release.set()
        await query.close()
        await context.fiber.dispose()


@pytest.mark.asyncio
async def test_query_engine_preabort_disabled_and_invalid_requests_never_open(monkeypatch):
    context = Context()
    await context.plugin(SessionPlugin)
    controller = AbortController()
    controller.abort()
    query = SqliteSessionQueryEngine(context, dict(path=':memory:', openAt='first-search'))
    async def forbidden():
        raise AssertionError('invalid request opened SQLite')
    monkeypatch.setattr(query, '_open', forbidden)
    try:
        for request, options, code in [
            (dict(query='needle'), dict(signal=controller.signal), 'SESSION_QUERY_ABORTED'),
            (dict(query=' '), None, 'SESSION_QUERY_INVALID_QUERY'),
            (dict(query='needle', limit=0), None, 'SESSION_QUERY_INVALID_LIMIT'),
        ]:
            with pytest.raises(SessionQueryError) as failure:
                await query.searchSessions(request, options)
            assert failure.value.code == code and query._ready is None
        query.open_at = 'never'
        with pytest.raises(SessionQueryError) as failure:
            await query.searchSessions(dict(query=None))
        assert failure.value.code == 'SESSION_QUERY_SEARCH_DISABLED' and query._ready is None
    finally:
        await query.close()
        await context.fiber.dispose()


@pytest.mark.parametrize('patch,detail', [
    ({'path': ''}, 'path must not be blank'),
    ({'path': '\ufeff '}, 'path must not be blank'),
    ({'openAt': 'immediate'}, 'openAt is not supported'),
    ({'defaultLimit': True}, 'defaultLimit must be an integer between 1 and 9007199254740990'),
    ({'maxLimit': 0}, 'maxLimit must be an integer between 1 and 9007199254740990'),
    ({'snippetChars': 0}, 'snippetChars must be a positive integer'),
    ({'readWindowMax': -1}, 'readWindowMax must be a non-negative integer'),
    ({'persistedInspectConcurrency': 9007199254740992}, 'persistedInspectConcurrency must be a positive safe integer'),
    ({'defaultLimit': 101}, 'defaultLimit must be less than or equal to maxLimit'),
    ({'journalMode': 'off'}, 'journalMode is not supported'),
])
def test_query_engine_configuration_refuses_before_context_access(patch, detail):
    with pytest.raises(SessionQueryError) as failure:
        SqliteSessionQueryEngine(None, dict(dict(path=':memory:'), **patch))
    assert failure.value.code == 'SESSION_QUERY_INVALID_CONFIG'
    assert failure.value.message == 'session-search SQLite config: ' + detail


@pytest.mark.parametrize('offset', [-1, True, 1.5, 9007199254740992, None])
def test_query_engine_cursor_rejects_foreign_or_unsafe_offset(offset):
    cursor = encode_cursor(dict(version=1, instance='owned', scope='events', fingerprint='f', generation='g', offset=offset))
    with pytest.raises(SessionQueryError) as failure:
        decode_cursor(cursor, 'owned', 'events', 'f', 'g')
    assert failure.value.code == 'SESSION_QUERY_INVALID_CURSOR'


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['list', 'inspect'])
async def test_query_engine_abort_ignoring_source_holds_serialization_until_cleanup(boundary):
    context = Context()
    await context.plugin(SessionPlugin)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    class Persistence:
        async def listSnapshots(self, signal=None):
            calls.append(('list', signal))
            if boundary == 'list' and len(calls) == 1:
                entered.set()
                await release.wait()
            return [dict(header=SessionHeader('s', created_at=1), revision='1')]
        async def inspect(self, session_id, signal=None):
            calls.append(('inspect', signal))
            if boundary == 'inspect' and not release.is_set():
                entered.set()
                await release.wait()
            return dict(meta=SessionHeader('s', created_at=1), events=[message('needle')])
    provider = context.provide('sessionPersistence', Persistence())
    query = SqliteSessionQueryEngine(context, dict(path=':memory:', openAt='first-search'))
    controller = AbortController()
    try:
        first = query.searchSessions(dict(query='needle'), dict(signal=controller.signal))
        await entered.wait()
        calls_at_abort = list(calls)
        controller.abort(TypeError('owned deadline'))
        second = query.searchEvents(dict(sessionId='s', query='needle'))
        queued_controller = AbortController()
        queued = query.searchSessions(dict(query='needle'), dict(signal=queued_controller.signal))
        queued_controller.abort()
        with pytest.raises(SessionQueryError) as failure:
            await queued
        assert failure.value.code == 'SESSION_QUERY_ABORTED'
        assert not first.done() and not second.done() and calls == calls_at_abort
        release.set()
        with pytest.raises(SessionQueryError) as failure:
            await first
        assert failure.value.code == 'SESSION_QUERY_ABORTED'
        assert (await second)['items'][0]['sessionId'] == 's'
        assert query._global_generation == 1
    finally:
        release.set()
        await query.close()
        provider()
        await context.fiber.dispose()


@pytest.mark.asyncio
async def test_query_engine_close_drains_accepted_source_and_refuses_queued_work():
    context = Context()
    await context.plugin(SessionPlugin)
    entered, release = asyncio.Event(), asyncio.Event()
    class Persistence:
        async def listSnapshots(self, signal=None):
            entered.set()
            await release.wait()
            return []
    provider = context.provide('sessionPersistence', Persistence())
    query = SqliteSessionQueryEngine(context, dict(path=':memory:', openAt='first-search'))
    try:
        accepted = query.searchSessions(dict(query='needle'))
        await entered.wait()
        queued = query.searchSessions(dict(query='needle'))
        closing = query.close()
        await asyncio.sleep(0)
        assert not closing.done() and query._db is not None
        release.set()
        assert await accepted == dict(items=[])
        with pytest.raises(SessionQueryError) as failure:
            await queued
        assert failure.value.code == 'SESSION_QUERY_INDEX_FAILED'
        await closing
        assert query._db is None
    finally:
        release.set()
        await query.close()
        provider()
        await context.fiber.dispose()


@pytest.mark.asyncio
async def test_query_engine_failed_readiness_is_shared_and_closed_once(monkeypatch):
    context = Context()
    await context.plugin(SessionPlugin)
    query = SqliteSessionQueryEngine(context, dict(path=':memory:', openAt='first-search'))
    cause = TypeError('failed owned opener')
    calls = []
    async def failed():
        calls.append('open')
        raise cause
    monkeypatch.setattr(query, '_open', failed)
    try:
        for attempt in range(2):
            with pytest.raises(SessionQueryError) as failure:
                await query.searchSessions(dict(query='needle'))
            assert failure.value.code == 'SESSION_QUERY_INDEX_FAILED' and failure.value.cause is cause
        assert calls == ['open']
    finally:
        await query.close()
        await context.fiber.dispose()


@pytest.mark.asyncio
async def test_query_engine_failed_transaction_preserves_both_fts_generations_and_next_search(monkeypatch):
    context = Context()
    await context.plugin(SessionPlugin)
    live = context.get('sessions').create('s')
    live.append('user/message', message('needle old')['data'], surface_op='append')
    query = SqliteSessionQueryEngine(context, dict(path=':memory:', openAt='first-search'))
    try:
        first = await query.searchSessions(dict(query='needle'))
        generation = query._global_generation
        local = query._local_generation
        database = query._db
        original = database.exec
        cause = TypeError('controlled commit refusal')
        def failed(sql):
            if sql == 'COMMIT':
                raise cause
            return original(sql)
        live.append('user/message', message('needle needle fresh')['data'], surface_op='append')
        monkeypatch.setattr(database, 'exec', failed)
        with pytest.raises(SessionQueryError) as failure:
            await query.searchSessions(dict(query='needle'))
        assert failure.value.code == 'SESSION_QUERY_INDEX_FAILED' and failure.value.cause is cause
        assert query._global_generation == generation and query._local_generation == local
        assert database.prepare('SELECT text FROM temp.live_docs').all() == [dict(text='needle old')]
        monkeypatch.setattr(database, 'exec', original)
        assert (await query.searchSessions(dict(query='needle')))['items'][0]['bestMatch']['seq'] == 1
        assert first['items'][0]['bestMatch']['seq'] == 0
    finally:
        await query.close()
        await context.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['startup', 'first-search', 'never'])
async def test_query_engine_actual_cordis_publication_readiness_and_retirement(tmp_path, phase):
    context = Context()
    await context.plugin(SessionPlugin)
    path = tmp_path / 'derived.sqlite'
    try:
        plugin = await context.plugin(SqliteSessionQueryPlugin, dict(path=str(path), openAt=phase))
        query = context.get('sessionQuery')
        assert isinstance(query, SqliteSessionQueryEngine)
        assert path.exists() == (phase == 'startup')
        assert context.get('tools') is None
        if phase != 'never':
            assert await query.searchSessions(dict(query='needle')) == dict(items=[])
            assert path.is_file()
        await plugin.dispose()
        assert context.get('sessionQuery') is None
        assert query._db is None and query._optional.state == FiberState.DISPOSED
    finally:
        await context.fiber.dispose()


@pytest.mark.asyncio
async def test_query_engine_optional_provider_child_disposal_waits_for_cleanup():
    context = Context()
    await context.plugin(SessionPlugin)
    plugin = await context.plugin(SqliteSessionQueryPlugin, dict(path=':memory:'))
    provider = context.provide('sessionPersistence', object())
    release, entered = asyncio.Event(), asyncio.Event()
    query = context.get('sessionQuery')
    async def cleanup():
        entered.set()
        await release.wait()
    query._optional.ctx.effect(lambda: cleanup)
    try:
        disposing = asyncio.ensure_future(plugin.dispose())
        await entered.wait()
        assert not disposing.done()
        release.set()
        await disposing
        assert query._db is None
    finally:
        release.set()
        provider()
        await context.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('with_signal', [False, True])
async def test_query_engine_readiness_non_error_value_preserves_source_wait_boundary(monkeypatch, with_signal):
    context = Context()
    await context.plugin(SessionPlugin)
    query = SqliteSessionQueryEngine(context, dict(path=':memory:', openAt='first-search'))
    cause = dict(dependency='unavailable')
    async def failed():
        raise ThrownValueError(cause)
    monkeypatch.setattr(query, '_open', failed)
    try:
        with pytest.raises(SessionQueryError) as failure:
            await query.searchSessions(dict(query='needle'), dict(signal=AbortController().signal) if with_signal else None)
        assert failure.value.code == 'SESSION_QUERY_INDEX_FAILED'
        if with_signal:
            assert failure.value.message.endswith('session-search dependency rejected with a non-Error value')
            assert failure.value.cause.cause is cause
        else:
            assert failure.value.message.endswith('unknown error') and failure.value.cause is cause
    finally:
        await query.close()
        await context.fiber.dispose()
