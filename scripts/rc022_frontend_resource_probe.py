"""Pair authenticated static resource reads and Peer-specific boot documents."""
import asyncio
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE = None


def fixture(directory):
    directory.mkdir(parents=True, exist_ok=True)
    files = {'index.html': b'<html><head><script>entry()</script></head><body>shell</body></html>',
             'app.js': b'export {}', 'preview.html': b'<body>preview</body>', 'icon.png': b'PNG', 'blob.bin': bytes([0, 255, 1])}
    for name, data in files.items(): (directory / name).write_bytes(data)
    (directory / 'empty').mkdir()


def project(raw):
    headers = {key: value for key, value in raw.get('headers', {}).items() if key in ('content-type', 'cache-control', 'etag', 'location', 'referrer-policy', 'allow')}
    body = raw.get('body') or b''
    if raw['status'] == 200 and b'__DSH_BOOT_READY__' in body and headers.get('content-type') == 'text/html; charset=utf-8':
        text = body.decode('utf-8')
        def value(name):
            match = re.search(r'globalThis\["' + name + r'"\] = ([\s\S]*?)</script>', text)
            return json.loads(match.group(1)) if match else None
        body = dict(snapshot=value('__DSH_REMOTE_ACCESS__'), browser=value('__BROWSER__'),
                    base=re.findall(r'<base href="([^"]*)">', text),
                    baseFirst=text.index('<base ') < min(text.index('__DSH_REMOTE_ACCESS__'), text.index('early()'), text.index('entry()')),
                    readiness=text.count('__DSH_BOOT_READY__') > 0)
    else:
        body = list(body)
    return dict(status=raw['status'], headers=headers, body=body)


