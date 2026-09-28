"""Loopback HTTP observations through the real native Python adapter."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

from dsh.cordis.context import Context
from dsh.cordis.environment import LaunchEnvironmentSnapshot
from dsh.llm.deepseek_api_extensions import DeepSeekLlmApiExtensionRegistry
from dsh.llm.llm_deepseek import DeepSeekAdapter
from dsh.llm.stream_bridge import iter_chunks
from dsh.core.abort import AbortController


async def observe(fixture):
    requests, accepted = [], []
    controller = AbortController()
    loop = asyncio.get_running_loop()
    mode = fixture.get('behavior', 'success')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            headers = {name: self.headers.get(name) for name in (
                'authorization', 'x-deepseek-harness-user-id', 'x-deepseek-harness-session-id', 'x-deepseek-harness-compact')}
            requests.append(dict(body=body, headers={k: v for k, v in headers.items() if v is not None}))
            if mode in ('cancel', 'idle'):
                if mode == 'cancel':
                    loop.call_soon_threadsafe(controller.abort, 'fixture cancellation')
                return  # The outer handler keeps the connection open until release.
            status = fixture.get('status', 200)
            payload = fixture.get('sse', 'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
            if status != 200:
                payload = json.dumps(dict(error=fixture.get('error', {'message': 'failed'})))
            data = payload.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Content-Type', 'text/event-stream' if status == 200 else 'application/json')
            for key, value in fixture.get('headers', {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

    # A separate event owns delayed requests, so cancellation evidence does
    # not depend on an arbitrary sleep and server teardown always releases it.
    release = threading.Event()
    original = Handler.do_POST
    def handle(self):
        original(self)
        if mode in ('cancel', 'idle'):
            release.wait(3)
    Handler.do_POST = handle
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    ctx = Context()
    ctx.set_service('launchEnvironment', LaunchEnvironmentSnapshot([{'source': 'process', 'values': {'DEEPSEEK_API_KEY': 'fixture-key'}}]))
    await ctx.plugin(DeepSeekLlmApiExtensionRegistry)
    extension = fixture.get('extension')
    def accept():
        accepted.append('accepted')
        if extension == 'accept-failed':
            raise RuntimeError('fixture acceptance failed')
    if extension:
        ctx.get('deepseekLlmApiExtensions').register('model' if extension == 'collision' else 'fixture_extension',
            {'prepare': lambda request: {'value': {'version': 1}, 'accept': accept}})
    adapter = DeepSeekAdapter(ctx, dict(baseURL='http://127.0.0.1:{}'.format(server.server_port), streamIdleTimeoutMs=150 if mode == 'idle' else 3000))
    adapter.user_id = 'fixture-user'
    result = dict(chunks=[], requests=requests, accepted=accepted)
    request = dict(model='model', messages=[dict(role='user', content=[dict(type='text', text='hello')])],
                   sessionId='fixture-session', purpose='compaction', signal=controller.signal)
    try:
        reader = iter_chunks(adapter.stream(request))
        try:
            async for chunk in reader:
                result['chunks'].append(chunk)
        finally:
            await reader.aclose()
    except Exception as error:
        result['error'] = {name: getattr(error, name) for name in ('code', 'status', 'providerRetryAfterMs', 'requestId')
                           if getattr(error, name, None) is not None}
    finally:
        release.set()
        await adapter.close()
        await ctx.fiber.dispose()
        server.shutdown()
        server.server_close()
        thread.join(2)
    return result
