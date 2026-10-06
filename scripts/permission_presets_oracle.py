import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.permission_presets_values import ALL_NAMES, GROUPS, complete_digest


SOURCE_COMMIT = 'cd5ef8148158c3a752a658978873241fdf8e2bbc'
OBSERVER_INPUTS = ('scripts/permission_presets_oracle.py', 'scripts/permission_presets_values.py',
    'scripts/oracles/permission_presets_source.mts', 'scripts/oracles/permission_presets.probe.spec.ts',
    'scripts/oracles/permission_presets_python.py', 'scripts/oracles/permission_presets_lifecycle_python.py',
    'scripts/oracles/permission_presets_domain_python.py', 'scripts/oracles/permission_presets_domain_source.mts',
    'scripts/oracles/permission_presets_domain.probe.spec.ts', 'scripts/oracles/vitest.permission-presets-probe.config.mts')
REQUIRED_IMPORTS = {'dsh/interaction/permission_presets.py', 'dsh/interaction/user_approval.py',
    'dsh/sandbox/sandbox_policy.py', 'dsh/core/session/__init__.py', 'dsh/session/projections.py',
    'dsh/settings/__init__.py', 'dsh/settings/provider.py', 'dsh/interaction/commands.py'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_digest(source):
    return hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False,
        separators=(',', ':')).encode('utf-8')).hexdigest()


