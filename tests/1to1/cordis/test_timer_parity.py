"""
1:1 Test Parity for Cordis TimerService
Authority: reference/vendor/timer/src/index.ts
"""

import asyncio
import pytest
import threading
import time
from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.cordis.loader import Loader
from dsh.cordis.timer import TimerService


def timer_effects(ctx):
    """Effect labels `ctx.fiber` owns for the timer helpers.

    `ctx.plugin(TimerService)` is itself a fiber effect of the reading context, so
    the timer contract is asserted on every other effect label.
    """
    return [meta["label"] for meta in ctx.fiber.get_effects() if meta["label"] != "ctx.plugin()"]


@pytest.mark.asyncio
async def test_d1_interval_dispose_raises_runtime_error_consistently():
    """ts:timer/src/index.ts:77-85 - disposed iterator raises RuntimeError on waiting and subsequent __anext__."""
    ctx = Context()
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service

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
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service

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
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service

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
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service

    tick_times = []

    async def slow_callback():
        tick_times.append(time.time())
        await asyncio.sleep(0.05)  # 50ms slow async task

    # Interval is 20ms. If awaited, a tick cycle takes 20ms + 50ms, so 0.3s holds ~3
    # ticks; without awaiting it, the callback starts on every interval (~9 ticks here).
    disposer = ctx.interval(slow_callback, 20)
    await asyncio.sleep(0.3)
    disposer()

    assert len(tick_times) >= 5


@pytest.mark.asyncio
async def test_d4_throttle_immediate_fires_after_dispose():
    """T5 (D4): Immediate execution path (remaining <= 0) still fires after dispose, trailing suppressed."""
    ctx = Context()
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
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
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
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
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
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
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
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

# ---------------------------------------------------------------------------
# Public contract cases for vendor/timer, mapped onto
# reference/vendor/timer/src/index.ts. The vendored package ships no spec file
# and vitest collects only packages/*/*/tests, apps/*/tests and scripts/**, so
# every case names the authoritative source lines it pins; the README API table
# and the deprecated aliases are covered as well.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t1_service_provides_timer_and_mixes_its_helpers():
    """ts:index.ts:12-16 - the class provides `timer` and mixes its six helpers onto ctx."""
    ctx = Context()
    fiber = ctx.plugin(TimerService)
    await asyncio.sleep(0)

    assert fiber.state == FiberState.ACTIVE
    assert ctx.get("timer").name == "timer"
    for helper in ("timeout", "interval", "throttle", "debounce", "setTimeout", "setInterval"):
        assert callable(getattr(ctx, helper))


@pytest.mark.asyncio
async def test_t1_timer_service_and_helpers_exist_only_while_the_plugin_fiber_is_loaded():
    """ts:index.ts:12-16 - the constructor both provides `timer` and mixes the six
    helpers, so both surfaces are absent before the plugin loads and are removed with
    the plugin fiber."""
    ctx = Context()
    assert ctx.get("timer") is None
    for helper in ("timeout", "interval", "throttle", "debounce", "setTimeout", "setInterval"):
        with pytest.raises(AttributeError):
            getattr(ctx, helper)

    fiber = ctx.plugin(TimerService)
    await fiber
    assert ctx.get("timer").name == "timer"
    for helper in ("timeout", "interval", "throttle", "debounce", "setTimeout", "setInterval"):
        assert callable(getattr(ctx, helper))

    await fiber.dispose()
    assert ctx.get("timer") is None
    for helper in ("timeout", "interval", "throttle", "debounce", "setTimeout", "setInterval"):
        with pytest.raises(AttributeError):
            getattr(ctx, helper)


@pytest.mark.asyncio
async def test_t1_base_bundle_row_mounts_the_service_through_its_vendor_name():
    """reference/packages/bundle/base/cordis.patch.yml mounts the package by name
    (`id: timer` / `name: '@deepseek-ai/cordis-plugin-timer'`), so the loader entry owns
    the service for exactly as long as that entry is loaded."""
    ctx = Context()
    await ctx.plugin(Loader)
    assert ctx.get("timer") is None

    await ctx.loader.create({"id": "timer", "name": "@deepseek-ai/cordis-plugin-timer"})
    assert ctx.get("timer").name == "timer"

    entry = next(e for e in ctx.loader.entries() if e.options.get("id") == "timer")
    assert entry.fiber is not None
    await entry.fiber.dispose()
    assert ctx.get("timer") is None


