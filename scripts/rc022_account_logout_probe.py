"""Captured-token logout retry policy through actual independent HTTP servers."""
import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    return [dict(maxRetries=retries, successAt=success, mode='normal') for retries in (0, 1, 5)
            for success in (1, 2, 6, None)]+[dict(maxRetries=2, successAt=None, mode=mode) for mode in
                ('pre-abort', 'header-abort', 'body-abort', 'header-timeout', 'body-timeout')]


def prepare(output):
    path = output/'inputs.json'; path.write_text(json.dumps(cases()), encoding='utf-8'); return [path]


async def observe():
    from dsh.core.abort import AbortController
    from dsh.credentials.account_logout import revokeAccount
    from dsh.credentials import account_protocol as protocol
    rows = []; hits = []; inputs = cases(); diagnostics = []; original = protocol._diagnostic
    protocol._diagnostic = lambda label, value: diagnostics.append(dict(label=label, **value))
    attempts = {}
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *_): pass
        def do_POST(self):
            index = int(self.path.split('/')[1]); case = inputs[index]; attempts[index] = attempts.get(index, 0)+1
            hits.append(dict(path=self.path[len('/'+str(index)):], token=self.headers.get('x-dsh-auth-token'), deployment=self.headers.get('x-deployment')))
            mode = case['mode']
            if mode.startswith('header-'):
                self.connection.settimeout(2)
                try: self.rfile.read(1)
                except OSError: pass
                return
            status = 200 if case['successAt'] == attempts[index] else 503
            payload = b'{"code":0,"data":{"biz_code":0,"biz_data":null}}'
            self.send_response(status); self.send_header('content-length', str(len(payload))); self.end_headers()
            try:
                if mode.startswith('body-'):
                    # A successful HTTP status is required to reach body parsing.
                    self.wfile.write(b'{'); self.wfile.flush(); self.connection.settimeout(2)
                    try: self.rfile.read(1)
                    except OSError: pass
                else: self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass
    # Body stalls must be 2xx; use the handler's first-success condition for them.
    for case in inputs:
        if case['mode'].startswith('body-'): case['successAt'] = 1
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); server.daemon_threads = True
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), name='account-logout-probe'); thread.start()
    try:
        for index, case in enumerate(inputs):
            start = len(hits); logged = len(diagnostics); controller = AbortController(); timer = None
            mode = case['mode']; timeout = 100 if 'timeout' in mode else 1000
            if mode == 'pre-abort': controller.abort(RuntimeError('private-cancel'))
            elif 'abort' in mode: timer = asyncio.get_running_loop().call_later(.04, controller.abort, RuntimeError('private-cancel'))
            try:
                await revokeAccount('http://127.0.0.1:'+str(server.server_port)+'/'+str(index), 'captured-old-token',
                                    dict(maxRetries=case['maxRetries'], delayMs=1, requestTimeoutMs=timeout), controller.signal, {'x-deployment': 'base'})
            finally:
                if timer: timer.cancel()
            logs = diagnostics[logged:]
            for value in logs: value['path'] = value['path'][len('/'+str(index)):]
            rows.append(dict(index=index, hits=hits[start:], diagnostics=logs, listeners=len(controller.signal._listeners)))
        return rows
    finally:
        protocol._diagnostic = original; server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_account_logout.mts', 'Actual captured-token logout, retry exhaustion and provider/timeout cancellation over HTTP.',
        [Path(__file__).resolve(), ROOT/'dsh/credentials/account_logout.py'], prepare=prepare)
