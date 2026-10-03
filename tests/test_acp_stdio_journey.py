import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


ROOT = Path(__file__).resolve().parents[1]


def isolated_environment(home, endpoint=None):
    environment = {name: value for name, value in os.environ.items()
                   if not re.search(r'(?:^|_)(?:API_KEY|API_TOKEN|ACCESS_TOKEN|REFRESH_TOKEN|OAUTH_TOKEN)$', name, re.I)
                   and name.upper() not in ('DSH_HOME', 'PYTHONPATH', 'PYTHONHOME')}
    environment.update(DSH_HOME=str(home), DSH_TELEMETRY_DISABLED='1')
    if endpoint is not None:
        environment.update(DEEPSEEK_API_KEY='fixture-only', DEEPSEEK_BASE_URL=endpoint)
    return environment


class AcpProcess:
    def __init__(self, directory, home, endpoint):
        self.frames = queue.Queue()
        self.observed, self.stderr = [], []
        self.process = subprocess.Popen([sys.executable, str(ROOT / 'dsh.py'), '--profile', 'acp'],
            cwd=str(directory), env=isolated_environment(home, endpoint), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', bufsize=1)
        def read():
            for line in self.process.stdout:
                try:
                    self.frames.put(json.loads(line))
                except ValueError:
                    self.frames.put({'invalid': line})
            self.frames.put({'eof': True})
        self.reader = threading.Thread(target=read, daemon=True)
        self.errors = threading.Thread(target=lambda: self.stderr.append(self.process.stderr.read()), daemon=True)
        self.reader.start()
        self.errors.start()

    def send(self, identity, method, params):
        self.raw(json.dumps(dict(jsonrpc='2.0', method=method, params=params,
                                 **({} if identity is None else {'id': identity})), ensure_ascii=False) + '\n')

    def raw(self, value):
        self.process.stdin.write(value)
        self.process.stdin.flush()

    def wait(self, predicate):
        while True:
            try:
                frame = self.frames.get(timeout=12)
            except queue.Empty:
                raise AssertionError('ACP response timed out: ' + ''.join(self.stderr))
            assert 'invalid' not in frame and 'eof' not in frame, (frame, self.stderr)
            self.observed.append(frame)
            if predicate(frame):
                return frame

    def reply(self, identity):
        return self.wait(lambda frame: frame.get('id') == identity)

    def finish(self):
        self.process.stdin.close()
        assert self.process.wait(timeout=10) == 0, self.stderr
        self.reader.join(2)
        self.errors.join(2)
        assert self.stderr == ['']

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=3)
        self.reader.join(2)
        self.errors.join(2)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()


