import pytest
from dsh.cordis.context import Context
from dsh.diagnostics.invariants import InvariantRegistry, InvariantError


def test_invariant_registry_duplicate_registration_raises():
    ctx = Context()
    registry = InvariantRegistry(ctx)
    ctx.set_service('invariants', registry)

    registry.register('@deepseek-ai/dsh-api-settings-controller', lambda c, fail: None)

    with pytest.raises(ValueError) as exc_info:
        registry.register('@deepseek-ai/dsh-api-settings-controller', lambda c, fail: None)
    assert 'already registered' in str(exc_info.value)


def test_invariant_registry_whitespace_validation():
    ctx = Context()
    registry = InvariantRegistry(ctx)
    ctx.set_service('invariants', registry)

    with pytest.raises(ValueError) as exc_info:
        registry.register('invalid package name with spaces', lambda c, fail: None)
    assert 'must be non-blank and contain no whitespace' in str(exc_info.value)


def test_invariant_error_format():
    err = InvariantError('@deepseek-ai/dsh-settings', 'unregistered namespace')
    assert err.code == 'INVARIANT'
    assert err.package_name == '@deepseek-ai/dsh-settings'
    assert 'invariant violated by' in str(err)
    assert '@deepseek-ai/dsh-settings' in str(err)
