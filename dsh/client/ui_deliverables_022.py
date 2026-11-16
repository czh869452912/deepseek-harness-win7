"""rc.3 authenticated change summaries, comparisons and verified native opens."""
import asyncio
import re
from urllib.parse import parse_qs, urlsplit

from dsh.client.ui_deliverables_current import (PRESENT_HOST_PATH, PRESENT_OPEN_PATH,
    is_presented_data, is_presented_file, response)
from dsh.cordis.json_text import stringify_json
from dsh.cordis.plugin import Plugin
from dsh.core.abort import AbortController
from dsh.core.cancellation import subscribe_abort
from dsh.typert.remote import remote_error_of
from dsh.typert.stores import field

CHANGED_FILES_PATH = '/api/changes.summary'
CHANGES_DIFF_PATH = '/api/changes.diff'
CHANGES_OPEN_PATH = '/api/changes.open'


def query_of(request):
    return {key: values[0] for key, values in parse_qs(urlsplit(request['url']).query, keep_blank_values=True).items()}


def coordinate(value):
    if value is None or re.fullmatch('[0-9]+', value) is None:
        return None
    significant = value.lstrip('0') or '0'
    return int(significant) if len(significant) <= 16 and int(significant) <= 9007199254740991 else None


def json_response(value):
    return response(200, stringify_json(value), {'content-type': 'application/json', 'cache-control': 'no-store'})


def failure_status(error):
    remote = remote_error_of(error)
    missing = (remote is not None and remote['code'] in ('session/not-found', 'workspace-file/not-found', 'workspace-file/not-regular-file')
               or getattr(error, 'code', None) in ('SESSION_QUERY_SESSION_NOT_FOUND', 'SESSION_QUERY_EVENT_NOT_FOUND', 'ENOENT', 'ENOTDIR'))
    return 404 if missing else 500


async def open_verified(ctx, request, path, action):
    fs, signal = ctx.fs, request['signal']
    mapped = fs.processPathFromHostPath(path)
    if mapped is None or fs.processPath(await fs.resolve(mapped, dict(signal=signal))) != path:
        return response(422, 'Path has no verified Host path.')
    signal.throwIfAborted()
    if request['method'] == 'GET':
        return json_response(await ctx.sessionController.workspacePathApplications(dict(path=path), signal))
    application = query_of(request).get('application')
    options = dict(action=action) if action == 'reveal' else {} if application is None else dict(application=application)
    await ctx.sessionController.openWorkspacePath(dict(path=path, **options), signal)
    return response(204, None, {'cache-control': 'no-store'})


async def handle_present_open(ctx, request):
    query, signal = query_of(request), request['signal']
    action = query.get('action', 'open')
    if action not in ('open', 'reveal'):
        return response(400, 'Invalid file action.')
    sid, seq, index = query.get('sessionId'), coordinate(query.get('seq')), coordinate(query.get('index'))
    if not sid or seq is None or index is None:
        return response(400, 'Invalid Presented file coordinates.')
    try:
        signal.throwIfAborted()
        if not ctx.sessionController.workspaceDesktop()['available']:
            return response(409, 'Host desktop unavailable.')
        observed = await ctx.sessionQuery.readEvent(dict(sessionId=sid, seq=seq, before=0, after=0), signal)
        target, session = observed['target'], observed['session']
        data = field(target, 'data')
        files = data['files'] if field(target, 'type') == 'deliverables/presented' and is_presented_data(data) else []
        file = files[index] if index < len(files) else None
        if not is_presented_file(file):
            return response(404, 'Presented file not found in this Session result.')
        signal.throwIfAborted()
        cwd = field(session, 'cwd')
        info = await ctx.workspaceFiles.stat(dict(sessionId=sid,
            workspaceRoot=ctx.sandboxPolicy.workspaceRoot if cwd is None else cwd), file['path'], signal)
        return await open_verified(ctx, request, info['absolutePath'], action)
    except Exception as error:
        signal.throwIfAborted()
        return response(failure_status(error), 'Presented file unavailable.')


