import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = 'cd5ef8148158c3a752a658978873241fdf8e2bbc'
GROUPS = ('real', 'read', 'image', 'window', 'escalation', 'diff')
NAMES = tuple(json.loads((ROOT / 'scripts/oracles/fs-values-cases.json').read_text(encoding='utf-8'))['names'])
OBSERVER_INPUTS = ('scripts/fs_values_oracle.py', 'scripts/fs_values_cases.py',
    'scripts/oracles/fs-values-cases.json', 'scripts/oracles/fs-real-tool-fixtures-v1.json',
    'scripts/oracles/read_tool_fixtures_v1.json', 'scripts/oracles/read-window-fixtures-v2.json',
    'scripts/oracles/diff-fixtures-v1.json') + tuple('scripts/oracles/fs_values_' + group + '_' + side + '.' + ('mts' if side == 'source' else 'py')
        for group in GROUPS for side in ('source', 'python'))
REQUIRED_IMPORTS = {'dsh/core/tools.py', 'dsh/core/system_prompt/__init__.py', 'dsh/cordis/context.py',
    'dsh/fs/tool_fs.py', 'dsh/fs/tool_read.py', 'dsh/fs/tool_read_render.py', 'dsh/fs/tool_read_image.py',
    'dsh/fs/tool_fs_mutation.py', 'dsh/fs/tool_fs_sandbox.py', 'dsh/fs/tool_diff.py',
    'dsh/sandbox/escalation.py', 'dsh/fs/fs_local.py', 'dsh/fs/fs_observation_policy.py',
    'dsh/attachment/local.py', 'dsh/llm/llm_service.py'}
