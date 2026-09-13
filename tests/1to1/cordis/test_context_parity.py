"""
1:1 parity unit test suite for dsh/cordis/context.py matching reference/vendor/cordis/src/context.ts.
Covers:
- T1: isolate with same label joins isolated scope
- T2: Attribute access on child context resolves provided services matching reserved names (status, session, agent)
- T3: has() returns True for declared services even if value is None
- T4: internal/get waterfall listener intercepts property access
- T6: ctx.effect() delegates directly to fiber.effect()
- T8: extend()/isolate()/intercept() derived contexts resolve the root registry
  state (shared runtime table and fiber-uid allocator)
"""

import pytest
from typing import Any

from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service


def test_t1_isolate_same_label_joins_scope():
    """T1: Same label joins scope between two isolated contexts."""
    root = Context()
    label_obj = object()

    child_a = root.isolate("shared_svc", label=label_obj)
    child_b = root.isolate("shared_svc", label=label_obj)
    child_c = root.isolate("shared_svc")  # distinct label

    child_a.provide("shared_svc", "isolated_val")

    assert child_a.get("shared_svc") == "isolated_val"
    assert child_b.get("shared_svc") == "isolated_val"
    assert child_c.get("shared_svc") is None
    assert root.get("shared_svc") is None


def test_t2_child_context_attribute_access_for_reserved_service_names():
    """T2: Service resolution priority: attribute access and get() on child context cleanly resolve provided services."""
    root = Context()
    dummy_status = {"online": True}
    root.set_service("status", dummy_status)

    child = root.extend()
    assert child.status == dummy_status
    assert child.get("status") == dummy_status


def test_t3_has_true_for_declared_none_valued_service():
    """T3: has() returns True for declared services even if the provided value is None."""
    ctx = Context()
    assert not ctx.has("nullable_svc")

    ctx.provide("nullable_svc", None)
    assert ctx.has("nullable_svc")


def test_t4_internal_get_waterfall_listener_shape_and_short_circuit():
    """T4: internal/get intercepts proxy property access of a plugin-fiber context.

    reflect.ts `ReflectService.handler.get` dispatches the waterfall only when
    `ctx.fiber.runtime` is set, and `ReflectService.get()` reads the store
    directly, so `ctx.get(...)` is never intercepted.
    """
    ctx = Context()
    intercepted = []
    seen = {}

    def on_get(target_ctx, name, error, next_fn):
        intercepted.append(name)
        if name == "virtual_prop":
            return "intercepted_val"
        return next_fn()

    ctx.on("internal/get", on_get)

    class ReaderPlugin(Plugin):
        name = "internal_get_reader"
        inject = ["probe_service"]

        def apply(self, c: Context) -> None:
            seen["virtual"] = c.virtual_prop
            seen["declared"] = c.probe_service

    ctx.provide("probe_service", "provided-value")
    fiber = ctx.plugin(ReaderPlugin)

    assert fiber.state == FiberState.ACTIVE
    assert seen["virtual"] == "intercepted_val"
    assert seen["declared"] == "provided-value"
    # `ctx.get()` and runtime-less attribute reads do not dispatch the waterfall.
    assert ctx.get("probe_service") == "provided-value"
    assert intercepted == ["virtual_prop", "probe_service"]


def test_t6_ctx_effect_delegates_to_fiber_effect():
    """T6: ctx.effect() executes setup immediately and returns disposer."""
    ctx = Context()
    events = []

    def my_setup():
        events.append("setup")
        return lambda: events.append("disposed")

    disposer = ctx.effect(my_setup, label="my_effect")
    assert "setup" in events
    assert "disposed" not in events

    disposer()
    assert "disposed" in events


def test_t7_strict_resolve_order_root_store_accessible():
    """T7: Plugin child context and grandchild context can resolve root-provided services without inject.

    [ADAPT / PERMITTED DEVIATION]
    In Cordis TypeScript, strict mode requires all accessed services to be explicitly declared in inject.
    In Python deepseek-harness-win7, root-provided services (e.g. core launcher services) remain accessible
    from descendant fibers even under strict_inject for framework convenience, while access to non-root
    undeclared services still strictly raises RuntimeError.
    """
    root = Context(strict_inject=True)
    root.provide("my_service", "hello_root")

    received_child = []
    received_grandchild = []

    class GrandchildPlugin(Plugin):
        name = "grandchild"
        inject = []

        def apply(self, gc: Context) -> None:
            received_grandchild.append(gc.my_service)

    class ChildPlugin(Plugin):
        name = "child"
        inject = []

        def apply(self, c: Context) -> None:
            received_child.append(c.my_service)
            c.plugin(GrandchildPlugin)

    fiber = root.plugin(ChildPlugin)
    assert fiber.state == FiberState.ACTIVE
    assert received_child == ["hello_root"]
    assert received_grandchild == ["hello_root"]

    # Negative case: Accessing an undeclared service not present in root store raises RuntimeError
    caught_negative = []

    class NegativePlugin(Plugin):
        name = "negative"
        inject = []

        def apply(self, neg_ctx: Context) -> None:
            try:
                _ = neg_ctx.nonexistent_service
            except RuntimeError as e:
                caught_negative.append(str(e))

    neg_fiber = root.plugin(NegativePlugin)
    assert "cannot get property" in caught_negative[0] and "without inject" in caught_negative[0]
    assert "nonexistent_service" in caught_negative[0]


def test_r1_repr_with_strict_inject_safe_fiber_access():
    """R1 pin test: Context.__repr__ on strict-inject context reads fiber safely without triggering inject checks."""
    ctx = Context(strict_inject=True)

    captured_reprs = []

    class DummyPlugin(Plugin):
        name = "dummy-plug"
        inject = []

        def apply(self, child_ctx: Context) -> None:
            r = repr(child_ctx)
            captured_reprs.append(r)

    fiber = ctx.plugin(DummyPlugin)
    assert fiber.state == FiberState.ACTIVE
    assert len(captured_reprs) == 1
    assert "dummy-plug" in captured_reprs[0]
    assert captured_reprs[0].startswith("Context <")





def test_t8_derived_contexts_resolve_the_root_registry_state():
    """T8: `extend()`/`isolate()`/`intercept()` keep one registry allocator.

    Reference: `context.ts#Context.extend` builds the child with
    `Object.create(this)`, so `ctx.registry`, `ctx.events`, `ctx.reflect` and
    `ctx.logger` all resolve to the parent's service instances; only the meta
    properties passed in shadow them. The Python port binds a per-context
    registry view, so the shared state itself (the fiber-uid allocator and the
    runtime table) must stay common to the whole tree.
    """
    root = Context()
    extended = root.extend()
    isolated = root.isolate("t8_service")
    intercepted = root.intercept("t8_service", {"flag": True})

    class TreePlugin(Plugin):
        name = "t8_tree"

    fiber = extended.plugin(TreePlugin, {})

    # The child published the fiber into the one shared runtime table.
    assert root.registry.get(TreePlugin) is extended.registry.get(TreePlugin)
    assert fiber in root.registry.list_fibers()
    assert fiber in isolated.registry.list_fibers()
    assert fiber in intercepted.registry.list_fibers()

    # ... and the shared allocator kept issuing strictly increasing uids.
    assert isolated.registry.counter == fiber.uid + 1
    assert intercepted.registry.counter == fiber.uid + 2
