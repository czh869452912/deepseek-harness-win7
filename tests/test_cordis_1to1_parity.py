"""
Unit tests verifying 1-to-1 Cordis architecture parity with official TypeScript reference.
"""

import pytest
import asyncio
from dsh.cordis.context import Context
from dsh.cordis.service import Service
from dsh.cordis.plugin import Plugin
from dsh.cordis.events import AggregateError, is_bailed
from dsh.cordis.fiber import FiberState
from dsh.cordis.loader import Loader, EntryNode


class DummyService(Service):
    provide_name = "dummy"

    def __init__(self, ctx, name=None):
        super().__init__(ctx, name=name)
        self.counter = 0

    def increment(self):
        self.counter += 1
        return self.counter


def test_service_base_auto_provide():
    ctx = Context()
    srv = DummyService(ctx)
    assert ctx.get("dummy") is srv
    assert srv.name == "dummy"
    assert srv.increment() == 1

    ctx.teardown()
    assert ctx.get("dummy") is None


def test_multi_fiber_same_plugin_class():
    ctx = Context()

    class CountPlugin(Plugin):
        name = "count_plugin"

        def apply(self, c):
            c.set_service("val", getattr(self, "config", {}).get("val", 0))

    fiber1 = ctx.registry.plugin(CountPlugin, config={"val": 10})
    assert fiber1 is not None
    assert fiber1.state == FiberState.ACTIVE

    fiber2 = ctx.registry.plugin(CountPlugin, config={"val": 20})
    assert fiber2 is not None
    assert fiber2 is not fiber1
    assert len(ctx.registry.get(CountPlugin).fibers) == 2


@pytest.mark.asyncio
async def test_waterfall_veto_semantics():
    ctx = Context()

    def middleware1(data, next_fn):
        return next_fn(data + " -> m1")

    def middleware_veto(data, next_fn):
        # Does NOT call next_fn: short-circuits/vetoes downstream
        return data + " -> veto"

    def middleware3(data, next_fn):
        return next_fn(data + " -> m3")

    ctx.on("pipeline", middleware1)
    ctx.on("pipeline", middleware_veto)
    ctx.on("pipeline", middleware3)

    res = await ctx.waterfall("pipeline", "start")
    assert res == "start -> m1 -> veto"


def test_is_bailed_exact_semantics():
    assert is_bailed(True) is True
    assert is_bailed("hello") is True
    assert is_bailed(0) is True
    assert is_bailed("") is True

    assert is_bailed(None) is False
    assert is_bailed(False) is False


@pytest.mark.asyncio
async def test_parallel_aggregate_error():
    ctx = Context()

    def bad_listener():
        raise ValueError("failed listener 1")

    def good_listener():
        return 42

    ctx.on("task", bad_listener)
    ctx.on("task", good_listener)

    with pytest.raises(AggregateError) as exc_info:
        await ctx.parallel("task")

    assert len(exc_info.value.errors) == 1


def test_isolate_and_intercept_inheritance():
    ctx = Context()
    ctx.set_service("db", "root_db")

    child = ctx.isolate("db")
    child.set_service("db", "isolated_db")

    assert ctx.get("db") == "root_db"
    assert child.get("db") == "isolated_db"

    intercepted = ctx.intercept("tools", {"timeout": 5000})
    assert intercepted._intercept_map.get("tools") == {"timeout": 5000}


def test_loader_service_and_entry_tree():
    ctx = Context()
    loader = Loader(ctx)

    assert ctx.get("loader") is loader
    assert loader.name == "loader"

    loader.load_from_dict([
        {"name": "test_pkg", "config": {"foo": "bar"}},
        {"name": "disabled_pkg", "disabled": True, "config": {}}
    ])

    assert len(loader.entries) == 2
    assert loader.entries[0].name == "test_pkg"
    assert loader.entries[1].disabled is True
