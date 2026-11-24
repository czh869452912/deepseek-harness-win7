import asyncio
import gzip
import http.client
import threading

import pytest

from dsh.cordis.context import Context
from dsh.host.connection.http_current import current_bridge_handler
from dsh.host.webserver import webserver
from dsh.host.webserver.webserver import HttpResponseWriter, WebServerService


class BufferedWriter:
    def __init__(self):
        self.data = bytearray()

    def write(self, data):
        self.data.extend(data)

    async def drain(self):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize('headers', [{}, {'Connection': 'keep-alive'},
    {'Connection': 'keep-alive', 'connection': 'keep-alive'}])
async def test_one_request_carrier_does_not_advertise_an_already_closing_persistent_socket(headers):
    writer = BufferedWriter()
    response = HttpResponseWriter(writer)
    for name, value in headers.items():
        response.write_header(name, value)
    response.write_body(b'complete')
    await response.finish()
    header, body = bytes(writer.data).split(b'\r\n\r\n', 1)
    connections = [line.lower() for line in header.split(b'\r\n') if line.lower().startswith(b'connection:')]
    assert connections == [b'connection: close']
    assert body == b'complete'


@pytest.mark.asyncio
@pytest.mark.parametrize('close', [False, True])
async def test_standard_http_client_reuses_only_an_open_connection(close):
    ctx = Context()
    server = WebServerService(ctx, host='127.0.0.1', port=0)
    async def answer(request, response):
        response.write_body(request['method'].encode('ascii'))
        await response.finish()
    server.register('exact', '/probe', answer)
    await server.start()
    def exercise():
        connection = http.client.HTTPConnection('127.0.0.1', server.listened_port, timeout=5)
        try:
            observations = []
            for method in ('GET', 'POST', 'POST'):
                connection.request(method, '/probe', headers={'Connection': 'close'} if close else {})
                response = connection.getresponse()
                observations.append((response.status, response.will_close, response.read(),
                                     connection.sock))
            return observations
        finally:
            connection.close()
    try:
        observations = await asyncio.get_running_loop().run_in_executor(None, exercise)
        assert [row[:3] for row in observations] == [
            (200, close, method.encode('ascii')) for method in ('GET', 'POST', 'POST')]
        if not close:
            assert observations[0][3] is not None
            assert observations[0][3] is observations[1][3] is observations[2][3]
    finally:
        await server.stop()
        await ctx.fiber.dispose()
        await ctx.fiber.await_settled()


@pytest.mark.asyncio
async def test_pipelined_buffered_rpc_keeps_each_request_body_and_disconnect_separate():
    from types import SimpleNamespace

    ctx = Context()
    server = WebServerService(ctx, port=0)
    signals = []

    async def fetch(request):
        signals.append(request['signal'])
        await asyncio.sleep(0)
        return dict(status=200, body=request['body'])

    bridge = current_bridge_handler(SimpleNamespace(request_rejection=lambda _: None),
        SimpleNamespace(requestBodyMode=lambda _: 'buffered', fetch=fetch))
    server.register('exact', '/probe', bridge)
    await server.start()
    reader, writer = await asyncio.open_connection('127.0.0.1', server.listened_port)
    try:
        writer.write(b'POST /probe HTTP/1.1\r\nHost: localhost\r\nContent-Length: 3\r\n\r\none'
                     b'POST /probe HTTP/1.1\r\nHost: localhost\r\nContent-Length: 3\r\nConnection: close\r\n\r\ntwo')
        await writer.drain()
        first = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 3)
        assert b'Connection: close' not in first
        assert await reader.readexactly(3) == b'one'
        second = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 3)
        assert b'Connection: close' in second
        assert await reader.readexactly(3) == b'two'
        assert await asyncio.wait_for(reader.read(), 3) == b''
        assert len(signals) == 2 and not any(signal.aborted for signal in signals)
    finally:
        writer.close()
        await writer.wait_closed()
        await server.stop()
        await ctx.fiber.dispose()
        await ctx.fiber.await_settled()


@pytest.mark.asyncio
async def test_buffered_gzip_response_is_chunk_framed_on_a_reused_socket(monkeypatch):
    server = WebServerService(None, port=0, compression='gzip', compression_threshold_bytes=1)
    event_loop_thread = threading.get_ident()
    compression_threads = []
    original_compressor = webserver.zlib.compressobj
    payloads = {'/probe/first': b'first' * 1024, '/probe/second': b'second' * 65536}

    class Compressor:
        def __init__(self, *args):
            self.stream = original_compressor(*args)

        def compress(self, data):
            compression_threads.append(threading.get_ident())
            return self.stream.compress(data)

        def flush(self):
            return self.stream.flush()

    monkeypatch.setattr(webserver.zlib, 'compressobj', Compressor)

    async def answer(request, response):
        response.write_header('Content-Type', 'text/plain')
        response.write_body(payloads[request['path']])
        await response.finish()

    server.register('prefix', '/probe', answer)
    await server.start()

    def exercise():
        client = http.client.HTTPConnection('127.0.0.1', server.port, timeout=3)
        try:
            socket = None
            for path in ('/probe/first', '/probe/second'):
                client.request('GET', path, headers={'Accept-Encoding': 'gzip'})
                response = client.getresponse()
                assert response.status == 200 and response.chunked and not response.will_close
                assert gzip.decompress(response.read()) == payloads[path]
                if socket is None:
                    socket = client.sock
                    assert socket is not None
                else:
                    assert client.sock is socket
        finally:
            client.close()

    try:
        await asyncio.get_running_loop().run_in_executor(None, exercise)
        assert len(compression_threads) == 2
        assert compression_threads[0] == event_loop_thread
        assert compression_threads[1] != event_loop_thread
    finally:
        await server.stop()
