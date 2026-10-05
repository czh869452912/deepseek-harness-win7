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
from scripts.oracles.session_restore_sign_python import NAMES

SOURCE_INPUTS = {
    'reference/packages/core/session/src/index.ts',
    'reference/packages/core/session/src/json.ts',
    'reference/packages/core/session/src/types.ts',
    'scripts/oracles/session_restore_sign.probe.spec.ts',
    'scripts/oracles/vitest.session-restore-sign-probe.config.mts',
    'scripts/oracles/vitest.agent-lifecycle.config.mts',
    'scripts/oracles/vitest.consumers.config.mts',
    'scripts/oracles/vitest.core.config.mts', 'migration/modules.json',
}
REQUIRED_MODULES = {'dsh/core/session/__init__.py', 'dsh/core/session/session.py',
    'dsh/core/session/types.py', 'dsh/core/session/json.py'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observation_digest(rows):
    if not isinstance(rows, list) or tuple(row['name'] for row in rows) != NAMES:
        raise ValueError('Session restore sign observations missing, duplicate or reordered')
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=True,
        allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def identity(source, check_files=True):
    if source.get('sourceCommit') != SOURCE_COMMIT or source.get('node') != 'v22.22.2':
        raise ValueError('Session restore sign Source identity differs')
    if not isinstance(source.get('inputs'), dict) or set(source['inputs']) != SOURCE_INPUTS:
        raise ValueError('Session restore sign Source guard inputs differ')
    if check_files and source['inputs'] != {name: digest(ROOT / name) for name in SOURCE_INPUTS}:
        raise ValueError('Session restore sign Source guard bytes changed')
    return observation_digest(source['rows'])


def validate_runtime(report, root, expected_digest, modules, check_files=True):
    root = Path(root).resolve()
    if not isinstance(report, dict) or Path(report['root']).resolve() != root or not report['python'].startswith('3.8.10 '):
        raise ValueError('Session restore sign selected root or Python differs')
    validate_executable(report['executable'], root, check_files)
    if not isinstance(modules, dict) or not REQUIRED_MODULES.issubset(modules) or report['modules'] != modules:
        raise ValueError('Session restore sign imported module closure differs')
    for name, expected in modules.items():
        if not name.startswith('dsh/') or '..' in Path(name).parts or ':' in name or '\\' in name:
            raise ValueError('Session restore sign imported path invalid')
        path = (root / name).resolve()
        if path.relative_to(root).as_posix() != name or not isinstance(expected, str) or len(expected) != 64 or any(character not in '0123456789abcdef' for character in expected):
            raise ValueError('Session restore sign imported identity invalid')
        if check_files and digest(path) != expected:
            raise ValueError('Session restore sign actual imported bytes differ')
    if observation_digest(report['rows']) != expected_digest:
        raise ValueError('Session restore sign complete observations differ')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    output = options.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    raw_path = output.with_suffix('.raw-source.json')
    source_path, native_path = output.with_suffix('.source.json'), output.with_suffix('.native.json')
    if any(path.exists() for path in (output, raw_path, source_path, native_path)):
        raise ValueError('Fresh Session restore sign paired outputs required')
    report = dict(status='runner-error')
    try:
        source_pin()
        inputs = {name: digest(ROOT / name) for name in SOURCE_INPUTS}
        environment = dict(os.environ, DSH_RESTORE_SIGN_SOURCE_OUTPUT=str(raw_path))
        for index, command in enumerate([
            ['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs', 'run', '--config',
                'scripts/oracles/vitest.session-restore-sign-probe.config.mts'],
            [sys.executable, '-I', 'scripts/oracles/session_restore_sign_python.py', '--root', str(ROOT), '--output', str(native_path)],
        ]):
            completed = subprocess.run(command, cwd=str(ROOT), env=environment, capture_output=True, timeout=60)
            output.with_suffix('.%d.log' % index).write_bytes(completed.stdout + completed.stderr)
            if completed.returncode or completed.stderr:
                raise RuntimeError('Session restore sign observer failed: ' + str(index))
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
            scope='18 actual public Session.fromRestore numeric admission and signed numeric identity observations. Whole values and negative zero preserve original value and Number.isSafeInteger/Object.is predicates, with exact fractional refusal diagnostics. Python mathematical equality plus copysign is the explicit counterpart to Source numeric Object.is, not output normalization. Complete rows compare without filtering. No JSON serialization or transferred input graph identity/all restore ABI claim. Creation snapshot negative-zero refusal remains unchanged. Actual selected/extracted ownPython3.8.10 imported modules, clean pinned Source/Node22.22.2 and static Source guards required. Not fullB1/profile/Win7 certification.')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=True, indent=2)
        stream.write('\n')
    print(report['status'])
    return 0 if report['status'] == 'matched' else 1


if __name__ == '__main__':
    raise SystemExit(main())
