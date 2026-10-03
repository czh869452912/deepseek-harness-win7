import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.oracles.subagent_acp_python import public_observation


INPUTS = ['scripts/subagent_acp_oracle.py', 'scripts/subagent_acp_journey.py',
    'scripts/acp_permission_journey.py', 'scripts/acp_mcp_journey.py',
    'scripts/oracles/subagent_acp_python.py', 'scripts/oracles/subagent_acp.probe.spec.ts',
    'scripts/oracles/subagent_acp_peer.py', 'scripts/oracles/vitest.subagent-acp-probe.config.mts',
    'scripts/oracles/agent_signal.probe.spec.ts', 'scripts/oracles/agent_signal_python.py',
    'scripts/oracles/vitest.agent-signal-probe.config.mts', 'scripts/oracles/acp-sdk-resolution.mjs',
    'scripts/oracles/vitest.subagent-acp.config.mts', 'scripts/oracles/official/package.json',
    'scripts/oracles/official/package-lock.json', 'scripts/verify_release.py', 'scripts/verify_portable.py',
    'tests/test_subagent_acp_observer.py', 'tests/test_subagent_acp.py', 'tests/test_subagent_acp_source.py',
    'tests/test_agent_signal_source.py', 'tests/test_subagent_acp_signal.py', 'tests/test_subagent_acp_consumer.py',
    'tests/test_subagent_acp_process.py', 'dsh/subagent/acp.py', 'dsh/subagent/runtime.py',
    'dsh/subagent/canonical_tools.py', 'dsh/subprocess/local.py', 'dsh/subprocess/types.py',
    'dsh/subprocess/service.py', 'dsh/core/abort.py', 'dsh/core/agent.py', 'dsh/core/agent_loop.py',
    'dsh/core/tool_calls.py', 'dsh/core/tools.py', 'dsh/acp/rpc.py', 'dsh/cordis/schema.py',
    'dsh/cordis/errors.py', 'dsh/boot/plugin_registry.py',
    'reference/packages/subagent/subagent-acp/src/run.ts',
    'reference/packages/subagent/subagent-acp/src/index.ts',
    'reference/packages/subprocess/subprocess-local/src/spawn.ts',
    'reference/packages/core/agent-loop/src/agent.ts']
NAMES = ['stop-' + reason for reason in ('end_turn', 'max_tokens', 'refusal', 'cancelled', 'max_turn_requests')] + [
    'permission-' + policy + '-' + reason for policy in ('reject', 'allow')
    for reason in ('end_turn', 'refusal', 'max_turn_requests')] + [
    'no-allow', 'unknown-kind', 'cwd', 'ambient', 'explicit', 'flush', 'cancel-noncooperative',
    'crash-initialize', 'crash-after-chunk', 'missing-session', 'spawn-failure']


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':'))


def expected_process():
    return {'parentRequests': 2, 'childRequests': 2, 'fileWork': True, 'childReaped': True,
        'parentContextIsolated': True, 'parentClosed': True,
        'scope': 'Actual canonical parent ACP, subprocess ACP child and file/model consumers; local endpoint only.'}


def validate_process(value):
    if canonical(value) != canonical(expected_process()):
        raise ValueError('Actual parent/subprocess ACP file/model consumer ownership differs')


def expected_signals():
    cause = {'kind': 'user', 'detail': 'actual cancellation reason'}
    reasons = [{'kind': 'aborted', 'reason': cause}, {'kind': 'completed'}]
    return {'tools': {'signalCount': 2, 'initiallyActive': True, 'firstAborted': True,
        'reason': cause, 'notifications': [cause], 'nextDistinct': True, 'nextActive': True,
        'modelRequests': 3, 'turnReasons': reasons},
        'admission': {'status': 'idle', 'modelRequests': 1, 'turnReasons': reasons},
        'queued': {'signalCount': 2, 'sameSignal': False, 'active': True, 'modelRequests': 4,
                   'turnReasons': [{'kind': 'completed'}, {'kind': 'completed'}]}}


def validate_signals(value):
    if canonical(value) != canonical(expected_signals()):
        raise ValueError('Actual model/tool cancellation generations or driver recovery differ')


