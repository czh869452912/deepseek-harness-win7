"""Actual localhost HTTP market index observations against pinned Source."""
import asyncio
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
SERVER = None
FILES = None
BODY = b'{"format":1,"title":"Market","plugins":[]}'
PATHS = ['ok', 'bom', 'missing', 'redirect', 'declared-size', 'stream-size', 'utf8', 'format', 'slow', 'empty', 'gzip-size', 'torn', 'abort']


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *_): pass
    def do_GET(self):
        path = self.path.strip('/'); status = 200; headers = {}; body = BODY
        if path == 'bom': body = b'\xef\xbb\xbf'+body
        elif path == 'missing': status = 404; body = b'missing'
        elif path == 'redirect': status = 302; headers['Location'] = '/ok'; body = b''
        elif path == 'declared-size': headers['Content-Length'] = '1000'; body = b'x'
        elif path == 'stream-size': headers['Transfer-Encoding'] = 'chunked'; body = b'x'*120
        elif path == 'utf8': body = b'\xff'
        elif path == 'format': body = b'{"format":2}'
        elif path in ('slow', 'abort'): time.sleep(.3)
        elif path == 'empty': status = 204; body = b''
        elif path == 'gzip-size': headers['Content-Encoding'] = 'gzip'; body = gzip.compress(b'x'*200)
        elif path == 'torn': headers['Content-Length'] = '50'; body = b'abc'
        self.send_response(status)
        for key, value in headers.items(): self.send_header(key, value)
        if 'Transfer-Encoding' not in headers and 'Content-Length' not in headers: self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close'); self.end_headers()
        try:
            if path == 'stream-size': self.wfile.write(b'78\r\n'+body+b'\r\n0\r\n\r\n')
            else: self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass
        self.close_connection = True


async def observe():
    from dsh.boot.market_http_022 import MarketHttpReader
    from dsh.core.abort import AbortController
    from dsh.typert.remote import RemoteError
    base = 'http://127.0.0.1:'+str(SERVER.server_port)+'/'; rows = []; raw = []
    for path in PATHS:
        controller = AbortController(); timer = None
        if path == 'abort': timer = asyncio.get_running_loop().call_later(.02, controller.abort, RuntimeError('Plugin market disposed'))
        try:
            value = await MarketHttpReader(timeout_ms=50 if path == 'slow' else 2000, max_bytes=100)(base+path, controller.signal)
            result = dict(ok=True, index=value)
        except RemoteError as error:
            result = dict(ok=False, code=error.code, message=error.message.replace(base, 'BASE/'),
                details={key:value.replace(base, 'BASE/') if isinstance(value, str) else value for key,value in error.details.items()})
        finally:
            if timer is not None: timer.cancel()
        raw.append(dict(path=path, result=result))
        if path == 'empty' and not result['ok']:
            result = dict(ok=False, code=result['code'], path=result['details']['path'], reasonPrefix=result['details']['reason'].split(':', 1)[0]+':')
        rows.append(dict(path=path, result=result))
    if FILES is not None: (FILES/'native-diagnostics.json').write_text(json.dumps(raw), encoding='utf-8')
    return rows


def prepare(output):
    global SERVER, FILES
    FILES = output; SERVER = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=SERVER.serve_forever, name='rc022-market-http-fixture', daemon=True); thread.start()
    path = output/'server.json'; path.write_text(json.dumps(dict(base='http://127.0.0.1:'+str(SERVER.server_port)+'/', paths=PATHS)), encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    try:
        probe.main('rc022_market_http.mts', scope='Actual localhost HTTP fetch + parser: success/BOM, status/redirect, declared/streamed/decoded body bounds, UTF-8/format, timeout, EOF and lifetime abort. Empty-body JSON diagnostic compared by code/path/prefix, raw engine prose retained.',
            prepare=prepare, extra_inputs=[ROOT/'dsh/boot/market_http_022.py', ROOT/'scripts/rc022_market_http_probe.py'])
    finally:
        if SERVER is not None: SERVER.shutdown(); SERVER.server_close()
