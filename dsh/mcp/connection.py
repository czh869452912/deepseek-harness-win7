import asyncio
import inspect
import math
from typing import Any, Dict, Optional

from dsh.mcp.tools import sync_tools
from dsh.mcp.transport import create_transport
from dsh.mcp.content import error_string
from dsh.cordis.utils import js_to_string


RECONNECT_DEFAULTS: Dict[str, Any] = {
    'enabled': True, 'initialDelayMs': 500, 'maxDelayMs': 30000, 'maxAttempts': 10,
}
GENERATION_CLOSE_TIMEOUT = 5
RECONNECT_ABSENT = object()


def resolve_reconnect_policy(config=RECONNECT_ABSENT,
                             path: str = 'mcp_client') -> Dict[str, Any]:
    if config is None:
        raise TypeError('Cannot convert undefined or null to object')
    if config is RECONNECT_ABSENT:
        config = {}
    policy = dict(RECONNECT_DEFAULTS)
    for name, value in (config or {}).items():
        if name not in policy:
            raise ValueError('%s.%s is not a reconnect option' % (path, name))
        if value is not None:
            policy[name] = value
    for name in ('initialDelayMs', 'maxDelayMs'):
        value = policy[name]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 2147483647:
            raise ValueError('%s.%s must be a positive finite number no greater than 2147483647' % (path, name))
    if policy['initialDelayMs'] > policy['maxDelayMs']:
        raise ValueError('%s.initialDelayMs must be less than or equal to maxDelayMs' % path)
    attempts = policy['maxAttempts']
    if (type(attempts) not in (int, float) or not math.isfinite(attempts)
            or attempts < 1 or int(attempts) != attempts):
        raise ValueError('%s.maxAttempts must be a positive integer' % path)
    return policy


async def _await_result(value):
    return await value if inspect.isawaitable(value) else value


class _UnconnectedGeneration:
    async def close(self):
        return None


