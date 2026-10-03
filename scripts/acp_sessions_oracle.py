import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
MODES = ['empty', 'pagination', 'filter', 'cursors', 'resume-refusals', 'reservation', 'shared-close', 'close-failure']


def validate_observations(rows):
    if not isinstance(rows, list) or [row.get('mode') for row in rows] != MODES:
        raise ValueError('missing, duplicate or unexpected observations')
    flags = {'empty': ['materialized', 'listedIdentity'], 'reservation': ['duplicateRejected', 'firstRejected',
             'retryReachedFactory', 'retryRejected'], 'shared-close': ['refused', 'agentGone'],
             'close-failure': ['reported', 'agentGone', 'listedIdentity']}
    for row in rows:
        if any(row.get(name) is not True for name in flags.get(row['mode'], [])):
            raise ValueError('lifecycle observation does not satisfy its declared invariant: ' + row['mode'])
        if row['mode'] in ('cursors', 'resume-refusals'):
            expected = 10 if row['mode'] == 'cursors' else 6
            if len(row.get('rejected', [])) != expected or any(value is not True for value in row['rejected']):
                raise ValueError('negative observation did not reject every required case')
        if row['mode'] == 'empty' and (row['hidden'] != {'sessions': []} or row['closed'] != {}
                or row['hiddenAfterResume'] != {'sessions': []} or not isinstance(row['listedCwd'], str)):
            raise ValueError('fresh/closed/resumed observation lost its required state')
        if row['mode'] == 'shared-close' and (row['results'] != [{}, {}] or type(row['userCancels']) is not int
                                             or row['userCancels'] != 1):
            raise ValueError('close operation was not shared')
        if row['mode'] in ('resume-refusals', 'reservation'):
            expected_calls = 0 if row['mode'] == 'resume-refusals' else 1
            if type(row['factoryCalls']) is not int or row['factoryCalls'] != expected_calls:
                raise ValueError('resume admission reached the wrong number of factories')
        if row['mode'] == 'reservation' and row['hidden'] != {'sessions': []}:
            raise ValueError('activating reservation was listed')
        if row['mode'] == 'pagination':
            pages = row.get('pages', [])
            if len(pages) != 3 or [item['sessionId'] for page in pages for item in page['sessions']] != ['new', 'Z', 'a', 'β', '😀', 'old']:
                raise ValueError('pagination fixture lost its exact ordered ids')
        if row['mode'] == 'filter' and [item['sessionId'] for item in row['result']['sessions']] != ['valid-a', 'valid-b']:
            raise ValueError('filter fixture exposed a non-resumable owner or lost a valid row')


def main():
    parser = argparse.ArgumentParser(description='Compare selected ACP Session lifecycle observations, not full wire/MCP/config parity.')
    parser.add_argument('--output', type=Path, default=ROOT / '.goose/out/acp-sessions-paired.json')
    output = parser.parse_args().output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'runner-error', 'cases': []}
    try:
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        actual = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
        if target != actual or subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain'], encoding='utf-8').strip():
            raise ValueError('reference differs from target')
        report['target_upstream'] = target
        inputs = ['dsh/acp/server.py', 'dsh/acp/session_controls.py', 'scripts/acp_sessions_oracle.py',
                  'dsh/acp/session_runtime.py', 'dsh/acp/content.py', 'dsh/acp/model_control.py', 'dsh/acp/updates.py',
                  'scripts/oracles/acp_sessions.probe.spec.ts', 'scripts/oracles/acp_sessions_python.py',
                  'scripts/oracles/vitest.acp.config.mts', 'scripts/oracles/vitest.acp-sessions-probe.config.mts',
                  'scripts/oracles/official/package-lock.json', 'scripts/oracles/acp-sdk-resolution.mjs', 'tests/test_acp_session_controls.py']
        report['inputSha256'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in inputs}
        paths = [output.with_suffix('.ts.json'), output.with_suffix('.python.json')]
        environment = dict(os.environ, ACP_SESSION_CONTROLS_OUTPUT=str(paths[0]))
        commands = [['node', '--expose-internals', 'scripts/oracles/official/node_modules/vitest/vitest.mjs',
                     'run', '--config', 'scripts/oracles/vitest.acp-sessions-probe.config.mts'],
                    [sys.executable, 'scripts/oracles/acp_sessions_python.py', str(paths[1])]]
        observations = []
        for index, command in enumerate(commands):
            paths[index].unlink(missing_ok=True)
            completed = subprocess.run(command, cwd=str(ROOT), env=environment, capture_output=True, timeout=90)
            output.with_suffix('.%d.log' % index).write_bytes(completed.stdout + completed.stderr)
            if completed.returncode != 0:
                raise RuntimeError('runner %d failed (%d)' % (index, completed.returncode))
            rows = json.loads(paths[index].read_text(encoding='utf-8'))
            validate_observations(rows)
            observations.append(rows)
        report['cases'] = [{'mode': left['mode'], 'status': 'matched' if left == right else 'different',
                            'upstream': left, 'python': right} for left, right in zip(*observations)]
        report['status'] = 'matched' if all(row['status'] == 'matched' for row in report['cases']) else 'different'
        if report['inputSha256'] != {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in inputs}:
            raise RuntimeError('observation inputs changed during the run')
        if actual != subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip() or subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain'], encoding='utf-8').strip():
            raise RuntimeError('reference changed during observation')
        report['scope'] = 'Eight declared semantic lifecycle projections; raw list/cursor fields are exact. Random fresh ids are checked for exact ownership on each side. SDK error-envelope bytes, configuration, semantic output and MCP are outside this contract.'
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report.update(status='runner-error', error=str(error))
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return {'matched': 0, 'different': 1, 'runner-error': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
