import pytest

from scripts.session_corpus_read_oracle import expected, validate_observations, validate_runtime


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'reorder', 'message', 'cause', 'foreign-cause',
    'conflict', 'signal', 'live-inspection', 'duplicate-inspection', 'peak', 'early-settlement',
    'queued-after-abort', 'projection-order', 'clone', 'title-mutable', 'weak-count'])
def test_corpus_read_observer_rejects_lost_source_or_batch_lifetimes(damage):
    rows = expected()
    validate_observations(rows)
    by_name = {row['name']: row['observed'] for row in rows}
    if damage == 'missing':
        rows.pop()
    elif damage == 'duplicate':
        rows[-1] = rows[0]
    elif damage == 'reorder':
        rows.reverse()
    elif damage == 'message':
        by_name['load-missing-record']['error']['message'] = 'session not found: a'
    elif damage == 'cause':
        by_name['load-failure']['error']['sameCause'] = False
    elif damage == 'foreign-cause':
        by_name['load-foreign-failure']['error']['sameCause'] = False
    elif damage == 'conflict':
        by_name['load-header-conflict']['error']['code'] = 'SESSION_QUERY_PERSISTENCE_FAILED'
    elif damage == 'signal':
        by_name['batch-concurrency']['counters']['signals'] = False
    elif damage == 'live-inspection':
        by_name['load-live']['counters']['inspections'] = ['a']
    elif damage == 'duplicate-inspection':
        by_name['batch-mixed-duplicates']['counters']['inspections'] = ['b', 'b']
    elif damage == 'peak':
        by_name['batch-concurrency']['counters']['peak'] = 3
    elif damage == 'early-settlement':
        by_name['batch-abort-drain']['settledBeforeDrain'] = True
    elif damage == 'queued-after-abort':
        by_name['batch-abort-drain']['counters']['inspections'].append('c')
    elif damage == 'projection-order':
        by_name['batch-concurrency']['projectBeforeNext'] = False
    elif damage == 'clone':
        by_name['load-cold']['detached'] = False
    elif damage == 'title-mutable':
        by_name['batch-clone']['titleMutationRefused'] = False
    else:
        by_name['load-live']['counters']['lists'] = False
    with pytest.raises(ValueError):
        validate_observations(rows)


@pytest.mark.parametrize('damage', ['missing', 'relative-root', 'foreign-module', 'python', 'weak-python'])
def test_corpus_read_runtime_requires_complete_observations_and_exact_product(tmp_path, damage):
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
