import copy

import pytest

from scripts.mcp_disposal_oracle import expected, validate_observations, validate_runtime


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'reordered', 'transient-swap', 'leaked-tools',
    'queued-fetch', 'extra-close', 'weak-generation', 'late-error', 'missing-warning', 'wrong-code', 'wrong-ready'])
def test_mcp_disposal_observer_rejects_incomplete_or_rewritten_ownership(damage):
    value = copy.deepcopy(expected())
    validate_observations(value)
    rows = value['supervisor']
    if damage == 'missing':
        rows.pop()
    elif damage == 'duplicate':
        rows[-1] = copy.deepcopy(rows[0])
    elif damage == 'reordered':
        rows.reverse()
    elif damage == 'transient-swap':
        rows[2]['trace'] = rows[2]['trace'][:-2]
    elif damage == 'leaked-tools':
        rows[3]['after'] = ['mcp__controlled__late']
    elif damage == 'queued-fetch':
        rows[-1]['trace'].append(['fetch', 'tools/list'])
    elif damage == 'extra-close':
        rows[0]['trace'].append(['close'])
    elif damage == 'weak-generation':
        rows[0]['trace'][0][1] = True
    elif damage == 'late-error':
        rows[4]['logs'].append(['error', 'controlled disposed fetch'])
    elif damage == 'missing-warning':
        value['factory']['logs'].pop()
    elif damage == 'wrong-code':
        value['factory']['outcome']['code'] = 'ignored'
    else:
        rows[2]['outcome'] = {}
    with pytest.raises(ValueError):
        validate_observations(value)


@pytest.mark.parametrize('damage', ['root', 'module', 'python', 'weak-python', 'missing'])
def test_mcp_disposal_runtime_requires_actual_product_provenance(tmp_path, damage):
    report = dict(expected(), root=str(tmp_path), module=str(tmp_path / 'dsh/__init__.py'), python=[3, 8, 10])
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
        del report['factory']
    with pytest.raises(ValueError):
        validate_runtime(report)
