import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
MODES = ['absent', 'catalog', 'unlisted', 'defaults', 'outage', 'serialized', 'pin', 'updates']
FIELDS = {
    'absent': {'options', 'snapshot', 'errors', 'calls'},
    'catalog': {'initial', 'changed', 'snapshot'},
    'unlisted': {'options', 'snapshot'},
    'defaults': {'defaults'},
    'outage': {'initial', 'unavailable', 'restored', 'snapshot'},
    'serialized': {'blocked', 'rejected', 'next', 'calls', 'snapshot'},
    'pin': {'pinned', 'wrongTurn', 'released', 'future'},
    'updates': {'assistant', 'calls', 'result'},
}


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def options_state(options, route, effort=None, reasoning=True):
    require(isinstance(options, list) and len(options) == (2 if reasoning else 1), 'missing model/config state')
    require([option['id'] for option in options] == (['model', 'reasoning_effort'] if reasoning else ['model']), 'incorrect option order')
    require(options[0]['currentValue'] == route and options[0]['type'] == 'select', 'lost exact model route')
    groups = options[0]['options']
    require(groups and all(group['options'] for group in groups), 'empty model catalog observation')
    choices = [option['value'] for group in groups for option in group['options']]
    require(route in choices and len(choices) == len(set(choices)), 'missing or duplicated route choice')
    for choice in choices:
        decoded = json.loads(choice)
        require(isinstance(decoded, list) and len(decoded) == 2 and all(isinstance(part, str) for part in decoded), 'model selector lost full route identity')
    if reasoning:
        require(options[1]['currentValue'] == effort and options[1]['type'] == 'select', 'incorrect reasoning state')
        values = [option['value'] for option in options[1]['options']]
        require(values == (['', 'low', 'high'] if effort == '' else ['low', 'high']) or
                values == ['', 'low', 'high'] and effort == 'low', 'missing reasoning choices')


def validate_observations(rows):
    require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows) and
            [row.get('mode') for row in rows] == MODES, 'missing, duplicate or unexpected observations')
    for row in rows:
        require(set(row) == FIELDS[row['mode']] | {'mode'}, 'incomplete or unexpected observation fields')
    absent, catalog, unlisted, defaults, outage, serialized, pin, updates = rows
    require(absent['options'] == [] and absent['snapshot'] is None and absent['calls'] == [] and
            absent['errors'] == ['model requires a select value', 'this session has no model selection'], 'absent route was not rejected truthfully')
    options_state(catalog['initial'], '["mock","first"]', 'high')
    options_state(catalog['changed'], '["other","next"]', 'high')
    require(catalog['snapshot'] == {'provider': 'other', 'model': 'next'}, 'implicit provider default became Agent-owned')
    options_state(unlisted['options'], '["private","模型\\\""]', 'high')
    require(unlisted['snapshot'] == {'provider': 'private', 'model': '模型"'}, 'unlisted exact route was dropped')
    require(isinstance(defaults['defaults'], list) and len(defaults['defaults']) == 2, 'missing default variants')
    for index, variant in enumerate(defaults['defaults']):
        require(set(variant) == {'providerDefault', 'initial', 'rejected', 'changed', 'reset', 'snapshot'} and
                variant['providerDefault'] is (index == 0), 'missing provider-default identity')
        effort = '' if index == 0 else 'high'
        options_state(variant['initial'], '["mock","first"]', effort)
        options_state(variant['changed'], '["mock","first"]', 'low')
        options_state(variant['reset'], '["mock","first"]', effort)
        require(variant['rejected'] == 'unknown reasoning effort for mock/first: extreme', 'invalid effort was not rejected')
        expected = {'provider': 'mock', 'model': 'first'}
        if index == 1:
            expected['reasoningEffort'] = 'high'
        require(variant['snapshot'] == expected, 'reset lost provider-default ownership')
    options_state(outage['initial'], '["mock","first"]', 'high')
    options_state(outage['unavailable'], '["mock","first"]', reasoning=False)
    options_state(outage['restored'], '["mock","first"]', 'high')
    require(outage['snapshot'] == {'provider': 'mock', 'model': 'first'}, 'outage altered future selection')
    require(serialized['blocked'] is True and serialized['rejected'] == 'unknown model option: invalid', 'mutations did not serialize after failure')
    options_state(serialized['next'], '["mock","first"]', 'low')
    selected = {'provider': 'mock', 'model': 'first', 'reasoningEffort': 'low'}
    require(serialized['snapshot'] == selected and serialized['calls'] == [
        {'provider': 'mock', 'model': 'first'}, selected, selected], 'mutation predecessor or successor was lost')
    require(pin['pinned'] == pin['wrongTurn'] == {'provider': 'mock', 'model': 'first'} and
            pin['released'] == pin['future'] == {'provider': 'other', 'model': 'next'}, 'turn pin or detached identity was lost')
    require(isinstance(updates['assistant'], list) and [item['sessionUpdate'] for item in updates['assistant']] == [
        'agent_thought_chunk', 'agent_message_chunk', 'agent_message_chunk', 'usage_update'], 'assistant output order was lost')
    require(updates['assistant'][:3] == [
        {'sessionUpdate': 'agent_thought_chunk', 'messageId': 'message-1', 'content': {'type': 'text', 'text': 'thought'}},
        {'sessionUpdate': 'agent_message_chunk', 'messageId': 'message-1', 'content': {'type': 'text', 'text': 'answer'}},
        {'sessionUpdate': 'agent_message_chunk', 'messageId': 'message-1', 'content': {'type': 'image', 'data': 'aW1hZ2U=', 'mimeType': 'image/png'}}], 'assistant content fields were lost')
    usage = updates['assistant'][3]
    require(set(usage) == {'sessionUpdate', 'used', 'size'} and type(usage['used']) is int and
            type(usage['size']) is int and usage['used'] == 7 and usage['size'] == 100, 'real usage/capacity was lost')
    expected_calls = [dict(sessionUpdate='tool_call', toolCallId='call', title='echo', kind='other',
                         status='in_progress', rawInput=value) for value in ['{', 'NaN', 'Infinity', None, {'value': [1, '中文']}]]
    require(json.dumps(updates['calls'], sort_keys=True) == json.dumps(expected_calls, sort_keys=True), 'raw JSON input or tool status was lost')
    require(updates['result'] == {'sessionUpdate': 'tool_call_update', 'toolCallId': 'call', 'status': 'failed', 'content': [
        {'type': 'content', 'content': {'type': 'text', 'text': 'failed'}},
        {'type': 'content', 'content': {'type': 'image', 'data': 'aW1hZ2U=', 'mimeType': 'image/png'}}]}, 'supplemental result fields were lost')


