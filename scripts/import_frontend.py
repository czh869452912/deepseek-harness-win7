"""Import a complete, recorded build from the unchanged pinned upstream."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_paths(root):
    root = Path(root).absolute()
    selected = []
    for folder, directories, files in os.walk(str(root / 'apps/web/dist'), followlinks=False):
        for name in directories + files:
            if getattr(os.lstat(str(Path(folder) / name)), 'st_file_attributes', 0) & 0x400:
                raise ValueError('frontend artifact reparse point refused')
        selected.extend(Path(folder) / name for name in files)
    selected.extend((root / 'packages').glob('*/*/lib/client.js'))
    selected.extend((root / 'packages').glob('*/*/lib/client.js.map'))
    for path in selected:
        for component in (path,) + tuple(path.parents):
            if component == root:
                break
            if component.is_symlink() or getattr(os.lstat(str(component)), 'st_file_attributes', 0) & 0x400:
                raise ValueError('frontend artifact reparse point refused')
        if not path.is_file():
            raise ValueError('frontend artifact must be an ordinary file')
    return sorted(selected, key=lambda path: path.relative_to(root).as_posix())


def build_digest(root, paths):
    result = hashlib.sha256()
    for path in paths:
        name = path.relative_to(root).as_posix().encode('utf-8')
        content = path.read_bytes()
        result.update(str(len(name)).encode('ascii') + b':' + name)
        result.update(str(len(content)).encode('ascii') + b':' + content)
    return dict(fileCount=len(paths), sha256=result.hexdigest())


def recorded_inputs(source, target):
    pin = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
    dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], encoding='utf-8').strip()
    if pin != target or dirty:
        raise ValueError('frontend requires the unchanged pinned upstream checkout')
    record = json.loads((source / '.dsh-build/client-build-environment.json').read_text(encoding='utf-8'))
    package = json.loads((source / 'package.json').read_text(encoding='utf-8'))
    expected = dict(DSH_CLIENT_BUILD_PROFILE='official', DSH_CLIENT_COMMIT_HASH=pin[:7],
        DSH_CLIENT_TITLE='DeepSeek Harness', DSH_CLIENT_VERSION=package['version'])
    if set(record) != {'formatVersion', 'environment', 'artifacts'} or record['formatVersion'] != 1 or record['environment'] != expected:
        raise ValueError('frontend requires the complete official build environment')
    paths = artifact_paths(source)
    if not paths or build_digest(source, paths) != record['artifacts']:
        raise ValueError('frontend artifacts differ from the complete upstream build record')
    return record, paths


def replace_bytes(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='frontend-import-', dir=str(path.parent))
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content)
        os.replace(temporary, str(path))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_import(root, manifest):
    rows = manifest.get('client_files')
    record = manifest.get('build_record')
    if not isinstance(rows, list) or not rows or not isinstance(record, dict):
        raise ValueError('frontend requires the complete recorded client artifacts')
    environment = record.get('environment', {})
    if (set(record) != {'formatVersion', 'environment', 'artifacts'}
            or record.get('formatVersion') != 1 or not isinstance(environment, dict) or set(environment) != {
            'DSH_CLIENT_BUILD_PROFILE', 'DSH_CLIENT_COMMIT_HASH', 'DSH_CLIENT_TITLE', 'DSH_CLIENT_VERSION'}
            or environment['DSH_CLIENT_BUILD_PROFILE'] != 'official'
            or environment['DSH_CLIENT_COMMIT_HASH'] != manifest['target_upstream'][:7]
            or environment['DSH_CLIENT_TITLE'] != 'DeepSeek Harness'
            or not isinstance(environment['DSH_CLIENT_VERSION'], str) or not environment['DSH_CLIENT_VERSION']):
        raise ValueError('frontend official build record differs')
    paths = artifact_paths(root)
    expected = {row['path']:row['sha256'] for row in manifest['files'] + rows}
    actual = {path.relative_to(root).as_posix():digest(path) for path in paths}
    if len(expected) != len(manifest['files']) + len(rows) or expected != actual or build_digest(root,paths) != record.get('artifacts'):
        raise ValueError('frontend complete shell/client build bytes differ')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'reference')
    parser.add_argument('--output-dir', type=Path, required=True)
    options = parser.parse_args()
    source = options.source.resolve()
    output = options.output_dir.resolve()
    output.relative_to(ROOT / '.goose/out')
    output.mkdir(parents=True, exist_ok=False)
    target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
    record, paths = recorded_inputs(source, target)
    selected = {path.relative_to(source).as_posix(): digest(path) for path in paths}
    old_manifest = json.loads((ROOT / 'scripts/frontend-inputs.json').read_text(encoding='utf-8'))
    old_shell = {path.relative_to(ROOT).as_posix(): digest(path) for path in (ROOT / 'apps/web/dist').rglob('*') if path.is_file()}
    if old_shell != {row['path']:row['sha256'] for row in old_manifest['files']}:
        raise ValueError('existing reviewed frontend bytes differ before import')
    previous = set(old_shell) | set(selected) | {'scripts/frontend-inputs.json'}
    before = {name:digest(ROOT / name) for name in sorted(previous) if (ROOT / name).is_file()}
    archive = output / 'previous-artifacts.zip'
    with zipfile.ZipFile(str(archive), 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in before:
            bundle.write(str(ROOT / name), name)
        bundle.writestr('inputs.json', json.dumps(before, indent=2))
    with zipfile.ZipFile(str(archive)) as bundle:
        if bundle.testzip() is not None or any(hashlib.sha256(bundle.read(name)).hexdigest() != value for name,value in before.items()):
            raise ValueError('frontend previous artifact archive failed verification')
    for name,value in selected.items():
        content = (source / name).read_bytes()
        if hashlib.sha256(content).hexdigest() != value:
            raise ValueError('upstream artifact changed during import')
        replace_bytes(ROOT / name, content)
    for name in old_shell:
        if name not in selected:
            path = ROOT / name
            path.resolve().relative_to((ROOT / 'apps/web/dist').resolve())
            if digest(path) != old_shell[name]:
                raise ValueError('obsolete frontend artifact changed before retirement')
            path.unlink()
    manifest = dict(target_upstream=target, kind='versioned-prebuilt-input',
        scope='Exact unchanged pinned upstream official full build imported with its verified complete build record; browser and host protocol acceptance are separate.',
        build_record=record,
        files=[dict(path=name,sha256=value) for name,value in selected.items() if name.startswith('apps/web/dist/')],
        client_files=[dict(path=name,sha256=value) for name,value in selected.items() if name.startswith('packages/')])
    replace_bytes(ROOT / 'scripts/frontend-inputs.json', (json.dumps(manifest,indent=2)+'\n').encode('utf-8'))
    final_record, final_paths = recorded_inputs(source, target)
    if final_record != record or {path.relative_to(source).as_posix():digest(path) for path in final_paths} != selected:
        raise ValueError('upstream build inputs changed during import')
    if any(digest(ROOT / name) != value for name,value in selected.items()):
        raise ValueError('imported frontend bytes differ')
    report = dict(status='imported',sourceRoot=str(source),sourcePin=target,buildRecord=record,
        artifacts=selected,previousArchiveSha256=digest(archive),previousArtifacts=before,
        scope='Complete unchanged Source official build; exact frontend and client bytes imported without browser source edits. Same-directory atomic replacement breaks prior hardlinks before writing. Previous complete artifact bytes preserved; original browser qualification still required.')
    with (output / 'report.json').open('x',encoding='utf-8') as stream:
        json.dump(report,stream,indent=2)
        stream.write('\n')
    print(json.dumps(dict(status=report['status'],artifacts=len(selected),digest=record['artifacts']['sha256'])))


if __name__ == '__main__':
    main()
