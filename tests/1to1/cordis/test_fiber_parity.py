"""
1:1 parity unit test suite for dsh/cordis/fiber.py matching reference/vendor/cordis/src/fiber.ts.
Covers:
- T1: Parent unload cascades dispose to child fibers (D1)
- T2: Direct fiber.dispose() deregisters from registry and runtime.fibers (D2)
- T3: internal/plugin disposed event emitted before unload with listener error isolation (D3)
- T4: inject intercept config populated on ctx._intercept_map (D4)
- T5: name property inherits from nearest named ancestor (D5)
- T6: FAILED fiber still allows effect registration (D6)
- T16: Disposed fiber with error reports DISPOSED state (D16)
- T17: CordisError default message text (D17)
- T18: Root fiber dispose restarts instead of destroying (D18)
"""

import asyncio
import pytest
from typing import Any

from dsh.cordis.context import Context
from dsh.cordis.fiber import CordisError, Fiber, FiberState
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service


@pytest.mark.asyncio
async def test_t1_parent_unload_disposes_child_fibers():
    """T1 (D1): Parent unload cascades dispose to child fibers."""
    ctx = Context()
    child_disposed = []

    class ChildPlugin(Plugin):
        name = "child_plugin"

        def apply(self, c: Context) -> None:
            c.effect(lambda: (lambda: child_disposed.append(True)))

    class ParentPlugin(Plugin):
        name = "parent_plugin"

        def apply(self, c: Context) -> None:
            c.plugin(ChildPlugin)

    parent_fiber = ctx.plugin(ParentPlugin)
    assert parent_fiber.state == FiberState.ACTIVE
    assert ctx.registry.has(ChildPlugin)

    await parent_fiber.dispose()

    assert parent_fiber.state == FiberState.DISPOSED
    assert len(child_disposed) == 1
    assert not ctx.registry.has(ChildPlugin)


@pytest.mark.asyncio
async def test_t2_direct_fiber_dispose_deregisters_from_registry():
    """T2 (D2): Direct fiber.dispose() deregisters from registry."""
    ctx = Context()

    class SimplePlugin(Plugin):
        name = "simple_plugin"

    fiber = ctx.plugin(SimplePlugin)
    assert ctx.registry.has(SimplePlugin)

    await fiber.dispose()

    assert fiber.state == FiberState.DISPOSED
    assert not ctx.registry.has(SimplePlugin)
    assert fiber not in ctx.registry.list_fibers()


@pytest.mark.asyncio
async def test_t3_internal_plugin_disposed_event_before_unload_and_error_isolated():
    """T3 (D3): internal/plugin disposed event is emitted before unload with listener error isolation."""
    ctx = Context()
    event_order = []

    class TrackedPlugin(Plugin):
        name = "tracked_plugin"

        def apply(self, c: Context) -> None:
            c.effect(lambda: (lambda: event_order.append("effect_unloaded")))

    def on_plugin_1(fiber: Fiber):
        if fiber.uid is None:
            event_order.append("event_uid_none")

    def on_plugin_failing(fiber: Fiber):
        if fiber.uid is None:
            raise RuntimeError("Listener error must be isolated")

    ctx.on("internal/plugin", on_plugin_1)
    ctx.on("internal/plugin", on_plugin_failing)

    fiber = ctx.plugin(TrackedPlugin)
    await fiber.dispose()

    assert "event_uid_none" in event_order
    assert "effect_unloaded" in event_order
    # Event emitted before unload
    assert event_order.index("event_uid_none") < event_order.index("effect_unloaded")


@pytest.mark.asyncio
async def test_t4_inject_intercept_config_reaches_intercept_map():
    """T4 (D4): inject intercept config is written to ctx._intercept_map."""
    ctx = Context()
    ctx.provide("my_service", object())
    captured_intercept = {}

    class InterceptConsumer(Plugin):
        name = "intercept_consumer"
        inject = {"my_service": {"custom_intercept_key": "custom_val"}}

        def apply(self, c: Context) -> None:
            captured_intercept.update(getattr(c, "_intercept_map", {}))

    fiber = ctx.plugin(InterceptConsumer)
    assert fiber.state == FiberState.ACTIVE
    assert "my_service" in captured_intercept
    assert captured_intercept["my_service"] == {"custom_intercept_key": "custom_val"}


@pytest.mark.asyncio
async def test_t5_name_inherits_nearest_named_ancestor():
    """T5 (D5): Anonymous child fiber inherits name of nearest named ancestor."""
    ctx = Context()
    child_fiber_ref = []

    class NamedParent(Plugin):
        name = "grand_parent_runtime"

        def apply(self, c: Context) -> None:
            def anonymous_child(child_ctx: Context):
                pass
            f = c.plugin(anonymous_child)
            child_fiber_ref.append(f)

    parent_fiber = ctx.plugin(NamedParent)
    assert len(child_fiber_ref) == 1
    child_fiber = child_fiber_ref[0]
    assert child_fiber.name == "grand_parent_runtime"


@pytest.mark.asyncio
async def test_t6_failed_fiber_still_allows_effect_registration():
    """T6 (D6): FAILED fiber (uid not None) still allows effect registration."""
    ctx = Context()

    class FailingPlugin(Plugin):
        name = "failing_plugin"

        def apply(self, c: Context) -> None:
            raise ValueError("Intentional startup failure")

    fiber = ctx.plugin(FailingPlugin)
    assert fiber.state == FiberState.FAILED
    assert fiber.uid is not None

    # Should not raise CordisError("INACTIVE_EFFECT")
    cleaned = []
    disposer = fiber.ctx.effect(lambda: (lambda: cleaned.append(True)))
    assert callable(disposer)

    await fiber.dispose()
    assert len(cleaned) == 1


@pytest.mark.asyncio
async def test_t16_disposed_fiber_with_error_reports_disposed():
    """T16 (D16): Disposed fiber that previously failed reports DISPOSED, not FAILED."""
    ctx = Context()

    class FailingPlugin(Plugin):
        name = "failing_plugin"

        def apply(self, c: Context) -> None:
            raise ValueError("Fatal crash")

    fiber = ctx.plugin(FailingPlugin)
    assert fiber.state == FiberState.FAILED

    await fiber.dispose()
    assert fiber.state == FiberState.DISPOSED


def test_t17_cordis_error_default_message_text():
    """T17 (D17): CordisError default message text matches CODE_MESSAGES."""
    err = CordisError("INACTIVE_EFFECT")
    assert str(err) == "cannot create effect on inactive context"
    assert err.code == "INACTIVE_EFFECT"


@pytest.mark.asyncio
async def test_t18_root_fiber_dispose_restarts_instead_of_destroying():
    """T18 (D18): Root fiber dispose restarts rather than transitioning to DISPOSED."""
    ctx = Context()
    root_fiber = ctx.fiber
    assert root_fiber.uid == 0
    assert root_fiber.state == FiberState.ACTIVE

    await root_fiber.dispose()
    assert root_fiber.uid == 0
    assert root_fiber.state in (FiberState.ACTIVE, FiberState.LOADING)
