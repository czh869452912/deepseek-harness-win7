import asyncio

import pytest

from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.cordis.registry import Inject
from dsh.cordis.service import Service


@pytest.mark.asyncio
async def test_inject_map_is_preserved_and_becomes_service_intercept():
    ctx = Context()
    ctx.provide("api", object())
    seen = []

    fiber = ctx.registry.inject(
        {"api": {"timeout": 10}},
        lambda child: seen.append(child._intercept_map["api"]),
    )
    await fiber

    assert fiber.inject == {"api": {"timeout": 10}}
    assert seen == [{"timeout": 10}]
    assert Inject.resolve(["api", "cache"]) == {"api": None, "cache": None}


@pytest.mark.asyncio
async def test_service_check_runs_for_consumer_context_and_controls_activation():
    ctx = Context()

    class CheckedService(Service):
        provide_name = "checked"

        def __init__(self, service_ctx):
            self.allowed_fiber = None
            setattr(self, Service.check, self.available)
            super().__init__(service_ctx)

        def available(self):
            return self.ctx.fiber is self.allowed_fiber

    service = CheckedService(ctx)
    calls = []

    class Consumer:
        inject = ["checked"]

        def apply(self, child):
            calls.append(child.fiber.uid)

    fiber = ctx.registry.plugin(Consumer())
    await asyncio.sleep(0)
    assert fiber.state == FiberState.PENDING

    service.allowed_fiber = fiber
    ctx.reflect.notify(["checked"])
    await fiber
    assert calls == [fiber.uid]


@pytest.mark.asyncio
async def test_plain_provider_check_keeps_zero_argument_contract():
    ctx = Context()
    enabled = [False]
    ctx.provide("feature", object(), check=lambda: enabled[0])
    calls = []
    fiber = ctx.registry.inject(["feature"], lambda _child: calls.append("load"))
    assert fiber.state == FiberState.PENDING

    enabled[0] = True
    ctx.reflect.notify(["feature"])
    await fiber
    assert calls == ["load"]


@pytest.mark.asyncio
async def test_provider_replacement_unloads_and_reloads_consumer_with_uid_epoch():
    ctx = Context()
    events = []

    class Consumer:
        inject = ["database"]

        def apply(self, child):
            events.append(("load", child.database))
            return lambda: events.append(("unload", child.database))

    consumer = ctx.registry.plugin(Consumer())
    assert consumer.state == FiberState.PENDING

    class Provider:
        def __init__(self, value):
            self.value = value

        def apply(self, child):
            child.provide("database", self.value)

    first = ctx.registry.plugin(Provider("first"))
    await first
    await consumer
    first_epoch = consumer.epoch
    assert first_epoch == ":%s" % first.uid

    await first.dispose()
    await consumer
    assert consumer.state == FiberState.PENDING

    second = ctx.registry.plugin(Provider("second"))
    await second
    await consumer
    assert consumer.epoch == ":%s" % second.uid
    assert consumer.epoch != first_epoch
    assert events == [
        ("load", "first"),
        ("unload", "first"),
        ("load", "second"),
    ]


def test_nested_dependency_notifications_are_queued_without_a_running_loop():
    ctx = Context()
    calls = []

    consumer = ctx.registry.inject(
        ["second"],
        lambda child: calls.append(child.second),
    )
    bridge = ctx.registry.inject(
        ["first"],
        lambda child: child.provide("second", "ready"),
    )
    assert consumer.state == FiberState.PENDING
    assert bridge.state == FiberState.PENDING

    ctx.provide("first", object())

    assert bridge.state == FiberState.ACTIVE
    assert consumer.state == FiberState.ACTIVE
    assert calls == ["ready"]


