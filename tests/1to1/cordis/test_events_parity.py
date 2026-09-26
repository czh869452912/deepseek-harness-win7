"""
1:1 Test Parity for Cordis EventBus
Authority: reference/vendor/cordis/src/events.ts
"""

import asyncio
import gc
import threading
import warnings

import pytest
from dsh.cordis.context import Context
from dsh.cordis.events import EventBus, is_bailed
from dsh.cordis.utils import DisposableList


@pytest.mark.asyncio
async def test_d1_d2_waterfall_onion_middleware_and_veto():
    """ts:cordis/events.ts:225-243 - onion middleware return value propagation and explicit veto."""
    bus = EventBus()

    call_order = []

    async def mw1(data, next_fn):
        call_order.append("mw1_before")
        res = await next_fn()
        call_order.append("mw1_after")
        return f"{res}_mw1"

    async def mw2(data, next_fn):
        call_order.append("mw2_before")
        res = await next_fn()
        call_order.append("mw2_after")
        return f"{res}_mw2"

    async def inner(data, next_fn=None):
        call_order.append("inner")
        return f"{data}_inner"

    bus.on("test.waterfall", mw1)
    bus.on("test.waterfall", mw2)

    result = await bus.waterfall("test.waterfall", "root", inner)
    assert result == "root_inner_mw2_mw1"
    assert call_order == ["mw1_before", "mw2_before", "inner", "mw2_after", "mw1_after"]


@pytest.mark.asyncio
async def test_d2_waterfall_short_circuit_veto():
    """ts:cordis/events.ts:227-230 - listener without calling next vetoes downstream."""
    bus = EventBus()

    async def mw_veto(data, next_fn):
        # Does not call next_fn, returns veto result
        return "vetoed"

    async def mw_never(data, next_fn):
        return await next_fn()

    bus.on("test.veto", mw_veto)
    bus.on("test.veto", mw_never)

    res = await bus.waterfall("test.veto", "input", lambda d, n=None: "inner")
    assert res == "vetoed"


def test_d2_waterfall_sync_onion_and_none_continuation():
    """ts:cordis/events.ts:225-243 - sync waterfall onion model."""
    bus = EventBus()

    def mw_observer(data, next_fn):
        # Calls next_fn and returns result
        return next_fn()

    def mw_modify(data, next_fn):
        res = next_fn()
        return f"{res}!"

    bus.on("sync.test", mw_observer)
    bus.on("sync.test", mw_modify)

    res = bus.waterfall_sync("sync.test", "hello", lambda d, n=None: d.upper())
    assert res == "HELLO!"


def test_d2_waterfall_sync_veto_without_next():
    """ts:cordis/events.ts:225-243 - sync waterfall listener returning without calling next() vetoes."""
    bus = EventBus()

    def mw_veto(data):
        # Does not call next_fn, returns None (veto)
        return None

    def mw_modify(data, next_fn):
        res = next_fn()
        return f"{res}!"

    bus.on("sync.test", mw_veto)
    bus.on("sync.test", mw_modify)

    res = bus.waterfall_sync("sync.test", "hello", lambda d, n=None: d.upper())
    assert res is None


@pytest.mark.asyncio
async def test_d3_waterfall_inner_receives_all_args():
    """ts:cordis/events.ts:236-242 - inner receives all remaining arguments plus next."""
    bus = EventBus()

    captured = {}

    def inner_callback(arg1, arg2, next_fn=None):
        captured["arg1"] = arg1
        captured["arg2"] = arg2
        captured["next_callable"] = callable(next_fn)
        return "done"

    await bus.waterfall("test.args", "val1", "val2", inner_callback)
    assert captured["arg1"] == "val1"
    assert captured["arg2"] == "val2"
    assert captured["next_callable"] is True


def test_d2_waterfall_reducer_via_next():
    """Waterfall middleware reducer pattern transforming return value via next."""
    ctx = Context()

    def step1(data, next_fn):
        return f"{next_fn()}_step1"

    def step2(data, next_fn=None):
        res = next_fn() if next_fn else data
        return f"{res}_step2"

    ctx.on("test.reduce", step1)
    ctx.on("test.reduce", step2)

    res = ctx.waterfall_sync("test.reduce", "init", lambda d: d)
    assert res == "init_step2_step1"


