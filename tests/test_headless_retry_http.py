"""Provider HTTP failures through the default profile and real AgentLoop retry."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import yaml


@pytest.mark.parametrize('statuses,retry_after,expected_retries,success', [
    ([503, 200], None, 1, True),
    ([401], None, 0, False),
    ([503, 503, 503], None, 2, False),
    ([503], '60', 0, False),
])
def test_default_headless_http_retry_policy(tmp_path, statuses, retry_after, expected_retries, success):
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            main = bool(request.get('tools'))
            if main:
                calls.append(request)
            status = statuses[min(len(calls) - 1, len(statuses) - 1)] if main else 200
            if status != 200:
                raw = json.dumps({'error': {'message': 'fixture failure'}}).encode('utf-8')
            else:
                raw = b'data: {"choices":[{"delta":{"content":"Recovered successfully"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
            self.send_response(status)
            self.send_header('Content-Type', 'text/event-stream' if status == 200 else 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            if status != 200 and retry_after:
                self.send_header('Retry-After', retry_after)
            self.end_headers()
            self.wfile.write(raw)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    worker.start()
    patch = tmp_path / 'retry.yaml'
    patch.write_text(yaml.safe_dump([dict(id='llm-deepseek', config=dict(retryPolicy=dict(
        mode='normal', maxRetries=2, backoff=dict(initialDelayMs=1, maxDelayMs=10, jitterRatio=0),
        retryableCodes=['SERVER'])))]), encoding='utf-8')
    env = dict(os.environ, DSH_HOME=str(tmp_path / 'home'), DSH_TELEMETRY_DISABLED='1',
               DEEPSEEK_API_KEY='fixture', DEEPSEEK_BASE_URL='http://127.0.0.1:%s' % server.server_port)
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'dsh.py'),
            '--profile', 'headless', '--patch', str(patch), 'Reply to the request'], cwd=str(tmp_path),
            env=env, capture_output=True, encoding='utf-8', timeout=25)
        assert result.returncode == (0 if success else 1), result.stdout + result.stderr
        assert len(calls) == len(statuses)
        logs = list((tmp_path / 'home/sessions').rglob('session.jsonl'))
        assert len(logs) == 1
        events = [json.loads(line) for line in logs[0].read_text(encoding='utf-8').splitlines()]
        retries = [event['data'] for event in events if event['type'] == 'llm/retry']
        assert [retry['retry'] for retry in retries] == list(range(1, expected_retries + 1))
        assert len([event for event in events if event['type'] == 'llm/retry-started']) == expected_retries
        assert len([event for event in events if event['type'] == 'turn/start']) == 1
        ends = [event for event in events if event['type'] == 'turn/end']
        assert len(ends) == 1
        assert ends[0]['data']['reason']['kind'] == ('completed' if success else 'error')
        assert len([event for event in events if event['type'] == 'assistant/message']) == int(success)
        if success:
            assert result.stdout.strip() == 'Recovered successfully'
            assert calls[0]['messages'] == calls[1]['messages']
        if retries:
            assert len({(retry['turn'], retry['step'], retry['retryId']) for retry in retries}) == 1
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)
