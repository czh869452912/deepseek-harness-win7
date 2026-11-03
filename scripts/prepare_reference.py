"""Prepare ignored pinned Source dependencies and the sealed original frontend.

The frontend is restored from its original observed carrier, never relabelled
from a rebuild at a different absolute path. No tracked Source bytes change.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import import_frontend
ARCHIVE = 'migration/evidence/artifacts/OFFICIAL-FRONTEND-QUALIFICATION-20261007-8D129C7D.zip'
ARCHIVE_SHA256 = 'b2ef057fe8308932708b76b1ef47576bda9b8ba27c9585a0886b6a1002d75abc'
STATIC_CLIENT_LIBRARIES = ('web', 'store', 'ui-slots', 'ui-primitives', 'ui-dockkit')


def restore_frontend(root, source):
    root, source = Path(root), Path(source)
    manifest = json.loads((root / 'scripts/frontend-inputs.json').read_text(encoding='utf-8'))
    pin = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
    dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], encoding='utf-8').strip()
    if pin != manifest['target_upstream'] or dirty:
        raise ValueError('Frontend restore requires the unchanged pinned Source')
    carrier = manifest.get('original_carrier', dict(path=ARCHIVE, sha256=ARCHIVE_SHA256))
    archive = root / carrier['path']
    archive.resolve().relative_to(root.resolve())
    if import_frontend.digest(archive) != carrier['sha256']:
        raise ValueError('Original frontend observation carrier differs')
    with zipfile.ZipFile(str(archive)) as bundle:
        if bundle.testzip() is not None:
            raise ValueError('Original frontend observation carrier CRC differs')
        record = bundle.read('proposed/reference/.dsh-build/client-build-environment.json')
        if json.loads(record) != manifest['build_record']:
            raise ValueError('Original frontend build record differs')
        payloads = {row['path']: bundle.read('imported/' + row['path']) for row in manifest['files'] + manifest['client_files']}
        for row in manifest['files'] + manifest['client_files']:
            if hashlib.sha256(payloads[row['path']]).hexdigest() != row['sha256']:
                raise ValueError('Original frontend member differs: ' + row['path'])
        payloads['.dsh-build/client-build-environment.json'] = record
    # Refuse unknown existing observations and reparse destinations. Fresh
    # files are atomically placed; identical originals are left in place.
    for name, content in payloads.items():
        target = source / name
        for parent in (target,) + tuple(target.parents):
            if parent == source.parent:
                break
            if parent.exists() and (parent.is_symlink() or getattr(os.lstat(str(parent)), 'st_file_attributes', 0) & 0x400):
                raise ValueError('Frontend restore reparse destination refused')
        if target.exists() and target.read_bytes() != content:
            raise ValueError('Frontend restore refuses an existing different observation: ' + name)
    restored = []
    for name, content in payloads.items():
        target = source / name
        if not target.exists():
            import_frontend.replace_bytes(target, content)
            restored.append(name)
    actual, paths = import_frontend.recorded_inputs(source, manifest['target_upstream'])
    if actual != manifest['build_record'] or {p.relative_to(source).as_posix(): import_frontend.digest(p) for p in paths} != {
            row['path']: row['sha256'] for row in manifest['files'] + manifest['client_files']}:
        raise ValueError('Restored original frontend observations differ')
    return dict(originalCarrier=carrier['path'], sha256=carrier['sha256'], restored=restored, buildRecord=actual,
                scope='Original sealed build bytes, not a build at the current checkout path')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    output = options.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = ROOT / 'reference'
    target = json.loads((ROOT / 'scripts/frontend-inputs.json').read_text(encoding='utf-8'))['target_upstream']
    pin = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
    dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], encoding='utf-8').strip()
    if pin != target or dirty:
        raise ValueError('Preparation requires the unchanged pinned Source before install/build')
    package = json.loads((source / 'package.json').read_text(encoding='utf-8'))
    pnpm = ROOT / 'scripts/source-runtime/node_modules/pnpm/bin/pnpm.mjs'
    version = subprocess.check_output(['node', str(pnpm), '--version'], encoding='utf-8').strip()
    if package['packageManager'] != 'pnpm@' + version or version != '11.7.0':
        raise ValueError('Pinned Source package manager differs')
    commands = []
    for name, args in [
        ('install', ['install', '--frozen-lockfile']),
        ('host-build', ['run', 'build:lib:host']),
        ('client-types', ['exec', 'tsc', '-b', 'tsconfig.client.json']),
        # These libraries are linked into the sealed shell. Refresh their
        # ignored Node entries for Source consumers without rebuilding or
        # replacing any original frontend/browser bundle observation.
    ] + [('static-client-' + name, ['exec', 'tsdown', '--env.DSH_BUILD_FACE', 'client',
             '--filter', '@deepseek-ai/dsh-client-' + name])
         for name in STATIC_CLIENT_LIBRARIES]:
        command = ['node', str(pnpm), '--dir', str(source)] + args
        environment = dict(os.environ, CI='true')
        with (output / (name + '.log')).open('xb') as log:
            result = subprocess.run(command, cwd=str(ROOT), env=environment,
                                    stdout=log, stderr=subprocess.STDOUT, timeout=1800)
        commands.append(dict(command=command, exit_code=result.returncode))
        if result.returncode:
            raise RuntimeError('Pinned Source ' + name + ' failed; see ' + str(output / (name + '.log')))
    result = dict(pnpm=version, commands=commands, frontend=restore_frontend(ROOT, source))
    (output / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status='prepared', pnpm=version, restored=len(result['frontend']['restored']))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
