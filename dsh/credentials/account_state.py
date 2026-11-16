"""Account credential ownership, query lifetimes and safe ordered state streams.

The browser authorization runner is supplied by the complete account provider;
this component owns the credential and client projection contracts it consumes.
"""
import asyncio
import sys
import platform as native_platform
import re

from dsh.cordis.awaiting import start_coroutine, await_callback_result
from dsh.cordis.schema import Schema
from dsh.cordis.utils import _UNDEFINED
from dsh.core.abort import AbortController
from dsh.core.cancellation import subscribe_abort
from dsh.credentials.account_client_metadata import mergePlatformCookies, platformClientHeaders
from dsh.credentials.account_details import readAccountDetail
from dsh.credentials.account_errors import PlatformAuthError, AccountUnauthorizedError
from dsh.credentials.account_lifetime import AccountRequestLifetime
from dsh.credentials.account_logout import revokeAccount
from dsh.credentials.account_notifications import readNotifications, readNotificationContent, sendNotificationEvent
from dsh.credentials.account_payloads import _isUrl
from dsh.credentials.account_protocol import platformHeaders, platformOrigin
from dsh.credentials.account_urls import _url
from dsh.typert.remote import TypertRemoteService, Remote
from dsh.typert.stores import field

KEY = 'deepseek-account-platform/default'
DEVICE = 'deepseek-account-platform/device'
DEFAULTS = dict(platformOrigin='https://platform.deepseek.com', harnessOrigin='https://harness.deepseek.com',
                desktopPlatform=None, embeddedPageDist='', inferenceOrigin='https://api.deepseek.com',
                allowLoopbackHttp=False, rewriteBrowserOrigin=False, requestHeaders={}, accountRequestHeaders={},
                requestTimeoutMs=30000, balanceTimeoutMs=30000, logoutMaxRetries=5, logoutRetryDelayMs=1000, attemptTimeoutMs=600000)


def configSchema():
    entries = {key: Schema.string().default(DEFAULTS[key]) for key in
               ('platformOrigin', 'harnessOrigin', 'embeddedPageDist', 'inferenceOrigin')}
    entries.update({key: Schema.boolean().default(DEFAULTS[key]) for key in ('allowLoopbackHttp', 'rewriteBrowserOrigin')})
    entries.update({key: Schema.dict(Schema.string().role('secret')).default({}) for key in ('requestHeaders', 'accountRequestHeaders')})
    entries['desktopPlatform'] = Schema.union([Schema.const('darwin'), Schema.const('win32'), Schema.const(None)]).default(None)
    for key, minimum, maximum in [('requestTimeoutMs', 1, 120000), ('balanceTimeoutMs', 1, 120000),
                                 ('logoutMaxRetries', 0, 5), ('logoutRetryDelayMs', 1, 60000), ('attemptTimeoutMs', 1, 3600000)]:
        schema = Schema.number().min(minimum).max(maximum).default(DEFAULTS[key])
        if key == 'logoutMaxRetries':
            schema = schema.step(1)
        entries[key] = schema
    return Schema.object(entries)


def grantPayload(record):
    if not isinstance(record, dict) or record.get('kind') != 'grant':
        raise PlatformAuthError('storage')
    payload = record.get('payload')
    if (not isinstance(payload, dict) or type(payload.get('version')) not in (int, float) or payload['version'] != 1 or
        not isinstance(payload.get('token'), str) or not payload['token'] or not _isUrl(payload.get('issuer'))):
        raise PlatformAuthError('storage')
    return {key: payload[key] for key in ('version', 'token', 'issuer')}


def deviceOsVersion():
    if sys.platform == 'win32':
        version = sys.getwindowsversion()
        return 'win32 '+'.'.join(str(value) for value in (version.major, version.minor, version.build))
    return ('darwin' if sys.platform == 'darwin' else 'linux')+' '+native_platform.release()


def isRunningAccountTask(agent):
    if field(agent, 'status') != 'running':
        return False
    session = field(agent, 'session')
    context = session.requestContext()
    return field(context, 'provider') == 'deepseek-account' if context is not None else False


def installAccountTaskCancellation(ctx):
    def install(scope):
        from dsh.llm.llm_service import LlmError
        def on_error(value):
            error = field(value, 'error')
            if isinstance(error, LlmError) and error.code == 'ACCOUNT_SIGN_IN_REQUIRED':
                scope.emit('deepseek-account/model-sign-in-required')
        scope.on('agent/error', on_error)
        def signed_out():
            for agent in scope.agents.list():
                if isRunningAccountTask(agent):
                    agent.cancel(dict(kind='hook', reason='deepseek-account/signed-out'), dict(keepInbox=True))
        scope.on('deepseek-account/signed-out', signed_out)
    ctx.inject(['agents'], install)


