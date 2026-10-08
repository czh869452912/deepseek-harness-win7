"""Source-shaped search/settings cases with actual local Messages HTTP boundaries."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from dsh.boot.plugin_registry import resolve_harness_plugin
from dsh.cordis.context import Context
from dsh.cordis.environment import LaunchEnvironmentSnapshot
from dsh.core.abort import AbortController
from dsh.web.deepseek_search_provider import DeepSeekSearchProvider, map_anthropic_response
from dsh.web.web_search_deepseek import resolve_options
from dsh.web.web_service import WebError, WebService
from test_boot_remote_composition import MemorySettings

ANSWER = {'content': [
    {'type': 'text', 'citations': [{'url': 'https://a.test', 'cited_text': 'first'},
                                 {'url': 'https://a.test', 'cited_text': 'second'}]},
    {'type': 'web_search_tool_result', 'content': [
        {'type': 'web_search_result', 'url': 'https://a.test', 'title': 'A', 'page_age': '2026-02-02'},
        {'type': 'web_search_result', 'url': 'https://b.test'},
        {'type': 'web_search_result', 'url': 'https://a.test', 'title': 'duplicate'},
        {'type': 'web_search_result', 'url': ''},
        {'type': 'web_search_result_error', 'url': 'https://error.test'}]}]}
EXPECTED = {'sources': [{'url': 'https://a.test', 'title': 'A', 'snippet': 'first', 'publishedAt': '2026-02-02'},
                        {'url': 'https://b.test'}], 'truncated': False}


@pytest.fixture
def messages_server():
    observed = []
    entered, release, disconnected = threading.Event(), threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            observed.append(dict(path=self.path, body=body.decode('utf-8'),
                                 headers={key.lower(): value for key, value in self.headers.items()}))
            if self.path.startswith('/redirect-'):
                self.send_response(int(self.path.split('/')[1].split('-')[1]))
                self.send_header('Location', 'http://127.0.0.1:%s/destination/messages' % self.server.server_port)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            status, payload = 200, json.dumps(ANSWER).encode('utf-8')
            if self.path.startswith('/error'):
                status, payload = 503, b'{"error":{"message":"Controlled API failure"}}'
            if self.path.startswith('/malformed'):
                payload = b'not JSON'
            if self.path.startswith('/bom'):
                payload = b'\xef\xbb\xbf' + payload
            if self.path.startswith('/replacement'):
                payload = b'{"content":[{"type":"web_search_tool_result","content":[{"type":"web_search_result","url":"https://\xff.test"}]}]}'
            if self.path.startswith('/nan'):
                payload = b'{"content":[{"type":"web_search_tool_result","content":[]}],"invalid":NaN}'
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            if '/slow' in self.path:
                self.wfile.write(payload[:2]); self.wfile.flush(); entered.set()
                self.connection.settimeout(2)
                try:
                    if self.connection.recv(1) == b'':
                        disconnected.set()
                except OSError:
                    pass
                release.wait(3)
            try:
                self.wfile.write(payload[2:] if '/slow' in self.path else payload)
            except OSError:
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever)
    worker.start()
    yield SimpleNamespace(base='http://127.0.0.1:%s' % server.server_port, observed=observed,
                          entered=entered, release=release, disconnected=disconnected)
    release.set()
    server.shutdown(); server.server_close(); worker.join(timeout=3)
    assert not worker.is_alive()


def options(base, **changes):
    return dict(dict(apiKey='controlled-search-key', baseURL=base, model='controlled-model',
                     apiVersion='2023-06-01', maxTokens=32, maxUses=2), **changes)


@pytest.mark.asyncio
async def test_actual_messages_body_headers_recording_and_web_cap(messages_server):
    records = []
    config = options(messages_server.base, recordRequest=records.append)
    provider = DeepSeekSearchProvider(lambda: config)
    assert provider.available()
    web = WebService()
    web.registerSearchProvider(provider)
    result = await web.search(dict(query='中文 query', maxResults=1))
    assert result == dict(sources=EXPECTED['sources'][:1], truncated=True)
    wire = messages_server.observed[0]
    assert wire['path'] == '/messages'
    body = json.loads(wire['body'])
    assert body == dict(model='controlled-model', max_tokens=32,
                        messages=[dict(role='user', content=[dict(type='text', text='Perform a web search for the query: 中文 query')])],
                        tools=[dict(type='web_search_20250305', name='web_search', max_uses=2)])
    assert records == [dict(endpoint=messages_server.base + '/messages', apiVersion='2023-06-01', body=body)]
    assert 'controlled-search-key' not in json.dumps(records)
    for header, value in {'x-api-key': 'controlled-search-key', 'authorization': 'Bearer controlled-search-key',
                          'anthropic-version': '2023-06-01', 'content-type': 'application/json',
                          'accept': 'application/json', 'user-agent': 'deepseek-harness/0.0.1'}.items():
        assert wire['headers'][header] == value


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 302, 303, 307, 308])
async def test_search_redirect_rejected_before_location_contact(messages_server, status):
    provider = DeepSeekSearchProvider(lambda: options(messages_server.base + '/redirect-%s' % status))
    with pytest.raises(WebError) as caught:
        await provider.search(dict(query='private query'))
    assert caught.value.code == 'WEB_PROVIDER_ERROR'
    assert len(messages_server.observed) == 1
    assert 'destination' not in messages_server.observed[0]['path']


@pytest.mark.asyncio
@pytest.mark.parametrize('path, message', [('/error', 'Controlled API failure'),
                                         ('/malformed', 'DeepSeek returned an unprocessable response body:')])
async def test_search_real_provider_and_decode_errors(messages_server, path, message):
    provider = DeepSeekSearchProvider(lambda: options(messages_server.base + path))
    with pytest.raises(WebError) as caught:
        await provider.search(dict(query='query'))
    assert caught.value.code == 'WEB_PROVIDER_ERROR'
    assert caught.value.message.startswith(message)


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/slow', '/error/slow'])
async def test_abort_mid_body_closes_owned_socket_and_preserves_reason(messages_server, path):
    provider = DeepSeekSearchProvider(lambda: options(messages_server.base + path))
    controller = AbortController()
    reason = RuntimeError('controlled abort')
    task = asyncio.create_task(provider.search(dict(query='query'), controller.signal))
    assert await asyncio.get_running_loop().run_in_executor(None, messages_server.entered.wait, 2)
    controller.abort(reason)
    with pytest.raises(WebError) as caught:
        await asyncio.wait_for(task, 2)
    assert caught.value.code == 'WEB_ABORTED' and caught.value.cause is reason
    assert await asyncio.get_running_loop().run_in_executor(None, messages_server.disconnected.wait, 2)
    assert not controller.signal._listeners
    assert not any(thread.name == 'dsh-http-cancellation' for thread in threading.enumerate())


@pytest.mark.asyncio
async def test_credentials_snapshot_abort_and_late_rejection_observed(messages_server):
    future = asyncio.get_running_loop().create_future()
    controller = AbortController()
    original = options(messages_server.base, apiKey=None, resolveApiKey=lambda: future)
    current = [original]
    provider = DeepSeekSearchProvider(lambda: current[0])
    task = asyncio.create_task(provider.search(dict(query='query'), controller.signal))
    await asyncio.sleep(0)
    current[0] = options('http://invalid-later.test', apiKey='later-key')
    controller.abort('first reason')
    with pytest.raises(WebError) as caught:
        await task
    assert caught.value.code == 'WEB_ABORTED' and caught.value.cause == 'first reason'
    future.set_exception(RuntimeError('late credential rejection'))
    await asyncio.sleep(0)
    assert not messages_server.observed and not controller.signal._listeners


@pytest.mark.asyncio
async def test_settings_live_redaction_detach_and_missing_credentials(monkeypatch, messages_server):
    ctx = Context()
    ctx.set_service('launchEnvironment', LaunchEnvironmentSnapshot([dict(source='process', values={
        'DEEPSEEK_API_KEY': 'ambient-key', 'DEEPSEEK_BASE_URL': 'http://chat-must-not-be-used.test',
        'DEEPSEEK_SEARCH_BASE_URL': messages_server.base})]))
    try:
        await ctx.plugin(WebService)
        settings_owner = await ctx.plugin(MemorySettings)
        plugin_owner = await ctx.plugin(resolve_harness_plugin('@deepseek-ai/dsh-web-search-deepseek'))
        web = ctx.get('web')
        registered = web.search_providers['deepseek-official']
        assert await web.search(dict(query='first')) == EXPECTED
        settings = ctx.get('settings')
        await settings.update('web-search-deepseek', dict(apiKey='literal-secret', model='updated'))
        assert 'literal-secret' not in json.dumps(settings.describe(dict(redactSecrets=True)))
        assert await web.search(dict(query='second')) == EXPECTED
        assert json.loads(messages_server.observed[-1]['body'])['model'] == 'updated'
        assert messages_server.observed[-1]['headers']['x-api-key'] == 'literal-secret'
        assert web.search_providers['deepseek-official'] is registered
        await settings_owner.dispose()
        ctx.set_service('credentials', SimpleNamespace(resolve=lambda ref: None))
        with pytest.raises(WebError) as caught:
            await web.search(dict(query='missing'))
        assert caught.value.code == 'WEB_PROVIDER_CREDENTIAL_MISSING'
        assert len(messages_server.observed) == 2
        await plugin_owner.dispose()
        assert not web.search_providers
    finally:
        await ctx.fiber.dispose()


def test_mapping_uses_first_citation_and_first_result_without_prose_fallback():
    assert map_anthropic_response(ANSWER) == EXPECTED
    with pytest.raises(WebError, match='no web_search_tool_result'):
        map_anthropic_response(dict(content=[dict(type='text', text='prose')]))


@pytest.mark.parametrize('limit', [0, -1, 1.5, True, float('inf')])
def test_invalid_limits_are_unavailable(limit):
    assert not DeepSeekSearchProvider(lambda: options('https://api.test', maxTokens=limit)).available()


@pytest.mark.asyncio
async def test_actual_pinned_source_complete_mapping_availability_and_missing_key(tmp_path, messages_server):
    root = Path(__file__).resolve().parents[1]
    fixture = root / 'tests/fixtures/web-search-deepseek-cases.json'
    output = tmp_path / 'source.json'
    node = shutil.which('node')
    assert node is not None, 'Pinned Node observer must be available'
    assert subprocess.check_output([node, '--version'], encoding='utf-8').strip() == 'v22.22.2'
    def source_state():
        return tuple(subprocess.check_output(['git', '-C', str(root / 'reference')] + args,
                                             encoding='utf-8').strip()
                     for args in (['rev-parse', 'HEAD'], ['status', '--porcelain']))
    before = source_state()
    assert before == ('cd5ef8148158c3a752a658978873241fdf8e2bbc', '')
    environment = dict(os.environ, TSX_TSCONFIG_PATH=str(root / 'reference/tsconfig.json'))
    command = [node, '--import', (root / 'reference/node_modules/tsx/dist/loader.mjs').as_uri(),
               str(root / 'scripts/oracles/web_search_deepseek_source.mjs'), str(root / 'reference'), str(fixture), str(output), messages_server.base]
    result = await asyncio.get_running_loop().run_in_executor(None, lambda: subprocess.run(
        command, cwd=str(root), env=environment, capture_output=True, check=True, timeout=30))
    assert not result.stderr
    source = json.loads(output.read_text(encoding='utf-8'))
    rows = []
    for entry in json.loads(fixture.read_text(encoding='utf-8')):
        try:
            rows.append(dict(name=entry['name'], value=map_anthropic_response(entry['response'])))
        except WebError as error:
            rows.append(dict(name=entry['name'], error=dict(code=error.code, message=error.message)))
    assert rows == source['rows']
    availability = [dict(maxTokens=value, available=DeepSeekSearchProvider(
        lambda value=value: options('https://api.test', maxTokens=value, maxUses=1)).available())
                    for value in [0, -1, 1.5, True, 1, 32]]
    assert availability == source['availability']
    provider = DeepSeekSearchProvider(lambda: options('https://unused.test', apiKey=None, apiKeyEnv='CONTROLLED_KEY'))
    with pytest.raises(WebError) as caught:
        await provider.search(dict(query='never dispatched'))
    assert dict(code=caught.value.code, message=caught.value.message) == source['missing']
    errors = []
    for signal in [None, AbortController().signal]:
        for failure in [RuntimeError('controlled credential failure'), TypeError('controlled credential type')]:
            async def reject():
                raise failure
            provider = DeepSeekSearchProvider(lambda: options('https://unused.test', apiKey=None, resolveApiKey=reject))
            with pytest.raises(WebError) as caught:
                await provider.search(dict(query='never dispatched'), signal)
            assert (caught.value.cause if signal is None else caught.value.cause.cause) is failure
            errors.append(dict(code=caught.value.code, message=caught.value.message))
    assert errors == source['credentialErrors']
    for row in source['decoding']:
        provider = DeepSeekSearchProvider(lambda: options(messages_server.base + row['path']))
        if 'value' in row:
            assert await provider.search(dict(query='controlled decoding')) == row['value']
        else:
            with pytest.raises(WebError) as caught:
                await provider.search(dict(query='controlled decoding'))
            assert caught.value.code == row['error']['code'] == 'WEB_PROVIDER_ERROR'
            assert caught.value.message.startswith('DeepSeek returned an unprocessable response body:')
    assert len(messages_server.observed) == 6
    assert source_state() == before
