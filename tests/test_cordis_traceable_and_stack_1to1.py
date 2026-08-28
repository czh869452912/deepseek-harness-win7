"""
1:1 Unit tests for get_traceable, with_props, and outer_stack in Cordis
Matching reference/vendor/cordis/src/utils.ts
"""

import pytest
from dsh.cordis.context import Context
from dsh.cordis.utils import get_traceable, with_props, build_outer_stack, compose_error


def test_get_traceable_callable():
    ctx = Context()
    
    received_ctx = None
    def my_fn(caller_ctx=None):
        nonlocal received_ctx
        received_ctx = caller_ctx
        return "ok"

    traced = get_traceable(ctx, my_fn)
    assert traced() == "ok"
    assert received_ctx is ctx


def test_with_props_combines_context():
    ctx1 = Context()
    ctx2 = ctx1.extend({"custom_prop": 123})

    class DummyService:
        def test(self, caller_ctx=None):
            return getattr(caller_ctx, "custom_prop", None)

    service = DummyService()
    bound = with_props(ctx2, service)
    assert bound.test() == 123


def test_build_outer_stack_and_compose_error():
    outer_stack_fn = build_outer_stack()
    stack = outer_stack_fn()
    assert isinstance(stack, list)
    assert len(stack) > 0

    def bad_action():
        raise ValueError("Something went wrong")

    with pytest.raises(ValueError) as excinfo:
        compose_error(bad_action, outer_stack_fn)

    assert hasattr(excinfo.value, "_outer_stack")
    assert len(excinfo.value._outer_stack) > 0
