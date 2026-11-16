"""Independent real HTTP retrieval against the pinned anonymous fetch provider."""
import asyncio
import gzip
import json
import socket
import sys
import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    rows = [dict(mode='body', data=list(data), contentType=contentType, limits=limits)
            for data, contentType in [(b'hello', 'text/plain'), (b'<h1>raw</h1>', 'text/html'),
                (b'{}', 'application/problem+json'), (b'pdf', 'application/pdf'), (b'unknown', None),
                (b'\xef\xbb\xbfA', 'text/plain'), (b'\xe4\xb8\xad', 'text/plain'),
                (b'\xe4\xb8\xad', 'text/plain; charset=utf-8,gbk'), (b'\xe4\xb8', 'text/plain; charset=utf-8,gbk'),
                (b'\xff', 'text/plain; charset=utf-8,gbk'), (b'\xff', 'text/plain; charset=windows-1252'),
                (b'\x1b$B\x24\x22', 'text/plain; charset=iso-2022-jp'), (b'ABC', 'text/plain; charset=not-a-charset'),
                ('A\U0001f642Z'.encode('utf-8'), 'text/plain')]
            for limits in ({}, {'maxResponseBytes': 2}, {'maxBodyChars': 2}, {'maxResponseBytes': 2.5, 'maxBodyChars': 1.5})]
    rows += [dict(mode='body', data=list(data), contentType='text/plain', declared=declared, limits={'maxResponseBytes': 5})
             for data in (b'12345', b'123456') for declared in (True, False)]
    rows += [dict(mode='body', data=list(b'compressed text'), contentType='text/plain', encoding=encoding)
             for encoding in ('gzip', 'deflate')]
    rows += [dict(mode='body', data=list(b'error body'), contentType='text/plain', status=status) for status in (204, 205, 304, 404, 500)]
    for status in (301, 302, 303, 307, 308):
        rows += [dict(mode='redirect', status=status, location=location, limits=limits)
                 for location, limits in [('next?x=1#f', {}), ('/final', {'maxRedirects': 0}),
                     ('http://127.0.0.1:1/other', {}), ('ftp://host/path', {}), ('http://u:p@host/path', {}),
                     ('http://[', {}), (None, {}), ('', {'maxRedirects': 2})]]
    rows += [dict(mode='redirect', status=302, location=location) for location in (
        './next/../next?q=1', '\\next', 'http:next', '/'+('\u00e9'*400), '/'+('a/../'*500)+'next')]
    rows += [dict(mode=mode) for mode in ('pre-abort', 'header-abort', 'body-abort', 'header-timeout', 'body-timeout', 'dropped-body', 'snapshot-request')]
    rows += [dict(mode='invalid-url', url=url) for url in ('bad', 'file:///tmp', 'http://u:p@host', 'http://host/'+('x'*2048))]
    for key in ('maxResponseBytes', 'maxBodyChars', 'timeoutMs', 'maxRedirects'):
        rows += [dict(mode='config', key=key, value=value) for value in (0, -1, 1.5, 2147483648)]
    return rows


def prepare(output):
    path = output/'inputs.json'; path.write_text(json.dumps(cases()), encoding='utf-8'); return [path]


