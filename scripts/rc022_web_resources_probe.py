"""Pair actual HTTP and caller-admitted resource reads on the same route table."""
import asyncio
import gzip
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis import Context
    from dsh.host.webserver.current import CurrentWebServer
    from dsh.host.connection.peer import Peer
    ctx = Context(); server = CurrentWebServer(ctx, port=0, compression='gzip'); rows = []; calls = []; cancelled = []; aborted = []
    peer = Peer(ctx, dict(principal=dict(kind='guest', id='reader')))
    gate = asyncio.Event()
    def resource(name):
        async def respond(request, who):
            calls.append(name)
            value = dict(name=name, url=request['url'], host=request.get('headers', {}).get('host'), peer=None if who is None else who.principal, aborted=request['signal'].aborted)
            return dict(status=200, headers={'content-type': 'application/json', 'x-resource': name}, body=json.dumps(value).encode('utf-8'))
        return respond
    async def handler(request, writer): writer.write_status(209); writer.write_body(b'handler'); await writer.finish()
    async def fail(request, who): raise RuntimeError('resource failed')
    class HeadBody:
        def __aiter__(self): return self
        async def __anext__(self): return b'never-consumed'
        async def aclose(self): cancelled.append('head')
    def head(request, who): return dict(status=202, headers={'x-resource': 'head'}, body=HeadBody())
    async def stream(request, who):
        async def body():
            try:
                yield b'first'
                await asyncio.Event().wait()
            finally:
                aborted.append(request['signal'].aborted)
        return dict(status=200, headers={'content-type': 'application/octet-stream'}, body=body())
    async def slow(request, who):
        async def body():
            await gate.wait()
            yield b'last'
        return dict(status=200, headers={}, body=body())
    async def read(path, method='GET'):
        value = await server.readResource(dict(url='http://untrusted.example' + path, method=method, headers=dict(host='spoof.example')), peer)
        body = value.get('body')
        if isinstance(body, (bytes, bytearray)): body = json.loads(body)
        elif body is None: body = ''
        return dict(status=value['status'], headers=value.get('headers', {}), body=body)
    async def http(path, method='GET', advertised=None, encoding=False):
        reader, writer = await asyncio.open_connection('127.0.0.1', server.listened_port)
        try:
            headers = method + ' ' + path + ' HTTP/1.1\r\nHost: transport.example\r\nConnection: close\r\n'
            if advertised is not None: headers += 'Content-Length: ' + str(advertised) + '\r\n'
            if encoding: headers += 'Accept-Encoding: gzip\r\n'
            writer.write(headers.encode('ascii') + b'\r\n'); await writer.drain()
            raw = await asyncio.wait_for(reader.read(), 1)
            head, body = raw.split(b'\r\n\r\n', 1); lines = head.decode('utf-8').split('\r\n'); headers = {key.lower(): value.strip() for key, value in (line.split(':', 1) for line in lines[1:])}
            if headers.get('content-encoding') == 'gzip': body = gzip.decompress(body)
            return dict(status=int(lines[0].split()[1]), headers={key: value for key, value in headers.items() if key in ('content-type', 'x-resource', 'allow', 'content-encoding')}, body=json.loads(body) if body.startswith(b'{') else body.decode('utf-8'))
        finally:
            writer.close(); await writer.wait_closed()
    try:
        rows.append(dict(name='empty-read', response=await read('/missing')))
        for kind, path, respond in [('exact', '/file', resource('exact')), ('prefix', '/files', resource('prefix')), ('prefix', '/files/deep', resource('deep')), ('exact', '/head', head), ('exact', '/fail', fail), ('exact', '/stream', stream), ('exact', '/slow', slow)]:
            server.register(dict(kind=kind, path=path, resource=respond))
        server.register(dict(kind='exact', path='/files/deep/hide', handler=handler))
        for path in ('/file?x=1', '/files/x', '/files/deep/x', '/files/deep/hide', '/files-not-a-prefix', '/files/deep/../x', '/files/%2e%2e/file'):
            rows.append(dict(name='read:' + path, response=await read(path)))
        rows.append(dict(name='read-post', response=await read('/unmatched', 'POST')))
        rows.append(dict(name='read-head', response=await read('/head', 'HEAD'), cancelled=list(cancelled)))
        try: await read('/fail')
        except Exception as error: rows.append(dict(name='read-failure', error=str(error)))
        fallback = server.registerFallback(dict(resource=resource('fallback')))
        rows.append(dict(name='fallback-read', response=await read('/missing')))
        await server.start()
        for path in ('/file?x=1', '/files/deep/hide', '/files/deep/../x', '/files/%2e%2e/file', '/file;tag', '/missing'):
            rows.append(dict(name='http:' + path, response=await http(path)))
        rows.append(dict(name='http-head', response=await http('/head', 'HEAD'), cancelled=list(cancelled)))
        rows.append(dict(name='gzip-resource', response=await http('/file', encoding=True)))
        rows.append(dict(name='gzip-head', response=await http('/file', 'HEAD', encoding=True)))
        before = len(calls)
        rows.append(dict(name='http-methods', exact=await http('/file', 'POST', 999999), fallback=await http('/missing', 'POST', 999999), calls=len(calls) - before))
        rows.append(dict(name='http-failure', response=await http('/fail')))
        reader, writer = await asyncio.open_connection('127.0.0.1', server.listened_port)
        try:
            writer.write(b'GET /slow HTTP/1.1\r\nHost: x\r\n\r\n'); await writer.drain()
            await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 1)
            early = not gate.is_set(); gate.set()
            tail = await asyncio.wait_for(reader.read(), 1)
            rows.append(dict(name='delayed-headers', headersEarly=early, body=tail.decode('utf-8')))
        finally:
            gate.set(); writer.close(); await writer.wait_closed()
        reader, writer = await asyncio.open_connection('127.0.0.1', server.listened_port)
        try:
            writer.write(b'GET /stream HTTP/1.1\r\nHost: x\r\n\r\n'); await writer.drain()
            raw = await asyncio.wait_for(reader.readuntil(b'first'), 1)
        finally:
            writer.close(); await writer.wait_closed()
        async def retired():
            while not aborted: await asyncio.sleep(.01)
        await asyncio.wait_for(retired(), 1)
        rows.append(dict(name='disconnect', first=raw.endswith(b'first'), cancelled=aborted))
        fallback(); rows.append(dict(name='fallback-unload', response=await read('/missing')))
        return rows
    finally:
        await server.stop(); await peer.dispose(); await ctx.fiber.dispose()


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_web_resources.mts', 'Actual HTTP and in-process resource route precedence, explicit trusted Peer versus absent HTTP Peer, placeholder URL/Host separation, canonical dot paths, method rejection before reading advertised bodies, HEAD body cancellation, thrown resource handling, streaming physical disconnect and fallback unload.', [Path(__file__).resolve(), ROOT/'dsh/host/webserver/current.py', ROOT/'dsh/host/webserver/resources.py', ROOT/'dsh/host/webserver/webserver.py'])