class McpConnection:
    def __init__(self, ctx: Any, config: Dict[str, Any], policy: Dict[str, Any]):
        self.ctx, self.config, self.policy = ctx, config, policy
        self.disposed = False
        self.disposers = {}
        self.client = None
        self._closed = None
        self._failed_attempts = 0
        self._connected_at = None
        self._first_error = None
        self._retry_task = None
        self._dispose_task = None
        self._sync_tail = None
        self._opts = {'serverName': config.get('serverName', 'default'),
                      'toolCallTimeoutMs': config.get('toolCallTimeoutMs', 60000),
                      'registrationFailure': 'contain'}
        self._label = 'mcp-client(%s)' % self._opts['serverName']
        self.ready = asyncio.get_event_loop().create_future()
        self._start_task = asyncio.create_task(self._initial())

    def _log(self, level, message):
        callback = getattr(getattr(self.ctx, 'logger', None), level, None)
        if callable(callback):
            callback('%s: %s' % (self._label, message))

    def _current(self, generation):
        return not self.disposed and self.client is generation

    def _enqueue(self, action):
        previous = self._sync_tail
        async def run():
            if previous is not None:
                await asyncio.gather(asyncio.shield(previous), return_exceptions=True)
            return await action()
        task = asyncio.create_task(run())
        self._sync_tail = task
        def settled(completed):
            if not completed.cancelled():
                completed.exception()
        task.add_done_callback(settled)
        return task

    def _enqueue_sync(self, generation, startup=False):
        async def run():
            if not self._current(generation):
                return
            opts = dict(self._opts)
            if startup and self.config.get('failOnStartupError'):
                opts['registrationFailure'] = 'throw'
            self.disposers = await sync_tools(generation, self.ctx, opts, self.disposers)
        return self._enqueue(run)

    async def _notification(self, generation, packet):
        if packet.get('method') != 'notifications/tools/list_changed' or not self._current(generation):
            return
        self._log('info', 'tool list changed, re-syncing')
        try:
            await asyncio.shield(self._enqueue_sync(generation))
        except Exception as error:
            if not self.disposed:
                self._log('error', 'tool re-sync failed: %s' % error_string(error))

    def _down(self, generation):
        if not self._current(generation):
            return
        self.client, self._closed = None, None
        established = self._connected_at is not None
        if not self.policy['enabled']:
            self._log('error', 'connection lost and reconnect is disabled — registered tools will fail until an HMR reload or Host restart'
                      if established else 'connection failed and reconnect is disabled — no tools were registered; reload the plugin or restart the Host to connect')
            return
        now = asyncio.get_running_loop().time()
        if established and (now - self._connected_at) * 1000 >= self.policy['maxDelayMs']:
            self._failed_attempts = 0
        self._connected_at = None
        self._failed_attempts += 1
        if self._failed_attempts > self.policy['maxAttempts']:
            async def clear():
                self._clear_tools()
            self._enqueue(clear)
            self._log('error', 'giving up after %s consecutive failed reconnect attempts — tools unregistered; reload the plugin or restart the Host to reconnect' % js_to_string(self.policy['maxAttempts']))
            return
        delay = self.policy['initialDelayMs']
        for attempt in range(self._failed_attempts - 1):
            delay = min(self.policy['maxDelayMs'], delay * 2)
            if delay == self.policy['maxDelayMs']:
                break
        delay = min(self.policy['maxDelayMs'], delay)
        self._log('warn', '%s in %sms (attempt %s/%s)' % (
            'connection lost; reconnecting' if established else 'connection failed; retrying',
            js_to_string(delay), self._failed_attempts, js_to_string(self.policy['maxAttempts'])))
        async def retry():
            await asyncio.sleep(delay / 1000)
            self._retry_task = None
            if not self.disposed:
                self._start_task = asyncio.create_task(self._connect_generation(False))
        self._retry_task = asyncio.create_task(retry())

    async def _wait_closed(self, closed):
        try:
            await asyncio.wait_for(closed.wait(), GENERATION_CLOSE_TIMEOUT)
            return True
        except asyncio.TimeoutError:
            return False

    async def _connect_generation(self, startup):
        if self.disposed:
            return
        generation = None
        try:
            generation = create_transport(self.config)
        except Exception as error:
            if self._first_error is None:
                self._first_error = error
            generation, closed = _UnconnectedGeneration(), asyncio.Event()
            self.client, self._closed = generation, closed
            if not self.disposed:
                self._log('warn', 'connection attempt failed: %s' % error_string(error))
                await self._wait_closed(closed)
                if self._current(generation):
                    self.client, self._closed = None, None
                    self._log('error', 'failed generation did not close within 5000ms — reconnect stopped to avoid overlapping server processes; reload the plugin or restart the Host to retry')
            return
        closed = asyncio.Event()
        settled = False
        self.client, self._closed = generation, closed
        def on_close():
            closed.set()
            if settled:
                self._down(generation)
        generation.on_close = on_close
        generation.on_notification = lambda packet: self._notification(generation, packet)
        try:
            await _await_result(generation.connect())
            if not closed.is_set():
                await asyncio.shield(self._enqueue_sync(generation, startup))
        except Exception as error:
            if self._first_error is None:
                self._first_error = error
            if self._current(generation):
                self._log('warn', 'connection attempt failed: %s' % error_string(error))
            try:
                await _await_result(generation.close())
            except Exception:
                pass
            quiesced = closed.is_set() or await self._wait_closed(closed)
            settled = True
            if not self._current(generation):
                return
            if not quiesced:
                self.client, self._closed = None, None
                self._log('error', 'failed generation did not close within 5000ms — reconnect stopped to avoid overlapping server processes; reload the plugin or restart the Host to retry')
                return
            self._down(generation)
            return
        settled = True
        if closed.is_set():
            self._down(generation)
        elif self._current(generation):
            self._connected_at = asyncio.get_running_loop().time()
            if self._failed_attempts:
                self._log('info', 'reconnected and re-synced tools (attempt %s/%s)' % (
                    self._failed_attempts, js_to_string(self.policy['maxAttempts'])))

    async def _initial(self):
        await self._connect_generation(True)
        if not self.ready.done():
            self.ready.set_result({} if self.client is not None else {'error':
                                   self._first_error or RuntimeError('%s: initial connection failed' % self._label)})

    def _clear_tools(self):
        for disposer in self.disposers.values():
            disposer()
        self.disposers = {}

    async def dispose(self):
        self.disposed = True
        if self._dispose_task is None:
            self._dispose_task = asyncio.create_task(self._dispose())
        await asyncio.shield(self._dispose_task)

    async def _dispose(self):
        self.disposed = True
        if self._retry_task is not None:
            self._retry_task.cancel()
            await asyncio.gather(self._retry_task, return_exceptions=True)
            self._retry_task = None
        current, closed = self.client, self._closed
        self.client, self._closed = None, None
        if current is not None:
            try:
                await _await_result(current.close())
            except Exception:
                pass
            if closed is not None and not await self._wait_closed(closed):
                self._log('error', 'generation did not close within 5000ms during disposal — server shutdown may be incomplete')
        await self._start_task
        if self._sync_tail is not None:
            await asyncio.gather(asyncio.shield(self._sync_tail), return_exceptions=True)
        self._clear_tools()
