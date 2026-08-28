"""
Unit tests for TimerService edge cases matching reference/vendor/timer/src/index.ts.
Tests zero delay timeouts, interval aclose, concurrent throttles, and debounce cancellations.
"""

import asyncio
import pytest
import time
from dsh.cordis.context import Context


@pytest.mark.asyncio
async def test_timer_timeout_zero_delay_future():
    """Verify that timeout(0) resolves promptly."""
    ctx = Context()
    t0 = time.time()
    await ctx.timeout(0)
    assert time.time() - t0 < 0.2


@pytest.mark.asyncio
async def test_timer_timeout_zero_delay_callback():
    """Verify that timeout(callback, 0) executes callback promptly."""
    ctx = Context()
    called = []
    ctx.timeout(lambda: called.append(1), 0)
    await asyncio.sleep(0.02)
    assert called == [1]


@pytest.mark.asyncio
async def test_timer_interval_immediate_aclose():
    """Verify that an interval iterator can be closed immediately without leaking tasks."""
    ctx = Context()
    it = ctx.interval(10)
    await it.aclose()
    assert it._disposed is True


@pytest.mark.asyncio
async def test_timer_concurrent_throttles():
    """Verify independent throttle instances do not interfere with each other."""
    ctx = Context()
    calls1 = []
    calls2 = []

    fn1 = ctx.throttle(lambda x: calls1.append(x), 30)
    fn2 = ctx.throttle(lambda x: calls2.append(x), 30)

    fn1("a")
    fn2("b")
    assert calls1 == ["a"]
    assert calls2 == ["b"]

    fn1.dispose()
    fn2.dispose()


@pytest.mark.asyncio
async def test_timer_debounce_cancel_reschedule():
    """Verify debounce resets countdown when called repeatedly before timeout expires."""
    ctx = Context()
    calls = []

    fn = ctx.debounce(lambda x: calls.append(x), 70)
    fn(1)
    await asyncio.sleep(0.03)
    fn(2)  # Resets countdown
    await asyncio.sleep(0.03)
    assert calls == []

    await asyncio.sleep(0.06)
    assert calls == [2]
    fn.dispose()
