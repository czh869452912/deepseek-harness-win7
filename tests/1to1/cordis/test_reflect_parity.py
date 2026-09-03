"""
1:1 Test Parity for Cordis Reflect
Authority: reference/vendor/cordis/src/reflect.ts
"""

import pytest
from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service


def test_t1_set_from_root_ctx_across_fibers_raises():
    """ts:reflect.ts:260-262 - root ctx cannot set service provided by a plugin fiber."""
    ctx = Context()

    class SvcPlugin(Service):
        name = "plugin_svc"

    ctx.plugin(SvcPlugin)
    assert ctx.get("plugin_svc") is not None

    with pytest.raises(RuntimeError, match="in multiple fibers"):
        ctx.set("plugin_svc", "malicious_overwrite")


def test_t2_plugin_provide_conflicting_with_root_provided_service_raises():
    """ts:reflect.ts:289-291 - plugin cannot provide a service already provided on root."""
    ctx = Context()
    ctx.provide("custom_core", "core_val")

    with pytest.raises(RuntimeError, match="has been registered"):
        ctx.provide("custom_core", "conflict_val")

    class ConflictingPlugin(Plugin):
        def apply(self, c):
            c.provide("custom_core", "conflict_val")

    fiber = ctx.plugin(ConflictingPlugin)
    assert fiber.error is not None
    assert "has been registered" in str(fiber.error)


def test_t3_internal_service_listener_scope_filtering():
    """ts:reflect.ts:330-334 - internal/service event only reaches listeners in matching isolation scope."""
    ctx = Context()
    isolated_child = ctx.isolate("isolated_svc")

    events_received_isolated = []
    events_received_root = []

    isolated_child.on("internal/service", lambda name, val: events_received_isolated.append((name, val)))
    ctx.on("internal/service", lambda name, val: events_received_root.append((name, val)))

    # Provide in root scope
    ctx.provide("isolated_svc", "root_value")

    # Root listener receives notification, isolated child does NOT
    assert ("isolated_svc", "root_value") in events_received_root
    assert ("isolated_svc", "root_value") not in events_received_isolated


def test_t7_numeric_string_property_bypasses_resolution():
    """ts:reflect.ts:89 - numeric string property bypasses service resolution as special property."""
    ctx = Context()
    assert ctx.get("0", strict=False) is None
    # Verify accessing numeric string property does not raise "without inject"
    val = getattr(ctx, "123", "fallback")
    assert val == "fallback"
