"""Complete PKCE browser login through actual canonical callback and Platform HTTP."""
import asyncio
import base64
import hashlib
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    return ['success', 'invalid-user', 'invalid-init', 'invalid-authorize-url', 'invalid-exchange',
            'invalid-completion-url', 'exchange-failure-web', 'exchange-failure-zh', 'exchange-failure-desktop',
            'cancel-waiting', 'expire-waiting', 'commit-cancel', 'invalid-device', 'invalid-callbacks',
            'duplicate-callback', 'cancel-exchanging', 'init-timeout']


def prepare(output):
    path = output/'inputs.json'; path.write_text(json.dumps(cases()), encoding='utf-8'); return [path]


async def http(origin, target, method='GET'):
    from urllib.parse import urlsplit
    parsed = urlsplit(origin)
    reader, writer = await asyncio.open_connection(parsed.hostname, parsed.port)
    try:
        writer.write((method+' '+target+' HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n').encode('ascii')); await writer.drain()
        wire = await asyncio.wait_for(reader.read(), 5)
        head, body = wire.split(b'\r\n\r\n', 1); lines = head.decode().split('\r\n')
        headers = dict(line.split(': ', 1) for line in lines[1:])
        return dict(status=int(lines[0].split()[1]), headers={key.lower(): value for key, value in headers.items()}, body=body.decode('utf-8'))
    finally:
        writer.close(); await writer.wait_closed()


def normalized_callback(value, origin):
    if value is None:
        return None
    headers = {key: entry.replace(origin, '<platform>') for key, entry in value['headers'].items()
               if key in ('location', 'cache-control', 'content-type', 'content-security-policy', 'referrer-policy')}
    body = value['body']
    csp = headers.get('content-security-policy')
    if csp:
        nonce = re.search("nonce-([^']+)", csp).group(1)
        assert re.fullmatch('[A-Za-z0-9_-]{22}', nonce) and ('nonce="'+nonce+'"') in body
        headers['content-security-policy'] = csp.replace(nonce, '<nonce>'); body = body.replace(nonce, '<nonce>')
    return dict(status=value['status'], headers=headers, body=body)


