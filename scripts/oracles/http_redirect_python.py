import argparse
import asyncio
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path)
parser.add_argument('--output', type=Path, required=True)
options = parser.parse_args()
root = (options.root or Path(__file__).resolve().parents[2]).resolve()
sys.path.insert(0, str(root))
from dsh.cordis.context import Context
from dsh.cordis.environment import LaunchEnvironmentSnapshot
from dsh.llm.deepseek_api_extensions import DeepSeekLlmApiExtensionRegistry
from dsh.llm.llm_deepseek import DeepSeekAdapter
from dsh.llm.stream_bridge import iter_chunks
from dsh.llm.http_stream import open_stream

FIXTURES = [dict(name=origin + '-' + str(status), origin=origin, status=status, hops=1)
            for origin in ('same', 'cross') for status in (301, 302, 303, 307, 308)] + [
    dict(name='same-307-twenty', origin='same', status=307, hops=20),
    dict(name='same-307-twenty-one', origin='same', status=307, hops=21),
    dict(name='same-307-loop', origin='same', status=307, hops=30, loop=True),
    dict(name='cross-back-307', origin='cross-back', status=307, hops=2),
    dict(name='rewrite-then-preserve', origin='same', status=302, hops=2, second=307),
]
FIXTURES += [dict(name='raw-' + origin + '-POST-' + str(status), origin=origin, status=status, hops=1, method='POST')
             for origin in ('same', 'cross') for status in (302, 307)]
FIXTURES += [dict(name='raw-same-PUT-' + str(status), origin='same', status=status, hops=1, method='PUT')
             for status in (301, 303, 307)]
FIXTURES += [dict(name='raw-same-HEAD-303', origin='same', status=303, hops=1, method='HEAD')]
FIXTURES += [dict(name='raw-' + name, origin=origin, status=307, hops=1, method='POST', **{flag: True})
             for name, origin, flag in [('same-credentials', 'same', 'credentials'), ('cross-credentials', 'cross', 'credentials'),
                                       ('unsupported-protocol', 'same', 'unsupported'), ('relative-fragment', 'same', 'relative'),
                                       ('abort-before-follow', 'same', 'abort'), ('stalled-redirect-body', 'same', 'stalled')]]


async def observe(fixture):
    requests, servers, threads, ports = [], [], [], []
    signal = threading.Event()

    def handler(origin):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *arguments):
                pass

            def receive(self):
                raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                names = [
                    'authorization', 'content-type', 'x-deepseek-harness-user-id',
                    'x-deepseek-harness-session-id', 'x-deepseek-harness-compact']
                if fixture.get('method'):
                    names += ['proxy-authorization', 'cookie', 'content-encoding', 'content-language', 'content-location']
                headers = {name: self.headers[name] for name in names if name in self.headers}
                requests.append(dict(origin=origin, method=self.command, path=self.path, headers=headers,
                                     body=json.loads(raw) if raw else None))
                if fixture.get('method'):
                    requests[-1]['hostOverride'] = self.headers.get('host') == 'fixture-host'
                if len(requests) <= fixture['hops']:
                    destination = 1 if fixture['origin'] == 'cross' else (
                        (1 if len(requests) == 1 else 0) if fixture['origin'] == 'cross-back' else 0)
                    target = '/chat/completions' if fixture.get('loop') else '/redirect/' + str(len(requests))
                    self.send_response(fixture['second'] if len(requests) == 2 and fixture.get('second') else fixture['status'])
                    location = ('ftp://127.0.0.1:1/resource' if fixture.get('unsupported') else
                                '../redirect/one?query=hello world#fragment' if fixture.get('relative') else
                                'http://{}127.0.0.1:{}{}'.format('fixture:credential@' if fixture.get('credentials') else '',
                                                               ports[destination], target))
                    if fixture.get('abort'):
                        signal.set()
                    self.send_header('Location', location)
                    payload = b''
                else:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    payload = b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
                self.send_header('Content-Length', '999999' if fixture.get('stalled') and len(requests) == 1 else str(len(payload)))
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(payload)

            do_POST = receive
            do_GET = receive
            do_PUT = receive
            do_HEAD = receive
        return Handler

    for origin in (0, 1):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(origin))
        thread = threading.Thread(target=server.serve_forever, kwargs=dict(poll_interval=0.01), daemon=True)
        thread.start()
        ports.append(server.server_port)
        servers.append(server)
        threads.append(thread)
    ctx = Context()
    ctx.set_service('launchEnvironment', LaunchEnvironmentSnapshot([
        dict(source='process', values=dict(DEEPSEEK_API_KEY='fixture-key'))]))
    await ctx.plugin(DeepSeekLlmApiExtensionRegistry)
    adapter = DeepSeekAdapter(ctx, dict(baseURL='http://127.0.0.1:{}'.format(ports[0]), streamIdleTimeoutMs=3000))
    adapter.user_id = 'fixture-user'
    row = dict(name=fixture['name'], requests=requests, chunks=[])
    reader = iter_chunks(adapter.stream(dict(model='model', messages=[dict(role='user', content=[dict(type='text', text='hello')])],
                                           sessionId='fixture-session', purpose='compaction')))
    try:
        if fixture.get('method'):
            def read_raw():
                request = urllib.request.Request('http://127.0.0.1:{}/chat/completions'.format(ports[0]),
                    method=fixture['method'], data=None if fixture['method'] == 'HEAD' else b'{"probe":1}',
                    headers={'Authorization': 'Bearer fixture-key', 'Proxy-Authorization': 'fixture-proxy',
                             'Cookie': 'fixture-cookie', 'Host': 'fixture-host', 'Content-Type': 'application/json',
                             'Content-Encoding': 'identity', 'Content-Language': 'en', 'Content-Location': 'fixture-location'})
                with open_stream(request, signal, 3000) as (response, chunks):
                    row['status'] = response.status
                    row['text'] = b''.join(chunks).decode('utf-8')
            await asyncio.get_running_loop().run_in_executor(None, read_raw)
        else:
            async for chunk in reader:
                row['chunks'].append(chunk)
    except Exception as error:
        row['error'] = dict(code=(getattr(error, 'code', None) if getattr(error, 'code', None) == 'ABORTED' else 'TRANSPORT')
                           if fixture.get('method') else getattr(error, 'code', None), status=getattr(error, 'status', None))
    finally:
        await reader.aclose()
        await adapter.close()
        await ctx.fiber.dispose()
        for server, thread in zip(servers, threads):
            server.shutdown()
            server.server_close()
            thread.join(2)
    return row


async def main():
    rows = [await observe(fixture) for fixture in FIXTURES]
    modules = {}
    for name, module in sorted(sys.modules.items()):
        if not name.startswith('dsh') or not getattr(module, '__file__', None):
            continue
        path = Path(module.__file__).resolve()
        relative = path.relative_to(root).as_posix()
        if not relative.startswith('dsh/') or path.suffix != '.py':
            raise ValueError('runtime module escaped selected root')
        modules[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    options.output.write_text(json.dumps(dict(root=str(root), python=sys.version.split()[0], modules=modules,
                                              rows=rows), ensure_ascii=True, indent=2) + '\n', encoding='utf-8')


asyncio.run(main())
