import copy
import json
from pathlib import Path
import pytest

from dsh.core.abort import AbortController
from dsh.session.session_query import SessionQueryService,SessionQueryError
from test_session_live_persistence import backend
from test_prepared_persistence import persisted


@pytest.mark.asyncio
async def test_actual_durable_filters_hold_inputs_before_await_and_classify_surface(backend):
    context,_,persistence = await persisted(backend)
    query = SessionQueryService(context,open_at='never')
    fixture = json.loads((Path(__file__).resolve().parents[1] /
        'scripts/oracles/session_event_trace_fixture.json').read_text(encoding='utf-8'))
    shifted = copy.deepcopy(fixture[1:5])
    for event in shifted:
        event['seq'] += 1
        if isinstance(event.get('surfaceOp'),dict):
            event['surfaceOp']['start'] += 1
            event['surfaceOp']['end'] += 1
        if 'sourceEventSeqs' in event:
            event['sourceEventSeqs'] = [seq + 1 for seq in event['sourceEventSeqs']]
    try:
        await persistence.append('s',shifted)
        clauses = [dict(kind='id',values=['s'])]
        pending = query.filterSessions(clauses)
        clauses[0]['values'][0] = 'foreign'
        assert [record['header'].id for record in await pending] == ['s']
        clauses = [dict(kind='surface',values=['current']),dict(kind='text',text='summary')]
        pending = query.filterEvents('s',clauses)
        clauses[0]['values'][0] = 'shadowed'
        documents = await pending
        assert [(document['seq'],document['surface'],document['text']) for document in documents] == [(5,'current','summary two')]
        documents[0]['text'] = 'foreign'
        repeated = await query.filterEvents('s',[dict(kind='surface',values=['shadowed'])])
        assert [(document['seq'],document['text']) for document in repeated] == [(2,'original'),(3,'summary one')]
        assert context.get('sessions').get('s') is None
    finally:
        query.close()
        await context.fiber.dispose()


@pytest.mark.asyncio
async def test_actual_durable_filter_pre_abort_and_invalid_bounds_do_not_access_backend(backend,monkeypatch):
    context,_,persistence = await persisted(backend)
    query = SessionQueryService(context,open_at='never')
    controller = AbortController()
    failure = TypeError('filter deadline')
    controller.abort(failure)
    async def accessed(signal=None):
        raise AssertionError('invalid or aborted filter listed persistence')
    monkeypatch.setattr(persistence,'list',accessed)
    try:
        with pytest.raises(SessionQueryError) as error:
            await query.filterSessions([dict(kind='created-at',**{'from':None})],controller.signal)
        assert error.value.code == 'SESSION_QUERY_INVALID_FILTER'
        with pytest.raises(TypeError) as error:
            await query.filterSessions([],controller.signal)
        assert error.value is failure
    finally:
        query.close()
        await context.fiber.dispose()
