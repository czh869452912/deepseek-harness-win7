import asyncio
import gc
import heapq
import weakref
from types import SimpleNamespace

import pytest

from dsh.core import timeout
from dsh.core.abort import AbortController
from dsh.core.cancellation import subscribe_abort
from dsh.cordis.context import Context
from dsh.core.tools import ToolsPlugin, ToolExecutionInput
from dsh.guard.timeout_policy import ToolCallTimeoutPolicyPlugin, tool_timeout_result
from dsh.llm.error import HarnessError


class Clock:
    def __init__(self):
        self.now = 0
        self.sequence = 0
        self.timers = []

    def call_later(self, seconds, callback, *args):
        handle = SimpleNamespace(cancelled=False)
        handle.cancel = lambda: setattr(handle, "cancelled", True)
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


@pytest.fixture
def clock(monkeypatch):
    value = Clock()
    monkeypatch.setattr(timeout, "asyncio", SimpleNamespace(get_running_loop=lambda: value))
    return value


def test_timeout_reason_clamp_and_scoped_classification():
    reason = timeout.TimeoutReason("BASH_TIMEOUT", 100.0)
    assert isinstance(reason, Exception)
    assert (reason.name, reason.code, reason.timeoutMs, reason.message) == (
        "TimeoutReason", "BASH_TIMEOUT", 100, "BASH_TIMEOUT after 100ms")
    assert timeout.timeout_of(dict(reason=reason)) is reason
    assert timeout.timeout_of(SimpleNamespace(reason=reason), "BASH_TIMEOUT") is reason
    assert timeout.timeout_of(dict(reason=reason), "OTHER") is None
    assert timeout.clamp_timeout(None, 120000, 600000) == 120000
    assert timeout.clamp_timeout(999999, 120000, 600000) == 600000
    assert timeout.clamp_timeout(5000, 120000, 600000) == 5000
    assert timeout.clamp_timeout(None, 900000, 600000) == 600000
    for carrier in ({}, dict(reason="user cancelled"), dict(reason=ValueError("other"))):
        assert timeout.timeout_of(carrier) is None


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True, "100", 10 ** 500])
def test_clamp_rejects_invalid_public_hint(value):
    with pytest.raises(ValueError, match="request.timeoutMs must be a positive finite number"):
        timeout.clamp_timeout(value, 100, 200, "request.timeoutMs")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), timeout.MAX_TIMER_DELAY_MS + 1, True, "100"])
def test_timer_rejects_unrepresentable_bound(clock, value):
    for factory in (timeout.deadline, timeout.idle_watchdog):
        with pytest.raises(ValueError, match="no greater than 2147483647"):
            factory(None, value, "TIMEOUT")
    assert not clock.timers


def test_deadline_boundary_disposal_and_first_reason(clock):
    upstream = AbortController()
    with timeout.deadline(upstream.signal, 100, "INNER") as d:
        clock.advance(99)
        assert not d.signal.aborted
        clock.advance(1)
        reason = timeout.timeout_of(d.signal, "INNER")
        assert reason.timeout_ms == 100
        upstream.abort("later")
        assert d.signal.reason is reason
    with timeout.deadline(None, 100, "OTHER") as disposed:
        disposed.dispose()
        disposed.dispose()
        clock.advance(1000)
        assert not disposed.signal.aborted


def test_deadline_upstream_first_and_preaborted_foreign_deadline(clock):
    upstream = AbortController()
    with timeout.deadline(upstream.signal, 100, "INNER") as d:
        upstream.abort("first")
        clock.advance(200)
        assert d.signal.reason == "first"
        assert timeout.timeout_of(d.signal) is None
    outer = AbortController()
    foreign = timeout.TimeoutReason("OUTER", 30)
    outer.abort(foreign)
    with timeout.deadline(outer.signal, 100, "INNER") as inner:
        assert inner.signal.aborted
        assert timeout.timeout_of(inner.signal, "INNER") is None
        assert timeout.timeout_of(inner.signal) is foreign


@pytest.mark.parametrize("interval", [0, -5])
def test_deadline_internal_no_timer_forwards_same_signal(clock, interval):
    upstream = AbortController()
    d = timeout.deadline(upstream.signal, interval, "NEVER")
    assert d.signal is upstream.signal
    assert not clock.timers
    upstream.abort("stop")
    assert d.signal.reason == "stop"
    d.dispose()
    without = timeout.deadline(None, interval, "NEVER")
    without.dispose()
    assert not without.signal.aborted


def test_disposed_timer_signal_keeps_upstream_forwarding_and_weak_ownership(clock):
    upstream = AbortController()
    d = timeout.deadline(upstream.signal, 100, "TIMEOUT")
    signal = d.signal
    d.dispose()
    del d
    clock.advance(200)
    assert not signal.aborted
    upstream.abort("after timer disposal")
    assert signal.reason == "after timer disposal"
    assert not upstream.signal._listeners

    controller = AbortController()
    holder = timeout.deadline(controller.signal, 100, "TIMEOUT")
    target = weakref.ref(holder.signal)
    holder.dispose()
    del holder
    # The fake clock retains cancelled callbacks until their due time.
    clock.advance(100)
    gc.collect()
    assert target() is None
    assert not controller.signal._listeners


