"""Compare pinned source and Python cooperative timeout observations."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MODES = ['unbudgeted', 'budgeted', 'deadline-return', 'deadline-throw',
         'user-first', 'deadline-first', 'foreign-first', 'number-text', 'nested', 'watchdog']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.goose/out/timeout-policy-paired.json')
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(status='runner-error', cases=[])
    try:
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        actual = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
        if target != actual:
            raise ValueError('reference differs from target')
        report['target_upstream'] = target
        paths = [output.with_suffix('.ts.json'), output.with_suffix('.python.json')]
        env = dict(os.environ, TIMEOUT_POLICY_OUTPUT=str(paths[0]))
        commands = [
            ['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs',
             'run', '--config', 'scripts/oracles/vitest.timeout-probe.config.mts'],
            [sys.executable, 'scripts/oracles/timeout_policy_python.py', str(paths[1])],
        ]
        observations = []
        for index, command in enumerate(commands):
            paths[index].unlink(missing_ok=True)
            result = subprocess.run(command, cwd=str(ROOT), env=env, capture_output=True, timeout=45)
            output.with_suffix('.%d.log' % index).write_bytes(result.stdout + result.stderr)
            if result.returncode != 0:
                raise RuntimeError('runner %d failed (%d)' % (index, result.returncode))
            rows = json.loads(paths[index].read_text(encoding='utf-8'))
            if [row['mode'] for row in rows] != MODES:
                raise ValueError('missing, duplicate or unexpected observations')
            observations.append(rows)
        for left, right in zip(*observations):
            matched = json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)
            report['cases'].append(dict(mode=left['mode'], status='matched' if matched else 'different',
                                        upstream=left, python=right))
        report['status'] = 'matched' if all(row['status'] == 'matched' for row in report['cases']) else 'different'
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return {'matched': 0, 'different': 1, 'runner-error': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