@pytest.mark.asyncio
async def test_isolated_consumer_tracks_same_scope_provider_remove_and_replace():
    ctx = Context()
    isolated = ctx.isolate("database")
    events = []

    class Consumer:
        inject = ["database"]

        def apply(self, child):
            events.append(("load", child.database))
            return lambda: events.append(("unload", child.database))

    consumer = isolated.registry.plugin(Consumer(), parent_ctx=isolated)
    assert consumer.state == FiberState.PENDING

    class Provider:
        def __init__(self, value):
            self.value = value

        def apply(self, child):
            child.provide("database", self.value)

    first = isolated.registry.plugin(Provider("isolated-first"), parent_ctx=isolated)
    await first
    await consumer
    first_epoch = ":%s" % first.uid
    assert consumer.epoch == first_epoch

    await first.dispose()
    await consumer
    assert consumer.state == FiberState.PENDING

    second = isolated.registry.plugin(Provider("isolated-second"), parent_ctx=isolated)
    await second
    await consumer
    assert consumer.epoch == ":%s" % second.uid
    assert consumer.epoch != first_epoch
    assert events == [
        ("load", "isolated-first"),
        ("unload", "isolated-first"),
        ("load", "isolated-second"),
    ]


def test_context_has_uses_same_isolation_key_as_get_and_attribute_access():
    ctx = Context()
    ctx.provide("database", "root")
    isolated = ctx.isolate("database")

    assert isolated.has("database") is False
    assert isolated.get("database") is None
    with pytest.raises(AttributeError):
        _ = isolated.database

    isolated.provide("database", "isolated")
    assert isolated.has("database") is True
    assert isolated.get("database") == "isolated"
    assert isolated.database == "isolated"
    assert ctx.has("database") is True
    assert ctx.get("database") == "root"


def test_internal_service_notifications_are_filtered_by_isolation_key():
    ctx = Context()
    isolated = ctx.isolate("database")
    root_seen = []
    isolated_seen = []

    ctx.on("internal/service", lambda name, value: root_seen.append((name, value)))
    isolated.on(
        "internal/service",
        lambda name, value: isolated_seen.append((name, value)),
    )

    ctx.provide("database", "root")
    assert root_seen == [("database", "root")]
    assert isolated_seen == []

    isolated.provide("database", "isolated")
    assert isolated_seen == [("database", "isolated")]
    assert root_seen == [("database", "root")]


def test_service_config_merge_receives_base_ancestors_and_head_in_order():
    ctx = Context()
    outer = ctx.intercept("configurable", {"outer": 1})
    inner = outer.intercept("configurable", {"inner": 2})
    calls = []

    class ConfigSchema:
        @staticmethod
        def merge(*configs):
            calls.append(configs)
            return {"merged": list(configs)}

    class Configurable(Service):
        provide_name = "configurable"
        Config = ConfigSchema

    service = Configurable(inner)
    base = {"base": 0}
    head = {"head": 3}

    assert service.resolve_intercept_config(base, head) == {
        "merged": [base, {"outer": 1}, {"inner": 2}, head]
    }
    assert calls == [(base, {"outer": 1}, {"inner": 2}, head)]


def test_service_config_merge_preserves_explicit_empty_base_and_head():
    ctx = Context()
    intercepted = ctx.intercept("configurable", {"middle": 1})
    calls = []

    class ConfigSchema:
        @staticmethod
        def merge(*configs):
            calls.append(configs)
            return list(configs)

    class Configurable(Service):
        provide_name = "configurable"
        Config = ConfigSchema

    service = Configurable(intercepted)
    base = {}
    head = {}

    assert service.resolve_intercept_config(base, head) == [
        base,
        {"middle": 1},
        head,
    ]
    assert calls == [(base, {"middle": 1}, head)]


def test_duplicate_provide_and_cross_fiber_set_are_rejected():
    ctx = Context()
    ctx.provide("value", 1)
    with pytest.raises(RuntimeError, match="has been registered"):
        ctx.provide("value", 2)

    class Sibling:
        def apply(self, child):
            child.reflect.set(child, "value", 3)

    with pytest.raises(RuntimeError, match="multiple fibers"):
        ctx.registry.plugin(Sibling())


