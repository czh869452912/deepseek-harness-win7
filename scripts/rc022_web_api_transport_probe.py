"""Ordered web credentials and dispatch through independent real HTTP servers."""
import asyncio
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
    rows = [dict(sources=sources, mode='ok') for sources in (
        ['account', 'key-ref'], ['key-ref', 'account'], ['account-empty', 'key-ref'],
        ['key-empty', 'account'], ['key-ref-empty', 'account'], ['account-empty', 'key-empty'],
        [], ['key-empty'], ['misconfigured', 'account'], ['account', 'misconfigured'],
        ['account-error', 'key-ref'], ['key-ref-error', 'account'], ['key-ref-configured-error', 'account'],
        ['key-ref-unconfigured', 'account'], ['key'], ['account'], ['key-ref-empty'], ['account-empty'])]
    for source in ('account', 'key-ref'):
        for mode in ('error-string', 'error-object', 'error-message', 'error-null', 'error-invalid',
                     'unauthorized', 'unauthorized-removal-error', 'redirect', 'invalid-result', 'invalid-json',
                     'header-abort', 'body-abort', 'unauthorized-body-abort', 'record-error', 'wait-error', 'pre-abort'):
            rows.append(dict(sources=[source], mode=mode))
    rows.extend(dict(sources=['key-ref', 'account'], mode=mode) for mode in ('resolve-abort', 'resolve-reject-late'))
    return rows


def prepare(output):
    path = output/'inputs.json'; path.write_text(json.dumps(cases()), encoding='utf-8'); return [path]