def handle_changes_summary(ctx, request):
    query = query_of(request)
    sid, seq = query.get('sessionId'), coordinate(query.get('seq'))
    if not sid or seq is None:
        return response(400, 'Invalid change summary coordinates.')
    summary = ctx.workspaceChanges.summary(sid, seq)
    if summary is None:
        return response(404, 'Change summary unavailable.')
    return json_response({key: summary[key] for key in ('turn', 'files', 'total', 'added', 'deleted')})


def changed_coordinates(request):
    query = query_of(request)
    sid, seq, index = query.get('sessionId'), coordinate(query.get('seq')), coordinate(query.get('index'))
    return None if not sid or seq is None or index is None else (sid, seq, index)


async def handle_changes_diff(ctx, request):
    coordinates, signal = changed_coordinates(request), request['signal']
    if coordinates is None:
        return response(400, 'Invalid changed file coordinates.')
    try:
        diff = await ctx.workspaceChanges.diff(*coordinates, signal)
        if diff is None:
            return response(404, 'Change comparison unavailable.')
        return json_response(diff)
    except Exception as error:
        signal.throwIfAborted()
        return response(failure_status(error), 'Change comparison unavailable.')


async def handle_changes_open(ctx, request):
    query, signal = query_of(request), request['signal']
    action = query.get('action', 'open')
    if action not in ('open', 'reveal'):
        return response(400, 'Invalid file action.')
    coordinates = changed_coordinates(request)
    if coordinates is None:
        return response(400, 'Invalid changed file coordinates.')
    sid, seq, index = coordinates
    try:
        signal.throwIfAborted()
        if not ctx.sessionController.workspaceDesktop()['available']:
            return response(409, 'Host desktop unavailable.')
        summary = ctx.workspaceChanges.summary(sid, seq)
        if summary is None:
            return response(404, 'Change summary unavailable.')
        if index >= len(summary['files']):
            return response(404, 'Changed file not found in this summary.')
        info = await ctx.workspaceFiles.stat(dict(sessionId=sid, workspaceRoot=summary['cwd']), summary['files'][index]['path'], signal)
        return await open_verified(ctx, request, info['absolutePath'], action)
    except Exception as error:
        signal.throwIfAborted()
        return response(failure_status(error), 'Changed file unavailable.')


def register_present_open(ctx):
    async def host(request):
        return json_response(ctx.sessionController.workspaceDesktop())

    async def summary(request):
        return handle_changes_summary(ctx, request)

    ctx.connection.fetch.register(dict(path=PRESENT_HOST_PATH, methods=['GET'], requestBody='buffered', fetch=host))
    ctx.connection.fetch.register(dict(path=CHANGED_FILES_PATH, methods=['GET'], requestBody='buffered', fetch=summary))
    lifetime, pending = AbortController(), set()

    async def close():
        lifetime.abort()
        if pending:
            await asyncio.gather(*list(pending), return_exceptions=True)
    ctx.effect(lambda: close, 'deliverables: native action and comparison lifetime')

    def wrap(handler):
        def fetch(request):
            combined = AbortController()
            subscriptions = [subscribe_abort(signal, combined.abort) for signal in (request.get('signal'), lifetime.signal)]
            async def run():
                try:
                    return await handler(ctx, dict(request, signal=combined.signal))
                finally:
                    for dispose in subscriptions:
                        dispose()
            task = asyncio.create_task(run())
            pending.add(task)
            task.add_done_callback(pending.discard)
            return task
        return fetch

    for path, methods, handler in [(PRESENT_OPEN_PATH, ['GET', 'POST'], handle_present_open),
            (CHANGES_OPEN_PATH, ['GET', 'POST'], handle_changes_open), (CHANGES_DIFF_PATH, ['GET'], handle_changes_diff)]:
        ctx.connection.fetch.register(dict(path=path, methods=methods, requestBody='buffered', fetch=wrap(handler)))


class CurrentClientUiDeliverables022(Plugin):
    id = name = '@deepseek-ai/dsh-client-ui-deliverables'
    inject = ['connection', 'sessionQuery', 'sessionController', 'workspaceFiles', 'fs', 'sandboxPolicy', 'workspaceChanges']

    def apply(self, ctx):
        register_present_open(ctx)
