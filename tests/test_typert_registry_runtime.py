from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.typert.registry import TypertRegistry
from dsh.typert.protocol import TypertLookupProvider


def descriptor(method="read"):
    return {"id": "test#" + method, "service": "sessions", "namespace": "sessions", "method": method,
            "parameters": [], "result": {"mode": "src-json"}, "invocation": {"kind": "direct"}}


def contribution(package="test", rows=None, schemas=None):
    return {"package": package, "face": "host", "model": {"services": [], "events": [], "objects": []},
            "schemas": schemas or [], "invocations": [descriptor()] if rows is None else rows}


class Owner(Plugin):
    inject = ["typert"]
    def apply(self, ctx):
        self.bound = ctx.get("typert")


@pytest.mark.asyncio
async def test_atomic_package_registration_and_fiber_owned_descriptor_history():
    ctx = Context()
    await ctx.plugin(TypertRegistry)
    owner = await ctx.plugin(Owner)
    registry = owner.plugin.bound
    observed = []
    ctx.get("typert").local.subscribe(lambda event: observed.append((event, len(ctx.get("typert").local.list()))))
    try:
        registry.register(contribution(rows=[descriptor("read"), descriptor("write")]))
        assert observed == [({"kind": "local", "key": "sessions/read"}, 2), ({"kind": "local", "key": "sessions/write"}, 2)]
        with pytest.raises(ValueError, match="endpoint already registered"):
            registry.register(contribution("other", rows=[descriptor("new"), descriptor("read")]))
        assert registry.getPackage("other") is None and registry.local.get("sessions/new") is None
        await owner.dispose()
        assert ctx.get("typert").local.list() == []
        assert ctx.get("typert").local.hasSeen("sessions/read")
        assert observed[-1] == ({"kind": "local", "key": "sessions/write"}, 0)
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_lookup_declaration_survives_unload_and_resolver_is_caller_owned():
    ctx = Context()
    await ctx.plugin(TypertRegistry)
    owner = await ctx.plugin(Owner)
    registry = ctx.get("typert")
    provider = TypertLookupProvider("session", "sessionId", "host#Session", "wire#SessionId", lambda key: "default:" + key)
    try:
        undo = registry.lookups.register("session", provider)
        owner.plugin.bound.lookups.configure("session", lambda key: "selected:" + key)
        assert await registry.lookups.get("session").resolve("a") == "selected:a"
        await owner.dispose()
        assert registry.lookups.get("session").resolve("a") == "default:a"
        undo()
        assert registry.lookups.get("session") is None
        assert registry.lookups.definitions()[0].wire == "sessionId"
        changed = TypertLookupProvider("session", "otherId", "host#Session", "wire#SessionId", lambda key: key)
        with pytest.raises(ValueError, match="changed its wire declaration"):
            registry.lookups.register("session", changed)
        registry.lookups.register("session", provider)
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_remote_and_context_ownership_ambiguity_and_observer_isolation():
    ctx = Context()
    await ctx.plugin(TypertRegistry)
    owner = await ctx.plugin(Owner)
    registry = ctx.get("typert")
    changes = []
    def failing(_):
        raise ValueError("observer failed")
    registry.remotes.subscribe(failing)
    registry.remotes.subscribe(changes.append)
    adapter = SimpleNamespace(wire="sessionId", wireTypeSymbol="wire#SessionId", identity=lambda context: "id", resolve=lambda key: ctx)
    try:
        owner.plugin.bound.remotes.register({"package": "client", "descriptors": [descriptor()]})
        assert changes == [{"kind": "remote", "key": "sessions/read"}]
        registry.contexts.registerHost("session", adapter)
        owner.plugin.bound.contexts.registerHost("other", adapter)
        with pytest.raises(ValueError, match="both session and other"):
            registry.contexts.identifyHost(ctx)
        await owner.dispose()
        assert registry.remotes.list() == []
        assert registry.contexts.identifyHost(ctx) == {"kind": "session", "identity": "id"}
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_schema_projection_is_fresh_and_failed_batch_publishes_nothing():
    ctx = Context()
    await ctx.plugin(TypertRegistry)
    registry = ctx.get("typert")
    class Schema:
        def to_json_schema(self):
            return {"type": "object", "properties": {"x": {"type": "string"}}}
    try:
        registry.register(contribution(schemas=[{"name": "Options", "schema": Schema()}]))
        first = registry.toJSONSchema("test#Options")
        first["properties"].clear()
        assert "x" in registry.toJSONSchema("test#Options")["properties"]
        with pytest.raises(ValueError, match="no schema named"):
            registry.resolve("test#Absent")
        invalid = descriptor("broken")
        invalid["cancellation"] = {"parameter": "wrong"}
        with pytest.raises(ValueError, match="must be signal"):
            registry.register(contribution("bad", rows=[invalid], schemas=[{"name": "Options", "schema": Schema()}]))
        assert registry.get("bad#Options") is None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.parametrize("mutation", [
    lambda row: row.update(method="../escape"),
    lambda row: row.update(scope={"context": "session", "wire": "sessionId"}),
    lambda row: row.update(parameters=[{"name": "session", "wire": "sessionId", "source": "lookup", "lookup": "session", "acceptsUndefined": False, "codec": {"mode": "src-json"}}]),
])
@pytest.mark.asyncio
async def test_invalid_descriptor_rejected_before_remote_publication(mutation):
    ctx = Context()
    await ctx.plugin(TypertRegistry)
    try:
        row = descriptor()
        mutation(row)
        with pytest.raises(ValueError):
            ctx.get("typert").remotes.register({"package": "test", "descriptors": [row]})
        assert ctx.get("typert").remotes.list() == []
    finally:
        await ctx.fiber.dispose()
