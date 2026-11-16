"""Actual restricted URLs, deployment headers and real bounded Platform HTTP."""
import asyncio
import gzip
import itertools
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    rows = []
    origins = ['https://platform.example', 'HTTPS://PLATFORM.example:443/', 'https:platform.example',
               'https://user@platform.example/', 'https://:@platform.example/', 'https://platform.example/?#',
               'https://platform.example/.', 'https://platform.example/a/..', 'https://platform.example/%2e/',
               'https://platform.example/path', 'https://platform.example/?x', 'https://platform.example/#x',
               'http://localhost:80/', 'http://127.1:00081/', 'http://0x7f000001/', 'http://[0:0::1]:82/',
               'http://localhost./', 'http://remote.example/', 'ftp://platform.example/', 'mailto:a@b',
               'not a url', 'https://', 'https://host:65536', 'https://host:-1', 'https://host:abc',
               'https://\u96ea.example', 'https://%65xample.test', ' https://platform.example/\t\n',
               'https://platform.example\\a\\..\\', 'https://platform.example//', 'file:///tmp/test']
    rows.extend(dict(kind='origin', value=value, allow=allow, field=field) for value, allow, field in
                itertools.product(origins, (False, True), ('platformOrigin', 'harnessOrigin')))
    login = ['http://localhost:80', 'http://LOCALHOST:00080/', 'http://127.0.0.1:65535/', 'http://[::1]:80',
             'http://localhost:0', 'http://localhost', 'http://localhost:65536', 'http://localhost:080/\n',
             ' http://localhost:81', 'http://127.1:81', 'http://[0:0::1]:81', 'https://localhost:81',
             'http://localhost:81/?', 'http://localhost:81/#', 'http://localhost:81/a/..', 'http://localhost:81//',
             'http://user@localhost:81', 'http://localhost:81?secret', 'http://localhost:81#secret']
    rows.extend(dict(kind='login', value=value) for value in login)
    paths = ['/dsh/authorize', '/a/../dsh/authorize', '/%2e/dsh/authorize', '/x/%2e%2e/dsh/authorize',
             '/dsh/%61uthorize', '/dsh/authorize/', '/dsh//authorize', '/dsh/authorize?', '/dsh/authorize#',
             '/dsh/authorize?x=a%2Fb&x=two+words&empty=', '/dsh/authorize?x=\u96ea \'"<>`{}',
             '/dsh/authorize#secret', '/other?code=private-secret']
    authorities = ['https://platform.example', 'https://other.example', 'http://localhost:81',
                   'http://other.example', 'https://u:p@platform.example', 'https://:@platform.example']
    rows.extend(dict(kind='browser', value=authority+path, origin=origin, rewrite=rewrite) for authority, path, origin, rewrite in
                itertools.product(authorities, paths, ('https://platform.example', 'http://localhost:81'), (False, True)))
    rows.extend(dict(kind='browser', value=value, origin='https://platform.example', rewrite=True) for value in
                ('bad-url', 'javascript:alert(1)', '//platform.example/dsh/authorize', 'https://',
                 'https://platform.example:65536/dsh/authorize'))
    headers = [{}, {'X-Test': '  value\t'}, {'Z': '1', 'a': '2', 'Cookie': 'a=b'}, {'x': '', 'X': 'two'},
               {'x': '\r\nvalue\r\n'}, {'x': 'a\nb'}, {'x': 'a\0b'}, {'x': '\u00ff'}, {'x': '\u0100'},
               {'x': '\u0080'}, {'x': '\x0bvalue\x0c'}, {'x': '\u96ea'}, {'': 'x'}, {'bad name': 'x'},
               {'x:y': 'z'}, {'x\r': 'z'}, {'x\u00ff': 'z'}]
    headers.extend({name: 'secret'} for name in ('Authorization', 'X-DSH-AUTH-TOKEN', 'HOST', 'content-length',
                   'transfer-encoding', 'connection', 'Content-Type'))
    rows.extend(dict(kind='headers', value=value) for value in headers)
    success = dict(code=0, data=dict(biz_code=0, biz_data=dict(ok=True)))
    envelopes = [success, None, [], {}, {'code': 0}, {'code': False, 'data': {}},
                 {'code': '0', 'data': {}}, {'code': 0, 'data': None}, {'code': 0, 'data': {'biz_code': 0}},
                 {'code': 40003}, {'code': 40003, 'data': None}, {'code': 40003, 'data': {}},
                 {'code': 0, 'data': {'biz_code': 40123, 'biz_data': {'token': 'response-secret'}}},
                 {'code': 0, 'data': {'biz_code': 'private-code', 'biz_data': None}}]
    envelopes.extend(dict(code=0, data=dict(biz_code=code, biz_data=None)) for code in
                     (True, None, .5, 9007199254740991, 9007199254740992, -9007199254740992))
    for op, body in itertools.product(('platform', 'account'), envelopes):
        rows.append(dict(kind='http', op=op, body=body))
    for status, op in itertools.product((201, 204, 205, 301, 302, 400, 401, 403, 429, 500), ('platform', 'account')):
        rows.append(dict(kind='http', op=op, body=success, status=status))
    for wire in ('bad-json', 'bom', 'invalid-utf8', 'gzip', 'limit', 'over-limit', 'gzip-over-limit', 'gzip-bomb', 'truncated', 'broken-chunk'):
        rows.append(dict(kind='http', op='account', body=success, wire=wire))
    for op in ('notifications', 'content', 'event', 'logout'):
        rows.append(dict(kind='http', op=op, body=success))
    for mode in ('pre-abort', 'header-abort', 'body-abort', 'header-timeout', 'body-timeout'):
        rows.append(dict(kind='http', op='account', body=success, mode=mode))
    for field, data in [('profile', {'email': 'masked'}), ('profile', {'id': 7, 'email': None, 'mobile': None, 'id_profile': {}}),
                        ('balance', {'normal_wallets': [], 'bonus_wallets': []}),
                        ('balance', {'normal_wallets': [None, {'currency': 'EUR', 'balance': 'private-value'}], 'bonus_wallets': None})]:
        rows.append(dict(kind='http', op='detail-'+field, body=dict(code=0, data=dict(biz_code=0, biz_data=data))))
    return rows


