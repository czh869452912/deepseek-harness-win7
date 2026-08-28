"""
Unit tests for Cordis TimerService matching reference/vendor/timer/src/index.ts.
Tests timeout (callback and future), interval (callback and async iterator),
throttle, debounce, and automatic fiber effect cancellation.
"""

import asyncio
import pytest
import time
from typing import List

from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.cordis.timer import TimerService


@pytest.mark.asyncio
async def test_timer_timeout_callback():
    ctx = Context()
    called = []

    def on_timeout():
        called.append(time.time())

    t0 = time.time()
    disposer = ctx.timeout(on_timeout, 30)
    assert callable(disposer)
    await asyncio.sleep(0.06)

    assert len(called) == 1
    assert called[0] - t0 >= 0.015


@pytest.mark.asyncio
async def test_timer_timeout_future():
    ctx = Context()
    t0 = time.time()
    await ctx.timeout(30)
    t1 = time.time()
    assert t1 - t0 >= 0.015


@pytest.mark.asyncio
async def test_timer_timeout_cancel():
    ctx = Context()
    called = []

    disposer = ctx.timeout(lambda: called.append(1), 50)
    disposer()
    await asyncio.sleep(0.08)

    assert called == []


@pytest.mark.asyncio
async def test_timer_interval_callback():
    ctx = Context()
    ticks = []

    disposer = ctx.interval(lambda: ticks.append(time.time()), 20)
    await asyncio.sleep(0.07)
    disposer()

    count_after_cancel = len(ticks)
    assert count_after_cancel >= 2

    await asyncio.sleep(0.05)
    assert len(ticks) == count_after_cancel


@pytest.mark.asyncio
async def test_timer_interval_async_iterator():
    ctx = Context()
    ticks = 0

    async def _consume():
        nonlocal ticks
        it = ctx.interval(15)
        async for _ in it:
            ticks += 1
            if ticks >= 3:
                await it.aclose()
                break

    await asyncio.wait_for(_consume(), timeout=1.0)
    assert ticks >= 3


@pytest.mark.asyncio
async def test_timer_throttle():
    ctx = Context()
    calls = []

    fn = ctx.throttle(lambda x: calls.append(x), 40)
    fn(1)
    fn(2)
    fn(3)
    assert calls == [1]

    await asyncio.sleep(0.06)
    assert calls == [1, 3]
    fn.dispose()


@pytest.mark.asyncio
async def test_timer_debounce():
    ctx = Context()
    calls = []

    fn = ctx.debounce(lambda x: calls.append(x), 30)
    fn(1)
    fn(2)
    fn(3)
    assert calls == []

    await asyncio.sleep(0.05)
    assert calls == [3]
    fn.dispose()


@pytest.mark.asyncio
async def test_timer_automatic_fiber_teardown():
    """Verify that all timers created by a plugin are automatically disposed when the plugin fiber unloads."""
    ctx = Context()
    ticks = []

    class TimedPlugin(Plugin):
        name = "timed-plugin"

        def apply(self, c: Context) -> None:
            c.interval(lambda: ticks.append(1), 15)
            c.timeout(lambda: ticks.append(99), 30)

    fiber = ctx.registry.plugin(TimedPlugin())
    await asyncio.sleep(0.04)
    assert len(ticks) >= 1

    # Dispose fiber -> cancels interval & timeout
    await fiber.dispose()
    count_at_dispose = len(ticks)

    await asyncio.sleep(0.06)
    assert len(ticks) == count_at_dispose