class AccountState(TypertRemoteService):
    inject = ['credentials', 'authorization']
    Config = configSchema()

    def __init__(self, ctx, config=None):
        super().__init__(ctx, 'deepseekAccount', dict(namespace='account'))
        installAccountTaskCancellation(ctx)
        resolved = self.Config(config or {})
        self.origin = platformOrigin(resolved['platformOrigin'], resolved['allowLoopbackHttp'], 'platformOrigin')
        self.harnessOrigin = platformOrigin(resolved['harnessOrigin'], resolved['allowLoopbackHttp'], 'harnessOrigin')
        inference = _url(resolved['inferenceOrigin'])
        if (inference['protocol'] not in ('http:', 'https:') or inference['credentials'] or inference['pathname'] != '/' or
            inference['search'] or inference['hash']):
            raise ValueError('account: inferenceOrigin must be an HTTP(S) origin without credentials, path, query or fragment')
        self.inferenceOrigin = inference['origin']; self.embeddedPageDist = resolved['embeddedPageDist']
        self.rewriteBrowserOrigin = resolved['rewriteBrowserOrigin']; self.platform = resolved.get('desktopPlatform', _UNDEFINED)
        self.requestHeaders = platformHeaders(resolved['requestHeaders']); overrides = platformHeaders(resolved['accountRequestHeaders'])
        self.accountRequestHeaders = dict(self.requestHeaders, **overrides)
        if 'cookie' in overrides:
            self.accountRequestHeaders['cookie'] = mergePlatformCookies(self.requestHeaders.get('cookie', ''), overrides['cookie'])
        self.requestTimeout = resolved['requestTimeoutMs']; self.balanceTimeout = resolved['balanceTimeoutMs']; self.attemptTimeout = resolved['attemptTimeoutMs']
        self.logoutPolicy = dict(maxRetries=resolved['logoutMaxRetries'], delayMs=resolved['logoutRetryDelayMs'], requestTimeoutMs=self.requestTimeout)
        self.logoutLifetime = AbortController(); self.revocations = set(); self.attempt = None; self.listeners = []
        self.lastProfile = None; self.detailsLifetime = AbortController(); self.closed = False; self.removing = None
        def run(session):
            if self.attempt is None:
                raise PlatformAuthError('protocol')
            self.attempt.running = start_coroutine(self.runLogin(session, self.attempt))
            return self.attempt.running
        ctx.authorization.registerFlow(dict(key=KEY, label='DeepSeek', methods=[dict(id='browser', label='DeepSeek')], run=run))
        def updated(key):
            if key == KEY:
                self.invalidateDetails(); self.changed('credentials-changed')
        ctx.on('credentials/record-updated', updated)
        ctx.effect(lambda: self.close, 'account: active attempt lifetime')

    async def initialize(self):
        record = await await_callback_result(self.ctx.credentials.readRecord(KEY))
        if record is None:
            return
        payload = grantPayload(record)
        if payload['issuer'] != self.origin:
            await await_callback_result(self.ctx.credentials.deleteRecord(KEY))

    async def close(self):
        self.closed = True; self.logoutLifetime.abort(); self.invalidateDetails()
        active = self.attempt
        if active is not None:
            if active.view['phase'] != 'committing':
                active.controller.abort()
            await asyncio.shield(active.done)
        if self.removing is not None:
            await asyncio.shield(self.removing)
        if self.revocations:
            await asyncio.gather(*tuple(self.revocations))
        self.changed('snapshot')

    @Remote
    async def getState(self):
        record = await await_callback_result(self.ctx.credentials.readRecord(KEY))
        if record is not None:
            grantPayload(record)
        attempt = self.attempt.view if self.attempt is not None else None
        if record is None and attempt is not None and attempt['phase'] == 'succeeded':
            attempt = None
        return dict(status='signed-out' if record is None else 'credential-stored', attempt=attempt,
                    links=dict(usageUrl=self.origin+'/usage', topUpUrl=self.origin+'/top_up'))

    async def readCurrentGrant(self, lifetime):
        if self.closed:
            return None
        record = await await_callback_result(self.ctx.credentials.readRecord(KEY))
        if record is None or lifetime.signal.aborted:
            return None
        payload = grantPayload(record)
        if payload['issuer'] != self.origin:
            raise PlatformAuthError('protocol')
        return payload

    def detailHeaders(self, client):
        return dict(self.accountRequestHeaders, **platformClientHeaders(self.platform, client))

    async def resolveToken(self, url):
        if self.closed or self.removing is not None:
            return None
        destination = _url(url)
        if destination['origin'] != self.inferenceOrigin or destination['credentials']:
            return None
        record = await await_callback_result(self.ctx.credentials.readRecord(KEY))
        if record is None:
            return None
        payload = grantPayload(record); issuer = _url(payload['issuer'])
        if payload['token'].startswith('dsh_mock_'):
            return None
        if self.inferenceOrigin == 'https://api.deepseek.com':
            if issuer['hostname'] in ('localhost', '127.0.0.1', '[::1]'):
                return None
        elif issuer['origin'] != self.origin:
            return None
        return payload['token']

    async def getPlatformSession(self):
        lifetime = self.detailsLifetime; stored = await self.readCurrentGrant(lifetime)
        if stored is None or lifetime.signal.aborted:
            return None
        cached = self.lastProfile
        result = dict(origin=self.origin, token=stored['token'], requestHeaders=dict(self.accountRequestHeaders),
                      userId=(cached['profile']['value']['id'] or None) if cached is not None and cached['token'] == stored['token'] else None)
        if self.embeddedPageDist:
            result['embeddedPageDist'] = self.embeddedPageDist
        return result

    async def getDeviceIdentity(self):
        record, session = await asyncio.gather(await_callback_result(self.ctx.credentials.readRecord(DEVICE)), self.getPlatformSession())
        result = dict(osVersion=deviceOsVersion())
        payload = record.get('payload') if isinstance(record, dict) and record.get('kind') == 'grant' else None
        identity = payload.get('id') if isinstance(payload, dict) else None
        if isinstance(identity, str) and re.fullmatch(r'(?:[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|00000000-0000-0000-0000-000000000000|ffffffff-ffff-ffff-ffff-ffffffffffff)', identity, re.I):
            result['deviceId'] = identity
        if session is not None and session['userId'] is not None:
            result['userId'] = session['userId']
        return result

    def cacheProfile(self, token, profile):
        if profile['status'] != 'ready':
            return
        previous = self.lastProfile['profile']['value']['id'] or None if self.lastProfile else None
        self.lastProfile = dict(token=token, profile=profile)
        if previous != (profile['value']['id'] or None):
            self.changed('identity')

    async def getDetail(self, field, headers, captured=None):
        lifetime, stored = captured if captured is not None else (self.detailsLifetime, None)
        if stored is None:
            stored = await self.readCurrentGrant(lifetime)
        if stored is None or lifetime.signal.aborted:
            return None
        initial = getattr(self.attempt, 'initialProfile', None)
        if field == 'profile' and initial is not None and initial['token'] == stored['token']:
            self.attempt.initialProfile = None
            return initial['value']
        try:
            with AccountRequestLifetime(lifetime.signal, self.balanceTimeout if field == 'balance' else self.requestTimeout) as signal:
                details = await readAccountDetail(field, self.origin, stored['token'], signal, headers)
            return None if self.detailsLifetime is not lifetime else details
        except Exception:
            if self.detailsLifetime is lifetime:
                await self.expireCredential(stored['token'], lifetime)
            return None

    @Remote
    async def getProfile(self, client):
        lifetime = self.detailsLifetime; stored = await self.readCurrentGrant(lifetime)
        if stored is None or lifetime.signal.aborted:
            return None
        result = await self.getDetail('profile', self.detailHeaders(client), (lifetime, stored))
        if self.detailsLifetime is not lifetime:
            return None
        if result is not None:
            self.cacheProfile(stored['token'], result)
        if result is None or result['status'] != 'failed':
            return result
        return self.lastProfile['profile'] if self.lastProfile is not None and self.lastProfile['token'] == stored['token'] else result

    @Remote
    async def getBalance(self, client):
        return await self.getDetail('balance', self.detailHeaders(client))

    async def notificationQuery(self, method, args, client, fallback):
        lifetime = self.detailsLifetime; headers = self.detailHeaders(client); stored = await self.readCurrentGrant(lifetime)
        if stored is None:
            return fallback
        try:
            with AccountRequestLifetime(lifetime.signal, self.requestTimeout) as signal:
                result = await method(self.harnessOrigin, stored['token'], *args, signal, headers)
            if self.detailsLifetime is not lifetime:
                return fallback
            return True if method is sendNotificationEvent else result
        except Exception as error:
            if self.detailsLifetime is not lifetime:
                return fallback
            if isinstance(error, AccountUnauthorizedError):
                await self.expireCredential(stored['token'], lifetime)
                return fallback
            raise

    @Remote
    async def getNotifications(self, client):
        return await self.notificationQuery(readNotifications, (), client, None)

    @Remote
    async def getNotificationContent(self, id, client):
        return await self.notificationQuery(readNotificationContent, (id,), client, None)

    @Remote
    async def reportNotificationEvent(self, id, event, client):
        return await self.notificationQuery(sendNotificationEvent, (id, event), client, False)

    async def rejectToken(self, token):
        lifetime = self.detailsLifetime; stored = await self.readCurrentGrant(lifetime)
        if stored is None or stored['token'] != token or self.detailsLifetime is not lifetime:
            return
        await self.expireCredential(token, lifetime)

    def expireCredential(self, token, lifetime):
        if self.removing is None:
            self.removing = start_coroutine(self._expireCredential(token, lifetime))
            self.removing.add_done_callback(self._clearRemoving)
        return asyncio.shield(self.removing)

    def _clearRemoving(self, done):
        if self.removing is done:
            self.removing = None

    async def _expireCredential(self, token, lifetime):
        if self.attempt is not None:
            await self.cancelSignIn(self.attempt.view['id'])
        record = await await_callback_result(self.ctx.credentials.readRecord(KEY))
        if self.closed or self.detailsLifetime is not lifetime or not isinstance(record, dict) or record.get('kind') != 'grant':
            return await self.getState()
        current = grantPayload(record)
        if current['token'] != token or current['issuer'] != self.origin:
            return await self.getState()
        await await_callback_result(self.ctx.credentials.deleteRecord(KEY))
        self.ctx.emit('deepseek-account/session-expired'); self.attempt = None
        self.ctx.emit('deepseek-account/signed-out'); self.changed('snapshot')
        return await self.getState()

    @Remote
    def signOut(self, client):
        if self.removing is None:
            self.removing = start_coroutine(self._signOut(client)); self.removing.add_done_callback(self._clearRemoving)
        return asyncio.shield(self.removing)

    async def _signOut(self, client):
        if self.closed:
            raise PlatformAuthError('protocol')
        if self.attempt is not None:
            await self.cancelSignIn(self.attempt.view['id'])
        record = await await_callback_result(self.ctx.credentials.readRecord(KEY))
        if record is not None:
            payload = grantPayload(record)
            if payload['issuer'] != self.origin:
                raise PlatformAuthError('protocol')
            await await_callback_result(self.ctx.credentials.deleteRecord(KEY))
            self.revoke(payload['token'], platformClientHeaders(self.platform, client))
        self.attempt = None; self.ctx.emit('deepseek-account/signed-out'); self.changed('snapshot')
        return await self.getState()

    @Remote
    def hasRunningAccountTasks(self):
        agents = self.ctx.get('agents')
        return any(isRunningAccountTask(agent) for agent in agents.list()) if agents is not None else False

    @Remote(dict(mode='stream'))
    async def watchExpiry(self, signal):
        pending = 0; wake = asyncio.Event()
        def expired():
            nonlocal pending
            pending += 1; wake.set()
        stop = self.ctx.on('deepseek-account/session-expired', expired)
        dispose = subscribe_abort(signal, lambda *_: wake.set())
        dispose_owner = subscribe_abort(self.logoutLifetime.signal, lambda *_: wake.set())
        try:
            while not signal.aborted and not self.logoutLifetime.signal.aborted:
                if pending:
                    pending -= 1; yield 'session-expired'
                    continue
                wake.clear(); await wake.wait()
        finally:
            stop(); dispose(); dispose_owner()

    def watch(self, signal, includeIdentityChanges=False):
        return self.observeUpdates(signal, includeIdentityChanges)

    @Remote(dict(name='watch', mode='stream'))
    def watchState(self, signal):
        return self.observeUpdates(signal, False)

    async def observeUpdates(self, signal, includeIdentityChanges):
        pending = 'snapshot'; wake = asyncio.Event()
        def changed(kind):
            nonlocal pending
            if kind == 'identity' and not includeIdentityChanges:
                return
            if kind == 'credentials-changed' or pending is None:
                pending = 'credentials-changed' if kind == 'credentials-changed' else 'snapshot'
            wake.set()
        self.listeners.append(changed); dispose = subscribe_abort(signal, lambda *_: wake.set())
        try:
            while not self.closed and not signal.aborted:
                if pending is not None:
                    kind, pending = pending, None; lifetime = self.detailsLifetime
                    state = await self.getState()
                    if lifetime is not self.detailsLifetime or signal.aborted or self.closed:
                        continue
                    yield dict(type=kind, state=state)
                    continue
                wake.clear(); await wake.wait()
        finally:
            self.listeners.remove(changed); dispose()

    def revoke(self, token, headers):
        if self.closed:
            return
        future = start_coroutine(revokeAccount(self.origin, token, self.logoutPolicy, self.logoutLifetime.signal, dict(self.requestHeaders, **headers)))
        self.revocations.add(future); future.add_done_callback(self.revocations.discard)

    def invalidateDetails(self):
        self.lastProfile = None; self.detailsLifetime.abort(); self.detailsLifetime = AbortController()

    def changed(self, kind):
        for listener in tuple(self.listeners):
            listener(kind)

    def update(self, attempt, value):
        attempt.view = dict((key, entry) for key, entry in attempt.view.items() if key != 'authorizeUrl')
        attempt.view.update(value); self.changed('snapshot')


setattr(AccountState, 'cordis.init', AccountState.initialize)
