import copy

import pytest

from scripts.subagent_acp_teardown_oracle import expected, validate_observations, validate_runtime


def negative_fixture(workspace):
    rows = copy.deepcopy(expected(workspace))
    for row in rows:
        observed = row['observed']
        observed['records'] = [{'spawn': {'pid': 123, 'cwd': str(workspace)}}] + observed.pop('wire')
    return rows


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'reordered', 'weak-listener', 'leaked-listener',
    'changed-exit', 'lost-exit-facts', 'lost-startup-member', 'unsafe-message', 'lost-host-cause',
    'repeat-error', 'recreated-error', 'repeat-termination', 'invented-wait', 'wrong-protocol', 'no-spawn', 'fake-pid',
    'wrong-cwd', 'wrong-result', 'sink-overrides-result'])
def test_teardown_observer_rejects_identity_error_aggregate_and_physical_exit_counterexamples(tmp_path, damage):
    value = negative_fixture(tmp_path)
    validate_observations(value, tmp_path)
    first = value[0]['observed']
    startup = value[1]['observed']['startFailure']
    if damage == 'missing':
        value.pop()
    elif damage == 'duplicate':
        value[-1] = copy.deepcopy(value[0])
    elif damage == 'reordered':
        value[0], value[1] = value[1], value[0]
    elif damage == 'weak-listener':
        first['listenerRemoved'] = 1
    elif damage == 'leaked-listener':
        first['listenerRemoved'] = False
    elif damage == 'changed-exit':
        first['actualExit'] = 0
    elif damage == 'lost-exit-facts':
        startup['errors'][1]['message'] = 'subagent-acp: Subagent failure (provider: ACP; stage: teardown; category: unknown)'
    elif damage == 'lost-startup-member':
        startup['errors'].pop(0)
    elif damage == 'unsafe-message':
        first['disposeFailure']['message'] += ' SECRET_TOKEN'
    elif damage == 'lost-host-cause':
        del first['disposeFailure']['cause']
    elif damage == 'repeat-error':
        first['rawErrors'] *= 2
    elif damage == 'recreated-error':
        first['sameDisposeFailure'] = False
    elif damage == 'repeat-termination':
        first['terminations'] = 2
    elif damage == 'invented-wait':
        first['waits'] = True
    elif damage == 'wrong-protocol':
        first['records'][2]['params']['mcpServers'] = ['parent']
    elif damage == 'no-spawn':
        first['records'].pop(0)
    elif damage == 'fake-pid':
        first['records'][0]['spawn']['pid'] = True
    elif damage == 'wrong-cwd':
        first['records'][0]['spawn']['cwd'] = 'foreign'
    elif damage == 'wrong-result':
        first['result']['stopReason'] = 'error'
    else:
        value[-1]['observed']['result'] = {'output': [], 'stopReason': 'completed'}
    with pytest.raises(ValueError):
        validate_observations(value, tmp_path)


@pytest.mark.parametrize('damage', ['module', 'python', 'weak-python', 'root', 'missing', 'empty', 'workspace'])
def test_teardown_runtime_requires_actual_embedded_provenance_and_complete_raw_observations(tmp_path, damage):
    value = {'observations': negative_fixture(tmp_path), 'root': str(tmp_path),
        'module': str(tmp_path / 'dsh/__init__.py'), 'python': [3, 8, 10]}
    validate_runtime(value)
    if damage == 'module':
        value['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    elif damage == 'python':
        value['python'] = [3, 9, 10]
    elif damage == 'weak-python':
        value['python'] = ['3', '8', '10']
    elif damage == 'root':
        value['root'] = 'relative'
    elif damage == 'missing':
        del value['observations']
    elif damage == 'empty':
        value['observations'] = []
    else:
        value['observations'][0]['observed']['records'][0]['spawn']['cwd'] = 'relative'
    with pytest.raises(ValueError):
        validate_runtime(value)
