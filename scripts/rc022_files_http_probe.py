"""Paired Messages Files requests against independent real loopback servers."""
import asyncio
import base64
import copy
import gzip
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    file = dict(id='file-a', type='file', mime_type='image/png', size_bytes=7,
                created_at='2026-11-17T00:00:01.999Z', filename='a.png')
    rows = [dict(op='retrieve', body=file)]
    for field, values in {
        'id': ['', None, 0, '雪'], 'type': ['file', 'image', None],
        'mime_type': ['', None, 7], 'size_bytes': [-1, 0, 1.0, True, 9007199254740991, 9007199254740992],
        'created_at': ['1970-01-01T00:00:00Z', '1969-12-31T23:59:59.999Z', 'invalid',
                       '2024-02-30T00:00:00Z', '+275760-09-13T00:00:00.000Z', None, 100],
        'filename': ['', None, 'a\nb.png'],
    }.items():
        for value in values:
            changed = copy.deepcopy(file); changed[field] = value
            rows.append(dict(op='retrieve', body=changed))
    for body in (None, [], {}, dict(data=[file], has_more=False),
                 dict(data=[file], has_more=True, first_id=None, last_id=None),
                 dict(data=[], has_more=False, first_id='', last_id=''),
                 dict(data=[file], has_more=0), dict(data=[file], has_more=True, first_id=1),
                 dict(data=[{}], has_more=False)):
        rows.append(dict(op='list', body=body))
    rows.append(dict(op='list-query', body=dict(data=[], has_more=False)))
    for body in (dict(id='file-a', type='file_deleted'), dict(id='wrong', type='file_deleted'),
                 dict(id='file-a', object='file', deleted=True), None):
        rows.append(dict(op='delete', body=body))
    rows.extend(dict(op='upload', body=file, expiry=value) for value in (3600, 2592000, 3600.0, 3599, 2592001, True))
    for status in (400, 401, 403, 429, 500):
        for body in ('not-json', dict(error=dict(message='storage quota', code='q', type='limit')),
                     dict(error=dict(message='', code=4, type='bad'))):
            rows.append(dict(op='retrieve', body=body, status=status))
    rows += [dict(op='retrieve', body='not-json'), dict(op='retrieve', body=file, gzip=True),
             dict(op='retrieve', body=file, status=302), dict(op='encoded', body=file)]
    return rows


def prepare(output):
    path = output/'inputs.json'; path.write_text(json.dumps(cases(), ensure_ascii=True), encoding='utf-8')
    return [path]


def multipart(body, content_type):
    boundary = content_type.split('boundary=')[1].encode('ascii')
    fields = []
    for part in body.split(b'--'+boundary)[1:-1]:
        head, payload = part[2:].split(b'\r\n\r\n', 1)
        fields.append(dict(header=head.decode('utf-8'), data=base64.b64encode(payload[:-2]).decode('ascii')))
    return fields


async def observe():
    from dsh.llm.deepseek_files_current import DeepSeekFilesClient
    inputs = cases(); hits = []; rows = []
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *_): pass
        def do_GET(self): self.run_request()
        def do_POST(self): self.run_request()
        def do_DELETE(self): self.run_request()
        def run_request(self):
            index = int(self.path.split('/')[1]); case = inputs[index]
            data = self.rfile.read(int(self.headers.get('content-length', '0')))
            hit = dict(path=self.path[len('/'+str(index)):], method=self.command,
                       auth=self.headers.get('x-api-key'), version=self.headers.get('anthropic-version'),
                       beta=self.headers.get('anthropic-beta'), ua=self.headers.get('user-agent'))
            if data: hit['fields'] = multipart(data, self.headers['content-type'])
            hits.append(hit)
            payload = (case['body'].encode('utf-8') if isinstance(case['body'], str)
                       else json.dumps(case['body'], ensure_ascii=True).encode('utf-8'))
            if case.get('gzip'):
                payload = gzip.compress(payload)
            self.send_response(case.get('status', 200))
            if case.get('status') == 302: self.send_header('location', '/leaked')
            if case.get('gzip'): self.send_header('content-encoding', 'gzip')
            self.send_header('content-length', str(len(payload))); self.end_headers()
            try: self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), name='files-http-probe')
    thread.start()
    try:
        for index, case in enumerate(inputs):
            client = DeepSeekFilesClient('http://127.0.0.1:'+str(server.server_port)+'/'+str(index)+'/anthropic',
                                         {'X-API-Key': ' test-secret ', 'Anthropic-Version': 'wrong', 'User-Agent': 'paired/1'})
            start = len(hits)
            try:
                op = case['op']
                if op == 'upload': value = await client.upload(bytes([0, 1, 255]), 'image/png', 'a"\r\nb.png', case['expiry'])
                elif op == 'list': value = await client.list()
                elif op == 'list-query': value = await client.list(after='a +/雪', limit=7)
                elif op == 'delete': value = await client.delete('file-a')
                else: value = await client.retrieve("a/!~*'()雪?" if op == 'encoded' else 'file-a')
                result = dict(value=value)
            except Exception as error:
                message = getattr(error, 'message', str(error)).replace('http://127.0.0.1:'+str(server.server_port), '<origin>')
                result = dict(error=dict(message=message, code=getattr(error, 'code', None),
                                         status=getattr(error, 'status', None), detail=getattr(error, 'detail', None)))
            rows.append(dict(index=index, result=result, hits=hits[start:]))
        return rows
    finally:
        server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_files_http.mts', 'Messages Files API: actual loopback HTTP, multipart fields, metadata and response errors.',
               [Path(__file__).resolve(), ROOT/'dsh/llm/deepseek_files_current.py'], prepare=prepare)
