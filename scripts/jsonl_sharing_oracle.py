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

NAMES = ('none/delete', 'none/write', 'zstd/delete', 'zstd/write')
SOURCE_INPUTS = {
    'reference/packages/session/session-persistence-jsonl/src/index.ts',
    'reference/packages/session/session-persistence-jsonl/src/format.ts',
    'reference/packages/session/session-persistence/src/coordinator.ts',
    'scripts/oracles/jsonl_sharing.probe.spec.ts', 'scripts/oracles/jsonl_sharing_python.py',
    'scripts/oracles/vitest.jsonl-sharing-probe.config.mts', 'scripts/oracles/vitest.agent-lifecycle.config.mts',
    'scripts/oracles/vitest.consumers.config.mts', 'scripts/oracles/vitest.core.config.mts', 'migration/modules.json',
} | {'scripts/import_paths.py'}
REQUIRED_MODULES = {'dsh/session/file_io.py', 'dsh/session/jsonl_store.py',
    'dsh/session/persistence_jsonl_canonical.py', 'dsh/cordis/context.py'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observation_digest(rows):
    if not isinstance(rows, list) or tuple(row.get('name') for row in rows) != NAMES:
        raise ValueError('JSONL sharing rows missing, duplicate or reordered')
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=True,
        allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def identity(source, check_files=True):
    if source.get('sourceCommit') != SOURCE_COMMIT or source.get('node') != 'v22.22.2':
        raise ValueError('JSONL sharing Source identity differs')
    if not isinstance(source.get('inputs'), dict) or set(source['inputs']) != SOURCE_INPUTS:
        raise ValueError('JSONL sharing Source guard inputs differ')
    if check_files and source['inputs'] != {name: digest(ROOT / name) for name in SOURCE_INPUTS}:
        raise ValueError('JSONL sharing Source bytes changed')
    return observation_digest(source['rows'])


def validate_runtime(report, root, expected_digest, modules, check_files=True):
    if __package__:
        from scripts.import_paths import resolve_import_path
    else:
        from import_paths import resolve_import_path
    root = Path(root).resolve()
    if Path(report['root']).resolve() != root or not report['python'].startswith('3.8.10 '):
        raise ValueError('JSONL sharing selected root or Python differs')
    validate_executable(report['executable'], root, check_files)
    if not isinstance(modules, dict) or not REQUIRED_MODULES.issubset(modules) or report['modules'] != modules:
        raise ValueError('JSONL sharing imported module closure differs')
    missing_prefixes = None if check_files else {}
    for name, expected in modules.items():
        if not name.startswith('dsh/') or '..' in Path(name).parts or ':' in name or '\\' in name:
            raise ValueError('JSONL sharing imported path invalid')
        path = resolve_import_path(root, name, missing_prefixes)
        if path.relative_to(root).as_posix() != name or not isinstance(expected, str) or len(expected) != 64 or any(character not in '0123456789abcdef' for character in expected):
            raise ValueError('JSONL sharing imported identity invalid')
        if check_files and digest(path) != expected:
            raise ValueError('JSONL sharing actual imported bytes differ')
    if observation_digest(report['rows']) != expected_digest:
        raise ValueError('JSONL sharing complete observations differ')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    output = options.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source_path, native_path = output.with_suffix('.source.json'), output.with_suffix('.native.json')
    if any(path.exists() for path in (output, source_path, native_path)):
        raise ValueError('Fresh JSONL sharing outputs required')
    report = dict(status='runner-error')
    try:
        source_pin()
        inputs = {name: digest(ROOT / name) for name in SOURCE_INPUTS}
        completed = subprocess.run([sys.executable, '-I', 'scripts/oracles/jsonl_sharing_python.py', '--root', str(ROOT),
            '--output', str(native_path), '--source-observer'], cwd=str(ROOT), env=dict(os.environ), capture_output=True, timeout=180)
        output.with_suffix('.log').write_bytes(completed.stdout + completed.stderr)
        if completed.returncode or completed.stderr:
            raise RuntimeError('Actual JSONL sharing observer failed')
        rows = []
        for name in NAMES:
            path = native_path.with_suffix('.' + name.replace('/', '-') + '.source.json')
            captured = json.loads(path.read_text(encoding='utf-8'))
            if captured['sourceCommit'] != SOURCE_COMMIT or captured['node'] != 'v22.22.2' or captured['name'] != name:
                raise ValueError('Actual JSONL sharing Source producer differs')
            rows.append(dict(name=name, observed=captured['observed']))
        source = dict(sourceCommit=SOURCE_COMMIT, node='v22.22.2', inputs=inputs, rows=rows)
        with source_path.open('x', encoding='utf-8') as stream:
            json.dump(source, stream, indent=2)
            stream.write('\n')
        expected = identity(source)
        native = json.loads(native_path.read_text(encoding='utf-8'))
        modules = {name: digest(ROOT / name) for name in native['modules']}
        validate_runtime(native, ROOT, expected, modules)
        source_pin()
        report.update(status='matched', target_upstream=SOURCE_COMMIT, cases=len(NAMES),
            observations_sha256=expected, modules=modules,
            scope='Four complete original/native plaintext/compressed JSONL list/inspect/raw observations while a live owned Win32 delete/read-write handle permits sharing. Joint preproduced files qualify reader sharing, not Source writer parity or attribution of the original transient holder. Exact failure archives and real denials remain unchanged.')
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        with output.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2)
            stream.write('\n')


if __name__ == '__main__':
    main()
