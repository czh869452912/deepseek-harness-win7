"""
1:1 Test Parity for Cordis TimerService
Authority: reference/vendor/timer/src/index.ts
"""

import asyncio
import pytest
import time
from dsh.cordis.context import Context
from dsh.cordis.timer import TimerService


@pytest.mark.asyncio
async def test_d1_interval_dispose_raises_runtime_error_consistently():
    """ts:timer/src/index.ts:77-85 - disposed iterator raises RuntimeError on waiting and subsequent __anext__."""
    ctx = Context()

    timer_iter = ctx.interval(20)

    # Start waiting for next tick
    task = asyncio.create_task(timer_iter.__anext__())
    await asyncio.sleep(0.005)

    # Dispose context
    ctx.dispose()

    with pytest.raises(RuntimeError) as exc_info:
        await task
    assert "Context has been disposed" in str(exc_info.value)

    # Subsequent __anext__ must CONTINUE raising RuntimeError
    with pytest.raises(RuntimeError) as exc_info2:
        await timer_iter.__anext__()
    assert "Context has been disposed" in str(exc_info2.value)


@pytest.mark.asyncio
async def test_d1_interval_aclose_clean_stop():
    """ts:timer/src/index.ts:87-92 - explicit aclose cleanly raises StopAsyncIteration."""
    ctx = Context()

    timer_iter = ctx.interval(20)

    task = asyncio.create_task(timer_iter.__anext__())
    await asyncio.sleep(0.005)

    await timer_iter.aclose()

    with pytest.raises(StopAsyncIteration):
        await task

    with pytest.raises(StopAsyncIteration):
        await timer_iter.__anext__()


@pytest.mark.asyncio
async def test_d2_interval_slow_consumer_drops_ticks():
    """ts:timer/src/index.ts:71-73 - ticks are dropped when no consumer is waiting (no burst)."""
    ctx = Context()

    timer_iter = ctx.interval(20)  # 20ms

    # Consume 1st tick
    await timer_iter.__anext__()

    # Sleep for 100ms (5 ticks pass without consumer)
    await asyncio.sleep(0.1)

    # Next call should wait for the NEXT tick, not instantly receive 5 cached ticks
    t0 = time.time()
    await timer_iter.__anext__()
    elapsed = time.time() - t0

    # If ticks were cached in a queue, elapsed would be ~0.000s; with drop, elapsed should be > 0.010s
    assert elapsed >= 0.010
    await timer_iter.aclose()


@pytest.mark.asyncio
async def test_d3_interval_callback_non_blocking_coroutine():
    """ts:timer/src/index.ts:63-66 - callback returning awaitable is not awaited in tick loop."""
    ctx = Context()

    tick_times = []

    async def slow_callback():
        tick_times.append(time.time())
        await asyncio.sleep(0.05)  # 50ms slow async task

    # Interval is 20ms. If awaited, interval would be 70ms. Without await, interval is ~20ms.
    disposer = ctx.interval(slow_callback, 20)
    await asyncio.sleep(0.15)
    disposer()

    assert len(tick_times) >= 3


@pytest.mark.asyncio
async def test_d4_throttle_immediate_fires_after_dispose():
    """T5 (D4): Immediate execution path (remaining <= 0) still fires after dispose, trailing suppressed."""
    ctx = Context()
    calls = []

    def cb(val):
        calls.append(val)

    fn = ctx.throttle(cb, 30)
    fn("first")
    assert calls == ["first"]

    await asyncio.sleep(0.06)
    # Dispose fiber / throttled function
    fn.dispose()

    # Immediate call (remaining <= 0 since 60ms > 30ms) still runs
    fn("after_dispose_immediate")
    assert calls == ["first", "after_dispose_immediate"]

    # Trailing call within delay is suppressed after dispose
    fn("trailing_suppressed")
    await asyncio.sleep(0.06)
    assert calls == ["first", "after_dispose_immediate"]


@pytest.mark.asyncio
async def test_d5_timeout_future_rejects_on_dispose():
    """T6 (D5): ctx.timeout(delay) future rejects with RuntimeError on fiber dispose."""
    ctx = Context()
    fut = ctx.timeout(200)

    # Dispose fiber while timeout future is pending
    await ctx.fiber.dispose()

    with pytest.raises(RuntimeError) as exc_info:
        await fut
    assert "Context has been disposed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_d5_no_loop_timeout_effect_cancellation():
    """T7 (D5): No-loop timeout fallback registers cancellable effect."""
    ctx = Context()
    # Simulate no running loop by invoking with loop=None logic directly
    timer_svc = ctx.get("timer")
    coro = timer_svc.timeout(50, ctx=ctx)

    # Dispose context before running coroutine
    await ctx.fiber.dispose()

    with pytest.raises(RuntimeError) as exc_info:
        await coro
    assert "Context has been disposed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_d4_throttle_no_trailing():
    """T8: throttle with no_trailing=True suppresses trailing invocation."""
    ctx = Context()
    calls = []

    def cb(val):
        calls.append(val)

    fn = ctx.throttle(cb, 50, no_trailing=True)
    fn(1)
    fn(2)  # within 50ms window
    assert calls == [1]

    await asyncio.sleep(0.08)
    # Trailing call was not scheduled
    assert calls == [1]
