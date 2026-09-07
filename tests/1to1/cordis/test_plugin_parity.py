"""
1:1 parity test suite for Cordis Plugin entry contracts matching
reference/vendor/cordis/src/registry.ts and fiber.ts (Report 2).
Covers T1-T6 for D1-D6.
"""

import asyncio
import pytest
from typing import Any, Dict, List, Optional
from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service
from dsh.cordis.schema import Schema
from dsh.cordis.fiber import FiberState


def create_test_context() -> Context:
    return Context()


def test_t1_inject_callback_receives_config():
    """T1: ctx.inject callback receives (ctx, config) (D2)."""
    ctx = create_test_context()
    captured = []

    def on_injected(c: Any, cfg: Any):
        captured.append((c, cfg))

    ctx.inject([], on_injected)
    assert len(captured) == 1
    assert captured[0][0] is not None
    assert captured[0][1] in (None, {})


def test_t2_object_plugin_apply_receives_config():
    """T2: Object plugin apply receives (ctx, config) (D3)."""
    ctx = create_test_context()
    captured = []

    class ObjPlugin:
        def apply(self, c: Any, config: Optional[Dict[str, Any]] = None):
            captured.append((c, config))

    ctx.plugin(ObjPlugin(), {"a": 1, "b": "test"})
    assert len(captured) == 1
    assert captured[0][1] == {"a": 1, "b": "test"}

    # Also test dict-shaped plugin with apply
    dict_captured = []
    dict_plugin = {
        "apply": lambda c, cfg: dict_captured.append(cfg)
    }
    ctx.plugin(dict_plugin, {"num": 42})
    assert len(dict_captured) == 1
    assert dict_captured[0] == {"num": 42}


def test_t3_registry_invalid_plugin_error_message():
    """T3: Invalid plugin error type and message, property access exception handled (D4)."""
    ctx = create_test_context()

    with pytest.raises(Exception) as exc_info:
        ctx.plugin(123)
    msg = str(exc_info.value)
    assert 'invalid plugin, expect function or object with an "apply" method' in msg
    assert "int" in msg

    # Object whose apply attribute raises when accessed
    class ExplodingApply:
        @property
        def apply(self):
            raise RuntimeError("Cannot access apply property")

    # registry.resolve returns None, plugin() raises invalid plugin Error
    with pytest.raises(Exception) as exc_info2:
        ctx.plugin(ExplodingApply())
    msg2 = str(exc_info2.value)
    assert 'invalid plugin, expect function or object with an "apply" method' in msg2


def test_t4_plugin_constructor_typeerror_propagates():
    """T4: Constructor internal TypeError propagates to fiber._error without fallback (D6)."""
    ctx = create_test_context()

    class BuggyPlugin(Plugin):
        def __init__(self, config=None):
            super().__init__(config)
            # Internal TypeError
            _ = None + 1

        def apply(self, c):
            pass

    fiber = ctx.plugin(BuggyPlugin)
    assert fiber.state == FiberState.FAILED
    assert isinstance(fiber._error, TypeError)
    assert "unsupported operand type" in str(fiber._error)


def test_t5_plugin_apply_returned_disposer_disposed():
    """T5: apply returned disposer or generator disposers executed on dispose (D5)."""
    ctx = create_test_context()
    disposed = []

    # Single callable disposer returned from apply
    def plugin_with_disposer(c: Any, cfg: Any):
        def cleanup():
            disposed.append("plugin_cleanup")
        return cleanup

    f1 = ctx.plugin(plugin_with_disposer)
    assert f1.state == FiberState.ACTIVE
    assert "plugin_cleanup" not in disposed

    asyncio.run(f1.dispose())
    assert "plugin_cleanup" in disposed

    # Generator yielding disposers
    generator_disposed = []

    def plugin_with_generator(c: Any, cfg: Any):
        yield lambda: generator_disposed.append("gen_disp_1")
        yield lambda: generator_disposed.append("gen_disp_2")

    f2 = ctx.plugin(plugin_with_generator)
    assert f2.state == FiberState.ACTIVE
    assert generator_disposed == []

    asyncio.run(f2.dispose())
    assert "gen_disp_1" in generator_disposed
    assert "gen_disp_2" in generator_disposed


def test_t6_plugin_provide_metadata_and_runtime_config():
    """T6: Service provide attribute and PluginRuntime.Config validation (D1)."""
    ctx = create_test_context()

    class CustomService(Service):
        provide = "custom_svc"

        def get_value(self):
            return 99

    f_svc = ctx.plugin(CustomService)
    assert f_svc.state == FiberState.ACTIVE
    assert ctx.get("custom_svc") is not None
    assert ctx.get("custom_svc").get_value() == 99

    # Runtime.Config validation
    cfg_schema = Schema.object({
        "port": Schema.number().default(8080)
    })

    class ConfiguredPlugin(Plugin):
        Config = cfg_schema

        def apply(self, c, cfg=None):
            pass

    f_cfg = ctx.plugin(ConfiguredPlugin, {})
    assert f_cfg.state == FiberState.ACTIVE
    assert f_cfg.config == {"port": 8080}
    runtime = ctx.registry.get(ConfiguredPlugin)
    assert runtime is not None
    assert runtime.Config is cfg_schema
