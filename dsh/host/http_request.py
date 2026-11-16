"""Owned, demand-driven HTTP response; no redirect or credential forwarding."""
from contextlib import asynccontextmanager
import urllib.request

from dsh.host.http_decode import contentCodings, decodeContentChunks
from dsh.llm.http_stream import open_stream
from dsh.llm.stream_bridge import OwnedStream, iter_chunks
from dsh.host.url_current import _url


@asynccontextmanager
async def request(url, method, headers, body, signal, redirect_policy='error', advertise_zstd=False):
    def read(cancellation):
        normalized = {}
        for key, value in headers.items():
            key, value = key.lower(), value.strip(' \t\r\n')
            normalized[key] = normalized[key]+', '+value if key in normalized else value
        secureEncoding = 'br, gzip, deflate, zstd' if advertise_zstd else 'br, gzip, deflate'
        normalized.setdefault('accept-encoding', secureEncoding if _url(url)['protocol'] == 'https:' else 'gzip, deflate')
        data = body.encode('utf-8') if body is not None else None
        if data is not None:
            normalized.setdefault('content-type', 'text/plain;charset=UTF-8')
        message = urllib.request.Request(_url(url)['href'], data=data, headers=normalized, method=method)
        with open_stream(message, cancellation, idle_timeout_ms=2147483647,
                         redirect_policy=redirect_policy, raise_http_errors=False) as (response, chunks):
            received = {}
            for key, value in response.headers.items():
                key = key.lower()
                received[key] = received[key]+', '+value if key in received else value
            hasBody = response.status not in (204, 205, 304)
            codings = contentCodings(received.get('content-encoding')) if hasBody else []
            yield dict(status=response.status, hasBody=hasBody, headers=received)
            chunks = decodeContentChunks(chunks, codings)
            yield from chunks
            if response.length is not None and response.length > 0:
                raise RuntimeError('HTTP response ended before its declared Content-Length')
    stream = iter_chunks(OwnedStream(read, signal))
    try:
        metadata = await stream.__anext__()
        yield metadata, stream
    finally:
        await stream.aclose()
