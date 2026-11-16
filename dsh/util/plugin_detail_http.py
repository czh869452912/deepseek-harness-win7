"""Owned bounded HTTP reads and npm CDN files on Python 3.8 / Windows 7."""
import asyncio
import math
import urllib.request
from urllib.parse import urljoin
import zlib

from dsh.core.abort import AbortController, NEVER_ABORTED
from dsh.llm.http_stream import open_stream
from dsh.host.http_proxy_policy import parse_url
from dsh.util.plugin_detail import DetailFailure, encode_path, readme_by_name


def _origin(url):
    parsed = parse_url(url)
    if parsed is None or parsed['protocol'] not in ('http:', 'https:'):return None
    return parsed['protocol'], parsed['hostname'], parsed['port']


async def fetch_body(url, max_bytes, signal=NEVER_ABORTED, options=None):
    options = options or {}
    lifetime = options.get('lifetime', NEVER_ABORTED)
    timeout = options.get('timeoutMs', 30000)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 2147483647:
        raise ValueError('timeoutMs must be a positive bounded timer')
    operation = AbortController()
    detach = [signal.add_listener('abort', lambda reason:operation.abort(reason)),
              lifetime.add_listener('abort', lambda reason:operation.abort(reason))]
    loop = asyncio.get_running_loop()
    timer = loop.call_later(timeout/1000, operation.abort)

    def request():
        target, last_status = url, None
        for _ in range(4):
            reading_body = False
            try:
                req = urllib.request.Request(target, headers={'Accept-Encoding':'gzip, deflate'})
                with open_stream(req, operation.signal, idle_timeout_ms=timeout,
                                 redirect_policy='manual', raise_http_errors=False) as (raw, chunks):
                    last_status = raw.status
                    location = raw.headers.get('location') if 300 <= raw.status < 400 else None
                    next_target = None
                    if location is not None:
                        try:
                            candidate = urljoin(target, location)
                            if _origin(candidate) is not None and _origin(candidate) == _origin(url):next_target = candidate
                        except ValueError:pass
                    if next_target is not None:
                        target = next_target
                        continue
                    if not 200 <= raw.status < 300:return dict(ok=False, status=raw.status)
                    try:declared = float(raw.headers.get('content-length', '0'))
                    except ValueError:declared = 0
                    if declared > max_bytes:raise DetailFailure('too-large', url+' exceeds '+str(max_bytes)+' bytes')
                    reading_body = True
                    encoding = raw.headers.get('content-encoding', '').lower()
                    decoder = zlib.decompressobj(16+zlib.MAX_WBITS) if encoding == 'gzip' else zlib.decompressobj() if encoding == 'deflate' else None
                    pieces, size = [], 0
                    for chunk in chunks:
                        if decoder is not None:chunk = decoder.decompress(chunk, max_bytes-size+1)
                        size += len(chunk)
                        if size > max_bytes:raise DetailFailure('too-large', url+' exceeds '+str(max_bytes)+' bytes')
                        pieces.append(chunk)
                    if getattr(raw, 'length', None) not in (None, 0):
                        raise ValueError('Truncated HTTP response')
                    if decoder is not None:
                        tail = decoder.flush(max_bytes-size+1)
                        if size+len(tail) > max_bytes:raise DetailFailure('too-large', url+' exceeds '+str(max_bytes)+' bytes')
                        if not decoder.eof:raise ValueError('Truncated compressed response')
                        pieces.append(tail)
                    return dict(ok=True, bytes=b''.join(pieces))
            except DetailFailure:raise
            except Exception as error:
                if not reading_body:
                    signal.throwIfAborted()
                    lifetime.throwIfAborted()
                raise DetailFailure('network', 'Could not '+('read '+url if reading_body else 'fetch '+target)+': '+str(error)) from error
        return dict(ok=False, status=last_status)

    worker = loop.run_in_executor(None, request)
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        operation.abort()
        try:await asyncio.shield(worker)
        except Exception:pass
        raise
    finally:
        timer.cancel()
        for remove in detach:remove()


class NpmFiles:
    def __init__(self, name, version, sources, options, fetch=None):
        self.name, self.version, self.sources = name, version, sources
        self.options, self.fetch = options, fetch_body if fetch is None else fetch
        self.key = 'npm:'+name+'@'+version

    async def read(self, path, max_bytes, signal=NEVER_ABORTED):
        failures = []
        for source in self.sources:
            suffix = encode_path(path)
            url = {'jsdelivr':'https://cdn.jsdelivr.net/npm/'+self.name+'@'+self.version+'/'+suffix,
                   'unpkg':'https://unpkg.com/'+self.name+'@'+self.version+'/'+suffix,
                   'npmmirror':'https://registry.npmmirror.com/'+self.name+'/'+self.version+'/files/'+suffix}[source]
            try:
                body = await self.fetch(url, max_bytes, signal, self.options)
                if body['ok']:return body['bytes']
                if body['status'] == 404:return None
                failures.append(url+': HTTP '+str(body['status']))
            except DetailFailure as error:
                if error.reason != 'network':raise
                failures.append(error.message)
        raise DetailFailure('network', '; '.join(failures))

    async def readme(self, directory, max_bytes, signal=NEVER_ABORTED):
        return await readme_by_name(self.read, directory, max_bytes, signal)
