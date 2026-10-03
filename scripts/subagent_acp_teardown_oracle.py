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
from scripts.oracles.subagent_acp_teardown_python import NAMES, RAW, public_observation


INPUTS = ['scripts/subagent_acp_teardown_oracle.py', 'scripts/oracles/subagent_acp_teardown_python.py',
    'scripts/oracles/subagent_acp_teardown.probe.spec.ts', 'scripts/oracles/vitest.subagent-acp-teardown-probe.config.mts',
    'scripts/oracles/subagent_acp_peer.py', 'scripts/oracles/acp-sdk-resolution.mjs',
    'scripts/oracles/official/package-lock.json', 'dsh/subagent/acp.py', 'dsh/subprocess/local.py',
    'dsh/subprocess/types.py', 'dsh/subprocess/service.py', 'dsh/acp/rpc.py', 'dsh/core/abort.py',
    'dsh/cordis/errors.py', 'tests/test_subagent_acp_teardown_source.py',
    'tests/test_subagent_acp_dispose_cancellation.py', 'tests/test_subagent_acp_teardown_observer.py',
    'reference/packages/subagent/subagent-acp/src/run.ts',
    'reference/packages/subagent/subagent/src/out-of-process.ts',
    'reference/packages/subprocess/subprocess-local/src/spawn.ts']


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':'))


def expected(workspace):
    startup = {'name': 'AcpRunFailure', 'message': 'subagent-acp: Subagent failure (provider: ACP; stage: new-session; category: protocol)',
        'cause': 'ACP child published without a session id'}
    cleanup = {'name': 'AcpRunFailure', 'message': 'subagent-acp: Subagent failure (provider: ACP; stage: teardown; category: process-exit; exit code: 1)', 'cause': RAW}
    rows = []
    for name in NAMES:
        wire = [{'method': 'initialize', 'params': {'protocolVersion': 1, 'clientCapabilities': {}}},
            {'method': 'session/new', 'params': {'cwd': str(workspace), 'mcpServers': []}}]
        observed = {'actualExit': 1, 'waits': 2, 'terminations': 1, 'listenerRemoved': True,
            'rawErrors': [RAW], 'wire': wire}
        if name in ('published-post-exit', 'throwing-error-sink'):
            wire.append({'method': 'session/prompt', 'params': {'sessionId': 'same-child-id',
                'prompt': [{'type': 'text', 'text': 'explicit child task'}]}})
            observed.update(result={'output': [{'type': 'text', 'text': 'child answer'}], 'stopReason': 'completed'},
                disposeFailure=cleanup, sameDisposeFailure=True)
        else:
            members = [startup, cleanup] if name == 'startup-post-exit' else [cleanup]
            observed['startFailure'] = {'name': 'AggregateError', 'message': '; '.join(member['message'] for member in members), 'errors': members}
            if name == 'startup-post-exit':
                observed['rawErrors'] = ['ACP child published without a session id', RAW]
        if name == 'throwing-error-sink':
            observed.update(actualExit=17, waits=0, terminations=0, rawErrors=['ACP connection closed'], disposeFailure=None)
            observed['result'].update(stopReason='error', diagnostic='Subagent failure (provider: ACP; stage: process; category: process-exit; exit code: 17)')
        rows.append({'name': name, 'observed': observed})
    return rows


def validate_observations(rows, workspace):
    if not isinstance(rows, list) or len(rows) != 4 or any(not isinstance(row, dict) or set(row) != {'name', 'observed'} for row in rows) or [row['name'] for row in rows] != list(NAMES):
        raise ValueError('Subprocess ACP teardown scenarios are missing, duplicated or reordered')
    for row in rows:
        observed = row['observed']
        if not isinstance(observed, dict) or not isinstance(observed.get('records'), list) or any(not isinstance(packet, dict) for packet in observed['records']):
            raise ValueError('Subprocess ACP teardown raw observations are missing')
        spawns = [packet['spawn'] for packet in observed['records'] if 'spawn' in packet]
        if len(spawns) != 1 or not isinstance(spawns[0], dict) or set(spawns[0]) != {'pid', 'cwd'} or type(spawns[0]['pid']) is not int or spawns[0]['pid'] <= 0 or spawns[0]['cwd'] != str(workspace):
            raise ValueError('Subprocess ACP teardown physical spawn ownership differs')
    if canonical([public_observation(row) for row in rows]) != canonical(expected(workspace)):
        raise ValueError('Subprocess ACP teardown safe facts, raw causes, memoization, protocol or exit observations differ')


