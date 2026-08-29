"""
Tests for deep strict dependency injection, optional dependencies ('?'),
and composite epoch dependency topology matching TS Cordis.
"""

import pytest
from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.cordis.registry import Inject, inject
from dsh.cordis.fiber import FiberState


class ProviderService:
    def __init__(self, val: str = "service_a"):
        self.val = val


class ProviderPlugin(Plugin):
    id = "provider-plugin"
    def apply(self, ctx: Context):
        ctx.set_service("my_service", ProviderService("hello_world"))


class DependentPlugin(Plugin):
    id = "dependent-plugin"
    inject = ["my_service", "optional_service?"]

    def __init__(self):
        self.loaded = False
        self.had_optional = False

    def apply(self, ctx: Context):
        self.loaded = True
        self.service = ctx.my_service
        self.had_optional = ctx.has("optional_service")


def test_optional_dependency_resolution():
    """Test that missing optional dependency ('?') does not block fiber activation."""
    ctx = Context()
    dep_plugin = DependentPlugin()

    # Load dependent plugin before provider
    fiber = ctx.plugin(dep_plugin)
    # Since 'my_service' is required and missing, fiber is PENDING / loading
    assert fiber.state != FiberState.ACTIVE

    # Now load provider plugin
    ctx.plugin(ProviderPlugin)

    # After provider is loaded, dependent should become ACTIVE even though 'optional_service' is absent
    assert fiber.state == FiberState.ACTIVE
    assert dep_plugin.loaded is True
    assert dep_plugin.service.val == "hello_world"
    assert dep_plugin.had_optional is False


def test_inject_helper_normalization():
    """Test Inject.resolve handles lists with '?', dicts, and booleans."""
    res1 = Inject.resolve(["a", "b?"])
    assert res1["a"] is None
    assert res1["b"] == {"required": False}

    res2 = Inject.resolve({"a": True, "b": False})
    assert res2["a"] == {"required": True}
    assert res2["b"] == {"required": False}

    res3 = Inject.resolve({"a": {"required": False}})
    assert res3["a"] == {"required": False}


def test_strict_inject_violation_in_fiber():
    """Test strict inject raises error when accessing undeclared service."""
    ctx = Context(strict_inject=True)

    class BadPlugin(Plugin):
        id = "bad-plugin"
        inject = ["my_service"]
        def apply(self, ctx: Context):
            _ = ctx.undeclared_service  # Should raise

    ctx.plugin(ProviderPlugin)
    fiber = ctx.plugin(BadPlugin)
    assert fiber.state == FiberState.FAILED
