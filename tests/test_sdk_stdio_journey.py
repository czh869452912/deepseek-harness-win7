"""Canonical launcher, real stdio frames, native HTTP model, and durable Session."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml
import pytest

from dsh.boot.profile import init_profile


@pytest.mark.parametrize('default_profile', [False, True])
def test_sdk_launcher_prompt_notifications_shutdown_and_persistence(tmp_path, default_profile):
    profile = tmp_path / 'home' / 'profiles' / 'sdk-journey'
    init_profile(str(profile), [], 'startup')
    rows = [dict(id=name, name='@deepseek-ai/dsh-' + name) for name in (
        'session', 'tools', 'system-prompt', 'agent', 'agent-loop', 'llm', 'llm-deepseek', 'sdk-app')]
    rows.extend([
        dict(id='persistence', name='@deepseek-ai/dsh-session-persistence-jsonl', config=dict(root=str(tmp_path / 'sessions'))),
        dict(id='rpc', name='@deepseek-ai/dsh-sdk-jsonrpc-server', inject=['sdkAppStartup', 'loader']),
    ])
    (profile / 'cordis.patch.yml').write_text(yaml.safe_dump([{'insert': rows}]), encoding='utf-8')
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            body = b'data: {"choices":[{"delta":{"content":"SDK journey complete"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
            if default_profile and len(requests) == 1:
                chunk = dict(choices=[dict(delta=dict(tool_calls=[dict(index=0, id='shell-call', type='function',
                    function=dict(name='pwsh', arguments=json.dumps(dict(command="Write-Output ('TOOL' + '-RESULT')"))))]), finish_reason='tool_calls')])
                body = ('data: ' + json.dumps(chunk) + '\n\ndata: [DONE]\n\n').encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = dict(os.environ, DSH_HOME=str(tmp_path / 'home'), DSH_TELEMETRY_DISABLED='1',
               DEEPSEEK_API_KEY='fixture-only', DEEPSEEK_BASE_URL='http://127.0.0.1:{}'.format(server.server_port))
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve().parents[1] / 'dsh.py'), '--profile', 'minimal' if default_profile else 'sdk-journey'],
        cwd=str(tmp_path), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        encoding='utf-8', bufsize=1)
    frames, stderr = queue.Queue(), []
    def read():
        for line in process.stdout:
            try:
                frames.put(json.loads(line))
            except ValueError:
                frames.put(dict(invalid=line))
        frames.put(dict(eof=True))
    reader = threading.Thread(target=read, daemon=True)
    errors = threading.Thread(target=lambda: stderr.append(process.stderr.read()), daemon=True)
    reader.start()
    errors.start()
    observed = []
    def wait(predicate):
        while True:
            try:
                frame = frames.get(timeout=10)
            except queue.Empty:
                raise AssertionError('SDK response timed out: ' + ''.join(stderr))
            assert 'invalid' not in frame and 'eof' not in frame, (frame, stderr)
            observed.append(frame)
            if predicate(frame):
                return frame
    def send(identity, method, params):
        process.stdin.write(json.dumps(dict(jsonrpc='2.0', id=identity, method=method, params=params)) + '\n')
        process.stdin.flush()
    try:
        send(1, 'initialize', dict(cwd=str(tmp_path), provider='deepseek-official', model='fixture-model'))
        assert 'result' in wait(lambda frame: frame.get('id') == 1)
        send(2, 'session/prompt', dict(sessionId='sdk-durable', contentBlocks=[dict(type='text', text='say hello')]))
        reply = wait(lambda frame: frame.get('id') == 2)
        assert reply['result']['messageId']
        wait(lambda frame: frame.get('method') == 'session.event' and 'SDK journey complete' in str(frame))
        send(3, 'shutdown', {})
        assert wait(lambda frame: frame.get('id') == 3)['result'] == {}
        assert process.wait(timeout=10) == 0, stderr
        assert requests[0]['model'] == 'fixture-model'
        if default_profile:
            assert len(requests) == 2
            assert any(message.get('role') == 'tool' and 'TOOL-RESULT' in str(message) for message in requests[1]['messages'])
        logs = list((tmp_path / ('home/sessions' if default_profile else 'sessions')).rglob('*.jsonl'))
        assert len(logs) == 1
        assert 'SDK journey complete' in logs[0].read_text(encoding='utf-8')
        assert any(frame.get('method') == 'session.status' for frame in observed)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)
        reader.join(2)
        errors.join(2)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
        server.shutdown()
        server.server_close()
        thread.join(2)
