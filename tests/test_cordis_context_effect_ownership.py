import asyncio

import pytest

from dsh.cordis.context import Context
from dsh.cordis.fiber import CordisError, FiberState
from dsh.cordis.loader import Loader
from dsh.cordis.plugin import Plugin
from dsh.cordis.reflect import Impl


@pytest.mark.asyncio
async def test_on_and_once_remain_registered_until_owner_fiber_unloads():
    ctx = Context()
    calls = []

    def plugin(plugin_ctx, _config):
        plugin_ctx.on("owned/on", lambda: calls.append("on"))
        plugin_ctx.once("owned/once", lambda: calls.append("once"))

    fiber = ctx.registry.plugin(plugin, {})
    await fiber

    fiber.ctx.emit("owned/on")
    fiber.ctx.emit("owned/once")
    fiber.ctx.emit("owned/once")
    assert calls == ["on", "once"]

    await fiber.dispose()
    fiber.ctx.emit("owned/on")
    fiber.ctx.emit("owned/once")
    assert calls == ["on", "once"]


@pytest.mark.asyncio
async def test_plugin_teardown_runs_once_during_unload_not_activation():
    ctx = Context()
    calls = []

    class OwnedPlugin(Plugin):
        id = "owned-plugin"

        def apply(self, plugin_ctx):
            calls.append("apply")

        def teardown(self):
            calls.append("teardown")

    fiber = ctx.registry.plugin(OwnedPlugin(), {})
    await fiber
    assert calls == ["apply"]

    await asyncio.gather(fiber.dispose(), fiber.dispose())
    assert calls == ["apply", "teardown"]


@pytest.mark.asyncio
async def test_parent_unload_awaits_child_and_removes_runtime_after_cleanup():
    ctx = Context()
    cleanup_started = asyncio.Event()
    allow_cleanup = asyncio.Event()
    calls = []
    child_holder = {}

    def child_plugin(_plugin_ctx, _config):
        async def cleanup():
            calls.append("child-cleanup-start")
            cleanup_started.set()
            await allow_cleanup.wait()
            calls.append("child-cleanup-end")

        return cleanup

    def parent_plugin(plugin_ctx, _config):
        plugin_ctx.plugin(child_plugin, {})
        child_holder["fiber"] = plugin_ctx.registry.get(child_plugin).fibers[0]

    parent = ctx.registry.plugin(parent_plugin, {})
    await parent
    child = child_holder["fiber"]
    await child

    unloading = asyncio.create_task(parent.dispose())
    await cleanup_started.wait()
    assert not unloading.done()
    assert child in ctx.registry.get(child_plugin).fibers

    allow_cleanup.set()
    await unloading
    assert calls == ["child-cleanup-start", "child-cleanup-end"]
    assert child.state == FiberState.DISPOSED
    assert ctx.registry.get(child_plugin) is None


@pytest.mark.asyncio
async def test_provide_and_accessor_keep_setup_result_as_owned_disposer():
    ctx = Context()

    def plugin(plugin_ctx, _config):
        plugin_ctx.provide("owned-service", 42)
        plugin_ctx.accessor("owned-accessor", {"get": lambda _ctx, _error: "value"})

    fiber = ctx.registry.plugin(plugin, {})
    await fiber
    assert fiber.ctx.get("owned-service") == 42
    assert fiber.ctx.get("owned-accessor") == "value"

    await fiber.dispose()
    assert ctx.get("owned-service", None, strict=False) is None
    assert "owned-accessor" not in ctx.reflect.props


@pytest.mark.asyncio
async def test_effect_uses_the_fiber_on_the_calling_context():
    ctx = Context()
    calls = []

    def plugin(plugin_ctx, _config):
        derived = plugin_ctx.extend()
        derived.effect(lambda: lambda: calls.append("cleanup"), label="derived")

    fiber = ctx.registry.plugin(plugin, {})
    await fiber
    assert any(effect["label"] == "derived" for effect in fiber.get_effects())
    assert not any(effect["label"] == "derived" for effect in ctx.fiber.get_effects())

    await fiber.dispose()
    assert calls == ["cleanup"]


