"""Observations from the real Python timeout policy and timing primitives."""

import asyncio
import heapq
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dsh.core import timeout
from dsh.core.abort import AbortController
from dsh.core.cancellation import subscribe_abort
from dsh.core.tools import ToolsPlugin, ToolExecutionInput
from dsh.cordis.context import Context
from dsh.guard.timeout_policy import ToolCallTimeoutPolicyPlugin
from dsh.llm.error import HarnessError

MODES = ['unbudgeted', 'budgeted', 'deadline-return', 'deadline-throw',
         'user-first', 'deadline-first', 'foreign-first']


class Clock:
    def __init__(self):
        self.now, self.sequence, self.timers = 0, 0, []

    def call_later(self, seconds, callback, *args):
        handle = SimpleNamespace(cancelled=False)
        handle.cancel = lambda: setattr(handle, 'cancelled', True)
        self.sequence += 1
        heapq.heappush(self.timers, (self.now + seconds * 1000, self.sequence, handle, callback, args))
        return handle

    def advance(self, milliseconds):
        end = self.now + milliseconds
        while self.timers and self.timers[0][0] <= end:
            when, _, handle, callback, args = heapq.heappop(self.timers)
            self.now = when
            if not handle.cancelled:
                callback(*args)
        self.now = end


async def wait_abort(signal):
    future = asyncio.get_running_loop().create_future()
    detach = subscribe_abort(signal, lambda *_args: future.set_result(None) if not future.done() else None)
    try:
        await future
    finally:
        detach()


async def run(clock):
    rows = []
    for mode in MODES:
        ctx, caller = Context(), AbortController()
        entered, saw_abort, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        signals, post = [], []

        async def tool(_args, exec):
            signals.append(exec.signal)
            entered.set()
            if mode in ('unbudgeted', 'budgeted'):
                return [dict(type='text', text='ok')]
            await wait_abort(exec.signal)
            saw_abort.set()
            await release.wait()
            if mode == 'deadline-throw':
                raise HarnessError('web fetch aborted', 'WEB_ABORTED')
            return [dict(type='text', text='released')]

        async def observer(exec, _result, next_fn):
            post.append(exec.signal is caller.signal)
            return await next_fn()

        try:
            await ctx.plugin(ToolsPlugin)
            await ctx.plugin(ToolCallTimeoutPolicyPlugin)
            spec = dict(name='probe', description='paired fixture', parameters={}, execute=tool,
                        output=dict(schema={}, render=lambda _args, value: value))
            if mode != 'unbudgeted':
                spec['timeoutMs'] = 100
            ctx.get('tools').register(spec)
            ctx.on('tools/post-execute', observer)
            pending = asyncio.create_task(ctx.get('tools').execute(
                ToolExecutionInput('call', 'probe', {}, signal=caller.signal)))
            await asyncio.wait_for(entered.wait(), 2)
            waited = False
            if mode not in ('unbudgeted', 'budgeted'):
                if mode in ('user-first', 'foreign-first'):
                    caller.abort('user' if mode == 'user-first' else timeout.TimeoutReason('OUTER', 30))
                clock.advance(100)
                await asyncio.wait_for(saw_abort.wait(), 2)
                waited = not pending.done()
                if mode == 'deadline-first':
                    caller.abort('late user')
                release.set()
            result = await pending
            reason = timeout.timeout_of(signals[0])
            rows.append(dict(mode=mode, derived=signals[0] is not caller.signal,
                             postCaller=post == [True], waitedForCleanup=waited,
                             timeoutCode=reason.code if reason else None,
                             result=dict(content=result.content, isError=result.is_error,
                                         error=dict(message=result.error['message'], info=result.error.get('info'))
                                         if result.error else None)))
        finally:
            release.set()
            caller.abort('cleanup')
            await ctx.fiber.dispose()

    rows.append(dict(mode='number-text', messages=[timeout.TimeoutReason('TEST', value).message
                     for value in [100.0, 0.00001, 0.000001, 0.0000001, 1e21, 100.25,
                                   float('nan'), float('inf'), float('-inf')]]))
    outer = AbortController()
    outer.abort(timeout.TimeoutReason('OUTER', 30))
    with timeout.deadline(outer.signal, 100, 'INNER') as inner:
        clock.advance(100)
        rows.append(dict(mode='nested', aborted=inner.signal.aborted, code=timeout.timeout_of(inner.signal).code,
                         local=timeout.timeout_of(inner.signal, 'INNER') is not None))
    with timeout.idle_watchdog(None, 100, 'IDLE') as watchdog:
        stable = watchdog.signal
        first, second = (asyncio.get_running_loop().create_future() for _ in range(2))
        watchdog.pulse()
        clock.advance(1000)
        no_demand = not stable.aborted
        demand = asyncio.create_task(watchdog.next(SimpleNamespace(next=lambda: first)))
        await asyncio.sleep(0)
        clock.advance(99)
        watchdog.pulse()
        clock.advance(99)
        protected = not stable.aborted
        first.set_result(dict(done=False, value=1))
        await demand
        clock.advance(1000)
        idle_protected = not stable.aborted
        late = asyncio.create_task(watchdog.next(SimpleNamespace(next=lambda: second)))
        await asyncio.sleep(0)
        clock.advance(100)
        rows.append(dict(mode='watchdog', noDemand=no_demand, pulseProtected=protected,
                         idleProtected=idle_protected, stable=watchdog.signal is stable,
                         code=timeout.timeout_of(stable).code))
        second.set_result(dict(done=True))
        await late
    return rows


if __name__ == '__main__':
    clock = Clock()
    with patch.object(timeout, 'asyncio', SimpleNamespace(get_running_loop=lambda: clock)):
        observations = asyncio.run(run(clock))
    Path(sys.argv[1]).write_text(json.dumps(observations, indent=2) + '\n', encoding='utf-8')