@pytest.mark.asyncio
async def test_deadline_historical_event_adapter(clock):
    event = asyncio.Event()
    with timeout.deadline(event, 100, "TIMEOUT") as d:
        event.set()
        await asyncio.sleep(0)
        assert d.signal.aborted and timeout.timeout_of(d.signal) is None
        clock.advance(100)
        assert d.signal.reason is None


@pytest.mark.asyncio
async def test_watchdog_demand_only_stable_signal_and_pulse(clock):
    pending = asyncio.get_running_loop().create_future()
    iterator = SimpleNamespace(next=lambda: pending)
    with timeout.idle_watchdog(None, 100, "IDLE") as watchdog:
        stable = watchdog.signal
        watchdog.pulse()
        clock.advance(1000)
        assert not stable.aborted
        first = asyncio.create_task(watchdog.next(iterator))
        await asyncio.sleep(0)
        clock.advance(99)
        watchdog.pulse()
        clock.advance(99)
        assert not stable.aborted
        pending.set_result(dict(done=False, value=1))
        assert await first == dict(done=False, value=1)
        clock.advance(10000)
        assert not stable.aborted and watchdog.signal is stable
        pending = asyncio.get_running_loop().create_future()
        second = asyncio.create_task(watchdog.next(iterator))
        await asyncio.sleep(0)
        clock.advance(100)
        assert timeout.timeout_of(stable, "IDLE").timeout_ms == 100
        pending.set_exception(stable.reason)
        with pytest.raises(timeout.TimeoutReason) as caught:
            await second
        assert caught.value is stable.reason


@pytest.mark.asyncio
async def test_watchdog_disposal_concurrency_failure_and_native_iterator(clock):
    pending = asyncio.get_running_loop().create_future()
    iterator = SimpleNamespace(next=lambda: pending)
    watchdog = timeout.idle_watchdog(None, 100, "IDLE")
    first = asyncio.create_task(watchdog.next(iterator))
    await asyncio.sleep(0)
    with pytest.raises(RuntimeError, match="already outstanding"):
        await watchdog.next(iterator)
    watchdog.dispose()
    watchdog.dispose()
    watchdog.pulse()
    clock.advance(1000)
    assert not watchdog.signal.aborted and not first.done()
    pending.set_result(dict(done=True))
    assert await first == dict(done=True)
    with pytest.raises(RuntimeError, match="disposed"):
        await watchdog.next(iterator)

    async def stream():
        yield "first"
    with timeout.idle_watchdog(None, 100, "IDLE") as native:
        values = stream()
        assert await native.next(values) == "first"
        with pytest.raises(StopAsyncIteration):
            await native.next(values)
        clock.advance(1000)
        assert not native.signal.aborted


@pytest.mark.asyncio
async def test_watchdog_upstream_abort_and_waiter_cancellation(clock):
    upstream = AbortController()
    with timeout.idle_watchdog(upstream.signal, 100, "IDLE") as watchdog:
        pending = asyncio.get_running_loop().create_future()
        demand = asyncio.create_task(watchdog.next(SimpleNamespace(next=lambda: pending)))
        await asyncio.sleep(0)
        upstream.abort("caller")
        clock.advance(1000)
        assert watchdog.signal.reason == "caller"
        assert timeout.timeout_of(watchdog.signal) is None
        assert not demand.done()
        demand.cancel()
        with pytest.raises(asyncio.CancelledError):
            await demand
        assert watchdog._timer is None and not watchdog._outstanding


async def setup_tool(handler, budget=100):
    ctx = Context()
    await ctx.plugin(ToolsPlugin)
    fiber = await ctx.plugin(ToolCallTimeoutPolicyPlugin)
    spec = dict(name="probe", description="test", parameters={}, execute=handler,
                output=dict(schema={}, render=lambda _args, value: value))
    if budget is not None:
        spec["timeoutMs"] = budget
    ctx.get("tools").register(spec)
    return ctx, fiber


async def execute(ctx, signal):
    return await ctx.get("tools").execute(ToolExecutionInput("call", "probe", {}, signal=signal))


