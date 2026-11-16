"""Asynchronous rc.3 authorization ownership and admitted credential commits."""
import asyncio
import inspect
from types import SimpleNamespace

from dsh.cordis.awaiting import start_coroutine, await_callback_result
from dsh.cordis.service import Service
from dsh.core.abort import AbortController
from dsh.core.cancellation import subscribe_abort
from dsh.credentials.authorization import AuthorizationError, AuthorizationDeclinedError
from dsh.typert.stores import field


class CurrentAuthorizationService(Service):
    inject = ['credentials']

    def __init__(self, ctx):
        super().__init__(ctx, 'authorization')
        self.flows = {}; self.running = {}

    def registerFlow(self, flow):
        key = field(flow, 'key')
        if key in self.flows:
            raise AuthorizationError('an authorization flow for "'+key+'" is already registered', 'DUPLICATE_FLOW')
        self.flows[key] = flow
        def dispose():
            self.flows.pop(key, None)
            self.cancel(key)
        return self.ctx.effect(lambda: dispose, 'authorization.registerFlow()')

    register_flow = registerFlow

    def _entry(self, flow):
        return dict(key=field(flow, 'key'), label=field(flow, 'label'), methods=field(flow, 'methods'),
                    inFlight=field(flow, 'key') in self.running)

    def list(self):
        return [self._entry(flow) for flow in self.flows.values()]

    def describe(self, key):
        return self._entry(self.flows[key]) if key in self.flows else None

    def cancel(self, key):
        active = self.running.get(key)
        if active is not None and not active.committing:
            active.controller.abort()

    def begin(self, request):
        return start_coroutine(self._begin(request))

    async def _begin(self, request):
        key = request['key']; flow = self.flows.get(key)
        if flow is None:
            raise AuthorizationError('no authorization flow is registered for "'+key+'"', 'NO_FLOW')
        methods = field(flow, 'methods')
        method = request.get('method')
        if method is None:
            method = field(methods[0], 'id')
        if not any(field(candidate, 'id') == method for candidate in methods):
            raise AuthorizationError('authorization flow for "'+key+'" offers no method "'+method+'"', 'UNKNOWN_METHOD')
        if key in self.running:
            raise AuthorizationError('an authorization attempt for "'+key+'" is already running', 'ALREADY_IN_FLIGHT')
        signal = request.get('signal')
        if signal is not None and signal.aborted:
            return dict(status='cancelled')
        controller = AbortController()
        def withdraw(*_):
            active = self.running.get(key)
            if active is not None and not active.committing:
                controller.abort(signal.reason)
        # No synchronous callback occurs here: the pre-aborted case returned above.
        dispose = subscribe_abort(signal, withdraw)
        self.running[key] = SimpleNamespace(controller=controller, committing=False)
        settlement = 'failed'
        try:
            outcome = await self._attempt(flow, method, controller.signal, request['interaction'])
            settlement = outcome['status']
            return outcome
        finally:
            dispose(); self.running.pop(key, None); self._settle(key, settlement)

    def _warnListener(self, key, error):
        self.ctx.logger.warn('authorization: an authorization/settled listener for "%s" failed', key)
        self.ctx.logger.warn(error)

    def _settle(self, key, settlement):
        for listener in self.ctx.events._dispatch_hooks('emit', 'authorization/settled', self.ctx):
            try:
                result = listener(key, settlement)
                if inspect.isawaitable(result):
                    future = start_coroutine(result) if inspect.iscoroutine(result) else asyncio.ensure_future(result)
                    def observed(done, key=key):
                        try:
                            done.result()
                        except BaseException as error:
                            self._warnListener(key, error)
                    future.add_done_callback(observed)
            except Exception as error:
                self._warnListener(key, error)

    async def _attempt(self, flow, method, signal, interaction):
        key = field(flow, 'key'); observed = dict(declined=False, committed=False)
        withdrawn = asyncio.get_running_loop().create_future()
        def on_abort(*_):
            if not withdrawn.done():
                withdrawn.set_result(None)
        dispose = subscribe_abort(signal, on_abort)
        def on_record(updated):
            if updated == key:
                observed['committed'] = True
        unwatch = self.ctx.on('credentials/record-updated', on_record)
        async def commit_owned(record):
            signal.throw_if_aborted()
            active = self.running.get(key)
            if active is None or active.controller.signal is not signal:
                raise AuthorizationError('authorization attempt is no longer active', 'CANCELLED')
            active.committing = True
            # The callback is synchronous in Python so both native synchronous
            # stores and async providers can consume the same record contract.
            await await_callback_result(self.ctx.credentials.modifyRecord(key, lambda *_: record))
        def notify(notice):
            try:
                field(interaction, 'notify')(notice)
            except Exception as error:
                self.ctx.logger.warn('authorization: the interaction surface failed to render a notice')
                self.ctx.logger.warn(error)
        async def prompt_owned(value):
            try:
                return await await_callback_result(field(interaction, 'prompt')(value))
            except AuthorizationDeclinedError:
                observed['declined'] = True
                raise
        session = SimpleNamespace(method=method, signal=signal,
                                  commit=lambda record: start_coroutine(commit_owned(record)), notify=notify,
                                  prompt=lambda value: start_coroutine(prompt_owned(value)))
        running = None
        try:
            result = field(flow, 'run')(session)
            if inspect.iscoroutine(result):
                running = start_coroutine(result)
            elif inspect.isawaitable(result):
                running = asyncio.ensure_future(result)
            else:
                running = asyncio.get_running_loop().create_future(); running.set_result(result)
            def observe_late(done):
                try:
                    done.result()
                except BaseException:
                    self.ctx.logger.debug('authorization: withdrawn flow failed after the fact')
            try:
                # race() installs the running continuation first, including an
                # already-settled run, so completion wins a simultaneous abort.
                if not running.done():
                    await asyncio.wait([running, withdrawn], return_when=asyncio.FIRST_COMPLETED)
                if withdrawn.done() and not running.done():
                    running.add_done_callback(observe_late)
                    return dict(status='cancelled')
                running.result()
            except Exception:
                if signal.aborted or observed['declined']:
                    return dict(status='cancelled')
                raise
        finally:
            unwatch(); dispose()
            if running is not None and not running.done():
                # Native Task cancellation also releases the key, but cannot
                # leave an unobserved flow rejection behind.
                running.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        if not observed['committed']:
            raise AuthorizationError('authorization flow for "'+key+'" resolved without committing a credential record in this attempt', 'NOT_COMMITTED')
        stored = await await_callback_result(self.ctx.credentials.describeRecord(key))
        if not field(stored, 'configured'):
            raise AuthorizationError('authorization flow for "'+key+'" deleted its credential record instead of committing one', 'NOT_COMMITTED')
        return dict(status='authorized')
