import copy

import pytest

from scripts.subprocess_ownership_oracle import expected, validate_observations, validate_runtime


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'reordered', 'lost-pending-owner', 'weak-owner',
    'unreleased-owner', 'skipped-terminal-fallback', 'reordered-admission', 'wrong-name', 'wrong-message',
    'lost-member', 'wrong-member-order', 'lost-member-identity', 'rewrapped-single-error'])
def test_subprocess_ownership_observer_rejects_lost_owner_or_rewritten_failure(damage):
    value = copy.deepcopy(expected())
    validate_observations(value)
    if damage == 'missing':
        value.pop()
    elif damage == 'duplicate':
        value[-1] = copy.deepcopy(value[0])
    elif damage == 'reordered':
        value.reverse()
    elif damage == 'lost-pending-owner':
        value[1]['observed']['retained']['ordinary'] = 0
    elif damage == 'weak-owner':
        value[0]['observed']['retained']['ordinary'] = True
    elif damage == 'unreleased-owner':
        value[1]['observed']['after']['ordinary'] = 1
    elif damage == 'skipped-terminal-fallback':
        value[2]['observed']['trace'].pop()
    elif damage == 'reordered-admission':
        trace = value[2]['observed']['trace']
        trace[1], trace[2] = trace[2], trace[1]
    elif damage == 'wrong-name':
        value[2]['observed']['error']['name'] = 'Error'
    elif damage == 'wrong-message':
        value[2]['observed']['error']['message'] += ': 2 errors'
    elif damage == 'lost-member':
        value[2]['observed']['error']['members'].pop()
    elif damage == 'wrong-member-order':
        value[2]['observed']['error']['members'].reverse()
    elif damage == 'lost-member-identity':
        value[2]['observed']['error']['memberIdentity'] = False
    else:
        value[-1]['observed']['error']['sameWaitFailure'] = False
    with pytest.raises(ValueError):
        validate_observations(value)


@pytest.mark.parametrize('damage', ['root', 'module', 'python', 'weak-python', 'missing'])
def test_subprocess_ownership_runtime_requires_actual_product_and_complete_observations(tmp_path, damage):
    report = {'observations': expected(), 'root': str(tmp_path), 'module': str(tmp_path / 'dsh/__init__.py'), 'python': [3, 8, 10]}
    validate_runtime(report)
    if damage == 'root':
        report['root'] = 'relative'
    elif damage == 'module':
        report['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    elif damage == 'python':
        report['python'] = [3, 9, 10]
    elif damage == 'weak-python':
        report['python'] = ['3', '8', '10']
    else:
        del report['observations']
    with pytest.raises(ValueError):
        validate_runtime(report)
