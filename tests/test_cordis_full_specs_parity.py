"""
Full-Spectrum 1:1 Parity Tests ported from Cordis / Cosmokit / Schemastery Reference Specs
Testing:
1. Event dispatch modes: waterfall, bail, serial, parallel (with AggregateError), once self-disposal.
2. Context accessors, mixins, provide, get, and set.
3. Cosmokit utilities: deep_equal, clone, pick, omit, value_map, filter_keys.
4. Schema validation with plugin Config schemas.
"""

import asyncio
import pytest
from typing import Any, Dict, List

from dsh.cordis.context import Context
from dsh.cordis.events import AggregateError
from dsh.cordis.fiber import Fiber, FiberState
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service
from dsh.cordis.schema import Schema, z, ValidationError
from dsh.cordis.utils import (
    deep_equal, clone, pick, omit, value_map, filter_keys,
    capitalize, uncapitalize, camelCase, paramCase, snakeCase, template,
    Symbols, get_traceable, with_props
)


# --- 1. Event Dispatch Modes ---

def test_events_waterfall_middleware_pipeline():
    """Test ctx.waterfall executing listeners in onion middleware style matching TS EventsService.waterfall."""
    ctx = Context()
    trail = []

    def middleware_1(val: str, next_fn=None):
        trail.append("m1_pre")
        res = next_fn(f"{val}+m1") if next_fn else val
        trail.append("m1_post")
        return res

    def middleware_2(val: str, next_fn=None):
        trail.append("m2_pre")
        res = next_fn(f"{val}+m2") if next_fn else val
        trail.append("m2_post")
        return res

    ctx.on("test/waterfall", middleware_1)
    ctx.on("test/waterfall", middleware_2)

    final_result = ctx.waterfall_sync("test/waterfall", "init", lambda v: f"{v}+final")
    assert final_result == "init+m1+m2+final"
    assert trail == ["m1_pre", "m2_pre", "m2_post", "m1_post"]


def test_events_bail_sync_short_circuit():
    """Test ctx.bail_sync stopping at first non-null/non-false value matching TS EventsService.bail."""
    ctx = Context()
    called = []

    ctx.on("test/bail", lambda: (called.append(1), None)[1])
    ctx.on("test/bail", lambda: (called.append(2), "hit_bail")[1])
    ctx.on("test/bail", lambda: (called.append(3), "should_not_reach")[1])

    res = ctx.bail_sync("test/bail")
    assert res == "hit_bail"
    assert called == [1, 2]


@pytest.mark.asyncio
async def test_events_serial_async_short_circuit():
    """Test ctx.serial awaiting in order until first bail matching TS EventsService.serial."""
    ctx = Context()
    called = []

    async def h1():
        called.append("h1")
        await asyncio.sleep(0.01)
        return False

    async def h2():
        called.append("h2")
        await asyncio.sleep(0.01)
        return {"status": "ok"}

    async def h3():
        called.append("h3")
        return {"status": "never"}

    ctx.on("test/serial", h1)
    ctx.on("test/serial", h2)
    ctx.on("test/serial", h3)

    res = await ctx.serial("test/serial")
    assert res == {"status": "ok"}
    assert called == ["h1", "h2"]


@pytest.mark.asyncio
async def test_events_parallel_aggregate_error():
    """Test ctx.parallel running concurrently and aggregating failures matching TS EventsService.parallel."""
    ctx = Context()

    async def ok_listener():
        await asyncio.sleep(0.01)

    async def fail_listener_1():
        await asyncio.sleep(0.01)
        raise ValueError("Error 1")

    async def fail_listener_2():
        await asyncio.sleep(0.01)
        raise TypeError("Error 2")

    ctx.on("test/parallel", ok_listener)
    ctx.on("test/parallel", fail_listener_1)
    ctx.on("test/parallel", fail_listener_2)

    with pytest.raises(AggregateError) as exc_info:
        await ctx.parallel("test/parallel")

    assert len(exc_info.value.errors) == 2


