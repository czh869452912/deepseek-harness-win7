"""Browser PKCE account authorization on the canonical reversible WebServer."""
import asyncio
import base64
import hashlib
import hmac
import platform
import secrets
import sys
import time
import uuid
from types import SimpleNamespace
from urllib.parse import parse_qsl, quote_plus, urlsplit

from dsh.cordis.awaiting import start_coroutine, await_callback_result
from dsh.cordis.utils import _UNDEFINED, _js_typeof
from dsh.core.abort import AbortController
from dsh.core.cancellation import subscribe_abort
from dsh.credentials.account_state import AccountState, KEY, DEVICE, deviceOsVersion
from dsh.credentials.account_client_metadata import platformClientHeaders, platformWireLocale
from dsh.credentials.account_details import profile
from dsh.credentials.account_errors import PlatformAuthError
from dsh.credentials.account_lifetime import AccountRequestLifetime
from dsh.credentials.account_payloads import parsePayload, payloadIssues
from dsh.credentials.account_protocol import requestPlatform, browserUrl, loginOrigin, _diagnostic
from dsh.credentials.account_urls import _url
from dsh.typert.remote import Remote


def _random(length):
    return base64.urlsafe_b64encode(secrets.token_bytes(length)).decode('ascii').rstrip('=')


def _now():
    return int(time.time()*1000)


def _completion(value, source):
    parsed = urlsplit(value); entries = parse_qsl(parsed.query, keep_blank_values=True, errors='replace')
    result = []; found = False
    for key, item in entries:
        if key == 'login_source':
            if not found:
                result.append((key, source)); found = True
        else:
            result.append((key, item))
    if not found:
        result.append(('login_source', source))
    def encode(item):
        return quote_plus(item, safe='*-._').replace('~', '%7E')
    query = '&'.join(encode(key)+'='+encode(item) for key, item in result)
    return parsed.scheme+'://'+parsed.netloc+parsed.path+'?'+query+('#' if '#' in value else '')


