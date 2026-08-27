import asyncio
import pytest
from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.cordis.fiber import FiberState


class SamplePlugin(Plugin):
    id = "sample"
    name = "sample-plugin"

    def apply(self, ctx):
        ctx.set_service("sample_service", "hello_service")


class DependentPlugin(Plugin):
    id = "dependent"
    inject = ["required_db"]

    def apply(self, ctx):
        ctx.set_service("dependent_ready", True)


def test_context_service_and_plugin():
    ctx = Context()
    ctx.plugin(SamplePlugin)

    assert ctx.has("sample_service")
    assert ctx.get("sample_service") == "hello_service"
    assert len(ctx.list_plugins()) == 1
    assert ctx.list_plugins()[0]["id"] == "sample"


@pytest.mark.asyncio
async def test_fiber_reactive_dependency_resolution():
    ctx = Context()
    
    # Mount dependent plugin before required service exists
    plugin_inst = ctx.plugin(DependentPlugin)
    fiber = ctx.registry.get_fiber("dependent")
    assert fiber is not None
    assert fiber.state == FiberState.PENDING
    assert not ctx.has("dependent_ready")

    # Provide required dependency
    ctx.set_service("required_db", "connected_db")
    await fiber.wait()
    assert fiber.state == FiberState.ACTIVE
    assert ctx.get("dependent_ready") is True


@pytest.mark.asyncio
async def test_event_bus_modes():
    ctx = Context()
    logs = []

    # 1. Emit
    ctx.on("test/emit", lambda val: logs.append(f"emit:{val}"))
    ctx.emit("test/emit", "a")
    assert logs == ["emit:a"]

    # 2. Waterfall
    async def middleware1(data, next_fn):
        res = await next_fn(data + "_m1")
        return res + "_m1_end"

    async def middleware2(data, next_fn):
        return await next_fn(data + "_m2")

    ctx.on("test/waterfall", middleware1)
    ctx.on("test/waterfall", middleware2)

    res = await ctx.waterfall("test/waterfall", "init", lambda value: value)
    assert res == "init_m1_m2_m1_end"

    # 2b. Waterfall with simple transformer (no next_fn parameter)
    def transformer1(data):
        return data + "-t1"

    async def transformer2(data):
        return data + "-t2"

    ctx.on("test/transform", transformer1)
    ctx.on("test/transform", transformer2)
    t_res = await ctx.waterfall("test/transform", "start", lambda value: value)
    assert t_res == "start-t1-t2"

    # 3. Parallel
    async def p1():
        await asyncio.sleep(0.01)
        return "p1"

    async def p2():
        return "p2"

    ctx.on("test/parallel", p1)
    ctx.on("test/parallel", p2)
    p_res = await ctx.parallel("test/parallel")
    assert p_res is None

    # 4. Bail 1:1 Semantics (False should NOT trigger bail; non-None non-False triggers bail)
    ctx.on("test/bail", lambda: False)
    ctx.on("test/bail", lambda: "bailed_val")
    ctx.on("test/bail", lambda: "unreachable")

    bail_res = ctx.bail_sync("test/bail")
    assert bail_res == "bailed_val"


def test_disposer_effects():
    ctx = Context()
    cleared = []

    def cleanup():
        cleared.append("ok")

    ctx.effect(lambda: cleanup)
    assert cleared == []
    ctx.teardown()
    assert cleared == ["ok"]


def test_context_intercept():
    ctx = Context()
    child = ctx.intercept("tools", {"max_tools": 10})
    assert child._intercept_map.get("tools") == {"max_tools": 10}
