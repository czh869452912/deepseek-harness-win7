"""Production Web upload, image receipt admission and cold history."""
import asyncio
import http.client
import json
from io import BytesIO

import pytest
from PIL import Image

from canonical_web_fixture import close_web_context, web_context


@pytest.mark.asyncio
async def test_web_image_upload_reaches_local_model_and_cold_history(tmp_path, monkeypatch):
    monkeypatch.setenv('DSH_ISSUE11_MODEL_KEY', 'local-test-key')
    model_requests = []

    async def serve_model(reader, writer):
        try:
            header = (await reader.readuntil(b'\r\n\r\n')).decode('ascii')
            length = next(int(line.split(':', 1)[1]) for line in header.splitlines()
                          if line.lower().startswith('content-length:'))
            model_requests.append(json.loads(await reader.readexactly(length)))
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n'
                         b'data: {"choices":[{"delta":{"content":"image received"},"finish_reason":"stop"}]}\n\n'
                         b'data: [DONE]\n\n')
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def client(ctx):
        port = ctx.webServer.listened_port

        async def send(method, path, body=None, headers=None):
            def request():
                connection = http.client.HTTPConnection('127.0.0.1', port, timeout=15)
                try:
                    connection.request(method, path, body, headers or {})
                    response = connection.getresponse()
                    return response.status, response.getheader('Set-Cookie'), response.read()
                finally:
                    connection.close()
            return await asyncio.get_running_loop().run_in_executor(None, request)

        status, cookie, _ = await send('GET', '/connect?interactions=answer&token=' +
                                       ctx.connection.browser_auth.launch_token)
        assert status == 302
        cookie = cookie.split(';', 1)[0]

        async def post(path, body, media_type='application/json'):
            status, _, data = await send('POST', '/api/' + path, body, {
                'Content-Type': media_type, 'Cookie': cookie,
            })
            assert status == 200
            return json.loads(data)

        async def rpc(method, **args):
            result = (await post(method, json.dumps(dict(type='client-request',
                rpcId=method, method=method, payload=dict(args=args)))))['result']
            assert result['ok'], result
            return result['value']

        return post, rpc

    home = tmp_path / 'home'
    server = await asyncio.start_server(serve_model, '127.0.0.1', 0)
    ctx = None
    try:
        ctx = await web_context(home)
        post, rpc = await client(ctx)
        endpoint = 'http://127.0.0.1:{}/v1'.format(server.sockets[0].getsockname()[1])
        await rpc('settings/update', ns='llm-pi-ai', patch={'providers': {'fixture': {
            'api': 'openai-completions', 'baseURL': endpoint, 'apiKeyEnv': 'DSH_ISSUE11_MODEL_KEY',
            'models': [{'id': 'vision', 'input': ['text', 'image']}],
        }}})
        sid = (await rpc('session/create', request={'cwd': str(tmp_path)}))['sessionId']
        await rpc('session/selectModel', request={'sessionId': sid, 'provider': 'fixture', 'model': 'vision'})
        image = BytesIO()
        Image.new('RGB', (2, 2), 'red').save(image, format='PNG')
        route = 'session/uploadFileBinary?sessionId=' + sid
        uploaded = await post(route + '&mediaType=image/png', image.getvalue(), 'application/octet-stream')
        assert uploaded['ok'], uploaded
        unsupported = await post(route + '&mediaType=text/plain', b'x', 'application/octet-stream')
        assert unsupported['error']['details']['reason'] == 'UNSUPPORTED_IMAGE_TYPE'
        image_ref = uploaded['value']['image']
        await rpc('session/prompt', request={'sessionId': sid, 'requestId': 'fixture-image', 'mode': 'queue',
            'content': [{'type': 'text', 'text': 'look'}, {'type': 'file', 'receiptId': uploaded['value']['receiptId']}]})

        async def wait_for_reply():
            while True:
                page = await rpc('session/events', request={'address': {'kind': 'session', 'sessionId': sid}})
                if 'image received' in json.dumps(page):
                    return
                await asyncio.sleep(0.025)
        await asyncio.wait_for(wait_for_reply(), 10)
        assert any(request['model'] == 'vision' and 'data:image/png;base64,' in json.dumps(request)
                   for request in model_requests)

        await close_web_context(ctx)
        ctx = None
        ctx = await web_context(home)
        _, rpc = await client(ctx)
        page = await rpc('session/events', request={'address': {'kind': 'session', 'sessionId': sid}})
        assert image_ref['attachmentId'] in json.dumps(page)
        assert 'image received' in json.dumps(page)
    finally:
        if ctx is not None:
            await close_web_context(ctx)
        server.close()
        await server.wait_closed()