@pytest.fixture
def local_model():
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            chunk = {'choices': [{'delta': {'reasoning_content': 'local thought', 'content': 'ACP journey 中文'},
                                  'finish_reason': 'stop'}]}
            body = ('data: ' + json.dumps(chunk, ensure_ascii=False) + '\n\ndata: [DONE]\n\n').encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:{}'.format(server.server_port), requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_actual_acp_profile_stdio_output_and_new_process_durable_resume(tmp_path, local_model):
    endpoint, requests = local_model
    home = tmp_path / 'home'
    child = AcpProcess(tmp_path, home, endpoint)
    try:
        child.send(1, 'initialize', {'protocolVersion': 1})
        initialized = child.reply(1)['result']
        assert initialized['protocolVersion'] == 1
        assert initialized['agentCapabilities']['sessionCapabilities'] == {'close': {}, 'list': {}, 'resume': {}}
        assert 'mcpCapabilities' not in initialized['agentCapabilities']
        child.send(2, 'session/new', {'cwd': str(tmp_path), 'mcpServers': []})
        created = child.reply(2)['result']
        session_id = created['sessionId']
        option = created['configOptions'][0]
        child.send(3, 'session/set_config_option', {'sessionId': session_id, 'configId': 'model', 'value': option['currentValue']})
        assert child.reply(3)['result']['configOptions'][0]['currentValue'] == option['currentValue']
        child.send(4, 'session/prompt', {'sessionId': session_id, 'prompt': [{'type': 'text', 'text': 'say hello 中文'}]})
        assert child.reply(4)['result'] == {'stopReason': 'end_turn'}
        updates = [frame['params'] for frame in child.observed if frame.get('method') == 'session/update']
        assert [value['update']['sessionUpdate'] for value in updates] == ['agent_thought_chunk', 'agent_message_chunk']
        assert all(value['sessionId'] == session_id for value in updates)
        assert updates[-1]['update']['content'] == {'type': 'text', 'text': 'ACP journey 中文'}
        assert child.observed[-1]['id'] == 4
        child.send(5, 'session/close', {'sessionId': session_id})
        assert child.reply(5)['result'] == {}
        child.send(6, 'session/list', {})
        assert child.reply(6)['result']['sessions'] == [{'sessionId': session_id, 'cwd': str(tmp_path)}]
        child.finish()
    finally:
        child.close()
    assert len(requests) == 1 and requests[0]['model'] == 'deepseek-v4-flash'
    child = AcpProcess(tmp_path, home, endpoint)
    try:
        child.send(1, 'initialize', {'protocolVersion': 1})
        child.reply(1)
        child.send(2, 'session/resume', {'sessionId': session_id, 'cwd': str(tmp_path)})
        assert child.reply(2)['result']['configOptions'][0]['currentValue'] == option['currentValue']
        assert not any(frame.get('method') == 'session/update' for frame in child.observed)
        child.send(3, 'session/prompt', {'sessionId': session_id, 'prompt': [{'type': 'text', 'text': 'continue'}]})
        assert child.reply(3)['result'] == {'stopReason': 'end_turn'}
        child.finish()
    finally:
        child.close()
    assert len(requests) == 2
    assert any(message.get('role') == 'assistant' and 'ACP journey 中文' in str(message) for message in requests[1]['messages'])


@pytest.mark.parametrize('argument,code', [('--help', 0), ('--unknown', 1), ('extra', 1)])
def test_canonical_acp_launcher_help_and_errors_exit_without_protocol(tmp_path, argument, code):
    result = subprocess.run([sys.executable, str(ROOT / 'dsh.py'), '--profile', 'acp', argument],
        cwd=str(tmp_path), env=isolated_environment(tmp_path / 'home'), input='', capture_output=True,
        encoding='utf-8', timeout=15)
    assert result.returncode == code, result.stdout + result.stderr
    if code == 0:
        assert 'dsh --profile acp' in result.stdout and result.stderr == ''
    else:
        assert 'error:' in result.stderr and result.stdout == ''
    assert '"jsonrpc"' not in result.stdout and 'Traceback' not in result.stderr


@pytest.mark.parametrize('payload,error', [('{', {'code': -32700, 'message': 'Parse error'}),
                                         ('42', {'code': -32600, 'message': 'Invalid request', 'data': 42})])
def test_buffered_preboot_eof_flushes_unterminated_protocol_error(tmp_path, local_model, payload, error):
    endpoint, requests = local_model
    child = AcpProcess(tmp_path, tmp_path / 'home', endpoint)
    try:
        child.raw(payload)
        child.finish()
        assert child.frames.get(timeout=1) == {'jsonrpc': '2.0', 'id': None, 'error': error}
        assert child.frames.get(timeout=1) == {'eof': True}
        assert not requests
    finally:
        child.close()


def test_stdio_schema_and_business_rejections_keep_connection_live_without_model_calls(tmp_path, local_model):
    endpoint, requests = local_model
    child = AcpProcess(tmp_path, tmp_path / 'home', endpoint)
    try:
        child.send(1, 'initialize', {'protocolVersion': True})
        assert child.reply(1)['error'] == {'code': -32602, 'message': 'Invalid params', 'data': {
            '_errors': [], 'protocolVersion': {'_errors': ['Invalid input: expected number, received boolean']}}}
        child.send(2, 'session/new', {'cwd': str(tmp_path)})
        assert child.reply(2)['error']['data']['mcpServers'] == {'_errors': ['Required value is missing']}
        child.send(3, 'session/close', {'sessionId': 'absent'})
        assert child.reply(3)['error'] == {'code': -32602, 'message': 'Invalid params: unknown session: absent'}
        child.send(4, 'unknown', {})
        assert child.reply(4)['error'] == {'code': -32601, 'message': '"Method not found": unknown', 'data': {'method': 'unknown'}}
        child.send(5, 'session/list', {})
        assert child.reply(5)['result'] == {'sessions': []}
        child.finish()
        assert not requests
    finally:
        child.close()