def test_d5_internal_listener_prepend_unshift():
    """ts:cordis/events.ts:140-146 - prepend option in internal/update uses unshift."""
    ctx = Context()
    order = []

    def first_listener(cfg, no_save, n=None):
        order.append("first")
        if n and callable(n):
            return n(cfg, no_save)

    def prepended_listener(cfg, no_save, n=None):
        order.append("prepended")
        if n and callable(n):
            return n(cfg, no_save)

    ctx.on("internal/update", first_listener, prepend=False)
    ctx.on("internal/update", prepended_listener, prepend=True)

    fiber_hooks = ctx.fiber._hooks.get("internal/update")
    assert fiber_hooks is not None
    # Verify prepended listener is strictly first in DisposableList by function identity
    items = list(fiber_hooks)
    assert getattr(items[0], "__wrapped__", items[0]) is prepended_listener
    assert getattr(items[1], "__wrapped__", items[1]) is first_listener

    # Verify execution order: prepended listener executes first
    ctx.emit("internal/update", {}, False)
    assert order == ["prepended", "first"]


def test_d7_bail_error_propagation_not_swallowed():
    """ts:cordis/events.ts:217-222 - TypeError inside listener must propagate and not be swallowed."""
    bus = EventBus()

    def buggy_listener(data):
        # TypeError inside the body, not arity mismatch
        return None + "cannot add"

    bus.on("test.bug", buggy_listener)

    with pytest.raises(TypeError):
        bus.bail("test.bug", "some_data")


@pytest.mark.asyncio
async def test_d8_parallel_dispatch_mode_emit():
    """ts:cordis/events.ts:184 - parallel dispatches with mode 'emit'."""
    bus = EventBus()
    dispatch_modes = []

    bus.on("internal/dispatch", lambda disp_type, *_: dispatch_modes.append(disp_type), global_listener=True)
    await bus.parallel("test.parallel", 1, 2)

    assert "emit" in dispatch_modes


def test_d9_dispatch_hooks_filter_exception_propagates():
    """ts:cordis/events.ts:171-174 - exceptions in ctx.filter propagate without being swallowed."""
    bus = EventBus()

    class BuggyContext:
        def filter(self, hook_ctx):
            raise RuntimeError("Filter crashed")

    ctx = BuggyContext()

    def dummy():
        pass

    bus.on("test.filter_crash", dummy)

    with pytest.raises(RuntimeError) as exc_info:
        bus.emit("test.filter_crash", caller_ctx=ctx)
    assert "Filter crashed" in str(exc_info.value)


def test_d9_emit_runs_a_loop_less_async_listener_without_waiting_for_its_settlement():
    """ts:cordis/events.ts:189-196 - `emit` runs listeners synchronously without waiting for
    returned promises: the listener body starts inside the dispatch, its settlement happens
    after `emit` returned, and the port keeps the awaitable owned until it settles."""
    bus = EventBus()
    steps = []
    release = threading.Event()

    async def listener(value):
        steps.append(("entered", value))
        await asyncio.get_running_loop().run_in_executor(None, release.wait)
        steps.append(("settled", value))

    bus.on("test.async_emit", listener)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        bus.emit("test.async_emit", 1)

        assert steps == [("entered", 1)]
        assert bus.pending_loopless_settlements() == 1

        release.set()
        assert bus.join_loopless_settlements(10.0) is True
        gc.collect()

    assert steps == [("entered", 1), ("settled", 1)]
    assert bus.pending_loopless_settlements() == 0
    assert [str(w.message) for w in caught if "never awaited" in str(w.message)] == []


def test_d9_emit_reports_a_failing_loop_less_async_listener_without_raising():
    """ts:cordis/events.ts:194-196 - the dispatch discards listener results, so a failing async
    listener settles and reports independently and never aborts the synchronous emitter."""
    errors = []

    class RecordingLogger:
        def error(self, format_str, *args):
            errors.append(format_str % args)

    class LoggingContext:
        def logger(self, name):
            return RecordingLogger()

    bus = EventBus(ctx=LoggingContext())
    entered = []

    async def listener():
        entered.append(True)
        await asyncio.sleep(0)
        raise RuntimeError("listener-boom")

    bus.on("test.async_emit_failure", listener)
    bus.emit("test.async_emit_failure")

    assert bus.join_loopless_settlements(10.0) is True
    assert entered == [True]
    assert errors == ["Listener for 'test.async_emit_failure' failed: listener-boom"]
    assert bus.pending_loopless_settlements() == 0

