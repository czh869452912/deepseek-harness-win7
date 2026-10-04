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
    names = ['root', 'complete', 'partial', 'cycle', 'self-cycle', 'missing', 'deep', 'unrelated-cycle',
        'persisted', 'listing-failure', 'foreign-rejection', 'pre-abort', 'list-abort', 'clone-detachment']
    for name in names:
        context = Context()
        controller = AbortController()
        failure = 'offline' if name == 'foreign-rejection' else TypeError('controlled lineage failure')
        counters = dict(lists=0, inspections=0, sameSignal=False)
        def header(identity, created_at=1, parent=None):
            return SessionHeader(identity, created_at=created_at, parent_session=parent)
        headers = [header('target')]
        if name in ('complete', 'clone-detachment'):
            headers = [header('root', 0), header('parent', 1, 'root'), header('target', 2, 'parent'),
                header('b', 4, 'target'), header('a', 4, 'target'), header('older', 3, 'target'),
                header('grandchild', 5, 'a')]
        if name == 'partial':
            headers = [header('target', 1, 'outside')]
        if name == 'cycle':
            headers = [header('target', 1, 'parent'), header('parent', 2, 'target')]
        if name == 'self-cycle':
            headers = [header('target', 1, 'target')]
        if name == 'unrelated-cycle':
            headers.extend([header('x', 2, 'y'), header('y', 3, 'x')])
        if name == 'deep':
            headers = [header('target', 0)] + [header('deep-' + str(index + 1), index + 1,
                'target' if index == 0 else 'deep-' + str(index)) for index in range(3500)]
        def record(value):
            meta = value['header']
            return dict(id=meta.id, createdAt=meta.createdAt, parent=meta.parentSession,
                        live=value['live'], persisted=value['persisted'])
        def normalize(trace):
            descendants = []
            pending = [(node, 1) for node in reversed(trace['descendants'])]
            while pending:
                node, depth = pending.pop()
                descendants.append(dict(record(node['session']), depth=depth))
                pending.extend((child, depth + 1) for child in reversed(node['descendants']))
            return dict(keys=sorted(trace), target=record(trace['target']),
                ancestors=[record(value) for value in trace['ancestors']], complete=trace['complete'],
                root=record(trace['root']) if 'root' in trace else None,
                unresolvedParentId=trace.get('unresolvedParentId'),
                descendants=dict(count=len(descendants), first=descendants[0], last=descendants[-1])
                    if name == 'deep' else descendants)
        observed = {}
        query = SessionQueryService(context, open_at='never')
        try:
            await context.plugin(SessionPlugin)
            if name not in ('persisted', 'listing-failure', 'foreign-rejection', 'pre-abort', 'list-abort'):
                for meta in headers:
                    context.get('sessions').enter(Session.create(meta.id, [], meta))
            async def listing(signal=None):
                counters['lists'] += 1
                counters['sameSignal'] = signal is controller.signal
                if name in ('listing-failure', 'foreign-rejection'):
                    if isinstance(failure, BaseException):
                        raise failure
                    raise ThrownValueError(failure)
                if name == 'list-abort':
                    controller.abort(failure)
                return headers
            async def inspection(identity, signal=None):
                counters['inspections'] += 1
                raise AssertionError('unexpected inspection')
            if name in ('persisted', 'listing-failure', 'foreign-rejection', 'pre-abort', 'list-abort'):
                context.set_service('sessionPersistence', SimpleNamespace(list=listing, inspect=inspection))
            if name == 'pre-abort':
                controller.abort(failure)
            try:
                trace = await query.traceSession('absent' if name == 'missing' else 'target', controller.signal)
                observed['trace'] = normalize(trace)
                if name == 'clone-detachment':
                    trace['target']['header'].created_at = 99
                    trace['ancestors'][0]['header'].created_at = 99
                    trace['root']['header'].created_at = 99
                    trace['descendants'][0]['session']['header'].created_at = 99
                    observed['repeated'] = normalize(await query.traceSession('target', controller.signal))
                    observed['sourceUnchanged'] = context.get('sessions').get('target').header.createdAt == 2
            except Exception as error:
                observed['error'] = dict(name=getattr(error, 'name', type(error).__name__),
                    message=getattr(error, 'message', str(error)), code=getattr(error, 'code', None),
                    sameCause=getattr(error, 'cause', None) is failure, sameFailure=error is failure)
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
