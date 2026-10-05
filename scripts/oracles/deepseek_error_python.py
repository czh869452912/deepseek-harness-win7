import argparse
import asyncio
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading


SCRIPT_ROOT = Path(__file__).resolve().parents[2]
NAMES = ('http-400', 'http-401', 'http-402', 'http-403', 'http-404', 'http-429', 'http-500', 'http-503',
    'context-overflow', 'quota-explicit', 'rate-header', 'empty', 'invalid-data', 'truncated',
    'extension-failure', 'cancel', 'idle', 'invalid-long-ascii', 'invalid-long-bmp',
    'invalid-split-surrogate', 'invalid-full-surrogate', 'idle-whole-float', 'idle-fraction', 'success')


async def observe(fixture):
    from dsh.cordis.context import Context
    from dsh.cordis.environment import LaunchEnvironmentSnapshot
    from dsh.core.abort import AbortController
    from dsh.llm.deepseek_api_extensions import DeepSeekLlmApiExtensionRegistry
    from dsh.llm.llm_deepseek import DeepSeekAdapter
    from dsh.llm.stream_bridge import iter_chunks

    requests, accepted = [], []
    controller = AbortController()
    loop = asyncio.get_running_loop()
    mode = fixture.get('behavior', 'success')
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *arguments):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            headers = {name: self.headers.get(name) for name in ('authorization',
                'x-deepseek-harness-user-id', 'x-deepseek-harness-session-id', 'x-deepseek-harness-compact')}
            requests.append(dict(body=body, headers={name: value for name, value in headers.items() if value is not None}))
            if mode in ('cancel', 'idle'):
                if mode == 'cancel':
                    loop.call_soon_threadsafe(controller.abort, 'fixture cancellation')
                release.wait(3)
                return
            status = fixture.get('status', 200)
            payload = fixture.get('sse', 'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
            if status != 200:
                payload = json.dumps(dict(error=fixture.get('error', dict(message='failed'))))
            data = payload.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Content-Type', 'text/event-stream' if status == 200 else 'application/json')
            for name, value in fixture.get('headers', {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    ctx = Context()
    ctx.set_service('launchEnvironment', LaunchEnvironmentSnapshot([dict(source='process', values={'DEEPSEEK_API_KEY': 'fixture-key'})]))
    await ctx.plugin(DeepSeekLlmApiExtensionRegistry)
    if fixture.get('extension'):
        def accept():
            accepted.append('accepted')
            raise RuntimeError('fixture acceptance failed')
        ctx.get('deepseekLlmApiExtensions').register('fixture_extension',
            dict(prepare=lambda request: dict(value=dict(version=1), accept=accept)))
    adapter = DeepSeekAdapter(ctx, dict(baseURL='http://127.0.0.1:{}'.format(server.server_port),
        streamIdleTimeoutMs=fixture.get('idleTimeoutMs', 150) if mode == 'idle' else 3000))
    adapter.user_id = 'fixture-user'
    result = dict(name=fixture['id'], chunks=[], requests=requests, accepted=accepted)
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
        if not all(hasattr(error, name) for name in ('name', 'message', 'failure', 'code')):
            raise
        result['error'] = dict(name=error.name, message=error.message, failure=error.failure, code=error.code)
        result['error'].update({name: error.failure[name] for name in ('status', 'providerRetryAfterMs', 'requestId')
            if name in error.failure})
    finally:
        release.set()
        await adapter.close()
        await ctx.fiber.dispose()
        server.shutdown()
        server.server_close()
        thread.join(2)
    return result


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    root = options.root.resolve()
    sys.path.insert(0, str(root))
    fixtures = json.loads((SCRIPT_ROOT / 'scripts/oracles/deepseek-error-fixtures.json').read_text(encoding='utf-8'))
    assert tuple(fixture['id'] for fixture in fixtures) == NAMES
    rows = [await observe(fixture) for fixture in fixtures]
    modules = {}
    for name, module in sorted(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if path and (name == 'dsh' or name.startswith('dsh.')):
            selected = Path(path).resolve()
            modules[selected.relative_to(root).as_posix()] = hashlib.sha256(selected.read_bytes()).hexdigest()
    with options.output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(root), executable=sys.executable, python=sys.version, modules=modules, rows=rows), stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    asyncio.run(main())