@pytest.mark.asyncio
async def test_t2_timeout_callback_runs_once_and_releases_its_effect_first():
    """ts:index.ts:35-42 - the firing callback disposes its own effect before user code runs."""
    ctx = Context()
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    observed = []
    ctx.timeout(lambda: observed.append(len(timer_effects(ctx))), 30)
    assert timer_effects(ctx) == ["ctx.timeout()"]

    await asyncio.sleep(0.25)

    assert observed == [0]
    assert timer_effects(ctx) == []


@pytest.mark.asyncio
async def test_t2_timeout_callback_disposer_cancels_the_pending_timer():
    """ts:index.ts:36-42 - the returned disposer clears the timer and releases the effect."""
    ctx = Context()
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    fired = []
    dispose = ctx.timeout(lambda: fired.append(1), 60)

    dispose()
    await asyncio.sleep(0.15)

    assert fired == []
    assert timer_effects(ctx) == []


@pytest.mark.asyncio
async def test_t2_timeout_callback_raising_escapes_to_the_loop_after_releasing_its_effect():
    """ts:index.ts:34-42 - the firing callback disposes its own effect and then runs
    unguarded, so a raising callback reaches the runtime's uncaught-exception handling
    with its effect already released."""
    ctx = Context()
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    loop = asyncio.get_running_loop()
    escaped = []

    def handler(handler_loop, context):
        escaped.append(context)

    previous = loop.get_exception_handler()
    loop.set_exception_handler(handler)
    observed = []

    def callback():
        observed.append(timer_effects(ctx))
        raise RuntimeError("timeout-boom")

    ctx.timeout(callback, 20)
    assert timer_effects(ctx) == ["ctx.timeout()"]
    try:
        await asyncio.sleep(0.15)
    finally:
        loop.set_exception_handler(previous)

    assert observed == [[]]
    assert len(escaped) == 1
    assert isinstance(escaped[0]["exception"], RuntimeError)
    assert str(escaped[0]["exception"]) == "timeout-boom"
    assert timer_effects(ctx) == []


@pytest.mark.asyncio
async def test_t3_timeout_delay_resolves_at_the_deadline_and_releases_its_effect():
    """ts:index.ts:43-52 - the promise form resolves after `delay` and settles its effect."""
    ctx = Context()
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    started = time.perf_counter()
    await ctx.timeout(40)
    elapsed = time.perf_counter() - started

    assert elapsed >= 0.03
    assert timer_effects(ctx) == []


@pytest.mark.asyncio
async def test_t3_timeout_delay_already_elapsed_survives_a_later_dispose():
    """ts:index.ts:46-52 - `reject` after `resolve` is a no-op, so the awaited value stands."""
    ctx = Context()
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    coroutine = ctx.timeout(30)

    # The reference resolves `promise` on the timer alone; the consumer is not needed.
    await asyncio.sleep(0.15)
    assert timer_effects(ctx) == []

    await ctx.fiber.dispose()
    assert await asyncio.wait_for(coroutine, 1) is None


@pytest.mark.asyncio
async def test_t4_deprecated_aliases_delegate_and_keep_their_disposers():
    """ts:index.ts:18-26 - setTimeout/setInterval return the timeout/interval disposers."""
    ctx = Context()
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    calls = []
    dispose_once = ctx.setTimeout(lambda: calls.append("once"), 30)
    dispose_repeat = ctx.setInterval(lambda: calls.append("repeat"), 30)

    await asyncio.sleep(0.12)
    dispose_once()
    dispose_repeat()
    settled = list(calls)

    await asyncio.sleep(0.12)

    assert settled[0] == "once"
    assert settled.count("repeat") >= 1
    assert calls == settled


