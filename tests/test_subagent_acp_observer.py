import copy
import os

import pytest

from scripts.subagent_acp_oracle import NAMES, expected_configurations, expected_process, expected_result, expected_signals, expected_wire, validate_process, validate_runtime, validate_signals


def negative_fixture(workspace):
    rows = []
    for name in NAMES:
        spawned = name != 'spawn-failure'
        records = [{'spawn': {'pid': 123, 'cwd': str(workspace)}}] if spawned else []
        records.extend(copy.deepcopy(expected_wire(name, workspace)))
        if name not in ('spawn-failure', 'crash-initialize', 'crash-after-chunk', 'cancel-noncooperative'):
            records.append({'closed': True})
        observed = {'quiescent': True, 'errorCount': 0, 'records': records,
            'spawned': spawned, 'flushed': name == 'flush', 'exitCode': 0}
        if name in ('crash-initialize', 'missing-session', 'spawn-failure'):
            detail = {'crash-initialize': 'stage: initialize; category: process-exit; exit code: 11',
                'missing-session': 'stage: new-session; category: protocol',
                'spawn-failure': 'stage: process; category: process-start'}[name]
            observed.update(error={'name': 'AcpRunFailure', 'message':
                'subagent-acp: Subagent failure (provider: ACP; ' + detail + ')'}, errorCount=1)
        else:
            observed.update(result=expected_result(name, workspace), idDistinct=True, localAgentAbsent=True)
        observed['exitCode'] = {'crash-initialize': 11, 'crash-after-chunk': 17, 'spawn-failure': None,
            'cancel-noncooperative': 1 if os.name == 'nt' else None}.get(name, 0)
        if name == 'crash-after-chunk':
            observed['errorCount'] = 1
        rows.append({'name': name, 'scenario': {'name': name}, 'observations': observed})
    return {'rows': rows, 'configurations': expected_configurations(workspace)}


@pytest.mark.parametrize('field', list(expected_process()))
@pytest.mark.parametrize('damage', ['missing', 'wrong-type', 'wrong-value'])
def test_actual_subagent_process_consumer_rejects_incomplete_or_fabricated_receipts(field, damage):
    value = expected_process()
    if damage == 'missing':
        del value[field]
    elif damage == 'wrong-type':
        value[field] = int(value[field]) if isinstance(value[field], bool) else str(value[field]) if isinstance(value[field], int) else None
    else:
        value[field] = False if isinstance(value[field], bool) else 0 if isinstance(value[field], int) else 'different scope'
    with pytest.raises(ValueError):
        validate_process(value)


@pytest.mark.parametrize('damage', ['missing-case', 'extra-case', 'reused-signal', 'lost-reason',
    'lost-notification', 'numeric-abort', 'inactive-next', 'dead-driver', 'queued-signal-reused',
    'queued-inactive', 'missing-turn', 'fabricated-requests'])
def test_actual_agent_signal_observer_rejects_cancellation_and_generation_regressions(damage):
    value = copy.deepcopy(expected_signals())
    if damage == 'missing-case':
        del value['admission']
    elif damage == 'extra-case':
        value['extra'] = {}
    elif damage == 'reused-signal':
        value['tools']['nextDistinct'] = False
    elif damage == 'lost-reason':
        value['tools']['reason'] = None
    elif damage == 'lost-notification':
        value['tools']['notifications'] = []
    elif damage == 'numeric-abort':
        value['tools']['firstAborted'] = 1
    elif damage == 'inactive-next':
        value['tools']['nextActive'] = False
    elif damage == 'dead-driver':
        value['admission']['status'] = 'running'
    elif damage == 'queued-signal-reused':
        value['queued']['sameSignal'] = True
    elif damage == 'queued-inactive':
        value['queued']['active'] = False
    elif damage == 'missing-turn':
        value['queued']['turnReasons'].pop()
    else:
        value['tools']['modelRequests'] = True
    with pytest.raises(ValueError):
        validate_signals(value)


