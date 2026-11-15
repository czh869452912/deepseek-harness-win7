"""Pair concrete bind literals and actual trusted/untrusted TLS lifecycle."""
import asyncio
import json
from pathlib import Path
import socket
import ssl
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe

HOSTS = ['127.0.0.1', '127.8.9.10', '10.1.2.3', '0.1.2.3', '0.0.0.1', '::1', 'fd00::1',
         '::ffff:10.1.2.3', '::ffff:0.1.2.3', '0:0:0:0:0:0:0:1', 'fe80::1%lo',
         '::0.0.0.1', '::0.0.0.1%lo', '::127.0.0.1', '::127.0.0.1%lo',
         '::ffff:127.0.0.1%lo', '::ffff:7f00:1', '0.0.0.0', '::', '::0', '0000::',
         '0::', '0:0:0:0:0:0:0:0', '::0.0.0.0', '::0.0.0.0%lo', '::%lo',
         '::ffff:0.0.0.0', '::ffff:0:0', '::ffff:0000:0000', '0:0:0:0:0:ffff:0:0',
         '0:0:0:0:0:ffff:0.0.0.0', '::ffff:0.0.0.0%eth0', 'localhost', 'example.com',
         '*', '[::]', '[fd00::1]', '10.1.2.3/8', '127.1', '0127.0.0.1', ' 127.0.0.1',
         '::1%bad zone', '::1%', 'FE80:0:0:0:0:0:0:1', '::ffff:127.00.0.1',
         'fe80::1%eth_0', 'fe80::1%eth~0', 'fe80::1%eth:0', 'fe80::1%eth.0', 'fe80::1%eth-0']


async def observe():
    from dsh.cordis import Context
    from dsh.host.webserver.current import CurrentWebServer, CurrentWebServerPlugin, CONFIG
    from dsh.host.webserver.bind import is_wildcard_host, is_loopback_host, normalize_bind_address, bind_url_host
    rows = []
    for host in HOSTS:
        row = dict(name='bind:' + host, wildcard=is_wildcard_host(host), loopback=is_loopback_host(host))
        try: row['config'] = CONFIG(dict(host=host, port=0))['host']
        except Exception as error: row['error'] = str(error)[str(error).find('webserver:'):]
        try: row['normalized'] = normalize_bind_address(host)
        except ValueError: row['normalized'] = None
        row['urlHost'] = bind_url_host(host)
        rows.append(row)
    material = ROOT / 'tests/fixtures/tls'
    tls = dict(certFile=str(material / 'localhost-cert.pem'), keyFile=str(material / 'localhost-key.pem'))
    ctx = Context(); clients = []
    try:
        try: CurrentWebServer(ctx, port=0).getOrigin()
        except ValueError as error: rows.append(dict(name='origin-before-bind', error=str(error)))
        fiber = await ctx.plugin(CurrentWebServerPlugin, dict(host='127.0.0.1', port=0, tls=tls))
        server = ctx.webServer
        server.register(dict(kind='exact', path='/tls', resource=lambda *_: dict(status=200, headers={}, body=b'SECURE')))
        ca = ssl.create_default_context(cafile=tls['certFile'])
        async def connect(context=ca):
            reader, writer = await asyncio.wait_for(asyncio.open_connection('127.0.0.1', server.port, ssl=context, server_hostname='localhost' if context else None), 5)
            clients.append(writer)
            return reader, writer
        async def get(context=ca):
            reader, writer = await connect(context)
            writer.write(b'GET /tls HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n'); await writer.drain()
            raw = await asyncio.wait_for(reader.read(), 2)
            writer.close(); await writer.wait_closed()
            if not raw.startswith(b'HTTP/'):
                raise ValueError('No HTTP response')
            return dict(status=int(raw.split(b' ', 2)[1]), body=raw.split(b'\r\n\r\n', 1)[1].decode())
        rows.append(dict(name='trusted-tls', protocol=server.protocol, origin=server.getOrigin().replace(str(server.port), 'PORT'), response=await get()))
        try: await get(ssl.create_default_context())
        except (OSError, ValueError): rows.append(dict(name='untrusted-tls', rejected=True))
        try: await get(None)
        except (OSError, ValueError): rows.append(dict(name='plaintext-to-tls', rejected=True))
        raw_reader, raw_writer = await connect(None)
        # A pending handshake must not prevent another connection being accepted.
        rows.append(dict(name='parallel-handshake', response=await get()))
        idle_reader, idle_writer = await connect()
        async def upgrade(request, writer):
            writer.write(b'HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: test\r\n\r\n'); await writer.drain()
            await request['reader'].read()
        server.register_upgrade('/upgrade', upgrade)
        up_reader, up_writer = await connect()
        up_writer.write(b'GET /upgrade HTTP/1.1\r\nHost: localhost\r\nConnection: Upgrade\r\nUpgrade: test\r\n\r\n'); await up_writer.drain()
        header = await asyncio.wait_for(up_reader.readuntil(b'\r\n\r\n'), 2)
        rows.append(dict(name='tls-upgrade', status=int(header.split(b' ')[1])))
        await asyncio.wait_for(fiber.dispose(), 2)
        closed = []
        for reader in (raw_reader, idle_reader, up_reader):
            try: closed.append(await asyncio.wait_for(reader.read(), 2) == b'')
            except OSError: closed.append(True)
        rows.append(dict(name='tls-unload', closed=closed))
        try: await connect()
        except OSError: rows.append(dict(name='listener-retired', rejected=True))
        plain = await ctx.plugin(CurrentWebServerPlugin, dict(host='127.0.0.1', port=0, tls=None))
        server = ctx.webServer
        server.register(dict(kind='exact', path='/tls', resource=lambda *_: dict(status=200, headers={}, body=b'SECURE')))
        rows.append(dict(name='null-tls', protocol=server.protocol, response=await get(None)))
        await plain.dispose()
        return rows
    finally:
        for writer in clients:
            writer.transport.abort()
            try: await writer.wait_closed()
            except OSError: pass
        await ctx.fiber.dispose()


def prepare(output):
    path = output / 'fixture.json'
    path.write_text(json.dumps(dict(hosts=HOSTS, cert=str(ROOT/'tests/fixtures/tls/localhost-cert.pem'), key=str(ROOT/'tests/fixtures/tls/localhost-key.pem'))), encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_web_tls.mts', 'Concrete literal classification/config/origin and actual trusted TLS, untrusted/plaintext refusal, parallel half-open handshake, upgrades and joined teardown, null TLS.',
               [Path(__file__).resolve(), ROOT/'dsh/host/webserver/current.py', ROOT/'dsh/host/webserver/bind.py', ROOT/'dsh/host/webserver/tls.py', ROOT/'dsh/host/webserver/socket_server.py', ROOT/'tests/fixtures/tls/localhost-cert.pem', ROOT/'tests/fixtures/tls/localhost-key.pem'], prepare)
