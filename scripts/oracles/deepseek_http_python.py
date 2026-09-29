"""Loopback HTTP observations through the real native Python adapter."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from types import SimpleNamespace

from dsh.cordis.context import Context
from dsh.cordis.environment import LaunchEnvironmentSnapshot
from dsh.llm.deepseek_api_extensions import DeepSeekLlmApiExtensionRegistry
from dsh.llm.llm_deepseek import DeepSeekAdapter
from dsh.llm.stream_bridge import iter_chunks
from dsh.core.abort import AbortController
from dsh.core.session import Session
from dsh.llm.llm_retry import LLMRetryPlugin


async def observe(fixture):
    requests, accepted = [], []
    reads, uploads = [], []
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
            statuses = fixture.get('statuses')
            status = statuses[min(len(requests) - 1, len(statuses) - 1)] if statuses else fixture.get('status', 200)
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
    def read_image(ref, policy, signal):
        reads.append(dict(id=ref['attachmentId'], policy=policy))
        return dict(attachment=ref, variantId=ref['attachmentId'], data=bytes(ref['bytes']),
                    mediaType=ref['mediaType'], bytes=ref['bytes'], width=ref['width'], height=ref['height'],
                    depth='uchar', space='srgb', hasAlpha=True)
    async def upload(version, connection, policy, signal):
        uploads.append(version['attachment']['attachmentId'])
        if fixture.get('filesFail') and len(uploads) >= fixture['filesFail']:
            raise RuntimeError('fixture files unavailable')
        return dict(record=dict(fileId='fixture-file-{}'.format(len(uploads))), uploaded=True)
    async def close_files():
        pass
    if fixture.get('images'):
        ctx.set_service('attachments', SimpleNamespace(read_image_request=read_image, imageHostPath=lambda ref: None))
    adapter = DeepSeekAdapter(ctx, dict(fixture.get('config', {}), baseURL='http://127.0.0.1:{}'.format(server.server_port), streamIdleTimeoutMs=150 if mode == 'idle' else 3000))
    if fixture.get('images'):
        adapter.files = SimpleNamespace(ensure_uploaded=upload, close=close_files)
    adapter.user_id = 'fixture-user'
    result = dict(chunks=[], requests=requests, accepted=accepted)
    session = Session('retry-session')
    if fixture.get('retry'):
        LLMRetryPlugin().apply(ctx)
        result['decisions'] = []
    if fixture.get('images'):
        result.update(reads=reads, uploads=uploads)
    request = dict(model=fixture.get('model', 'model'), messages=fixture.get('messages', [dict(role='user', content=[dict(type='text', text='hello')])]),
                   sessionId='fixture-session', purpose='compaction', signal=controller.signal)
    try:
        for attempt in range(8):
            try:
                reader = iter_chunks(adapter.stream(request))
                try:
                    async for chunk in reader:
                        result['chunks'].append(chunk)
                finally:
                    await reader.aclose()
                break
            except Exception as error:
                if not fixture.get('retry'):
                    raise
                async def no_recovery():
                    return None
                decision = await ctx.waterfall('agent/request-error', dict(agent=SimpleNamespace(session=session), turn=1, step=1,
                    provider='deepseek-official', failure=error.failure, signal=controller.signal,
                    retryPolicy=adapter.provider_retry_policy('deepseek-official')), no_recovery)
                result['decisions'].append(decision)
                if not isinstance(decision, dict) or decision.get('kind') != 'retry':
                    raise
    except Exception as error:
        result['error'] = {name: getattr(error, name) for name in ('code', 'status', 'providerRetryAfterMs', 'requestId')
                           if getattr(error, name, None) is not None}
    finally:
        if fixture.get('retry'):
            result['retryEvents'] = []
            for event in session.events:
                data = {key: value for key, value in event['data'].items() if key != 'retryId'}
                if 'failure' in data:
                    data['failure'] = {key: value for key, value in data['failure'].items() if key != 'message'}
                result['retryEvents'].append(dict(type=event['type'], data=data))
        release.set()
        await adapter.close()
        await ctx.fiber.dispose()
        server.shutdown()
        server.server_close()
        thread.join(2)
    return result
