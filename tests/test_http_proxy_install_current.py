"""Actual process policy, HTTP/TLS hops, cancellation and child consumers."""
import asyncio
import json
import select
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from dsh.host.http_proxy import install_proxy_from_environment, proxy_route_for, requests_session
from dsh.host.http_proxy_policy import PROXY_ENV_NAMES
from dsh.llm.http_stream import open_stream
from dsh.subprocess.local import child_env
from scripts.oracles.http_proxy_current_python import Lookup
from scripts.oracles.http_proxy_install_current_python import execute
from scripts.session_format_oracle import json_equal


CASES = json.loads((Path(__file__).parents[1] / 'scripts/oracles/http_proxy_install_current_cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['case'])
def test_current_install_pair(case):
    assert json_equal(execute(case), case['expected'])


@pytest.fixture
def network(monkeypatch):
    for name in PROXY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    root = Path(__file__).parent / 'fixtures/tls'
    cert = root / 'proxy-test-cert.pem'
    monkeypatch.setenv('SSL_CERT_FILE', str(cert))
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(str(cert), str(root / 'proxy-test-key.pem'))
    state = dict(hops=[], origins=[], release=threading.Event(), entered=threading.Event(), errors=[])

    class Origin(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            state['origins'].append(dict(path=self.path, headers=dict(self.headers)))
            raw = b'ORIGIN'
            self.send_response(200)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_CONNECT(self):
            state['hops'].append(dict(method='CONNECT', path=self.path, headers=dict(self.headers)))
            if self.path.startswith('stall.test:'):
                state['entered'].set()
                state['release'].wait(3)
                return
            if self.path.startswith('tls-stall.test:'):
                self.send_response(200)
                self.end_headers()
                state['entered'].set()
                state['release'].wait(3)
                return
            upstream = socket.create_connection(('127.0.0.1', origin_tls.server_port), timeout=2)
            try:
                self.send_response(200)
                self.end_headers()
                while not state['release'].is_set():
                    readable, _, _ = select.select([self.connection, upstream], [], [], .02)
                    if isinstance(self.connection, ssl.SSLSocket) and self.connection.pending():
                        readable = list(set(readable + [self.connection]))
                    for source in readable:
                        data = source.recv(65536)
                        if not data:
                            return
                        (upstream if source is self.connection else self.connection).sendall(data)
            except (OSError, ValueError):
                pass
            finally:
                upstream.close()

        def do_GET(self):
            state['hops'].append(dict(method='GET', path=self.path, headers=dict(self.headers)))
            raw = b'VIA-PROXY'
            self.send_response(200)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            data = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            state['hops'].append(dict(method='POST', path=self.path, headers=dict(self.headers), body=json.loads(data)))
            raw = b'data: {"choices":[{"delta":{"content":"proxied"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    origin = ThreadingHTTPServer(('127.0.0.1', 0), Origin)
    origin_tls = ThreadingHTTPServer(('127.0.0.1', 0), Origin)
    origin_tls.socket = tls.wrap_socket(origin_tls.socket, server_side=True)
    proxy = ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
    proxy_tls = ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
    proxy_tls.socket = tls.wrap_socket(proxy_tls.socket, server_side=True)
    servers = [origin, origin_tls, proxy, proxy_tls]
    threads = [threading.Thread(target=lambda server=server: server.serve_forever(poll_interval=.01), daemon=True) for server in servers]
    for thread in threads:
        thread.start()
    state.update(origin=origin, origin_tls=origin_tls, proxy=proxy, proxy_tls=proxy_tls)
    try:
        yield state
    finally:
        state['release'].set()
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(2)


@pytest.mark.asyncio
@pytest.mark.parametrize('proxy_tls', [False, True])
@pytest.mark.parametrize('target_tls', [False, True])
@pytest.mark.parametrize('consumer', ['urlopen', 'stream', 'requests'])
async def test_actual_routes_tls_and_credentials(network, proxy_tls, target_tls, consumer):
    proxy = network['proxy_tls' if proxy_tls else 'proxy']
    proxy_url = '%s://user:p%%40ss@localhost:%s' % ('https' if proxy_tls else 'http', proxy.server_port)
    target = 'https://origin.test/probe' if target_tls else 'http://origin.test/probe'
    dispose = await install_proxy_from_environment(Lookup({'HTTP_PROXY': proxy_url}), lambda _: None)
    try:
        if consumer == 'stream':
            with open_stream(urllib.request.Request(target, headers={'Authorization': 'Bearer origin-only'}), idle_timeout_ms=2000) as result:
                body = b''.join(result[1])
        elif consumer == 'requests':
            with requests_session() as session:
                response = session.get(target, headers={'Authorization': 'Bearer origin-only'}, verify=str(Path(__file__).parent / 'fixtures/tls/proxy-test-cert.pem'), timeout=2)
                body = response.content
        else:
            with urllib.request.urlopen(urllib.request.Request(target, headers={'Authorization': 'Bearer origin-only'}), timeout=2) as response:
                body = response.read()
        assert body == (b'ORIGIN' if target_tls else b'VIA-PROXY')
        hop = network['hops'][0]
        assert hop['method'] == ('CONNECT' if target_tls else 'GET')
        assert hop['path'] == ('origin.test:443' if target_tls else target)
        assert hop['headers']['Proxy-Authorization'] == 'Basic dXNlcjpwQHNz'
        if target_tls:
            assert 'Authorization' not in hop['headers']
            assert network['origins'][0]['headers']['Authorization'] == 'Bearer origin-only'
            assert 'Proxy-Authorization' not in network['origins'][0]['headers']
    finally:
        await dispose()


@pytest.mark.asyncio
async def test_actual_loopback_never_hits_proxy_and_active_requests_finish_after_dispose(network):
    dispose = await install_proxy_from_environment(Lookup({'HTTP_PROXY': 'http://localhost:%s' % network['proxy'].server_port}), lambda _: None)
    try:
        direct = 'http://127.0.0.1:%s/direct' % network['origin'].server_port
        with urllib.request.urlopen(direct, timeout=2) as response:
            assert response.read() == b'ORIGIN'
        assert network['hops'] == []
        with open_stream('http://origin.test/probe', idle_timeout_ms=2000) as response:
            await dispose()
            assert b''.join(response[1]) == b'VIA-PROXY'
    finally:
        await dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('cancelled', [False, True])
async def test_connect_stall_keeps_stream_timeout_and_cancellation_owner(network, cancelled):
    from dsh.llm.llm_service import LlmError
    signal = threading.Event()
    dispose = await install_proxy_from_environment(Lookup({'HTTP_PROXY': 'http://127.0.0.1:%s' % network['proxy'].server_port}), lambda _: None)
    canceller = None
    if cancelled:
        def cancel():
            if network['entered'].wait(2):
                signal.set()
        canceller = threading.Thread(target=cancel, daemon=True)
        canceller.start()
    try:
        started = time.monotonic()
        with pytest.raises(LlmError) as error:
            with open_stream('https://stall.test/probe', idle_timeout_ms=2000 if cancelled else 150, signal=signal):
                pytest.fail('stalled CONNECT must not become a successful response')
        assert error.value.code == ('ABORTED' if cancelled else 'TIMEOUT')
        assert time.monotonic() - started < 1
        assert len(network['hops']) == 1
    finally:
        network['release'].set()
        if canceller:
            canceller.join(2)
        await dispose()


@pytest.mark.asyncio
async def test_real_llm_and_child_receive_resolved_policy(network, monkeypatch):
    from dsh.llm.llm_service import LLMService
    proxy_url = 'http://localhost:%s' % network['proxy'].server_port
    monkeypatch.setenv('ALL_PROXY', proxy_url)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'not-for-child')
    dispose = await install_proxy_from_environment(Lookup({'ALL_PROXY': proxy_url}), lambda _: None)
    try:
        chunks = list(LLMService(api_key='origin-only', base_url='http://origin.test').chat_completion_stream([], model='test'))
        assert any(chunk.get('type') == 'text-delta' and chunk.get('text') == 'proxied' for chunk in chunks)
        assert network['hops'][0]['body']['model'] == 'test'
        child = subprocess.run([sys.executable, '-c', 'import os,json; print(json.dumps({k:os.environ.get(k) for k in ["HTTP_PROXY","HTTPS_PROXY","NO_PROXY","NODE_USE_ENV_PROXY","DEEPSEEK_API_KEY"]}))'], env=child_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', timeout=5, check=True)
        values = json.loads(child.stdout)
        assert values['HTTP_PROXY'] == values['HTTPS_PROXY'] == proxy_url
        assert values['NODE_USE_ENV_PROXY'] == '1'
        assert 'localhost' in values['NO_PROXY']
        assert values['DEEPSEEK_API_KEY'] is None
    finally:
        await dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('consumer', ['urlopen', 'stream', 'requests'])
async def test_https_proxy_certificate_is_checked_even_for_http_target(network, monkeypatch, consumer):
    wrong_ca = str(Path(__file__).parent / 'fixtures/tls/localhost-cert.pem')
    monkeypatch.setenv('SSL_CERT_FILE', wrong_ca)
    dispose = await install_proxy_from_environment(Lookup({'HTTP_PROXY': 'https://127.0.0.1:%s' % network['proxy_tls'].server_port}), lambda _: None)
    try:
        with pytest.raises(Exception, match='CERTIFICATE_VERIFY_FAILED|certificate verify failed'):
            if consumer == 'stream':
                with open_stream('http://origin.test/probe', idle_timeout_ms=2000):
                    pytest.fail('untrusted proxy must not admit a response')
            elif consumer == 'requests':
                with requests_session() as session:
                    session.get('http://origin.test/probe', verify=wrong_ca, timeout=2)
            else:
                urllib.request.urlopen('http://origin.test/probe', timeout=2)
        assert network['hops'] == []
    finally:
        await dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('proxy_tls', [False, True])
@pytest.mark.parametrize('cancelled', [False, True])
async def test_origin_tls_stall_inside_tunnel_stays_cancellable(network, proxy_tls, cancelled):
    from dsh.llm.llm_service import LlmError
    signal = threading.Event()
    proxy = network['proxy_tls' if proxy_tls else 'proxy']
    url = '%s://127.0.0.1:%s' % ('https' if proxy_tls else 'http', proxy.server_port)
    dispose = await install_proxy_from_environment(Lookup({'HTTP_PROXY': url}), lambda _: None)
    worker = None
    if cancelled:
        def cancel():
            if network['entered'].wait(2):
                signal.set()
        worker = threading.Thread(target=cancel, daemon=True)
        worker.start()
    try:
        started = time.monotonic()
        with pytest.raises(LlmError) as error:
            with open_stream('https://tls-stall.test/probe', idle_timeout_ms=2000 if cancelled else 200, signal=signal):
                pytest.fail('TLS stall must not return a response')
        assert error.value.code == ('ABORTED' if cancelled else 'TIMEOUT')
        assert network['entered'].is_set()
        assert time.monotonic() - started < 1
    finally:
        network['release'].set()
        if worker:
            worker.join(2)
        await dispose()


@pytest.mark.asyncio
async def test_real_profile_installs_before_first_plugin_and_restores_after_shutdown(network, tmp_path):
    from dsh.boot.profile import init_profile
    from dsh.boot.profile_boot import run_profile
    from dsh.cordis.environment import LaunchEnvironmentSnapshot
    directory = tmp_path / 'profiles/rescue'
    init_profile(str(directory), [])
    plugin = directory / 'observe.py'
    plugin.write_text('import urllib.request\ndef apply(ctx, config):\n    with urllib.request.urlopen("http://origin.test/boot", timeout=2) as response:\n        ctx.provide("bootProxyObservation", response.read().decode("ascii"))\n', encoding='utf-8')
    (directory / 'cordis.patch.yml').write_text(json.dumps([{'insert': [{'id': 'observe', 'name': str(plugin)}]}]), encoding='utf-8')
    proxy_url = 'http://127.0.0.1:%s' % network['proxy'].server_port
    environment = LaunchEnvironmentSnapshot([{'source': 'user-env', 'path': str(tmp_path / '.env'), 'values': {'HTTP_PROXY': proxy_url}}])
    before = proxy_route_for('http://example.com/')
    result = await asyncio.wait_for(run_profile(dict(profile='rescue', dshHome=str(tmp_path), environment=environment, waitForExit=False)), 10)
    try:
        assert result['ctx'].get('bootProxyObservation') == 'VIA-PROXY'
        assert network['hops'][0]['path'] == 'http://origin.test/boot'
        assert proxy_route_for('http://example.com/')['proxy'] == proxy_url
    finally:
        await asyncio.wait_for(result['shutdown'].shutdown(), 5)
    assert proxy_route_for('http://example.com/') == before


@pytest.mark.asyncio
async def test_failed_profile_restores_policy_and_environment(network, tmp_path):
    from dsh.boot.profile import init_profile
    from dsh.boot.profile_boot import run_profile
    from dsh.cordis.environment import LaunchEnvironmentSnapshot
    directory = tmp_path / 'profiles/rescue'
    init_profile(str(directory), [])
    (directory / 'cordis.patch.yml').write_text('invalid: [yaml', encoding='utf-8')
    proxy_url = 'http://127.0.0.1:%s' % network['proxy'].server_port
    environment = LaunchEnvironmentSnapshot([{'source': 'user-env', 'values': {'HTTP_PROXY': proxy_url}}])
    before = proxy_route_for('http://example.com/')
    with pytest.raises(Exception):
        await asyncio.wait_for(run_profile(dict(profile='rescue', dshHome=str(tmp_path), environment=environment, waitForExit=False)), 10)
    assert proxy_route_for('http://example.com/') == before
