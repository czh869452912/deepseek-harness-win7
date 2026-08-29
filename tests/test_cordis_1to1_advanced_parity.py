"""
Comprehensive unit tests for 1:1 Cordis Core Architecture Parity
"""
import asyncio
import pytest
from typing import Any, Dict, List

from dsh.cordis.context import Context
from dsh.cordis.fiber import Fiber, FiberState
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service
from dsh.cordis.schema import Schema, z, ValidationError
from dsh.cordis.utils import Symbols, get_traceable, with_props, TracedProxy
from dsh.cordis.loader import Loader, Entry, EntryTree, EntryGroup, LocalRealm, GlobalRealm


class DummyService(Service):
    name = "dummy"
    def __init__(self, ctx: Context):
        super().__init__(ctx, name="dummy")
        self.call_count = 0

    def do_action(self) -> str:
        self.call_count += 1
        return f"action_done_{self.call_count}"


class UpstreamDep(Service):
    name = "upstream"
    def __init__(self, ctx: Context):
        super().__init__(ctx, name="upstream")


@pytest.mark.asyncio
async def test_fiber_generator_epoch_interruption():
    ctx = Context()
    yielded_items = []
    closed = False

    def gen_effect():
        nonlocal closed
        try:
            yield lambda: yielded_items.append("disposer_1")
            yield lambda: yielded_items.append("disposer_2")
            yield lambda: yielded_items.append("disposer_3")
        finally:
            closed = True

    class ConsumerPlugin(Plugin):
        inject = ["upstream"]
        def apply(self, c: Context):
            c.effect(gen_effect)

    dep = UpstreamDep(ctx)
    fiber = ctx.plugin(ConsumerPlugin)
    await fiber.await_settled()
    assert fiber.state == FiberState.ACTIVE

    await fiber.dispose()
    assert fiber.state == FiberState.DISPOSED
    assert "disposer_1" in yielded_items
    assert "disposer_2" in yielded_items
    assert "disposer_3" in yielded_items


@pytest.mark.asyncio
async def test_fiber_asyncgen_epoch_interruption():
    ctx = Context()
    yielded_items = []
    async_closed = False

    async def async_gen_effect():
        nonlocal async_closed
        try:
            await asyncio.sleep(0.01)
            yield lambda: yielded_items.append("async_disp_1")
            await asyncio.sleep(0.01)
            yield lambda: yielded_items.append("async_disp_2")
        finally:
            async_closed = True

    class AsyncPlugin(Plugin):
        inject = ["upstream"]
        def apply(self, c: Context):
            c.effect(async_gen_effect)

    dep = UpstreamDep(ctx)
    fiber = ctx.plugin(AsyncPlugin)
    await fiber.await_settled()
    assert fiber.state == FiberState.ACTIVE

    await fiber.dispose()
    assert fiber.state == FiberState.DISPOSED
    assert "async_disp_1" in yielded_items


def test_traced_proxy_symbols_original_and_shadow():
    root_ctx = Context()
    dummy = DummyService(root_ctx)

    child_ctx = root_ctx.extend()
    traced = get_traceable(child_ctx, dummy)

    assert getattr(traced, Symbols.original) is dummy
    assert getattr(traced, "cordis.original") is dummy
    assert traced.ctx is child_ctx
    assert traced.do_action() == "action_done_1"


def test_schemastery_to_json_refs_table():
    inner_schema = z.string().description("inner text")
    obj_schema = z.object({
        "name": inner_schema,
        "age": z.number().min(0).max(120),
    })

    json_refs = obj_schema.toJSON()
    assert isinstance(json_refs, dict)
    assert "uid" in json_refs
    assert "refs" in json_refs
    assert json_refs["uid"] == obj_schema.uid

    refs = json_refs["refs"]
    assert obj_schema.uid in refs
    assert inner_schema.uid in refs
    assert refs[obj_schema.uid]["type"] == "object"
    assert refs[inner_schema.uid]["type"] == "string"


def test_schemastery_i18n_advanced_placeholders():
    schema = z.object({
        "title": z.string(),
        "tags": z.array(z.string()),
    })

    localized = schema.i18n({
        "zh": {
            "$description": "用户配置",
            "title": "标题",
            "tags": {
                "$description": "标签列表",
                "$inner": "单项标签"
            }
        },
        "en": {
            "$description": "User Config",
            "title": "Title",
            "tags": {
                "$description": "Tag List",
                "$inner": "Tag item"
            }
        }
    })

    assert localized.meta["description"]["zh"] == "用户配置"
    assert localized.meta["description"]["en"] == "User Config"
    assert localized.dict["title"].meta["description"]["zh"] == "标题"
    assert localized.dict["title"].meta["description"]["en"] == "Title"
    assert localized.dict["tags"].meta["description"]["zh"] == "标签列表"
    assert localized.dict["tags"].inner.meta["description"]["zh"] == "单项标签"


def test_loader_realms_and_partial_dispose():
    ctx = Context()
    loader = Loader(ctx)

    local_r = LocalRealm(None)
    assert local_r.access("tools", create=True).startswith("tools#")

    global_r = GlobalRealm("custom_scope")
    assert global_r.access("fs", create=True) == "fs@custom_scope"
    assert global_r.size == 1
    global_r.delete("fs")
    assert global_r.size == 0
