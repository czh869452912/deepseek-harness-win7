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
from dsh.cordis.errors import ThrownValueError
from dsh.core.abort import AbortController
from dsh.core.session import Session, SessionHeader
from dsh.core.session.session import SessionPlugin
from dsh.session.session_query import SessionQueryService


async def observe():
    fixture = json.loads((Path(__file__).parent / 'session_event_trace_fixture.json').read_text(encoding='utf-8'))
    rows = []
    names = ["trace-original","trace-replacement","trace-log-only","trace-current","trace-detachment","surface-live","surface-cold","surface-empty","surface-invalid","list-records","list-invalid","trace-missing-before-invalid","trace-invalid-surface","trace-duplicate-sources","trace-non-surface-source","window-target","window-default","window-clamped","window-alias","window-invalid-before","window-invalid-after","window-invalid-limit","window-before-abort","trace-pre-abort","trace-list-failure","trace-inspect-failure","trace-foreign-failure","trace-header-conflict","trace-attach-wins","read-session-adoption"]
    for name in names:
        context = Context()
        controller = AbortController()
        failure = 'offline' if name == 'trace-foreign-failure' else TypeError('controlled event failure')
        counters = dict(lists=0, inspections=0, sameSignal=True)
        meta = SessionHeader('owned', created_at=9, cwd='/controlled/cwd')
        events = copy.deepcopy(fixture)
        if name == 'surface-empty':
            events = []
        if name in ('surface-invalid','list-invalid','trace-missing-before-invalid','trace-invalid-surface'):
            events[2]['surfaceOp']['start'] = 99
        if name == 'trace-duplicate-sources':
            events[3]['sourceEventSeqs'] = [0,0]
        if name == 'trace-non-surface-source':
            events[0]['sourceEventSeqs'] = [0]
        def normalize_event(event):
            content = event['data'].get('content', [])
            return dict(seq=event['seq'], type=event['type'], time=event['time'],
                        text=content[0]['text'] if content else None)
        observed = {}
        query = SessionQueryService(context, open_at='never', read_window_max=2 if name == 'window-invalid-limit' else 50)
        try:
            await context.plugin(SessionPlugin)
            live = name in ('trace-original','trace-replacement','trace-log-only','trace-current','trace-detachment',
                'surface-live','list-records','window-target','window-default','window-clamped','window-alias',
                'read-session-adoption')
            if live:
                context.get('sessions').enter(Session.create(meta.id, events, meta))
            else:
                async def listing(signal=None):
                    counters['lists'] += 1
                    expected = controller.signal if name in ('trace-pre-abort','window-before-abort','trace-list-failure',
                        'trace-inspect-failure','trace-foreign-failure','trace-header-conflict','trace-attach-wins') else None
                    counters['sameSignal'] = counters['sameSignal'] and signal is expected
                    if name == 'trace-list-failure':
                        raise failure
                    return [meta]
                async def inspection(identity, signal=None):
                    counters['inspections'] += 1
                    expected = controller.signal if name in ('trace-inspect-failure','trace-foreign-failure',
                        'trace-header-conflict','trace-attach-wins') else None
                    counters['sameSignal'] = counters['sameSignal'] and signal is expected
                    if name in ('trace-inspect-failure','trace-foreign-failure'):
                        if isinstance(failure, BaseException):
                            raise failure
                        raise ThrownValueError(failure)
                    if name == 'trace-attach-wins':
                        context.get('sessions').enter(Session.create(meta.id, events, meta))
                    return dict(meta=SessionHeader(meta.id, created_at=9,
                        cwd='/foreign' if name == 'trace-header-conflict' else meta.cwd), events=events)
                context.set_service('sessionPersistence', SimpleNamespace(list=listing, inspect=inspection))
            if name in ('trace-pre-abort','window-before-abort'):
                controller.abort(failure)
            try:
                if name.startswith('surface-'):
                    value = await query.readSurface(meta.id)
                    observed['surface'] = dict(id=value['session'].id, capturedThroughSeq=value['capturedThroughSeq'],
                                               events=[normalize_event(event) for event in value['events']])
                    if value['events']:
                        try:
                            value['events'][0]['data']['content'][0]['text'] = 'foreign'
                        except TypeError:
                            observed['messageMutationRefused'] = True
                elif name.startswith('list-'):
                    observed['records'] = await query.listEvents(meta.id)
                elif name.startswith('window-'):
                    request = dict(sessionId=meta.id, seq=2)
                    if name in ('window-target','window-alias'):
                        request.update(before=1,after=1)
                    if name == 'window-clamped':
                        request.update(seq=0,before=50,after=50)
                    if name in ('window-invalid-before','window-before-abort'):
                        request['before'] = -1
                    if name == 'window-invalid-after':
                        request['after'] = True
                    if name == 'window-invalid-limit':
                        request['after'] = 3
                    value = await query.readEvent(request, controller.signal if name == 'window-before-abort' else None)
                    observed['window'] = dict(id=value['session'].id, target=normalize_event(value['target']),
                        events=[normalize_event(event) for event in value['events']],
                        startSeq=value['startSeq'], endSeq=value['endSeq'])
                    observed['targetAlias'] = value['events'][request['seq']-value['startSeq']] is value['target']
                    if name == 'window-alias':
                        try:
                            value['target']['data']['content'][0]['text'] = 'foreign'
                        except TypeError:
                            observed['messageMutationRefused'] = True
                        value['target']['time'] = 99
                        observed['aliasTime'] = value['events'][request['seq']-value['startSeq']]['time']
                        observed['sourceTime'] = context.get('sessions').get(meta.id).events[request['seq']]['time']
                elif name == 'read-session-adoption':
                    value = await query.readSession(meta.id)
                    try:
                        value['events'][1]['data']['content'][0]['text'] = 'foreign'
                    except TypeError:
                        observed['messageMutationRefused'] = True
                    value['events'][1]['time'] = 99
                    observed['sourceTime'] = context.get('sessions').get(meta.id).events[1]['time']
                    observed['log'] = [normalize_event(event) for event in value['events']]
                else:
                    seq = 2 if name in ('trace-replacement','trace-detachment') else (
                        0 if name in ('trace-log-only','trace-invalid-surface') else 4 if name == 'trace-current'
                        else 99 if name == 'trace-missing-before-invalid' else 1)
                    signal = controller.signal if name in ('trace-pre-abort','trace-list-failure','trace-inspect-failure',
                        'trace-foreign-failure','trace-header-conflict','trace-attach-wins') else None
                    value = await query.traceEvent(dict(sessionId=meta.id, seq=seq), signal)
                    observed['trace'] = dict(id=value['session'].id, **{key:item for key,item in value.items() if key != 'session'})
                    if name == 'trace-detachment':
                        value['target']['time'] = 99
                        for key in ('replacementChain','replacedEventSeqs','sourceEventSeqs','derivedEventSeqs'):
                            value[key].append(99)
                        repeated = await query.traceEvent(dict(sessionId=meta.id, seq=seq))
                        observed['repeated'] = dict(id=repeated['session'].id,
                            **{key:item for key,item in repeated.items() if key != 'session'})
            except Exception as error:
                cause = getattr(error, 'cause', None)
                observed['error'] = dict(name=getattr(error, 'name', type(error).__name__),
                    message=getattr(error, 'message', str(error)), code=getattr(error, 'code', None),
                    sameCause=cause is failure, sameFailure=error is failure,
                    causeMessage=str(cause) if isinstance(cause, BaseException) else None)
            observed['counters'] = counters
            rows.append(dict(name=name, observed=observed))
        finally:
            query.close()
            await context.fiber.dispose()
    return rows


if __name__ == '__main__':
    arguments.output.write_text(json.dumps(dict(observations=asyncio.run(observe()), root=str(ROOT),
        module=str(Path(dsh.__file__).resolve()), python=list(sys.version_info[:3])),
        ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
