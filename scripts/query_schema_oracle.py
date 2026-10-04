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
    "scripts/query_schema_oracle.py",
    "scripts/oracles/query_schema_python.py",
    "scripts/oracles/query_schema_expected.json",
    "scripts/oracles/query_schema.probe.spec.ts",
    "scripts/oracles/vitest.query-schema-probe.config.mts",
    "dsh/session/query_schema.py",
    "dsh/session/sqlite_database.py",
    "dsh/session/bin/sqlite3.dll",
    "dsh/session/bin/sqlite3.json",
    "reference/packages/session-query/session-query-sqlite/src/schema.ts",
    "tests/test_query_schema_source.py",
    "tests/test_query_schema_observer.py",
    "tests/test_sqlite_database.py",
    "tests/test_query_schema.py"
]
EXPECTED = json.loads((ROOT / 'scripts/oracles/query_schema_expected.json').read_text(encoding='utf-8'))


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False, separators=(',', ':'))


def expected():
    return copy.deepcopy(EXPECTED)


def validate_observations(rows):
    if canonical(rows) != canonical(EXPECTED):
        raise ValueError('Session query schema, STRICT constraints, FTS documents, data scopes, reset or foreign refusal differs')


def validate_runtime(report):
    if (not isinstance(report, dict) or set(report) != {'observations', 'root', 'module', 'python', 'sqlite'}
            or not isinstance(report['root'], str) or not Path(report['root']).is_absolute()
            or not isinstance(report['module'], str)
            or Path(report['module']).resolve() != (Path(report['root']) / 'dsh/__init__.py').resolve()
            or canonical(report['python']) != '[3,8,10]'):
        raise ValueError('Session query schema runtime provenance is incomplete')
    runtime = report.get('sqlite')
    if (not isinstance(runtime, dict) or set(runtime) != {'version', 'sourceId', 'dll', 'sha256'}
            or runtime['version'] != '3.51.2'
            or runtime['sourceId'] != '2026-01-09 17:27:48 b270f8339eb13b504d0b2ba154ebca966b7dde08e40c3ed7d559749818cb2075'
            or runtime['sha256'] != '2339b9e7c8b2d4be67d5516fed37aa70c02bdb463386c47ab130d00586751642'
            or not isinstance(runtime['dll'], str)
            or Path(runtime['dll']).resolve() != (Path(report['root']) / 'dsh/session/bin/sqlite3.dll').resolve()):
        raise ValueError('Session query schema SQLite runtime provenance differs')
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
            raise ValueError('Session query schema reference is not the clean pinned source')
        def hashes():
            return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}
        report.update(target_upstream=target, inputSha256=hashes())
        paths = [output.with_name(output.stem + '.' + side + '.json') for side in ('source', 'native')]
        node = shutil.which('node')
        if node is None:
            raise ValueError('Session query schema source requires Node')
        commands = [[node, str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'), 'run',
            '--config', str(ROOT / 'scripts/oracles/vitest.query-schema-probe.config.mts')],
            [sys.executable, str(ROOT / 'scripts/oracles/query_schema_python.py'), str(paths[1])]]
        for index, command in enumerate(commands):
            result = subprocess.run(command, cwd=str(ROOT), env=dict(os.environ, QUERY_SCHEMA_OUTPUT=str(paths[0])),
                capture_output=True, timeout=90)
            output.with_name(output.stem + '.' + str(index) + '.log').write_bytes(result.stdout + result.stderr)
            if result.returncode:
                raise ValueError('Session query schema runner failed: ' + str(index))
        source, native = [json.loads(path.read_text(encoding='utf-8')) for path in paths]
        validate_observations(source)
        validate_runtime(native)
        if native['root'] != str(ROOT) or canonical(source) != canonical(native['observations']):
            raise ValueError('Session query schema actual source/native observations differ')
        if report['inputSha256'] != hashes():
            raise ValueError('Session query schema inputs changed during observation')
        report.update(status='passed', cases=19,
            scope='Actual pinned source schema and native modern SQLite: version-8 ownership, STRICT typing/checks, unicode61 documents, four journal modes, durable reopen, connection-local live scopes, recognized version reset and unchanged refusal of foreign/canonical/corrupt files. The native API uses the hash-pinned official 3.51.2 DLL without replacing CPython SQLite. Full public search, ranking/cursors/reconciliation/generations, persistence schema-19 and Win7 remain unaccepted.')
    except Exception as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
