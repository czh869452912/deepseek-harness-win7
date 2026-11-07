"""Build the pinned Electron22/Python3.8 desktop and Standard/AIO NSIS packages.

All generated output belongs to one fresh directory. Offline Microsoft payloads
remain external inputs and are never copied into Git. Building runs no installer.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_portable import VERSION, build_portable
from scripts.windows_prerequisites import stage_prerequisites, validate_prerequisites, verify_file


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(data)
    return result.hexdigest()


def plain_tree(directory):
    directory = Path(directory).absolute()
    if directory.resolve() != directory:
        raise ValueError('Desktop input/output traverses a link')
    for parent, directories, filenames in os.walk(str(directory), followlinks=False):
        for name in directories + filenames:
            path = Path(parent) / name
            metadata = path.lstat()
            if path.is_symlink() or getattr(metadata, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Desktop tree contains a linked path: ' + str(path))
            if path.is_file() and metadata.st_nlink != 1:
                raise ValueError('Desktop tree contains a shared file: ' + str(path))
    return directory


def extract_tool(archive, identity, destination):
    verify_file(archive, identity)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(str(archive)) as stream:
        names = set()
        for member in stream.infolist():
            path = Path(member.filename)
            if (path.is_absolute() or '..' in path.parts or chr(92) in member.filename or ':' in member.filename
                    or member.filename.lower() in names or member.external_attr >> 28 == 0xA):
                raise ValueError('Unsafe or duplicate tool archive member')
            names.add(member.filename.lower())
        stream.extractall(str(destination))
    plain_tree(destination)


def validate_portable(directory, architecture='x64'):
    directory = plain_tree(directory)
    required = ('python.exe', 'python38.dll', 'dsh.py', 'apps/web/dist/index.html',
                'dsh/host/desktop/process.py', 'dsh/host/desktop/health_transaction.py')
    if not all((directory / name).is_file() for name in required):
        raise ValueError('Desktop needs the complete current Portable payload')
    provenance = json.loads((directory / 'build-provenance.json').read_text(encoding='utf-8'))
    if provenance.get('python_runtime', {}).get('version') != [3, 8, 10]:
        raise ValueError('Desktop requires Python3.8.10')
    if provenance['python_runtime'].get('bits') != (32 if architecture == 'x86' else 64):
        raise ValueError('Desktop Portable architecture differs')
    # Reject a stale manually supplied Portable: providers and original bundles
    # must match this checkout. The receipt retains its original provenance.
    for prefix in ('dsh', 'apps/web/dist', 'packages'):
        expected = {path.relative_to(ROOT / prefix).as_posix(): path for path in (ROOT / prefix).rglob('*')
                    if path.is_file() and not {'__pycache__','node_modules','.git'}.intersection(path.parts)
                    and path.suffix not in ('.pyc','.tsbuildinfo')}
        actual = {path.relative_to(directory / prefix).as_posix(): path for path in (directory / prefix).rglob('*')
                  if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc'}
        if set(expected) != set(actual) or any(digest(path) != digest(actual[name]) for name, path in expected.items()):
            raise ValueError('Portable payload differs from current source: ' + prefix)
    return provenance


def inventory(directory):
    directory = plain_tree(directory)
    return [dict(path=path.relative_to(directory).as_posix(), bytes=path.stat().st_size, sha256=digest(path))
            for path in sorted(directory.rglob('*')) if path.is_file()]


def desktop_package_inputs(portable, destination):
    """Use the reviewed Python-host/browser closure, not upstream build/tests."""
    selected = {}
    for manifest_name in ('runtime-inputs.json','frontend-inputs.json'):
        manifest = json.loads((ROOT / 'scripts' / manifest_name).read_text(encoding='utf-8'))
        # The frontend manifest separates shell files from original plugin
        # bundles. Both lists form the pinned complete browser build.
        for row in manifest['files'] + manifest.get('native_files', []) + manifest.get('client_files', []):
            if row['path'].startswith('packages/'):
                if row['path'] in selected and selected[row['path']] != row['sha256']:
                    raise ValueError('Conflicting package input identity')
                selected[row['path']] = row['sha256']
    for path in (ROOT / 'packages').glob('*/*/*'):
        if path.is_file() and path.name.upper().startswith(('LICENSE','COPYING','NOTICE')):
            selected[path.relative_to(ROOT).as_posix()] = digest(path)
    # Native profile aliases also have product-owned bundle patches. These are
    # consumed on import by the public compatibility facade, before boot.
    for path in (ROOT / 'packages/bundle').glob('*/cordis.patch.yml'):
        selected[path.relative_to(ROOT).as_posix()] = digest(path)
    for name, expected in sorted(selected.items()):
        source = Path(portable) / name
        if digest(source) != expected:
            raise ValueError('Reviewed Desktop package input differs: ' + name)
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(source), str(target))
    return dict(files=len(selected),scope='Pinned runtime manifests, presets, strict host descriptors, original client bundles/maps and package licenses')


def desktop_source_inputs():
    manifest = json.loads((ROOT / 'apps/desktop/source-input.json').read_text(encoding='utf-8'))
    baseline = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))
    if manifest['sourceCommit'] != baseline['target_upstream']:
        raise ValueError('Desktop Source inputs differ from the pinned target')
    for row in manifest['inputs']:
        if (digest(ROOT / row['target']) != row['sha256'] or
                digest(ROOT / 'reference' / row['source']) != row['sourceSha256']):
            raise ValueError('Desktop generated/original bytes differ: ' + row['target'])
    return manifest


def nsis_define(value):
    value = str(value)
    if any(character in value for character in ('"', '\n', '\r')):
        raise ValueError('Unsafe NSIS define')
    return value.replace('$', '$$')


def build(args):
    architecture = args.architecture
    if architecture not in ('x64', 'x86'):
        raise ValueError('Unsupported Desktop architecture')
    if architecture == 'x86' and args.portable_dir is None:
        raise ValueError('x86 Desktop requires an explicit qualified --portable-dir')
    editions = ('standard', 'aio') if args.edition == 'both' else (args.edition,)
    if 'aio' in editions and args.external_prereq_dir is None:
        raise ValueError('AIO requires --external-prereq-dir with fixed Microsoft offline files')
    tools = json.loads((ROOT / 'scripts/desktop-tool-inputs.json').read_text(encoding='utf-8'))
    if architecture == 'x86':
        inputs = json.loads((ROOT / 'scripts/x86-inputs.json').read_text(encoding='utf-8'))
        electron = next(row for row in inputs['downloads'] if row['name'] == 'electron-v22.3.27-win32-ia32.zip')
        tools['electron'] = dict(electron, version='22.3.27', architecture='x86')
    source_inputs = desktop_source_inputs()
    update_config = getattr(args, 'update_config', None)
    update_bytes = None
    if update_config is not None:
        update_bytes = update_config.read_bytes()
        if len(update_bytes) > 16384:
            raise ValueError('Desktop update configuration exceeds its byte limit')
        # Validate with the same Node16 implementation shipped in the shell;
        # validation executes after extracting the exact Electron runtime below.
        json.loads(update_bytes.decode('utf-8'))
    installer_inputs = {name: (ROOT / 'apps/desktop/installer' / name).read_bytes()
                        for name in ('setup.nsi','prerequisites.ps1','uninstall-files.ps1','publish-installation.ps1')}
    verify_file(args.electron_archive, tools['electron'])
    verify_file(args.nsis_archive, tools['nsis'])
    if 'aio' in editions:
        for system_arch in (('x86', 'x64') if architecture == 'x86' else ('x64',)):
            validate_prerequisites(args.external_prereq_dir, system_arch)
    output = Path(args.output_dir).absolute()
    if output.exists() or output.resolve() != output:
        raise ValueError('Desktop output must be a fresh directory without linked ancestors')
    if any(output == ROOT / name or output in (ROOT / name).parents or ROOT / name in output.parents
           for name in ('dsh', 'apps', 'packages', 'scripts', 'reference')):
        raise ValueError('Desktop output overlaps source inputs')
    output.mkdir(parents=True)
    frozen = output / 'installer-inputs'
    frozen.mkdir()
    for name, data in installer_inputs.items():
        (frozen / name).write_bytes(data)
    record = dict(schema=1,status='building',version=VERSION,architecture=architecture,tools=tools,sourceInputs=source_inputs,editions=list(editions),
                  installerInputs={name:hashlib.sha256(data).hexdigest() for name,data in installer_inputs.items()},
                  installationExecuted=False,releaseQualified=False)
    report = output / 'desktop-build.json'
    try:
        if args.portable_dir is None:
            portable, _ = build_portable(output_dir=str(output / 'portable'))
        else:
            portable = args.portable_dir
        record['portable'] = validate_portable(portable, architecture)
        unpacked = output / 'desktop-unpacked'
        extract_tool(args.electron_archive, tools['electron'], unpacked)
        (unpacked / 'electron.exe').rename(unpacked / 'DeepSeek Harness.exe')
        default_app = unpacked / 'resources/default_app.asar'
        if default_app.exists():
            default_app.unlink()
        if update_bytes is not None:
            configuration_path = unpacked / 'resources/win7-update.json'
            configuration_path.write_bytes(update_bytes)
            environment = dict(os.environ, ELECTRON_RUN_AS_NODE='1')
            validation = "require(process.argv[1]).configuration(JSON.parse(require('fs').readFileSync(process.argv[2],'utf8')))"
            subprocess.run([str(unpacked / 'DeepSeek Harness.exe'), '-e', validation,
                            str(ROOT / 'apps/desktop/updates.cjs'), str(configuration_path)],
                           env=environment, check=True, capture_output=True, timeout=30)
            record['updateConfiguration'] = dict(sha256=hashlib.sha256(update_bytes).hexdigest(), channel='win7-electron22')
        application = unpacked / 'resources/app'
        application.mkdir()
        for source in sorted((ROOT / 'apps/desktop').glob('*.cjs')):
            if source.name != 'smoke-test.cjs':
                shutil.copyfile(str(source), str(application / source.name))
        for filename in ('package.json', 'tray.png', 'source-input.json', 'win7-setup.html'):
            shutil.copyfile(str(ROOT / 'apps/desktop' / filename), str(application / filename))
        shutil.copytree(str(ROOT / 'apps/desktop/renderer'), str(application / 'renderer'))
        harness = unpacked / 'resources/harness'
        shutil.copytree(str(portable), str(harness),
                        ignore=lambda directory,names: ['packages'] if Path(directory) == Path(portable) else [])
        record['packageClosure'] = desktop_package_inputs(portable, harness)
        shutil.copytree(str(ROOT / 'apps/desktop-host'), str(unpacked / 'resources/harness/apps/desktop-host'))
        # Qualify the actual extracted closure before spending time compressing
        # installers. The observer executes the bundled Electron's Node16 and
        # bundled Python, including cold recovery and forced tree cleanup.
        environment = {name:value for name,value in os.environ.items()
                       if not re.search(r'(?:^|_)(?:API_KEY|API_TOKEN|ACCESS_TOKEN|REFRESH_TOKEN|OAUTH_TOKEN)$',name,re.I)
                       and name.upper() not in ('DSH_HOME','PYTHONPATH','PYTHONHOME','NODE_OPTIONS')}
        environment.update(ELECTRON_RUN_AS_NODE='1',PYTHONDONTWRITEBYTECODE='1')
        command = [str(unpacked / 'DeepSeek Harness.exe'),str(ROOT / 'scripts/oracles/desktop_process_current.cjs'),
                   '--python',str(harness / 'python.exe'),'--root',str(harness),
                   '--shell-dir',str(application),'--output',str(output / 'pipe-preflight')]
        with (output / 'pipe-preflight.log').open('w',encoding='utf-8') as log:
            subprocess.run(command,env=environment,stdout=log,stderr=subprocess.STDOUT,timeout=180,check=True)
        preflight = output / 'pipe-preflight/report.json'
        observed = json.loads(preflight.read_text(encoding='utf-8'))
        if observed.get('status') != 'qualified' or len(observed.get('checks',[])) != 9:
            raise ValueError('Actual packaged Node16/Python preflight failed')
        record['pipePreflight'] = dict(path='pipe-preflight/report.json',sha256=digest(preflight),checks=observed['checks'])
        staged = []
        if 'aio' in editions:
            # The ia32 shell also runs on x64 Windows. Servicing packages
            # must match the OS; the common .NET installer is copied once.
            staged = stage_prerequisites(args.external_prereq_dir,
                'both' if architecture == 'x86' else 'x64', output / 'prerequisites')
        record['prerequisites'] = staged
        rows = inventory(unpacked)
        owned = ''.join(row['sha256'] + '\t' + row['path'] + '\n' for row in rows)
        (unpacked / 'dsh-owned-files.tsv').write_bytes(owned.encode('utf-8'))
        generation = VERSION + '-' + hashlib.sha256(owned.encode('utf-8')).hexdigest()[:12]
        max_root = 240 - len('/versions/' + generation + '/') - max(len(row['path'].encode('utf-16-le')) // 2 for row in rows)
        if max_root < 40:
            raise ValueError('Desktop payload paths leave insufficient Win7 installation space')
        record['generation'] = generation
        record['payload'] = dict(files=len(rows),bytes=sum(row['bytes'] for row in rows),
                                 inventorySha256=hashlib.sha256(owned.encode('utf-8')).hexdigest())
        extract_tool(args.nsis_archive, tools['nsis'], output / 'nsis')
        compiler = output / 'nsis/nsis-3.13/makensis.exe'
        artifacts = []
        for edition in editions:
            filename = 'dsh-desktop-' + edition + '-setup-v' + VERSION + '-' + architecture + '.exe'
            definitions = dict(VERSION=VERSION,EDITION=edition,ARCHITECTURE=architecture,OUTPUT=output / filename,
                               GENERATION=generation,PAYLOAD=unpacked,
                               POLICY=frozen / 'prerequisites.ps1',
                               CLEANUP=frozen / 'uninstall-files.ps1',PUBLICATION=frozen / 'publish-installation.ps1',MAX_INSTALL_ROOT=max_root,
                               PREREQUISITES=output / 'prerequisites')
            command = [str(compiler), '/V3'] + ['/D' + name + '=' + nsis_define(value) for name, value in definitions.items()]
            command.append(str(frozen / 'setup.nsi'))
            with (output / (edition + '-nsis.log')).open('w', encoding='utf-8') as log:
                subprocess.run(command, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
                               encoding='utf-8', check=True, timeout=1800)
            artifact = output / filename
            artifacts.append(dict(path=filename,bytes=artifact.stat().st_size,sha256=digest(artifact)))
        record.update(status='built',artifacts=artifacts)
        return record
    except BaseException as error:
        record.update(status='failed',error=str(error))
        raise
    finally:
        report.write_text(json.dumps(record,indent=2) + '\n',encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edition', choices=('standard','aio','both'), default='standard')
    parser.add_argument('--architecture', choices=('x64','x86'), default='x64')
    parser.add_argument('--external-prereq-dir', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--portable-dir', type=Path)
    parser.add_argument('--update-config', type=Path,
                        help='Optional Win7 channel HTTPS URL and Ed25519 public key; absent leaves updates idle')
    parser.add_argument('--electron-archive', type=Path, default=ROOT / '.goose/tools/electron-22.3.27-win32-x64/electron-v22.3.27-win32-x64.zip')
    parser.add_argument('--nsis-archive', type=Path, default=ROOT / '.goose/tools/nsis-3.13/nsis-3.13.zip')
    args = parser.parse_args()
    print(json.dumps(build(args),indent=2))


if __name__ == '__main__':
    main()
