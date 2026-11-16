"""Actual Messages adapter transactions against real loopback HTTP."""
import asyncio
import gzip
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe

MODES = ['normal', 'compaction', 'gzip', 'concat-gzip', 'malformed', 'inband-error', 'empty', 'redirect',
         'auth', 'quota', 'retry-after', 'gateway', 'extension-accept-fail', 'extension-prepare-fail',
         'image', 'stale-file', 'inline-fallback', 'idle-header', 'idle-body', 'mapped', 'mapper-fail', 'real-upload', 'real-stale',
         'early-close', 'slow-consumer', 'cancel-header', 'cancel-body', 'broken-chunk', 'duplicate-headers',
         'truncated-length', 'empty205', 'tool-changes', 'image-tool-changes']
WORKSPACE = None


def events():
    return [dict(type='message_start', message=dict(usage=dict(input_tokens=1, output_tokens=0))),
            dict(type='content_block_start', index=0, content_block=dict(type='text', text='hello')),
            dict(type='content_block_delta', index=0, delta=dict(type='text_delta', text=' world')),
            dict(type='content_block_stop', index=0),
            dict(type='message_delta', delta=dict(stop_reason='end_turn'), usage=dict(output_tokens=2)),
            dict(type='message_stop')]


def config():
    from dsh.llm.deepseek_config_current import resolveAdapterOptions
    return resolveAdapterOptions(dict(models=[dict(id='m', inputModalities=['text', 'image'])]))


def prepare(output):
    global WORKSPACE
    WORKSPACE = output/'files'; WORKSPACE.mkdir()
    path = output/'inputs.json'; path.write_text(json.dumps(dict(modes=MODES, config=config(), events=events())), encoding='utf-8')
    return [path]


