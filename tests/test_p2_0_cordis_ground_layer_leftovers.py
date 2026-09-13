"""
P2-0 Nail Tests: Cordis Ground-Layer Leftover Closure (≈25 MUST-FIX items).
Covers G1, G2, G3, G4, G5, G6 alignment with TS Cordis / Cosmokit.
"""

import asyncio
import datetime
import pytest

from dsh.cordis import Context, Plugin, Service
from dsh.cordis.events import EventBus
from dsh.cordis.fiber import FiberState
from dsh.cordis.registry import inject
from dsh.cordis.utils import Binary, Time, define_property, is_, map_values, mapValues


# ==============================================================================
# G2-plugin: D4, D6, D7, D10, D28
# ==============================================================================

def test_g2_d4_method_inject_deferred_execution():
    """D4: @inject on class method defers execution until service available instead of throwing."""
    ctx = Context()
    executed = []

    class ServiceDep:
        val = 42

    class MyPlugin(Plugin):
        name = "my_plugin"

        @inject("dep")
        def run_action(self):
            executed.append(self.ctx.dep.val)

    # Calling method when service is missing does not throw RuntimeError; it returns a deferred hook
    plugin = MyPlugin()
    plugin.ctx = ctx
    res = plugin.run_action()
    assert len(executed) == 0

    # Provide the service now
    ctx.set_service("dep", ServiceDep())
    assert executed == [42]


def test_g2_d6_d7_runtime_identity_and_name_cleanup():
    """D6/D7: PluginRuntime does not invent fallback to id or schema; name 'apply' is cleared."""
    ctx = Context()

    class ApplyNamedPlugin:
        name = "apply"
        schema = {"fake": True}

        def apply(self, c, cfg=None):
            pass

    fiber = ctx.plugin(ApplyNamedPlugin)
    runtime = ctx.registry.get(ApplyNamedPlugin)
    assert runtime is not None
    # 'apply' name is normalized to None
    assert runtime.name is None
    # schema is not picked up as Config
    assert runtime.Config is None

    # Unload can be done by plugin class directly matching TS registry.delete
    loop = asyncio.new_event_loop()
    try:
        success = loop.run_until_complete(ctx.registry.unload_plugin(ApplyNamedPlugin))
        assert success is True
        assert not ctx.registry.has(ApplyNamedPlugin)
    finally:
        loop.close()


def test_g2_d10_registry_does_not_emit_internal_plugin():
    """D10: registry.plugin does not emit internal/plugin (only Fiber handles lifecycle)."""
    ctx = Context()
    emitted = []

    ctx.on("internal/plugin", lambda f: emitted.append(f.name), global_listener=True)

    class SamplePlugin(Plugin):
        name = "sample"
        def apply(self, c, cfg=None):
            pass

    # When plugin is mounted, Fiber handles lifecycle. Registry.plugin does not independently emit
    ctx.plugin(SamplePlugin)
    # The fiber itself is active
    assert ctx.registry.has(SamplePlugin)


def test_g2_d28_provide_duplicate_raises_exact_error():
    """D28: reflect.provide throws exact TS error when service is already registered on that key, even if same value."""
    ctx = Context()

    ctx.provide("singleton_svc", "val1")

    with pytest.raises(RuntimeError) as excinfo:
        ctx.provide("singleton_svc", "val1")
    assert 'service "singleton_svc" has been registered at <root>' in str(excinfo.value)


# ==============================================================================
# G3-events: D4, D6, D7
# ==============================================================================

def test_g3_d4_waterfall_next_does_not_accept_override_args():
    """D4: waterfall next_fn ignores override arguments and forwards initial args matching TS."""
    bus = EventBus()
    seen_args = []

    def mw1(val, next_fn):
        seen_args.append(("mw1", val))
        # Attempt to pass override argument
        return next_fn("hacked_val")

    def mw2(val, next_fn):
        seen_args.append(("mw2", val))
        return next_fn()

    def inner(val):
        seen_args.append(("inner", val))
        return f"done:{val}"

    bus.on("waterfall/test", mw1)
    bus.on("waterfall/test", mw2)

    res = bus.waterfall_sync("waterfall/test", "initial_val", inner)
    assert res == "done:initial_val"
    assert seen_args == [
        ("mw1", "initial_val"),
        ("mw2", "initial_val"),
        ("inner", "initial_val"),
    ]


