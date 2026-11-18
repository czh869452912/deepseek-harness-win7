import pytest

from scripts.session_observation_read_oracle import expected, validate_observations, validate_runtime


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'reorder', 'message', 'code', 'cause',
    'raw-failure', 'foreign-cause', 'missing-close', 'double-close', 'unclosed-backend',
    'live-stat', 'duplicate-stat', 'none-projects', 'cursor', 'retained-cut', 'weak-count'])
def test_point_read_observer_rejects_hidden_errors_and_lost_ownership(damage):
    rows = expected()
    validate_observations(rows)
    if damage == 'missing':
        rows.pop()
    elif damage == 'duplicate':
        rows[-1] = rows[0]
    elif damage == 'reorder':
        rows.reverse()
    elif damage == 'message':
        rows[0]['observed']['error']['message'] = 'session not found: owned'
    elif damage == 'code':
        rows[1]['observed']['error']['code'] = 'SESSION_QUERY_PERSISTENCE_FAILED'
    elif damage == 'cause':
        rows[2]['observed']['error']['sameCause'] = False
    elif damage == 'raw-failure':
        rows[9]['observed']['error']['sameFailure'] = True
    elif damage == 'foreign-cause':
        rows[4]['observed']['error']['sameCause'] = False
    elif damage == 'missing-close':
        rows[8]['observed']['counters']['closes'] = 0
    elif damage == 'double-close':
        rows[9]['observed']['counters']['closes'] = 2
    elif damage == 'unclosed-backend':
        rows[10]['observed']['closesAfterFirst'] = 0
    elif damage == 'live-stat':
        rows[11]['observed']['counters']['stats'] = 1
    elif damage == 'duplicate-stat':
        rows[13]['observed']['counters']['stats'] = 2
    elif damage == 'none-projects':
        rows[14]['observed']['counters']['applied'] = 1
    elif damage == 'cursor':
        rows[15]['observed']['cut']['cursor'] = 0
    elif damage == 'retained-cut':
        rows[10]['observed']['retained']['cursor'] = 2
    else:
        rows[0]['observed']['counters']['stats'] = False
    with pytest.raises(ValueError):
        validate_observations(rows)


@pytest.mark.parametrize('damage', ['missing', 'relative-root', 'foreign-module', 'python', 'weak-python'])
def test_point_read_runtime_requires_complete_observations_and_exact_product(tmp_path, damage):
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
