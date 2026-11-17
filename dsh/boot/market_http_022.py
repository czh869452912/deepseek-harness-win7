"""Bounded anonymous market HTTP index fetch over the owned Host transport."""
import asyncio
import http.client
import math
import re

from dsh.boot.market_index_022 import parse_index_body
from dsh.core.abort import AbortController
from dsh.cordis.errors import ThrownValueError
from dsh.cordis.text import trim_js
from dsh.cordis.utils import _js_key_to_string
from dsh.host.http_request import request as request_http
from dsh.typert.remote import RemoteError


def message_of(error):
    if not isinstance(error, ThrownValueError):
        return str(error)
    value = error.value
    return 'null' if value is None else _js_key_to_string(value)


def cause_chain_of(error, depth=0):
    cause = getattr(error, 'cause', getattr(error, '__cause__', None))
    if not isinstance(error, ThrownValueError) and cause is not None and depth < 4:
        return message_of(error)+': '+cause_chain_of(cause, depth+1)
    return message_of(error)


def content_length_number(text):
    value = trim_js(str(text))
    if not value:
        return 0
    if re.fullmatch(r'0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+', value):
        try: return float(int(value, 0))
        except OverflowError: return math.inf
    if re.fullmatch(r'[+-]?(?:Infinity|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)', value, flags=re.ASCII):
        return float(value)
    return math.nan


class MarketHttpReader:
    def __init__(self, timeout_ms=15000, max_bytes=128*1024*1024, request=None, parser=None):
        self.timeout_ms, self.max_bytes = timeout_ms, max_bytes
        self.request, self.parser = request or request_http, parser or parse_index_body

    async def __call__(self, url, lifetime):
        def failed(reason, cause=None):
            return RemoteError('plugin-market/fetch-failed', 'Could not fetch '+url+': '+reason,
                               dict(url=url, reason=reason), cause=cause)
        scope = AbortController()
        remove = lifetime.add_listener('abort', lambda reason: scope.abort(reason))
        timer = asyncio.get_running_loop().call_later(self.timeout_ms/1000,
            scope.abort, RuntimeError('The operation was aborted due to timeout'))
        phase = 'request'
        try:
            try:
                scope.signal.throwIfAborted()
                async with self.request(url, 'GET', {'accept': 'application/json'}, None, scope.signal,
                                        redirect_policy='manual', advertise_zstd=True) as (response, stream):
                    status, headers = response['status'], response['headers']
                    if status in (301, 302, 303, 307, 308) and 'location' in headers:
                        raise failed('fetch failed: unexpected redirect')
                    if not 200 <= status < 300:
                        raise failed('HTTP '+str(status))
                    phase = 'body'
                    too_large = 'body exceeds '+str(self.max_bytes)+' bytes'
                    if content_length_number(headers.get('content-length', 0)) > self.max_bytes:
                        raise failed(too_large)
                    size, chunks = 0, []
                    async for chunk in stream:
                        size += len(chunk)
                        if size > self.max_bytes:
                            raise failed(too_large)
                        chunks.append(chunk)
                    body = b''.join(chunks)
            except RemoteError:
                raise
            except Exception as error:
                if scope.signal.aborted:
                    raise failed(message_of(scope.signal.reason), error)
                if phase == 'body' and (isinstance(error, (http.client.HTTPException, OSError))
                        or str(error) == 'HTTP response ended before its declared Content-Length'):
                    raise failed('terminated', error)
                raise failed(cause_chain_of(error) if phase == 'request' else message_of(error), error)
        finally:
            timer.cancel()
            remove()
        # Source's fetch timeout covers headers/body, not the isolated parser.
        # Its lifetime still owns parsing through service disposal.
        try:
            result = await self.parser(body, url, lifetime)
        except Exception as error:
            raise failed(message_of(error), error)
        if result['ok']:
            return result['index']
        raise RemoteError('plugin-market/invalid-index', url+': '+result['message'],
                          dict(url=url, path=result['path'], reason=result['reason']))
