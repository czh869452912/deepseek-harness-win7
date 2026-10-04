import copy

import pytest

from scripts.projection_cache_failure_oracle import expected, validate_observations, validate_runtime


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'reorder', 'hidden-error', 'wrapped-error',
    'cold-replay', 'cold-overwrite', 'prepared-error', 'prepared-overwrite', 'lost-tail',
    'replayed-prefix', 'wrong-cut', 'wrong-identity', 'wrong-version', 'weak-seq'])
def test_cache_observer_rejects_hidden_failure_or_wrong_durable_cut(damage):
    rows = copy.deepcopy(expected())
    validate_observations(rows)
    if damage == 'missing':
        rows.pop()
    elif damage == 'duplicate':
        rows[-1] = copy.deepcopy(rows[0])
    elif damage == 'reorder':
        rows.reverse()
    elif damage == 'hidden-error':
        del rows[0]['observed']['error']
    elif damage == 'wrapped-error':
        rows[0]['observed']['error']['sameParserFailure'] = False
    elif damage == 'cold-replay':
        rows[0]['observed']['applied'] = [0, 1]
    elif damage == 'cold-overwrite':
        rows[0]['observed']['document']['record']['rows']['controlled/count']['val'] = 2
    elif damage == 'prepared-error':
        rows[1]['observed']['error'] = copy.deepcopy(rows[0]['observed']['error'])
    elif damage == 'prepared-overwrite':
        rows[1]['observed']['document']['record']['rows']['controlled/count']['seq'] = 1
    elif damage == 'lost-tail':
        rows[2]['observed']['applied'] = []
    elif damage == 'replayed-prefix':
        rows[2]['observed']['applied'] = [0, 1]
    elif damage == 'wrong-cut':
        rows[2]['observed']['snapshot']['asOfSeq'] = 0
    elif damage == 'wrong-identity':
        rows[3]['observed']['document']['record']['identity']['createdAt'] = 8
    elif damage == 'wrong-version':
        rows[5]['observed']['document']['record']['rows']['controlled/count']['ver'] = 0
    else:
        rows[0]['observed']['document']['record']['rows']['controlled/count']['seq'] = False
    with pytest.raises(ValueError):
        validate_observations(rows)


@pytest.mark.parametrize('damage', ['missing', 'relative-root', 'foreign-module', 'python', 'weak-python'])
def test_cache_runtime_requires_complete_observations_and_exact_embedded_product(tmp_path, damage):
    report = {'observations': expected(), 'root': str(tmp_path), 'module': str(tmp_path / 'dsh/__init__.py'), 'python': [3, 8, 10]}
    validate_runtime(report)
    if damage == 'missing':
        del report['observations']
    elif damage == 'relative-root':
        report['root'] = 'relative'
    elif damage == 'foreign-module':
        report['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    elif damage == 'python':
        report['python'] = [3, 9, 0]
    else:
        report['python'] = ['3', '8', '10']
    with pytest.raises(ValueError):
        validate_runtime(report)
