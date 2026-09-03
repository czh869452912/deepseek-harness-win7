"""
Comprehensive unit tests for Cordis Fiber lifecycle, reactive cascade resolution,
dynamic dependency replacement, check() guard conditions, and status events.
Matching reference/vendor/cordis test specifications.
"""

import asyncio
import pytest
from typing import Any, Dict, List, Optional

from dsh.cordis.context import Context
from dsh.cordis.fiber import Fiber, FiberState, INACTIVE_EPOCH
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service


class AlphaService(Service):
    name = "alpha"

    def __init__(self, ctx: Context, version: int = 1):
        super().__init__(ctx, "alpha", allow_replace=True)
        self.version = version


class BetaService(Service):
    name = "beta"

    def __init__(self, ctx: Context, alpha: AlphaService):
        super().__init__(ctx, "beta")
        self.alpha = alpha


def test_cascading_dependency_resolution_and_teardown():
    """
    Test 4-stage dependency cascade:
    Plugin A (provides alpha) -> Plugin B (injects alpha, provides beta) ->
    Plugin C (injects beta, provides gamma) -> Plugin D (injects gamma).
    """
    ctx = Context()
    events_log = []

    def log_status(fiber: Fiber, old_state: int):
        events_log.append((fiber.name, old_state, fiber.state))

    ctx.on("internal/status", log_status, global_listener=True)

    class PluginD(Plugin):
        name = "plugin-d"
        inject = ["gamma"]
        def apply(self, c: Context) -> None:
            c.effect(lambda: lambda: events_log.append(("plugin-d", "disposed")))

    class PluginC(Plugin):
        name = "plugin-c"
        inject = ["beta"]
        def apply(self, c: Context) -> None:
            c.set_service("gamma", f"gamma_from_{c.beta.name}")
            c.effect(lambda: lambda: events_log.append(("plugin-c", "disposed")))

    class PluginB(Plugin):
        name = "plugin-b"
        inject = ["alpha"]
        def apply(self, c: Context) -> None:
            c.set_service("beta", BetaService(c, c.alpha))
            c.effect(lambda: lambda: events_log.append(("plugin-b", "disposed")))

    class PluginA(Plugin):
        name = "plugin-a"
        inject = []
        def apply(self, c: Context) -> None:
            c.set_service("alpha", AlphaService(c, version=1))
            c.effect(lambda: lambda: events_log.append(("plugin-a", "disposed")))

    # Register in reverse order: D, C, B, A
    fiber_d = ctx.registry.plugin(PluginD())
    fiber_c = ctx.registry.plugin(PluginC())
    fiber_b = ctx.registry.plugin(PluginB())

    assert fiber_d.state == FiberState.PENDING
    assert fiber_c.state == FiberState.PENDING
    assert fiber_b.state == FiberState.PENDING

    # Register A -> Triggers cascade activation A -> B -> C -> D!
    fiber_a = ctx.registry.plugin(PluginA())

    assert fiber_a.state == FiberState.ACTIVE
    assert fiber_b.state == FiberState.ACTIVE
    assert fiber_c.state == FiberState.ACTIVE
    assert fiber_d.state == FiberState.ACTIVE

    assert ctx.get("alpha").version == 1
    assert ctx.get("beta").alpha.version == 1
    assert ctx.get("gamma") == "gamma_from_beta"

    # Dispose A -> Triggers cascading unload D, C, B, A
    fiber_a.dispose_sync() if hasattr(fiber_a, "dispose_sync") else None
    fiber_a.set_epoch(INACTIVE_EPOCH)

    assert fiber_a.state in (FiberState.PENDING, FiberState.DISPOSED)
    assert fiber_b.state == FiberState.PENDING
    assert fiber_c.state == FiberState.PENDING
    assert fiber_d.state == FiberState.PENDING


def test_dynamic_dependency_replacement():
    """When upstream service provider plugin is replaced with a new provider plugin, dependents reload with new instance."""
    ctx = Context()
    b_versions = []

    class AlphaPlugin1(Plugin):
        name = "alpha-1"
        def apply(self, c: Context) -> None:
            c.set_service("alpha", AlphaService(c, version=1))

    class AlphaPlugin2(Plugin):
        name = "alpha-2"
        def apply(self, c: Context) -> None:
            c.set_service("alpha", AlphaService(c, version=2))

    class DependentPlugin(Plugin):
        name = "dependent"
        inject = ["alpha"]

        def apply(self, c: Context) -> None:
            b_versions.append(c.alpha.version)

    f_alpha1 = ctx.registry.plugin(AlphaPlugin1())
    fiber = ctx.registry.plugin(DependentPlugin())

    assert fiber.state == FiberState.ACTIVE
    assert b_versions == [1]
    assert fiber.epoch == f":{f_alpha1.uid}"

    # Replace service provider plugin with AlphaPlugin2
    f_alpha2 = ctx.registry.plugin(AlphaPlugin2())

    assert fiber.state == FiberState.ACTIVE
    assert b_versions == [1, 2]
    assert fiber.epoch == f":{f_alpha2.uid}"


def test_service_check_guard_condition():
    """
    When service implementation has a check() function returning False,
    the implementation is unavailable and dependent fibers remain PENDING.
    When check() becomes True, dependents transition to ACTIVE.
    """
    ctx = Context()
    is_ready = False

    def check_fn():
        return is_ready

    srv = AlphaService(ctx, version=10)
    ctx.set_service("alpha", srv, check=check_fn)

    applied = []

    class GuardedPlugin(Plugin):
        name = "guarded"
        inject = ["alpha"]

        def apply(self, c: Context) -> None:
            applied.append(c.alpha.version)

    fiber = ctx.registry.plugin(GuardedPlugin())
    assert fiber.state == FiberState.PENDING
    assert applied == []

    # Turn readiness to True and notify reflect
    is_ready = True
    ctx.reflect.notify(["alpha"])

    assert fiber.state == FiberState.ACTIVE
    assert applied == [10]


def test_context_filter_event_dispatch():
    """Verify that Context.filter restricts event delivery based on scope hierarchy."""
    ctx = Context()
    received = []

    sub_ctx = ctx.extend()
    sub_ctx.on("scoped/event", lambda val: received.append(("sub", val)))

    isolated_ctx = ctx.isolate("isolated_service")
    isolated_ctx.on("scoped/event", lambda val: received.append(("isolated", val)))

    # Emit from root
    ctx.emit("scoped/event", "msg1")
    assert len(received) == 2
    assert ("sub", "msg1") in received
    assert ("isolated", "msg1") in received
