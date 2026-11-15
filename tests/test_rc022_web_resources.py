import pytest

from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.host.webserver.current import CurrentWebServer
from dsh.host.webserver.resources import write_response
from scripts.rc022_web_resources_probe import observe


@pytest.mark.asyncio
async def test_real_http_and_trusted_peer_reads_share_resource_routes():
    rows = {row['name']: row for row in await observe()}
    assert len(rows) == 26
    assert rows['http:/file;tag']['response']['body']['name'] == 'fallback'
    assert rows['read:/files/deep/hide']['response']['status'] == 404
    assert rows['http:/files/deep/hide']['response']['status'] == 209
    direct = rows['read:/file?x=1']['response']['body']
    transport = rows['http:/file?x=1']['response']['body']
    assert direct['peer'] == dict(kind='guest', id='reader')
    assert transport['peer'] is None
    assert direct['url'] == 'http://untrusted.example/file?x=1'
    assert transport['url'] == 'http://x/file?x=1' and transport['host'] == 'transport.example'
    assert rows['http-methods']['calls'] == 0
    assert rows['http-methods']['exact']['status'] == rows['http-methods']['fallback']['status'] == 405
    assert rows['http-head']['cancelled'] == ['head', 'head']
    assert rows['gzip-resource']['response']['headers']['content-encoding'] == 'gzip'
    assert 'content-encoding' not in rows['gzip-head']['response']['headers']
    assert rows['gzip-head']['response']['body'] == ''
    assert rows['read-failure']['error'] == 'resource failed'
    assert rows['http-failure']['response']['status'] == 400
    assert rows['delayed-headers'] == dict(name='delayed-headers', headersEarly=True, body='last')
    assert rows['disconnect']['cancelled'] == [True]


@pytest.mark.asyncio
async def test_resource_read_preserves_peer_and_get_response_and_cancels_head():
    ctx = Context(); server = CurrentWebServer(ctx); peer = object(); observed = []
    class Body:
        closed = 0
        async def aclose(self): self.closed += 1
    body = Body(); response = dict(status=200, headers={'x-original': 'yes'}, body=body)
    async def resource(request, who):
        observed.append((request, who))
        return response
    undo = server.register(dict(kind='exact', path='/data', resource=resource))
    try:
        assert await server.readResource(dict(url='https://remote.example/data'), peer) is response
        assert observed[-1][1] is peer
        assert observed[-1][0]['method'] == 'GET'
        assert not observed[-1][0]['signal'].aborted
        head = await server.readResource(dict(url='https://remote.example/data', method='HEAD'), peer)
        assert head == dict(response, body=None) and body.closed == 1
        undo()
        assert (await server.readResource(dict(url='https://remote.example/data'), peer))['status'] == 404
        assert body.closed == 1
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_head_body_cancel_failure_rejects_read():
    ctx = Context(); server = CurrentWebServer(ctx)
    class Body:
        async def aclose(self): raise RuntimeError('cancel failed')
    server.registerFallback(dict(resource=lambda request, peer: dict(status=200, headers={}, body=Body())))
    try:
        with pytest.raises(RuntimeError, match='cancel failed'):
            await server.readResource(dict(url='http://x/', method='HEAD'), object())
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_naturally_completed_body_is_not_cancelled():
    class Body:
        step, closed = 0, False
        def __aiter__(self): return self
        async def __anext__(self):
            self.step += 1
            if self.step > 1: raise StopAsyncIteration
            return b'chunk'
        async def aclose(self): self.closed = True
    class Writer:
        chunks, flushed, ended = [], False, False
        def write_status(self, status): pass
        async def send_headers(self): self.flushed = True
        async def write_chunk(self, chunk):
            assert self.flushed
            self.chunks.append(chunk)
        async def finish(self): self.ended = True
    writer, body = Writer(), Body()
    await write_response(writer, dict(status=200, headers={}, body=body), AbortController().signal)
    assert writer.chunks == [b'chunk'] and writer.ended and not body.closed
