import pytest

from dsh.core.abort import AbortController
from dsh.session.session_query import SessionQueryService, SessionQueryError
from test_session_live_persistence import backend
from test_prepared_persistence import persisted


@pytest.mark.asyncio
async def test_actual_durable_corpus_load_and_title_batch_are_cold_detached_and_immutable(backend):
    ctx, _, persistence = await persisted(backend)
    query = SessionQueryService(ctx, open_at='never', persisted_inspect_concurrency=2)
    try:
        await persistence.append('s', [{'type': 'session/title', 'seq': 2, 'time': 3,
            'data': {'title': 'Stored title', 'messageSeqs': [], 'source': {'kind': 'user'}}}])
        loaded = await query.readSession('s')
        assert len(loaded['events']) == 3
        assert ctx.get('sessions').get('s') is None
        loaded['events'][2]['data']['title'] = 'Foreign'
        first = await query.readTitleSnapshot('s')
        assert first['title']['title'] == 'Stored title'
        with pytest.raises(TypeError):
            first['title']['source']['kind'] = 'foreign'
        assert (await query.readTitle('s'))['title'] == 'Stored title'
        results = await query.readTitleSnapshots(['s', 's', 'missing'])
        assert [(row['sessionId'], row['status']) for row in results] == [('s', 'fulfilled'), ('missing', 'rejected')]
        assert results[1]['reason'].code == 'SESSION_QUERY_SESSION_NOT_FOUND'
        assert ctx.get('sessions').get('s') is None
    finally:
        query.close()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_actual_durable_title_batch_pre_abort_preserves_reason_without_listing(backend, monkeypatch):
    ctx, _, persistence = await persisted(backend)
    query = SessionQueryService(ctx, open_at='never')
    controller = AbortController()
    failure = TypeError('title deadline')
    controller.abort(failure)
    async def accessed(signal=None):
        raise AssertionError('aborted batch listed persistence')
    monkeypatch.setattr(persistence, 'list', accessed)
    try:
        with pytest.raises(TypeError) as error:
            await query.readTitleSnapshots(['s'], controller.signal)
        assert error.value is failure
    finally:
        query.close()
        await ctx.fiber.dispose()


@pytest.mark.parametrize('value', [0, -1, 1.5, True, '2', 9007199254740992, float('nan'), float('inf')])
def test_title_batch_refuses_invalid_inspection_concurrency(value):
    with pytest.raises(SessionQueryError) as error:
        SessionQueryService(None, open_at='never', persisted_inspect_concurrency=value)
    assert error.value.code == 'SESSION_QUERY_INVALID_CONFIG'
    assert error.value.message == 'session-query: persistedInspectConcurrency must be a positive safe integer'


@pytest.mark.parametrize('value', [1, 1.0, 9007199254740991])
def test_title_batch_accepts_safe_integer_inspection_concurrency(value):
    query = SessionQueryService(None, open_at='never', persisted_inspect_concurrency=value)
    try:
        assert query._corpus.persisted_inspect_concurrency == int(value)
    finally:
        query.close()
