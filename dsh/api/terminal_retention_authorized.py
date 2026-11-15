"""Monotonic terminal holds, conservative activity observations and retryable close."""
import asyncio

from dsh.core.abort import AbortController
from dsh.core.cleanup import CleanupPromise
from dsh.typert.remote import RemoteError


class LoopScheduler:
    def now(self):return asyncio.get_running_loop().time() * 1000
    def later(self, delay, callback):return asyncio.get_running_loop().call_later(delay / 1000, callback)


class TerminalRetention:
    def __init__(self, policy, inspect, terminate, failed, scheduler=None):
        self.policy, self.inspect, self.terminate, self.failed = policy, inspect, terminate, failed
        self.scheduler = scheduler or LoopScheduler();self.lifetime = AbortController();self.holders = set()
        self.epoch = 0;self.timer = None;self.observation = None;self.idle = None
        self.closing = False;self.disposed = False;self.cleanup = None
        self.schedule(0)

    async def retain(self, signal):
        signal.throwIfAborted()
        if self.closing or self.disposed:
            raise RemoteError('terminal/unavailable', 'Terminal is closing or unavailable', {})
        holder = object();ended = asyncio.get_running_loop().create_future()
        signals = (signal, self.lifetime.signal)
        def release(*_):
            if holder not in self.holders:return
            self.holders.remove(holder)
            for item in signals:item.removeEventListener('abort', release)
            self.invalidate()
            if not ended.done():ended.set_result(None)
            self.schedule(0)
        self.holders.add(holder);self.invalidate();self.cancel_timer()
        for item in signals:item.addEventListener('abort', release, dict(once=True))
        try:yield dict(type='retained');await ended
        finally:release()

    def invalidate(self):self.epoch += 1;self.idle = None

    def close(self):
        if self.cleanup is not None:return self.cleanup
        self.closing = True;self.invalidate();self.lifetime.abort(RuntimeError('Terminal closed'));self.cancel_timer()
        async def cleanup():
            try:await self.terminate()
            except Exception:
                self.cleanup = None;self.schedule(self.policy['cleanupRetryMs']);raise
        self.cleanup = CleanupPromise(cleanup())
        return self.cleanup

    async def dispose(self):
        self.disposed = True;self.cancel_timer();observation = self.observation
        try:await asyncio.shield(self.close())
        finally:
            if observation is not None:await asyncio.shield(observation)

    def cancel_timer(self):
        if self.timer is not None:self.timer.cancel();self.timer = None

    def schedule(self, delay):
        if self.disposed or self.timer is not None:return
        if not self.closing and (self.holders or self.policy['unattendedTimeoutMs'] == 0):return
        due = self.scheduler.now() + delay
        def ready():
            self.timer = None;remaining = due - self.scheduler.now()
            if remaining > 0:self.schedule(remaining);return
            if self.closing:
                task = self.close()
                def report(done):
                    if not done.cancelled() and done.exception() is not None:self.failed(done.exception())
                task.add_done_callback(report)
            else:self.observe()
        self.timer = self.scheduler.later(min(delay, 2147483647), ready)

    def observe(self):
        if self.observation is not None:return
        epoch = self.epoch
        async def observe():
            try:
                try:activity = await self.inspect()
                except Exception:activity = dict(state='unknown', revision=0)
                if self.disposed or self.closing or self.holders or epoch != self.epoch:return
                now = self.scheduler.now()
                if activity['state'] != 'idle':self.idle = None;return
                if self.idle is None or self.idle['revision'] != activity['revision'] or now - self.idle['observedAt'] > self.policy['activityPollIntervalMs'] * 2:
                    self.idle = dict(since=now, observedAt=now, revision=activity['revision'])
                else:self.idle['observedAt'] = now
                if now - self.idle['since'] >= self.policy['unattendedTimeoutMs']:await asyncio.shield(self.close())
            except Exception as error:self.failed(error)
            finally:
                self.observation = None
                if not self.closing:self.schedule(self.policy['activityPollIntervalMs'])
        self.observation = asyncio.ensure_future(observe())
