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
INPUTS = [
    "scripts/session_requests_oracle.py",
    "scripts/oracles/session_requests_python.py",
    "scripts/oracles/session_requests_expected.json",
    "scripts/oracles/session_requests_cases.json",
    "scripts/oracles/session_requests.probe.spec.ts",
    "scripts/oracles/vitest.session-requests-probe.config.mts",
    "dsh/session/session_query.py",
    "dsh/session/query_requests.py",
    "dsh/session/web_search.py",
    "reference/packages/session-query/session-query-sqlite/src/query.ts",
    "reference/packages/session-query/session-query-sqlite/src/index.ts",
    "reference/packages/session-query/session-query-sqlite/src/schema.ts",
    "reference/packages/session-query/session-query/src/filters.ts",
    "reference/packages/session-query/session-query/src/config.ts",
    "tests/test_session_requests_source.py",
    "tests/test_session_requests_observer.py",
    "tests/test_session_requests.py"
]
EXPECTED = json.loads((ROOT / 'scripts/oracles/session_requests_expected.json').read_text(encoding='utf-8'))


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False, separators=(',', ':'))


def expected():
    return copy.deepcopy(EXPECTED)


def validate_observations(rows):
    if canonical(rows) != canonical(EXPECTED):
        raise ValueError('Session search request ownership, literal diagnostics, SQL bindings/budgets, snippets or public validation order differ')


def validate_runtime(report):
    if (not isinstance(report, dict) or set(report) != {'observations', 'root', 'module', 'python'}
            or not isinstance(report['root'], str) or not Path(report['root']).is_absolute()
            or not isinstance(report['module'], str)
            or Path(report['module']).resolve() != (Path(report['root']) / 'dsh/__init__.py').resolve()
            or canonical(report['python']) != '[3,8,10]'):
        raise ValueError('Session search requests runtime provenance is incomplete')
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
            raise ValueError('Session search requests reference is not the clean pinned source')
        def hashes():
            return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}
        report.update(target_upstream=target, inputSha256=hashes())
        paths = [output.with_name(output.stem + '.' + side + '.json') for side in ('source', 'native')]
        node = shutil.which('node')
        if node is None:
            raise ValueError('Session search requests source requires Node')
        commands = [[node, str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'), 'run',
            '--config', str(ROOT / 'scripts/oracles/vitest.session-requests-probe.config.mts')],
            [sys.executable, str(ROOT / 'scripts/oracles/session_requests_python.py'), str(paths[1])]]
        for index, command in enumerate(commands):
            result = subprocess.run(command, cwd=str(ROOT), env=dict(os.environ, SESSION_REQUESTS_OUTPUT=str(paths[0])),
                capture_output=True, timeout=90)
            output.with_name(output.stem + '.' + str(index) + '.log').write_bytes(result.stdout + result.stderr)
            if result.returncode:
                raise ValueError('Session search requests runner failed: ' + str(index))
        source, native = [json.loads(path.read_text(encoding='utf-8')) for path in paths]
        validate_observations(source)
        validate_runtime(native)
        if native['root'] != str(ROOT) or canonical(source) != canonical(native['observations']):
            raise ValueError('Session search requests actual source/native observations differ')
        if report['inputSha256'] != hashes():
            raise ValueError('Session search requests inputs changed during observation')
        report.update(status='passed', cases=50,
            scope='Actual query.ts normalization, predicates evaluated in real SQLite, binding/planner budgets and snippets, plus actual SQLite Engine disabled/invalid/pre-abort calls with no provider/index access. Default public limits only; no full FTS/configuration/cursor/generation/ranking/Unicode-locale/profile/Win7 certification.')
    except Exception as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