async def observe():
    from dsh.cordis.context import Context
    from dsh.cordis.awaiting import await_callback_result
    from dsh.credentials.deepseek_account_current import CurrentDeepSeekAccount
    from dsh.credentials.account_state import KEY, DEVICE
    from dsh.credentials.authorization_current import CurrentAuthorizationService
    from dsh.credentials import deepseek_account_current as account_module, account_protocol as protocol
    from dsh.host.webserver.current import CurrentWebServerPlugin
    rows = []; original_log = protocol._diagnostic; original_account_log = account_module._diagnostic
    try:
        for mode in cases():
            ctx = Context(); records = {}; hits = []; logs = []; init = {}; verification = []
            origin = ''; commit_entered = asyncio.Event(); commit_gate = asyncio.get_running_loop().create_future()
            exchange_entered = threading.Event(); exchange_gate = threading.Event(); init_gate = threading.Event()
            if mode == 'invalid-device': records[DEVICE] = dict(kind='grant', payload=dict(id='not-uuid'))
            async def read(key): return records.get(key)
            async def modify(key, mutate):
                record = await await_callback_result(mutate(records.get(key)))
                if record is not None:
                    if key == KEY and mode == 'commit-cancel':
                        commit_entered.set(); await commit_gate
                    records[key] = record; ctx.emit('credentials/record-updated', key)
                return records.get(key)
            async def delete(key):
                if key in records: del records[key]; ctx.emit('credentials/record-updated', key)
            async def describe(key): return dict(configured=key in records)
            ctx.set_service('credentials', SimpleNamespace(readRecord=read, modifyRecord=modify, deleteRecord=delete, describeRecord=describe))
            class Handler(BaseHTTPRequestHandler):
                protocol_version = 'HTTP/1.1'
                def log_message(self, *_): pass
                def do_GET(self): self.respond()
                def do_POST(self): self.respond()
                def respond(self):
                    data = self.rfile.read(int(self.headers.get('content-length', '0')))
                    body = json.loads(data) if data else None
                    hits.append(dict(path=self.path, method=self.command, token=self.headers.get('x-dsh-auth-token'),
                        locale=self.headers.get('x-client-locale'), platform=self.headers.get('x-client-platform'), cookie=self.headers.get('cookie')))
                    status = 200
                    if self.path.endswith('auth_init'):
                        init.update(body)
                        if mode == 'init-timeout': init_gate.wait(5)
                        payload = dict(authorize_url=origin+('/wrong?private-secret' if mode == 'invalid-authorize-url' else '/dsh/authorize?authorize_id=fixture'),
                                       authorize_id='fixture', expires_in=600)
                        if mode == 'invalid-init': payload['expires_in'] = 'private-secret'
                        verification.append(dict(method=body['code_challenge_method'], locale=body['locale'], source=body['login_source'],
                                                 stateLength=len(body['state']), challengeLength=len(body['code_challenge']),
                                                 callbackMatches=body['redirect_uri'] == callback_origin+'/oauth/callback'))
                    elif self.path.endswith('auth_exchange'):
                        exchange_entered.set()
                        if mode in ('duplicate-callback', 'cancel-exchanging'): exchange_gate.wait(5)
                        expected = base64.urlsafe_b64encode(hashlib.sha256(body['code_verifier'].encode()).digest()).decode().rstrip('=')
                        verification.append(dict(pkce=expected == init['code_challenge'], code=body['code'],
                            redirectMatches=body['redirect_uri'] == init['redirect_uri'], deviceValid=bool(re.fullmatch('[0-9a-f-]{36}', body['device_id'])),
                            deviceModel=body['device_model'], osVersion=body['os_version']))
                        payload = dict(token='fixture-token', authorized_url=origin+('/wrong' if mode == 'invalid-completion-url' else '/dsh/authorized?x=a%2Fb&login_source=old&login_source=duplicate&v=~#'),
                                       user=dict(id='user-id', email='masked', token='must-discard'))
                        if mode == 'invalid-user': payload['user'] = dict(email=7)
                        if mode == 'invalid-exchange': payload['token'] = 'invalid token'
                        if mode.startswith('exchange-failure'): status = 503
                    elif self.path.endswith('auth_cancel'):
                        verification.append(dict(cancelId=body['authorize_id'], verifierMatches=base64.urlsafe_b64encode(hashlib.sha256(body['code_verifier'].encode()).digest()).decode().rstrip('=') == init['code_challenge']))
                        payload = None
                    else: payload = dict(id='fallback-user', email='masked')
                    wire = json.dumps(dict(code=0, data=dict(biz_code=0, biz_data=payload))).encode('utf-8')
                    self.send_response(status); self.send_header('content-length', str(len(wire))); self.end_headers()
                    try: self.wfile.write(wire)
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            # Join owned request handlers after releasing their fixture gates.
            server.daemon_threads = False
            thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), name='account-login-probe'); thread.start()
            origin = 'http://127.0.0.1:'+str(server.server_port)
            def log(label, value): logs.append(dict(label=label, **value))
            protocol._diagnostic = log; account_module._diagnostic = log
            callback = None; invalid = []; result = None
            try:
                await ctx.plugin(CurrentWebServerPlugin, dict(host='127.0.0.1', port=0))
                await ctx.plugin(CurrentAuthorizationService)
                await ctx.plugin(CurrentDeepSeekAccount, dict(platformOrigin=origin, inferenceOrigin=origin, allowLoopbackHttp=True,
                    desktopPlatform=None, requestHeaders={'cookie': 'gate=fixture'}, requestTimeoutMs=100 if mode == 'init-timeout' else 3000,
                    attemptTimeoutMs=300 if mode == 'expire-waiting' else 3000))
                account = ctx.deepseekAccount
                callback_origin = ctx.webServer.getOrigin()
                client = dict(version='fixture/1', locale='zh' if mode == 'exchange-failure-zh' else 'en', timezoneOffsetSeconds=28800)
                start = await account.startSignIn(client, ctx.webServer.getOrigin(), 'desktop' if mode == 'exchange-failure-desktop' else 'web')
                for _ in range(1000):
                    state = await account.getState()
                    if state['attempt']['phase'] != 'initializing': break
                    await asyncio.sleep(.002)
                assert state['attempt']['phase'] != 'initializing'
                joined = await account.startSignIn(dict(client, locale='other'), ctx.webServer.getOrigin(), 'desktop') if state['attempt']['phase'] == 'waiting-browser' else None
                join_same = joined is None or joined['attempt']['id'] == state['attempt']['id']
                if state['attempt']['phase'] == 'waiting-browser':
                    target = '/oauth/callback?state='+quote(init['state'])+'&code=fixture-code'
                    if mode == 'invalid-callbacks':
                        for bad in [target+'&code=duplicate', target+'&state=duplicate', '/oauth/callback?state=wrong&code=fixture-code', target.replace('fixture-code', '')]:
                            invalid.append((await http(ctx.webServer.getOrigin(), bad))['status'])
                        invalid.append((await http(ctx.webServer.getOrigin(), target, 'POST'))['status'])
                    if mode == 'cancel-waiting': await account.cancelSignIn(state['attempt']['id'])
                    elif mode != 'expire-waiting':
                        pending = asyncio.create_task(http(ctx.webServer.getOrigin(), target))
                        if mode in ('duplicate-callback', 'cancel-exchanging'):
                            # Python 3.8's Windows loop can service 2ms sleeps early
                            # within its clock resolution; count a real Event wait,
                            # rather than spending a fixed number of fast iterations.
                            reached = await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(
                                None, exchange_entered.wait, 2), 2.5)
                            assert reached, dict(mode=mode, state=await account.getState())
                            if mode == 'duplicate-callback': invalid.append((await http(ctx.webServer.getOrigin(), target))['status'])
                            else: await account.cancelSignIn(state['attempt']['id'])
                            exchange_gate.set()
                        if mode == 'commit-cancel':
                            await asyncio.wait_for(commit_entered.wait(), 3)
                            cancel = asyncio.create_task(account.cancelSignIn(state['attempt']['id'])); await asyncio.sleep(0)
                            assert not cancel.done(); commit_gate.set_result(None); await cancel
                        callback = await pending
                await asyncio.wait_for(asyncio.shield(account.attempt.done), 5)
                final = await account.getState(); phase = final['attempt']['phase']
                selected = {key: final['attempt'][key] for key in ('phase', 'errorCode') if key in final['attempt']}
                if 'authorizeUrl' in final['attempt']: selected['authorizeUrl'] = final['attempt']['authorizeUrl'].replace(origin, '<platform>')
                profile = await account.getProfile(client) if phase == 'succeeded' else None
                stored = records.get(KEY)
                if stored is not None:
                    assert stored['payload']['issuer'] == origin
                    stored = dict(stored, payload=dict(stored['payload'], issuer='<platform>'))
                result = dict(initialPhase=start['attempt']['phase'], joinSame=join_same, final=dict(status=final['status'], attempt=selected),
                              callback=normalized_callback(callback, origin), invalid=invalid, stored=stored,
                              profile=profile, routeGone=ctx.webServer.match('/oauth/callback') is None,
                              flowInFlight=ctx.authorization.describe(KEY)['inFlight'])
            finally:
                if not commit_gate.done(): commit_gate.set_result(None)
                exchange_gate.set(); init_gate.set()
                await ctx.fiber.dispose(); server.shutdown(); server.server_close(); thread.join()
            rows.append(dict(mode=mode, result=result, hits=hits, verification=verification, diagnostics=logs))
        return rows
    finally:
        protocol._diagnostic = original_log; account_module._diagnostic = original_account_log


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_account_login.mts', 'Actual canonical browser callbacks and Platform HTTP: PKCE, commit, cancellation, expiration and failure documents.',
        [Path(__file__).resolve(), ROOT/'dsh/credentials/deepseek_account_current.py', ROOT/'dsh/credentials/account_state.py'], prepare=prepare)