@pytest.mark.asyncio
async def test_t5_interval_callback_raising_escapes_to_the_loop_and_ends_the_tick_chain():
    """ts:index.ts:63-66 - `setInterval(callback, delay)` hands the callback to the runtime
    with no catch anywhere in the timer, so a raising callback reaches the runtime's
    uncaught-exception handling and its tick chain ends instead of continuing."""
    ctx = Context()
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    loop = asyncio.get_running_loop()
    escaped = []

    def handler(handler_loop, context):
        escaped.append(context)

    previous = loop.get_exception_handler()
    loop.set_exception_handler(handler)
    ticks = []

    def callback():
        ticks.append(1)
        raise RuntimeError("tick-boom")

    dispose = ctx.interval(callback, 20)
    try:
        await asyncio.sleep(0.15)
    finally:
        loop.set_exception_handler(previous)

    assert ticks == [1]
    assert len(escaped) == 1
    assert isinstance(escaped[0]["exception"], RuntimeError)
    assert str(escaped[0]["exception"]) == "tick-boom"

    # The reference clears an interval only through its disposer, so the raise leaves
    # the effect owned until that disposer runs.
    assert timer_effects(ctx) == ["ctx.interval()"]
    dispose()
    assert timer_effects(ctx) == []


def test_t5_interval_callback_raising_without_running_loop_escapes_to_the_thread_hook():
    """ts:index.ts:63-66 - the same contract with no loop to hold the interval: the raising
    callback escapes its worker thread through `threading.excepthook` and the tick chain
    ends there."""
    ctx = Context()
    ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    escaped = []

    def hook(args):
        escaped.append((args.exc_type, args.exc_value, args.thread.name))

    previous = threading.excepthook
    threading.excepthook = hook
    ticks = []

    def callback():
        ticks.append(1)
        raise RuntimeError("tick-boom")

    dispose = ctx.interval(callback, 20)
    try:
        deadline = time.monotonic() + 2
        while not escaped and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.15)  # a caught-and-retried callback would tick again here
    finally:
        threading.excepthook = previous

    assert ticks == [1]
    booms = [entry for entry in escaped if str(entry[1]) == "tick-boom"]
    assert len(booms) == 1
    assert booms[0][0] is RuntimeError
    assert booms[0][2] != "MainThread"

    assert timer_effects(ctx) == ["ctx.interval()"]
    dispose()
    assert timer_effects(ctx) == []


@pytest.mark.asyncio
async def test_t6_interval_iterator_is_its_own_async_iterator_and_waits_for_a_tick():
    """ts:index.ts:71-73 & 99-101 - a tick resolves the waiting consumer; the iterator is its own."""
    ctx = Context()
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    iterator = ctx.interval(60)
    assert iterator.__aiter__() is iterator

    started = time.perf_counter()
    await iterator.__anext__()
    elapsed = time.perf_counter() - started
    await iterator.aclose()

    assert elapsed >= 0.03
    assert timer_effects(ctx) == []


@pytest.mark.asyncio
async def test_t6_interval_iterator_return_delivers_the_value_to_pending_and_later_next():
    """ts:index.ts:87-92 - `return(value)` resolves the pending `next()` with
    `{ done: true, value }` and keeps returning that value from every later `next()`."""
    ctx = Context()
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    iterator = ctx.interval(500)
    pending = asyncio.ensure_future(iterator.__anext__())
    await asyncio.sleep(0.02)

    await iterator.aclose("closed")

    with pytest.raises(StopAsyncIteration) as pending_exc:
        await pending
    with pytest.raises(StopAsyncIteration) as later_exc:
        await iterator.__anext__()

    assert pending_exc.value.args == ("closed",)
    assert later_exc.value.args == ("closed",)
    assert timer_effects(ctx) == []


