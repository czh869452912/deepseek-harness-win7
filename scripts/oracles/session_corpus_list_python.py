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
from dsh.core.session import Session, SessionHeader
from dsh.core.session.session import SessionPlugin
from dsh.session.session_query import SessionQueryService


async def observe():
    rows = []
    for name in ['no-provider', 'persisted-live', 'tie-order', 'duplicate-durable', 'foreign-header',
        'listing-failure', 'foreign-rejection', 'pre-abort', 'list-abort', 'signal-forwarded', 'post-list-attach', 'clone-detachment']:
        context = Context()
        header = SessionHeader('owned', created_at=9, cwd='/controlled/cwd')
        controller = AbortController()
        failure = 'offline' if name == 'foreign-rejection' else TypeError('controlled listing failure')
        counters = {'lists': 0, 'sameSignal': False}
        observed = {}
        query = SessionQueryService(context, open_at='never')
        try:
            await context.plugin(SessionPlugin)
            headers = [header]
            if name == 'tie-order':
                headers = [SessionHeader(identity, created_at=10 if identity == 'new' else 9, cwd=header.cwd)
                    for identity in ['b', 'a', 'new']]
            if name == 'duplicate-durable':
                headers = [header, SessionHeader(header.id, created_at=10, cwd=header.cwd)]
            if name in ('persisted-live', 'foreign-header', 'clone-detachment'):
                context.get('sessions').enter(Session.create(header.id, [], SessionHeader(header.id,
                    created_at=8 if name == 'foreign-header' else 9, cwd=header.cwd)))
            async def listing(signal=None):
                counters['lists'] += 1
                counters['sameSignal'] = signal is controller.signal
                if name in ('listing-failure', 'foreign-rejection'):
                    if isinstance(failure, BaseException):
                        raise failure
                    raise ThrownValueError(failure)
                if name == 'list-abort':
                    controller.abort(failure)
                if name == 'post-list-attach':
                    context.get('sessions').enter(Session.create(header.id, [], header))
                return headers
            if name != 'no-provider':
                context.set_service('sessionPersistence', SimpleNamespace(list=listing))
            if name == 'pre-abort':
                controller.abort(failure)
            try:
                records = await query.listSessions(controller.signal)
                observed['records'] = [{'id': record['header'].id, 'createdAt': record['header'].createdAt,
                    'cwd': record['header'].cwd, 'live': record['live'], 'persisted': record['persisted']} for record in records]
                if name == 'clone-detachment':
                    records[0]['header'].cwd = '/mutated'
                    observed['originalCwd'] = context.get('sessions').get(header.id).header.cwd
            except Exception as error:
                observed['error'] = {'name': getattr(error, 'name', type(error).__name__),
                    'message': getattr(error, 'message', str(error)), 'code': getattr(error, 'code', None),
                    'sameCause': getattr(error, 'cause', None) is failure, 'sameFailure': error is failure}
            observed['counters'] = counters
            rows.append({'name': name, 'observed': observed})
        finally:
            query.close()
            await context.fiber.dispose()
    return rows



if __name__ == '__main__':
    arguments.output.write_text(json.dumps({'observations': asyncio.run(observe()), 'root': str(ROOT),
        'module': str(Path(dsh.__file__).resolve()), 'python': list(sys.version_info[:3])},
        ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