def main():
    parser = argparse.ArgumentParser(description='Compare eight declared model/config/update projections against pinned ACP source.')
    parser.add_argument('--output', type=Path, default=ROOT / '.goose/out/acp-model-output-paired.json')
    output = parser.parse_args().output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'runner-error', 'cases': []}
    try:
        def reference_git(*arguments):
            return subprocess.check_output(['git', '-C', str(ROOT / 'reference')] + list(arguments), encoding='utf-8').strip()
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        require(reference_git('rev-parse', 'HEAD') == target and not reference_git('status', '--porcelain'), 'reference differs from target')
        inputs = ['dsh/acp/' + name + '.py' for name in ('model_control', 'content', 'updates', 'session_runtime', 'server')]
        inputs += ['scripts/acp_model_output_oracle.py', 'scripts/oracles/acp_model_output.probe.spec.ts',
                   'dsh/core/agent_loop.py', 'dsh/core/model_selection.py', 'dsh/llm/llm_service.py',
                   'scripts/oracles/acp_model_output_python.py', 'scripts/oracles/vitest.acp-model-output-probe.config.mts',
                   'scripts/oracles/vitest.acp.config.mts', 'scripts/oracles/acp-sdk-resolution.mjs',
                   'scripts/oracles/official/package-lock.json', 'tests/test_acp_model_output.py']
        def hashes():
            return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in inputs}
        report.update(target_upstream=target, inputSha256=hashes())
        paths = [output.with_suffix('.ts.json'), output.with_suffix('.python.json')]
        environment = dict(os.environ, ACP_MODEL_OUTPUT=str(paths[0]))
        commands = [['node', '--expose-internals', 'scripts/oracles/official/node_modules/vitest/vitest.mjs',
                     'run', '--config', 'scripts/oracles/vitest.acp-model-output-probe.config.mts'],
                    [sys.executable, 'scripts/oracles/acp_model_output_python.py', str(paths[1])]]
        observations = []
        for index, command in enumerate(commands):
            paths[index].unlink(missing_ok=True)
            completed = subprocess.run(command, cwd=str(ROOT), env=environment, capture_output=True, timeout=90)
            output.with_suffix('.%d.log' % index).write_bytes(completed.stdout + completed.stderr)
            require(completed.returncode == 0, 'runner %d failed (%d)' % (index, completed.returncode))
            rows = json.loads(paths[index].read_text(encoding='utf-8'))
            validate_observations(rows)
            observations.append(rows)
        report['cases'] = [{'mode': left['mode'], 'status': 'matched' if json.dumps(left, sort_keys=True) ==
                            json.dumps(right, sort_keys=True) else 'different', 'upstream': left, 'python': right}
                           for left, right in zip(*observations)]
        report['status'] = 'matched' if all(row['status'] == 'matched' for row in report['cases']) else 'different'
        require(report['inputSha256'] == hashes(), 'observation inputs changed during the run')
        require(reference_git('rev-parse', 'HEAD') == target and not reference_git('status', '--porcelain'), 'reference changed during observation')
        report['scope'] = 'Eight exact semantic model/control/update projections. Canonical prompt/close/history ownership is tested separately. Complete SDK wire errors, stdio, MCP and real remote providers are outside this contract.'
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report.update(status='runner-error', error=str(error))
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return {'matched': 0, 'different': 1, 'runner-error': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
