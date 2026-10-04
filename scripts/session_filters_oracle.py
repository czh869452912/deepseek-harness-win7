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
INPUTS = ['scripts/session_filters_oracle.py','scripts/oracles/session_filters_python.py',
    'scripts/oracles/session_filters_expected.json','scripts/oracles/session_filters_cases.json',
    'scripts/oracles/session_event_trace_fixture.json','scripts/oracles/session_filters.probe.spec.ts',
    'scripts/oracles/vitest.session-filters-probe.config.mts',
    'dsh/session/session_query.py','dsh/session/corpus.py','dsh/session/tracing.py',
    'dsh/core/session/types.py','dsh/core/session/session.py',
    'reference/packages/session-query/session-query/src/filters.ts',
    'reference/packages/session-query/session-query/src/documents.ts',
    'reference/packages/session-query/session-query/src/extraction.ts',
    'reference/packages/session-query/session-query/src/corpus.ts',
    'reference/packages/session-query/session-query/src/index.ts',
    'reference/packages/session-query/session-query/tests/test-service.ts',
    'tests/test_session_filters_source.py','tests/test_session_filters_observer.py','tests/test_session_filters.py']
EXPECTED = json.loads((ROOT / 'scripts/oracles/session_filters_expected.json').read_text(encoding='utf-8'))


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False, separators=(',', ':'))


def expected():
    return copy.deepcopy(EXPECTED)


def validate_observations(rows):
    if canonical(rows) != canonical(EXPECTED):
        raise ValueError('Session filters raw errors, owned clauses, literal matches, surface documents or concrete query consumers differ')


def validate_runtime(report):
    if (not isinstance(report, dict) or set(report) != {'observations', 'root', 'module', 'python'}
            or not isinstance(report['root'], str) or not Path(report['root']).is_absolute()
            or not isinstance(report['module'], str)
            or Path(report['module']).resolve() != (Path(report['root']) / 'dsh/__init__.py').resolve()
            or canonical(report['python']) != '[3,8,10]'):
        raise ValueError('Session filters runtime provenance is incomplete')
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
            raise ValueError('Session filters reference is not the clean pinned source')
        def hashes():
            return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}
        report.update(target_upstream=target, inputSha256=hashes())
        paths = [output.with_name(output.stem + '.' + side + '.json') for side in ('source', 'native')]
        node = shutil.which('node')
        if node is None:
            raise ValueError('Session filters source requires Node')
        commands = [[node, str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'), 'run',
            '--config', str(ROOT / 'scripts/oracles/vitest.session-filters-probe.config.mts')],
            [sys.executable, str(ROOT / 'scripts/oracles/session_filters_python.py'), str(paths[1])]]
        for index, command in enumerate(commands):
            result = subprocess.run(command, cwd=str(ROOT), env=dict(os.environ, SESSION_FILTERS_OUTPUT=str(paths[0])),
                capture_output=True, timeout=90)
            output.with_name(output.stem + '.' + str(index) + '.log').write_bytes(result.stdout + result.stderr)
            if result.returncode:
                raise ValueError('Session filters runner failed: ' + str(index))
        source, native = [json.loads(path.read_text(encoding='utf-8')) for path in paths]
        validate_observations(source)
        validate_runtime(native)
        if native['root'] != str(ROOT) or canonical(source) != canonical(native['observations']):
            raise ValueError('Session filters actual source/native observations differ')
        if report['inputSha256'] != hashes():
            raise ValueError('Session filters inputs changed during observation')
        report.update(status='passed', cases=33,
            scope='Actual filter materialization/text/documents and concrete query consumers with controlled persistence listing/inspection/failure seams. Enumerated ECMAScript whitespace and I-case behavior; no complete Unicode-version/FTS/profile/Win7 certification.')
    except Exception as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