@pytest.mark.asyncio
async def test_t6_interval_iterator_throw_rejects_pending_and_finishes_the_iterator():
    """ts:index.ts:93-98 - `throw(reason)` rejects the pending `next()` with the reason,
    releases the interval, and ends the iterator without delivering the error again."""
    ctx = Context()
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    iterator = ctx.interval(500)
    pending = asyncio.ensure_future(iterator.__anext__())
    await asyncio.sleep(0.02)

    with pytest.raises(StopAsyncIteration):
        await iterator.athrow(RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await pending
    with pytest.raises(RuntimeError, match="boom"):
        await iterator.__anext__()
    assert timer_effects(ctx) == []


def test_t6_interval_iterator_created_without_a_running_loop_keeps_the_creation_cadence():
    """ts:index.ts:67-73 - setInterval ticks from creation, so a caller outside an
    event loop still gets its ticks at the same instants as a loop-bound caller."""
    ctx = Context()
    ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    started = time.perf_counter()
    iterator = ctx.interval(400)

    time.sleep(0.3)

    async def consume():
        await asyncio.wait_for(iterator.__anext__(), 1)
        first_tick = time.perf_counter()
        await asyncio.wait_for(iterator.__anext__(), 1)
        return first_tick, time.perf_counter() - first_tick

    first_tick, gap = asyncio.run(consume())

    # The 0.4s tick; a tick loop started by the wait itself would deliver at 0.7s.
    assert first_tick - started < 0.55
    assert 0.3 <= gap < 0.6


@pytest.mark.asyncio
async def test_t7_throttle_trailing_call_runs_with_the_latest_arguments():
    """ts:index.ts:112-135 - a call inside the window schedules the trailing run with its own args."""
    ctx = Context()
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    calls = []
    throttled = ctx.throttle(lambda *args: calls.append(args), 200)

    throttled(1, "x")
    throttled(2, "y")
    assert calls == [(1, "x")]

    await asyncio.sleep(0.4)

    assert calls == [(1, "x"), (2, "y")]
    throttled.dispose()


@pytest.mark.asyncio
async def test_t7_throttle_dispose_clears_the_pending_trailing_call():
    """ts:index.ts:108-116 - disposing the wrapper clears its scheduled trailing call."""
    ctx = Context()
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    calls = []
    throttled = ctx.throttle(lambda value: calls.append(value), 200)
    throttled(1)
    throttled(2)

    throttled.dispose()
    await asyncio.sleep(0.4)

    assert calls == [1]
    assert timer_effects(ctx) == []


@pytest.mark.asyncio
async def test_t7_throttle_and_debounce_use_their_reference_effect_labels():
    """ts:index.ts:127 & 140 - `_schedule` registers the label of the helper that created it."""
    ctx = Context()
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    throttled = ctx.throttle(lambda: None, 50)
    debounced = ctx.debounce(lambda: None, 50)

    assert sorted(timer_effects(ctx)) == [
        "ctx.debounce()",
        "ctx.throttle()",
    ]

    throttled.dispose()
    debounced.dispose()
    assert timer_effects(ctx) == []


@pytest.mark.asyncio
async def test_t8_debounce_resets_its_timer_and_calls_with_the_last_arguments():
    """ts:index.ts:139-144 - every call clears the pending timer, so only the last call runs."""
    ctx = Context()
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    calls = []
    debounced = ctx.debounce(lambda *args: calls.append(args), 300)

    debounced(1)
    await asyncio.sleep(0.2)
    debounced(2)
    await asyncio.sleep(0.2)
    assert calls == []  # an unreset 300ms timer would have fired by now

    await asyncio.sleep(0.3)

    assert calls == [(2,)]
    debounced.dispose()


@pytest.mark.asyncio
async def test_t8_debounce_dispose_clears_pending_and_ignores_later_calls():
    """ts:index.ts:108-110 & 140-143 - a disposed wrapper clears its timer and drops later calls."""
    ctx = Context()
    await ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    calls = []
    debounced = ctx.debounce(lambda value: calls.append(value), 200)
    debounced(1)
    await asyncio.sleep(0.05)

    debounced.dispose()
    debounced(2)
    await asyncio.sleep(0.35)

    assert calls == []
    assert timer_effects(ctx) == []


def test_t9_timeout_without_running_loop_keeps_its_creation_deadline():
    """ts:index.ts:43-52 - Python-only fallback: with no loop to hold the timer, the
    deadline is fixed at creation and the coroutine sleeps what is left of it."""
    ctx = Context()
    ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    started = time.perf_counter()
    coroutine = ctx.timeout(400)
    time.sleep(0.3)

    asyncio.run(asyncio.wait_for(coroutine, 5))
    elapsed = time.perf_counter() - started

    assert elapsed >= 0.35
    assert elapsed < 0.6  # a deadline taken at await time would take 0.3s + 0.4s


def test_t9_timeout_without_running_loop_rejects_when_disposed_before_the_deadline():
    """ts:index.ts:47-52 - disposal before the deadline rejects with 'Context has been disposed'."""
    ctx = Context()
    ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    coroutine = ctx.timeout(2000)

    ctx.dispose()

    with pytest.raises(RuntimeError, match="Context has been disposed"):
        asyncio.run(asyncio.wait_for(coroutine, 5))


def test_t9_timeout_without_running_loop_keeps_a_deadline_that_already_elapsed():
    """ts:index.ts:46-52 - the reject in the disposer is a no-op once the timer fired."""
    ctx = Context()
    ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    coroutine = ctx.timeout(60)
    time.sleep(0.2)

    ctx.dispose()

    assert asyncio.run(asyncio.wait_for(coroutine, 5)) is None


def test_t9_throttle_without_running_loop_still_runs_the_trailing_call():
    """ts:index.ts:132-133 - the trailing invocation is scheduled on whatever timer exists."""
    ctx = Context()
    ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    calls = []
    throttled = ctx.throttle(lambda value: calls.append(value), 60)
    throttled(1)
    throttled(2)

    time.sleep(0.4)
    throttled.dispose()

    assert calls == [1, 2]


def test_t9_timeout_callback_without_running_loop_runs_once_per_call():
    """ts:index.ts:34-42 - the callback form fires exactly once per call without a
    loop to hold the timer, and every timer effect is released afterwards."""
    ctx = Context()
    ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    calls = []

    disposers = [ctx.timeout(lambda: calls.append(1), 0) for _ in range(100)]
    time.sleep(0.3)

    assert calls == [1] * 100
    assert timer_effects(ctx) == []

    for dispose in disposers:
        dispose()
    assert timer_effects(ctx) == []


def test_t9_timeout_callback_without_running_loop_disposes_its_effect_first():
    """ts:index.ts:35-42 - the firing callback disposes its own effect before user code runs."""
    ctx = Context()
    ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    observed = []
    ctx.timeout(lambda: observed.append(len(timer_effects(ctx))), 0)

    time.sleep(0.2)

    assert observed == [0]
    assert timer_effects(ctx) == []


def test_t9_timeout_callback_without_running_loop_disposer_cancels_the_timer():
    """ts:index.ts:36-42 - the disposer clears a pending no-loop timer and releases the effect."""
    ctx = Context()
    ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    fired = []
    dispose = ctx.timeout(lambda: fired.append(1), 300)

    dispose()
    time.sleep(0.5)

    assert fired == []
    assert timer_effects(ctx) == []


def test_t9_timeout_callback_raising_without_running_loop_escapes_to_the_thread_hook():
    """ts:index.ts:34-42 - the same contract without a loop to hold the timer: the disposer
    runs first and the callback's exception reaches `threading.excepthook`."""
    ctx = Context()
    ctx.plugin(TimerService)  # vendor/timer index.ts:12-16 - the plugin owns the service
    escaped = []

    def hook(args):
        escaped.append((args.exc_type, args.exc_value))

    previous = threading.excepthook
    threading.excepthook = hook
    observed = []

    def callback():
        observed.append(timer_effects(ctx))
        raise RuntimeError("timeout-boom")

    ctx.timeout(callback, 0)
    try:
        deadline = time.monotonic() + 2
        while not escaped and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        threading.excepthook = previous

    assert observed == [[]]
    booms = [entry for entry in escaped if str(entry[1]) == "timeout-boom"]
    assert len(booms) == 1
    assert booms[0][0] is RuntimeError
    assert timer_effects(ctx) == []
