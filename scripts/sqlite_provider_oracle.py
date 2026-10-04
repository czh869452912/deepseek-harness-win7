import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.oracles.sqlite_schema_inputs import build_inputs
from scripts.oracles.sqlite_provider_logical_inputs import build_cases
from scripts.sqlite_format_oracle import MODULES as FORMAT_MODULES, ASSETS as FORMAT_ASSETS, digest
from dsh.session.sqlite_sql import SQL_RESOURCES

MODULES = ['dsh/session/persistence_sqlite_canonical.py', 'dsh/session/sqlite_store.py',
           'dsh/session/sqlite_schema.py', 'dsh/session/sqlite_sql.py', 'dsh/session/sqlite_logical.py',
           'dsh/session/sqlite_database.py', 'dsh/session/file_revision.py', 'dsh/session/persistence.py',
           'dsh/session/coordinator.py', 'dsh/session/prepared_persistence.py', 'dsh/session/preparations.py',
           'dsh/session/live_persistence.py', 'dsh/session/write_behind.py', 'dsh/core/session/types.py',
           'dsh/core/session/json.py', 'dsh/boot/plugin_registry.py', 'dsh/session/__init__.py',
           'dsh/core/session/__init__.py', 'dsh/core/session/session.py', 'dsh/core/session/preparation.py',
           'dsh/core/session/repair.py', 'dsh/session/repair.py'] + FORMAT_MODULES
ASSETS = ['dsh/session/resources/sql/' + name + '.sql' for name in SQL_RESOURCES] + [
    'dsh/session/resources/sql/manifest.json', 'dsh/session/bin/sqlite3.dll', 'dsh/session/bin/sqlite3.json',
] + ['dsh/session/bin/zstd/' + name for name in FORMAT_ASSETS]
STORE_NAMES = ['exact-cross-file-revision', 'source-cross-read', 'source-cross-suffix', 'source-cross-list',
    'source-cross-snapshots', 'revision-advanced-once', 'stale-append', 'after-stale-append', 'stale-repair',
    'after-stale-repair', 'ownership-changed-append', 'after-ownership-refusal', 'page-size', 'physical-count',
    'physical-kind', 'torn-load', 'torn-append-refusal', 'repair-missing-marker', 'repaired-load', 'repair-old-marker',
    'committed-corruption', 'journal-wal', 'journal-delete', 'journal-truncate', 'journal-persist',
    'refuse-unversioned', 'refuse-old-version', 'refuse-future-version', 'refuse-foreign-application',
    'refuse-altered-schema', 'peer-revision-observed', 'peer-stale-append', 'peer-winning-tail']
COLD_NAMES = ['lazy', 'inspected', 'recovered', 'coldPrepared', 'stored', 'endSeedSeq', 'suffix', 'unpublished']
LOCK_NAMES = ['crossProcessBusyCode', 'revisionUnchangedWhileBlocked', 'finiteBudget', 'staleRepairRefused', 'winningTailRetained']
OBSERVERS = ['sqlite_store', 'sqlite_schema', 'sqlite_config', 'sqlite_provider_cold', 'sqlite_store_lock', 'sqlite_provider_logical']
INPUTS = MODULES + ASSETS + ['scripts/sqlite_provider_oracle.py', 'scripts/oracles/sqlite_schema_inputs.py',
    'scripts/oracles/sqlite_provider_python.py', 'scripts/oracles/sqlite_store_python.py',
    'scripts/oracles/sqlite_provider_cold_python.py', 'scripts/oracles/sqlite_store_lock_python.py',
    'scripts/oracles/sqlite_store_lock_peer.py', 'scripts/oracles/sqlite_provider_logical_inputs.py'] + [
    'scripts/oracles/' + name + '.probe.spec.ts' for name in OBSERVERS] + [
    'scripts/oracles/vitest.' + name.replace('_', '-') + '-probe.config.mts' for name in OBSERVERS] + [
    'reference/packages/session/session-persistence-sqlite/src/' + name + '.ts'
    for name in ('index', 'store', 'schema', 'sql', 'codec', 'compression')] + [
    'reference/packages/session/session-persistence-sqlite/resources/sql/' + name + '.sql' for name in SQL_RESOURCES]


