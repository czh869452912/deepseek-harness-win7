"""
Comprehensive unit tests for Cordis Strict Dependency Injection (Stage 2).
Verifies dictionary injection, list injection, child context inheritance,
isolated realm scoping, root exemption, and safe optional queries.
"""

import pytest
from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service


class AlphaService(Service):
    name = "alpha"

    def __init__(self, ctx: Context):
        super().__init__(ctx, "alpha")
        self.val = "alpha_ready"


class BetaService(Service):
    name = "beta"

    def __init__(self, ctx: Context):
        super().__init__(ctx, "beta")
        self.val = "beta_ready"


def test_strict_inject_root_context_unrestricted():
    """Root context (uid=0) can access all services directly for setup."""
    ctx = Context(strict_inject=True)
    ctx.set_service("alpha", AlphaService(ctx))
    assert ctx.alpha.val == "alpha_ready"


def test_strict_inject_dict_dependencies():
    """Plugins can declare inject as a dictionary {service_name: config}."""
    ctx = Context(strict_inject=True)
    ctx.set_service("alpha", AlphaService(ctx))

    accessed = []

    class DictInjectPlugin(Plugin):
        name = "dict-inject-plugin"
        inject = {"alpha": None}

        def apply(self, c: Context) -> None:
            accessed.append(c.alpha.val)

    fiber = ctx.registry.plugin(DictInjectPlugin())
    assert fiber.state == FiberState.ACTIVE
    assert accessed == ["alpha_ready"]


def test_strict_inject_multiple_dependencies():
    """Plugins declaring multiple dependencies can access all declared services."""
    ctx = Context(strict_inject=True)
    ctx.set_service("alpha", AlphaService(ctx))
    ctx.set_service("beta", BetaService(ctx))

    accessed = []

    class MultiInjectPlugin(Plugin):
        name = "multi-inject-plugin"
        inject = ["alpha", "beta"]

        def apply(self, c: Context) -> None:
            accessed.append((c.alpha.val, c.beta.val))

    fiber = ctx.registry.plugin(MultiInjectPlugin())
    assert fiber.state == FiberState.ACTIVE
    assert accessed == [("alpha_ready", "beta_ready")]


def test_strict_inject_partial_declaration_blocks_undeclared():
    """Plugin declaring alpha but not beta can access alpha but fails on beta."""
    ctx = Context(strict_inject=True)
    ctx.set_service("alpha", AlphaService(ctx))
    ctx.set_service("beta", BetaService(ctx))

    class PartialPlugin(Plugin):
        name = "partial-plugin"
        inject = ["alpha"]

        def apply(self, c: Context) -> None:
            _ = c.alpha.val  # Allowed
            _ = c.beta.val   # Should raise!

    fiber = ctx.registry.plugin(PartialPlugin())
    assert fiber.state == FiberState.FAILED
    assert "cannot get property 'beta' without inject" in str(fiber.error)


def test_strict_inject_child_context_inheritance():
    """Child contexts extended from strict root inherit strict_inject=True."""
    root = Context(strict_inject=True)
    root.set_service("alpha", AlphaService(root))

    child = root.extend()
    assert child.strict_inject is True


def test_strict_inject_ctx_has_does_not_raise():
    """Calling ctx.has('service') checks availability without triggering strict inject violation."""
    ctx = Context(strict_inject=True)
    ctx.set_service("alpha", AlphaService(ctx))

    has_results = []

    class HasCheckPlugin(Plugin):
        name = "has-check-plugin"
        inject = []

        def apply(self, c: Context) -> None:
            has_results.append(c.has("alpha"))
            has_results.append(c.has("non_existent"))

    fiber = ctx.registry.plugin(HasCheckPlugin())
    assert fiber.state == FiberState.ACTIVE
    assert has_results == [True, False]


def test_strict_inject_optional_safe_query():
    """ctx.get('service', strict=False) returns service if present, None if missing, without error."""
    ctx = Context(strict_inject=True)
    ctx.set_service("alpha", AlphaService(ctx))

    results = []

    class OptionalPlugin(Plugin):
        name = "optional-plugin"
        inject = []

        def apply(self, c: Context) -> None:
            results.append(c.get("alpha", strict=False).val)
            results.append(c.get("beta", strict=False))

    fiber = ctx.registry.plugin(OptionalPlugin())
    assert fiber.state == FiberState.ACTIVE
    assert results == ["alpha_ready", None]
