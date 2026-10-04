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
from dsh.core.session import Session, SessionHeader, SessionPlugin
from dsh.session.corpus import SessionCorpus
from dsh.session.session_query import SessionQueryService
from dsh.session.title import fold_session_title


async def observe():
    rows = []
    names = ['load-live', 'load-cold', 'load-missing-provider', 'load-missing-record', 'load-corrupt', 'load-failure',
        'load-foreign-failure', 'load-header-conflict', 'load-attach-wins', 'batch-live-only', 'batch-mixed-duplicates',
        'batch-list-failure', 'batch-foreign-failure', 'batch-inspect-isolated', 'batch-list-attach', 'batch-clone',
        'batch-concurrency', 'batch-abort-drain', 'pre-abort']
    for name in names:
        ctx = Context()
        def header(identity, created_at=9):
            return SessionHeader(identity, created_at=created_at, cwd='/controlled/cwd')
        def title(identity):
            return {'type': 'session/title', 'seq': 0, 'time': 3,
                'data': {'title': 'Title ' + identity, 'messageSeqs': [], 'source': {'kind': 'user'}}}
        controller = AbortController()
        failure = 'offline' if 'foreign-failure' in name else TypeError('controlled corpus failure')
        if name == 'load-corrupt':
            failure.name = 'SessionPersistenceCorruptionError'
        counters = {'lists': 0, 'inspections': [], 'signals': True, 'inFlight': 0, 'peak': 0, 'settled': 0}
        timeline, releases = [], {}
        auto_release = False
        inspected = None
        observed = {}
        ids = ['a', 'b', 'c', 'd', 'e'] if name in ('batch-concurrency', 'batch-abort-drain') else ['a', 'b']
        listed = [header(identity) for identity in ids]
        if name == 'load-missing-record':
            listed = []
        def live(identity):
            ctx.get('sessions').enter(Session.create(identity, [title(identity)], header(identity)))
        def normalize_error(error):
            return {'name': getattr(error, 'name', type(error).__name__),
                'message': getattr(error, 'message', str(error)), 'code': getattr(error, 'code', None),
                'sameCause': getattr(error, 'cause', None) is failure, 'sameFailure': error is failure}
        query = SessionQueryService(ctx, open_at='never', persisted_inspect_concurrency=2)
        try:
            await ctx.plugin(SessionPlugin)
            if name in ('load-live', 'batch-live-only', 'batch-mixed-duplicates', 'batch-list-failure', 'batch-foreign-failure', 'batch-clone'):
                live('a')
            if name == 'batch-live-only':
                live('b')
            async def listing(signal=None):
                nonlocal listed
                counters['lists'] += 1
                counters['signals'] = counters['signals'] and signal is controller.signal
                if name in ('batch-list-failure', 'batch-foreign-failure'):
                    if isinstance(failure, BaseException):
                        raise failure
                    raise ThrownValueError(failure)
                if name == 'batch-list-attach':
                    live('b')
                    listed = [header('a')]
                return listed
            async def inspect(identity, signal=None):
                nonlocal inspected
                counters['inspections'].append(identity)
                counters['signals'] = counters['signals'] and signal is controller.signal
                counters['inFlight'] += 1
                counters['peak'] = max(counters['peak'], counters['inFlight'])
                timeline.append('inspect:' + identity)
                try:
                    if name in ('load-corrupt', 'load-failure', 'load-foreign-failure') or (
                            name == 'batch-inspect-isolated' and identity == 'b'):
                        if isinstance(failure, BaseException):
                            raise failure
                        raise ThrownValueError(failure)
                    if name == 'load-attach-wins':
                        live(identity)
                    if name in ('batch-concurrency', 'batch-abort-drain') and not auto_release:
                        gate = asyncio.Event()
                        releases[identity] = gate.set
                        await gate.wait()
                    if name == 'batch-abort-drain':
                        raise failure
                    event = title(identity)
                    if name == 'batch-concurrency':
                        class ProjectedData(dict):
                            def get(self, key, default=None):
                                if key == 'messageSeqs':
                                    timeline.append('project:' + identity)
                                return super().get(key, default)
                        event['data'] = ProjectedData(event['data'])
                    inspected = SimpleNamespace(meta=header(identity, 8 if name == 'load-header-conflict' else 9), events=[event])
                    return inspected
                finally:
                    counters['inFlight'] -= 1
                    counters['settled'] += 1
            if name != 'load-missing-provider':
                ctx.set_service('sessionPersistence', SimpleNamespace(list=listing, inspect=inspect))
            corpus = SessionCorpus(ctx, 2)
            if name == 'pre-abort':
                controller.abort(failure)
            try:
                if name.startswith('load-'):
                    loaded = await corpus.load('a', controller.signal)
                    observed['loaded'] = {'id': loaded['header'].id, 'createdAt': loaded['header'].createdAt,
                        'cwd': loaded['header'].cwd, 'eventTypes': [event['type'] for event in loaded['events']],
                        'title': fold_session_title(loaded['events'])}
                    loaded['header'].cwd = '/mutated'
                    loaded['events'][0]['data']['title'] = 'mutated'
                    known = ctx.get('sessions').get('a')
                    owner_header = known.header if known is not None else inspected.meta
                    owner_events = known.events if known is not None else inspected.events
                    observed['detached'] = owner_header.cwd == '/controlled/cwd' and owner_events[0]['data']['title'] == 'Title a'
                else:
                    selected = ['a', 'b', 'a', 'missing', 'b'] if name == 'batch-mixed-duplicates' else ids
                    pending = asyncio.create_task(query.readTitleSnapshots(selected, controller.signal))
                    if name in ('batch-concurrency', 'batch-abort-drain'):
                        while len(releases) < 2:
                            await asyncio.sleep(0.001)
                        if name == 'batch-abort-drain':
                            controller.abort(failure)
                            await asyncio.sleep(0.005)
                            observed['settledBeforeDrain'] = pending.done()
                            for release in releases.values():
                                release()
                        else:
                            releases['a']()
                            while 'c' not in counters['inspections']:
                                await asyncio.sleep(0.001)
                            auto_release = True
                            for release in releases.values():
                                release()
                    results = await pending
                    observed['results'] = [{'id': result['sessionId'], 'status': result['status'],
                        'value': {'id': result['value']['session'].id, 'cwd': result['value']['session'].cwd,
                            'title': result['value'].get('title')}} if result['status'] == 'fulfilled' else
                        {'id': result['sessionId'], 'status': result['status'], 'error': normalize_error(result['reason'])}
                        for result in results]
                    if name == 'batch-clone':
                        value = results[0]['value']
                        value['session'].cwd = '/mutated'
                        try:
                            value['title']['source']['kind'] = 'foreign'
                        except TypeError:
                            observed['titleMutationRefused'] = True
                        known = ctx.get('sessions').get('a')
                        observed['detached'] = known.header.cwd == '/controlled/cwd' and known.events[0]['data']['source']['kind'] == 'user'
                    if name == 'batch-concurrency':
                        observed['projectBeforeNext'] = timeline.index('project:a') < timeline.index('inspect:c')
            except Exception as error:
                observed['error'] = normalize_error(error)
            observed['counters'] = counters
            rows.append({'name': name, 'observed': observed})
        finally:
            for release in releases.values():
                release()
            query.close()
            await ctx.fiber.dispose()
    return rows



if __name__ == '__main__':
    arguments.output.write_text(json.dumps({'observations': asyncio.run(observe()), 'root': str(ROOT),
        'module': str(Path(dsh.__file__).resolve()), 'python': list(sys.version_info[:3])},
        ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
