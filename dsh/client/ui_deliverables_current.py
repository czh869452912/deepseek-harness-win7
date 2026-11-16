"""rc.3 authenticated native actions for Session-declared source files."""
import asyncio
import json
import re
from urllib.parse import parse_qs, urlsplit

from dsh.cordis.plugin import Plugin
from dsh.core.abort import AbortController
from dsh.core.cancellation import subscribe_abort
from dsh.host.connection.rpc_host import response as connection_response
from dsh.typert.remote import remote_error_of
from dsh.typert.stores import field

def response(status, body, headers=None):
    return connection_response(status, body, {'content-type': 'text/plain;charset=UTF-8'} if headers is None and isinstance(body, str) else headers)


PRESENT_OPEN_PATH = '/api/present.open'
PRESENT_HOST_PATH = '/api/present.host'
JS_WHITESPACE = '\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'


def is_presented_file(value):
    return (isinstance(value, dict) and isinstance(value.get('path'), str)
            and bool(value['path'].strip(JS_WHITESPACE))
            and ('description' not in value or isinstance(value['description'], str)))


def is_presented_data(value):
    if not isinstance(value, dict):
        return False
    turn = value.get('turn')
    return (type(turn) in (int, float) and 1 <= turn <= 9007199254740991 and int(turn) == turn
            and isinstance(value.get('callId'), str) and bool(value['callId'])
            and isinstance(value.get('files'), list))


async def handle_present_open(ctx, request):
    query = parse_qs(urlsplit(request['url']).query, keep_blank_values=True)
    def parameter(name, default=None):
        return query.get(name, [default])[0]
    action = parameter('action', 'open')
    if action not in ('open', 'reveal'):
        return response(400, 'Invalid file action.')
    sid, seq, index = parameter('sessionId'), parameter('seq'), parameter('index')
    def coordinate(value):
        if value is None or re.fullmatch('[0-9]+', value) is None:
            return None
        # Leading zeros are accepted by Number(), including arbitrarily many.
        significant = value.lstrip('0') or '0'
        return int(significant) if len(significant) <= 16 and int(significant) <= 9007199254740991 else None
    seq, index = coordinate(seq), coordinate(index)
    if not sid or seq is None or index is None:
        return response(400, 'Invalid Presented file coordinates.')
    signal = request['signal']
    try:
        signal.throwIfAborted()
        if not ctx.get('sessionController').workspaceDesktop()['available']:
            return response(409, 'Host desktop unavailable.')
        observed = await ctx.get('sessionQuery').readEvent(dict(sessionId=sid, seq=seq, before=0, after=0), signal)
        target, session = observed['target'], observed['session']
        data = field(target, 'data')
        files = data['files'] if field(target, 'type') == 'deliverables/presented' and is_presented_data(data) else []
        file = files[index] if index < len(files) else None
        if not is_presented_file(file):
            return response(404, 'Presented file not found in this Session result.')
        signal.throwIfAborted()
        cwd = field(session, 'cwd')
        scope = dict(sessionId=sid, workspaceRoot=field(ctx.get('sandboxPolicy'), 'workspaceRoot') if cwd is None else cwd)
        info = await ctx.get('workspaceFiles').stat(scope, file['path'], signal)
        path, fs = info['absolutePath'], ctx.get('fs')
        mapped = fs.processPathFromHostPath(path)
        if mapped is None or fs.processPath(await fs.resolve(mapped, dict(signal=signal))) != path:
            return response(422, 'Presented file has no verified Host path.')
        signal.throwIfAborted()
        await ctx.get('sessionController').openWorkspacePath(dict(path=path, **(dict(action=action) if action == 'reveal' else {})), signal)
        return response(204, None, {'cache-control': 'no-store'})
    except Exception as error:
        signal.throwIfAborted()
        remote = remote_error_of(error)
        missing = (remote is not None and remote['code'] in ('session/not-found', 'workspace-file/not-found', 'workspace-file/not-regular-file')
                   or getattr(error, 'code', None) in ('SESSION_QUERY_SESSION_NOT_FOUND', 'SESSION_QUERY_EVENT_NOT_FOUND', 'ENOENT', 'ENOTDIR'))
        return response(404 if missing else 500, 'Presented file unavailable.')


def register_present_open(ctx):
    lifetime, pending = AbortController(), set()

    async def close():
        lifetime.abort()
        if pending:
            await asyncio.gather(*list(pending), return_exceptions=True)
    ctx.effect(lambda: close, 'present: native action lifetime')

    async def host(request):
        return response(200, json.dumps(ctx.get('sessionController').workspaceDesktop(), ensure_ascii=False, separators=(',', ':')),
                        {'content-type': 'application/json', 'cache-control': 'no-store'})

    def fetch(request):
        combined = AbortController()
        subscriptions = [subscribe_abort(signal, combined.abort) for signal in (request.get('signal'), lifetime.signal)]
        async def run():
            try:
                return await handle_present_open(ctx, dict(request, signal=combined.signal))
            finally:
                for dispose in subscriptions:
                    dispose()
        task = asyncio.create_task(run())
        pending.add(task)
        task.add_done_callback(pending.discard)
        return task

    ctx.get('connection').fetch.register(dict(path=PRESENT_HOST_PATH, methods=['GET'], requestBody='buffered', fetch=host))
    ctx.get('connection').fetch.register(dict(path=PRESENT_OPEN_PATH, methods=['POST'], requestBody='buffered', fetch=fetch))


class CurrentClientUiDeliverables(Plugin):
    id = name = '@deepseek-ai/dsh-client-ui-deliverables'
    inject = ['connection', 'sessionQuery', 'sessionController', 'workspaceFiles', 'fs', 'sandboxPolicy']

    def apply(self, ctx):
        register_present_open(ctx)