def test_d9_emit_holds_loop_less_continuations_behind_the_dispatch_barrier():
    """ts:cordis/events.ts:194-195 - `this.dispatch('emit', args).map(cb => cb(...args))` invokes
    every listener in one synchronous pass and discards the returned promises, so a loop-less
    async listener's continuation is held by the dispatch-wide release barrier: no continuation
    can resume before the emitter has invoked the last listener of the same dispatch."""
    bus = EventBus()
    steps = []
    seen_at_resume = []
    release = threading.Event()

    async def first():
        steps.append("first-prefix")
        await asyncio.sleep(0)
        seen_at_resume.append(list(steps))
        await asyncio.get_running_loop().run_in_executor(None, release.wait)
        steps.append("first-continuation")

    def second():
        steps.append("second-listener")

    async def third():
        steps.append("third-prefix")
        await asyncio.sleep(0)
        await asyncio.get_running_loop().run_in_executor(None, release.wait)
        steps.append("third-continuation")

    bus.on("test.emit_barrier", first)
    bus.on("test.emit_barrier", second)
    bus.on("test.emit_barrier", third)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        bus.emit("test.emit_barrier")

        # Every listener and its synchronous prefix has run and both settlements are owned.
        assert steps == ["first-prefix", "second-listener", "third-prefix"]
        assert bus.pending_loopless_settlements() == 2

        release.set()
        assert bus.join_loopless_settlements(10.0) is True
        gc.collect()

    assert steps == [
        "first-prefix",
        "second-listener",
        "third-prefix",
        "first-continuation",
        "third-continuation",
    ]
    # Each continuation resumed only once the dispatch had invoked every listener.
    assert seen_at_resume == [["first-prefix", "second-listener", "third-prefix"]]
    assert bus.pending_loopless_settlements() == 0
    assert [str(w.message) for w in caught if "never awaited" in str(w.message)] == []


def test_d9_emit_releases_held_loop_less_settlements_when_a_listener_raises():
    """ts:cordis/events.ts:194-195 - a listener that throws out of the synchronous dispatch does
    not abandon the continuations already held by the dispatch barrier: they still settle."""
    bus = EventBus()
    steps = []
    resumed = threading.Event()

    async def first():
        steps.append("first-prefix")
        await asyncio.sleep(0)
        resumed.set()

    def second():
        raise RuntimeError("second-listener-boom")

    bus.on("test.emit_barrier_raise", first)
    bus.on("test.emit_barrier_raise", second)

    with pytest.raises(RuntimeError) as exc_info:
        bus.emit("test.emit_barrier_raise")
    assert "second-listener-boom" in str(exc_info.value)

    assert steps == ["first-prefix"]
    assert bus.pending_loopless_settlements() == 1

    assert resumed.wait(10.0) is True
    assert bus.join_loopless_settlements(10.0) is True
    assert bus.pending_loopless_settlements() == 0


def test_d9_emit_settles_a_loop_less_listener_that_suspends_on_a_pending_future():
    """ts:cordis/events.ts:189-196 - a loop-less listener that suspends on a future it awaits
    (not a bare yield) keeps that suspension owned and resumes with the future's result."""
    bus = EventBus()
    steps = []
    gates = []

    async def listener():
        steps.append("prefix")
        gate = asyncio.Future()
        gates.append(gate)
        steps.append(await gate)

    bus.on("test.async_emit_future", listener)
    bus.emit("test.async_emit_future")

    assert steps == ["prefix"]
    assert bus.pending_loopless_settlements() == 1

    gates[0].get_loop().call_soon_threadsafe(gates[0].set_result, "resolved")
    assert bus.join_loopless_settlements(10.0) is True
    assert steps == ["prefix", "resolved"]
    assert bus.pending_loopless_settlements() == 0


def test_d9_emit_settlement_cancellation_reaches_the_loop_less_listener_cleanup():
    """ts:cordis/events.ts:189-196 - the loop-less settlement is an owned task-like driver, so
    cancelling it is delivered into the listener at its suspension point and its cleanup runs."""
    bus = EventBus()
    steps = []
    cleaned = threading.Event()

    async def listener():
        steps.append("prefix")
        try:
            await asyncio.sleep(30.0)
            steps.append("never")
        finally:
            steps.append("finally")
            cleaned.set()

    bus.on("test.async_emit_cancel", listener)
    bus.emit("test.async_emit_cancel")

    assert steps == ["prefix"]
    assert bus.pending_loopless_settlements() == 1

    (settlement,) = list(bus._loopless_settlements)
    settlement.cancel()

    # Cancelling the settlement marks its future done before the owned loop has delivered the
    # cancellation to the listener, so the cleanup itself is what is waited for here.
    assert cleaned.wait(10.0) is True
    assert bus.join_loopless_settlements(10.0) is True
    assert steps == ["prefix", "finally"]
    assert bus.pending_loopless_settlements() == 0