@pytest.fixture
def held_model():
    requests, release, admitted = [], threading.Event(), threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(value)
            prompts = [str(message.get('content', '')) for message in value['messages']
                       if message.get('role') == 'user' and any(text in str(message.get('content', ''))
                       for text in ('hold first', 'hold on EOF', 'finish second', 'continue second', 'continue after EOF'))]
            held = bool(prompts) and any(text in prompts[-1] for text in ('hold first', 'hold on EOF'))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            chunk = {'choices': [{'delta': {'content': 'admitted'}, 'finish_reason': None}]}
            try:
                self.wfile.write(('data: ' + json.dumps(chunk) + '\n\n').encode('utf-8'))
                self.wfile.flush()
                if held:
                    admitted.set()
                    release.wait(25)
                self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:{}'.format(server.server_port), requests, admitted
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.mark.parametrize('cancellation', ['session/cancel', '$/cancel_request'])
def test_real_process_concurrent_sessions_cancel_only_owned_request(tmp_path, held_model, cancellation):
    endpoint, requests, admitted = held_model
    child = AcpProcess(tmp_path, tmp_path / 'home', endpoint)
    try:
        identities = []
        for identity in (1, 2):
            child.send(identity, 'session/new', {'cwd': str(tmp_path), 'mcpServers': []})
            identities.append(child.reply(identity)['result']['sessionId'])
        child.send(10, 'session/prompt', {'sessionId': identities[0], 'prompt': [{'type': 'text', 'text': 'hold first'}]})
        assert admitted.wait(10), 'first Session did not enter actual HTTP stream'
        child.send(11, 'session/prompt', {'sessionId': identities[1], 'prompt': [{'type': 'text', 'text': 'finish second'}]})
        assert child.reply(11)['result'] == {'stopReason': 'end_turn'}
        assert not any(frame.get('id') == 10 for frame in child.observed)
        child.send(None, cancellation, {'sessionId': identities[0]} if cancellation == 'session/cancel' else {'requestId': 10})
        assert child.reply(10)['result'] == {'stopReason': 'cancelled'}
        child.send(12, 'session/close', {'sessionId': identities[0]})
        assert child.reply(12)['result'] == {}
        child.send(13, 'session/prompt', {'sessionId': identities[1], 'prompt': [{'type': 'text', 'text': 'continue second'}]})
        assert child.reply(13)['result'] == {'stopReason': 'end_turn'}
        child.finish()
        assert len(requests) == 3
    finally:
        child.close()


def test_real_process_eof_cancels_active_turn_and_reopens_durable_session(tmp_path, held_model):
    endpoint, requests, admitted = held_model
    home = tmp_path / 'home'
    child = AcpProcess(tmp_path, home, endpoint)
    try:
        child.send(1, 'session/new', {'cwd': str(tmp_path), 'mcpServers': []})
        session_id = child.reply(1)['result']['sessionId']
        child.send(2, 'session/prompt', {'sessionId': session_id, 'prompt': [{'type': 'text', 'text': 'hold on EOF'}]})
        assert admitted.wait(10), 'active turn did not enter actual HTTP stream'
        started = time.monotonic()
        child.finish()
        assert time.monotonic() - started < 10
        assert child.frames.get(timeout=1) == {'eof': True}
    finally:
        child.close()
    child = AcpProcess(tmp_path, home, endpoint)
    try:
        child.send(3, 'session/resume', {'sessionId': session_id, 'cwd': str(tmp_path)})
        assert 'configOptions' in child.reply(3)['result']
        child.send(4, 'session/prompt', {'sessionId': session_id, 'prompt': [{'type': 'text', 'text': 'continue after EOF'}]})
        assert child.reply(4)['result'] == {'stopReason': 'end_turn'}
        child.finish()
        assert len(requests) == 2
    finally:
        child.close()