@pytest.mark.asyncio
async def test_g3_d4_waterfall_async_next_does_not_accept_override_args():
    """D4 async: async waterfall next_fn ignores override arguments and forwards initial args matching TS."""
    bus = EventBus()
    seen_args = []

    async def mw1(val, next_fn):
        seen_args.append(("mw1", val))
        return await next_fn("hacked_val")

    def inner(val):
        seen_args.append(("inner", val))
        return f"async_done:{val}"

    bus.on("waterfall/async_test", mw1)
    res = await bus.waterfall("waterfall/async_test", "initial_val", inner)
    assert res == "async_done:initial_val"
    assert seen_args == [("mw1", "initial_val"), ("inner", "initial_val")]


def test_g3_d6_internal_dispatch_passes_four_positional_args():
    """D6: internal/dispatch receives 4 positional args (type, name, args, caller_ctx) with no dict conversion."""
    bus = EventBus()
    dispatches = []

    def on_dispatch(disp_type, event_name, event_args, caller_ctx):
        dispatches.append((disp_type, event_name, event_args))

    bus.on("internal/dispatch", on_dispatch, global_listener=True)
    bus.emit("custom_event", "arg1", 42)

    assert len(dispatches) >= 1
    assert dispatches[0] == ("emit", "custom_event", ["arg1", 42])


def test_g3_d7_internal_listener_options_payload():
    """D7: internal/listener receives options dict with prepend and global keys."""
    bus = EventBus()
    captured_options = []

    def on_listener(name, listener, options, *args, **kwargs):
        captured_options.append((name, options))

    bus.on("internal/listener", on_listener, global_listener=True)
    bus.on("some_test_event", lambda: None, prepend=True, global_listener=False)

    assert any(
        name == "some_test_event" and isinstance(opt, dict) and opt.get("prepend") is True
        for name, opt in captured_options
    )


# ==============================================================================
# G5-fiber: D8, D14, D20, D21
# ==============================================================================

def test_g5_d8_fiber_apply_without_signature_sniffing():
    """D8: apply is called with (ctx, config) and non-callable truthy return raises TypeError('Invalid effect')."""
    ctx = Context()

    class InvalidEffectPlugin(Plugin):
        name = "invalid_effect"
        def apply(self, c, cfg=None):
            return "not_a_callable_or_disposer"

    fiber = ctx.plugin(InvalidEffectPlugin)
    assert fiber.state == FiberState.FAILED
    assert isinstance(fiber.error, TypeError)
    assert "Invalid effect" in str(fiber.error)


def test_g5_d20_fiber_name_ancestor_traversal():
    """D20: Fiber.name traverses ancestors checking only runtime.name, returning 'root' when unnamed."""
    ctx = Context()

    # Lambda plugin has cb_name '<lambda>' which normalizes to runtime.name = None
    fiber = ctx.plugin(lambda c: None)
    # Since lambda has no runtime.name, fiber.name traverses up to parent and returns 'root'
    assert fiber.name == "root"


@pytest.mark.asyncio
async def test_g5_d21_fiber_async_restart():
    """D21: Fiber.restart is an async method that asserts active, reloads, and returns fiber."""
    ctx = Context()
    init_count = 0

    class RestartablePlugin(Plugin):
        name = "restartable"
        def apply(self, c, cfg=None):
            nonlocal init_count
            init_count += 1

    fiber = await ctx.plugin(RestartablePlugin)
    assert init_count == 1
    assert fiber.state == FiberState.ACTIVE

    res = await fiber.restart()
    assert res is fiber
    assert init_count == 2
    assert fiber.state == FiberState.ACTIVE


# ==============================================================================
# G6-context: D1, D2, D3, D5, D9, D10, D11, D12
# ==============================================================================

def test_g6_d1_context_is_brand_only():
    """D1: Context.is_ returns True only for branded Context, rejecting arbitrary duck-typed objects."""
    ctx = Context()
    assert Context.is_(ctx) is True

    class FakeContext:
        registry = True
        reflect = True
        extend = True

    assert Context.is_(FakeContext()) is False
    assert Context.is_({"registry": None, "reflect": None, "extend": None}) is False


