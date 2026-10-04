import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
INPUTS = ['scripts/session_lineage_oracle.py', 'scripts/oracles/session_lineage_python.py',
    'scripts/oracles/session_lineage_expected.json', 'scripts/oracles/session_lineage.probe.spec.ts',
    'scripts/oracles/vitest.session-lineage-probe.config.mts', 'scripts/oracles/vitest.session-corpus.config.mts',
    'dsh/session/tracing.py', 'dsh/session/session_query.py', 'dsh/session/persistence.py',
    'dsh/core/session/session.py', 'dsh/core/session/types.py',
    'reference/packages/session-query/session-query/src/tracing.ts',
    'reference/packages/session-query/session-query/src/corpus.ts',
    'reference/packages/session-query/session-query/src/index.ts',
    'reference/packages/session-query/session-query/tests/test-service.ts',
    'tests/test_session_lineage_source.py', 'tests/test_session_lineage_observer.py',
    'tests/test_session_lineage.py']
EXPECTED = json.loads((ROOT / 'scripts/oracles/session_lineage_expected.json').read_text(encoding='utf-8'))


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False, separators=(',', ':'))


def expected():
    return copy.deepcopy(EXPECTED)


def validate_observations(rows):
    if canonical(rows) != canonical(EXPECTED):
        raise ValueError('Session lineage raw errors, source cuts, signals, ordered title results, inspect concurrency or abort drain differs')


def validate_runtime(report):
    if (not isinstance(report, dict) or set(report) != {'observations', 'root', 'module', 'python'}
            or not isinstance(report['root'], str) or not Path(report['root']).is_absolute()
            or not isinstance(report['module'], str)
            or Path(report['module']).resolve() != (Path(report['root']) / 'dsh/__init__.py').resolve()
            or canonical(report['python']) != '[3,8,10]'):
        raise ValueError('Session lineage runtime provenance is incomplete')
    validate_observations(report['observations'])


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
            raise ValueError('Session lineage reference is not the clean pinned source')
        def hashes():
            return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}
        report.update(target_upstream=target, inputSha256=hashes())
        paths = [output.with_name(output.stem + '.' + side + '.json') for side in ('source', 'native')]
        node = shutil.which('node')
        if node is None:
            raise ValueError('Session lineage source requires Node')
        commands = [[node, str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'), 'run',
            '--config', str(ROOT / 'scripts/oracles/vitest.session-lineage-probe.config.mts')],
            [sys.executable, str(ROOT / 'scripts/oracles/session_lineage_python.py'), str(paths[1])]]
        for index, command in enumerate(commands):
            result = subprocess.run(command, cwd=str(ROOT), env=dict(os.environ, SESSION_LINEAGE_OUTPUT=str(paths[0])),
                capture_output=True, timeout=90)
            output.with_name(output.stem + '.' + str(index) + '.log').write_bytes(result.stdout + result.stderr)
            if result.returncode:
                raise ValueError('Session lineage runner failed: ' + str(index))
        source, native = [json.loads(path.read_text(encoding='utf-8')) for path in paths]
        validate_observations(source)
        validate_runtime(native)
        if native['root'] != str(ROOT) or canonical(source) != canonical(native['observations']):
            raise ValueError('Session lineage actual source/native observations differ')
        if report['inputSha256'] != hashes():
            raise ValueError('Session lineage inputs changed during observation')
        report.update(status='passed', cases=14,
            scope='Actual SessionStore and query lineage from one logical corpus listing with controlled listing failure seams; ASCII tie ids and 3500 descendants. No full FTS/event tracing/non-ASCII locale/deferred Win7 certification.')
    except Exception as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
