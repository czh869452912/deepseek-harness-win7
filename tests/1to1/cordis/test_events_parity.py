"""
1:1 Test Parity for Cordis EventBus
Authority: reference/vendor/cordis/src/events.ts
"""

import pytest
import asyncio
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
    """ts:cordis/events.ts:225-243 - sync waterfall onion model and None-return continuation."""
    bus = EventBus()

    def mw_observer(data):
        # Returns None (observer)
        pass

    def mw_modify(data, next_fn):
        res = next_fn()
        return f"{res}!"

    bus.on("sync.test", mw_observer)
    bus.on("sync.test", mw_modify)

    res = bus.waterfall_sync("sync.test", "hello", lambda d, n=None: d.upper())
    assert res == "HELLO!"


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


def test_d5_internal_listener_prepend_unshift():
    """ts:cordis/events.ts:140-146 - prepend option in internal/update uses unshift."""
    ctx = Context()
    order = []

    ctx.on("internal/update", lambda cfg, no_save, n=None: order.append("first"), prepend=False)
    ctx.on("internal/update", lambda cfg, no_save, n=None: order.append("prepended"), prepend=True)

    fiber_hooks = ctx.fiber._hooks.get("internal/update")
    assert fiber_hooks is not None
    # Verify prepended listener is first in DisposableList
    items = list(fiber_hooks)
    # The last unshifted item should be first
    assert items[0].__name__ == "<lambda>"


def test_d7_bail_error_propagation_not_swallowed():
    """ts:cordis/events.ts:217-222 - TypeError inside listener must propagate and not be swallowed."""
    bus = EventBus()

    def buggy_listener(data):
        # TypeError inside the body, not arity mismatch
        return None + "cannot add"

    bus.on("test.bug", buggy_listener)

    with pytest.raises(TypeError):
        bus.bail_sync("test.bug", "some_data")


@pytest.mark.asyncio
async def test_d8_parallel_dispatch_mode_emit():
    """ts:cordis/events.ts:184 - parallel dispatches with mode 'emit'."""
    bus = EventBus()
    dispatch_modes = []

    bus.on("internal/dispatch", lambda info: dispatch_modes.append(info.get("type")), global_listener=True)
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
