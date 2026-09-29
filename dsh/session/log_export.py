"""Authenticated, pull-driven export of durable Session artifacts and media."""
import asyncio
import io
import json
import re
import zipfile
from urllib.parse import parse_qs, urlsplit

from dsh.cordis.plugin import Plugin
from dsh.core.abort import NEVER_ABORTED
from dsh.host.connection.rpc_host import response


def safe_segment(value):
    return re.sub(r'[^A-Za-z0-9_-]', '_', value)


def image_refs(content):
    refs = {}
    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            if value.get('type') == 'image' and isinstance(value.get('attachment'), dict):
                ref = value['attachment']
                refs[ref['attachmentId']] = ref
            for key in ('content', 'message', 'inserted', 'block'):
                visit(value.get(key))
    for line in content.splitlines():
        try:
            data = json.loads(line).get('data', {})
        except (ValueError, AttributeError):
            continue
        visit(data)
        chunk = data.get('chunk', {})
        if chunk.get('type') == 'block-end':
            visit(chunk.get('block'))
    return refs


async def raw_artifact(ctx, sid, signal):
    signal.throw_if_aborted()
    sessions = ctx.get('sessions')
    session = sessions.get(sid) if sessions is not None else None
    if session is not None:
        await sessions.flush(session)
    raw = await ctx.get('sessionPersistence').read_raw(sid)
    signal.throw_if_aborted()
    return raw


async def entries(ctx, root, sid, descendants, signal):
    media = image_refs(root['content'])
    yield root['filename'], root['content'].encode('utf-8')
    if descendants:
        lineage = await ctx.get('sessionQuery').traceSession(sid, dict(signal=signal))
        seen, pending = {sid}, list(reversed(lineage['descendants']))
        while pending:
            signal.throw_if_aborted()
            node = pending.pop()
            child = node['session']['header'].id
            if child in seen:
                continue
            seen.add(child)
            raw = await raw_artifact(ctx, child, signal)
            if raw is None:
                raise RuntimeError('subagent "%s" has no stored log artifact' % child)
            media.update(image_refs(raw['content']))
            yield 'subagents/%s/%s' % (safe_segment(child), raw['filename']), raw['content'].encode('utf-8')
            pending.extend(reversed(node['descendants']))
    extensions = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp', 'image/gif': 'gif'}
    for ref in media.values():
        signal.throw_if_aborted()
        stored = await ctx.get('attachments').read_image(ref)
        signal.throw_if_aborted()
        yield 'media/%s.%s' % (ref['attachmentId'], extensions[ref['mediaType']]), stored['data']


class ZipSink(io.RawIOBase):
    """Unseekable sink drained after each bounded compressor input block."""
    def __init__(self):
        super().__init__()
        self.offset, self.pending = 0, bytearray()

    def tell(self):
        return self.offset

    def write(self, data):
        self.pending.extend(data)
        self.offset += len(data)
        return len(data)

    def take(self):
        value = bytes(self.pending)
        self.pending.clear()
        return value


async def archive(ctx, root, sid, descendants, level, signal):
    sink = ZipSink()
    with zipfile.ZipFile(sink, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=level, allowZip64=True) as zip_file:
        async for name, data in entries(ctx, root, sid, descendants, signal):
            with zip_file.open(name, 'w', force_zip64=True) as entry:
                for start in range(0, len(data), 65536):
                    signal.throw_if_aborted()
                    entry.write(data[start:start + 65536])
                    chunk = sink.take()
                    if chunk:
                        yield chunk
                    await asyncio.sleep(0)
            chunk = sink.take()
            if chunk:
                yield chunk
    signal.throw_if_aborted()
    yield sink.take()


class SessionLogExportPlugin(Plugin):
    inject = ['commands', 'connection']

    def apply(self, ctx):
        level = self.config.get('compressionLevel', 6)
        if type(level) is not int or not 0 <= level <= 9:
            raise ValueError('compressionLevel must be an integer between 0 and 9')
        async def command(invocation):
            if invocation.rawInput.strip():
                return dict(kind='error', text='The Web /export command does not accept a path.')
            return dict(kind='success', text='Session log download requested.')
        ctx.get('commands').register(dict(name='export', description='Download this Session log as a ZIP archive', handler=command))

        async def fetch(request):
            signal = request.get('signal') or NEVER_ABORTED
            query = parse_qs(urlsplit(request.get('raw_url', request.get('url', request.get('path', '')))).query, keep_blank_values=True)
            if not query:
                query = request.get('query', {})
                if isinstance(query, str):
                    query = parse_qs(query, keep_blank_values=True)
            def value(key):
                item = query.get(key)
                return item[-1] if isinstance(item, list) else item
            sid, descendants = value('sessionId'), value('includeDescendants')
            if not sid or descendants not in (None, 'true', 'false'):
                return response(400, 'missing or invalid sessionId query parameter')
            if any(ctx.get(key) is None for key in ('sessionQuery', 'sessionPersistence', 'attachments')):
                return response(500, 'session log export is unavailable: missing session-query, session-persistence, or attachments service')
            if not callable(getattr(ctx.get('sessionPersistence'), 'read_raw', None)):
                return response(501, 'session log export is unavailable: the persistence backend does not expose per-session raw artifacts')
            try:
                root = await raw_artifact(ctx, sid, signal)
            except Exception:
                signal.throw_if_aborted()
                return response(500, 'session log export failed to prepare the stored artifact')
            if root is None:
                return response(404, 'session not found')
            headers = {'content-type': 'application/zip', 'content-disposition': 'attachment; filename="dsh-session-%s.zip"' % safe_segment(sid)}
            body = b'' if request['method'] == 'HEAD' else archive(ctx, root, sid, descendants == 'true', level, signal)
            return response(200, body, headers)
        ctx.get('connection').fetch.register(dict(path='/api/session.export', methods=['GET', 'HEAD'], fetch=fetch))