def test_events_once_self_disposal():
    """Test ctx.once firing exactly once and automatically disposing."""
    ctx = Context()
    count = 0

    def once_handler():
        nonlocal count
        count += 1

    ctx.once("test/once", once_handler)
    ctx.emit("test/once")
    ctx.emit("test/once")
    ctx.emit("test/once")

    assert count == 1


# --- 2. Reflect Accessors & Mixins ---

def test_reflect_accessors_and_provide():
    """Test ctx.accessor, ctx.provide, ctx.get and ctx.set matching TS reflect.ts."""
    ctx = Context()

    # Accessor
    stored_state = {"val": "initial"}
    ctx.accessor("dynamic_val", {
        "get": lambda receiver, err: stored_state["val"],
        "set": lambda receiver, val, err: stored_state.update({"val": val}),
    })

    assert ctx.dynamic_val == "initial"
    ctx.dynamic_val = "updated"
    assert ctx.dynamic_val == "updated"

    # Provide service
    class MockStore:
        def __init__(self):
            self.data = {}

    store = MockStore()
    disposer = ctx.provide("mock_store", store)
    assert ctx.get("mock_store") is store

    # Overwrite with ctx.set
    new_store = MockStore()
    ctx.set("mock_store", new_store)
    assert ctx.get("mock_store") is new_store

    # Dispose
    disposer()
    assert ctx.get("mock_store") is None


# --- 3. Cosmokit Utility Invariants ---

def test_cosmokit_utilities_deep_equal_and_clone():
    """Test deep_equal, clone, pick, omit, value_map matching Cosmokit."""
    obj1 = {"a": [1, 2, {"x": "y"}], "b": 42}
    obj2 = {"a": [1, 2, {"x": "y"}], "b": 42}
    obj3 = {"a": [1, 2, {"x": "z"}], "b": 42}

    assert deep_equal(obj1, obj2) is True
    assert deep_equal(obj1, obj3) is False

    cloned = clone(obj1)
    assert deep_equal(cloned, obj1) is True
    cloned["a"][2]["x"] = "modified"
    assert obj1["a"][2]["x"] == "y"

    # pick and omit
    d = {"name": "test", "age": 20, "secret": "xyz"}
    assert pick(d, ["name", "age"]) == {"name": "test", "age": 20}
    assert omit(d, ["secret"]) == {"name": "test", "age": 20}

    # value_map and filter_keys
    mapped = value_map({"a": 1, "b": 2}, lambda x, k: x * 10)
    assert mapped == {"a": 10, "b": 20}

    filtered = filter_keys({"$desc": "info", "name": "val"}, lambda k: not k.startswith("$"))
    assert filtered == {"name": "val"}

    # string transforms
    assert capitalize("helloWorld") == "HelloWorld"
    assert uncapitalize("HelloWorld") == "helloWorld"
    assert camelCase("foo-bar_baz") == "fooBarBaz"
    assert paramCase("fooBarBaz") == "foo-bar-baz"
    assert snakeCase("fooBarBaz") == "foo_bar_baz"
    assert template("Hello, {name}! Today is {day}.", {"name": "Antigravity", "day": "Sunday"}) == "Hello, Antigravity! Today is Sunday."


# --- 4. Plugin Config Schema Invariants ---

def test_plugin_config_schema_validation():
    """Test plugins declaring Config schema with automatic validation on registration."""
    ctx = Context()

    class ConfiguredPlugin(Plugin):
        Config = z.object({
            "host": z.string().default("127.0.0.1"),
            "port": z.number().min(1024).max(65535).default(8080),
        })

        def __init__(self, config=None):
            super().__init__(config)
            self.applied = False

        def apply(self, c: Context):
            self.applied = True

    # Valid config with defaults
    f1 = ctx.plugin(ConfiguredPlugin, {"port": 9000})
    assert f1.state == FiberState.ACTIVE
    assert f1.plugin.config == {"host": "127.0.0.1", "port": 9000}

    # Invalid config sets fiber to FAILED state and attaches ValidationError
    f2 = ctx.plugin(ConfiguredPlugin, {"port": 80})  # 80 is below min(1024)
    assert f2.state == FiberState.FAILED
    assert isinstance(f2.error, ValidationError)
    assert f2.plugin.applied is False