def hashes(root, paths):
    return {name: hashlib.sha256((Path(root) / name).read_bytes()).hexdigest() for name in paths}


def names():
    return STORE_NAMES + ['schema-' + item['name'] for item in build_inputs()['cases']] + [
        'config-' + str(index) for index in range(22)] + ['cold-' + name for name in COLD_NAMES] + ['lock-' + name for name in LOCK_NAMES] + [
        'logical-' + item['name'] for item in build_cases()]


def normalize(value, directory):
    if isinstance(value, dict):
        return {key: normalize(item, directory) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize(item, directory) for item in value]
    return value.replace(str(directory), '<workspace>') if isinstance(value, str) else value


def observation_digest(rows):
    if not isinstance(rows, list) or [row.get('name') if isinstance(row, dict) else None for row in rows] != names():
        raise ValueError('SQLite provider observation inventory differs')
    for row in rows:
        allowed = ({'name', 'input', 'value'}, {'name', 'input', 'error'}) if row['name'].startswith('config-') else ({'name', 'value'}, {'name', 'error'})
        logical_error = row['name'].startswith('logical-') and isinstance(row.get('error'), dict) and set(row['error']) == {'name', 'message'} and all(isinstance(value, str) for value in row['error'].values())
        if set(row) not in allowed or ('error' in row and not isinstance(row['error'], str) and not logical_error):
            raise ValueError('SQLite provider outcome is malformed')
    return digest(rows)


def source_identity(source):
    if not isinstance(source, dict) or set(source) != {'node', 'rows'} or source['node'] != 'v22.22.2':
        raise ValueError('Pinned SQLite provider Source runtime differs')
    return observation_digest(source['rows'])


