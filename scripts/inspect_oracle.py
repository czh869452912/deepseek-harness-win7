"""Compare actual pinned/native Inspect; permit only the documented unload fix."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MODE = 'registry/disposal'
_CANCELLED = dict(error=dict(message='client.read: Client inspect query client.read was cancelled'))
SOURCE_DISPOSAL = dict(mode=MODE, afterDispose=dict(pending=1, settled=False, closed=0), result=_CANCELLED)
NATIVE_DISPOSAL = dict(mode=MODE, afterDispose=dict(pending=0, settled=True, closed=0), result=_CANCELLED)


def classify(left, right):
    if left == right:
        return 'matched'
    if left == SOURCE_DISPOSAL and right == NATIVE_DISPOSAL:
        return 'reviewed-upstream-bug/INSPECT-001'
    return 'different'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.goose/out/inspect-paired.json')
    output = parser.parse_args().output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(status='runner-error', cases=[])
    try:
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        actual = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
        if target != actual:
            raise ValueError('reference differs from target')
        if subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain', '--untracked-files=no'], encoding='utf-8').strip():
            raise ValueError('reference has tracked changes')
        report['target_upstream'] = target
        inputs = ['scripts/inspect_oracle.py', 'scripts/oracles/inspect-cases.json', 'scripts/oracles/inspect.spec.ts',
            'scripts/oracles/inspect_python.py', 'scripts/oracles/vitest.inspect-probe.config.mts',
            'scripts/oracles/vitest.agent-lifecycle.config.mts', 'scripts/oracles/vitest.consumers.config.mts', 'scripts/oracles/vitest.core.config.mts',
            'scripts/oracles/export-inspect-catalog.mjs', 'dsh/core/json_schema.py', 'dsh/core/tools.py',
            'dsh/extensions/inspect_registry.py', 'dsh/extensions/inspect_providers.py', 'dsh/extensions/inspect_catalog.json',
            'dsh/extensions/host_runner.py', 'dsh/extensions/cordis_manager.py', 'dsh/core/session/json.py',
            'dsh/cordis/context.py', 'dsh/cordis/fiber.py', 'dsh/core/abort.py', 'dsh/core/cancellation.py',
            'dsh/cordis/utils.py', 'dsh/cordis/errors.py', 'dsh/cordis/service.py', 'dsh/llm/error.py',
            'tests/test_cordis_inspect_registry.py', 'tests/test_cordis_tools_full.py',
            'tests/fixtures/inspect-source-observations.json']
        report['input_sha256'] = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in inputs}
        modes = [spec['mode'] for spec in json.loads((ROOT / 'scripts/oracles/inspect-cases.json').read_text(encoding='utf-8'))]
        if not modes or len(set(modes)) != len(modes):
            raise ValueError('empty or duplicate case identities')
        commands = [['node', 'scripts/oracles/export-inspect-catalog.mjs', '--check'],
            ['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs', 'run', '--config', 'scripts/oracles/vitest.inspect-probe.config.mts'],
            [sys.executable, 'scripts/oracles/inspect_python.py', str(output.with_suffix('.python.json'))]]
        paths = [output.with_suffix('.ts.json'), output.with_suffix('.python.json')]
        env = dict(os.environ, INSPECT_OUTPUT=str(paths[0]))
        for path in paths:
            path.unlink(missing_ok=True)
        for index, command in enumerate(commands):
            run = subprocess.run(command, cwd=str(ROOT), env=env, capture_output=True, timeout=90)
            output.with_suffix('.%d.log' % index).write_bytes(run.stdout + run.stderr)
            if run.returncode:
                raise RuntimeError('runner %d failed (%d)' % (index, run.returncode))
        observations = [json.loads(path.read_text(encoding='utf-8')) for path in paths]
        if any([row['mode'] for row in rows] != modes for rows in observations):
            raise ValueError('missing, duplicate or unexpected observations')
        fixture = json.loads((ROOT / 'tests/fixtures/inspect-source-observations.json').read_text(encoding='utf-8'))
        if fixture['target_upstream'] != target or fixture['observations'] != observations[0][:-1]:
            raise ValueError('checked-in source observations are stale')
        for path, digest in fixture['source_sha256'].items():
            if hashlib.sha256((ROOT / path).read_text(encoding='utf-8').encode('utf-8')).hexdigest() != digest:
                raise ValueError('source observation input changed: ' + path)
        for left, right in zip(*observations):
            report['cases'].append(dict(mode=left['mode'], status=classify(left, right), upstream=left, python=right))
        report['status'] = 'passed' if all(row['status'] != 'different' for row in report['cases']) else 'different'
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as caught:
        report['error'] = str(caught)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'], dict((status, sum(row['status'] == status for row in report['cases']))
        for status in ('matched', 'reviewed-upstream-bug/INSPECT-001', 'different')))
    return {'passed': 0, 'different': 1, 'runner-error': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
