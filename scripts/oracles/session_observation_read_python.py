import argparse
import asyncio
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
sys.path.insert(1, str(Path(__file__).resolve().parent))
from dsh.cordis import Context
from dsh.cordis.errors import ThrownValueError
from dsh.core.abort import AbortController
from dsh.core.session import SessionHeader
from dsh.core.session.current_session import CurrentSession as Session
from current_persistence_fixture import SessionPluginV4 as SessionPlugin
from dsh.session.observation_current import CurrentSessionObservationReader as SessionObservationReader
from dsh.session.persistence import SessionPersistenceCorruptionError, SessionPersistenceNotFoundError
from current_persistence_fixture import ProjectionPluginV4 as SessionProjectionsPlugin


async def observe():
    rows = []
    names = ['missing-provider', 'missing-record', 'corrupt-record', 'persistence-failure', 'foreign-rejection',
        'wrong-source', 'pre-abort', 'stat-abort', 'projection-failure', 'live-projection-failure',
        'prepared-leases', 'live-leases', 'published-live', 'stable-cold-read', 'projection-none', 'prepared-projection']
    for name in names:
        context = Context()
        header = SessionHeader('owned', version=4, created_at=9, cwd='/controlled/cwd')
        events = [{'type': 'controlled/event', 'seq': 0, 'time': 0, 'data': {}, 'ignorable': True}]
        controller = AbortController()
        failure = TypeError('controlled read failure')
        if name == 'missing-record':
            failure = SessionPersistenceNotFoundError('owned')
        if name == 'corrupt-record':
            failure = SessionPersistenceCorruptionError('controlled corrupt record')
        if name == 'foreign-rejection':
            failure = 'offline'
        counters = {'stats': 0, 'opens': 0, 'closes': 0, 'applied': 0}
        observed = {}
        try:
            await context.plugin(SessionPlugin)
            await context.plugin(SessionProjectionsPlugin)
            broken = name in ('projection-failure', 'live-projection-failure', 'projection-none')
            def initialize(meta, inherited_event_count):
                if broken:
                    raise failure
                return 0
            def apply(state, event):
                counters['applied'] += 1
                return state + 1
            await context.get('sessionProjections').register({'key': 'controlled/count', 'stateVersion': 1,
                'stateSchema': lambda value: value, 'init': initialize, 'apply': apply,
                'wire': {'viewSchema': lambda value: value, 'view': lambda state: state}})
            meta = SessionHeader('foreign', version=4, created_at=9, cwd=header.cwd) if name == 'wrong-source' else header
            prepared_session = Session.create(meta.id, events, meta, format_version=4)
            if name == 'live-leases':
                context.get('sessions').enter(prepared_session)
            async def stat(session_id, options=None):
                counters['stats'] += 1
                if name in ('missing-record', 'persistence-failure', 'foreign-rejection'):
                    if name == 'foreign-rejection':
                        raise ThrownValueError(failure)
                    raise failure
                if name == 'stat-abort':
                    controller.abort(failure)
                if name in ('published-live', 'live-projection-failure'):
                    context.get('sessions').enter(Session.create(header.id, [], header, format_version=4))
                return dict(header=meta, revision='controlled:0')
            async def opened(session_id, mode, options=None):
                assert mode == 'read'
                counters['opens'] += 1
                closed = [False]
                async def read(start=0, options=None):
                    if name == 'corrupt-record':
                        raise failure
                    return dict(events=prepared_session.snapshotEvents()[start:], eventState='detached')
                async def close():
                    if not closed[0]:
                        counters['closes'] += 1
                    closed[0] = True
                return SimpleNamespace(header=meta, inheritedEventCount=0, read=read, close=close)
            if name != 'missing-provider':
                context.set_service('sessionPersistence', SimpleNamespace(stat=stat, open=opened))
            if name == 'pre-abort':
                controller.abort(failure)
            try:
                lease = await SessionObservationReader(context).read(header.id, {'signal': controller.signal,
                    'projectionMode': 'none' if name in ('prepared-leases', 'live-leases', 'published-live',
                        'stable-cold-read', 'projection-none') else 'all'})
                observed['cut'] = {'source': lease.source, 'id': lease.header.id, 'cursor': lease.cursor,
                    'length': len(lease.events), 'revision': getattr(lease, 'revision', None), 'projections': lease.projections}
                if name.endswith('leases'):
                    retained = lease.retain()
                    lease.dispose()
                    lease.dispose()
                    observed['closesAfterFirst'] = counters['closes']
                    try:
                        lease.retain()
                    except Exception as error:
                        observed['retainFailure'] = {'message': str(error), 'ordinaryError': type(error) is ValueError}
                    observed['retained'] = {'source': retained.source, 'cursor': retained.cursor, 'length': len(retained.events)}
                    retained.dispose()
                    retained.dispose()
                else:
                    lease.dispose()
            except Exception as error:
                observed['error'] = {'name': getattr(error, 'name', type(error).__name__),
                    'message': getattr(error, 'message', str(error)), 'code': getattr(error, 'code', None),
                    'sameCause': getattr(error, 'cause', None) is failure, 'sameFailure': error is failure}
            observed['counters'] = counters
            rows.append({'name': name, 'observed': observed})
        finally:
            await context.fiber.dispose()
    return rows


if __name__ == '__main__':
    arguments.output.write_text(json.dumps({'observations': asyncio.run(observe()), 'root': str(ROOT),
        'module': str(Path(dsh.__file__).resolve()), 'python': list(sys.version_info[:3])},
        ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
