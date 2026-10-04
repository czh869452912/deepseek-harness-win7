import pytest

from dsh.core.abort import AbortController
from dsh.core.session import SessionHeader
from dsh.session.session_query import SessionQueryService
from test_session_live_persistence import backend
from test_prepared_persistence import persisted


@pytest.mark.asyncio
async def test_actual_durable_lineage_is_cold_ordered_and_marks_unresolved_parent(backend):
    context, _, persistence = await persisted(backend)
    await persistence.create(SessionHeader('b', created_at=4, parent_session='s'))
    await persistence.create(SessionHeader('a', created_at=4, parent_session='s'))
    await persistence.create(SessionHeader('older', created_at=3, parent_session='s'))
    await persistence.create(SessionHeader('partial', created_at=2, parent_session='outside'))
    for identity in ['b', 'a', 'older', 'partial']:
        await persistence.append(identity, [dict(type='turn/start', seq=0, time=1, data=dict(turn=1))])
    query = SessionQueryService(context, open_at='never')
    try:
        trace = await query.traceSession('s')
        assert trace['complete']
        assert trace['root']['header'].id == 's'
        assert [node['session']['header'].id for node in trace['descendants']] == ['older','a','b']
        trace['descendants'][0]['session']['header'].cwd = 'foreign'
        repeated = await query.traceSession('s')
        assert repeated['descendants'][0]['session']['header'].cwd is None
        partial = await query.traceSession('partial')
        assert partial['complete'] is False
        assert partial['unresolvedParentId'] == 'outside'
        assert 'root' not in partial
        assert context.get('sessions').list() == []
    finally:
        query.close()
        await context.fiber.dispose()


@pytest.mark.asyncio
async def test_actual_durable_lineage_pre_abort_uses_exact_reason_without_backend_access(backend, monkeypatch):
    context, _, persistence = await persisted(backend)
    query = SessionQueryService(context, open_at='never')
    controller = AbortController()
    failure = TypeError('lineage deadline')
    controller.abort(failure)
    async def accessed(signal=None):
        raise AssertionError('aborted lineage listed backend')
    monkeypatch.setattr(persistence, 'list', accessed)
    try:
        with pytest.raises(TypeError) as error:
            await query.traceSession('s', dict(signal=controller.signal))
        assert error.value is failure
    finally:
        query.close()
        await context.fiber.dispose()
