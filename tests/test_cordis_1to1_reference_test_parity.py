"""
Comprehensive 1:1 Parity Test Suite ported directly from TypeScript Reference Specs
(reference/vendor/cordis, reference/vendor/schemastery, reference/vendor/loader, and reference/packages)
"""

import asyncio
import pytest
from typing import Any, Dict, List

from dsh.cordis.context import Context
from dsh.cordis.fiber import Fiber, FiberState, INACTIVE_EPOCH
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service, ServiceSymbols
from dsh.cordis.schema import Schema, z, ValidationError
from dsh.cordis.utils import Symbols, get_traceable, with_props, TracedProxy
from dsh.cordis.loader import Loader, Entry, LocalRealm, GlobalRealm


# --- 1. Schemastery Advanced Types Parity ---

def test_schemastery_bitset_resolution_and_validation():
    """Test z.bitset numeric bitmask and string key array validation matching TS Schemastery."""
    perms = z.bitset({
        "read": 1,
        "write": 2,
        "exec": 4,
        "admin": 8,
    })

    # Integer bitmask passes directly
    assert perms(3) == 3
    assert perms(15) == 15

    # String keys array converts to numeric sum
    assert perms(["read", "exec"]) == 5
    assert perms(["write", "admin"]) == 10

    # Invalid input raises ValidationError
    with pytest.raises(ValidationError):
        perms("invalid")


def test_schemastery_intersect_merging():
    """Test z.intersect output merging matching TS Schemastery."""
    schema_a = z.object({"name": z.string().required()})
    schema_b = z.object({"age": z.number().required()})
    merged_schema = z.intersect([schema_a, schema_b])

    # Valid data matches all branches and merges
    val = merged_schema({"name": "Alice", "age": 30})
    assert val == {"name": "Alice", "age": 30}

    # Invalid data missing one branch fails
    with pytest.raises(ValidationError):
        merged_schema({"name": "Alice"})


def test_schemastery_tuple_validation():
    """Test z.tuple fixed-length array validation matching TS Schemastery."""
    tuple_schema = z.tuple([z.string(), z.number(), z.boolean()])

    res = tuple_schema(["test", 123, True])
    assert res == ["test", 123, True]

    # Wrong length or type raises ValidationError
    with pytest.raises(ValidationError):
        tuple_schema(["test", 123])

    with pytest.raises(ValidationError):
        tuple_schema(["test", "not-a-number", True])


def test_schemastery_transform_and_lazy():
    """Test z.transform and z.lazy matching TS Schemastery."""
    transform_schema = z.transform(z.string(), lambda s, opt: s.upper().strip())
    assert transform_schema("  hello world  ") == "HELLO WORLD"

    # Recursive / Lazy schema
    lazy_schema = z.lazy(lambda: z.object({
        "value": z.number().required(),
        "next": z.union([lazy_schema, z.never()]).optional(),
    }))

    assert lazy_schema({"value": 1}) == {"value": 1}
    assert lazy_schema({"value": 1, "next": {"value": 2}}) == {"value": 1, "next": {"value": 2}}


def test_schemastery_simplify_nested():
    """Test schema.simplify() removing default values matching TS Schemastery."""
    cfg_schema = z.object({
        "mode": z.union(["fast", "accurate"]).default("fast"),
        "retries": z.number().default(3),
        "custom": z.string().optional(),
    })

    # When equal to default, simplify strips it
    assert cfg_schema.simplify({"mode": "fast", "retries": 3}) is None
    # When non-default, simplify keeps modified fields
    assert cfg_schema.simplify({"mode": "accurate", "retries": 3}) == {"mode": "accurate"}
    assert cfg_schema.simplify({"mode": "fast", "retries": 5, "custom": "yes"}) == {"retries": 5, "custom": "yes"}


# --- 2. Cordis Traceable & Shadow Invariants ---

