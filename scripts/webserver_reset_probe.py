import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import struct
import sys


def validate(report, root=None):
    if (not isinstance(report, dict) or set(report) != {'python', 'platform', 'root', 'module', 'observations'}
            or report.get('python') != '3.8.10' or report.get('platform') != 'win32'):
        raise ValueError('webserver reset requires the Windows Python 3.8.10 runtime')
    actual_root = Path(report.get('root', '')).resolve()
    if root is not None and actual_root != Path(root).resolve():
        raise ValueError('webserver reset imported a different product')
    if Path(report.get('module', '')).resolve() != actual_root / 'dsh/host/webserver/socket_server.py':
        raise ValueError('webserver reset module is outside the product')
    expected = [
        dict(mode='http-stream', resets=3, owned=True, alive=True, retired=True, errors=[]),
        dict(mode='upgrade', resets=3, owned=True, alive=True, retired=True, errors=[])]
    if json.dumps(report.get('observations'), sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise ValueError('webserver reset observations are incomplete')


async def observe(upgrade):
    from dsh.cordis.context import Context
    from dsh.host.webserver.socket_server import OwnedSocket
    from dsh.host.webserver.webserver import WebServerService
    context = Context()
    server = WebServerService(context, port=0)
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    errors = []
    loop.set_exception_handler(lambda active_loop, value: errors.append(str(value.get('exception', value))))
    entered = asyncio.Queue()
    retired = asyncio.Queue()

    async def stream(request, response):
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

    async def answer(request, response):
        response.write_body(b'alive')
        await response.finish()

    if upgrade:
        server.register_upgrade('/stream', stream)
    else:
        server.register('exact', '/stream', stream)
    server.register('exact', '/healthy', answer)
    await server.start()
    ownership = []
    try:
        for index in range(3):
            reader, writer = await asyncio.open_connection('127.0.0.1', server.port)
            try:
                headers = 'Connection: Upgrade\r\nUpgrade: probe\r\n' if upgrade else ''
                writer.write(('GET /stream HTTP/1.1\r\nHost: local\r\n' + headers + '\r\n').encode('ascii'))
                await writer.drain()
                owned_writer = await asyncio.wait_for(entered.get(), 5)
                ownership.append(isinstance(owned_writer.transport._sock, OwnedSocket))
                await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5)
                writer.get_extra_info('socket').setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                    struct.pack('HH' if os.name == 'nt' else 'ii', 1, 0))
                writer.transport.abort()
                assert await asyncio.wait_for(retired.get(), 5) is owned_writer
                try:
                    await asyncio.wait_for(owned_writer.wait_closed(), 5)
                except ConnectionError:
                    pass
            finally:
                writer.close()
                await writer.wait_closed()
        reader, writer = await asyncio.open_connection('127.0.0.1', server.port)
        try:
            writer.write(b'GET /healthy HTTP/1.1\r\nHost: local\r\n\r\n')
            await writer.drain()
            result = await asyncio.wait_for(reader.read(), 5)
            alive = result.startswith(b'HTTP/1.1 200') and result.endswith(b'alive')
        finally:
            writer.close()
            await writer.wait_closed()
        await server.stop()
        return dict(mode='upgrade' if upgrade else 'http-stream', resets=3,
            owned=all(ownership), alive=alive,
            retired=not server._connections and not server._upgraded_sockets, errors=errors)
    finally:
        await server.stop()
        loop.set_exception_handler(previous)
        await context.fiber.dispose()
        await context.fiber.await_settled()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--output', required=True)
    arguments = parser.parse_args()
    root = Path(arguments.root).resolve()
    sys.path.insert(0, str(root))
    import dsh.host.webserver.socket_server as provider

    async def run():
        return [await observe(False), await observe(True)]

    report = dict(root=str(root), module=str(Path(provider.__file__).resolve()),
        python=sys.version.split()[0], platform=sys.platform, observations=asyncio.run(run()))
    validate(report, root)
    Path(arguments.output).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