async def observe(workspace=None):
    global WORKSPACE
    owned = tempfile.TemporaryDirectory(prefix='frontend-resource-') if workspace is None and WORKSPACE is None else None
    directory = Path(workspace or WORKSPACE or owned.name)
    fixture(directory)
    from dsh.cordis import Context
    from dsh.host.webserver.current import CurrentWebServer
    from dsh.host.connection.plugin_current import AuthorizedConnectionPlugin
    from dsh.host.connection.peer import Peer
    from dsh.host.frontend_static.current import CurrentFrontendStatic
    from dsh.typert.remote_access import RemoteAccessService
    ctx = Context(); records = {}; rows = []; server = CurrentWebServer(ctx, port=0)
    def modify(key, mutate):
        value = mutate(records.get(key))
        if value is not None: records[key] = value
        return records.get(key)
    ctx.set_service('credentials', SimpleNamespace(modify_record=modify))
    ctx.set_service('webServer', server)
    await ctx.plugin(AuthorizedConnectionPlugin); await ctx.plugin(RemoteAccessService)
    ctx.remoteAccess.registerPolicy('guest', SimpleNamespace(bindings=lambda principal: [dict(resource=dict(kind='session', id='visible'), role=dict(actions=['notes/read', 'event:notice']))]))
    peer = Peer(ctx, dict(principal=dict(kind='guest')))
    ctx.on('webserver/index-inject', lambda table, who: table.append(dict(kind='global', name='__BROWSER__', value=who is ctx.connection.browserPeer)))
    server.tap_index(lambda html: html.replace('<head>', '<head><script>early()</script>'))
    frontend = await ctx.plugin(CurrentFrontendStatic, dict(distIndex=str(directory / 'index.html')))
    async def http(path, method='GET', cookie=None, etag=None, host=None):
        reader, writer = await asyncio.open_connection('127.0.0.1', server.listened_port)
        try:
            headers = method + ' ' + path + ' HTTP/1.1\r\nHost: ' + (host or '127.0.0.1:' + str(server.listened_port)) + '\r\nConnection: close\r\n'
            if cookie: headers += 'Cookie: ' + cookie + '\r\n'
            if etag: headers += 'If-None-Match: ' + etag + '\r\n'
            writer.write(headers.encode('utf-8') + b'\r\n'); await writer.drain()
            raw = await asyncio.wait_for(reader.read(), 2)
            head, body = raw.split(b'\r\n\r\n', 1); lines = head.decode('utf-8').split('\r\n')
            return dict(status=int(lines[0].split()[1]), headers={key.lower(): value.strip() for key, value in (line.split(':', 1) for line in lines[1:])}, body=body)
        finally:
            writer.close(); await writer.wait_closed()
    async def read(path, method='GET', etag=None):
        return await server.readResource(dict(url='http://reader.invalid' + path, method=method, headers={'if-none-match': etag} if etag else {}), peer)
    try:
        await server.start()
        rows.append(dict(name='anonymous-index', response=project(await http('/'))))
        token = ctx.connection.browser_auth.launch_token
        exchange = await http('/?token=' + token); cookie = exchange['headers']['set-cookie'].split(';')[0]
        rows.append(dict(name='browser-exchange', response=project(exchange), version=cookie.split('=', 1)[1].split('.')[0]))
        for path, method in [('/', 'GET'), ('/index.html', 'GET'), ('/', 'HEAD')]:
            rows.append(dict(name='browser:' + method + ':' + path, response=project(await http(path, method, cookie))))
        for path in ('/', '/index.html'):
            rows.append(dict(name='reader:' + path, response=project(await read(path))))
        rows.append(dict(name='reader-head', response=project(await read('/', 'HEAD'))))
        operator = await http('/connect?token=' + token); api_cookie = operator['headers']['set-cookie'].split(';')[0]
        rows.append(dict(name='api-cookie-index', response=project(await http('/', cookie=api_cookie))))
        rows.append(dict(name='wrong-audience-index', response=project(await http('/', cookie=cookie, host='elsewhere.example'))))
        for path in ('/app.js', '/preview.html', '/icon.png', '/blob.bin', '/empty', '/missing', '/..%2f..%2fsecret', '/bad%', '/bad%00path'):
            rows.append(dict(name='public:' + path, response=project(await http(path))))
        first = await http('/app.js'); etag = first['headers']['etag']
        rows.append(dict(name='revalidated', http=project(await http('/app.js', etag=etag)), reader=project(await read('/app.js', etag=etag)), head=project(await http('/app.js', 'HEAD'))))
        (directory / 'app.js').write_text('export const rebuilt = true', encoding='utf-8')
        rows.append(dict(name='rebuilt', response=project(await http('/app.js', etag=etag))))
        rows.append(dict(name='index-not-cached', response=project(await http('/', cookie=cookie, etag=etag))))
        rows.append(dict(name='methods', http=project(await http('/app.js', 'POST')), reader=project(await read('/app.js', 'POST'))))
        (directory / 'index.html').unlink()
        rows.append(dict(name='index-removed', http=project(await http('/', cookie=cookie)), reader=project(await read('/'))))
        await frontend.dispose()
        rows.append(dict(name='frontend-unload', http=project(await http('/app.js')), reader=project(await read('/app.js'))))
        return rows
    finally:
        await server.stop(); await peer.dispose(); await ctx.fiber.dispose()
        if owned is not None: owned.cleanup()


def prepare(output):
    global WORKSPACE
    source, WORKSPACE = output / 'files/source', output / 'files/native'
    fixture(source)
    path = output / 'fixture.json'
    path.write_text(json.dumps(dict(source=str(source))), encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_frontend_resource.mts', 'Actual static frontend resource, browser v1 exchange versus API v2 rejection, owner/guest Peer-specific rendered index, relative base after transforms, public assets/PNG/binary, exact weak ETags/304/rebuild, invalid paths/methods/missing files and reversible unload.', [Path(__file__).resolve(), ROOT/'dsh/host/frontend_static/current.py', ROOT/'dsh/host/webserver/current.py'], prepare)