async def observe():
    from dsh.core.abort import AbortController
    from dsh.web import deepseek_api_transport as transport
    rows = []; hits = []; inputs = cases(); entered = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *_): pass
        def do_POST(self):
            index = int(self.path.split('/')[1]); mode = inputs[index]['mode']
            body = self.rfile.read(int(self.headers['content-length']))
            headers = {name: self.headers[name] for name in ('x-dsh-auth-token', 'authorization', 'x-api-key', 'content-type', 'accept', 'user-agent') if name in self.headers}
            hits.append(dict(path=self.path[len('/'+str(index)):], headers=headers, body=json.loads(body)))
            status = 401 if mode.startswith('unauthorized') else 503 if mode.startswith('error-') else 302 if mode == 'redirect' else 200
            payload = {'value': 17}
            if mode == 'error-string': payload = dict(error='provider-detail')
            elif mode == 'error-object': payload = dict(error=dict(message='provider-detail'))
            elif mode == 'error-message': payload = dict(message='provider-detail')
            elif mode == 'error-null': payload = dict(error=None, message='fallback-detail')
            elif mode.startswith('unauthorized'): payload = dict(error=dict(message='rejected'))
            elif mode == 'invalid-result': payload = []
            encoded = b'invalid' if mode in ('error-invalid', 'invalid-json') else json.dumps(payload).encode('utf-8')
            entered.set()
            try:
                if mode == 'header-abort':
                    self.connection.settimeout(2)
                    try: self.rfile.read(1)
                    except OSError: pass
                    return
                self.send_response(status)
                if status == 302: self.send_header('location', '/must-not-follow')
                self.send_header('content-length', str(len(encoded))); self.end_headers()
                if 'body-abort' in mode:
                    self.wfile.write(encoded[:1]); self.wfile.flush(); self.connection.settimeout(2)
                    try: self.rfile.read(1)
                    except OSError: pass
                else: self.wfile.write(encoded)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), name='web-api-transport-probe'); thread.start()
    origin = 'http://127.0.0.1:'+str(server.server_port)
    def fail(message): raise RuntimeError(message)
    try:
        for index, entry in enumerate(inputs):
            start = len(hits); events = []; controller = AbortController(); entered.clear()
            mode = entry['mode']; pending = asyncio.get_running_loop().create_future(); dispatching = False
            async def resolve(tag):
                events.append(tag)
                if dispatching and tag == 'key-ref' and mode.startswith('resolve-'): return await pending
                if tag.endswith('-error'): fail('read-failed')
                return None if tag.endswith('-empty') else 'account-token' if tag.startswith('account') else 'api-key'
            async def configured(tag):
                events.append('configured:'+tag)
                if tag.endswith('configured-error'): fail('presence-failed')
                return tag != 'key-ref-unconfigured'
            async def reject(token):
                events.append('reject:'+token)
                if mode == 'unauthorized-removal-error': fail('remove-failed')
            sources = []
            for tag in entry['sources']:
                base = origin+'/'+str(index)+('/account///' if tag.startswith('account') else '/key/')
                if tag == 'misconfigured': sources.append(dict(kind=tag, message='route settings invalid'))
                elif tag.startswith('account'):
                    sources.append(dict(kind='account', baseURL=base, resolveToken=lambda endpoint, tag=tag: resolve(tag), rejectToken=reject))
                elif tag.startswith('key-ref'):
                    sources.append(dict(kind='api-key', baseURL=base, key=dict(resolve=lambda tag=tag: resolve(tag), configured=lambda tag=tag: configured(tag))))
                else: sources.append(dict(kind='api-key', baseURL=base, key='' if tag == 'key-empty' else 'api-key'))
            auth = dict(sources=sources)
            available = transport.hasDeepSeekWebCredential(auth)
            ready = await transport.isDeepSeekWebAuthReady(auth, '/search')
            dispatching = True
            def record(endpoint):
                events.append('record:'+endpoint.replace(origin+'/'+str(index), '<endpoint>'))
                if mode == 'record-error': fail('record-failed')
            async def wait(signal):
                events.append('wait')
                if mode == 'wait-error': fail('wait-failed')
            def decode(value):
                if not isinstance(value, dict) or 'value' not in value: raise transport.invalidResponse()
                return value['value']
            guidance = dict(subject='Search', plugin='web-deepseek-api', custom=index % 2 == 0, baseURLField='searchBaseURL', apiKeyEnvField='searchApiKeyEnv')
            request = dict(path='/search', body=dict(query='fixture'), decode=decode, guidance=guidance,
                           apiKeyHeaders=lambda key: {'x-api-key': key}, recordRequest=record, waitToSend=wait)
            if mode == 'pre-abort': controller.abort(RuntimeError('private-cancel'))
            operation = asyncio.create_task(transport.dispatchDeepSeekWeb(auth, request, controller.signal))
            if mode.startswith('resolve-'):
                while 'key-ref' not in events: await asyncio.sleep(0)
                controller.abort(RuntimeError('private-cancel')); await asyncio.sleep(0)
                if mode == 'resolve-reject-late': pending.set_exception(RuntimeError('late-failed'))
                else: pending.set_result('late-key')
            elif 'abort' in mode and mode != 'pre-abort':
                while not entered.is_set(): await asyncio.sleep(.001)
                await asyncio.sleep(.03); controller.abort(RuntimeError('private-cancel'))
            try: result = dict(value=await operation)
            except Exception as error:
                message = getattr(error, 'message', str(error)).replace(origin+'/'+str(index), '<endpoint>')
                if mode == 'invalid-json': message = re.sub(r'(?s)(unprocessable response body: ).*?(\n\nThe web request)', r'\1<runtime JSON diagnostic>\2', message)
                result = dict(code=getattr(error, 'code', None), message=message)
            controller.abort(RuntimeError('caller-scope-finished'))
            for _ in range(3): await asyncio.sleep(0)
            rows.append(dict(index=index, available=available, ready=ready, result=result, events=events, hits=hits[start:], listeners=len(controller.signal._listeners)))
        return rows
    finally:
        server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_web_api_transport.mts', 'Ordered web credentials and real HTTP; JSON parser diagnostic text is runtime-specific.',
        [Path(__file__).resolve(), ROOT/'dsh/web/deepseek_api_transport.py', ROOT/'dsh/host/http_request.py', ROOT/'dsh/host/url_current.py'], prepare=prepare)
