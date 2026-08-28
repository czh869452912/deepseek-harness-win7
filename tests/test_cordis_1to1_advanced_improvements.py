"""
Unit tests verifying 1:1 Cordis architecture advanced improvements in Python 3.8.10 port:
1. Fiber Awaitable and attribute delegation
2. Method-level @inject reactive dispatch
3. TracedProxy full dunder method delegation
4. Strict inject diagnostic errors and hierarchy traversal
5. evaluate_expr AST and complex operator handling
"""

import asyncio
import os
import pytest
from dsh.cordis.context import Context
from dsh.cordis.fiber import Fiber, FiberState
from dsh.cordis.plugin import Plugin
from dsh.cordis.registry import inject
from dsh.cordis.service import Service
from dsh.cordis.utils import TracedProxy, get_traceable
from dsh.cordis.loader import evaluate_expr, interpolate


class GreetingService(Service):
    name = "greeting"

    def __init__(self, ctx: Context):
        super().__init__(ctx, "greeting")
        self.message = "Hello from GreetingService"

    def greet(self, user: str) -> str:
        return f"Hello, {user}!"


@pytest.mark.asyncio
async def test_fiber_awaitable_and_plugin_return():
    """Verify that ctx.plugin() returns an Awaitable Fiber with transparent attribute delegation."""
    ctx = Context()

    class AsyncSetupPlugin(Plugin):
        name = "async-setup-plugin"
        inject = []

        def __init__(self):
            super().__init__()
            self.loaded_val = None

        async def apply(self, c: Context):
            await asyncio.sleep(0.01)
            self.loaded_val = 42

    fiber = await ctx.plugin(AsyncSetupPlugin())
    assert isinstance(fiber, Fiber)
    assert fiber.state == FiberState.ACTIVE
    # Transparent delegation to plugin attribute
    assert fiber.loaded_val == 42
    assert fiber.plugin.loaded_val == 42


def test_method_inject_reactive_dispatch():
    """Verify that @inject on methods automatically registers reactive hooks that run once dependency arrives."""
    ctx = Context()

    executed_records = []

    class ReactiveMethodPlugin(Plugin):
        name = "reactive-method-plugin"

        @inject("greeting")
        def on_greeting_available(self):
            executed_records.append(self.ctx.greeting.greet("Alice"))

    fiber = ctx.plugin(ReactiveMethodPlugin())
    assert fiber.state == FiberState.ACTIVE
    # greeting is not yet provided, so on_greeting_available has not run
    assert executed_records == []

    # Now provide GreetingService
    ctx.set_service("greeting", GreetingService(ctx))

    # The reactive hook bound by @inject should have executed automatically
    assert executed_records == ["Hello, Alice!"]


def test_traced_proxy_dunder_delegation():
    """Verify TracedProxy full dunder method delegation (containers, iterators, context managers, comparisons)."""
    ctx = Context()

    class Resource:
        def __init__(self):
            self.data = {"key1": "val1", "key2": "val2"}
            self.entered = False
            self.exited = False

        def __getitem__(self, item):
            return self.data[item]

        def __setitem__(self, key, value):
            self.data[key] = value

        def __len__(self):
            return len(self.data)

        def __contains__(self, item):
            return item in self.data

        def __iter__(self):
            return iter(self.data.keys())

        def __enter__(self):
            self.entered = True
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.exited = True

        def __bool__(self):
            return bool(self.data)

    res = Resource()
    proxy = TracedProxy(ctx, res)
    assert isinstance(proxy, TracedProxy)

    # Container protocol
    assert proxy["key1"] == "val1"
    proxy["key3"] = "val3"
    assert proxy["key3"] == "val3"
    assert len(proxy) == 3
    assert "key2" in proxy
    assert list(proxy) == ["key1", "key2", "key3"]

    # Context manager protocol
    with proxy as p:
        assert p.entered is True
    assert res.exited is True

    # Boolean and comparison
    assert bool(proxy) is True
    assert proxy == res


def test_strict_inject_diagnostic_errors():
    """Verify 1:1 strict inject diagnostic errors (without inject vs in inactive context)."""
    ctx = Context(strict_inject=True)

    class InactiveDependencyPlugin(Plugin):
        name = "inactive-dep-plugin"
        inject = ["non_existent_service"]

        def apply(self, c: Context):
            pass

    fiber = ctx.plugin(InactiveDependencyPlugin())
    assert fiber.state == FiberState.PENDING

    class UndeclaredAccessPlugin(Plugin):
        name = "undeclared-access-plugin"
        inject = []

        def apply(self, c: Context):
            # Attempt to access non-injected property
            _ = c.non_existent_service

    f2 = ctx.plugin(UndeclaredAccessPlugin())
    assert f2.state == FiberState.FAILED
    assert "cannot get property 'non_existent_service' without inject" in str(f2.error)


def test_evaluate_expr_complex_ast():
    """Verify evaluate_expr AST and complex operator handling (ternary, logic, platform, env)."""
    ctx = Context()
    os.environ["DSH_TEST_VAR"] = "12345"

    # Ternary operator
    assert evaluate_expr(ctx, "true ? 100 : 200") == 100
    assert evaluate_expr(ctx, "false ? 100 : 200") == 200

    # Logical and comparison operators
    assert evaluate_expr(ctx, "1 === 1 && 2 !== 3") is True
    assert evaluate_expr(ctx, "!false || 1 === 2") is True

    # Environment variables
    assert evaluate_expr(ctx, "process.env.DSH_TEST_VAR === '12345'") is True
    assert evaluate_expr(ctx, "process.env['DSH_TEST_VAR'] === '12345'") is True

    # Interpolate nested structures with ternary expressions
    data = {
        "enabled": {"__jsExpr": "1 === 1 ? true : false"},
        "nested": [
            {"__jsExpr": "process.env.DSH_TEST_VAR"},
            "literal",
        ]
    }
    interpolated = interpolate(ctx, data)
    assert interpolated == {
        "enabled": True,
        "nested": ["12345", "literal"]
    }
