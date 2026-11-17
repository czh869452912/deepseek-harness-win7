import asyncio
from contextlib import asynccontextmanager
import threading

import pytest

from dsh.boot.market_http_022 import MarketHttpReader, cause_chain_of, content_length_number
from dsh.core.abort import AbortController
from dsh.typert.remote import RemoteError
from scripts import rc022_market_http_probe as probe


@pytest.mark.asyncio
async def test_actual_http_index_paths(monkeypatch):
    server = probe.ThreadingHTTPServer(('127.0.0.1', 0), probe.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    monkeypatch.setattr(probe, 'SERVER', server)
    try:
        rows = {row['path']: row['result'] for row in await probe.observe()}
        assert rows['ok']['ok'] and rows['bom'] == rows['ok']
        assert rows['missing']['details']['reason'] == 'HTTP 404'
        assert rows['redirect']['details']['reason'] == 'fetch failed: unexpected redirect'
        for path in ['declared-size', 'stream-size', 'gzip-size']:
            assert rows[path]['details']['reason'] == 'body exceeds 100 bytes'
        assert rows['utf8']['details']['reason'] == 'must be UTF-8'
        assert rows['format']['details']['path'] == '$.format'
        assert rows['slow']['details']['reason'] == 'The operation was aborted due to timeout'
        assert rows['torn']['details']['reason'] == 'terminated'
        assert rows['abort']['details']['reason'] == 'Plugin market disposed'
    finally:
        server.shutdown(); server.server_close(); thread.join(2)
    assert not thread.is_alive()


def response(status=200, headers=None, chunks=(), trace=None):
    @asynccontextmanager
    async def request(url, method, sent, body, signal, **options):
        if trace is not None:
            trace.append(dict(method=method, sent=sent, body=body, options=options))
        async def stream():
            for chunk in chunks:
                if trace is not None: trace.append('read')
                yield chunk
        try: yield dict(status=status, headers=headers or {}), stream()
        finally:
            if trace is not None: trace.append('closed')
    return request


@pytest.mark.asyncio
@pytest.mark.parametrize('status,headers', [(404, {}), (302, {'location': '/next'}), (200, {'content-length': '1001'})])
async def test_refusal_closes_without_body_demand(status, headers):
    trace = []; lifetime = AbortController()
    reader = MarketHttpReader(max_bytes=100, request=response(status, headers, [b'never read'], trace))
    with pytest.raises(RemoteError): await reader('https://market.example/a', lifetime.signal)
    assert 'read' not in trace and trace[-1] == 'closed'
    assert trace[0] == dict(method='GET', sent={'accept': 'application/json'}, body=None,
        options=dict(redirect_policy='manual', advertise_zstd=True))
    assert not lifetime.signal._listeners


@pytest.mark.asyncio
async def test_streaming_overflow_stops_before_later_chunks():
    trace = []; reader = MarketHttpReader(max_bytes=3, request=response(chunks=[b'ab', b'cd', b'never'], trace=trace))
    with pytest.raises(RemoteError) as caught: await reader('https://market.example/a', AbortController().signal)
    assert caught.value.details['reason'] == 'body exceeds 3 bytes'
    assert trace.count('read') == 2 and trace[-1] == 'closed'


@pytest.mark.asyncio
async def test_fetch_timeout_does_not_cover_parser():
    async def parser(body, url, signal):
        await asyncio.sleep(.03)
        signal.throwIfAborted()
        return dict(ok=True, index=dict(title='Parsed'))
    lifetime = AbortController()
    reader = MarketHttpReader(timeout_ms=5, request=response(), parser=parser)
    assert await reader('https://market.example/a', lifetime.signal) == dict(title='Parsed')
    assert not lifetime.signal._listeners


@pytest.mark.asyncio
async def test_lifetime_still_aborts_parser_after_fetch_deadline_removed():
    entered = asyncio.Event()
    async def parser(body, url, signal):
        entered.set(); await signal.wait_aborted(); signal.throwIfAborted()
    lifetime = AbortController(); reason = RuntimeError('Plugin market disposed')
    task = asyncio.create_task(MarketHttpReader(request=response(), parser=parser)('https://market.example/a', lifetime.signal))
    await entered.wait(); lifetime.abort(reason)
    with pytest.raises(RemoteError) as caught: await task
    assert caught.value.code == 'plugin-market/fetch-failed'
    assert caught.value.cause is reason


def test_cyclic_cause_chain_has_source_depth_bound():
    error = RuntimeError('loop'); error.cause = error
    assert cause_chain_of(error) == ': '.join(['loop']*5)


@pytest.mark.parametrize('value,expected', [('  ', 0), ('0x10', 16), ('0b10', 2), ('0o10', 8), ('1e2', 100), ('+Infinity', float('inf'))])
def test_content_length_uses_js_numeric_conversion(value, expected):
    assert content_length_number(value) == expected


@pytest.mark.parametrize('value', ['nope', 'inf', '1_0', '0xZZ', '-0x10'])
def test_unusable_content_length_does_not_imply_overflow(value):
    assert not content_length_number(value) > 1
