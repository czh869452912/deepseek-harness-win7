import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.javascript_workflow_oracle import digest, assets, PRIVATE_ASSET_PATHS
from scripts.runtime_context_oracle import source_pin, validate_executable

SOURCE_COMMIT = 'cd5ef8148158c3a752a658978873241fdf8e2bbc'
NAMES = ('before-entry-exit', 'cancel-before-entry-exit')


def observation_digest(observations):
    if not isinstance(observations, list) or tuple(row['name'] for row in observations) != NAMES:
        raise ValueError('JavaScript initial write observations missing, duplicate or reordered')
    return hashlib.sha256(json.dumps(observations, sort_keys=True, ensure_ascii=True,
        allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def identity(source):
    if source.get('sourceCommit') != SOURCE_COMMIT or source.get('node') != 'v22.22.2':
        raise ValueError('JavaScript initial write Source identity differs')
    required = {'reference/packages/workflow/workflow-worker-thread/src/' + name + '.ts'
        for name in ('host', 'runtime', 'realm', 'session', 'worker')}
    if not required.issubset(source['inputs']) or 'scripts/oracles/javascript_initial_source.mjs' not in source['inputs']:
        raise ValueError('JavaScript initial write Source input closure differs')
    for name, expected in source['inputs'].items():
        path = (ROOT / name).resolve()
        if path.relative_to(ROOT).as_posix() != name or digest(path) != expected:
            raise ValueError('JavaScript initial write Source input bytes changed')
    return observation_digest(source['observations'])


def validate_runtime(report, root, expected_digest, modules, expected_assets, check_files=True):
    root = Path(root).resolve()
    if not isinstance(report, dict) or Path(report['root']).resolve() != root or not report['python'].startswith('3.8.10 '):
        raise ValueError('JavaScript initial write selected runtime differs')
    validate_executable(report['executable'], root, check_files)
    required = {'dsh/javascript/runtime.py', 'dsh/workflow/javascript_run.py',
        'dsh/workflow/workflow_service.py', 'dsh/subagent/runtime.py', 'dsh/cordis/context.py'}
    if not isinstance(modules, dict) or not required.issubset(modules) or report['modules'] != modules:
        raise ValueError('JavaScript initial write imported module closure differs')
    for name, expected in modules.items():
        if not name.startswith('dsh/') or '..' in Path(name).parts or ':' in name or '\\' in name:
            raise ValueError('JavaScript initial write imported module path invalid')
        path = (root / name).resolve()
        if path.relative_to(root).as_posix() != name or not isinstance(expected, str) or len(expected) != 64 or any(character not in '0123456789abcdef' for character in expected):
            raise ValueError('JavaScript initial write imported module identity invalid')
        if check_files and digest(path) != expected:
            raise ValueError('JavaScript initial write imported module bytes differ')
    if not isinstance(expected_assets, dict) or set(expected_assets) != PRIVATE_ASSET_PATHS:
        raise ValueError('JavaScript initial write private asset closure differs')
    for name, expected in expected_assets.items():
        if not name.startswith(('dsh/javascript/bin/', 'dsh/javascript/workflow/')) or '..' in Path(name).parts or ':' in name or '\\' in name or not isinstance(expected, str) or len(expected) != 64 or any(character not in '0123456789abcdef' for character in expected):
            raise ValueError('JavaScript initial write private asset identity invalid')
    if report['assets'] != expected_assets or check_files and assets(root) != expected_assets:
        raise ValueError('JavaScript initial write private assets differ')
    if observation_digest(report['observations']) != expected_digest:
        raise ValueError('JavaScript initial write complete observations differ')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    output = options.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    directory = output.with_suffix('.source-workspace')
    source_path, native_path = output.with_suffix('.source.json'), output.with_suffix('.native.json')
    if any(path.exists() for path in (output, directory, source_path, native_path)):
        raise ValueError('Fresh JavaScript initial write outputs required')
    report = dict(status='runner-error')
    try:
        source_pin()
        for index, command in enumerate([
            ['node', 'scripts/oracles/javascript_initial_source.mjs', str(directory)],
            [sys.executable, '-I', 'scripts/oracles/javascript_initial_python.py', '--root', str(ROOT), '--output', str(native_path)],
        ]):
            completed = subprocess.run(command, cwd=str(ROOT), capture_output=True, timeout=60)
            output.with_suffix('.%d.log' % index).write_bytes(completed.stdout + completed.stderr)
            if completed.returncode or completed.stderr:
                raise RuntimeError('JavaScript initial write observer failed: ' + str(index))
        with source_path.open('xb') as stream:
            stream.write((directory / 'source.json').read_bytes())
        source = json.loads(source_path.read_text(encoding='utf-8'))
        source_digest = identity(source)
        if set(source['bundle']) != {'host.mjs', 'original-worker.cjs', 'worker.cjs'}:
            raise ValueError('JavaScript initial write Source bundle closure differs')
        for name, expected in source['bundle'].items():
            if name not in ('host.mjs', 'original-worker.cjs', 'worker.cjs') or digest(directory / name) != expected:
                raise ValueError('JavaScript initial write Source bundle changed')
        native = json.loads(native_path.read_text(encoding='utf-8'))
        modules = {name: digest(ROOT / name) for name in native['modules']}
        expected_assets = assets(ROOT)
        validate_runtime(native, ROOT, source_digest, modules, expected_assets)
        source_pin()
        report.update(status='matched', target_upstream=SOURCE_COMMIT, cases=len(NAMES),
            observations_sha256=source_digest, modules=modules, assets=expected_assets,
            scope='Two actual worker entries blocked before Ready emission and physical exit before initial drain resumes. Original host and original worker bundle bytes retained separately from the disclosed timing bootstrap. Complete outcomes, first cancellation, events, empty child requests, actual exit and owned disposal match. Known exited initial pipe failures preserve physical outcome; live pipe failures retain their identity in separate native controls. This is not every startup schedule, complete Node/model/profile/C2 or Win7 certification.')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=True, indent=2)
        stream.write('\n')
    print(report['status'])
    return 0 if report['status'] == 'matched' else 1


if __name__ == '__main__':
    raise SystemExit(main())