def prepare(output):
    path = output/'inputs.json'; path.write_text(json.dumps(cases(), ensure_ascii=True), encoding='utf-8'); return [path]


async def observe():
    from dsh.core.abort import AbortController
    from dsh.cordis.utils import _UNDEFINED
    from dsh.credentials import account_protocol as module
    from dsh.credentials.account_errors import AccountUnauthorizedError
    inputs = cases(); hits = []; rows = []; diagnostics = []; original = module._diagnostic
    module._diagnostic = lambda label, value: diagnostics.append(dict(label=label, **value))
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *_): pass
        def do_GET(self): self.run_request()
        def do_POST(self): self.run_request()
        def run_request(self):
            index = int(self.path.split('/')[1]); case = inputs[index]
            data = self.rfile.read(int(self.headers.get('content-length', '0')))
            hits.append(dict(path=self.path[len('/'+str(index)):], method=self.command,
                             auth=self.headers.get('x-dsh-auth-token'), deployment=self.headers.get('x-deployment'),
                             contentType=self.headers.get('content-type'), body=data.decode('utf-8')))
            mode = case.get('mode', '')
            if mode.startswith('header-'):
                self.connection.settimeout(2)
                try: self.rfile.read(1)
                except OSError: pass
                return
            wire = case.get('wire'); payload = json.dumps(case['body'], separators=(',', ':'), ensure_ascii=True).encode()
            if wire == 'bad-json': payload = b'not-json'
            elif wire == 'bom': payload = b'\xef\xbb\xbf'+payload
            elif wire == 'invalid-utf8': payload = b'{"code":0,"data":{"biz_code":0,"biz_data":"\xff"}}'
            elif wire in ('limit', 'over-limit', 'gzip-over-limit'):
                payload += b' '*(65536-len(payload)+(1 if wire != 'limit' else 0))
            if wire == 'gzip-bomb': payload += b' '*(10*1024*1024)
            if wire in ('gzip', 'gzip-over-limit', 'gzip-bomb'): payload = gzip.compress(payload)
            self.send_response(case.get('status', 200))
            if case.get('status') in (301, 302): self.send_header('location', '/leaked')
            if wire in ('gzip', 'gzip-over-limit', 'gzip-bomb'): self.send_header('content-encoding', 'gzip')
            if wire == 'broken-chunk': self.send_header('transfer-encoding', 'chunked')
            else: self.send_header('content-length', str(len(payload)+(10 if wire == 'truncated' else 0)))
            self.end_headers()
            try:
                if mode.startswith('body-'):
                    self.wfile.write(b'{'); self.wfile.flush(); self.connection.settimeout(2)
                    try: self.rfile.read(1)
                    except OSError: pass
                    return
                if wire == 'broken-chunk': payload = b'Z\r\ninvalid\r\n'; self.close_connection = True
                if wire == 'truncated': self.close_connection = True
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); server.daemon_threads = True
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), name='account-protocol-probe'); thread.start()
    try:
        for index, case in enumerate(inputs):
            start = len(hits); logged = len(diagnostics); kind = case['kind']; timer = None
            try:
                if kind == 'origin': value = module.platformOrigin(case['value'], case['allow'], case['field'])
                elif kind == 'login': value = module.loginOrigin(case['value'])
                elif kind == 'browser': value = module.browserUrl(case['value'], case['origin'], '/dsh/authorize', case['rewrite'])
                elif kind == 'headers': value = module.platformHeaders(case['value'])
                else:
                    origin = 'http://127.0.0.1:'+str(server.server_port)+'/'+str(index)
                    controller = AbortController(); mode = case.get('mode', '')
                    reason = RuntimeError('private-cancel')
                    if 'timeout' in mode: reason.name = 'TimeoutError'
                    if mode == 'pre-abort': controller.abort(reason)
                    elif mode: timer = asyncio.get_running_loop().call_later(.04, controller.abort, reason)
                    args = (controller.signal, {'x-deployment': 'base'})
                    op = case['op']
                    if op == 'platform': value = await module.requestPlatform(origin, 'auth_init', {'verifier': 'request-secret'}, *args)
                    elif op == 'account': value = await module.requestAccount(origin, '/auth-api/v0/users/current', 'fixture-token', *args)
                    elif op == 'notifications': value = await module.requestNotifications(origin, 'fixture-token', *args)
                    elif op == 'content': value = await module.requestNotificationContent(origin, 'fixture-token', "a +/!~*'()\u96ea?", *args)
                    elif op == 'event': value = await module.requestNotificationEvent(origin, 'fixture-token', 'id', 'dismissed', *args)
                    elif op.startswith('detail-'):
                        from dsh.credentials.account_details import readAccountDetail
                        value = await readAccountDetail(op[7:], origin, 'fixture-token', *args)
                    else:
                        await module.logoutAccount(origin, 'fixture-token', *args)
                        value = _UNDEFINED  # Source void / Python None are host-language return conventions.
                result = {'value': '<undefined>' if value is _UNDEFINED else value}
            except Exception as error:
                result = dict(error=dict(message=getattr(error, 'message', str(error)), code=getattr(error, 'code', None), unauthorized=isinstance(error, AccountUnauthorizedError)))
            finally:
                if timer: timer.cancel()
            logs = diagnostics[logged:]
            if kind == 'http':
                for log in logs:
                    if 'path' in log: log['path'] = log['path'][len('/'+str(index)):]
            rows.append(dict(index=index, result=result, hits=hits[start:], diagnostics=logs))
        return rows
    finally:
        module._diagnostic = original
        server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_account_protocol.mts', 'Actual restricted URL/header policies and real Platform HTTP envelopes, limits and cancellation.',
        [Path(__file__).resolve(), ROOT/'dsh/credentials/account_protocol.py', ROOT/'dsh/credentials/account_urls.py',
         ROOT/'dsh/credentials/account_http.py', ROOT/'dsh/credentials/account_details.py'], prepare=prepare)