@pytest.mark.asyncio
async def test_manual_listener_disposer_removes_listener_and_effect_metadata():
    ctx = Context()
    owned = {}
    calls = []

    def plugin(plugin_ctx, _config):
        owned["dispose"] = plugin_ctx.on("owned/manual", lambda: calls.append("call"))

    fiber = ctx.registry.plugin(plugin, {})
    await fiber
    assert any(effect["label"] == "ctx.on(owned/manual)" for effect in fiber.get_effects())

    await owned["dispose"]()
    assert not any(effect["label"] == "ctx.on(owned/manual)" for effect in fiber.get_effects())
    fiber.ctx.emit("owned/manual")
    assert calls == []


@pytest.mark.asyncio
async def test_once_removes_raw_listener_before_reentrant_handler_and_drops_metadata():
    ctx = Context()
    calls = []

    def plugin(plugin_ctx, _config):
        def handler():
            calls.append("once")
            plugin_ctx.emit("owned/reentrant-once")

        plugin_ctx.once("owned/reentrant-once", handler)

    fiber = ctx.registry.plugin(plugin, {})
    await fiber
    fiber.ctx.emit("owned/reentrant-once")
    await asyncio.sleep(0)

    assert calls == ["once"]
    assert not any(effect["label"] == "ctx.once(owned/reentrant-once)" for effect in fiber.get_effects())


@pytest.mark.asyncio
async def test_inactive_context_effect_and_listeners_fail_without_registration_leaks():
    ctx = Context()
    fiber = ctx.registry.plugin(lambda _ctx, _config: None, {})
    await fiber
    await fiber.dispose()
    hook_count = sum(len(hooks) for hooks in ctx.events._hooks.values())

    with pytest.raises(CordisError):
        fiber.ctx.effect(lambda: None)
    with pytest.raises(CordisError):
        fiber.ctx.on("inactive/on", lambda: None)
    with pytest.raises(CordisError):
        fiber.ctx.once("inactive/once", lambda: None)

    assert sum(len(hooks) for hooks in ctx.events._hooks.values()) == hook_count


@pytest.mark.asyncio
async def test_duplicate_provider_in_same_isolation_scope_raises():
    ctx = Context()
    label = object()
    first = ctx.isolate("shared", label=label)
    second = ctx.isolate("shared", label=label)

    first.provide("shared", "first")
    with pytest.raises(RuntimeError, match="has been registered"):
        second.provide("shared", "second")


def test_duplicate_set_service_does_not_overwrite_existing_impl():
    ctx = Context()
    ctx.set_service("stable", "first")

    with pytest.raises(RuntimeError, match="has been registered"):
        ctx.set_service("stable", "second")

    assert ctx.get("stable") == "first"


@pytest.mark.asyncio
async def test_stale_provider_disposer_does_not_delete_replacement_impl():
    ctx = Context()
    isolated = ctx.isolate("service")
    dispose = isolated.provide("service", "old")
    assert isolated.reflect.set(isolated, "service", "old-assigned") is True
    isolated.service = "old-mutated"
    key = isolated._isolated_keys["service"]
    replacement = Impl("service", isolated.fiber, "new")
    ctx.reflect.store[key] = replacement
    isolated._services["service"] = "new"

    await dispose()

    assert ctx.reflect.store[key] is replacement
    assert isolated._services["service"] == "new"
    assert isolated.get("service") == "new"
    assert isolated.service == "new"


@pytest.mark.asyncio
async def test_loader_mounts_plugin_under_target_derived_context():
    ctx = Context()
    loader = Loader(ctx)
    target = ctx.isolate("loader-owned")

    def loaded(_plugin_ctx, _config):
        return None

    loader.register_plugin_class("loaded", loaded)
    loader.load_from_dict([{"id": "loaded", "name": "loaded"}], target_ctx=target)
    entry = loader.entries[-1]
    fiber = entry.fiber
    await fiber

    assert fiber.parent is entry.ctx
    assert entry.ctx._parent is target
    assert fiber.ctx.fiber is fiber


def test_registry_plugin_mounts_synchronously_without_a_running_loop():
    ctx = Context()
    calls = []

    fiber = ctx.registry.plugin(lambda _ctx, _config: calls.append("apply"), {})

    assert calls == ["apply"]
    assert fiber.state == FiberState.ACTIVE