def expected_result(name, workspace):
    text, reason, diagnostic = 'child answer', 'completed', None
    if name.startswith('stop-'):
        stop = name[len('stop-'):]
        reason = {'end_turn': 'completed', 'max_tokens': 'max-tokens', 'refusal': 'refusal',
                  'cancelled': 'aborted', 'max_turn_requests': 'error'}[stop]
        if stop == 'max_turn_requests':
            diagnostic = 'Subagent failure (provider: ACP; stage: prompt; category: remote-limit; stop reason: max_turn_requests)'
    elif name.startswith('permission-'):
        unused, policy, stop = name.split('-', 2)
        reason = {'end_turn': 'completed', 'refusal': 'refusal', 'max_turn_requests': 'error'}[stop]
        if stop != 'end_turn':
            diagnostic = 'ACP unattended decision (policy: {}; request: execute; decision: {})'.format(policy, 'allowed' if policy == 'allow' else 'denied')
            if stop == 'max_turn_requests':
                diagnostic = 'Subagent failure (provider: ACP; stage: prompt; category: remote-limit; stop reason: max_turn_requests)\n' + diagnostic
    elif name == 'no-allow':
        text, reason = '', 'aborted'
        diagnostic = 'ACP unattended decision (policy: allow; request: unknown; decision: denied)'
    elif name == 'unknown-kind':
        reason = 'refusal'
        diagnostic = 'ACP unattended decision (policy: reject; request: unknown; decision: denied)'
    elif name == 'cwd':
        text = str(workspace) + '\n' + str(workspace)
    elif name == 'ambient':
        text = '<AMBIENT_SECRET unset>'
    elif name == 'explicit':
        text = 'child-owned'
    elif name == 'cancel-noncooperative':
        reason = 'aborted'
    elif name == 'crash-after-chunk':
        reason = 'error'
        diagnostic = 'Subagent failure (provider: ACP; stage: process; category: process-exit; exit code: 17)'
    result = {'output': [{'type': 'text', 'text': text}] if text else [], 'stopReason': reason}
    if diagnostic is not None:
        result['diagnostic'] = diagnostic
    return result


def expected_configurations(workspace):
    defaults = {'providerName': 'acp', 'command': 'fixture', 'args': [], 'permission': 'reject',
        'env': {}, 'disposeEofGraceMs': 6000, 'disposeGraceMs': 3000}
    capabilities = {'agentOptions': False, 'outputSchema': False, 'depthLimit': False, 'toolFilter': False, 'persona': False}
    def configured(input_value):
        return {'input': input_value, 'result': {'config': dict(defaults, **input_value),
            'name': 'acp', 'capabilities': capabilities, 'inheritsParentContext': False}}
    def rejected(input_value, message):
        return {'input': input_value, 'error': {'name': 'Error', 'message': 'subagent-acp: ' + message}}
    return [configured({'command': 'fixture'}),
        rejected({'command': 'fixture', 'disposeGraceMs': 0}, 'disposeGraceMs must be a positive finite number no greater than 2147483647'),
        rejected({'command': 'fixture', 'disposeEofGraceMs': 2147483648}, 'disposeEofGraceMs must be a positive finite number no greater than 2147483647'),
        rejected({'command': 'fixture', 'cwd': ''}, 'config cwd must not be empty — omit the key to inherit the parent session cwd'),
        configured({'command': 'fixture', 'cwd': str(workspace)}), configured({'command': 'fixture', 'disposeGraceMs': 0.5})]


def expected_wire(name, workspace):
    if name == 'spawn-failure':
        return []
    packets = [{'method': 'initialize', 'params': {'protocolVersion': 1, 'clientCapabilities': {}}}]
    if name == 'crash-initialize':
        return packets
    packets.append({'method': 'session/new', 'params': {'cwd': str(workspace), 'mcpServers': []}})
    if name == 'missing-session':
        return packets
    packets.append({'method': 'session/prompt', 'params': {'sessionId': 'same-child-id',
        'prompt': [{'type': 'text', 'text': 'explicit child task'}]}})
    if name.startswith('permission-') or name in ('no-allow', 'unknown-kind', 'cancel-noncooperative'):
        outcome = {'outcome': 'selected', 'optionId': 'first'} if name.startswith('permission-allow-') else {'outcome': 'cancelled'}
        packets.append({'result': {'outcome': outcome}})
    if name == 'cancel-noncooperative':
        packets.append({'method': 'session/cancel', 'params': {'sessionId': 'same-child-id'}})
    return packets


