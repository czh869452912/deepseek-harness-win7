"""Integration coverage for Cordis' internal waterfall producers."""

from typing import Any, Dict, List

from dsh.cordis.context import Context
from dsh.cordis.loader import Loader
from dsh.cordis.plugin import Plugin
import pytest


def test_internal_get_preserves_upstream_arguments_and_uses_inner_thunk() -> None:
    ctx = Context()
    ctx.set_service("answer", 42)
    calls: List[Any] = []

    def hook(target: Context, name: str, error: Exception, next_fn: Any) -> Any:
        calls.append((target, name, error, callable(next_fn)))
        return next_fn()

    ctx.on("internal/get", hook)

    assert ctx.get("answer") == 42
    assert calls[0][0] is ctx
    assert calls[0][1] == "answer"
    assert isinstance(calls[0][2], Exception)
    assert calls[0][3] is True


def test_internal_set_preserves_upstream_arguments_and_uses_inner_thunk() -> None:
    ctx = Context()
    ctx.set_service("answer", 42)
    calls: List[Any] = []

    def hook(
        target: Context,
        name: str,
        value: Any,
        error: Exception,
        next_fn: Any,
    ) -> Any:
        calls.append((target, name, value, error, callable(next_fn)))
        return next_fn()

    ctx.on("internal/set", hook)

    assert ctx.reflect.set(ctx, "answer", 43) is True
    assert ctx.get("answer") == 43
    assert calls[0][0] is ctx
    assert calls[0][1:3] == ("answer", 43)
    assert isinstance(calls[0][3], Exception)
    assert calls[0][4] is True


def test_internal_set_missing_service_raises_without_creating_it() -> None:
    ctx = Context()

    with pytest.raises(RuntimeError, match="without provide"):
        ctx.reflect.set(ctx, "missing", 1)

    assert "missing" not in ctx._services
    assert "missing" not in ctx.reflect.store


def test_internal_set_rejects_a_different_providing_fiber() -> None:
    ctx = Context()

    class Provider(Plugin):
        name = "provider"

        def apply(self, plugin_ctx: Context) -> None:
            plugin_ctx.provide("owned", 1)

    class Sibling(Plugin):
        name = "sibling"

    provider = ctx.registry.plugin(Provider)
    sibling = ctx.registry.plugin(Sibling)

    with pytest.raises(RuntimeError, match="multiple fibers"):
        ctx.reflect.set(sibling.ctx, "owned", 2)

    assert provider.ctx.get("owned") == 1


def test_internal_get_middleware_can_replace_a_missing_service() -> None:
    ctx = Context()
    seen: List[Any] = []

    def hook(target: Context, name: str, error: Exception, next_fn: Any) -> Any:
        seen.append((target, name, error, callable(next_fn)))
        return "replacement"

    ctx.on("internal/get", hook)

    assert ctx.get("missing") == "replacement"
    assert seen[0][0] is ctx
    assert seen[0][1] == "missing"
    assert isinstance(seen[0][2], Exception)
    assert seen[0][3] is True


def test_internal_config_runs_during_activation_with_config_then_next() -> None:
    ctx = Context()
    calls: List[Any] = []

    def hook(config: Dict[str, Any], next_fn: Any) -> Dict[str, Any]:
        calls.append((config, callable(next_fn)))
        resolved = dict(next_fn())
        resolved["interpolated"] = True
        return resolved

    ctx.on("internal/config", hook, global_listener=True)

    class ConfigPlugin(Plugin):
        name = "config-plugin"

    fiber = ctx.registry.plugin(ConfigPlugin, config={"raw": True})

    assert calls == [({"raw": True}, True)]
    assert fiber.config == {"raw": True, "interpolated": True}


def test_internal_update_and_loader_hooks_receive_upstream_positions() -> None:
    ctx = Context()
    Loader(ctx)
    seen: List[Any] = []

    class UpdatePlugin(Plugin):
        name = "update-plugin"

    fiber = ctx.registry.plugin(UpdatePlugin, config={"version": 1})

    def hook(config: Dict[str, Any], no_save: bool, next_fn: Any) -> Any:
        seen.append((config, no_save, callable(next_fn)))
        return next_fn()

    fiber.ctx.on("internal/update", hook)

    fiber.update({"version": 2}, no_save=True)

    assert seen == [({"version": 2}, True, True)]
    assert fiber.config == {"version": 2}


def test_local_internal_hooks_do_not_cross_sibling_contexts() -> None:
    ctx = Context()
    calls: List[str] = []

    class First(Plugin):
        name = "first"

        def apply(self, plugin_ctx: Context) -> None:
            plugin_ctx.provide("first-value", 1)
            plugin_ctx.on(
                "internal/config",
                lambda config, next_fn: calls.append("config") or next_fn(),
            )
            plugin_ctx.on(
                "internal/get",
                lambda target, name, error, next_fn: calls.append("get") or next_fn(),
            )
            plugin_ctx.on(
                "internal/set",
                lambda target, name, value, error, next_fn: calls.append("set") or next_fn(),
            )

    class Second(Plugin):
        name = "second"

        def apply(self, plugin_ctx: Context) -> None:
            plugin_ctx.provide("second-value", 2)

    first = ctx.registry.plugin(First, config={"version": 1})
    second = ctx.registry.plugin(Second, config={"version": 1})

    assert second.ctx.get("second-value") == 2
    assert second.ctx.reflect.set(second.ctx, "second-value", 3) is True
    second.update({"version": 2})

    assert first.ctx.get("first-value") == 1
    assert calls == ["get"]
