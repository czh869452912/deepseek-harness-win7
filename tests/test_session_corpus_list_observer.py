import pytest

from scripts.session_corpus_list_oracle import expected, validate_observations, validate_runtime


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'reorder', 'message', 'code', 'cause',
    'foreign-cause', 'abort-identity', 'signal', 'listing-count', 'live-precedence', 'durable-precedence',
    'duplicate-order', 'clone', 'weak-count'])
def test_corpus_list_observer_rejects_lost_signal_error_or_source_ownership(damage):
    rows = expected()
    validate_observations(rows)
    if damage == 'missing':
        rows.pop()
    elif damage == 'duplicate':
        rows[-1] = rows[0]
    elif damage == 'reorder':
        rows.reverse()
    elif damage == 'message':
        rows[4]['observed']['error']['message'] = 'session source headers conflict'
    elif damage == 'code':
        rows[5]['observed']['error']['code'] = 'SESSION_QUERY_SESSION_NOT_FOUND'
    elif damage == 'cause':
        rows[5]['observed']['error']['sameCause'] = False
    elif damage == 'foreign-cause':
        rows[6]['observed']['error']['sameCause'] = False
    elif damage == 'abort-identity':
        rows[8]['observed']['error']['sameFailure'] = False
    elif damage == 'signal':
        rows[9]['observed']['counters']['sameSignal'] = False
    elif damage == 'listing-count':
        rows[0]['observed']['counters']['lists'] = 1
    elif damage == 'live-precedence':
        rows[1]['observed']['records'][0]['live'] = False
    elif damage == 'durable-precedence':
        rows[1]['observed']['records'][0]['persisted'] = False
    elif damage == 'duplicate-order':
        rows[3]['observed']['records'][0]['createdAt'] = 9
    elif damage == 'clone':
        rows[11]['observed']['originalCwd'] = '/mutated'
    else:
        rows[0]['observed']['counters']['lists'] = False
    with pytest.raises(ValueError):
        validate_observations(rows)


@pytest.mark.parametrize('damage', ['missing', 'relative-root', 'foreign-module', 'python', 'weak-python'])
def test_corpus_list_runtime_requires_exact_product_provenance(tmp_path, damage):
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
