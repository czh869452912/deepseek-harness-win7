"""
1:1 parity unit test suite for dsh/cordis/registry.py matching reference/vendor/cordis/src/registry.ts.
Covers:
- T1: Service provided by class plugin unloads when plugin fiber is disposed
- T4: @inject class decorator does not mutate base class inject dict
- T5: inject intercept config reaches service
- T6: Object plugin named 'apply' is treated as anonymous and inherits ancestor name
- T7: Plugin can be loaded on FAILED fiber matching TS assertActive behavior
- T8: internal/plugin listener can see the fiber in registry.list_fibers()
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
