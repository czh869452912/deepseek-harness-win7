import copy
import json
from pathlib import Path
import pytest
from dsh.core.abort import AbortController
from dsh.session.session_query import SessionQueryService, SessionQueryError
from test_session_live_persistence import backend
from test_prepared_persistence import persisted


@pytest.mark.asyncio
async def test_actual_durable_search_request_captures_query_before_await(backend):
    context,_,persistence = await persisted(backend)
    query = SessionQueryService(context,open_at='first-search')
    message = copy.deepcopy(json.loads((Path(__file__).resolve().parents[1]/
        'scripts/oracles/session_event_trace_fixture.json').read_text(encoding='utf-8'))[1])
    message['seq'] = 2
    message['time'] = 3
    message['data']['content'][0]['text'] = 'needle in durable history'
    try:
        await persistence.append('s',[message])
        request = dict(query='  needle  ',eventFilters=[dict(kind='surface',values=['current'])])
        pending = query.searchSessions(request)
        request['query'] = 'foreign'
        request['eventFilters'][0]['values'][0] = 'shadowed'
        result = await pending
        assert [(item['header'].id,item['bestMatch']['seq'],item['bestMatch']['surface'])
                for item in result['items']] == [('s',2,'current')]
        assert context.get('sessions').get('s') is None
    finally:
        query.close()
        await context.fiber.dispose()


@pytest.mark.asyncio
async def test_actual_durable_invalid_search_precedes_abort_and_index_access(backend,monkeypatch):
    context,_,persistence = await persisted(backend)
    query = SessionQueryService(context,open_at='first-search')
    controller = AbortController()
    controller.abort(TypeError('caller reason'))
    async def accessed(signal=None):
        raise AssertionError('invalid search accessed persistence')
    monkeypatch.setattr(persistence,'list',accessed)
    try:
        for request,code in [
            (dict(query=1),'SESSION_QUERY_INVALID_QUERY'),
            (dict(query='needle',cursor=None),'SESSION_QUERY_INVALID_CURSOR'),
            (dict(query='needle',limit=True),'SESSION_QUERY_INVALID_LIMIT'),
            (dict(query='needle',limit=10 ** 1000),'SESSION_QUERY_INVALID_LIMIT'),
            (dict(query='needle',eventFilters=[dict(kind='text',text='needle')]),'SESSION_QUERY_INVALID_FILTER'),
        ]:
            with pytest.raises(SessionQueryError) as error:
                await query.searchSessions(request,dict(signal=controller.signal))
            assert error.value.code == code
            assert query._conn is None
        with pytest.raises(SessionQueryError) as error:
            await query.searchSessions(dict(query='needle'),dict(signal=controller.signal))
        assert error.value.code == 'SESSION_QUERY_ABORTED'
        assert error.value.message == 'session-search aborted'
        assert query._conn is None
        query.open_at = 'never'
        with pytest.raises(SessionQueryError) as error:
            await query.searchSessions(dict(query=1),dict(signal=controller.signal))
        assert error.value.code == 'SESSION_QUERY_SEARCH_DISABLED'
        assert query._conn is None
    finally:
        query.close()
        await context.fiber.dispose()