def validate_runtime(report):
    if not isinstance(report, dict) or set(report) != {'observations', 'root', 'module', 'python'}:
        raise ValueError('Extracted subprocess ACP teardown runtime fields differ')
    if not isinstance(report['root'], str) or not isinstance(report['module'], str) or not Path(report['root']).is_absolute() or Path(report['module']).resolve() != (Path(report['root']) / 'dsh/__init__.py').resolve() or canonical(report['python']) != '[3,8,10]':
        raise ValueError('Subprocess ACP teardown runtime provenance differs')
    rows = report['observations']
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise ValueError('Subprocess ACP teardown runtime observations are missing')
    try:
        workspace = rows[0]['observed']['records'][0]['spawn']['cwd']
    except (IndexError, KeyError, TypeError) as error:
        raise ValueError('Subprocess ACP teardown workspace provenance is missing') from error
    if not isinstance(workspace, str) or not Path(workspace).is_absolute():
        raise ValueError('Subprocess ACP teardown workspace is not absolute')
    validate_observations(rows, Path(workspace))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'failed'}
    try:
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        actual = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
        dirty = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain'], encoding='utf-8').strip()
        if actual != target or dirty:
            raise ValueError('Subprocess ACP teardown reference differs from the clean pinned target')
        def hashes():
            return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}
        report.update(target_upstream=target, inputSha256=hashes())
        workspace = output.with_name(output.stem + '-runtime')
        workspace.mkdir()
        source, native = output.with_name(output.stem + '.source.json'), output.with_name(output.stem + '.native.json')
        env = dict(os.environ, SUBAGENT_ACP_TEARDOWN_WORKSPACE=str(workspace), SUBAGENT_ACP_TEARDOWN_OUTPUT=str(source),
            SUBAGENT_ACP_PYTHON=sys.executable, SUBAGENT_ACP_PEER=str(ROOT / 'scripts/oracles/subagent_acp_peer.py'))
        node = shutil.which('node')
        if node is None:
            raise ValueError('Subprocess ACP teardown source observations require Node')
        commands = [[node, '--expose-internals', str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'),
            'run', '--config', str(ROOT / 'scripts/oracles/vitest.subagent-acp-teardown-probe.config.mts')],
            [sys.executable, str(ROOT / 'scripts/oracles/subagent_acp_teardown_python.py'), str(workspace), str(native)]]
        for index, command in enumerate(commands):
            result = subprocess.run(command, cwd=str(ROOT), env=env, capture_output=True, timeout=90)
            output.with_name(output.stem + '.' + str(index) + '.log').write_bytes(result.stdout + result.stderr)
            if result.returncode:
                raise ValueError('Subprocess ACP teardown observation runner failed: ' + str(index))
        original = json.loads(source.read_text(encoding='utf-8'))
        runtime = json.loads(native.read_text(encoding='utf-8'))
        validate_observations(original, workspace)
        validate_runtime(runtime)
        if runtime['root'] != str(ROOT) or canonical([public_observation(row) for row in original]) != canonical([public_observation(row) for row in runtime['observations']]):
            raise ValueError('Subprocess ACP teardown actual source/native observations differ')
        if report['inputSha256'] != hashes():
            raise ValueError('Subprocess ACP teardown inputs changed during frozen observations')
        report.update(status='passed', cases=4, adaptations=['Only RPC ids and physical pid namespaces are abstracted; raw cause strings and wire packets are retained.'],
            scope='Actual original selected startup/published teardown failures and sink containment; no complete process tree or Win7 certification.')
    except Exception as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