def validate_runtime(value, workspace):
    if not isinstance(value, dict) or set(value) != {'rows', 'configurations'}:
        raise ValueError('Subprocess ACP raw observation fields differ')
    rows = value['rows']
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows) or [row.get('name') for row in rows] != NAMES:
        raise ValueError('Subprocess ACP declared runtime cases are missing, duplicated or reordered')
    configs = value['configurations']
    if not isinstance(configs, list) or len(configs) != 6 or any(not isinstance(row, dict) or 'input' not in row for row in configs) or len({canonical(row['input']) for row in configs}) != 6:
        raise ValueError('Subprocess ACP configuration observations are incomplete')
    if canonical(configs) != canonical(expected_configurations(workspace)):
        raise ValueError('Subprocess ACP configuration defaults, provider metadata or exact errors differ')
    for row in rows:
        if set(row) != {'name', 'scenario', 'observations'} or not isinstance(row['scenario'], dict) or row['scenario'].get('name') != row['name']:
            raise ValueError('Subprocess ACP scenario identity differs')
        observed = row['observations']
        if not isinstance(observed, dict):
            raise ValueError('Subprocess ACP observation is not an object')
        if observed.get('quiescent') is not True or type(observed.get('errorCount')) is not int:
            raise ValueError('Subprocess ACP failed to prove actual quiescence or host diagnostics')
        if not isinstance(observed.get('records'), list) or type(observed.get('spawned')) is not bool or type(observed.get('flushed')) is not bool:
            raise ValueError('Subprocess ACP process raw facts are incomplete')
        records = observed['records']
        if any(not isinstance(packet, dict) for packet in records):
            raise ValueError('Subprocess ACP raw packet is not an object')
        spawns = [packet['spawn'] for packet in records if 'spawn' in packet]
        spawned = row['name'] != 'spawn-failure'
        if len(spawns) != int(spawned) or any(not isinstance(spawn, dict) or set(spawn) != {'pid', 'cwd'} or type(spawn['pid']) is not int or spawn['pid'] <= 0 or spawn['cwd'] != str(workspace) for spawn in spawns):
            raise ValueError('Subprocess ACP raw process ownership differs')
        public = public_observation(observed)
        if canonical(public['wire']) != canonical(expected_wire(row['name'], workspace)):
            raise ValueError('Subprocess ACP actual protocol order, parameters or permission reply differs')
        expected_closes = 0 if row['name'] in ('spawn-failure', 'crash-initialize', 'crash-after-chunk', 'cancel-noncooperative') else 1
        if public['processFacts']['closes'] != expected_closes:
            raise ValueError('Subprocess ACP actual peer EOF observation differs')
        if row['name'] in ('crash-initialize', 'missing-session', 'spawn-failure'):
            if set(observed) != {'error', 'quiescent', 'exitCode', 'errorCount', 'records', 'spawned', 'flushed'}:
                raise ValueError('Unpublished subprocess ACP error shape differs')
            expected = {'crash-initialize': 'stage: initialize; category: process-exit; exit code: 11',
                'missing-session': 'stage: new-session; category: protocol',
                'spawn-failure': 'stage: process; category: process-start'}[row['name']]
            if canonical(observed['error']) != canonical({'name': 'AcpRunFailure',
                'message': 'subagent-acp: Subagent failure (provider: ACP; ' + expected + ')'}):
                raise ValueError('Unpublished subprocess ACP safe failure facts differ')
            if observed['errorCount'] != 1 or observed['spawned'] is not (row['name'] != 'spawn-failure'):
                raise ValueError('Unpublished subprocess ACP spawn/diagnostic facts differ')
        else:
            if set(observed) != {'result', 'idDistinct', 'localAgentAbsent', 'quiescent', 'exitCode', 'errorCount', 'records', 'spawned', 'flushed'}:
                raise ValueError('Published subprocess ACP result fields differ')
            if observed['idDistinct'] is not True or observed['localAgentAbsent'] is not True or observed['spawned'] is not True:
                raise ValueError('Subprocess ACP run publication or parent namespace identity differs')
            result = observed['result']
            if not isinstance(result, dict) or set(result) not in ({'output', 'stopReason'}, {'output', 'stopReason', 'diagnostic'}):
                raise ValueError('Subprocess ACP resolved result shape differs')
            if result['stopReason'] not in ('completed', 'aborted', 'max-tokens', 'refusal', 'error') or not isinstance(result['output'], list):
                raise ValueError('Subprocess ACP stop/output vocabulary differs')
            if any(set(block) != {'type', 'text'} or block['type'] != 'text' or not isinstance(block['text'], str) for block in result['output']):
                raise ValueError('Subprocess ACP leaked non-assistant or malformed output')
            if 'diagnostic' in result and (not isinstance(result['diagnostic'], str) or 'untrusted' in result['diagnostic'] or 'private-' in result['diagnostic']):
                raise ValueError('Subprocess ACP unsafe or malformed model diagnostic')
            if canonical(result) != canonical(expected_result(row['name'], workspace)):
                raise ValueError('Subprocess ACP declared complete result differs: ' + row['name'])
            if observed['errorCount'] != (1 if row['name'] == 'crash-after-chunk' else 0):
                raise ValueError('Subprocess ACP Host error observation count differs')
        exit_code = {'crash-initialize': 11, 'crash-after-chunk': 17, 'spawn-failure': None,
            'cancel-noncooperative': 1 if os.name == 'nt' else None}.get(row['name'], 0)
        if canonical(observed['exitCode']) != canonical(exit_code):
            raise ValueError('Subprocess ACP actual process exit outcome differs')
        if row['name'] == 'flush' and observed['flushed'] is not True:
            raise ValueError('Subprocess ACP EOF flush was not observed')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'runner-error'}
    try:
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        original = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
        dirty = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain'], encoding='utf-8').strip()
        if original != target or dirty:
            raise ValueError('Subprocess ACP reference differs from the clean pinned target')
        sdk = json.loads((ROOT / 'scripts/oracles/official/node_modules/@agentclientprotocol/sdk/package.json').read_text(encoding='utf-8'))
        if sdk['version'] != '1.4.0':
            raise ValueError('Subprocess ACP source SDK differs from the pinned dependency')
        def hashes():
            return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}
        report.update(target_upstream=target, inputSha256=hashes())
        workspace = output.with_name(output.stem + '-runtime')
        workspace.mkdir()
        node = shutil.which('node')
        if node is None:
            raise ValueError('Subprocess ACP source observations require Node')
        source = output.with_name(output.stem + '.source.json')
        native = output.with_name(output.stem + '.native.json')
        signal_source = output.with_name(output.stem + '.signals-source.json')
        signal_native = output.with_name(output.stem + '.signals-native.json')
        env = dict(os.environ, AMBIENT_SECRET='private-parent-secret', SUBAGENT_ACP_WORKSPACE=str(workspace),
            SUBAGENT_ACP_PYTHON=sys.executable, SUBAGENT_ACP_PEER=str(ROOT / 'scripts/oracles/subagent_acp_peer.py'),
            SUBAGENT_ACP_OUTPUT=str(source), AGENT_SIGNAL_OUTPUT=str(signal_source))
        commands = [[node, '--expose-internals', str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'),
            'run', '--config', str(ROOT / 'scripts/oracles/vitest.subagent-acp-probe.config.mts')],
            [sys.executable, str(ROOT / 'scripts/oracles/subagent_acp_python.py'), str(workspace), str(source), str(native)],
            [node, '--expose-internals', str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'),
             'run', '--config', str(ROOT / 'scripts/oracles/vitest.agent-signal-probe.config.mts')],
            [sys.executable, str(ROOT / 'scripts/oracles/agent_signal_python.py'), str(signal_native)]]
        for index, command in enumerate(commands):
            completed = subprocess.run(command, cwd=str(ROOT), env=env, capture_output=True, timeout=90)
            output.with_name(output.stem + '.' + str(index) + '.log').write_bytes(completed.stdout + completed.stderr)
            if completed.returncode != 0:
                raise ValueError('Subprocess ACP source/native runner failed: ' + str(index))
        source_data = json.loads(source.read_text(encoding='utf-8'))
        native_data = json.loads(native.read_text(encoding='utf-8'))
        for data in (source_data, native_data):
            validate_runtime(data, workspace)
        if canonical(source_data['configurations']) != canonical(native_data['configurations']):
            raise ValueError('Subprocess ACP actual configuration/provider fields differ')
        for source_row, native_row in zip(source_data['rows'], native_data['rows']):
            if canonical(public_observation(source_row['observations'])) != canonical(public_observation(native_row['observations'])):
                raise ValueError('Subprocess ACP actual wire/output/process facts differ: ' + source_row['name'])
        for path in (signal_source, signal_native):
            validate_signals(json.loads(path.read_text(encoding='utf-8')))
        if hashes() != report['inputSha256']:
            raise ValueError('Subprocess ACP inputs changed during frozen observations')
        report.update(status='passed', runtimeCases=22, configurationCases=6, signalCases=3,
            adaptations=['Protocol request ids and process/parent run identities have separate namespaces; raw observations are retained.'],
            scope='Selected actual original ACP subprocess, safe diagnostics and model/tool cancellation; no paid endpoint, complete subprocess tree or Win7 certification.')
    except Exception as error:
        report.update(status='failed', error=str(error))
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
