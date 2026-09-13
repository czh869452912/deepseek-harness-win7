"""
1:1 parity unit test suite for dsh/cordis/registry.py matching reference/vendor/cordis/src/registry.ts.
Covers:
- T1: Service provided by class plugin unloads when plugin fiber is disposed
- T4: @inject class decorator does not mutate base class inject dict
- T5: inject intercept config reaches service
- T6: Object plugin named 'apply' is treated as anonymous and inherits ancestor name
- T7: Plugin can be loaded on FAILED fiber matching TS assertActive behavior
- T8: internal/plugin listener can see the fiber in registry.list_fibers()
- T9: One `RegistryService.counter` allocates fiber uids across root and
  derived contexts (`ctx.extend()`/`isolate()`/`intercept()`)
- T9b: `counter` increments on every read (registry.ts `get counter()`)
- T10: inspection drops a fiber on its own disposal (`registry.ts:258-265`
  keeps no auxiliary pending-fiber index; the child disposer removes the fiber)
- T11: a disposed fiber of a live runtime is not reported while its live sibling is
"""

import pytest
import asyncio
from typing import Any

from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service
from dsh.cordis.registry import inject


@pytest.mark.asyncio
async def test_t1_service_provided_by_class_plugin_disposed_on_plugin_unload():
    """T1: Service provided by class plugin is unregistered when fiber is disposed."""
    ctx = Context()

    class SvcPlugin(Service):
        name = "svc_service"

        def __init__(self, c: Context):
            super().__init__(c, "svc_service")

    fiber = ctx.plugin(SvcPlugin)
    assert ctx.has("svc_service")
    assert ctx.get("svc_service") is not None

    await fiber.dispose()
    assert ctx.get("svc_service") is None
    assert "svc_service" not in ctx.reflect.store


def test_t4_inject_decorator_does_not_mutate_base_class_inject():
    """T4: @inject decorator does not mutate base class inject dict."""
    class BasePlugin(Plugin):
        name = "base"
        inject = ["base_dep"]

    @inject("child_dep")
    class ChildPlugin(BasePlugin):
        name = "child"

    assert "base_dep" in BasePlugin.inject
    assert "child_dep" not in BasePlugin.inject
    assert "base_dep" in ChildPlugin.inject
    assert "child_dep" in ChildPlugin.inject


@pytest.mark.asyncio
async def test_t5_inject_intercept_config_reaches_service_resolve_config():
    """T5: inject intercept config reaches service without required flag pollution."""
    ctx = Context()
    captured_config = {}

    class InterceptService(Service):
        name = "db_service"

        def __init__(self, c: Context):
            super().__init__(c, "db_service")

    ctx.plugin(InterceptService)

    class Consumer(Plugin):
        name = "consumer"
        inject = {"db_service": {"pool": 5}}

        def apply(self, c: Context) -> None:
            captured_config.update(getattr(c, "_intercept_map", {}).get("db_service", {}))

    fiber = ctx.plugin(Consumer)
    assert fiber.state == FiberState.ACTIVE
    assert captured_config.get("pool") == 5
    assert "required" not in captured_config


@pytest.mark.asyncio
async def test_t6_object_plugin_named_apply_is_anonymous():
    """T6: Object plugin with name='apply' is treated as anonymous."""
    ctx = Context()
    child_fiber_ref = []

    class NamedParent(Plugin):
        name = "parent_named"

        def apply(self, c: Context) -> None:
            obj_plugin = {
                "name": "apply",
                "apply": lambda child_ctx: None,
            }
            f = c.plugin(obj_plugin)
            child_fiber_ref.append(f)

    ctx.plugin(NamedParent)
    assert len(child_fiber_ref) == 1
    child_fiber = child_fiber_ref[0]
    assert child_fiber.name == "parent_named"


@pytest.mark.asyncio
async def test_t7_plugin_can_load_on_failed_fiber_like_ts():
    """T7: Plugin can be loaded on FAILED fiber because uid is not None."""
    ctx = Context()

    class FailingParent(Plugin):
        name = "failing_parent"

        def apply(self, c: Context) -> None:
            raise RuntimeError("Setup failed")

    parent_fiber = ctx.plugin(FailingParent)
    assert parent_fiber.state == FiberState.FAILED
    assert parent_fiber.uid is not None

    class SiblingPlugin(Plugin):
        name = "sibling"

        def apply(self, c: Context) -> None:
            pass

    # Loading child on parent_fiber.ctx should succeed because parent_fiber.uid is not None
    child_fiber = parent_fiber.ctx.plugin(SiblingPlugin)
    assert child_fiber.state == FiberState.ACTIVE


