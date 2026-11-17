"""Current inspect response deadlines and first-valid-page request ownership.

The previous registry remains available to historical pin-bound observations.
"""
import asyncio
import sys
from collections.abc import Coroutine

from dsh.cordis.awaiting import start_coroutine, await_callback_result
from dsh.cordis.json_text import stringify_json
from dsh.cordis.utils import _js_to_string_element
from dsh.core.abort import NEVER_ABORTED
from dsh.core.cancellation import aborted, subscribe_abort
from dsh.core.cleanup import CleanupPromise
from dsh.core.session.json import UNDEFINED
from dsh.extensions.inspect_registry import (CordisInspectRegistryService,
    _method, _input, _output, _throw_if_aborted)


class _QueryOperation(Coroutine):
    """Accept native Task cancellation even before its first scheduled step."""
    def __init__(self, coroutine):
        self.owned = CleanupPromise(start_coroutine(coroutine))
        self.waiting = self._wait()
        self.started = False

    async def _drain(self):
        if not self.owned.task.done():
            self.owned.task.cancel()
        try:
            await asyncio.shield(self.owned.task)
        except BaseException:
            pass

    async def _wait(self):
        try:
            return await self.owned
        except asyncio.CancelledError:
            await self._drain()
            raise

    async def _cancel_before_start(self, error):
        await self._drain()
        raise error

    def __await__(self):
        return self

    __iter__ = __await__

    def __next__(self):
        return self.send(None)

    def send(self, value):
        self.started = True
        return self.waiting.send(value)

    def throw(self, typ, value=None, traceback=None):
        error = typ if isinstance(typ, BaseException) else typ() if value is None else value
        if not self.started and isinstance(error, asyncio.CancelledError):
            self.waiting.close()
            self.waiting = self._cancel_before_start(error)
            return self.send(None)
        self.started = True
        return self.waiting.throw(typ, value, traceback)

    def close(self):
        if not self.owned.task.done():
            self.owned.task.cancel()
        self.waiting.close()


class CurrentCordisInspectRegistryService(CordisInspectRegistryService):
    def __init__(self, ctx, config=None):
        self.clientQueryTimeoutMs = 10000 if config is None else config
        super().__init__(ctx)

    def query(self, platform, provider, method_name, input, agent, signal):
        return _QueryOperation(self._query(platform, provider, method_name, input, agent,
                                      NEVER_ABORTED if signal is None else signal))

    async def _query(self, platform, provider, method_name, input, agent, signal):
        if platform != 'host':
            return await self.query_client(provider, method_name, input, agent, signal)
        registration = self._providers.get(provider)
        if registration is None:
            raise ValueError('Host Cordis inspect provider "{}" is not registered'.format(provider))
        method = _method(registration['manifest'], method_name)
        _input('Host', provider, method, input)
        _throw_if_aborted(signal)
        from types import SimpleNamespace
        value = await await_callback_result(registration['query'](method_name, input,
            SimpleNamespace(agent=agent, signal=signal)))
        _throw_if_aborted(signal)
        return _output('Host', provider, method, value)

    def _settle(self, request_id, resolution):
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        pending['future'].set_result(resolution)
        try:
            self.ctx.emit('cordis/inspect-query-resolved', dict(requestId=request_id))
        except Exception as error:
            print('[cordis-host-runner] notifying Client inspect completion failed:', error, file=sys.stderr)

    def resolve_client_query(self, agent, request_id, resolution):
        pending = self._pending.get(request_id)
        if pending is None or pending['request']['agentId'] != agent.id:
            return dict(accepted=False)
        if not resolution.get('ok'):
            if 'failure' not in pending:
                pending['failure'] = '{}: {}'.format(_js_to_string_element(resolution.get('reason', UNDEFINED)),
                    _js_to_string_element(resolution.get('message', UNDEFINED)))
            return dict(accepted=False)
        try:
            data = _output('Client', pending['request']['provider'], pending['method'], resolution.get('data', UNDEFINED))
        except Exception as error:
            if 'failure' not in pending:
                pending['failure'] = str(error)
            return dict(accepted=False)
        self._settle(request_id, dict(ok=True, data=data))
        return dict(accepted=True)

    def _cancel(self, request_id):
        pending = self._pending.get(request_id)
        if pending is None:
            return
        request = pending['request']
        self._settle(request_id, dict(ok=False, reason='cancelled',
            message='Client inspect query {}.{} was cancelled'.format(request['provider'], request['method'])))

    def query_client(self, provider_id, method_name, input, agent, signal):
        return _QueryOperation(self._query_client(provider_id, method_name, input, agent, signal))

    async def _query_client(self, provider_id, method_name, input, agent, signal):
        provider = next((row for row in self._client_manifest or [] if row['id'] == provider_id), None)
        if provider is None:
            raise ValueError('Client Cordis inspect provider "{}" is not registered'.format(provider_id))
        method = _method(provider, method_name)
        _input('Client', provider_id, method, input)
        _throw_if_aborted(signal)
        gateway = self.ctx.get('typertGateway')
        if gateway is not None and not gateway.hasLiveClient():
            raise RuntimeError('Client inspect query {}.{} has no connected Harness page. Open or reconnect the Harness page, then retry.'.format(provider_id, method_name))
        request_id = 'inspect-{}'.format(self._next_request)
        self._next_request += 1
        request = dict(requestId=request_id, agentId=agent.id, provider=provider_id, method=method_name)
        if input is not UNDEFINED:
            request['input'] = input
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = dict(request=request, method=method, future=future)
        def timeout():
            pending = self._pending.get(request_id)
            if pending is None:
                return
            detail = 'Client failure: ' + pending['failure'] if 'failure' in pending else 'Open or reconnect the Harness page, then retry.'
            self._settle(request_id, dict(ok=False, reason='provider-error', message=
                'Client inspect query {}.{} timed out after {}ms. {}'.format(provider_id, method_name,
                    stringify_json(self.clientQueryTimeoutMs), detail)))
        # The runner validates this integer to Node's [1, 2147483647] timer range.
        timer = asyncio.get_running_loop().call_later(self.clientQueryTimeoutMs / 1000, timeout)
        remove = subscribe_abort(signal, lambda *_: self._cancel(request_id))
        try:
            if aborted(signal):
                self._cancel(request_id)
            else:
                self.ctx.emit('cordis/inspect-query', request)
            resolution = await await_callback_result(asyncio.shield(future))
            if not resolution['ok']:
                raise RuntimeError('{}.{}: {}'.format(provider_id, method_name, resolution['message']))
            return resolution['data']
        except asyncio.CancelledError:
            self._cancel(request_id)
            raise
        finally:
            timer.cancel()
            remove()
            self._pending.pop(request_id, None)

    def close(self):
        for request_id in list(self._pending):
            self._settle(request_id, dict(ok=False, reason='cancelled', message='Client inspect registry was disposed'))

    resolveClientQuery = resolve_client_query
    queryClient = query_client
