import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dsh.cordis.context import Context
from dsh.cordis.environment import LaunchEnvironmentSnapshot
from dsh.llm.llm_pi_ai import LLMPiAiPlugin
from dsh.llm.llm_service import LlmError, LlmRuntime
from dsh.llm.pi_auth import resolve_api_key
from dsh.settings.settings_file import SettingsFilePlugin


def route(endpoint='http://localhost:1', name='m', **extra):
    return dict(api='openai-completions', baseURL=endpoint, models=[dict(id=name)], **extra)


@pytest.mark.asyncio
async def test_dormant_provider_settings_activate_replace_reject_and_unload(tmp_path):
    ctx = Context()
    await ctx.plugin(LlmRuntime)
    await ctx.plugin(SettingsFilePlugin, dict(path=str(tmp_path / 'settings.yaml'), watch=False))
    plugin = await ctx.plugin(LLMPiAiPlugin)
    llm, settings = ctx.get('llm'), ctx.get('settings')
    try:
        assert llm.list_providers() == []
        assert any(row['provider'] == 'openai' for row in llm.list_configurable_providers())
        await settings.replace('llm-pi-ai', dict(providers=dict(gateway=route(displayName='Gateway'))))
        assert llm.list_providers() == [dict(id='gateway', name='Gateway')]
        assert (await llm.list_models('gateway'))[0]['id'] == 'm'
        await settings.replace('llm-pi-ai', dict(providers=dict(gateway=route(name='next', displayName='Renamed', retryPolicy=dict(mode='always')))))
        assert llm.list_providers()[0]['name'] == 'Renamed'
        assert llm._adapters['gateway']['retryPolicy']['mode'] == 'always'
        with pytest.raises(Exception):
            await settings.replace('llm-pi-ai', dict(providers=dict(gateway=dict(api='anthropic-messages', baseURL='http://localhost', models=[dict(id='m')]))))
        assert (await llm.list_models('gateway'))[0]['id'] == 'next'
        assert 'anthropic-messages' not in (tmp_path / 'settings.yaml').read_text(encoding='utf-8')
        await settings.replace('llm-pi-ai', dict(providers={}))
        assert llm.list_providers() == []
        await plugin.dispose()
        assert llm.list_configurable_providers() == []
        assert 'llm-pi-ai' not in llm._discoveries
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_explicit_missing_credential_never_uses_ambient_other_key():
    ctx = Context()
    ctx.set_service('launchEnvironment', LaunchEnvironmentSnapshot([dict(source='process', values=dict(OPENAI_API_KEY='ambient'))]))
    try:
        assert await resolve_api_key(ctx, 'openai', {}) == 'ambient'
        with pytest.raises(LlmError) as error:
            await resolve_api_key(ctx, 'openai', dict(apiKeyEnv='TENANT_KEY'))
        assert error.value.code == 'MISSING_CREDENTIAL'
        assert await resolve_api_key(ctx, 'custom', {}) is None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_prepared_request_keeps_endpoint_model_and_credential_generation(tmp_path):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append((self.path, body['model'], self.headers['Authorization']))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"done"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    worker.start()
    endpoint = 'http://127.0.0.1:{}'.format(server.server_port)
    ctx = Context()
    ctx.set_service('launchEnvironment', LaunchEnvironmentSnapshot([dict(source='process', values=dict(OLD_KEY='old', NEW_KEY='new'))]))
    await ctx.plugin(LlmRuntime)
    await ctx.plugin(SettingsFilePlugin, dict(path=str(tmp_path / 'settings.yaml'), watch=False))
    await ctx.plugin(LLMPiAiPlugin, dict(providers=dict(gateway=route(endpoint + '/old', name='old-model', apiKeyEnv='OLD_KEY'))))
    try:
        llm, settings = ctx.get('llm'), ctx.get('settings')
        adapter = llm._adapters['gateway']['adapter']
        prepared = await adapter.prepare_call('gateway', 'old-model')
        await settings.replace('llm-pi-ai', dict(providers=dict(gateway=route(endpoint + '/new', name='new-model', apiKeyEnv='NEW_KEY'))))
        request = dict(provider='gateway', model='old-model', messages=[dict(role='user', content=[dict(type='text', text='hello')])])
        chunks = [chunk async for chunk in prepared['stream'](request)]
        assert chunks[-1]['reason'] == dict(kind='stop')
        chunks = [chunk async for chunk in adapter.stream(dict(request, model='new-model'))]
        assert chunks[-1]['reason'] == dict(kind='stop')
        assert requests == [('/old/chat/completions', 'old-model', 'Bearer old'), ('/new/chat/completions', 'new-model', 'Bearer new')]
    finally:
        await ctx.fiber.dispose()
        server.shutdown()
        server.server_close()
        worker.join()


@pytest.mark.asyncio
async def test_unloading_provider_cancels_and_drains_active_http_reader():
    opened, release = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200)
            self.end_headers()
            self.wfile.flush()
            opened.set()
            release.wait(5)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    worker.start()
    ctx = Context()
    await ctx.plugin(LlmRuntime)
    ctx.set_service('launchEnvironment', LaunchEnvironmentSnapshot([dict(source='process', values=dict(TEST_KEY='fixture'))]))
    plugin = await ctx.plugin(LLMPiAiPlugin, dict(providers=dict(gateway=route('http://127.0.0.1:{}'.format(server.server_port), apiKeyEnv='TEST_KEY'))))
    adapter = ctx.get('llm')._adapters['gateway']['adapter']

    async def consume():
        return [chunk async for chunk in adapter.stream(dict(provider='gateway', model='m', messages=[]))]

    task = asyncio.create_task(consume())
    try:
        assert await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(None, opened.wait, 2), 3)
        await asyncio.wait_for(plugin.dispose(), 2)
        assert task.done() and task.cancelled()
        assert adapter.active == {} and ctx.get('llm').list_providers() == []
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await ctx.fiber.dispose()
        server.shutdown()
        server.server_close()
        worker.join()


@pytest.mark.asyncio
async def test_discovery_catalog_precedes_credentials_and_http_listing_is_bounded(monkeypatch):
    from dsh.llm import pi_discovery

    def forbidden():
        raise AssertionError('catalog discovery must not resolve credentials')

    catalog = await pi_discovery.discover_models(dict(provider='openai'), forbidden)
    assert catalog and all('contextWindow' in model for model in catalog)
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append((self.path, self.headers.get('Authorization')))
            body = json.dumps(dict(data=[dict(id='m', display_name='Model', context_length=4096), dict(id=''), None])).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    worker.start()
    try:
        request = dict(provider='custom', baseURL='http://127.0.0.1:{}/v1'.format(server.server_port), apiKey='draft-key')
        assert await pi_discovery.discover_models(request, forbidden) == [dict(id='m', name='Model', contextWindow=4096)]
        assert requests == [('/v1/models', 'Bearer draft-key')]
        monkeypatch.setattr(pi_discovery, 'MAX_RESPONSE_BYTES', 16)
        with pytest.raises(LlmError) as error:
            await pi_discovery.discover_models(request)
        assert error.value.code == 'DISCOVERY_FAILED'
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
