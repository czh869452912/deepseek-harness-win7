import pytest

from dsh.core.abort import AbortController
from dsh.session.session_query import SessionQueryService
from dsh.session.persistence_jsonl import JsonlSessionPersistence
from test_session_live_persistence import backend
from test_prepared_persistence import persisted


@pytest.mark.asyncio
async def test_actual_durable_list_refuses_exact_pre_abort_before_backend_access(backend, monkeypatch):
    ctx, _, persistence = await persisted(backend)
    controller = AbortController()
    failure = TypeError('cancel durable listing')
    controller.abort(failure)
    def accessed(*args):
        raise AssertionError('aborted listing accessed backend')
    try:
        if isinstance(persistence, JsonlSessionPersistence):
            monkeypatch.setattr('dsh.session.persistence_jsonl.os.listdir', accessed)
        else:
            class NoDatabaseAccess:
                cursor = accessed
            monkeypatch.setattr(persistence, '_conn', NoDatabaseAccess())
        with pytest.raises(TypeError) as error:
            await persistence.list(controller.signal)
        assert error.value is failure
    finally:
        monkeypatch.undo()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_actual_durable_list_keeps_live_precedence_and_detaches_returned_headers(backend):
    ctx, _, persistence = await persisted(backend)
    query = SessionQueryService(ctx, open_at='never')
    try:
        records = await query.listSessions(AbortController().signal)
        assert [(row['header'].id, row['live'], row['persisted']) for row in records] == [('s', False, True)]
        records[0]['header'].cwd = '/foreign'
        assert (await query.listSessions())[0]['header'].cwd != '/foreign'
        prepared = await persistence.prepare('s')
        ctx.get('sessions').enter(prepared.session)
        prepared.dispose()
        rows = await query.listSessions()
        assert [(row['header'].id, row['live'], row['persisted']) for row in rows] == [('s', True, True)]
    finally:
        query.close()
        await ctx.fiber.dispose()
