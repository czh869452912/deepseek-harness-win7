"""
Unit tests verifying Cordis Strict Dependency Injection enforcement (Stage 2).
"""

import pytest
from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service


class DummyService(Service):
    name = "dummy"

    def __init__(self, ctx: Context):
        super().__init__(ctx, "dummy")
        self.message = "hello dummy"


def test_strict_inject_disabled_allows_undeclared_service():
    """When strict_inject=False, undeclared service access is permitted."""
    ctx = Context(strict_inject=False)
    ctx.set_service("dummy", DummyService(ctx))

    accessed_val = []

    class RelaxedPlugin(Plugin):
        name = "relaxed-plugin"
        inject = []

        def apply(self, c: Context) -> None:
            accessed_val.append(c.dummy.message)

    ctx.registry.plugin(RelaxedPlugin())
    assert accessed_val == ["hello dummy"]


def test_strict_inject_enabled_blocks_undeclared_service():
    """When strict_inject=True, accessing undeclared service raises RuntimeError and fails the fiber."""
    ctx = Context(strict_inject=True)
    ctx.set_service("dummy", DummyService(ctx))

    class StrictUndeclaredPlugin(Plugin):
        name = "strict-undeclared-plugin"
        inject = []

        def apply(self, c: Context) -> None:
            _ = c.dummy.message

    fiber = ctx.registry.plugin(StrictUndeclaredPlugin())
    assert fiber.state == FiberState.FAILED
    assert fiber.error is not None
    assert "cannot get property 'dummy' without inject" in str(fiber.error)

    with pytest.raises(RuntimeError) as excinfo:
        fiber.assert_active()
    assert "cannot get property 'dummy' without inject" in str(excinfo.value)


def test_strict_inject_enabled_allows_declared_service():
    """When strict_inject=True, declaring inject allows accessing the service."""
    ctx = Context(strict_inject=True)
    ctx.set_service("dummy", DummyService(ctx))

    accessed_val = []

    class StrictDeclaredPlugin(Plugin):
        name = "strict-declared-plugin"
        inject = ["dummy"]

        def apply(self, c: Context) -> None:
            accessed_val.append(c.dummy.message)

    ctx.registry.plugin(StrictDeclaredPlugin())
    assert accessed_val == ["hello dummy"]


def test_strict_inject_enabled_ctx_get_bypasses_for_optional():
    """When strict_inject=True, ctx.get('...', strict=False) safely retrieves optional service."""
    ctx = Context(strict_inject=True)
    ctx.set_service("dummy", DummyService(ctx))

    accessed_val = []

    class OptionalServicePlugin(Plugin):
        name = "optional-service-plugin"
        inject = []

        def apply(self, c: Context) -> None:
            svc = c.get("dummy", strict=False)
            if svc:
                accessed_val.append(svc.message)

    ctx.registry.plugin(OptionalServicePlugin())
    assert accessed_val == ["hello dummy"]