def source_inputs(source_root):
    source_root = Path(source_root).resolve()
    pin = subprocess.check_output(['git', '-C', str(source_root), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
    dirty = subprocess.check_output(['git', '-C', str(source_root), 'status', '--porcelain'], encoding='utf-8').strip()
    if pin != SOURCE_COMMIT or dirty:
        raise ValueError('Permission Source pin differs or is dirty')
    files = subprocess.check_output(['git', '-C', str(source_root), 'ls-files', '-z'], encoding='utf-8').split('\0')
    files = [name for name in files if name]
    if 'packages/interaction/permission-presets/src/index.ts' not in files:
        raise ValueError('Permission Source provider missing')
    inputs = {'reference/' + name: digest(source_root / name) for name in files}
    inputs.update({name: digest(ROOT / name) for name in OBSERVER_INPUTS})
    return inputs


def identity(source, source_root, check_files=True):
    if (not isinstance(source, dict) or set(source) != {'sourceCommit', 'node', 'inputs', 'groups'}
            or source.get('sourceCommit') != SOURCE_COMMIT or source.get('node') != 'v22.22.2'):
        raise ValueError('Permission Source runtime differs')
    inputs = source.get('inputs')
    required = set(OBSERVER_INPUTS) | {'reference/packages/interaction/permission-presets/src/index.ts'}
    if not isinstance(inputs, dict) or not required.issubset(inputs):
        raise ValueError('Permission Source input identity missing')
    for name, expected in inputs.items():
        if (not isinstance(name, str) or '\\' in name or ':' in name or '..' in Path(name).parts
                or PurePosixPath(name).as_posix() != name
                or not (name.startswith('reference/') or name in OBSERVER_INPUTS)
                or not isinstance(expected, str) or len(expected) != 64
                or any(character not in '0123456789abcdef' for character in expected)):
            raise ValueError('Permission Source input identity invalid')
    if check_files and inputs != source_inputs(source_root):
        raise ValueError('Permission Source guarded bytes changed')
    for group in GROUPS:
        child = source['groups'][group]
        expected_keys = {'sourceCommit', 'node', 'rows', 'rawErrors' if group == 'lifecycle' else 'observedClock'}
        if not isinstance(child, dict) or set(child) != expected_keys:
            raise ValueError('Permission Source child observation shape differs')
        if child.get('sourceCommit') != source['sourceCommit'] or child.get('node') != source['node']:
            raise ValueError('Permission Source child runtime differs')
    return complete_digest(source, 'source')


def validate_runtime(report, root, executable, source, modules, check_files=True, owned_runtime=False):
    root = Path(root).resolve()
    if (not isinstance(report, dict) or set(report) != {'root', 'python', 'executable', 'modules', 'groups'}
            or report.get('root') != str(root) or not report['python'].startswith('3.8.10 ')):
        raise ValueError('Permission selected root or Python differs')
    if Path(report['executable']).resolve() != Path(executable).resolve():
        raise ValueError('Permission selected interpreter differs')
    if owned_runtime:
        if Path(executable).resolve() != root / 'python.exe':
            raise ValueError('Permission portable interpreter does not belong to the selected root')
    if not isinstance(modules, dict) or not REQUIRED_IMPORTS.issubset(modules) or report.get('modules') != modules:
        raise ValueError('Permission actual imported closure differs')
    for name, expected in modules.items():
        if (not isinstance(name, str) or not name.startswith('dsh/') or '\\' in name or ':' in name
                or '..' in Path(name).parts or not isinstance(expected, str) or len(expected) != 64
                or any(character not in '0123456789abcdef' for character in expected)):
            raise ValueError('Permission imported identity invalid')
        path = (root / name).resolve()
        if path.relative_to(root).as_posix() != name or check_files and digest(path) != expected:
            raise ValueError('Permission actual imported bytes differ')
    child_modules = {}
    for group in GROUPS:
        child = report['groups'][group]
        expected_keys = {'root', 'python', 'executable', 'modules', 'rows',
            'rawErrors' if group == 'lifecycle' else 'observedClock'}
        if not isinstance(child, dict) or set(child) != expected_keys:
            raise ValueError('Permission child runtime observation shape differs')
        if child['root'] != str(root) or child['executable'] != report['executable'] or child['python'] != report['python']:
            raise ValueError('Permission child selected runtime differs')
        if not isinstance(child.get('modules'), dict) or not {
                'dsh/cordis/context.py', 'dsh/interaction/permission_presets.py',
                'dsh/core/session/__init__.py'}.issubset(child['modules']):
            raise ValueError('Permission child imported closure missing')
        for name, expected in child['modules'].items():
            if name not in modules or modules[name] != expected:
                raise ValueError('Permission child approved imported bytes differ')
            child_modules[name] = expected
    if child_modules != modules:
        raise ValueError('Permission aggregate imported closure differs')
    if complete_digest(report, 'native') != identity(source, ROOT / 'reference', check_files=False):
        raise ValueError('Permission complete lifecycle observations differ')


def observe_native(root, executable, output):
    root, executable, output = Path(root).resolve(), Path(executable).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('Fresh Permission native output required')
    completed = subprocess.run([str(executable), '-I', str(ROOT / 'scripts/oracles/permission_presets_python.py'),
        '--root', str(root), '--output', str(output)], cwd=str(output.parent), capture_output=True, timeout=90)
    output.with_suffix('.log').write_bytes(completed.stdout + completed.stderr)
    if completed.returncode or completed.stderr:
        raise RuntimeError('Actual Permission native observer failed')
    return json.loads(output.read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    output = options.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source_path, native_path = output.with_suffix('.source.json'), output.with_suffix('.native.json')
    if any(path.exists() for path in (output, source_path, native_path)):
        raise ValueError('Fresh Permission outputs required')
    result = dict(status='runner-error')
    try:
        inputs = source_inputs(ROOT / 'reference')
        lifecycle_path, domain_path = output.with_suffix('.lifecycle.source.json'), output.with_suffix('.domain.source.json')
        if lifecycle_path.exists() or domain_path.exists():
            raise ValueError('Fresh Permission Source child outputs required')
        environment = dict(os.environ, DSH_PERMISSION_PRESETS_OUTPUT=str(lifecycle_path), DSH_PERMISSION_DOMAIN_OUTPUT=str(domain_path))
        completed = subprocess.run(['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs', 'run',
            '--config', 'scripts/oracles/vitest.permission-presets-probe.config.mts'],
            cwd=str(ROOT), env=environment, capture_output=True, timeout=90)
        output.with_suffix('.source.log').write_bytes(completed.stdout + completed.stderr)
        if completed.returncode:
            raise RuntimeError('Actual Permission Source observer failed')
        if source_inputs(ROOT / 'reference') != inputs:
            raise ValueError('Permission Source inputs changed during observation')
        source = dict(sourceCommit=SOURCE_COMMIT, node='v22.22.2', inputs=inputs,
            groups={'lifecycle': json.loads(lifecycle_path.read_text(encoding='utf-8')),
                'domain': json.loads(domain_path.read_text(encoding='utf-8'))})
        with source_path.open('x', encoding='utf-8') as stream:
            json.dump(source, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        expected = identity(source, ROOT / 'reference')
        native = observe_native(ROOT, sys.executable, native_path)
        validate_runtime(native, ROOT, sys.executable, source, native['modules'])
        result = dict(status='matched', cases=len(ALL_NAMES), observationsSha256=expected)
    except Exception as error:
        result['error'] = str(error)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return 0 if result['status'] == 'matched' else 1


if __name__ == '__main__':
    raise SystemExit(main())
