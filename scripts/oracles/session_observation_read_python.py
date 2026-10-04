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
from dsh.cordis import Context
from dsh.cordis.errors import ThrownValueError
from dsh.core.abort import AbortController
from dsh.core.session import SessionHeader
from dsh.core.session.session import Session, SessionPlugin
from dsh.session.observation import SessionObservationReader
from dsh.session.persistence import SessionPersistenceCorruptionError
from dsh.session.projections import SessionProjectionsPlugin


class SessionPersistenceNotFoundError(FileNotFoundError):
    pass


async def observe():
    rows = []
    names = ['missing-provider', 'missing-record', 'corrupt-record', 'persistence-failure', 'foreign-rejection',
        'wrong-source', 'pre-abort', 'borrow-abort', 'projection-failure', 'live-projection-failure',
        'prepared-leases', 'live-leases', 'published-live', 'detached-live-retry', 'projection-none', 'prepared-projection']
    for name in names:
        context = Context()
        header = SessionHeader('owned', created_at=9, cwd='/controlled/cwd')
        events = [{'type': 'controlled/event', 'seq': 0, 'time': 0, 'data': {}}]
        controller = AbortController()
        failure = TypeError('controlled read failure')
        if name == 'missing-record':
            failure = SessionPersistenceNotFoundError('session "owned" not found')
        if name == 'corrupt-record':
            failure = SessionPersistenceCorruptionError('controlled corrupt record')
        if name == 'foreign-rejection':
            failure = 'offline'
        counters = {'borrows': 0, 'releases': 0, 'applied': 0}
        observed = {}
        try:
            await context.plugin(SessionPlugin)
            await context.plugin(SessionProjectionsPlugin)
            broken = name in ('projection-failure', 'live-projection-failure', 'projection-none')
            def initialize(meta):
                if broken:
                    raise failure
                return 0
            def apply(state, event):
                counters['applied'] += 1
                return state + 1
            context.get('sessionProjections').register({'key': 'controlled/count', 'stateVersion': 1,
                'stateSchema': lambda value: value, 'init': initialize, 'apply': apply,
                'wire': {'viewSchema': lambda value: value, 'view': lambda state: state}})
            meta = SessionHeader('foreign', created_at=9, cwd=header.cwd) if name == 'wrong-source' else header
            prepared_session = Session.create(meta.id, events, meta)
            if name == 'live-leases':
                context.get('sessions').enter(prepared_session)
            def release():
                counters['releases'] += 1
            async def borrow(session_id, signal=None):
                counters['borrows'] += 1
                if name in ('missing-record', 'corrupt-record', 'persistence-failure', 'foreign-rejection'):
                    if name == 'foreign-rejection':
                        raise ThrownValueError(failure)
                    raise failure
                if name == 'borrow-abort':
                    controller.abort(failure)
                if name in ('published-live', 'live-projection-failure'):
                    context.get('sessions').enter(Session.create(header.id, [], header))
                return SimpleNamespace(source='live' if name == 'detached-live-retry' and counters['borrows'] == 1 else 'prepared',
                    inspection=SimpleNamespace(meta=prepared_session.header, events=prepared_session.events),
                    revision='controlled:0', preparedSession=prepared_session, dispose=release)
            if name != 'missing-provider':
                context.set_service('sessionPersistence', SimpleNamespace(borrowSession=borrow))
            if name == 'pre-abort':
                controller.abort(failure)
            try:
                lease = await SessionObservationReader(context).read(header.id, {'signal': controller.signal,
                    'projectionMode': 'none' if name in ('prepared-leases', 'live-leases', 'published-live',
                        'detached-live-retry', 'projection-none') else 'all'})
                observed['cut'] = {'source': lease.source, 'id': lease.header.id, 'cursor': lease.cursor,
                    'length': len(lease.events), 'revision': lease.revision, 'projections': lease.projections}
                if name.endswith('leases'):
                    retained = lease.retain()
                    lease.dispose()
                    lease.dispose()
                    observed['releasesAfterFirst'] = counters['releases']
                    try:
                        lease.retain()
                    except Exception as error:
                        observed['retainFailure'] = {'message': str(error), 'ordinaryError': type(error) is RuntimeError}
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