async def observe():
    from dsh.core.abort import AbortController
    from dsh.web.http_fetch_current import HttpFetchProvider, DEFAULTS, validateLimits
    inputs = cases(); hits = []; entered = threading.Event(); rows = []
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *_): pass
        def do_GET(self):
            parts = self.path.split('/'); index = int(parts[1]) if parts[1].isdigit() else 0
            entry = inputs[index]; mode = entry['mode']; redirected = len(parts) > 2 and parts[2].startswith('next')
            hits.append(dict(path=self.path, headers={key:self.headers[key] for key in ('user-agent','accept','authorization','cookie') if key in self.headers}))
            entered.set()
            if mode in ('header-abort', 'header-timeout'): return self.hold()
            data = bytes(entry.get('data', list(b'final body'))); status = entry.get('status', 200)
            if mode == 'redirect' and not redirected:
                self.send_response(status)
                if entry.get('location') is not None: self.send_header('location', entry['location'])
                self.send_header('content-length','0'); self.end_headers(); return
            if mode == 'redirect': data = b'final body'; status = 200
            encoding = entry.get('encoding')
            if encoding == 'gzip': data = gzip.compress(data)
            if encoding == 'deflate': data = zlib.compress(data)
            self.send_response(status)
            if entry.get('contentType', 'text/plain') is not None: self.send_header('content-type', entry.get('contentType', 'text/plain'))
            if encoding: self.send_header('content-encoding', encoding)
            if mode.startswith('body-') or mode == 'dropped-body': self.send_header('content-length', '100')
            elif entry.get('declared', False): self.send_header('content-length',str(len(data)))
            else: self.send_header('transfer-encoding','chunked')
            self.end_headers()
            if mode.startswith('body-') or mode == 'dropped-body':
                self.wfile.write(b'X'); self.wfile.flush()
                if mode == 'dropped-body': self.close_connection = True; return
                return self.hold()
            if status not in (204,205,304):
                if entry.get('declared', False): self.wfile.write(data)
                else:
                    if data: self.wfile.write(('%x\r\n'%len(data)).encode()+data+b'\r\n')
                    self.wfile.write(b'0\r\n\r\n')
            elif not entry.get('declared', False) and status == 205: self.wfile.write(b'0\r\n\r\n')
            self.wfile.flush()
        def hold(self):
            self.connection.settimeout(2)
            try: self.connection.recv(1)
            except (OSError, socket.timeout): pass
            self.close_connection = True
    server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
    thread = threading.Thread(target=lambda:server.serve_forever(poll_interval=.01)); thread.start()
    origin = 'http://127.0.0.1:'+str(server.server_port)
    try:
        rows.append(dict(description=HttpFetchProvider.description, available=HttpFetchProvider(DEFAULTS).available()))
        for index, entry in enumerate(inputs):
            mode=entry['mode']; limits=dict(DEFAULTS, userAgent='paired-fetch/1.0', **entry.get('limits',{}))
            if mode.endswith('timeout'): limits['timeoutMs']=100
            if mode=='config':
                limits[entry['key']]=entry['value']
                try: validateLimits(limits); result=dict(ok=True)
                except Exception as error: result=dict(message=str(error))
                rows.append(result); continue
            controller=AbortController(); start=len(hits); entered.clear(); waiter=None
            if mode=='pre-abort': controller.abort(RuntimeError('caller stopped'))
            if mode in ('header-abort','body-abort'):
                async def cancel():
                    while not entered.is_set(): await asyncio.sleep(.001)
                    await asyncio.sleep(.01); controller.abort(RuntimeError('caller stopped'))
                waiter=asyncio.create_task(cancel())
            try:
                request=dict(url=entry.get('url',origin+'/'+str(index)+'/start'))
                operation=HttpFetchProvider(limits).fetch(request,controller.signal)
                if mode=='snapshot-request': request['url']='invalid-after-call'
                result=await operation
            except Exception as error: result=dict(code=getattr(error,'code',None),message=getattr(error,'message',str(error)))
            finally:
                if waiter is not None: waiter.cancel(); await asyncio.gather(waiter,return_exceptions=True)
            controller.abort(RuntimeError('scope disposed'))
            rows.append(dict(result=result,hits=hits[start:],listeners=len(controller.signal._listeners)))
    finally:
        server.shutdown(); server.server_close(); thread.join(2)
    return json.loads(json.dumps(rows).replace(origin,'http://fixture.test'))


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_http_fetch.mts','Real anonymous fetch: redirects, byte/UTF-16 caps, content, decoding, transport and cancellation.',
               [Path(__file__).resolve(),ROOT/'dsh/web/http_fetch_current.py',ROOT/'dsh/host/http_request.py'],prepare=prepare)