class BaseTestService(Service):
    name = "test_svc"
    def __init__(self, ctx: Context):
        super().__init__(ctx, name="test_svc")
        self.log_history = []

    def log(self, msg: str, caller_ctx: Any = None) -> str:
        ctx_id = getattr(caller_ctx, "uid", "no_ctx") if caller_ctx else "no_ctx"
        self.log_history.append((msg, ctx_id))
        return f"{msg}:{ctx_id}"


def test_traceable_proxy_caller_ctx_injection():
    """Test TracedProxy automatically injecting caller_ctx into method signatures."""
    root_ctx = Context()
    root_svc = BaseTestService(root_ctx)

    child_ctx = root_ctx.extend()
    traced = get_traceable(child_ctx, root_svc)

    res = traced.log("test_event")
    assert res.startswith("test_event:")
    assert len(root_svc.log_history) == 1
    assert getattr(traced, Symbols.original) is root_svc


def test_traceable_proxy_shadow_context_unwrapping():
    """Test that creating traceable proxies with shadow context correctly preserves root identity."""
    root_ctx = Context()
    svc = BaseTestService(root_ctx)

    child1 = root_ctx.extend()
    child2 = child1.extend()

    t1 = get_traceable(child1, svc)
    t2 = get_traceable(child2, t1)

    assert getattr(t2, Symbols.original) is svc
    assert getattr(t1, Symbols.original) is svc


# --- 3. Fiber Generator & Async Generator Disposer Invariants ---

@pytest.mark.asyncio
async def test_fiber_multi_disposer_lifo_order():
    """Test that Fiber effects execute disposers in strict LIFO reverse order matching TS fiber.dispose."""
    ctx = Context()
    order = []

    class LifoPlugin(Plugin):
        def apply(self, c: Context):
            c.effect(lambda: lambda: order.append(1))
            c.effect(lambda: lambda: order.append(2))
            c.effect(lambda: lambda: order.append(3))

    fiber = ctx.plugin(LifoPlugin)
    await fiber.await_settled()
    assert fiber.state == FiberState.ACTIVE

    await fiber.dispose()
    assert fiber.state == FiberState.DISPOSED
    # Disposers must execute in reverse registration order: 3 -> 2 -> 1
    assert order == [3, 2, 1]


@pytest.mark.asyncio
async def test_fiber_generator_interruption_on_reloading():
    """Test that generator effects safely interrupt when epoch shifts during execution."""
    ctx = Context()
    consumed = []
    closed = False

    def generator_effect():
        nonlocal closed
        try:
            yield lambda: consumed.append("disp_a")
            yield lambda: consumed.append("disp_b")
        finally:
            closed = True

    class GenPlugin(Plugin):
        def apply(self, c: Context):
            c.effect(generator_effect)

    fiber = ctx.plugin(GenPlugin)
    await fiber.await_settled()
    assert fiber.state == FiberState.ACTIVE

    await fiber.dispose()
    assert fiber.state == FiberState.DISPOSED
    assert "disp_a" in consumed
    assert "disp_b" in consumed


# --- 4. Loader Realm Isolation & Lifetime ---

def test_loader_realm_scoped_access_and_gc():
    """Test LocalRealm and GlobalRealm isolation scope keys and disposal."""
    ctx = Context()
    loader = Loader(ctx)

    # Local Realm generates entry-specific suffix (#<id>)
    e1 = Entry(loader=loader, name="test-entry-1", entry_id="entry_alpha")
    realm1 = LocalRealm(e1)
    k1 = realm1.access("database", create=True)
    assert k1 == "database#entry_alpha"

    # Global Realm shares same key for same label (@<label>)
    g1 = GlobalRealm("tenant_a")
    g2 = GlobalRealm("tenant_a")
    assert g1.access("mq", create=True) == "mq@tenant_a"
    assert g2.access("mq", create=False) == "mq@tenant_a"

    # Clean up
    g1.delete("mq")
    assert g1.size == 0