async def wait_for_abort(signal):
    settled = asyncio.get_running_loop().create_future()
    detach = subscribe_abort(signal, lambda *_args: settled.set_result(None) if not settled.done() else None)
    try:
        await settled
    finally:
        detach()


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", [None, 10000])
async def test_guard_fast_result_signal_restoration_and_unload(clock, budget):
    seen = []
    post = []
    async def tool(_args, exec):
        seen.append(exec.signal)
        return [dict(type="text", text="ok")]
    ctx, fiber = await setup_tool(tool, budget)
    async def observer(exec, _result, next_fn):
        post.append(exec.signal)
        return await next_fn()
    ctx.on("tools/post-execute", observer)
    upstream = AbortController()
    try:
        result = await execute(ctx, upstream.signal)
        assert not result.is_error and result.content == [dict(type="text", text="ok")]
        assert (seen[0] is upstream.signal) == (budget is None)
        assert post == [upstream.signal]
        clock.advance(20000)
        assert not seen[0].aborted
        await fiber.dispose()
        await execute(ctx, upstream.signal)
        assert seen[-1] is upstream.signal
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("throws", [False, True])
async def test_guard_deadline_waits_for_cleanup_and_classifies_first_reason(clock, throws):
    entered, saw_abort, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    seen = []
    async def tool(_args, exec):
        seen.append(exec.signal)
        entered.set()
        await wait_for_abort(exec.signal)
        saw_abort.set()
        await release.wait()
        if throws:
            raise HarnessError("web fetch aborted", "WEB_ABORTED")
        return [dict(type="text", text="cleanup complete")]
    ctx, _fiber = await setup_tool(tool)
    upstream = AbortController()
    task = asyncio.create_task(execute(ctx, upstream.signal))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        clock.advance(100)
        await asyncio.wait_for(saw_abort.wait(), 2)
        assert not task.done()
        assert timeout.timeout_of(seen[0], "TOOL_TIMEOUT") is not None
        upstream.abort("later user cancellation")
        release.set()
        result = await task
        expected = tool_timeout_result(100)
        assert result.is_error and result.content == expected["content"]
        assert result.error["message"] == expected["error"]["message"]
        assert result.error["info"] == expected["error"]["info"]
    finally:
        release.set()
        if not task.done():
            upstream.abort("cleanup")
            await task
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign", [False, True])
async def test_guard_preserves_user_or_foreign_deadline_abort(clock, foreign):
    entered = asyncio.Event()
    async def tool(_args, exec):
        entered.set()
        await wait_for_abort(exec.signal)
        return [dict(type="text", text="stopped")]
    ctx, _fiber = await setup_tool(tool)
    upstream = AbortController()
    task = asyncio.create_task(execute(ctx, upstream.signal))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        upstream.abort(timeout.TimeoutReason("OUTER_TIMEOUT", 30) if foreign else "user")
        clock.advance(200)
        result = await task
        assert result.is_error and result.error["info"]["code"] == "ABORTED"
    finally:
        if not task.done():
            upstream.abort("cleanup")
            await task
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_guard_does_not_claim_tool_owned_timeout_exception(clock):
    async def tool(_args, _exec):
        raise asyncio.TimeoutError("provider timeout")
    ctx, _fiber = await setup_tool(tool)
    try:
        result = await execute(ctx, AbortController().signal)
        assert result.is_error
        assert result.error["message"] == "provider timeout"
        assert result.error.get("info", {}).get("code") != "TOOL_TIMEOUT"
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_guard_restores_signal_when_downstream_wrapper_throws(clock):
    ctx = Context()
    upstream = AbortController()
    ctx.set_service("tools", SimpleNamespace(get=lambda *_args: SimpleNamespace(timeout_ms=100)))
    await ctx.plugin(ToolCallTimeoutPolicyPlugin)
    data = dict(name="probe", signal=upstream.signal)
    async def fail(*_args):
        assert data["signal"] is not upstream.signal
        raise asyncio.TimeoutError("wrapper failed")
    ctx.on("tools/execute", fail)
    try:
        with pytest.raises(asyncio.TimeoutError, match="wrapper failed"):
            await ctx.waterfall("tools/execute", data)
        assert data["signal"] is upstream.signal
        assert all(row[2].cancelled for row in clock.timers)
    finally:
        await ctx.fiber.dispose()


@pytest.mark.parametrize("value, text", [(100.0, "100"), (0.00001, "0.00001"),
                                        (0.000001, "0.000001"), (0.0000001, "1e-7"),
                                        (1e21, "1e+21"), (100.25, "100.25"),
                                        (float("nan"), "NaN"), (float("inf"), "Infinity"),
                                        (float("-inf"), "-Infinity")])
def test_timeout_message_uses_ecmascript_number_notation(value, text):
    assert timeout.TimeoutReason("TEST", value).message == "TEST after " + text + "ms"
    assert tool_timeout_result(value)["error"]["message"] == "tool call timed out after " + text + "ms"


@pytest.mark.asyncio
async def test_guard_actual_event_loop_timer_reaches_cooperative_tool():
    async def tool(_args, exec):
        await wait_for_abort(exec.signal)
        return [dict(type="text", text="released")]
    ctx, _fiber = await setup_tool(tool, 10)
    try:
        result = await asyncio.wait_for(execute(ctx, AbortController().signal), 2)
        assert result.is_error and result.error["info"]["code"] == "TOOL_TIMEOUT"
    finally:
        await ctx.fiber.dispose()
