import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.oracles.acp_permissions_python import RESPONSES

MODES = [mode for mode, response in RESPONSES]
IDENTITY = '00000000-0000-4000-8000-000000000001'
DEFECT_MODES = ('unknown-kind-allow', 'missing-kind-allow')
INPUTS = [
    'scripts/acp_permissions_oracle.py', 'scripts/oracles/acp_permissions_python.py',
    'scripts/oracles/acp_permissions.probe.spec.ts', 'scripts/oracles/vitest.acp-permissions-probe.config.mts',
    'scripts/oracles/vitest.acp.config.mts', 'scripts/oracles/acp-sdk-resolution.mjs',
    'scripts/oracles/official/package-lock.json', 'dsh/acp/server.py', 'dsh/acp/rpc.py',
    'dsh/acp/session_runtime.py', 'dsh/interaction/user_approval.py', 'dsh/core/tools.py',
    'dsh/core/abort.py', 'reference/packages/acp/acp/src/index.ts',
    'reference/packages/acp/acp/tests/harness.ts', 'reference/packages/acp/acp/tests/approval.spec.ts',
    'reference/packages/interaction/user-approval/src/index.ts',
    'migration/reviews/ACP-MALFORMED-PERMISSION-20261003.md',
]


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def expected_row(mode, response, original=False):
    dispatched = mode not in ('same-id-foreign', 'missing-call-id', 'pre-abort')
    outcome = {'allow': 'allowed-once', 'reject': 'rejected', 'unknown-option': 'rejected',
               'cancelled': 'cancelled', 'pre-abort': 'cancelled'}.get(mode, 'unavailable')
    if original and mode in DEFECT_MODES:
        outcome = 'allowed-once'
    request = {'sessionId': IDENTITY, 'toolCall': {'toolCallId': 'call-9'}, 'options': [
        {'optionId': 'allow-once', 'name': 'Allow once', 'kind': 'allow_once'},
        {'optionId': 'reject-once', 'name': 'Reject', 'kind': 'reject_once'}]}
    update = {'sessionId': IDENTITY, 'update': {'toolCallId': 'call-9', 'title': 'bash', 'kind': 'other',
        'status': 'in_progress', 'rawInput': {}, 'sessionUpdate': 'tool_call'}}
    return {'mode': mode, 'response': response, 'outcome': outcome, 'requests': [request] if dispatched else [],
        'updates': [update], 'updateBeforePermission': True if dispatched else None,
        'audit': {'types': ['approval/asked', 'approval/decided'], 'correlated': True, 'outcome': outcome}}


def validate_observations(rows, original=False):
    require(isinstance(rows, list) and [row.get('mode') for row in rows if isinstance(row, dict)] == MODES,
            'missing, duplicate or reordered permission observations')
    for row, (mode, response) in zip(rows, RESPONSES):
        require(json.dumps(row, sort_keys=True) == json.dumps(expected_row(mode, response, original), sort_keys=True),
                'incomplete or corrupted permission observation: ' + mode)


def reviewed_malformed_outcome_difference(source, native):
    mode = source.get('mode')
    if mode not in DEFECT_MODES or native.get('mode') != mode:
        return False
    response = dict(RESPONSES)[mode]
    return source == expected_row(mode, response, original=True) and native == expected_row(mode, response)


def classify(source, native):
    validate_observations(source, original=True)
    validate_observations(native)
    return [{'mode': left['mode'], 'status': 'matched' if left == right else
             'reviewed-original-defect' if reviewed_malformed_outcome_difference(left, right) else 'different',
             'upstream': copy.deepcopy(left), 'python': copy.deepcopy(right)} for left, right in zip(source, native)]


def main():
    parser = argparse.ArgumentParser(description='Observe exact ACP one-shot permissions and the narrowly reviewed source grant defect.')
    parser.add_argument('--output', required=True, type=Path)
    output = parser.parse_args().output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'runner-error', 'cases': []}
    try:
        def reference_git(*arguments):
            return subprocess.check_output(['git', '-C', str(ROOT / 'reference')] + list(arguments), encoding='utf-8').strip()
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        require(reference_git('rev-parse', 'HEAD') == target and not reference_git('status', '--porcelain'), 'reference differs from target')
        def hashes():
            return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}
        report.update(target_upstream=target, inputSha256=hashes())
        paths = [output.with_suffix('.ts.json'), output.with_suffix('.python.json')]
        environment = dict(os.environ, ACP_PERMISSIONS_OUTPUT=str(paths[0]))
        commands = [['node', '--expose-internals', 'scripts/oracles/official/node_modules/vitest/vitest.mjs',
                     'run', '--config', 'scripts/oracles/vitest.acp-permissions-probe.config.mts'],
                    [sys.executable, 'scripts/oracles/acp_permissions_python.py', str(paths[1])]]
        observations = []
        for index, command in enumerate(commands):
            paths[index].unlink(missing_ok=True)
            result = subprocess.run(command, cwd=str(ROOT), env=environment, capture_output=True, timeout=90)
            output.with_suffix('.%d.log' % index).write_bytes(result.stdout + result.stderr)
            require(result.returncode == 0, 'permission observer runner failed: ' + str(index))
            observations.append(json.loads(paths[index].read_text(encoding='utf-8')))
        report['cases'] = classify(*observations)
        report.update(status='passed', matched=10, reviewed_original_defects=2,
            scope='Twelve exact bounded permission observations: ten raw matches and two separately reviewed malformed-outcome grants. Runtime process consumers and full clean acceptance are separate; no MCP/subagent or full ACP certification.')
        require(report['inputSha256'] == hashes(), 'observation inputs changed')
        require(reference_git('rev-parse', 'HEAD') == target and not reference_git('status', '--porcelain'), 'reference changed')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report.update(status='runner-error', error=str(error))
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return 0 if report['status'] == 'passed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