async def observe(workspace=None):
    from dsh.llm.deepseek_messages_adapter import DeepSeekMessagesAdapter
    from dsh.core.abort import AbortController
    from dsh.llm.llm_service import LlmError
    from dsh.llm.deepseek_file_store_current import DeepSeekFileStore, fileScope
    from dsh.llm.deepseek_upload_index_current import DeepSeekUploadIndex
    from scripts.rc022_files_http_probe import multipart
    inputs = MODES; hits = []; rows = []; attempts = {}; uploads = {}
    root = workspace or WORKSPACE
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *_): pass
        def do_POST(self):
            index = int(self.path.split('/')[1]); mode = inputs[index]
            payload = self.rfile.read(int(self.headers['content-length']))
            if self.path.endswith('/files'):
                uploads[index] = uploads.get(index, 0)+1
                fields = multipart(payload, self.headers['content-type'])
                hits.append(dict(path=self.path[len('/'+str(index)):], fields=fields))
                body = json.dumps(dict(id='file-'+str(uploads[index]), type='file', mime_type='image/png',
                    size_bytes=3, created_at='2026-11-17T00:00:01Z', filename='uploaded.png')).encode('utf-8')
                self.send_response(200); self.send_header('content-length', str(len(body))); self.end_headers(); self.wfile.write(body)
                return
            attempts[index] = attempts.get(index, 0)+1
            body = json.loads(payload)
            hits.append(dict(path=self.path[len('/'+str(index)):], body=body,
                headers={key: self.headers.get(key) for key in ('x-api-key', 'anthropic-version', 'anthropic-beta',
                    'x-deepseek-harness-user-id', 'x-deepseek-harness-session-id', 'x-deepseek-harness-compact')}))
            status = 200; payload = ''.join('event: '+event['type']+'\ndata: '+json.dumps(event)+'\n\n' for event in events()).encode('utf-8')
            if mode == 'malformed': payload = b'event: message_start\ndata: {\n\n'
            if mode == 'inband-error': payload = b'event: error\ndata: {"type":"error","error":{"type":"rate_limit_error","message":"busy"}}\n\n'
            if mode == 'empty': status = 204; payload = b''
            if mode == 'empty205': status = 205; payload = b''
            if mode == 'truncated-length': payload = b'event: message_start\ndata: {'
            if mode == 'redirect': status = 302
            if mode in ('auth', 'mapped', 'mapper-fail'): status = 401; payload = b'{"error":{"message":"bad key"}}'
            if mode == 'quota': status = 402; payload = b'{"error":{"message":"storage quota exceeded"}}'
            if mode in ('retry-after', 'duplicate-headers'): status = 503; payload = b'{"error":{"message":"busy"}}'
            if mode == 'gateway': status = 502; payload = b'gateway failed'
            if mode == 'stale-file' and attempts[index] == 1: status = 400; payload = b'{"error":{"message":"file-a not found"}}'
            if mode == 'real-stale' and attempts[index] == 1: status = 400; payload = b'{"error":{"message":"file-1 not found"}}'
            if mode == 'gzip': payload = gzip.compress(payload)
            if mode == 'concat-gzip': payload = gzip.compress(payload[:20])+gzip.compress(payload[20:])
            def send():
                try:
                    self.send_response(status)
                    if mode == 'redirect': self.send_header('location', '/leaked')
                    if mode in ('gzip', 'concat-gzip'): self.send_header('content-encoding', 'gzip')
                    if mode == 'retry-after': self.send_header('retry-after', '2'); self.send_header('request-id', 'r1')
                    if mode == 'duplicate-headers':
                        self.send_header('retry-after', '1'); self.send_header('retry-after', '2')
                        self.send_header('request-id', 'a'); self.send_header('request-id', 'b')
                    if mode == 'broken-chunk':
                        self.send_header('transfer-encoding', 'chunked'); self.end_headers()
                        part = b'event: message_start\ndata: {'
                        self.wfile.write(('%x\r\n' % len(part)).encode('ascii')+part+b'\r\n')
                        self.wfile.flush(); self.close_connection = True; return
                    self.send_header('content-length', str(len(payload)+(10 if mode == 'truncated-length' else 0))); self.end_headers()
                    if mode == 'truncated-length': self.close_connection = True
                    if mode in ('idle-body', 'cancel-body'):
                        self.wfile.write(payload[:1]); self.wfile.flush()
                        threading.Event().wait(.3); self.wfile.write(payload[1:])
                    else: self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError): pass
            if mode in ('idle-header', 'cancel-header'): threading.Event().wait(.3)
            send()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = False
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), name='messages-adapter-probe'); thread.start()
    try:
        for index, mode in enumerate(inputs):
            options = config(); options['baseURL'] = 'http://127.0.0.1:'+str(server.server_port)+'/'+str(index)+'/anthropic'
            options['streamIdleTimeoutMs'] = 80 if mode.startswith('idle-') or mode == 'slow-consumer' else 2000
            calls = []; chunks = []; start = len(hits)
            ref = dict(attachmentId='sha256:'+'a'*64, mediaType='image/png', bytes=3, width=2, height=2, hasAlpha=False)
            version = dict(attachment=ref, variantId='sha256:'+'b'*64, mediaType='image/png', bytes=3, width=2, height=2, hasAlpha=False, data=b'abc')
            async def read_image(ref, target, signal): return version
            async def ensure(*_):
                calls.append('files')
                if mode == 'inline-fallback': raise RuntimeError('upload unavailable')
                return dict(record=dict(fileId='file-a'))
            async def invalidate(generations, connection): calls.append(dict(invalidate=generations))
            async def accept():
                calls.append('accept')
                if mode == 'extension-accept-fail': raise RuntimeError('accept unavailable')
            async def extensions(request):
                calls.append(dict(extensions=dict(sessionId=request.get('sessionId'), purpose=request.get('purpose'))))
                if mode == 'extension-prepare-fail': raise RuntimeError('prepare unavailable')
                return dict(fields=dict(custom=dict(enabled=True)), accept=accept)
            async def mapper(error):
                calls.append('mapper')
                if mode == 'mapper-fail': raise RuntimeError('mapper unavailable')
                return LlmError('credential refreshed', 'AUTH')
            async def auth(connection):
                calls.append('auth'); result = dict(headers={'x-api-key': 'secret'})
                if mode in ('mapped', 'mapper-fail'): result['onRequestError'] = mapper
                return result
            dependencies = dict(options=lambda: options, resolveAuth=auth, resolveUserId=lambda: 'user-id',
                resolveFiles=lambda: SimpleNamespace(ensureUploaded=ensure, invalidate=invalidate),
                resolveAttachments=lambda: SimpleNamespace(readImageRequest=read_image), prepareExtensions=extensions,
                onExtensionsUnaccepted=lambda _: calls.append('unaccepted'))
            real = None; index_path = None
            if mode.startswith('real-'):
                index_path = root/('native-'+str(index))/'index.json'
                real = DeepSeekFileStore(index=DeepSeekUploadIndex(str(index_path)), now=lambda: 10000)
                dependencies['resolveFiles'] = lambda: real
            adapter = DeepSeekMessagesAdapter(dependencies)
            content = [dict(type='text', text='hi')]
            if mode in ('image', 'stale-file', 'inline-fallback', 'image-tool-changes') or mode.startswith('real-'): content.append(dict(type='image', attachment=ref))
            if mode == 'real-upload': content.append(dict(type='image', attachment=ref))
            request = dict(provider='deepseek-official', model='m', messages=[dict(role='user', content=content, source=dict(kind='user'))],
                           sessionId='session', purpose='compaction' if mode == 'compaction' else 'response')
            if mode in ('tool-changes', 'image-tool-changes'):
                request['messages'].append(dict(role='developer', source=dict(kind='tool-runtime'), content=[dict(type='tool-addition', toolName='read')]))
                request['tools'] = [dict(name='read', description='Read a file', parameters=dict(type='object'), deferLoading=True)]
            abort_timer = None
            if mode.startswith('cancel-'):
                controller = AbortController(); request['signal'] = controller.signal
                abort_timer = asyncio.get_running_loop().call_later(.08, controller.abort, RuntimeError('caller stopped'))
            stream = adapter.stream(request)
            try:
                async for chunk in stream:
                    chunks.append(chunk)
                    if mode == 'early-close': break
                    if mode == 'slow-consumer' and len(chunks) == 1: await asyncio.sleep(.16)
                result = dict(chunks=chunks)
            except Exception as error:
                result = dict(chunks=chunks, error=getattr(error, 'failure', dict(message=str(error))))
            finally:
                if abort_timer is not None: abort_timer.cancel()
                await stream.aclose()
                await adapter.close()
                if real is not None: await real.close()
            row = dict(mode=mode, result=result, calls=calls, hits=hits[start:])
            if index_path is not None:
                disk = json.loads(index_path.read_text(encoding='utf-8'))
                for record in disk['records']:
                    assert record['scope'] == fileScope(dict(baseURL=options['baseURL'], headers={'x-api-key': 'secret'}))
                    record['scope'] = '<verified-origin-scope>'
                row['disk'] = disk
            rows.append(row)
        return rows
    finally:
        server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_messages_adapter.mts', 'Actual Messages adapter through loopback HTTP: request lifecycle, image/File retries, extensions, SSE and idle deadlines.',
        [Path(__file__).resolve(), ROOT/'dsh/llm/deepseek_messages_adapter.py', ROOT/'dsh/llm/deepseek_messages_http.py'], prepare=prepare)
