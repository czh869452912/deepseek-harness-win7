import asyncio
import os
import socket
import struct

import pytest

from dsh.cordis.context import Context
from dsh.host.webserver.socket_server import OwnedSocket, OwnedSocketServer
from dsh.host.webserver.webserver import WebServerService


def reset_error(code=10054):
    error = ConnectionResetError(code, 'controlled peer reset')
    error.winerror = code
    return error


@pytest.mark.parametrize('code', [10054, 10053, None])
def test_owned_socket_contains_only_windows_peer_reset_at_shutdown(monkeypatch, code):
    original = socket.socket()
    warnings = []
    owned = OwnedSocket(original.family, original.type, original.proto,
        original.detach(), warnings.append)
    error = reset_error(code)

    def fail_shutdown(self, how):
        assert self is owned and how == socket.SHUT_RDWR
        raise error

    monkeypatch.setattr(socket.socket, 'shutdown', fail_shutdown)
    try:
        if code == 10054:
            owned.shutdown(socket.SHUT_RDWR)
            assert warnings == [error]
        else:
            with pytest.raises(ConnectionResetError) as caught:
                owned.shutdown(socket.SHUT_RDWR)
            assert caught.value is error and warnings == []
    finally:
        owned.close()
    assert owned.fileno() == -1


@pytest.mark.asyncio
async def test_reset_during_actual_proactor_cleanup_closes_socket_and_notifies_once(monkeypatch):
    if os.name != 'nt':
        return
    from asyncio.proactor_events import _ProactorBasePipeTransport
    original = socket.socket()
    warnings = []
    owned = OwnedSocket(original.family, original.type, original.proto,
        original.detach(), warnings.append)
    error = reset_error()
    notifications = []
    detachments = []

    class Protocol:
        def connection_lost(self, failure):
            notifications.append(failure)

    class Server:
        def _detach(self):
            detachments.append(True)

    def fail_shutdown(self, how):
        raise error

    monkeypatch.setattr(socket.socket, 'shutdown', fail_shutdown)
    transport = object.__new__(_ProactorBasePipeTransport)
    transport._sock = owned
    transport._protocol = Protocol()
    transport._server = Server()
    transport._closing = True
    transport._call_connection_lost(None)
    assert notifications == [None] and detachments == [True]
    assert warnings == [error] and owned.fileno() == -1
    assert transport._sock is None and transport._server is None


@pytest.mark.asyncio
async def test_owned_listener_cancellation_releases_accept_and_bound_port():
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    listener.setblocking(False)
    server = OwnedSocketServer(listener, lambda reader, writer: None, lambda error: None)
    assert server.is_serving() and len(server.sockets) == 1
    await server.start_serving()
    server.close()
    server.close()
    await server.wait_closed()
    assert server.accept_task.done() and not server.is_serving()
    assert server.sockets == () and listener.fileno() == -1
    with pytest.raises(RuntimeError, match='listener is closed'):
        await server.start_serving()


@pytest.mark.asyncio
@pytest.mark.parametrize('upgrade', [False, True])
async def test_real_peer_resets_retire_owned_connections_and_leave_host_healthy(upgrade):
    ctx = Context()
    server = WebServerService(ctx, port=0)
    loop = asyncio.get_running_loop()
    errors = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda active_loop, context: errors.append(context))
    entered = asyncio.Queue()
    retired = asyncio.Queue()

    async def streaming(request, response):
        writer = response if upgrade else response.writer
        entered.put_nowait(writer)
        try:
            if upgrade:
                writer.write(b'HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: probe\r\n\r\n')
                await writer.drain()
            else:
                response.write_header('Content-Type', 'text/event-stream')
                await response.send_headers()
            await request['reader'].read()
        except ConnectionError:
            pass
        finally:
            retired.put_nowait(writer)

    async def healthy(request, response):
        response.write_body(b'alive')
        await response.finish()

    if upgrade:
        server.register_upgrade('/stream', streaming)
    else:
        server.register('exact', '/stream', streaming)
    server.register('exact', '/healthy', healthy)
    await server.start()
    try:
        for index in range(3):
            reader, writer = await asyncio.open_connection('127.0.0.1', server.port)
            headers = 'Connection: Upgrade\r\nUpgrade: probe\r\n' if upgrade else ''
            writer.write(('GET /stream HTTP/1.1\r\nHost: local\r\n' + headers + '\r\n').encode('ascii'))
            await writer.drain()
            owned_writer = await asyncio.wait_for(entered.get(), 5)
            if os.name == 'nt':
                assert isinstance(owned_writer.transport._sock, OwnedSocket)
            await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5)
            client_socket = writer.get_extra_info('socket')
            client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                struct.pack('HH' if os.name == 'nt' else 'ii', 1, 0))
            writer.transport.abort()
            assert await asyncio.wait_for(retired.get(), 5) is owned_writer
            try:
                await asyncio.wait_for(owned_writer.wait_closed(), 5)
            except ConnectionError:
                pass
            await writer.wait_closed()
        reader, writer = await asyncio.open_connection('127.0.0.1', server.port)
        writer.write(b'GET /healthy HTTP/1.1\r\nHost: local\r\n\r\n')
        await writer.drain()
        response = await asyncio.wait_for(reader.read(), 5)
        assert response.endswith(b'alive') and response.startswith(b'HTTP/1.1 200')
        writer.close()
        await writer.wait_closed()
        await server.stop()
        assert not server._connections and not server._upgraded_sockets
        assert errors == []
    finally:
        await server.stop()
        loop.set_exception_handler(previous)
        await ctx.fiber.dispose()
        await ctx.fiber.await_settled()
