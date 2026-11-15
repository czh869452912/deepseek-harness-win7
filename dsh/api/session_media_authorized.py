"""Authenticated version-addressed file display through the composed FS."""
import os
from urllib.parse import parse_qs, quote_plus, urlsplit

from dsh.api.session_media_current import BASE_HEADERS, ERROR_STATUSES, field, media_type
from dsh.cordis.plugin import Plugin
from dsh.fs.fs_local import FsError
from dsh.host.connection.rpc_host import response


VERSIONED_HEADERS = dict(BASE_HEADERS, **{'cache-control': 'private, max-age=31536000, immutable'})


def query_value(value):
    # URLSearchParams uses form encoding, including '~' but excluding '*'.
    return quote_plus(str(value), safe='*-._').replace('~', '%7E')


async def serve_file(request, fs, max_bytes):
    head = request['method'] == 'HEAD'
    def fail(status, text):
        headers = dict(BASE_HEADERS)
        if not head:
            headers['content-type'] = 'text/plain;charset=UTF-8'
        return response(status, None if head else text, headers)
    params = parse_qs(urlsplit(request['url']).query, keep_blank_values=True)
    path = params.get('path', [None])[0]
    if path is None or path == '':
        return fail(400, 'missing path')
    if '\0' in path or not os.path.isabs(path):
        return fail(400, 'absolute path required')
    signal = request.get('signal')
    try:
        target = await fs.resolve(path, dict(signal=signal))
        info = await fs.stat(target, signal)
        if info is None:
            return fail(404, 'not found')
        if field(info, 'type') != 'file':
            return fail(403, 'not a regular file')
        size = field(info, 'size')
        if size is not None and size > max_bytes:
            return fail(413, 'file exceeds byte limit')
        version = field(info, 'version')
        if params.get('v', [None])[0] != version:
            return response(302, None, dict(BASE_HEADERS, location='?path='+query_value(path)+'&v='+query_value(version)))
        headers = dict(VERSIONED_HEADERS, **{'content-type': media_type(field(target, 'displayPath'))})
        if head:
            if size is not None:
                headers['content-length'] = str(size)
            return response(200, None, headers)
        data = bytes(await fs.readBytes(target, signal, max_bytes))
        headers['content-length'] = str(len(data))
        return response(200, data, headers)
    except FsError as error:
        return fail(ERROR_STATUSES.get(error.code, 500), error.code)


class AuthorizedSessionMediaReferences(Plugin):
    inject = ['connection', 'fs', 'attachments']

    def apply(self, ctx):
        max_bytes = ctx.get('attachments').imageLimits['maxImageBytes']
        ctx.effect(lambda: ctx.get('connection').fetch.register(dict(path='/api/file', methods=['GET', 'HEAD'],
            requestBody='buffered', fetch=lambda request: serve_file(request, ctx.get('fs'), max_bytes))),
            'session-controller: /api/file')
