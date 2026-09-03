"""
1:1 Test Parity for Cordis Service
Authority: reference/vendor/cordis/src/service.ts
"""

import pytest
from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service


def test_t1_service_duplicate_registration_raises():
    """ts:service.ts:57 & reflect.ts:318 - duplicate service provide raises RuntimeError."""
    ctx = Context()

    class SvcA(Service):
        name = "my_svc"

    class SvcB(Service):
        name = "my_svc"

    ctx.plugin(SvcA)
    assert ctx.get("my_svc") is not None

    with pytest.raises(RuntimeError, match="has been registered"):
        ctx.plugin(SvcB)


def test_t2_callable_service_invokes_invoke_method():
    """ts:service.ts:50-52 & utils.ts:220-223 - Service.__call__ routes to invoke method."""
    ctx = Context()

    class MathService(Service):
        name = "math_svc"

        def invoke(self, a, b):
            return a * b

    ctx.plugin(MathService)
    svc = ctx.get("math_svc")
    assert callable(svc)
    assert svc(3, 4) == 12


def test_t2_non_callable_service_raises_type_error():
    """ts:service.ts:50-52 - Service without invoke method raises TypeError on call."""
    ctx = Context()

    class PlainService(Service):
        name = "plain_svc"

    ctx.plugin(PlainService)
    svc = ctx.get("plain_svc")
    with pytest.raises(TypeError, match="is not callable"):
        svc()


def test_t4_resolve_config_passes_non_dict_base_raw():
    """ts:service.ts:93-96 - base and head are passed raw without {"base": ...} wrapper."""
    ctx = Context()

    captured_configs = []

    class CustomConfig:
        @classmethod
        def merge(cls, *configs):
            captured_configs.extend(configs)
            return {"merged": True}

    class InterceptedService(Service):
        name = "intercepted"
        Config = CustomConfig

    svc = InterceptedService(ctx)
    svc.resolve_intercept_config(base="raw_string_config", head={"key": "val"})

    assert "raw_string_config" in captured_configs
    assert {"key": "val"} in captured_configs
    assert not any(isinstance(c, dict) and "base" in c for c in captured_configs)


def test_t5_service_plain_check_method_used_by_provide_path():
    """ts:service.ts:57 - plain def check(self) method is used as availability predicate."""
    ctx = Context()

    class UnreadyService(Service):
        name = "unready"

        def check(self):
            return False

    class DependentPlugin(Plugin):
        inject = ["unready"]

        def apply(self, c):
            c.set_service("dependent_active", True)

    ctx.plugin(UnreadyService)
    fiber = ctx.plugin(DependentPlugin)

    assert fiber.state == FiberState.PENDING
    assert ctx.get("dependent_active", strict=False) is None
