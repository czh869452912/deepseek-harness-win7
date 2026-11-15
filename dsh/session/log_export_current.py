"""Backend-independent v3 JSONL and streamed attachment ZIP export."""
import asyncio
import json
import re
import zipfile
from urllib.parse import parse_qs, urlsplit

from dsh.cordis.json_text import stringify_json
from dsh.cordis.plugin import Plugin
from dsh.core.abort import NEVER_ABORTED
from dsh.host.connection.rpc_host import response
from dsh.session.log_export import ZipSink, safe_segment
from dsh.session.persistence import SessionPersistenceNotFoundError

SESSION_LOG_FILENAME = 'session.v3.jsonl'
EXTENSIONS = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp', 'image/gif': 'gif'}


def field(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def serialize_session_log(header, events):
    row = dict(type='session', version=field(header, 'version'), id=field(header, 'id'),
               createdAt=field(header, 'createdAt'))
    for key in ('cwd', 'parentSession'):
        if field(header, key) is not None:
            row[key] = field(header, key)
    row['isSeeded'] = field(header, 'isSeeded')
    if field(header, 'origin') is not None:
        row['origin'] = field(header, 'origin')
    row['delegationDepth'] = field(header, 'delegationDepth', 0)
    if row['delegationDepth'] is None:
        row['delegationDepth'] = 0
    if field(header, 'agentPreset') is not None:
        row['agentPreset'] = field(header, 'agentPreset')
    return '\n'.join(stringify_json(value) for value in [row, *events]) + '\n'


async def read_session_log_text(persistence, session_id, signal=None):
    options = {} if signal is None else dict(signal=signal)
    try:
        handle = await persistence.open(session_id, 'read', options)
    except SessionPersistenceNotFoundError:
        return None
    try:
        result = await handle.read(0, 9007199254740991, options)
        return serialize_session_log(handle.header, result['events'])
    finally:
        await handle.close()


async def flush_live_session_log(ctx, session_id, signal):
    signal.throw_if_aborted()
    sessions = ctx.get('sessions')
    session = sessions.get(session_id) if sessions is not None else None
    if session is not None:
        await sessions.flush(session)
        signal.throw_if_aborted()


def attachment_refs(content, images, files):
    def collect(content):
        if not isinstance(content, list):
            return
        pending = list(content)
        while pending:
            block = pending.pop()
            if not isinstance(block, dict):
                continue
            ref = block.get('attachment')
            if isinstance(ref, dict):
                if block.get('type') == 'image':
                    images[ref['attachmentId']] = ref
                if block.get('type') == 'file':
                    files[(ref['attachmentId'], ref['name'])] = ref
            if isinstance(block.get('content'), list):
                pending.extend(block['content'])
    for line in content.split('\n'):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        data = field(event, 'data')
        if not isinstance(data, dict):
            continue
        collect(data.get('content'))
        collect(field(data.get('message'), 'content'))
        for message in data.get('inserted', []):
            collect(field(message, 'content'))
        for record in data.get('stream', []):
            chunk = field(record, 'chunk')
            if field(record, 'type') == 'chunk' and field(chunk, 'type') == 'block-end':
                collect([field(chunk, 'block')])


def file_entry_path(ref):
    digest = re.sub(r'^sha256:', '', ref['attachmentId'])
    name = re.sub(r'[\\/\x00-\x1f\x7f]', '_', ref['name'])
    if name in ('', '.', '..'):
        name = 'file'
    return 'files/{}/{}/{}'.format(digest[:2], digest, name)


async def session_log_zip_entries(ctx, root, session_id, descendants=False, signal=NEVER_ABORTED):
    images, files = {}, {}
    attachment_refs(root, images, files)
    yield dict(path=SESSION_LOG_FILENAME, content=root)
    if descendants:
        seen = {session_id}
        lineage = await ctx.get('sessionQuery').traceSession(session_id, dict(signal=signal))
        signal.throw_if_aborted()
        pending = list(reversed(lineage['descendants']))
        while pending:
            signal.throw_if_aborted()
            node = pending.pop()
            child = field(node['session']['header'], 'id')
            if child in seen:
                continue
            seen.add(child)
            await flush_live_session_log(ctx, child, signal)
            content = await read_session_log_text(ctx.get('sessionPersistence'), child, signal)
            signal.throw_if_aborted()
            if content is None:
                raise RuntimeError('subagent "{}" has no stored log'.format(child))
            attachment_refs(content, images, files)
            yield dict(path='subagents/{}/{}'.format(safe_segment(child), SESSION_LOG_FILENAME), content=content)
            pending.extend(reversed(node['descendants']))
    for ref in images.values():
        signal.throw_if_aborted()
        stored = await ctx.get('attachments').readImage(ref, signal)
        signal.throw_if_aborted()
        yield dict(path='media/{}.{}'.format(ref['attachmentId'], EXTENSIONS[ref['mediaType']]), data=stored['data'])
    for ref in files.values():
        signal.throw_if_aborted()
        yield dict(path=file_entry_path(ref), chunks=ctx.get('attachments').readFileStream(ref, signal))


async def archive(ctx, root, session_id, descendants, level, signal):
    async def chunks(row):
        if 'chunks' in row:
            source = row['chunks'].__aiter__()
            try:
                async for chunk in source:
                    yield chunk
            finally:
                close = getattr(source, 'aclose', None)
                if close is not None:
                    await close()
        elif 'content' in row:
            text = row['content']
            for start in range(0, len(text), 65536):
                yield text[start:start + 65536].encode('utf-8')
        else:
            yield row['data']
    sink = ZipSink()
    with zipfile.ZipFile(sink, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=level, allowZip64=True) as zipped:
        async for row in session_log_zip_entries(ctx, root, session_id, descendants, signal):
            with zipped.open(row['path'], 'w', force_zip64=True) as entry:
                source = chunks(row)
                try:
                    async for data in source:
                        for start in range(0, len(data), 65536):
                            signal.throw_if_aborted()
                            entry.write(data[start:start + 65536])
                            yield sink.take()
                            signal.throw_if_aborted()
                            await asyncio.sleep(0)
                finally:
                    await source.aclose()
            chunk = sink.take()
            if chunk:
                yield chunk
    signal.throw_if_aborted()
    yield sink.take()


class CurrentSessionLogExportPlugin(Plugin):
    inject = ['commands', 'connection']

    def apply(self, ctx):
        level = self.config.get('compressionLevel', 6)
        if type(level) not in (int, float) or not 0 <= level <= 9 or int(level) != level:
            raise ValueError('compressionLevel must be an integer between 0 and 9')
        async def command(invocation):
            return (dict(kind='error', text='The Web /export command does not accept a path.') if invocation.rawInput.strip()
                    else dict(kind='success', text='Session log download requested.'))
        ctx.effect(lambda: ctx.get('commands').register(dict(name='export', definitionId='@deepseek-ai/dsh-session-log-export',
            description='Download this Session log as a ZIP archive', handler=command)), 'session-log-download: command')

        async def fetch(request):
            head, signal = request['method'] == 'HEAD', request.get('signal') or NEVER_ABORTED
            def answer(status, body, headers=None):
                return response(status, None if head else body,
                                headers if headers is not None else {'content-type': 'text/plain;charset=UTF-8'})
            query = parse_qs(urlsplit(request['url']).query, keep_blank_values=True)
            session_id = query.get('sessionId', [''])[-1]
            descendants = query.get('includeDescendants', [None])[-1]
            if not session_id or descendants not in (None, 'true', 'false'):
                return answer(400, 'missing or invalid sessionId query parameter')
            if any(ctx.get(key) is None for key in ('sessionQuery', 'sessionPersistence', 'attachments')):
                return answer(500, 'session log export is unavailable: missing session-query, session-persistence, or attachments service')
            try:
                await flush_live_session_log(ctx, session_id, signal)
                root = await read_session_log_text(ctx.get('sessionPersistence'), session_id, signal)
                signal.throw_if_aborted()
            except Exception:
                signal.throw_if_aborted()
                return answer(500, 'session log export failed to read the stored log')
            if root is None:
                return answer(404, 'session not found')
            headers = {'content-type': 'application/zip',
                'content-disposition': 'attachment; filename="dsh-session-{}.zip"'.format(safe_segment(session_id))}
            return answer(200, None if head else archive(ctx, root, session_id, descendants == 'true', int(level), signal), headers)
        ctx.get('connection').fetch.register(dict(path='/api/session.export', methods=['GET', 'HEAD'],
                                                  requestBody='buffered', fetch=fetch))
