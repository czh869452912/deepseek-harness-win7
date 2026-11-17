import asyncio
import json
from types import SimpleNamespace

import pytest

from dsh.boot.plugin_market_022 import CurrentPluginMarket
from dsh.cordis import Context
from dsh.typert.dispatch import original_of
from dsh.util.plugin_detail import DetailFailure
from scripts.rc022_market_remote_probe import observe_fixture


@pytest.mark.asyncio
async def test_detail_remote_file_readers_and_reversible_image_route(tmp_path):
    rows = await observe_fixture(tmp_path/'cache')
    assert len(rows) == 18
    assert rows[0]['value']['origin'] == 'locale' and rows[0]['value']['markdown'].startswith('# 中文')
    assert rows[0]['fetches'] == rows[1]['fetches'] < rows[2]['fetches']
    assert rows[3]['value']['markdown'] == '# Npm'
    assert rows[4]['value']['markdown'] == '# Private repository'
    assert rows[5]['value']['markdown'] == '# Manifest repository'
    assert rows[7]['value'] == dict(status='none')
    assert rows[8]['error']['code'] == 'plugin-market/detail-unavailable'
    assert rows[11]['error']['code'] == 'plugin-market/invalid-query'
    assert rows[12]['status'] == 200 and rows[12]['body'] == [137, 80, 78, 71, 10]
    assert rows[12]['headers']['cache-control'] == 'private, max-age=600'
    assert [row['status'] for row in rows[13:16]] == [404, 404, 400]
    assert rows[-1] == dict(step='disposed', paths=[])


@pytest.mark.asyncio
async def test_market_remote_over_authorized_gateway_http_and_owned_image(tmp_path):
    from dsh.host.webserver.webserver import WebServerService
    from dsh.host.connection.plugin_current import AuthorizedConnectionPlugin
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.typert.remote_access import RemoteAccessService
    from dsh.typert.gateway_transport import AuthorizedGatewayTransport
    from scripts.rc022_rpc_http_probe import decode_response
    ctx = Context(); records, ready = {}, []
    def modify(key, mutate):
        value = mutate(records.get(key))
        if value is not None: records[key] = value
        return records.get(key)
    ctx.provide('credentials', SimpleNamespace(modifyRecord=modify))
    ctx.provide('appReady', SimpleNamespace(onReady=lambda callback: ready.append(callback) or (lambda: None)))
    async def bundles(): return []
    ctx.provide('pluginManager', SimpleNamespace(listBundles=bundles, listVersionExemptions=lambda: dict(exemptions={})))
    await ctx.plugin(CurrentTypertRegistry); await ctx.plugin(RemoteAccessService)
    await ctx.plugin(AuthorizedGatewayTransport, dict(websocketCompression='none'))
    await ctx.plugin(AuthorizedConnectionPlugin)
    server = WebServerService(ctx, host='127.0.0.1', port=0); ctx.set_service('webServer', server)
    fiber = ctx.plugin(CurrentPluginMarket, dict(indexes=['https://market.example/index.json'], detailCacheDir=str(tmp_path/'cache')))
    await fiber
    market = original_of(ctx.pluginMarket)
    # SRC fixture descriptor exercises the carrier and omitted optional argument;
    # the original generated strict artifact is qualified by the browser batch.
    ctx.typert.register(dict(package='market-fixture', face='host', model={}, schemas=[], invocations=[dict(
        id='pluginMarket#readEntryDetail', service='pluginMarket', namespace='pluginMarket', method='readEntryDetail',
        parameters=[dict(name=name, wire=name, source='json', codec=dict(mode='src-json')) for name in ('url', 'name', 'version', 'language', 'options')],
        invocation=dict(kind='direct'), result=dict(mode='src-json'))]))
    async def index(*_):
        return dict(plugins=[dict(name='private', versions=[dict(version='1.0.0', source=dict(type='npm', registry='https://private.example/'))])])
    market.documents.fetch_index = index
    class Image:
        key = 'fixture-image'
        async def read(self, path, maximum, signal): return b'\x89PNG\n'
    document = market.details.found('readme', Image(), 'README.md', '# Image')['document']
    async def http(path, body=None, cookie=None):
        reader, writer = await asyncio.open_connection('127.0.0.1', server.listened_port)
        try:
            data = b'' if body is None else json.dumps(body).encode('utf-8')
            headers = ('GET' if body is None else 'POST')+' '+path+' HTTP/1.1\r\nHost: 127.0.0.1:'+str(server.listened_port)+'\r\nConnection: close\r\n'
            if cookie: headers += 'Cookie: '+cookie+'\r\n'
            if body is not None: headers += 'Content-Type: application/json\r\nContent-Length: '+str(len(data))+'\r\n'
            writer.write(headers.encode('ascii')+b'\r\n'+data); await writer.drain()
            raw = await asyncio.wait_for(reader.read(), 5)
            head, data = raw.split(b'\r\n\r\n', 1); lines = head.decode('latin-1').split('\r\n')
            return dict(status=int(lines[0].split()[1]), headers={key.lower():value.strip() for key, value in (line.split(':', 1) for line in lines[1:])}, body=data)
        finally:
            writer.close(); await writer.wait_closed()
    try:
        async def mounted():
            while server.match('/connect') is None or not ready: await asyncio.sleep(0)
        await asyncio.wait_for(mounted(), 2); await server.start()
        for callback in list(ready): callback()
        path = '/api/plugin-market/detail-file?document='+document+'&path=img/a.png'
        assert (await http(path))['status'] == 401
        exchanged = await http('/connect?token='+ctx.connection.browser_auth.launch_token)
        cookie = exchanged['headers']['set-cookie'].split(';')[0]
        image = await http(path, cookie=cookie)
        assert image['status'] == 200 and image['body'] == b'\x89PNG\n'
        assert image['headers']['cache-control'] == 'private, max-age=600'
        response = await http('/api/pluginMarket/readEntryDetail', dict(type='client-request', rpcId='detail', method='pluginMarket/readEntryDetail',
            payload=dict(args=dict(url='https://market.example/index.json', name='private', version='1.0.0', language='en'))), cookie)
        decoded = decode_response(response)
        assert decoded['status'] == 200 and decoded['body']['result'].get('value') == dict(status='none'), decoded
        await fiber.dispose()
        assert (await http(path, cookie=cookie))['status'] == 404
    finally:
        await server.stop(); await ctx.fiber.dispose()
