"""One generation's work lifetime, caller deadlines and shared bounded cleanup."""
import asyncio

from dsh.core.abort import AbortController,abort_reason_error
from dsh.cordis.awaiting import start_coroutine
from dsh.mcp.deadline_current import with_deadline
from dsh.mcp.diagnostic_current import McpLocalError
from dsh.mcp.transport_current import create_current_transport


class _SharedCleanup:
    def __init__(self, task):
        self.task = task

    def __await__(self):
        return asyncio.shield(self.task).__await__()


class McpGeneration:
    def __init__(self, client, close_timeout_ms, diagnostic, transport_factory=None):
        self.client = client
        self.lifetime = AbortController()
        self._close_timeout_ms = close_timeout_ms
        self._diagnostic = diagnostic
        self._factory = transport_factory if transport_factory is not None else create_current_transport
        self._pending = set()
        self._closed = asyncio.Event()
        self.transport = None
        self._started = False
        self._close_observed = False
        self._closing = None
        self._cleanup_work = None

    def connect(self, config, timeout_ms=None):
        self.lifetime.signal.throw_if_aborted()
        transport = self.transport = self._factory(config)
        original_close, original_start = transport.close, transport.start
        closing = [None]

        async def close():
            if closing[0] is None:
                closing[0] = asyncio.ensure_future(original_close())
            return await asyncio.shield(closing[0])

        async def start():
            self.lifetime.signal.throw_if_aborted()
            self._started = True
            return await original_start()

        def closed():
            self._close_observed = True
            self._closed.set()

        transport.close, transport.start, transport.on_close = close, start, closed

        async def operation(signal):
            options = dict(signal=signal)
            if timeout_ms is not None:
                options['timeout'] = max(1,timeout_ms)
            await self.client.connect(transport, options)
            self.assertOpen()

        return self.run(operation,timeout_ms)

    def assertOpen(self):
        self.lifetime.signal.throw_if_aborted()
        if self._close_observed:
            raise McpLocalError('MCP transport closed')

    def run(self, operation, timeout_ms=None):
        signal = self.lifetime.signal

        async def actual():
            signal.throw_if_aborted()
            return await operation(signal)

        task = asyncio.create_task(actual())
        self._pending.add(task)
        interrupted = asyncio.get_running_loop().create_future()

        def aborted(_):
            if not interrupted.done():
                interrupted.set_exception(abort_reason_error(signal))

        detach = signal.add_listener('abort',aborted)

        def settled(completed):
            self._pending.discard(completed)
            detach()
            if completed.cancelled():
                if not interrupted.done():
                    interrupted.cancel()
                return
            error = completed.exception()
            if not interrupted.done():
                if error is not None:
                    interrupted.set_exception(error)
                else:
                    interrupted.set_result(completed.result())

        task.add_done_callback(settled)
        def observed(completed):
            if not completed.cancelled():
                completed.exception()
        interrupted.add_done_callback(observed)
        return interrupted if timeout_ms is None else start_coroutine(with_deadline(interrupted,timeout_ms,'MCP operation timed out'))

    def close(self):
        if self._closing is None:
            self._closing = _SharedCleanup(start_coroutine(self._finish()))
        return self._closing

    async def _finish(self):
        self.lifetime.abort(McpLocalError('MCP connection closed'))
        cleanup_error = [None]

        async def work():
            try:
                if getattr(self.client,'transport',None) is None:
                    if self.transport is not None:
                        await self.transport.close()
                else:
                    await self.client.close()
            except Exception as error:
                cleanup_error[0] = self._diagnostic(error)
            await asyncio.gather(*list(self._pending),return_exceptions=True)
            if self._started and not self._close_observed:
                await self._closed.wait()

        self._cleanup_work = asyncio.create_task(work())
        try:
            await with_deadline(self._cleanup_work,self._close_timeout_ms,'MCP cleanup did not settle')
            result = dict(closeConfirmed=True)
        except Exception as error:
            result = dict(closeConfirmed=self.transport is None or self._close_observed)
            if cleanup_error[0] is None:
                cleanup_error[0] = self._diagnostic(error)
        if cleanup_error[0] is not None:
            result['cleanupError'] = cleanup_error[0]
        return result