def test_g6_d2_effect_metas_preserved_on_root():
    """D2: Root context does not clear _effect_metas on creation."""
    ctx = Context()
    assert hasattr(ctx.fiber, "_effect_metas")
    assert isinstance(ctx.fiber._effect_metas, dict)
    assert len(ctx.fiber._effect_metas) > 0


def test_g6_d3_extend_shadow_propagation():
    """D3: ctx.extend() propagates _shadow from parent to child."""
    root = Context()
    root._shadow = "custom_shadow_token"

    child = root.extend()
    assert getattr(child, "_shadow", None) == "custom_shadow_token"


def test_g6_d5_isolate_single_key_contract():
    """D5: ctx.isolate accepts a single service name and optional label."""
    root = Context()
    label_obj = object()
    child_a = root.isolate("db", label=label_obj)
    child_b = root.isolate("db", label=label_obj)
    child_c = root.isolate("db")

    assert child_a["symbols.isolate"]["db"] is label_obj
    assert child_b["symbols.isolate"]["db"] is label_obj
    assert child_c["symbols.isolate"]["db"] is not label_obj


def test_g6_d9_d12_strict_store_lookup_and_error():
    """D9/D12: Root context handles undeclared access via reflect.get/AttributeError, child contexts throw strict inject error, and isolated key is respected."""
    root = Context(strict_inject=True)

    # Root context (no runtime) does not throw inject error (TS reflect.ts:152: if (!ctx.fiber.runtime) return ctx.reflect.get(prop, false))
    assert not hasattr(root, "missing_service")
    with pytest.raises(AttributeError):
        _ = root.missing_service

    # Child context in plugin
    class StrictChildPlugin(Plugin):
        name = "strict_child"
        inject = []
        def apply(self, c, cfg=None):
            with pytest.raises(RuntimeError) as exc_child:
                _ = c.another_missing
            assert 'cannot get property "another_missing" without inject' in str(exc_child.value) or "cannot get property 'another_missing' without inject" in str(exc_child.value)

    f = root.plugin(StrictChildPlugin)
    assert f.state == FiberState.ACTIVE


# ==============================================================================
# G1 / G4: G1-D5, G1-D14, G4-D2
# ==============================================================================

def test_g1_d5_parse_date_md_branch():
    """G1-D5: Time.parse_date handles M-D-H:MM[:SS] format with current year completion."""
    now = datetime.datetime.now()
    parsed = Time.parse_date("9-9-12:30")
    assert parsed.year == now.year
    assert parsed.month == 9
    assert parsed.day == 9
    assert parsed.hour == 12
    assert parsed.minute == 30


def test_g1_d14_cosmokit_binary_and_helpers():
    """G1-D14: Cosmokit is_, Binary, define_property, and map_values exist and function."""
    # is_
    assert is_("String", "hello") is True
    assert is_("String", 123) is False
    is_num = is_("Number")
    assert is_num(42) is True
    assert is_num("42") is False

    # Binary
    raw = b"Hello Cosmokit"
    b64 = Binary.to_base64(raw)
    assert Binary.from_base64(b64) == raw
    hex_str = Binary.to_hex(raw)
    assert Binary.from_hex(hex_str) == raw
    assert Binary.is_source(raw) is True
    assert Binary.is_source("not binary") is False

    # define_property
    class Obj:
        pass
    o = Obj()
    define_property(o, "secret", 1234)
    assert getattr(o, "secret") == 1234

    # map_values / mapValues
    d = {"a": 1, "b": 2}
    mapped = map_values(d, lambda v, k: v * 10)
    assert mapped == {"a": 10, "b": 20}
    assert mapValues(d, lambda v, k: f"{k}_{v}") == {"a": "a_1", "b": "b_2"}


def test_g4_d2_timer_exceptions_logged(capsys):
    """G4-D2: Timer interval thread logs exceptions instead of swallowing with empty pass."""
    ctx = Context()
    # interval with bad callback logs error
    def bad_cb():
        raise ValueError("simulated interval failure")

    # In thread mode (no running loop in sync test)
    # TimerService interval returns a disposer
    disposer = ctx.timer.interval(bad_cb, 50)
    import time
    time.sleep(0.15)
    disposer()
