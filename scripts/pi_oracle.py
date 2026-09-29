"""Compare pinned-source pi-ai observations with product Python outputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.goose/out/current-review/pi-paired.json')
    parser.add_argument('--node', default='node')
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(status='runner-error', cases=[])
    try:
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        actual = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
        if actual != target:
            raise ValueError('reference differs from pinned target')
        dirty = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain'], encoding='utf-8').strip()
        if dirty:
            raise ValueError('reference has local changes')
        fixtures = json.loads((ROOT / 'scripts/oracles/pi-fixtures.json').read_text(encoding='utf-8'))
        ids = [row['id'] for row in fixtures]
        if len(set(ids)) != len(ids) or not ids:
            raise ValueError('invalid fixture identities')
        report.update(target_upstream=target, candidate=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=str(ROOT), encoding='utf-8').strip(),
                      node=subprocess.check_output([args.node, '--version'], encoding='utf-8').strip(), python=sys.version)
        sources = list((ROOT / 'reference/packages/llm/llm-pi-ai/src').glob('*.ts'))
        sources += list((ROOT / 'dsh/llm').glob('*.py'))
        sources += [ROOT / 'dsh/llm/pi_catalog.json', ROOT / 'scripts/oracles/export-pi-catalog.mjs']
        sources += [ROOT / 'scripts/oracles/official/node_modules/@earendil-works/pi-ai/dist/api/transform-messages.js']
        sources += [ROOT / 'scripts/oracles/official/node_modules/@earendil-works/pi-ai/dist/api/openai-completions.js']
        sources += [ROOT / 'scripts/oracles/official/node_modules/@earendil-works/pi-ai/dist/api' / name for name in
                    ('openai-responses.js', 'openai-responses-shared.js', 'anthropic-messages.js', 'simple-options.js')]
        sources += [ROOT / 'scripts/oracles/official/node_modules/@earendil-works/pi-ai/dist/utils/json-parse.js',
                    ROOT / 'scripts/oracles/official/node_modules/partial-json/dist/index.js']
        sources += [ROOT / 'scripts/oracles' / name for name in ('pi-fixtures.json', 'pi.spec.ts', 'pi_python.py', 'pi-http.ts', 'pi_http_python.py', 'vitest.pi-probe.config.mts', 'official/package-lock.json')]
        before = {str(path.relative_to(ROOT)): digest(path) for path in sources}
        paths = [output.with_suffix('.ts.json'), output.with_suffix('.python.json')]
        commands = [[args.node, '--expose-internals', 'scripts/oracles/official/node_modules/vitest/vitest.mjs',
                     'run', '--config', 'scripts/oracles/vitest.pi-probe.config.mts'],
                    [sys.executable, 'scripts/oracles/pi_python.py', str(paths[1])]]
        observations = []
        for index, command in enumerate(commands):
            paths[index].unlink(missing_ok=True)
            result = subprocess.run(command, cwd=str(ROOT), env=dict(os.environ, PI_OUTPUT=str(paths[0])),
                                    capture_output=True, timeout=45)
            output.with_suffix('.{}.log'.format(index)).write_bytes(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError('runner {} failed with exit {}'.format(index, result.returncode))
            rows = json.loads(paths[index].read_text(encoding='utf-8'))
            if [row['id'] for row in rows] != ids:
                raise ValueError('missing, reordered, or unexpected observations')
            observations.append(rows)
        after = {str(path.relative_to(ROOT)): digest(path) for path in sources}
        if before != after:
            raise ValueError('oracle inputs changed during observation')
        report.update(sourceHashes=before, commands=commands,
                      boundary='Exact JSON values and error codes; error prose and timing are not compared. No paid network calls.')
        for left, right in zip(*observations):
            report['cases'].append(dict(id=left['id'], status='matched' if left == right else 'different', upstream=left, python=right))
        report['status'] = 'matched' if all(row['status'] == 'matched' for row in report['cases']) else 'different'
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(report['status'])
    return {'matched': 0, 'different': 1, 'runner-error': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