@pytest.mark.asyncio
async def test_t8_internal_plugin_listener_sees_fiber_in_registry():
    """T8: internal/plugin listener can see the fiber in registry."""
    ctx = Context()
    seen_in_registry = []

    def on_plugin(fiber):
        all_fibers = ctx.registry.list_fibers()
        seen_in_registry.append(fiber in all_fibers)

    ctx.on("internal/plugin", on_plugin)

    class MyPlugin(Plugin):
        name = "my_plugin"

    fiber = ctx.plugin(MyPlugin)
    assert len(seen_in_registry) == 1
    assert seen_in_registry[0] is True


@pytest.mark.asyncio
async def test_t9_registry_counter_is_shared_across_derived_contexts():
    """T9: one `RegistryService.counter` allocates every fiber uid in the tree.

    Reference: `registry.ts#RegistryService` is installed once by the Context
    constructor, and `context.ts` derived contexts (`extend`/`isolate`/
    `intercept`) only inherit properties through the prototype chain, so every
    `ctx.registry` is the same service instance whose
    `get counter() { return ++this._counter }` allocates `this.uid =
    parent.registry.counter` (`fiber.ts` constructor). A bound Python registry
    view must therefore share the allocator state instead of copying the
    counter, otherwise plugins mounted from a derived context re-use uids
    already handed to a sibling.
    """
    root = Context()
    derived = root.extend().isolate("t9_isolated").intercept("t9_isolated", {})

    # Every read allocates the next value, whichever context reads it.
    first = root.registry.counter
    second = derived.registry.counter
    third = root.registry.counter
    assert (first, second, third) == (first, first + 1, first + 2)

    class RootPlugin(Plugin):
        name = "t9_root"

    class DerivedPlugin(Plugin):
        name = "t9_derived"

    class LaterRootPlugin(Plugin):
        name = "t9_later_root"

    root_fiber = root.plugin(RootPlugin, {})
    derived_fiber = derived.plugin(DerivedPlugin, {})
    later_root_fiber = root.plugin(LaterRootPlugin, {})

    uids = [root_fiber.uid, derived_fiber.uid, later_root_fiber.uid]
    assert len(set(uids)) == 3
    assert uids == [third + 1, third + 2, third + 3]


@pytest.mark.asyncio
async def test_t9b_counter_property_increments_on_every_read():
    """T9b: `counter` is a getter that increments, not a snapshot of `_counter`."""
    ctx = Context()
    child = ctx.extend()

    values = [ctx.registry.counter for _ in range(3)]
    assert values == [values[0], values[0] + 1, values[0] + 2]
    assert child.registry.counter == values[0] + 3


@pytest.mark.asyncio
async def test_t10_registry_inspection_drops_a_fiber_on_its_own_disposal():
    """T10: pending and activated fibers are reported only while they are live.

    Reference: `registry.ts:258-265`. `registry.values()` hands out the runtimes
    and each runtime's `fibers` is a `DisposableList` the child disposer removes
    from, so an activated or disposed fiber can never be reported through a
    retained auxiliary index.
    """
    ctx = Context()

    class LateServicePlugin(Plugin):
        name = "t10_late_service"
        inject = ["t10_service"]

        def apply(self, c: Context) -> None:
            pass

    fiber = ctx.registry.plugin(LateServicePlugin)
    assert fiber.state == FiberState.PENDING
    assert fiber in ctx.registry.list_fibers()

    ctx.set_service("t10_service", {"value": 1})
    assert fiber.state == FiberState.ACTIVE
    assert fiber in ctx.registry.list_fibers()

    await fiber.dispose()

    assert fiber.state == FiberState.DISPOSED
    assert ctx.registry.has(LateServicePlugin) is False
    assert fiber not in ctx.registry.list_fibers()
    assert ctx.registry.list_fibers() == []


@pytest.mark.asyncio
async def test_t11_disposed_fiber_of_a_live_runtime_is_not_reported():
    """T11: a disposed fiber leaves inspection while its sibling stays registered.

    Reference: `registry.ts:263-265` delegates removal to each fiber's own
    disposer, so a runtime keeps reporting exactly its live fibers.
    """
    ctx = Context()

    class TwinPlugin(Plugin):
        name = "t11_twin"

    first = ctx.registry.plugin(TwinPlugin)
    second = ctx.registry.plugin(TwinPlugin)
    assert first in ctx.registry.list_fibers()
    assert second in ctx.registry.list_fibers()

    await first.dispose()

    runtime = ctx.registry.get(TwinPlugin)
    assert runtime is not None
    assert runtime.fibers == [second]
    assert first not in ctx.registry.list_fibers()
    assert second in ctx.registry.list_fibers()

    await second.dispose()

    assert ctx.registry.has(TwinPlugin) is False
    assert ctx.registry.list_fibers() == []