class CurrentDeepSeekAccount(AccountState):
    @Remote
    async def startSignIn(self, client, callbackOrigin, loginSource):
        if self.removing is not None:
            await asyncio.shield(self.removing)
        origin = loginOrigin(callbackOrigin)
        if self.closed:
            raise PlatformAuthError('protocol')
        if self.attempt is not None and self.attempt.view['phase'] in ('initializing', 'waiting-browser', 'exchanging', 'committing'):
            return await self.getState()
        previous = self.attempt
        if previous is not None:
            await asyncio.shield(previous.done)
            if self.closed:
                raise PlatformAuthError('protocol')
            if self.attempt is not previous:
                return await self.getState()
        loop = asyncio.get_running_loop()
        settled = loop.create_future(); settled.set_result(None)
        attempt = SimpleNamespace(origin=origin, loginSource=loginSource, locale=platformWireLocale(client['locale']),
                                  clientHeaders=platformClientHeaders(self.platform, client),
                                  view=dict(id=str(uuid.uuid4()), phase='initializing'), controller=AbortController(),
                                  done=settled, running=settled, disposeCallback=None, callback=None, initialProfile=None,
                                  completionUrl=None, callbackFinished=loop.create_future())
        self.attempt = attempt
        attempt.done = start_coroutine(self._settleAttempt(attempt))
        self.changed('snapshot')
        return await self.getState()

    async def _settleAttempt(self, attempt):
        async def no_prompt(*_):
            raise PlatformAuthError('protocol')
        try:
            outcome = await self.ctx.authorization.begin(dict(key=KEY, signal=attempt.controller.signal,
                interaction=dict(notify=lambda *_: None, prompt=no_prompt)))
            self.update(attempt, dict(phase='succeeded' if outcome['status'] == 'authorized' else 'cancelled'))
            if outcome['status'] == 'authorized' and attempt.completionUrl is not None:
                await self.finishCallback(attempt, 302, {'location': attempt.completionUrl, 'cache-control': 'no-store'})
            else:
                await self.finishCallback(attempt, 204, {'cache-control': 'no-store'})
        except Exception as error:
            code = error.code if isinstance(error, PlatformAuthError) else 'protocol'
            _diagnostic('sign-in failed', dict(errorCode=code))
            self.update(attempt, dict(phase='expired' if code == 'expired' else 'failed', errorCode=code))
            await self.finishFailedCallback(attempt)
        finally:
            try:
                await asyncio.shield(attempt.running)
            except Exception:
                pass
            if attempt.callback is not None:
                await asyncio.shield(attempt.callbackFinished)
            if attempt.disposeCallback is not None:
                await await_callback_result(attempt.disposeCallback())

    @Remote
    async def cancelSignIn(self, attemptId):
        attempt = self.attempt
        if attempt is not None and attempt.view['id'] == attemptId:
            if attempt.view['phase'] != 'committing':
                attempt.controller.abort(); self.ctx.authorization.cancel(KEY)
            await asyncio.shield(attempt.done)
        return await self.getState()

    async def finishCallback(self, attempt, status, headers, body=None):
        if attempt.callback is None:
            return
        response = attempt.callback
        try:
            response.write_status(status)
            for key, value in headers.items():
                response.write_header(key, value)
            if body is not None:
                response.write_body(body.encode('utf-8'))
            await response.finish()
        except (OSError, RuntimeError):
            # A browser closing its callback tab never changes an authorization
            # outcome whose credential write has already settled.
            pass
        finally:
            if not attempt.callbackFinished.done():
                attempt.callbackFinished.set_result(None)

    async def finishFailedCallback(self, attempt):
        if attempt.loginSource != 'web':
            await self.finishCallback(attempt, 204, {'cache-control': 'no-store'})
            return
        nonce = _random(16)
        message = '登录失败，请关闭此标签页并在原页面重试。' if attempt.locale == 'zh_CN' else 'Sign-in failed. Close this tab and try again in the original tab.'
        language = 'zh-CN' if attempt.locale == 'zh_CN' else 'en'
        headers = {'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store',
                   'content-security-policy': "default-src 'none'; script-src 'nonce-"+nonce+"'; frame-ancestors 'none'",
                   'referrer-policy': 'no-referrer'}
        body = '<!doctype html><html lang="'+language+'"><meta charset="utf-8"><title>'+message+'</title>'
        body += '<body><p>'+message+'</p><script nonce="'+nonce+'">window.close()</script></body></html>'
        await self.finishCallback(attempt, 200, headers, body)

    def rejectPayload(self, stage, kind, value):
        issues = []
        for issue in payloadIssues(kind, value):
            item = value
            for key in issue['path']:
                item = item.get(key, _UNDEFINED) if isinstance(item, dict) else _UNDEFINED
            received = 'null' if item is None else 'array' if isinstance(item, list) else _js_typeof(item)
            issues.append(dict(issue, receivedType=received))
        _diagnostic('payload rejected', dict(stage=stage, issues=issues))
        raise PlatformAuthError('protocol')

    async def request(self, method, body, signal, headers):
        with AccountRequestLifetime(signal, self.requestTimeout) as fused:
            return await requestPlatform(self.origin, method, body, fused, dict(self.requestHeaders, **headers))

    def cancelRequest(self, authorizeId, verifier, headers):
        if self.closed:
            return
        async def cancel():
            try:
                await self.request('auth_cancel', dict(authorize_id=authorizeId, code_verifier=verifier), self.logoutLifetime.signal, headers)
            except Exception:
                pass
        future = start_coroutine(cancel()); self.revocations.add(future); future.add_done_callback(self.revocations.discard)

    async def runLogin(self, session, attempt):
        web = self.ctx.get('webServer')
        if web is None:
            raise PlatformAuthError('protocol')
        verifier = _random(32); state = _random(32)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode('ascii').rstrip('=')
        authorize_id = None; code = asyncio.get_running_loop().create_future()
        code.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        deadline = AbortController(); expires_at = _now()+self.attemptTimeout; fused = AbortController()
        relay_session = subscribe_abort(session.signal, lambda *_: fused.abort(session.signal.reason))
        relay_deadline = subscribe_abort(deadline.signal, lambda *_: fused.abort(deadline.signal.reason))
        signal = fused.signal
        timer = asyncio.get_running_loop().call_later(self.attemptTimeout/1000, deadline.abort)
        def abort(*_):
            if not code.done():
                code.set_exception(PlatformAuthError('expired'))
        relay_code = subscribe_abort(signal, abort)
        try:
            async def callback(request, response):
                try:
                    raw = request.get('raw_url', request.get('url', '/'))
                    parsed = urlsplit(raw); pairs = parse_qsl(parsed.query, keep_blank_values=True, errors='replace')
                except ValueError:
                    response.write_status(400); response.write_header('cache-control', 'no-store'); await response.finish(); return
                states = [value for key, value in pairs if key == 'state']; codes = [value for key, value in pairs if key == 'code']
                received_state = states[0] if states else ''
                valid_state = hmac.compare_digest(received_state.encode('utf-8', 'replace'), state.encode('ascii'))
                if request.get('method') != 'GET' or parsed.path != '/oauth/callback' or not valid_state or len(states) != 1 or len(codes) != 1 or not codes[0]:
                    response.write_status(400); response.write_header('cache-control', 'no-store'); await response.finish(); return
                if signal.aborted or attempt.callback is not None or attempt.view['phase'] != 'waiting-browser':
                    response.write_status(410); response.write_header('cache-control', 'no-store'); await response.finish(); return
                attempt.callback = response; code.set_result(codes[0])
                await asyncio.shield(attempt.callbackFinished)
            attempt.disposeCallback = self.ctx.effect(lambda: web.register(dict(kind='exact', path='/oauth/callback', handler=callback)), 'account: browser callback')
            signal.throw_if_aborted()
            redirect_uri = attempt.origin+'/oauth/callback'
            raw = await self.request('auth_init', dict(code_challenge=challenge, code_challenge_method='S256', state=state,
                redirect_uri=redirect_uri, locale=attempt.locale, login_source=attempt.loginSource), signal, attempt.clientHeaders)
            if payloadIssues('initialization', raw):
                self.rejectPayload('auth_init', 'initialization', raw)
            initialization = parsePayload('initialization', raw)
            authorize_url = browserUrl(initialization['authorize_url'], self.origin, '/dsh/authorize', self.rewriteBrowserOrigin)
            authorize_id = initialization['authorize_id']; signal.throw_if_aborted()
            now = _now(); expires_at = min(expires_at, now+initialization['expires_in']*1000); remaining = expires_at-now
            if remaining <= 0:
                deadline.abort(); signal.throw_if_aborted()
            timer.cancel(); timer = asyncio.get_running_loop().call_later(remaining/1000, deadline.abort)
            self.update(attempt, dict(phase='waiting-browser', authorizeUrl=authorize_url, expiresAt=expires_at))
            received_code = await asyncio.shield(code); signal.throw_if_aborted()
            self.update(attempt, dict(phase='exchanging'))
            record = await await_callback_result(self.ctx.credentials.modifyRecord(DEVICE,
                lambda current: dict(kind='grant', payload=dict(id=str(uuid.uuid4()))) if current is None else None))
            if not isinstance(record, dict) or record.get('kind') != 'grant':
                raise PlatformAuthError('storage')
            payload = record.get('payload')
            device_id = payload.get('id') if isinstance(payload, dict) else None
            # The same UUID acceptance contract is used by getDeviceIdentity.
            import re
            if not isinstance(device_id, str) or re.fullmatch(r'(?:[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|00000000-0000-0000-0000-000000000000|ffffffff-ffff-ffff-ffff-ffffffffffff)', device_id, re.I) is None:
                raise PlatformAuthError('protocol')
            architecture = platform.machine().lower(); architecture = 'x64' if architecture in ('amd64', 'x86_64') else 'arm64' if architecture in ('arm64', 'aarch64') else 'ia32' if architecture in ('x86', 'i386', 'i686') else architecture
            host = 'win32' if sys.platform == 'win32' else 'darwin' if sys.platform == 'darwin' else 'linux'
            raw = await self.request('auth_exchange', dict(code=received_code, code_verifier=verifier, redirect_uri=redirect_uri,
                device_id=device_id, device_model=host+'-'+architecture, os_version=deviceOsVersion()), signal, attempt.clientHeaders)
            if payloadIssues('exchange', raw):
                self.rejectPayload('auth_exchange', 'exchange', raw)
            result = parsePayload('exchange', raw)
            attempt.completionUrl = _completion(browserUrl(result['authorized_url'], self.origin, '/dsh/authorized', self.rewriteBrowserOrigin), attempt.loginSource)
            if _now() >= expires_at:
                deadline.abort()
            signal.throw_if_aborted()
            if result.get('user') is not None:
                try:
                    attempt.initialProfile = dict(token=result['token'], value=dict(status='ready', value=profile(result['user'])))
                except Exception:
                    pass
            self.update(attempt, dict(phase='committing')); timer.cancel()
            try:
                await session.commit(dict(kind='grant', payload=dict(version=1, token=result['token'], issuer=self.origin)))
            except Exception:
                raise PlatformAuthError('storage') from None
        except Exception:
            if deadline.signal.aborted:
                raise PlatformAuthError('expired') from None
            raise
        finally:
            if signal.aborted and authorize_id is not None:
                self.cancelRequest(authorize_id, verifier, attempt.clientHeaders)
            timer.cancel(); relay_code(); relay_deadline(); relay_session()
