"""Peer-aware static frontend resource with browser admission and revalidation."""
import asyncio
import base64
import hashlib
import os
import re
from urllib.parse import urlsplit

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema as z
from dsh.host.frontend_static.frontend_static import MIME_TYPES, HTML_MIME, STATIC_MISS_ERRORS, decode_pathname, url_join

MIME = dict(MIME_TYPES)
MIME['.png'] = 'image/png'
HEAD_OPEN = re.compile(r'<head(?:\s[^>]*)?>', re.IGNORECASE)


def read_bytes(target):
    if os.path.isdir(target):
        raise IsADirectoryError(target)
    with open(target, 'rb') as handle:
        return handle.read()


async def read_owned(target):
    pending = asyncio.get_running_loop().run_in_executor(None, read_bytes, target)
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        await asyncio.gather(pending, return_exceptions=True)
        raise


class IndexAuthorization:
    def __init__(self):
        self.response = dict(status=401, headers={}, body=None)

    def write_status(self, status): self.response['status'] = status
    def write_header(self, name, value): self.response['headers'][name.lower()] = value
    def write_body(self, value): self.response['body'] = value


class CurrentFrontendStatic(Plugin):
    id = 'frontend-static'
    inject = ['webServer', 'connection']
    Config = z.object(dict(distIndex=z.string().required()))

    def apply(self, ctx):
        dist_index = self.config['distIndex']
        dist_root = os.path.dirname(dist_index)
        async def resource(request, peer=None):
            pathname = decode_pathname(urlsplit(request['url']).path)
            target = os.path.abspath(url_join(dist_root, pathname))
            if target != dist_root and not target.startswith(dist_root + os.sep):
                return dict(status=403, headers={}, body=None)
            try:
                index = target in (dist_root, dist_index)
                if index and peer is None:
                    authorization = IndexAuthorization()
                    if not ctx.get('connection').authorize_index(request, authorization):
                        return authorization.response
                body = await read_owned(target if not index else dist_index)
                if index:
                    reader = peer if peer is not None else ctx.get('connection').browserPeer
                    html = ctx.get('webServer').renderIndex(body.decode('utf-8', errors='replace'), reader)
                    body = HEAD_OPEN.sub(lambda match: match.group(0) + '<base href="./">', html, count=1).encode('utf-8')
                    headers = {'content-type': HTML_MIME}
                else:
                    etag = 'W/"' + base64.urlsafe_b64encode(hashlib.sha1(body).digest()).decode('ascii').rstrip('=') + '"'
                    cache = {'cache-control': 'no-cache', 'etag': etag}
                    previous = next((value for key, value in request.get('headers', {}).items() if key.lower() == 'if-none-match'), None)
                    if previous == etag:
                        return dict(status=304, headers=cache, body=None)
                    headers = dict(cache, **{'content-type': MIME.get(os.path.splitext(target)[1], 'application/octet-stream')})
            except STATIC_MISS_ERRORS:
                return dict(status=404, headers={}, body=None)
            return dict(status=200, headers=headers, body=None if request.get('method') == 'HEAD' else body)
        ctx.effect(lambda: ctx.get('webServer').registerFallback(dict(resource=resource)), 'frontend-static: fallback seat')
