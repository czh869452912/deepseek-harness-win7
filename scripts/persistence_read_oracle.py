import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.runtime_context_oracle import SOURCE_COMMIT, source_pin, validate_executable
from scripts.oracles.persistence_read_python import assets

PUBLIC = ('create/whole', 'create/negative-zero', 'create/fraction', 'create/boolean',
    'append/whole', 'append/negative-zero', 'append/fraction', 'append/boolean',
    'read/whole', 'read/negative-zero', 'read/fraction', 'read/boolean', 'read/unsafe', 'abort/before', 'abort/after-read')
NAMES = tuple(backend + '/' + name for backend in ('jsonl-none', 'jsonl-zstd', 'sqlite') for name in PUBLIC) + (
    'jsonl-none/queued', 'jsonl-zstd/queued', 'sqlite/queued', 'sqlite/legacy-forward', 'sqlite/legacy-after', 'sqlite/aborted-failure')
SOURCE_INPUTS = {
    'reference/packages/session/session-persistence/src/coordinator.ts',
    'reference/packages/session/session-persistence-jsonl/src/index.ts',
    'reference/packages/session/session-persistence-sqlite/src/index.ts',
    'reference/packages/session/session-persistence-sqlite/src/store.ts',
    'reference/packages/core/session/src/json.ts', 'reference/packages/core/session/src/types.ts',
    'scripts/oracles/persistence_public.probe.spec.ts', 'scripts/oracles/persistence_order.probe.spec.ts',
    'scripts/oracles/vitest.persistence-read-probe.config.mts', 'scripts/oracles/vitest.agent-lifecycle.config.mts',
    'scripts/oracles/vitest.consumers.config.mts', 'scripts/oracles/vitest.core.config.mts', 'migration/modules.json',
}
REQUIRED_MODULES = {'dsh/session/coordinator.py', 'dsh/session/persistence_jsonl_canonical.py',
    'dsh/session/persistence_sqlite_canonical.py', 'dsh/session/preparations.py',
    'dsh/session/jsonl_store.py', 'dsh/session/sqlite_store.py', 'dsh/cordis/context.py'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observation_digest(rows):
    if not isinstance(rows, list) or tuple(row['name'] for row in rows) != NAMES:
        raise ValueError('Persistence read observations missing, duplicate or reordered')
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=True,
        allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def identity(source, check_files=True):
    if source.get('sourceCommit') != SOURCE_COMMIT or source.get('node') != 'v22.22.2':
        raise ValueError('Persistence read Source identity differs')
    if not isinstance(source.get('inputs'), dict) or set(source['inputs']) != SOURCE_INPUTS:
        raise ValueError('Persistence read Source guard inputs differ')
    if check_files and source['inputs'] != {name: digest(ROOT / name) for name in SOURCE_INPUTS}:
        raise ValueError('Persistence read Source guard bytes changed')
    return observation_digest(source['rows'])


def validate_runtime(report, root, expected_digest, modules, expected_assets, check_files=True):
    root = Path(root).resolve()
    if not isinstance(report, dict) or Path(report['root']).resolve() != root or not report['python'].startswith('3.8.10 '):
        raise ValueError('Persistence read selected root or Python differs')
    validate_executable(report['executable'], root, check_files)
    if not isinstance(modules, dict) or not REQUIRED_MODULES.issubset(modules) or report['modules'] != modules:
        raise ValueError('Persistence read imported module closure differs')
    if not isinstance(expected_assets, dict) or not {'dsh/session/bin/sqlite3.dll', 'dsh/session/bin/zstd/dsh_zstd.dll',
            'dsh/session/resources/sql/manifest.json'}.issubset(expected_assets) or report['assets'] != expected_assets:
        raise ValueError('Persistence read private asset closure differs')
    for name, expected in dict(modules, **expected_assets).items():
        if not name.startswith('dsh/') or '..' in Path(name).parts or ':' in name or '\\' in name:
            raise ValueError('Persistence read imported path invalid')
        path = (root / name).resolve()
        if path.relative_to(root).as_posix() != name or not isinstance(expected, str) or len(expected) != 64 or any(character not in '0123456789abcdef' for character in expected):
            raise ValueError('Persistence read imported identity invalid')
        if check_files and digest(path) != expected:
            raise ValueError('Persistence read actual imported bytes differ')
    if check_files and assets(root) != expected_assets:
        raise ValueError('Persistence read actual asset closure differs')
    if observation_digest(report['rows']) != expected_digest:
        raise ValueError('Persistence read complete observations differ')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    output = options.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    public, order = output.with_suffix('.public-source.json'), output.with_suffix('.order-source.json')
    source_path, native_path = output.with_suffix('.source.json'), output.with_suffix('.native.json')
    if any(path.exists() for path in (output, public, order, source_path, native_path)):
        raise ValueError('Fresh persistence read paired outputs required')
    report = dict(status='runner-error')
    try:
        source_pin()
        inputs = {name: digest(ROOT / name) for name in SOURCE_INPUTS}
        environment = dict(os.environ, DSH_PUBLIC_SOURCE_OUTPUT=str(public), DSH_ORDER_SOURCE_OUTPUT=str(order))
        commands = [
            ['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs', 'run', '--config',
                'scripts/oracles/vitest.persistence-read-probe.config.mts'],
            [sys.executable, '-I', 'scripts/oracles/persistence_read_python.py', '--root', str(ROOT), '--output', str(native_path)],
        ]
        for index, command in enumerate(commands):
            completed = subprocess.run(command, cwd=str(ROOT), env=environment, capture_output=True, timeout=60)
            output.with_suffix('.%d.log' % index).write_bytes(completed.stdout + completed.stderr)
            if completed.returncode or completed.stderr:
                raise RuntimeError('Persistence read observer failed: ' + str(index))
        sources = [json.loads(path.read_text(encoding='utf-8')) for path in (public, order)]
        if any(value['sourceCommit'] != SOURCE_COMMIT or value['node'] != 'v22.22.2' for value in sources):
            raise ValueError('Actual persistence Source producer identity differs')
        source = dict(sourceCommit=SOURCE_COMMIT, node='v22.22.2', inputs=inputs, rows=sources[0]['rows'] + sources[1]['rows'])
        with source_path.open('x', encoding='utf-8') as stream:
            json.dump(source, stream, indent=2)
            stream.write('\n')
        expected_digest = identity(source)
        native = json.loads(native_path.read_text(encoding='utf-8'))
        modules, expected_assets = {name: digest(ROOT / name) for name in native['modules']}, assets(ROOT)
        validate_runtime(native, ROOT, expected_digest, modules, expected_assets)
        source_pin()
        report.update(status='matched', target_upstream=SOURCE_COMMIT, cases=len(NAMES),
            observations_sha256=expected_digest, modules=modules, assets=expected_assets,
            scope='51 actual canonical plaintext/compressed JSONL and SQLite numeric admission, read return/queued abort, legacy prefix forwarding and aborted backend error priority observations. Complete rows including exact bounded errors/reason identity/physical hook calls match. Guard inventory is not a full dynamic Source import inventory. Not arbitrary metadata/events/plugin ABI, all cancellation/retirement schedules, profiles, fullB1 or Win7 certification.')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(report['status'])
    return 0 if report['status'] == 'matched' else 1


if __name__ == '__main__':
    raise SystemExit(main())
