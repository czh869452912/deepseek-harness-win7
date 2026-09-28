import pytest
from dsh.code_runtime.contract import validate_bindings, snapshot_json, OutputLedger, encoded


@pytest.mark.parametrize('name', ['lambda', '$tools', '__builtins__', '__debug__', 'console', 'class', 'with'])
def test_portable_reserved_globals_fail_before_run(name):
    with pytest.raises(ValueError):
        validate_bindings([{'global': name, 'functions': {}}])


def test_duplicate_error_globals_and_python_exception_slots_are_rejected():
    for descriptor in [dict(name='tools', memberNameProperty='member'), dict(name='ToolError', memberNameProperty='__cause__')]:
        with pytest.raises(ValueError):
            validate_bindings([dict(global_='unused', **{'global': 'tools'}, functions={}, errorClass=descriptor)])
    assert '__proto__' in validate_bindings([{'global': 'tools', 'functions': {'__proto__': lambda value: value}}])['tools']['functions']


def test_json_boundary_rejects_loss_and_retains_plain_values():
    cyclic = []
    cyclic.append(cyclic)
    for value in [float('nan'), float('inf'), {1: 'number key'}, cyclic, (1, 2), 2 ** 53 + 1]:
        with pytest.raises(ValueError):
            snapshot_json(value)
    assert snapshot_json({'值': [None, False, 1, -0.5]}) == {'值': [None, False, 1, -0.5]}


@pytest.mark.parametrize('budget', [4, 5, 16, 40, 100])
def test_outer_budget_counts_encoded_unicode_logs_and_error(budget):
    ledger = OutputLedger(budget)
    for _ in range(20):
        if not ledger.admit('中文\n"\\'):
            break
    result = ledger.limit()
    assert len(encoded(result['logs'])) + len(encoded(result['error']['message'])) <= budget
    assert result['error']['kind'] == 'output-limit'
