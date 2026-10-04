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
    'scripts/query_engine_oracle.py', 'scripts/oracles/query_engine_python.py',
    'scripts/oracles/query_engine.probe.spec.ts', 'scripts/oracles/query_engine_expected.json',
    'scripts/oracles/vitest.query-engine-probe.config.mts',
    'dsh/session/query_engine.py', 'dsh/session/query_requests.py', 'dsh/session/query_schema.py',
    'dsh/session/sqlite_database.py', 'dsh/session/bin/sqlite3.dll', 'dsh/session/session_query.py',
    'dsh/session/tracing.py', 'dsh/session/corpus.py',
    'reference/packages/session-query/session-query-sqlite/src/index.ts',
    'reference/packages/session-query/session-query-sqlite/src/query.ts',
    'reference/packages/session-query/session-query-sqlite/src/schema.ts',
    'tests/test_query_engine.py', 'tests/test_query_engine_observer.py', 'tests/test_query_engine_source.py',
]
EXPECTED = json.loads((ROOT / 'scripts/oracles/query_engine_expected.json').read_text(encoding='utf-8'))


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':'))


def expected():
    return copy.deepcopy(EXPECTED)


def validate(rows):
    if canonical(rows) != canonical(EXPECTED):
        raise ValueError('Actual query FTS/lifecycle/revision/cursor observations differ')


def validate_runtime(report, root=None):
    fields = {'observations', 'root', 'moduleFile', 'python', 'sqliteVersion', 'sqliteSourceId', 'sqliteDllSha256', 'manifest'}
    if not isinstance(report, dict) or set(report) != fields or not isinstance(report.get('root'), str):
        raise ValueError('Query engine runtime receipt is incomplete')
    validate(report.get('observations'))
    expected_root = Path(root if root is not None else report.get('root', '')).resolve()
    manifest = json.loads((ROOT / 'dsh/session/bin/sqlite3.json').read_text(encoding='utf-8'))
    if (report.get('root') != str(expected_root)
            or report.get('moduleFile') != str(expected_root / 'dsh/session/query_engine.py')
            or report.get('python') != '3.8.10'
            or report.get('sqliteVersion') != manifest['version']
            or report.get('sqliteSourceId') != manifest['source_id']
            or report.get('sqliteDllSha256') != manifest['dll_sha256']
            or report.get('manifest') != manifest):
        raise ValueError('Query engine runtime provenance differs')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(status='failed')
    try:
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        actual = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
        dirty = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain'], encoding='utf-8').strip()
        if actual != target or dirty:
            raise ValueError('Query engine requires the clean pinned upstream')
        def hashes():
            return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}
        report.update(target_upstream=target, inputSha256=hashes())
        paths = [output.with_name(output.stem + '.' + side + '.json') for side in ('source', 'native')]
        node = shutil.which('node')
        if node is None:
            raise ValueError('Source query engine requires Node')
        commands = [[node, str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'), 'run',
                     '--config', str(ROOT / 'scripts/oracles/vitest.query-engine-probe.config.mts')],
                    [sys.executable, '-I', str(ROOT / 'scripts/oracles/query_engine_python.py'), str(paths[1])]]
        for position, command in enumerate(commands):
            result = subprocess.run(command, cwd=str(ROOT), env=dict(os.environ, QUERY_ENGINE_OUTPUT=str(paths[0])),
                                    capture_output=True, timeout=90)
            output.with_name(output.stem + '.' + str(position) + '.log').write_bytes(result.stdout + result.stderr)
            if result.returncode:
                raise ValueError('Query engine runner failed: ' + str(position))
        validate(json.loads(paths[0].read_text(encoding='utf-8')))
        native = json.loads(paths[1].read_text(encoding='utf-8'))
        validate_runtime(native, ROOT)
        if report['inputSha256'] != hashes():
            raise ValueError('Query engine inputs changed during observation')
        report.update(status='passed', cases=len(EXPECTED), scope='Actual original/native FTS selection and typed lifecycle/revision/cursor boundaries. Non-ASCII ICU fingerprint order, exhaustive semantic extraction, all races and public plugin/tool integration remain unaccepted prototype scope.')
    except Exception as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2)+'\n', encoding='utf-8')
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
