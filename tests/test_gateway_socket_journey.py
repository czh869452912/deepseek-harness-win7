import asyncio
import json
from types import SimpleNamespace

import pytest
from wsproto import WSConnection, ConnectionType
from wsproto.events import Request, AcceptConnection, TextMessage, Ping, CloseConnection

from dsh.cordis.context import Context
from dsh.typert.registry import TypertRegistry
from dsh.typert.remote import Remote, TypertRemoteService
from dsh.typert.gateway import TypertGatewayService
from dsh.host.connection.rpc_host import HostConnectionService
from dsh.host.connection.http_bridge import bridge_handler
from dsh.host.webserver.webserver import WebServerService
from dsh.typert.stream_mux import MuxConnection
from dsh.core.abort import AbortController


class Streams(TypertRemoteService):
    def __init__(self, ctx):
        super().__init__(ctx, "fixture")
        self.closed = asyncio.Event()

    @Remote
    def echo(self, value):
        return value

    @Remote({"mode": "stream"})
    async def watch(self, signal):
        try:
            yield {"message": "first"}
            await signal.wait_aborted()
        finally:
            self.closed.set()

    @Remote({"mode": "stream"})
    async def once(self):
        yield "finished"

    @Remote({"mode": "stream"})
    async def echo_stream(self, value):
        yield value


class Client:
    async def connect(self, port):
        self.reader, self.writer = await asyncio.open_connection("127.0.0.1", port)
        self.codec, self.events = WSConnection(ConnectionType.CLIENT), []
        self.writer.write(self.codec.send(Request(host="127.0.0.1:" + str(port), target="/api/remote.mux")))
        await self.writer.drain()
        assert isinstance(await self.next_event(), AcceptConnection)
        return self

    async def next_event(self):
        while not self.events:
            data = await asyncio.wait_for(self.reader.read(65536), 2)
            if not data:
                raise EOFError("socket closed")
            self.codec.receive_data(data)
            self.events.extend(self.codec.events())
        return self.events.pop(0)

    async def send(self, value):
        self.writer.write(self.codec.send(TextMessage(data=json.dumps(value))))
        await self.writer.drain()

    async def receive(self):
        parts = []
        while True:
            event = await self.next_event()
            if isinstance(event, Ping):
                self.writer.write(self.codec.send(event.response()))
                await self.writer.drain()
            elif isinstance(event, TextMessage):
                parts.append(event.data)
                if event.message_finished:
                    return json.loads("".join(parts))
            else:
                return event

    async def close(self):
        self.writer.close()
        await self.writer.wait_closed()


async def setup(allowed=True):
    ctx = Context()
    await ctx.plugin(TypertRegistry)
    await ctx.plugin(Streams)
    server = WebServerService(ctx, host="127.0.0.1", port=0)
    ctx.set_service("webServer", server)
    connection = HostConnectionService(ctx, [], SimpleNamespace(is_authenticated=lambda _: allowed))
    server.register("prefix", "/api", bridge_handler(connection, connection.createSharedFetchHandler("/api").fetch))
    gateway = await ctx.plugin(TypertGatewayService, config={"websocketHeartbeatIntervalMs": 40})
    await server.start()
    return ctx, server, gateway