@pytest.mark.parametrize('damage', ['missing-case', 'duplicate-case', 'reordered-case', 'missing-config',
    'duplicate-config', 'changed-default', 'invented-capability', 'parent-inheritance', 'lost-config-error',
    'unreaped', 'numeric-quiescence', 'reused-id', 'local-agent', 'empty-wire', 'wrong-cwd',
    'invented-pid', 'wrong-method', 'extra-parent-mcp', 'leaked-parent-prompt', 'unsafe-permission',
    'missing-eof', 'leaked-thought', 'wrong-stop', 'unsafe-diagnostic', 'wrong-exit',
    'lost-host-error', 'invented-spawn', 'missing-flush', 'unsafe-start-error'])
def test_subagent_runtime_observer_rejects_business_wire_and_process_counterexamples(tmp_path, damage):
    value = negative_fixture(tmp_path)
    validate_runtime(value, tmp_path)
    rows = {row['name']: row['observations'] for row in value['rows']}
    first = rows['stop-end_turn']
    if damage == 'missing-case':
        value['rows'].pop()
    elif damage == 'duplicate-case':
        value['rows'][-1] = copy.deepcopy(value['rows'][0])
    elif damage == 'reordered-case':
        value['rows'][0], value['rows'][1] = value['rows'][1], value['rows'][0]
    elif damage == 'missing-config':
        value['configurations'].pop()
    elif damage == 'duplicate-config':
        value['configurations'][-1] = copy.deepcopy(value['configurations'][0])
    elif damage == 'changed-default':
        value['configurations'][0]['result']['config']['permission'] = 'allow'
    elif damage == 'invented-capability':
        value['configurations'][0]['result']['capabilities']['persona'] = True
    elif damage == 'parent-inheritance':
        value['configurations'][0]['result']['inheritsParentContext'] = True
    elif damage == 'lost-config-error':
        del value['configurations'][1]['error']
    elif damage == 'unreaped':
        first['quiescent'] = False
    elif damage == 'numeric-quiescence':
        first['quiescent'] = 1
    elif damage == 'reused-id':
        first['idDistinct'] = False
    elif damage == 'local-agent':
        first['localAgentAbsent'] = False
    elif damage == 'empty-wire':
        first['records'] = []
    elif damage == 'wrong-cwd':
        first['records'][0]['spawn']['cwd'] = 'foreign'
    elif damage == 'invented-pid':
        first['records'][0]['spawn']['pid'] = True
    elif damage == 'wrong-method':
        first['records'][1]['method'] = 'session/prompt'
    elif damage == 'extra-parent-mcp':
        first['records'][2]['params']['mcpServers'] = [{'name': 'parent'}]
    elif damage == 'leaked-parent-prompt':
        first['records'][3]['params']['prompt'].append({'type': 'text', 'text': 'private-parent'})
    elif damage == 'unsafe-permission':
        rows['permission-reject-refusal']['records'][-2]['result']['outcome'] = {'outcome': 'selected', 'optionId': 'first'}
    elif damage == 'missing-eof':
        first['records'].pop()
    elif damage == 'leaked-thought':
        first['result']['output'].append({'type': 'thought', 'text': 'private-child'})
    elif damage == 'wrong-stop':
        rows['stop-max_tokens']['result']['stopReason'] = 'completed'
    elif damage == 'unsafe-diagnostic':
        rows['crash-after-chunk']['result']['diagnostic'] += ' private-path'
    elif damage == 'wrong-exit':
        rows['crash-after-chunk']['exitCode'] = 0
    elif damage == 'lost-host-error':
        rows['crash-initialize']['errorCount'] = 0
    elif damage == 'invented-spawn':
        rows['spawn-failure']['spawned'] = True
    elif damage == 'missing-flush':
        rows['flush']['flushed'] = False
    else:
        rows['missing-session']['error']['message'] += ' untrusted-sdk-message'
    with pytest.raises(ValueError):
        validate_runtime(value, tmp_path)
