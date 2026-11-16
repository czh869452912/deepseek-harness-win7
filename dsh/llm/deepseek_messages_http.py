"""Demand-driven Messages HTTP bytes with owned socket and reader teardown."""
from contextlib import asynccontextmanager
import urllib.request
import zlib

from dsh.llm.http_stream import open_stream
from dsh.llm.llm_service import LlmError
from dsh.llm.stream_bridge import OwnedStream, iter_chunks


def _inflate(chunks, encoding):
    decoder = None; prefix = b''
    for chunk in chunks:
        if decoder is None:
            prefix += chunk
            if len(prefix) < 2: continue
            chunk, prefix = prefix, b''
            window = 16+zlib.MAX_WBITS if encoding == 'gzip' else zlib.MAX_WBITS if chunk[0]&15 == 8 else -zlib.MAX_WBITS
            decoder = zlib.decompressobj(window)
        while chunk:
            value = decoder.decompress(chunk)
            if value: yield value
            chunk = decoder.unused_data
            if decoder.eof and encoding == 'gzip':
                decoder = zlib.decompressobj(16+zlib.MAX_WBITS)
                if chunk.startswith(b'\0'): return
            elif chunk: break
    if decoder is not None:
        value = decoder.flush()
        if value: yield value
    elif prefix:
        # Match zlib's normal incomplete-input behavior at fetch EOF.
        decoder = zlib.decompressobj(16+zlib.MAX_WBITS if encoding == 'gzip' else zlib.MAX_WBITS)
        value = decoder.decompress(prefix)+decoder.flush()
        if value: yield value


@asynccontextmanager
async def requestMessages(url, headers, payload, signal):
    def read_response(cancellation):
        merged = {}
        for key, value in headers.items():
            key, value = key.lower(), value.strip(' \t\r\n')
            merged[key] = merged[key]+', '+value if key in merged else value
        merged.setdefault('accept-encoding', 'gzip, deflate')
        request = urllib.request.Request(url, data=payload.encode('utf-8'), headers=merged, method='POST')
        with open_stream(request, cancellation, idle_timeout_ms=2147483647,
                         redirect_policy='error', raise_http_errors=False) as (response, chunks):
            received = {}
            for key, value in response.headers.items():
                key = key.lower()
                received[key] = received[key]+', '+value if key in received else value
            yield dict(status=response.status, headers=received, hasBody=response.status not in (204, 205))
            decoded = chunks
            for encoding in reversed(received.get('content-encoding', '').split(',')):
                encoding = encoding.strip().lower()
                if encoding in ('gzip', 'deflate'): decoded = _inflate(decoded, encoding)
            yield from decoded
            if response.length is not None and response.length > 0:
                raise RuntimeError('Messages HTTP response ended before its declared Content-Length')
    def read(cancellation):
        try: yield from read_response(cancellation)
        except LlmError as error:
            # Native HTTP framing/cancellation errors are transport exceptions;
            # provider LlmErrors are constructed above this byte boundary.
            raise RuntimeError(error.message) from error
    stream = iter_chunks(OwnedStream(read, signal))
    try:
        metadata = await stream.__anext__()
        yield metadata, stream
    finally:
        await stream.aclose()
