"""Compare actual Connection-authenticated deliverables routes with rc.3."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    rows = [dict(name='summary', path='/api/changes.summary'), dict(name='diff', path='/api/changes.diff'),
            dict(name='binary', path='/api/changes.diff', kind='binary'), dict(name='oversized', path='/api/changes.diff', kind='oversized'),
            dict(name='open', path='/api/changes.open', method='POST'), dict(name='applications', path='/api/changes.open'),
            dict(name='reveal', path='/api/changes.open', method='POST', suffix='&action=reveal&application=ignored'),
            dict(name='application', path='/api/changes.open', method='POST', suffix='&application=custom.app'),
            dict(name='empty-application', path='/api/changes.open', method='POST', suffix='&application='),
            dict(name='present-open', path='/api/present.open', method='POST'), dict(name='present-applications', path='/api/present.open'),
            dict(name='present-application', path='/api/present.open', method='POST', suffix='&application=custom.app'),
            dict(name='host', path='/api/present.host')]
    for route in ['summary', 'diff', 'open']:
        for name, options in [('no-session', dict(query='?seq=7&index=0')), ('bad-seq', dict(query='?sessionId=s&seq=1e2&index=0')),
                ('large-seq', dict(query='?sessionId=s&seq=9007199254740992&index=0')),
                ('newline', dict(query='?sessionId=s&seq=7%0A&index=0')), ('missing', dict(missing=True)),
                ('zeros', dict(query='?sessionId=s&seq=0000000000000007&index=0000'))]:
            rows.append(dict(name=route+'-'+name, path='/api/changes.'+route, **options))
    for route in ['diff', 'open', 'present.open']:
        for name, options in [('missing-file', dict(index=9)), ('missing-remote', dict(failure='diff' if route == 'diff' else 'stat', remoteCode='workspace-file/not-found')),
                ('unexpected', dict(failure='diff' if route == 'diff' else 'stat')), ('aborted', dict(aborted=True))]:
            rows.append(dict(name=route+'-'+name, path='/api/'+('changes.'+route if route != 'present.open' else route), **options))
    for name, options in [('unavailable', dict(unavailable=True)), ('unmapped', dict(unmapped=True)),
            ('wrong-mapping', dict(wrongMapping=True)), ('open-failure', dict(method='POST', failure='open')),
            ('applications-failure', dict(failure='applications')), ('bad-action', dict(suffix='&action=delete')),
            ('abort-stat', dict(abortDuring=True)), ('pending-disposal', dict(pending=True))]:
        rows.append(dict(name=name, path='/api/changes.diff' if name == 'pending-disposal' else '/api/changes.open', **options))
    return rows


def prepare(output):
    path = output/'input.json'
    path.write_text(json.dumps(cases()), encoding='utf-8')
    return [path]


async def run(test):
    from dsh.client.ui_deliverables_022 import CurrentClientUiDeliverables022
    from dsh.cordis.context import Context
    from dsh.core.abort import AbortController
    from dsh.fs.fs_local import FsError
    from dsh.host.connection.current import CurrentHostConnection
    from dsh.typert.remote import RemoteError
    ctx, controller, calls = Context(), AbortController(), []
    pending_started = asyncio.Event()
    def fail(stage):
        if test.get('failure') == stage:
            if test.get('remoteCode'): raise RemoteError(test['remoteCode'], '/private/host/path', {})
            raise FsError('/private/host/path', 'UNEXPECTED')
    async def read(request, signal):
        calls.append(dict(op='read', request=request))
        return dict(session=dict(cwd='/child'), target=dict(type='deliverables/presented', data=dict(turn=1, callId='call', files=[dict(path='output.txt')])))
    async def stat(scope, path, signal):
        calls.append(dict(op='stat', scope=scope, path=path)); fail('stat')
        if test.get('abortDuring'): controller.abort(ValueError('cancelled'))
        return dict(absolutePath='/host/current.txt')
    async def resolve(path, options):
        calls.append(dict(op='resolve', path=path)); return object()
    def mapping(path):
        calls.append(dict(op='mapping', path=path)); return None if test.get('unmapped') else '/process/current.txt'
    async def open_path(request, signal):
        calls.append(dict(op='open', request=request)); fail('open')
    async def applications(request, signal):
        calls.append(dict(op='applications', request=request)); fail('applications')
        return dict(applications=[dict(id='custom.app', name='Editor')])
    def summary(sid, seq):
        calls.append(dict(op='summary', sessionId=sid, seq=seq))
        return None if test.get('missing') else dict(turn=1, cwd='/secret/workspace', files=[dict(path='output.txt', display='output.txt', added=1, deleted=0)],
            total=1, added=1, deleted=0, snapshot=dict(before='private-before', after='private-after'))
    async def diff(sid, seq, index, signal):
        calls.append(dict(op='diff', sessionId=sid, seq=seq, index=index)); fail('diff')
        if test.get('pending'):
            pending_started.set()
            await signal.wait_aborted()
            signal.throwIfAborted()
        if test.get('missing') or index != 0: return None
        return dict(kind=test.get('kind', 'text'), path='output.txt', display='output.txt')
    try:
        ctx.set_service('sessionQuery', NS(readEvent=read))
        ctx.set_service('workspaceFiles', NS(stat=stat))
        ctx.set_service('workspaceChanges', NS(summary=summary, diff=diff))
        ctx.set_service('sandboxPolicy', NS(workspaceRoot='/fallback'))
        ctx.set_service('fs', NS(resolve=resolve, processPathFromHostPath=mapping,
            processPath=lambda target: '/host/wrong' if test.get('wrongMapping') else '/host/current.txt'))
        ctx.set_service('sessionController', NS(workspaceDesktop=lambda: dict(name='host', available=not test.get('unavailable'), fileManager='explorer'),
            openWorkspacePath=open_path, workspacePathApplications=applications))
        connection = CurrentHostConnection(ctx, [], NS(isAuthenticated=lambda _: True))
        fiber = await ctx.plugin(CurrentClientUiDeliverables022)
        if test.get('aborted'): controller.abort(ValueError('cancelled'))
        path = test['path']
        query = test.get('query', '?sessionId=s&seq=7&index='+str(test.get('index', 0)))+test.get('suffix', '')
        async def fetch():
            try:
                result = await connection.createSharedFetchHandler('/api').fetch(dict(url='http://localhost'+path+query,
                    path=path, method=test.get('method', 'GET'), headers={}, signal=controller.signal))
                body = result['body']
                if result['headers'].get('content-type', '').startswith('application/json'):
                    body = json.loads(body)
                return dict(status=result['status'], headers=result['headers'], body=body)
            except Exception as error:
                return dict(error=str(error))
        if test.get('pending'):
            task = asyncio.create_task(fetch())
            await asyncio.wait_for(pending_started.wait(), 2)
            await fiber.dispose()
            result = await task
        else:
            result = await fetch()
            await fiber.dispose()
        return dict(name=test['name'], response=result, calls=calls, withdrawn=not any(
            path.startswith(('/api/changes.', '/api/present.')) for path in connection.fetch_routes), listeners=len(controller.signal._listeners))
    finally:
        await ctx.fiber.dispose()


async def observe():
    return [await run(test) for test in cases()]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_change_routes.mts', 'Actual original/native Connection routes: private summary fields, coordinates, lazy diffs, '
        'verified open/application discovery, declared files, mapped-path refusal, sanitized failures, abort and pending-read disposal.',
        [Path(__file__).resolve(), ROOT/'dsh/client/ui_deliverables_022.py'], prepare=prepare)
