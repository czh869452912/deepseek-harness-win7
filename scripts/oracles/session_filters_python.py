import argparse
import asyncio
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
arguments = None
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--root', type=Path, default=ROOT)
    arguments = parser.parse_args()
    ROOT = arguments.root.resolve()
sys.path.insert(0, str(ROOT))
import dsh
from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.core.session import Session, SessionHeader
from dsh.core.session.session import SessionPlugin
from dsh.session.session_query import SessionQueryService, compile_session_text_filter, materialize_session_result_filters
from dsh.session.session_query import materialize_session_event_result_filters, filter_session_event_documents, build_session_event_search_documents


async def observe():
    directory = Path(__file__).parent
    cases = json.loads((directory/'session_filters_cases.json').read_text(encoding='utf-8'))
    events = json.loads((directory/'session_event_trace_fixture.json').read_text(encoding='utf-8'))
    rows = []
    for item in cases:
        filters = copy.deepcopy(item.get('filters'))
        if item['name'] == 'sessions-nan-range':
            filters[0]['from'] = float('nan')
        if item['name'] == 'sessions-infinite-range':
            filters[0]['to'] = float('inf')
        failure = TypeError('controlled filter listing failure')
        observed = {}
        context = None
        query = None
        try:
            if item['mode'].endswith('-materialize'):
                owned = (materialize_session_result_filters(filters) if item['mode'] == 'sessions-materialize'
                         else materialize_session_event_result_filters(filters))
                if item['name'] == 'sessions-detached-values':
                    filters[0]['values'][0] = 'foreign'
                observed['filters'] = owned
            elif item['mode'] == 'text':
                pattern = compile_session_text_filter(item['text'])
                observed['matches'] = [pattern.search(document) is not None for document in item['documents']]
            elif item['mode'] == 'events-filter':
                observed['documents'] = filter_session_event_documents([],filters)
            elif item['mode'] == 'documents':
                observed['documents'] = build_session_event_search_documents('owned',events)
            else:
                context = Context()
                await context.plugin(SessionPlugin)
                live = SessionHeader('live',created_at=2,cwd='/workspace')
                cold = SessionHeader('cold',created_at=1)
                context.get('sessions').enter(Session.create(live.id,events,live))
                controller = AbortController()
                counters = dict(lists=0,inspections=0,sameSignal=True)
                observed['counters'] = counters
                async def listing(signal=None):
                    counters['lists'] += 1
                    expected = controller.signal if item['mode'] == 'public-sessions' else None
                    counters['sameSignal'] = counters['sameSignal'] and signal is expected
                    if item['name'] == 'public-sessions-failure':
                        raise failure
                    return [cold]
                async def inspection(identity,signal=None):
                    counters['inspections'] += 1
                    return dict(meta=cold,events=events)
                context.set_service('sessionPersistence',SimpleNamespace(list=listing,inspect=inspection))
                query = SessionQueryService(context,open_at='never')
                if item['name'] in ('public-sessions-pre-abort','public-sessions-invalid-before-abort'):
                    controller.abort(failure)
                if item['mode'] == 'public-sessions':
                    pending = query.filterSessions(filters,controller.signal)
                    if item['name'] == 'public-sessions-before-await':
                        filters[0]['values'][0] = 'foreign'
                    observed['records'] = [dict(id=record['header'].id,live=record['live'],persisted=record['persisted'])
                                           for record in await pending]
                else:
                    pending = query.filterEvents(cold.id if item['name'] == 'public-events-cold' else live.id,filters)
                    if item['name'] == 'public-events-before-await':
                        filters[0]['values'][0] = 'turn/start'
                    observed['documents'] = await pending
        except Exception as error:
            observed['error'] = dict(name=getattr(error,'name',type(error).__name__),
                message=getattr(error,'message',str(error)),code=getattr(error,'code',None),
                sameCause=getattr(error,'cause',None) is failure,sameFailure=error is failure)
        finally:
            if query is not None:
                query.close()
            if context is not None:
                await context.fiber.dispose()
        rows.append(dict(name=item['name'],observed=observed))
    return rows


if __name__ == '__main__':
    arguments.output.write_text(json.dumps(dict(observations=asyncio.run(observe()),root=str(ROOT),
        module=str(Path(dsh.__file__).resolve()),python=list(sys.version_info[:3])),
        ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