@pytest.mark.asyncio
async def test_rpc_and_mux_share_actual_remote_service_cancel_and_drain():
    ctx, server, gateway = await setup()
    client = await Client().connect(server.listened_port)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.listened_port)
        body = json.dumps({"type": "client-request", "rpcId": "r", "method": "fixture/echo", "payload": {"args": {"value": {"ok": 1}}}}).encode()
        writer.write(b"POST /api/fixture/echo HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
        await writer.drain()
        raw = await reader.read()
        assert json.loads(raw.split(b"\r\n\r\n", 1)[1])["result"] == {"ok": True, "value": {"ok": 1}}
        writer.close()
        await writer.wait_closed()
        await client.send({"type": "open", "streamId": "a", "endpoint": "fixture/watch", "payload": {"args": {}}})
        assert await client.receive() == {"type": "item", "streamId": "a", "value": {"message": "first"}}
        await client.send({"type": "open", "streamId": "b", "endpoint": "fixture/once", "payload": {"args": {}}})
        assert (await client.receive())["value"] == "finished"
        assert await client.receive() == {"type": "end", "streamId": "b"}
        await client.send({"type": "cancel", "streamId": "a"})
        await asyncio.wait_for(ctx.get("fixture").closed.wait(), 1)
        # A cancelled stream emits no terminal frame; the next frame is a ping.
        assert isinstance(await client.next_event(), Ping)
        await gateway.dispose()
        assert server._upgrade_routes == {}
    finally:
        await client.close()
        await server.stop()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_mux_duplicate_stream_closes_generation_and_auth_fence_precedes_upgrade():
    ctx, server, gateway = await setup()
    client = await Client().connect(server.listened_port)
    try:
        message = {"type": "open", "streamId": "same", "endpoint": "fixture/watch", "payload": {"args": {}}}
        await client.send(message)
        await client.receive()
        await client.send(message)
        closed = await client.receive()
        assert isinstance(closed, CloseConnection) and closed.code == 1008
        await asyncio.wait_for(ctx.get("fixture").closed.wait(), 1)
    finally:
        await client.close()
        await gateway.dispose()
        await server.stop()
        await ctx.fiber.dispose()


    ctx, server, gateway = await setup(False)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.listened_port)
        codec = WSConnection(ConnectionType.CLIENT)
        writer.write(codec.send(Request(host="127.0.0.1", target="/api/remote.mux")))
        await writer.drain()
        assert b" 401 " in await reader.read()
        writer.close()
        await writer.wait_closed()
    finally:
        await gateway.dispose()
        await server.stop()
        await ctx.fiber.dispose()


class ResetWriter:
    def __init__(self):
        self.closed = False
        self.fail_writes = False

    def write(self, data):
        pass

    async def drain(self):
        if self.fail_writes:
            raise ConnectionResetError(10054, 'fixture peer reset')

    def is_closing(self):
        return self.closed

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


def upgrade_request(reader):
    codec = WSConnection(ConnectionType.CLIENT)
    request = codec.send(Request(host='localhost', target='/api/remote.mux'))
    headers = dict(line.decode('ascii').split(': ', 1) for line in request.split(b'\r\n')[1:] if line)
    return dict(headers={key.lower(): value for key, value in headers.items()},
                path='/api/remote.mux', reader=reader)


@pytest.mark.asyncio
async def test_reset_reader_retires_connection_and_cancels_existing_stream():
    entered, released = asyncio.Event(), asyncio.Event()
    controller = AbortController()
    async def active():
        entered.set()
        try:
            await controller.signal.wait_aborted()
        finally:
            released.set()
    task = asyncio.create_task(active())
    await entered.wait()
    class Reader:
        async def read(self, size):
            raise ConnectionResetError(64, 'fixture Windows reset')
    writer = ResetWriter()
    mux = MuxConnection(upgrade_request(Reader()), writer, None, str, 30000)
    mux.streams['active'] = (controller, task)
    await mux.run()
    assert mux.closed and writer.closed and controller.signal.aborted
    assert released.is_set() and task.done()


@pytest.mark.asyncio
async def test_reset_during_item_error_and_close_delivery_settles_iterator():
    released = asyncio.Event()
    async def source():
        try:
            yield {'value': 1}
        finally:
            released.set()
    async def open_stream(*args):
        return source()
    writer = ResetWriter()
    mux = MuxConnection(upgrade_request(None), writer, open_stream, str, 30000)
    mux.codec.initiate_upgrade_connection(list((key.encode('ascii'), value.encode('ascii'))
        for key, value in mux.request['headers'].items()), '/api/remote.mux')
    list(mux.codec.events())
    await mux.send_event(AcceptConnection())
    writer.fail_writes = True
    await mux.pump(dict(streamId='item', endpoint='fixture/once', payload={}), AbortController())
    assert writer.closed and released.is_set()


@pytest.mark.asyncio
async def test_abrupt_real_socket_close_keeps_other_gateway_connections_usable():
    ctx, server, gateway = await setup()
    first = await Client().connect(server.listened_port)
    second = None
    try:
        await first.send(dict(type='open', streamId='reset', endpoint='fixture/watch', payload=dict(args={})))
        assert (await first.receive())['type'] == 'item'
        first.writer.transport.abort()
        await asyncio.wait_for(ctx.get('fixture').closed.wait(), 2)
        second = await Client().connect(server.listened_port)
        await second.send(dict(type='open', streamId='healthy', endpoint='fixture/once', payload=dict(args={})))
        assert (await second.receive())['value'] == 'finished'
        assert (await second.receive())['type'] == 'end'
    finally:
        if second is not None:
            await second.close()
        await gateway.dispose()
        await server.stop()
        await ctx.fiber.dispose()