def validate_runtime(report, root=None, expected_digest=None, expected_inputs=None, expected_modules=None, expected_assets=None):
    fields = {'root', 'python', 'moduleFile', 'modules', 'assets', 'generatedInputsSha256', 'rows'}
    if not isinstance(report, dict) or set(report) != fields or not isinstance(report['root'], str):
        raise ValueError('SQLite provider runtime receipt is incomplete')
    root = Path(root if root is not None else report['root']).resolve()
    if report['root'] != str(root) or report['python'] != '3.8.10' or report['moduleFile'] != str(root / 'dsh/session/sqlite_store.py'):
        raise ValueError('SQLite provider runtime provenance differs')
    for field, paths, supplied in (('modules', MODULES, expected_modules), ('assets', ASSETS, expected_assets)):
        expected = hashes(root, paths) if supplied is None else supplied
        if (not isinstance(expected, dict) or set(expected) != set(paths)
                or any(not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value) for value in expected.values())
                or report[field] != expected):
            raise ValueError('SQLite provider owned file closure differs')
    actual = observation_digest(report['rows'])
    for value, expected in ((actual, expected_digest), (report['generatedInputsSha256'], expected_inputs)):
        if (not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value)
                or expected is not None and (not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected) or value != expected)):
            raise ValueError('SQLite provider observations/inputs differ from actual Source')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--python', type=Path)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--environment', type=Path)
    arguments = parser.parse_args()
    output = arguments.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    product = arguments.root.resolve() if arguments.root else ROOT
    python = str(arguments.python.resolve()) if arguments.python else sys.executable
    workspace = output.with_name(output.stem + '.workspace')
    if output.exists():
        raise ValueError('SQLite provider requires a fresh output')
    report = dict(status='failed')
    try:
        workspace.mkdir()
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        actual = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
        dirty = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain'], encoding='utf-8').strip()
        if target != actual or dirty:
            raise ValueError('SQLite provider requires the unchanged pinned Source')
        report.update(target_upstream=target, inputSha256=hashes(ROOT, INPUTS))
        inputs = build_inputs()
        inputs['logicalCases'] = build_cases()
        inputs.update(modules=MODULES, assets=ASSETS)
        inputs_path = output.with_name(output.stem + '.inputs.json')
        inputs_path.write_text(json.dumps(inputs, ensure_ascii=True) + '\n', encoding='utf-8')
        node = shutil.which('node')
        if node is None:
            raise ValueError('SQLite provider requires pinned Node')
        environment = dict(os.environ, SQLITE_STORE_DIRECTORY=str(workspace), SQLITE_SCHEMA_INPUT=str(inputs_path),
            SQLITE_SCHEMA_OUTPUT=str(workspace / 'source-schema.json'), SQLITE_CONFIG_REPORT=str(workspace / 'source-config.json'),
            SQLITE_PROVIDER_DIRECTORY=str(workspace), SQLITE_LOCK_DIRECTORY=str(workspace / 'lock'), SQLITE_LOCK_PYTHON=python, SQLITE_LOCK_ROOT=str(product), SQLITE_LOGICAL_OUTPUT=str(workspace / 'source-logical.json'))
        (workspace / 'lock').mkdir()
        sequence = 0
        def run(command, native_process=False):
            nonlocal sequence
            selected_environment = json.loads(arguments.environment.read_text(encoding='utf-8')) if native_process and arguments.environment else environment
            result = subprocess.run(command, cwd=str(workspace) if native_process else str(ROOT), env=selected_environment, capture_output=True, timeout=120)
            output.with_name(output.stem + '.' + str(sequence) + '.log').write_bytes(result.stdout + result.stderr)
            sequence += 1
            if result.returncode:
                raise ValueError('SQLite provider observer failed: ' + str(sequence - 1))
        native_path = output.with_name(output.stem + '.native.json')
        native = [python, '-I', str(ROOT / 'scripts/oracles/sqlite_provider_python.py'), '--root', str(product),
                  '--directory', str(workspace), '--inputs', str(inputs_path)]
        run(native + ['--mode', 'produce'], native_process=True)
        for observer in OBSERVERS:
            run([node, str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'), 'run', '--config',
                str(ROOT / ('scripts/oracles/vitest.' + observer.replace('_', '-') + '-probe.config.mts'))])
        run(native + ['--mode', 'consume', '--config-source', str(workspace / 'source-config.json'), '--output', str(native_path)], native_process=True)
        store = json.loads((workspace / 'source-observations.json').read_text(encoding='utf-8'))
        schema = json.loads((workspace / 'source-schema.json').read_text(encoding='utf-8'))
        config = json.loads((workspace / 'source-config.json').read_text(encoding='utf-8'))
        cold = json.loads((workspace / 'source-cold-observations.json').read_text(encoding='utf-8'))
        lock = json.loads((workspace / 'lock/source-observations.json').read_text(encoding='utf-8'))
        logical = json.loads((workspace / 'source-logical.json').read_text(encoding='utf-8'))
        if any(value.get('node') != 'v22.22.2' for value in (store, schema, config, cold, lock, logical)):
            raise ValueError('SQLite provider Source observers use a different Node')
        rows = store['rows'] + [dict(item, name='schema-' + item['name']) for item in schema['rows']] + [
            dict(item, name='config-' + item['name']) for item in config['rows']] + [
            dict(name='cold-' + name, value=cold[name]) for name in COLD_NAMES] + [
            dict(name='lock-' + name, value=lock[name]) for name in LOCK_NAMES] + logical['rows']
        source = dict(node='v22.22.2', rows=normalize(rows, workspace))
        source_path = output.with_name(output.stem + '.source.json')
        source_path.write_text(json.dumps(source, ensure_ascii=True), encoding='utf-8')
        receipt = json.loads(native_path.read_text(encoding='utf-8'))
        receipt['rows'] = normalize(receipt['rows'], workspace)
        native_path.write_text(json.dumps(receipt, ensure_ascii=True), encoding='utf-8')
        expected = source_identity(source)
        generated = hashlib.sha256(inputs_path.read_bytes()).hexdigest()
        validate_runtime(receipt, product, expected, generated)
        if report['inputSha256'] != hashes(ROOT, INPUTS):
            raise ValueError('SQLite provider observation inputs changed')
        report.update(status='passed', cases=len(rows), observationsSha256=expected, generatedInputsSha256=generated,
                      modules=receipt['modules'], assets=receipt['assets'], nativeRoot=receipt['root'],
                      scope='Bounded schema19 actual mutual cross-files/revisions/metadata/config/cold/competing-process provider; full arbitrary histories, original EPERM suite and real Win7 remain unaccepted.')
    except Exception as error:
        report['failure'] = str(error)
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=report['status'], cases=report.get('cases'), failure=report.get('failure'))))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
