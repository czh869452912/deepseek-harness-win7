import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = 'cd5ef8148158c3a752a658978873241fdf8e2bbc'
NAMES = ('text.txt', 'empty.txt', '中文.txt', 'fixed-time.txt', 'directory', 'metadata-change.txt', 'missing.txt')
SOURCE_AREAS = ('packages/fs/fs-local', 'packages/fs/fs', 'vendor/cordis', 'packages/typert', 'vendor/schemastery')
OBSERVER_INPUTS = ('scripts/win32_stat_oracle.py', 'scripts/oracles/win32_stat_source.mts', 'scripts/oracles/win32_stat_python.py') + ('scripts/import_paths.py',)
REQUIRED_MODULES = frozenset(('dsh/__init__.py', 'dsh/fs/fs_local.py', 'dsh/fs/win32_stat.py',
    'dsh/llm/error.py') + tuple(
    'dsh/cordis/' + name + '.py' for name in ('__init__', 'awaiting', 'context', 'environment', 'errors', 'events',
        'fiber', 'hmr', 'include', 'loader', 'logger', 'plugin', 'profile', 'reflect', 'registry', 'schema',
        'service', 'timer', 'utils')))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_inputs(source_root):
    source_root = Path(source_root).resolve()
    pin = subprocess.check_output(['git', '-C', str(source_root), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
    dirty = subprocess.check_output(['git', '-C', str(source_root), 'status', '--porcelain'], encoding='utf-8').strip()
    if pin != SOURCE_COMMIT or dirty:
        raise ValueError('File metadata Source pin differs or is dirty')
    files = subprocess.check_output(['git', '-C', str(source_root), 'ls-files', '-z', '--'] + list(SOURCE_AREAS), encoding='utf-8').split('\0')
    files = [name for name in files if name]
    if any(not any(name.startswith(area + '/') for name in files) for area in SOURCE_AREAS):
        raise ValueError('File metadata Source provider inputs missing')
    result = {'reference/' + name: digest(source_root / name) for name in files}
    result.update({name: digest(ROOT / name) for name in OBSERVER_INPUTS})
    return result


def observation_digest(rows):
    if not isinstance(rows, list) or len(rows) != len(NAMES) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('Complete file metadata rows missing')
    if tuple(row.get('name') for row in rows) != NAMES:
        raise ValueError('File metadata identities or order differ')
    for row in rows:
        if set(row) != {'name', 'stat', 'lstat', 'raw'}:
            raise ValueError('File metadata row shape differs')
        if row['name'] == 'missing.txt':
            if any(row[field] is not None for field in ('stat', 'lstat', 'raw')):
                raise ValueError('Missing file metadata differs')
            continue
        if not isinstance(row['raw'], dict) or set(row['raw']) != {'dev', 'ino', 'size', 'mtimeNs', 'ctimeNs'}:
            raise ValueError('Raw file metadata incomplete')
        if any(not isinstance(value, str) or not value.isdecimal() for value in row['raw'].values()):
            raise ValueError('Raw file metadata integer identity differs')
        expected_version = ':'.join(row['raw'][key] for key in ('dev', 'ino', 'size', 'mtimeNs', 'ctimeNs'))
        for field in ('stat', 'lstat'):
            info = row[field]
            if not isinstance(info, dict) or set(info) != {'type', 'version', 'size'}:
                raise ValueError('Public file metadata incomplete')
            if info['type'] != ('directory' if row['name'] == 'directory' else 'file'):
                raise ValueError('Public file type differs')
            if type(info['size']) is not int or info['size'] != int(row['raw']['size']) or info['version'] != expected_version:
                raise ValueError('Public file metadata disagrees with raw identity')
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()


def identity(source, source_root, check_files=True):
    if source.get('sourceCommit') != SOURCE_COMMIT or source.get('node') != 'v22.22.2':
        raise ValueError('File metadata Source runtime differs')
    if check_files and source.get('inputs') != source_inputs(source_root):
        raise ValueError('File metadata Source guarded bytes differ')
    return observation_digest(source['rows'])


def validate_runtime(report, root, executable, source, modules, check_files=True):
    if __package__:
        from scripts.import_paths import resolve_import_path
    else:
        from import_paths import resolve_import_path
    root = Path(root).resolve()
    if Path(report['root']).resolve() != root or not report['python'].startswith('3.8.10 '):
        raise ValueError('File metadata selected root or Python differs')
    if Path(report['executable']).resolve() != Path(executable).resolve():
        raise ValueError('File metadata selected interpreter differs')
    if report.get('destination') != source['destination']:
        raise ValueError('File metadata physical workspace differs')
    if not isinstance(modules, dict) or set(modules) != REQUIRED_MODULES or report.get('modules') != modules:
        raise ValueError('File metadata actual import closure differs')
    missing_prefixes = None if check_files else {}
    for name, expected in modules.items():
        path = resolve_import_path(root, name, missing_prefixes)
        if path.relative_to(root).as_posix() != name or not isinstance(expected, str) or len(expected) != 64 or any(character not in '0123456789abcdef' for character in expected):
            raise ValueError('File metadata imported identity invalid')
        if check_files and digest(path) != expected:
            raise ValueError('File metadata actual imported bytes differ')
    if observation_digest(report['rows']) != observation_digest(source['rows']):
        raise ValueError('Complete file metadata observations differ')
    handles = report.get('handles')
    if not isinstance(handles, dict) or set(handles) != {'successful_probes', 'initial_handle_count', 'final_handle_count', 'failures'}:
        raise ValueError('File metadata handle evidence missing')
    initial = handles['initial_handle_count']
    if type(initial) is not int or initial < 1 or type(handles['final_handle_count']) is not int or handles['final_handle_count'] != initial:
        raise ValueError('File metadata handle ownership differs')
    if type(handles['successful_probes']) is not int or handles['successful_probes'] != 256:
        raise ValueError('File metadata successful handle probes missing')
    expected = [dict(boundary=boundary, winerror=5, closed_handles=1, handle_count=initial)
        for boundary in ('GetFileInformationByHandle', 'GetFileInformationByHandleEx')]
    failures = handles['failures']
    if not isinstance(failures, list) or len(failures) != 2 or any(not isinstance(row, dict)
            or any(type(row.get(field)) is not int for field in ('winerror', 'closed_handles', 'handle_count')) for row in failures) or failures != expected:
        raise ValueError('File metadata failed handle cleanup differs')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT / 'reference')
    parser.add_argument('--native-root', type=Path, default=ROOT)
    options = parser.parse_args()
    if os.name != 'nt':
        raise RuntimeError('Windows file metadata observation requires Windows')
    output = options.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source_root, native_root = options.source_root.resolve(), options.native_root.resolve()
    source_path, native_path = output.with_suffix('.source.json'), output.with_suffix('.native.json')
    destination = output.with_suffix('.files')
    if any(path.exists() for path in (output, source_path, native_path, destination)):
        raise ValueError('Fresh file metadata outputs required')
    report = dict(status='runner-error')
    try:
        inputs = source_inputs(source_root)
        environment = dict(os.environ, DSH_STAT_SOURCE_ROOT=str(source_root), DSH_STAT_DESTINATION=str(destination),
            DSH_STAT_SOURCE_OUTPUT=str(source_path), TSX_TSCONFIG_PATH=str(source_root / 'tsconfig.json'))
        completed = subprocess.run(['node', '--import', (source_root / 'node_modules/tsx/dist/esm/index.mjs').as_uri(),
            str(ROOT / 'scripts/oracles/win32_stat_source.mts')], cwd=str(source_root), env=environment, capture_output=True, timeout=90)
        output.with_suffix('.source.log').write_bytes(completed.stdout + completed.stderr)
        if completed.returncode or completed.stderr:
            raise RuntimeError('Actual file metadata Source observer failed')
        source = json.loads(source_path.read_text(encoding='utf-8'))
        source['inputs'] = inputs
        source_path.write_text(json.dumps(source, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        expected = identity(source, source_root)
        completed = subprocess.run([sys.executable, '-I', str(ROOT / 'scripts/oracles/win32_stat_python.py'),
            '--root', str(native_root), '--destination', str(destination), '--output', str(native_path)],
            cwd=str(ROOT), capture_output=True, timeout=90)
        output.with_suffix('.native.log').write_bytes(completed.stdout + completed.stderr)
        if completed.returncode or completed.stderr:
            raise RuntimeError('Actual file metadata native observer failed')
        native = json.loads(native_path.read_text(encoding='utf-8'))
        validate_runtime(native, native_root, sys.executable, source, native['modules'])
        report = dict(status='matched', cases=len(NAMES), observationsSha256=expected, handle_probes=256, handle_failure_boundaries=2)
    except Exception as error:
        report['error'] = str(error)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    return 0 if report['status'] == 'matched' else 1


if __name__ == '__main__':
    raise SystemExit(main())
