"""Unpublished factory lifetimes, adapted from agent-loop/src/index.ts.

Business abort ends the observer promptly without cancelling a storage provider's
operation. A late preparation is released exactly once, never published.
"""
import asyncio
import inspect
from dsh.core.abort import AbortController


class FactoryTransaction:
    def __init__(self, factory, owner, sid, signal):
        self.factory, self.owner, self.sid = factory, owner, sid
        self.controller = AbortController()
        self.scope = self.agent = self.driver = None
        self.detach_agent = self.detach_session = None
        self.disposing = None
        self.listeners = []
        self.unfollow = None
        self.assert_live()
        if signal is not None:
            self.listeners.append(signal.add_listener('abort', self.controller.abort))
        self.listeners.append(factory._factory_abort.signal.add_listener('abort', self.controller.abort))
        try:
            self.assert_live()
            self.unfollow = owner.disposable(self.owner_dispose, label='agent factory transaction')
            factory._transactions.add(self)
        except BaseException:
            for remove in self.listeners:
                remove()
            raise

    def assert_live(self):
        if self.controller.signal.aborted:
            reason = self.controller.signal.reason
            if isinstance(reason, BaseException):
                raise reason
            error = RuntimeError('agent "%s" creation aborted' % self.sid)
            error.reason = reason
            raise error
        if not self.factory._accepting:
            raise RuntimeError('agent loop is not active')
        self.factory.ctx.fiber.assert_active()
        self.owner.fiber.assert_active()

    async def race(self, operation, release=None):
        self.assert_live()
        value = operation()
        if not inspect.isawaitable(value):
            try:
                self.assert_live()
            except BaseException:
                if release is not None:
                    release(value)
                raise
            return value
        pending = asyncio.ensure_future(value)
        aborted = asyncio.ensure_future(self.controller.signal.wait_aborted())
        def abandoned(result):
            try:
                value = result.result()
                if release is not None:
                    release(value)
            except (Exception, asyncio.CancelledError):
                pass
        try:
            await asyncio.wait((pending, aborted), return_when=asyncio.FIRST_COMPLETED)
            self.assert_live()
            return pending.result()
        except BaseException:
            pending.add_done_callback(abandoned)
            raise
        finally:
            aborted.cancel()
            await asyncio.gather(aborted, return_exceptions=True)

    def owner_dispose(self):
        if self.disposing is not None:
            return None
        self.controller.abort(RuntimeError('agent "%s" owner disposed' % self.sid))
        return self.dispose(owner_triggered=True)

    async def dispose(self, owner_triggered=False):
        if self.disposing is None:
            self.controller.abort(RuntimeError('agent "%s" disposed' % self.sid))
            self.disposing = asyncio.ensure_future(self._dispose(owner_triggered))
        await asyncio.shield(self.disposing)

    async def _dispose(self, owner_triggered):
        for remove in self.listeners:
            remove()
        self.listeners.clear()
        try:
            if self.agent is not None:
                self.agent.cancel({'kind': 'disposed'})
            if self.driver is not None:
                await self.agent.when_idle()
                self.driver.cancel()
                await asyncio.gather(self.driver, return_exceptions=True)
                if self.driver in self.factory._active_tasks:
                    self.factory._active_tasks.remove(self.driver)
            if self.scope is not None:
                await self.scope.dispose()
        finally:
            if self.detach_agent is not None:
                self.detach_agent()
            if self.detach_session is not None:
                self.detach_session()
            self.factory._transactions.discard(self)
            if not owner_triggered and self.unfollow is not None:
                # Calling the effect disposer retires its registration. Its
                # callback must not await this same teardown recursively.
                result = self.unfollow()
                if inspect.isawaitable(result):
                    await result
