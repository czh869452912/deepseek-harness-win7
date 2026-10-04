import copy
import json
from pathlib import Path
import pytest

from dsh.session.session_query import SessionQueryService, SessionQueryError
from test_session_live_persistence import backend
from test_prepared_persistence import persisted


@pytest.mark.asyncio
async def test_actual_durable_surface_event_trace_and_window_stay_cold_and_detached(backend):
    context, _, persistence = await persisted(backend)
    query = SessionQueryService(context, open_at='never')
    fixture = json.loads((Path(__file__).resolve().parents[1] /
        'scripts/oracles/session_event_trace_fixture.json').read_text(encoding='utf-8'))
    shifted = copy.deepcopy(fixture[1:5])
    for event in shifted:
        event['seq'] += 1
        if isinstance(event.get('surfaceOp'), dict):
            event['surfaceOp']['start'] += 1
            event['surfaceOp']['end'] += 1
        if 'sourceEventSeqs' in event:
            event['sourceEventSeqs'] = [seq + 1 for seq in event['sourceEventSeqs']]
    try:
        await persistence.append('s', shifted)
        trace = await query.traceEvent(dict(sessionId='s', seq=2))
        assert trace['replacementChain'] == [3,5]
        assert trace['derivedEventSeqs'] == [3]
        assert trace['target']['surface'] == 'shadowed'
        surface = await query.readSurface('s')
        assert [event['seq'] for event in surface['events']] == [5,4]
        with pytest.raises(TypeError):
            surface['events'][1]['data']['content'][0]['text'] = 'foreign'
        window = await query.readEvent(dict(sessionId='s', seq=3, before=1, after=1))
        assert window['target'] is window['events'][1]
        with pytest.raises(TypeError):
            window['target']['data']['content'][0]['text'] = 'foreign'
        window['target']['time'] = 99
        assert (await query.readEvent(dict(sessionId='s', seq=3)))['target']['time'] != 99
        log = await query.readSession('s')
        with pytest.raises(TypeError):
            log['events'][2]['data']['content'][0]['text'] = 'foreign'
        assert context.get('sessions').get('s') is None
        fresh = backend[2]()
        try:
            stored = await fresh.read_from('s', 0)
            assert stored.events[2]['surfaceOp'] == 'append'
            assert stored.events[3]['surfaceOp'] == dict(op='replace',start=2,end=2)
            assert stored.events[5]['surfaceOp'] == dict(op='replace',start=3,end=3)
        finally:
            if hasattr(fresh, 'close'):
                fresh.close()
    finally:
        query.close()
        await context.fiber.dispose()


@pytest.mark.parametrize('name,value', [('before',-1),('after',True),('before',None),
    ('before',1.5),('after',51),('after',float('nan')),('before',float('inf'))])
@pytest.mark.asyncio
async def test_invalid_window_precedes_missing_source_and_does_not_access_backend(name,value):
    query = SessionQueryService(None, open_at='never')
    try:
        with pytest.raises(SessionQueryError) as error:
            await query.readEvent(dict(sessionId='missing',seq=0,**{name:value}))
        assert error.value.code == 'SESSION_QUERY_INVALID_WINDOW'
        assert error.value.message == name + ' must be an integer between 0 and 50'
    finally:
        query.close()


@pytest.mark.parametrize('value', [-1,True,1.5,float('inf'),float('nan'),'2'])
def test_event_read_configuration_rejects_non_integer_window(value):
    with pytest.raises(SessionQueryError) as error:
        SessionQueryService(None,open_at='never',read_window_max=value)
    assert error.value.code == 'SESSION_QUERY_INVALID_CONFIG'


@pytest.mark.parametrize('value',[0,1.0,50])
def test_event_read_configuration_accepts_non_negative_integer_window(value):
    query = SessionQueryService(None,open_at='never',read_window_max=value)
    try:
        assert query._read_window_max == int(value)
    finally:
        query.close()
