import asyncio
import http.client

import pytest

from dsh.cordis.context import Context
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
async def test_standard_http_client_reconnects_before_next_post_instead_of_reusing_closed_socket():
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
                connection.request(method, '/probe')
                response = connection.getresponse()
                observations.append((response.status, response.will_close, response.read()))
            return observations
        finally:
            connection.close()
    try:
        observations = await asyncio.get_running_loop().run_in_executor(None, exercise)
        assert observations == [(200, True, method.encode('ascii')) for method in ('GET', 'POST', 'POST')]
    finally:
        await server.stop()
        await ctx.fiber.dispose()
        await ctx.fiber.await_settled()
