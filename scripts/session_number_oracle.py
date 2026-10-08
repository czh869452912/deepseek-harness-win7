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
from scripts.oracles.session_number_python import NAMES

SOURCE_INPUTS = {
    'reference/packages/core/session/src/index.ts',
    'reference/packages/core/session/src/json.ts',
    'reference/packages/core/session/src/types.ts',
    'scripts/oracles/session_number.probe.spec.ts',
    'scripts/oracles/vitest.session-number-probe.config.mts',
    'scripts/oracles/vitest.agent-lifecycle.config.mts',
    'scripts/oracles/vitest.consumers.config.mts',
    'scripts/oracles/vitest.core.config.mts', 'migration/modules.json',
} | {'scripts/import_paths.py'}
REQUIRED_MODULES = {'dsh/core/session/__init__.py', 'dsh/core/session/session.py',
    'dsh/core/session/types.py', 'dsh/core/session/json.py'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observation_digest(rows):
    if not isinstance(rows, list) or tuple(row['name'] for row in rows) != NAMES:
        raise ValueError('Session number observations missing, duplicate or reordered')
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=True,
        allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def identity(source, check_files=True):
    if source.get('sourceCommit') != SOURCE_COMMIT or source.get('node') != 'v22.22.2':
        raise ValueError('Session number Source identity differs')
    if not isinstance(source.get('inputs'), dict) or set(source['inputs']) != SOURCE_INPUTS:
        raise ValueError('Session number Source guard inputs differ')
    if check_files and source['inputs'] != {name: digest(ROOT / name) for name in SOURCE_INPUTS}:
        raise ValueError('Session number Source guard bytes changed')
    return observation_digest(source['rows'])


def validate_runtime(report, root, expected_digest, modules, check_files=True):
    if __package__:
        from scripts.import_paths import resolve_import_path
    else:
        from import_paths import resolve_import_path
    root = Path(root).resolve()
    if not isinstance(report, dict) or Path(report['root']).resolve() != root or not report['python'].startswith('3.8.10 '):
        raise ValueError('Session number selected root or Python differs')
    validate_executable(report['executable'], root, check_files)
    if not isinstance(modules, dict) or not REQUIRED_MODULES.issubset(modules) or report['modules'] != modules:
        raise ValueError('Session number imported module closure differs')
    missing_prefixes = None if check_files else {}
    for name, expected in modules.items():
        if not name.startswith('dsh/') or '..' in Path(name).parts or ':' in name or '\\' in name:
            raise ValueError('Session number imported path invalid')
        path = resolve_import_path(root, name, missing_prefixes)
        if path.relative_to(root).as_posix() != name or not isinstance(expected, str) or len(expected) != 64 or any(character not in '0123456789abcdef' for character in expected):
            raise ValueError('Session number imported identity invalid')
        if check_files and digest(path) != expected:
            raise ValueError('Session number actual imported bytes differ')
    if observation_digest(report['rows']) != expected_digest:
        raise ValueError('Session number complete observations differ')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    output = options.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    raw_path = output.with_suffix('.raw-source.json')
    source_path, native_path = output.with_suffix('.source.json'), output.with_suffix('.native.json')
    if any(path.exists() for path in (output, raw_path, source_path, native_path)):
        raise ValueError('Fresh Session number paired outputs required')
    report = dict(status='runner-error')
    try:
        source_pin()
        inputs = {name: digest(ROOT / name) for name in SOURCE_INPUTS}
        environment = dict(os.environ, DSH_SESSION_NUMBER_SOURCE_OUTPUT=str(raw_path))
        for index, command in enumerate([
            ['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs', 'run', '--config',
                'scripts/oracles/vitest.session-number-probe.config.mts'],
            [sys.executable, '-I', 'scripts/oracles/session_number_python.py', '--root', str(ROOT), '--output', str(native_path)],
        ]):
            completed = subprocess.run(command, cwd=str(ROOT), env=environment, capture_output=True, timeout=60)
            output.with_suffix('.%d.log' % index).write_bytes(completed.stdout + completed.stderr)
            if completed.returncode or completed.stderr:
                raise RuntimeError('Session number observer failed: ' + str(index))
        source = json.loads(raw_path.read_text(encoding='utf-8'))
        source['inputs'] = inputs
        with source_path.open('x', encoding='utf-8') as stream:
            json.dump(source, stream, indent=2)
            stream.write('\n')
        expected_digest = identity(source)
        native = json.loads(native_path.read_text(encoding='utf-8'))
        modules = {name: digest(ROOT / name) for name in native['modules']}
        validate_runtime(native, ROOT, expected_digest, modules)
        source_pin()
        report.update(status='matched', target_upstream=SOURCE_COMMIT, cases=len(NAMES),
            observations_sha256=expected_digest, modules=modules,
            scope='53 actual public Session.create numeric header/seed, retained deeply immutable published header and shallow/deep clone observations. Complete rows match without output filtering or numeric normalization. Python ValueError corresponds to Source Error at this admission boundary; unexpected exceptions fail the observer. Guard inventory is not a full dynamic Source closure. Mutable construction/from_dict/deepclone DTOs remain separate from published validated headers. Shallow clones retain shared frozen nested values; structuredClone/deepcopy returns a fully mutable detached graph. Actual corpus/list/load/lineage/snapshot consumers additionally verify this boundary. Not arbitrary restore/plugin ABI, every malformed/ownership schedule, fullB1 or Win7 certification.')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=True, indent=2)
        stream.write('\n')
    print(report['status'])
    return 0 if report['status'] == 'matched' else 1


if __name__ == '__main__':
    raise SystemExit(main())
