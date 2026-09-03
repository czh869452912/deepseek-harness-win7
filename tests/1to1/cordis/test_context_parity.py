"""
1:1 parity unit test suite for dsh/cordis/context.py matching reference/vendor/cordis/src/context.ts.
Covers:
- T1: isolate with same label joins isolated scope
- T2: Attribute access on child context resolves provided services matching reserved names (status, session, agent)
- T3: has() returns True for declared services even if value is None
- T4: internal/get waterfall listener intercepts property access
- T6: ctx.effect() delegates directly to fiber.effect()
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
    """T2: Attribute access on context resolves provided services even if name in RESERVED_ATTRS."""
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
    """T4: internal/get waterfall listener can intercept and short-circuit property access."""
    ctx = Context(strict_inject=False)
    intercepted = []

    def on_get(target_ctx, name, error, next_fn):
        intercepted.append(name)
        if name == "virtual_prop":
            return "intercepted_val"
        return next_fn()

    ctx.on("internal/get", on_get)

    val = ctx.get("virtual_prop")
    assert val == "intercepted_val"
    assert "virtual_prop" in intercepted


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