@pytest.mark.asyncio
async def test_provider_teardown_removes_attribute_created_by_reflect_set():
    ctx = Context()

    class Provider:
        def apply(self, child):
            child.provide("mutable", "before")
            child.reflect.set(child, "mutable", "after")

    fiber = ctx.registry.plugin(Provider())
    await fiber
    provider_ctx = fiber.ctx
    assert provider_ctx.mutable == "after"

    await fiber.dispose()

    assert provider_ctx.has("mutable") is False
    assert provider_ctx.get("mutable") is None
    with pytest.raises(RuntimeError, match="without inject"):
        _ = provider_ctx.mutable


@pytest.mark.asyncio
async def test_loading_provider_local_cache_does_not_bypass_strict_lookup():
    ctx = Context()
    observed = []

    class Provider:
        def apply(self, child):
            child.provide("warming", "not-ready")
            observed.append((
                child.get("warming"),
                child.has("warming"),
                ctx.get("warming"),
                ctx.has("warming"),
            ))

    fiber = ctx.registry.plugin(Provider())
    await fiber

    assert observed == [(None, False, None, False)]
    assert fiber.ctx.get("warming") == "not-ready"
    assert fiber.ctx.has("warming") is True


@pytest.mark.asyncio
async def test_traceable_service_method_binds_effect_to_calling_fiber():
    ctx = Context()
    cleanups = []

    class Hooks(Service):
        provide_name = "hooks"

        def install(self):
            owner = self.ctx.fiber.uid
            self.ctx.effect(lambda: lambda: cleanups.append(owner), "hook.install")
            return owner

    provider = ctx.registry.plugin(lambda child, _config: Hooks(child))
    await provider
    seen = []

    class Consumer:
        inject = ["hooks"]

        def apply(self, child):
            seen.append(child.hooks.install())

    consumer = ctx.registry.plugin(Consumer())
    await consumer
    assert seen == [consumer.uid]

    consumer_uid = consumer.uid
    await consumer.dispose()
    assert cleanups == [consumer_uid]
    assert provider.state == FiberState.ACTIVE


@pytest.mark.asyncio
async def test_callable_service_uses_calling_context_shadow():
    ctx = Context()

    class CallableService(Service):
        provide_name = "callable"

        def __init__(self, service_ctx):
            setattr(self, Service.invoke, self.invoke_body)
            super().__init__(service_ctx)

        def invoke_body(self):
            return self.ctx.fiber.uid

    provider = ctx.registry.plugin(lambda child, _config: CallableService(child))
    await provider
    seen = []
    consumer = ctx.registry.inject(["callable"], lambda child: seen.append(child.callable()))
    await consumer
    assert seen == [consumer.uid]


@pytest.mark.asyncio
async def test_context_property_access_requires_inject_but_get_is_unrestricted():
    ctx = Context()
    provider = ctx.registry.plugin(lambda child: child.provide("secret", 42))
    await provider
    results = []

    def undeclared(child):
        results.append(child.get("secret"))
        with pytest.raises(RuntimeError, match="without inject"):
            _ = child.secret

    plain = ctx.registry.plugin(undeclared)
    await plain

    declared = ctx.registry.inject(["secret"], lambda child: results.append(child.secret))
    await declared
    assert results == [42, 42]


def test_registry_exposes_map_surface():
    ctx = Context()

    def plugin(_ctx):
        return None

    ctx.registry.plugin(plugin)
    runtime = ctx.registry.get(plugin)

    assert list(ctx.registry.keys()) == [plugin]
    assert list(ctx.registry.values()) == [runtime]
    assert list(ctx.registry.entries()) == [(plugin, runtime)]
    visited = []
    ctx.registry.for_each(lambda value, key: visited.append((key, value)))
    assert visited == [(plugin, runtime)]
