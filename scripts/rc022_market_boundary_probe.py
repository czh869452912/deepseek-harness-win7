"""Actual HTTP/parser qualification at the default 128 MiB Market boundary."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from urllib.parse import urlsplit
import zlib

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
LIMIT = 128*1024*1024
BASE = None
OUTPUT = None
CASES = ('exact', 'declared-over', 'streamed-over', 'gzip-over')
DOCUMENT = b'{"format":1,"title":"Boundary","plugins":[]}'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        kind = urlsplit(self.path).path.strip('/')
        size = LIMIT if kind == 'exact' else LIMIT+1
        self.send_response(200)
        if kind in ('exact', 'declared-over'): self.send_header('Content-Length', str(size))
        if kind == 'gzip-over': self.send_header('Content-Encoding', 'gzip')
        self.send_header('Connection', 'close'); self.end_headers()
        compressor = zlib.compressobj(wbits=31) if kind == 'gzip-over' else None
        def write(data):
            if compressor is not None: data = compressor.compress(data)
            if data: self.wfile.write(data)
        try:
            write(DOCUMENT); remaining = size-len(DOCUMENT); padding = b' '*65536
            while remaining:
                chunk = padding[:min(remaining, len(padding))]
                write(chunk); remaining -= len(chunk)
            if compressor is not None: self.wfile.write(compressor.flush())
        except (BrokenPipeError, ConnectionError, OSError): pass


async def observations(base):
    from dsh.boot.market_http_022 import MarketHttpReader
    from dsh.core.abort import AbortController
    rows = []
    for kind in CASES:
        try:
            value = await MarketHttpReader(15000, LIMIT)(base+'/'+kind, AbortController().signal)
            rows.append(dict(kind=kind, ok=True, index=value))
        except Exception as error:
            rows.append(dict(kind=kind, ok=False, code=getattr(error, 'code', None),
                message=str(error), details=getattr(error, 'details', None)))
    return rows


def prepare(output):
    global OUTPUT
    OUTPUT = output
    path = output/'input.json'; path.write_text(json.dumps(dict(base=BASE, limit=LIMIT, cases=CASES)), encoding='utf-8')
    return [path]


async def native():
    rows = await observations(BASE)
    (OUTPUT/'x64.json').write_text(json.dumps(rows, ensure_ascii=True), encoding='utf-8')
    executable = ROOT/'.goose/tools/python-3.8.10-win32/python.exe'
    command = [str(executable), str(Path(__file__).resolve()), '--native-worker', BASE]
    (OUTPUT/'x86-command.json').write_text(json.dumps(command), encoding='utf-8')
    # Run after x64 buffers have been released; this process owns all its bytes.
    process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 90)
    finally:
        if process.returncode is None:
            process.kill(); await process.communicate()
    (OUTPUT/'x86.stderr').write_bytes(stderr); (OUTPUT/'x86.json').write_bytes(stdout)
    assert process.returncode == 0, stderr.decode('utf-8', errors='replace')[-2000:]
    assert json.loads(stdout) == rows
    assert rows[0]['ok'] and all(not row['ok'] for row in rows[1:])
    return rows


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--native-worker':
        import ctypes
        assert ctypes.sizeof(ctypes.c_void_p) == 4
        print(json.dumps(asyncio.run(observations(sys.argv[2])), ensure_ascii=True))
    else:
        from scripts import rc022_events_probe as probe
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        BASE = 'http://127.0.0.1:'+str(server.server_port)
        probe.native = native
        source = ROOT/'.goose/out/rc022-prep-20261114-01/source'
        try:
            probe.main('rc022_market_boundary.mts', 'Actual default 128 MiB exact body, declared/streamed/decoded-gzip overflow; original HTTP/parser and shipped x64/x86 workers.',
                [Path(__file__).resolve(), ROOT/'dsh/boot/market_http_022.py', ROOT/'dsh/boot/market_index_022.py',
                 ROOT/'dsh/boot/market-index/manifest.json', ROOT/'dsh/llm/stream_bridge.py', source/'packages/boot/plugin-market/src/index.ts',
                 source/'packages/boot/plugin-market/src/parse-thread.ts'], prepare)
        finally:
            server.shutdown(); server.server_close(); thread.join(2)