SOURCE_REQUIRED = {
    'reference/packages/core/tools/src/index.ts', 'reference/packages/fs/tool-fs/src/index.ts',
    'reference/packages/fs/tool-fs/src/read.ts', 'reference/packages/fs/tool-fs/src/read-render.ts',
    'reference/packages/fs/tool-fs/src/read-image.ts', 'reference/packages/fs/tool-fs/src/write.ts',
    'reference/packages/fs/tool-fs/src/edit.ts', 'reference/packages/fs/tool-fs/src/sandbox.ts',
    'reference/packages/fs/tool-fs/src/diff.ts', 'reference/packages/fs/tool-fs/package.json',
    'reference/pnpm-lock.yaml',
} | {'reference/node_modules/.pnpm/diff@9.0.0/node_modules/diff/' + name for name in (
    'package.json', 'libesm/diff/base.js', 'libesm/diff/line.js', 'libesm/patch/create.js')}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_inputs(source_root):
    source_root = Path(source_root).resolve()
    pin = subprocess.check_output(['git', '-C', str(source_root), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
    dirty = subprocess.check_output(['git', '-C', str(source_root), 'status', '--porcelain'], encoding='utf-8').strip()
    if pin != SOURCE_COMMIT or dirty:
        raise ValueError('FS values Source pin differs or is dirty')
    files = subprocess.check_output(['git', '-C', str(source_root), 'ls-files', '-z'], encoding='utf-8').split('\0')
    inputs = {'reference/' + name: digest(source_root / name) for name in files if name}
    dependency = subprocess.check_output(['node', '-e', "process.stdout.write(require('path').dirname(require.resolve('diff/package.json', {paths:[process.argv[1]]})))", str(source_root / 'packages/fs/tool-fs')], encoding='utf-8').strip()
    if json.loads((Path(dependency) / 'package.json').read_text(encoding='utf-8'))['version'] != '9.0.0':
        raise ValueError('FS actual diff dependency version differs from pinned lock')
    paths = [Path(dependency) / 'package.json'] + sorted((Path(dependency) / 'libesm').rglob('*.js'))
    for path in paths:
        inputs['reference/' + path.relative_to(source_root).as_posix()] = digest(path)
    inputs.update({name: digest(ROOT / name) for name in OBSERVER_INPUTS})
    return inputs


def json_values(value):
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError('Nonfinite FS JSON number')
        return int(value) if value.is_integer() else value
    if isinstance(value, dict):
        return {name:json_values(item) for name,item in value.items()}
    if isinstance(value, list):
        return [json_values(item) for item in value]
    return value


def complete_digest(rows):
    if not isinstance(rows, list) or [row.get('name') for row in rows] != list(NAMES):
        raise ValueError('Complete ordered FS values observations required')
    return hashlib.sha256(json.dumps(json_values(rows), sort_keys=True, ensure_ascii=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def identity(source, source_root, check_files=True):
    if (not isinstance(source, dict) or set(source) != {'sourceCommit', 'node', 'fixtureSha256', 'rows', 'inputs', 'fixtureWorkspace'}
            or source.get('sourceCommit') != SOURCE_COMMIT or source.get('node') != 'v22.22.2'):
        raise ValueError('FS values Source runtime differs')
    if not isinstance(source['fixtureWorkspace'], str) or not Path(source['fixtureWorkspace']).is_absolute():
        raise ValueError('FS controlled fixture workspace differs')
    inputs = source['inputs']
    required = set(OBSERVER_INPUTS) | SOURCE_REQUIRED
    if not isinstance(inputs, dict) or not required.issubset(inputs):
        raise ValueError('FS values Source input identity missing')
    for name, expected in inputs.items():
        if (not isinstance(name, str) or '\\' in name or ':' in name or '..' in PurePosixPath(name).parts
                or PurePosixPath(name).as_posix() != name or not (name.startswith('reference/') or name in OBSERVER_INPUTS)
                or not isinstance(expected, str) or len(expected) != 64
                or any(character not in '0123456789abcdef' for character in expected)):
            raise ValueError('FS values Source input identity invalid')
    if source['fixtureSha256'] != inputs['scripts/fs_values_oracle.py']:
        raise ValueError('FS values Source observer bytes differ')
    if check_files and inputs != source_inputs(source_root):
        raise ValueError('FS values Source guarded bytes changed')
    return complete_digest(source['rows'])


def validate_runtime(report, root, executable, source, modules, check_files=True, owned_runtime=False):
    root, executable = Path(root).resolve(), Path(executable).resolve()
    if (not isinstance(report, dict) or set(report) != {'root', 'python', 'executable', 'imports', 'rows', 'fixtureSha256', 'fixtureWorkspace'}
            or report.get('root') != str(root) or not report.get('python', '').startswith('3.8.10 ')
            or Path(report['executable']).resolve() != executable):
        raise ValueError('FS values selected root or Python differs')
    if report['fixtureWorkspace'] != source['fixtureWorkspace']:
        raise ValueError('FS controlled fixture workspace changed')
    if owned_runtime and executable != root / 'python.exe':
        raise ValueError('FS values interpreter must belong to the selected portable')
    if report['fixtureSha256'] != source['inputs']['scripts/fs_values_oracle.py']:
        raise ValueError('FS values native observer bytes differ')
    if not isinstance(modules, dict) or not REQUIRED_IMPORTS.issubset(modules) or report['imports'] != modules:
        raise ValueError('FS values actual imported closure differs')
    for name, expected in modules.items():
        if (not isinstance(name, str) or not name.startswith('dsh/') or '\\' in name or ':' in name
                or '..' in PurePosixPath(name).parts or PurePosixPath(name).as_posix() != name
                or not isinstance(expected, str) or len(expected) != 64
                or any(character not in '0123456789abcdef' for character in expected)):
            raise ValueError('FS values imported identity invalid')
        path = (root / name).resolve()
        if path.relative_to(root).as_posix() != name or check_files and digest(path) != expected:
            raise ValueError('FS values actual imported bytes differ')
    if complete_digest(report['rows']) != identity(source, ROOT / 'reference', check_files=False):
        raise ValueError('FS values complete public observations differ')


def combine(group, rows):
    return [dict(row, name=group + '/' + row['name']) for row in rows]


def observe_native(root, executable, output, fixture_workspace=None):
    root, executable, output = Path(root).resolve(), Path(executable).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('Fresh FS native output required')
    workspace = output.parent / (output.stem + '.work')
    workspace.mkdir(parents=True, exist_ok=True)
    fixtures = Path(fixture_workspace).resolve() if fixture_workspace is not None else output.parent / (output.stem.replace('.native', '') + '.work')
    environment = dict(os.environ, DSH_FS_FIXTURE_WORK=str(fixtures))
    rows, imports = [], {}
    for group in GROUPS:
        path = workspace / ('native-' + group + '.json')
        completed = subprocess.run([str(executable), '-I', str(ROOT / ('scripts/oracles/fs_values_' + group + '_python.py')),
            '--root', str(root), '--output', str(path)], cwd=str(workspace), env=environment, capture_output=True, timeout=180)
        path.with_suffix('.log').write_bytes(completed.stdout + completed.stderr)
        if completed.returncode or completed.stderr:
            raise RuntimeError('Actual FS native observer failed: ' + group)
        observed = json.loads(path.read_text(encoding='utf-8'))
        if (observed['root'] != str(root) or Path(observed['executable']).resolve() != executable
                or not observed['python'].startswith('3.8.10 ') or not observed['modules']):
            raise ValueError('FS group runtime identity differs: ' + group)
        for name,value in observed['modules'].items():
            if name in imports and imports[name] != value:
                raise ValueError('FS group imported bytes changed')
            imports[name] = value
        rows.extend(combine(group, observed['rows']))
    report = dict(root=str(root), python=observed['python'], executable=str(executable), imports=imports, rows=rows,
                  fixtureSha256=digest(ROOT / 'scripts/fs_values_oracle.py'), fixtureWorkspace=str(fixtures))
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=True, indent=2)
        stream.write('\n')
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--executable', type=Path, default=Path(sys.executable))
    options = parser.parse_args()
    output = options.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source_path, native_path = output.with_suffix('.source.json'), output.with_suffix('.native.json')
    workspace = output.parent / (output.stem + '.work')
    if any(path.exists() for path in (output, source_path, native_path, workspace)):
        raise ValueError('Fresh FS outputs and workspace required')
    workspace.mkdir()
    result = dict(status='runner-error')
    try:
        inputs = source_inputs(ROOT / 'reference')
        rows = []
        for group in GROUPS:
            path = workspace / ('source-' + group + '.json')
            environment = dict(os.environ, DSH_FS_OUTPUT=str(path), DSH_FS_WORK=str(workspace),
                               TSX_TSCONFIG_PATH=str(ROOT / 'reference/tsconfig.json'))
            completed = subprocess.run(['node', '--import', (ROOT / 'reference/node_modules/tsx/dist/loader.mjs').as_uri(),
                str(ROOT / ('scripts/oracles/fs_values_' + group + '_source.mts'))], cwd=str(ROOT), env=environment,
                capture_output=True, timeout=180)
            path.with_suffix('.log').write_bytes(completed.stdout + completed.stderr)
            if completed.returncode:
                raise RuntimeError('Actual FS Source observer failed: ' + group)
            observed = json.loads(path.read_text(encoding='utf-8'))
            if observed['sourceCommit'] != SOURCE_COMMIT or observed['node'] != 'v22.22.2':
                raise ValueError('FS group Source runtime differs: ' + group)
            if group == 'diff':
                for name,value in observed['inputs'].items():
                    selected = Path(name).resolve()
                    try:
                        expected = 'reference/' + selected.relative_to(ROOT / 'reference').as_posix()
                    except ValueError:
                        expected = selected.relative_to(ROOT).as_posix()
                    if inputs.get(expected) != value:
                        raise ValueError('FS actual diff dependency bytes differ')
            rows.extend(combine(group, observed['rows']))
        if source_inputs(ROOT / 'reference') != inputs:
            raise ValueError('FS Source inputs changed during observation')
        source = dict(sourceCommit=SOURCE_COMMIT, node='v22.22.2', rows=rows, inputs=inputs,
                      fixtureSha256=digest(ROOT / 'scripts/fs_values_oracle.py'), fixtureWorkspace=str(workspace))
        with source_path.open('x', encoding='utf-8') as stream:
            json.dump(source, stream, ensure_ascii=True, indent=2)
            stream.write('\n')
        expected = identity(source, ROOT / 'reference')
        native = observe_native(options.root, options.executable, native_path, workspace)
        validate_runtime(native, options.root, options.executable, source, native['imports'])
        if source_inputs(ROOT / 'reference') != inputs:
            raise ValueError('FS Source inputs changed during native observation')
        result = dict(status='matched', cases=len(NAMES), observationsSha256=expected)
    except Exception as error:
        result['error'] = str(error)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return 0 if result['status'] == 'matched' else 1


if __name__ == '__main__':
    raise SystemExit(main())


