"""
Unit tests porting official TypeScript reference Cordis parity improvements:
1. Waterfall Koa-style next() continuation & pipeline veto (reference/packages/core/events)
2. Custom thisArg & Context.filter event dispatch isolation (reference/vendor/cordis/src/events.ts)
3. Service dynamic child context binding & _extend (reference/vendor/cordis/src/service.ts)
4. Dynamic plugin module cache eviction on entry removal (reference/vendor/loader)
5. Schemastery to_json_schema() Draft-07 output & intersect merge (reference/vendor/schemastery)
"""

import asyncio
import os
import sys
import tempfile
import pytest

from dsh.cordis.context import Context
from dsh.cordis.events import EventBus
from dsh.cordis.service import Service
from dsh.cordis.schema import Schema
from dsh.cordis.loader import Loader, Entry, resolve_plugin_class


# ==============================================================================
# 1. Waterfall Koa-style next() Continuation & Pipeline Veto
# ==============================================================================

@pytest.mark.asyncio
async def test_waterfall_next_continuation_and_pipeline():
    """Verify async waterfall passes next continuation and allows wrapping execution."""
    ctx = Context()
    order = []

    async def mw1(data, next_fn):
        order.append("mw1_start")
        res = await next_fn(data + " -> mw1")
        order.append("mw1_end")
        return res

    async def mw2(data, next_fn):
        order.append("mw2_start")
        await asyncio.sleep(0.01)
        res = await next_fn(data + " -> mw2")
        order.append("mw2_end")
        return res

    ctx.on("test/pipeline", mw1)
    ctx.on("test/pipeline", mw2)

    result = await ctx.waterfall("test/pipeline", "initial", lambda d: d + " -> final")
    assert result == "initial -> mw1 -> mw2 -> final"
    assert order == ["mw1_start", "mw2_start", "mw2_end", "mw1_end"]


def test_waterfall_sync_veto_without_calling_next():
    """Verify sync waterfall vetoes execution when next() is not invoked."""
    ctx = Context()
    called = []

    def vetoing_mw(data, next_fn):
        called.append("veto")
        return "blocked"

    def never_reached_mw(data, next_fn):
        called.append("never")
        return next_fn(data)

    ctx.on("test/veto", vetoing_mw)
    ctx.on("test/veto", never_reached_mw)

    res = ctx.waterfall_sync("test/veto", "start", lambda d: d + " -> default")
    assert res == "blocked"
    assert called == ["veto"]


# ==============================================================================
# 2. Custom thisArg & Context.filter Event Dispatch Isolation
# ==============================================================================

def test_custom_this_arg_and_event_filter():
    """Verify event dispatch checks filter on thisArg."""
    bus = EventBus()
    ctx1 = Context()
    ctx2 = Context()

    received = []
    bus.on("custom/event", lambda: received.append("ctx1"), ctx=ctx1)
    bus.on("custom/event", lambda: received.append("ctx2"), ctx=ctx2)

    class CustomScopeCarrier:
        def filter(self, target_ctx):
            return target_ctx is ctx1

    carrier = CustomScopeCarrier()
    bus.emit("custom/event", caller_ctx=carrier)
    assert received == ["ctx1"]


# ==============================================================================
# 3. Service Dynamic Child Context Binding & _extend
# ==============================================================================

def test_service_dynamic_child_context_binding():
    """Verify service accesses through child context dynamically expose child ctx."""
    root = Context()

    class DatabaseService(Service):
        name = "db"

        def get_current_ctx(self):
            return self.ctx

    db = DatabaseService(root, "db")

    child = root.extend()
    child_db = child.get("db")

    # Accessing db through child context reflects child context
    assert child_db.ctx is child
    assert root.get("db").ctx is root


# ==============================================================================
# 4. Dynamic Plugin Module Cache Eviction
# ==============================================================================

def test_loader_module_cache_eviction_on_dispose():
    """Verify dynamic file plugin is removed from sys.modules when entry is disposed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        plugin_file = os.path.join(tmpdir, "dynamic_plugin.py")
        with open(plugin_file, "w", encoding="utf-8") as f:
            f.write(
                "from dsh.cordis.plugin import Plugin\n"
                "class TempPlugin(Plugin):\n"
                "    name = 'temp-plugin'\n"
                "    def apply(self, ctx):\n"
                "        ctx.set_service('temp_svc', 'active')\n"
            )

        root = Context()
        loader = Loader(root)

        entry_id = loader.create({
            "id": "temp_entry",
            "name": f"{plugin_file}:TempPlugin",
        })

        entry = loader.resolve(entry_id)
        assert entry._loaded_module_name is not None
        assert entry._loaded_module_name in sys.modules
        mod_name = entry._loaded_module_name

        # Dispose entry
        loader.remove(entry_id)
        assert mod_name not in sys.modules


# ==============================================================================
# 5. Schemastery to_json_schema() Draft-07 Output & Intersect
# ==============================================================================

def test_schemastery_to_json_schema_output():
    """Verify to_json_schema() produces valid standard JSON Schema draft-07."""
    schema = Schema.object({
        "name": Schema.string().description("User name").required(),
        "age": Schema.number().min(0).max(120).default(18),
        "tags": Schema.array(Schema.string()).description("List of tags"),
        "role": Schema.union([Schema.const_("admin"), Schema.const_("user")]),
    }).description("User Profile Schema")

    json_schema = schema.to_json_schema()
    assert json_schema["type"] == "object"
    assert json_schema["description"] == "User Profile Schema"
    assert "name" in json_schema["properties"]
    assert json_schema["properties"]["name"]["type"] == "string"
    assert json_schema["properties"]["name"]["description"] == "User name"
    assert json_schema["required"] == ["name"]
    assert json_schema["properties"]["age"]["type"] == "number"
    assert json_schema["properties"]["age"]["minimum"] == 0
    assert json_schema["properties"]["age"]["maximum"] == 120
    assert json_schema["properties"]["age"]["default"] == 18
    assert json_schema["properties"]["tags"]["type"] == "array"
    assert json_schema["properties"]["tags"]["items"]["type"] == "string"
    assert "anyOf" in json_schema["properties"]["role"]


def test_schemastery_intersect_deep_merge():
    """Verify intersect merges dictionaries and validates both components."""
    schema1 = Schema.object({"a": Schema.string().required()})
    schema2 = Schema.object({"b": Schema.number().required()})
    combined = Schema.intersect([schema1, schema2])

    res = combined({"a": "hello", "b": 42})
    assert res == {"a": "hello", "b": 42}

    with pytest.raises(Exception):
        combined({"a": "hello"})  # missing b
