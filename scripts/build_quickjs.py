import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = '6d46d07d04041b40f4f49eaa7fdebe44c314c699'
SOURCE_ARCHIVE_SHA256 = 'd0d41bf4842480ca8672a856eb86cb2d5cb6aae008072c9fe91786f9185a0692'
COMPILER_ARCHIVE_SHA256 = '1e936a4a694fc27f9625e3311f5ec5d6d99abfeaa514fd41c52a4f8347145d1a'
COMPILER_SHA256 = '821f0bc3eca2915569861955f07fe615b2339efa97b62d45c59968a8d989c68c'
BINARY_SHA256 = '26609aa1d86b3d4f8509859ad94d79229b40abd9978f4faf0d237c45e88259aa'


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            value.update(chunk)
    return value.hexdigest()


def verify_archive(archive_path, directory, expected, categories=None):
    if digest(archive_path) != expected:
        raise ValueError('Pinned build archive differs: ' + str(archive_path))
    selected = {}
    with zipfile.ZipFile(str(archive_path)) as archive:
        prefix = directory.name + '/'
        for entry in archive.infolist():
            if entry.is_dir() or not entry.filename.startswith(prefix):
                continue
            relative = Path(entry.filename[len(prefix):])
            if relative.is_absolute() or '..' in relative.parts or ':' in str(relative):
                raise ValueError('Invalid pinned build archive path')
            if categories is not None and relative.parts[0] not in categories:
                continue
            expected_hash = hashlib.sha256(archive.read(entry)).hexdigest()
            if digest(directory / relative) != expected_hash:
                raise ValueError('Extracted build input differs: ' + str(relative))
            selected[relative.as_posix()] = expected_hash
    if not selected:
        raise ValueError('Pinned build archive has no selected inputs')
    actual = {path.relative_to(directory).as_posix() for path in directory.rglob('*') if path.is_file()
              and (categories is None or path.relative_to(directory).parts[0] in categories)}
    if actual != set(selected):
        raise ValueError('Extracted build input inventory differs')
    return selected


def build(source, compiler, output):
    source, compiler, output = source.resolve(), compiler.resolve(), output.resolve()
    inputs = verify_archive(source.with_suffix('.zip'), source, SOURCE_ARCHIVE_SHA256)
    toolchain = compiler.parent.parent
    toolchain_inputs = verify_archive(toolchain.with_suffix('.zip'), toolchain, COMPILER_ARCHIVE_SHA256,
                                     ('bin', 'include', 'lib', 'x86_64-w64-mingw32'))
    if digest(compiler) != COMPILER_SHA256 or 'msvcrt' not in toolchain.name:
        raise ValueError('QuickJS requires the pinned x64 MSVCRT compiler')
    if output.exists():
        raise ValueError('QuickJS build output must be a new directory')
    wrapper = ROOT / 'scripts/native/quickjs_worker.c'
    output.mkdir(parents=True)
    binary = output / 'dsh_js_worker.exe'
    command = [str(compiler), '-O2', '-std=c11', '-D_GNU_SOURCE', '-DNDEBUG', '-DWIN32_LEAN_AND_MEAN',
               '-D_WIN32_WINNT=0x0601', '-DWINVER=0x0601', '-I' + str(source), str(wrapper)]
    command.extend(str(source / name) for name in ('dtoa.c', 'libregexp.c', 'libunicode.c', 'quickjs.c'))
    command.extend(['-static', '-pthread', '-Wl,--no-insert-timestamp',
                    '-Wl,--major-os-version,6,--minor-os-version,1,--major-subsystem-version,6,--minor-subsystem-version,1',
                    '-o', str(binary)])
    subprocess.run(command, check=True)
    audit = subprocess.run([str(compiler.parent / 'llvm-readobj.exe'), '--file-headers', '--coff-imports', str(binary)],
                           check=True, stdout=subprocess.PIPE, encoding='utf-8').stdout
    (output / 'pe-audit.txt').write_text(audit, encoding='utf-8')
    imports = re.findall(r'^  Name: (\S+)', audit, re.MULTILINE)
    if sorted(imports) != ['KERNEL32.dll', 'msvcrt.dll']:
        raise ValueError('QuickJS has unexpected runtime DLL imports')
    for field, expected in [('MajorOperatingSystemVersion', 6), ('MinorOperatingSystemVersion', 1),
                            ('MajorSubsystemVersion', 6), ('MinorSubsystemVersion', 1)]:
        if re.findall(r'^  ' + field + r': (\d+)$', audit, re.MULTILINE) != [str(expected)]:
            raise ValueError('QuickJS PE Windows version differs')
    licenses = output / 'licenses'
    licenses.mkdir()
    shutil.copy2(source / 'LICENSE', licenses / 'QUICKJS-LICENSE')
    notices = []
    for path in sorted(source.iterdir()):
        if path.suffix not in ('.c', '.h'):
            continue
        text = path.read_text(encoding='utf-8')
        for block in re.findall(r'/\*.*?\*/', text, re.DOTALL):
            if re.search(r'copyright|permission is hereby|redistribution and use', block, re.IGNORECASE):
                notices.append(path.name + '\n' + block)
    if not any('Marcin Kolny' in notice for notice in notices):
        raise ValueError('QuickJS atomics license notice is missing')
    (licenses / 'QUICKJS-NOTICES.txt').write_text('\n\n'.join(notices) + '\n', encoding='utf-8')
    for path in (ROOT / 'dsh/session/bin/icu').iterdir():
        if path.name.startswith(('LLVM-LICENSE', 'MinGW-COPYING')):
            shutil.copy2(path, licenses / path.name)
    provenance = dict(version='0.17.0', source_commit=SOURCE_COMMIT, source_archive_sha256=SOURCE_ARCHIVE_SHA256,
                      source_inputs=inputs, compiler_sha256=COMPILER_SHA256,
                      compiler_archive_sha256=COMPILER_ARCHIVE_SHA256, toolchain_inputs=toolchain_inputs,
                      wrapper_path=wrapper.relative_to(ROOT).as_posix(), wrapper_sha256=digest(wrapper),
                      command=command, binary_sha256=digest(binary), binary_size=binary.stat().st_size,
                      audit_sha256=digest(output / 'pe-audit.txt'), imported_dlls=imports,
                      licenses={path.name: digest(path) for path in sorted(licenses.iterdir())},
                      scope='Private unchanged QuickJS-NG source with an owned two-realm process wrapper. Windows6.1 PE targeting and import inspection; real Win7 execution is not certified.')
    (output / 'build-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(binary=str(binary), sha256=provenance['binary_sha256'], source_files=len(inputs))))


def stage(output, destination):
    output, destination = output.resolve(), destination.resolve()
    provenance = json.loads((output / 'build-provenance.json').read_text(encoding='utf-8'))
    wrapper = ROOT / 'scripts/native/quickjs_worker.c'
    if (provenance['binary_sha256'] != BINARY_SHA256 or digest(output / 'dsh_js_worker.exe') != BINARY_SHA256
            or provenance['source_commit'] != SOURCE_COMMIT or provenance['source_archive_sha256'] != SOURCE_ARCHIVE_SHA256
            or provenance['compiler_sha256'] != COMPILER_SHA256
            or provenance['compiler_archive_sha256'] != COMPILER_ARCHIVE_SHA256
            or provenance['wrapper_sha256'] != digest(wrapper)
            or provenance['audit_sha256'] != digest(output / 'pe-audit.txt')):
        raise ValueError('QuickJS staging provenance differs')
    for name, expected in provenance['licenses'].items():
        if Path(name).name != name or digest(output / 'licenses' / name) != expected:
            raise ValueError('QuickJS staging license differs')
    if destination.exists():
        raise ValueError('QuickJS staging destination must be new')
    destination.mkdir(parents=True)
    shutil.copy2(output / 'dsh_js_worker.exe', destination / 'dsh_js_worker.exe')
    for name in ('build-provenance.json', 'pe-audit.txt'):
        shutil.copy2(output / name, destination / name)
    for name in provenance['licenses']:
        shutil.copy2(output / 'licenses' / name, destination / name)
    resources = {path.name: digest(path) for path in sorted(destination.iterdir()) if path.name != 'dsh_js_worker.exe'}
    manifest = dict(version='0.17.0', source_commit=SOURCE_COMMIT, binary_sha256=BINARY_SHA256, resources=resources)
    (destination / 'runtime.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(staged=str(destination), manifest_sha256=digest(destination / 'runtime.json'))))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage-output', type=Path)
    parser.add_argument('--stage-only', action='store_true')
    args = parser.parse_args()
    if args.stage_only:
        verify_archive(args.source.resolve().with_suffix('.zip'), args.source.resolve(), SOURCE_ARCHIVE_SHA256)
        compiler = args.compiler.resolve()
        toolchain = compiler.parent.parent
        verify_archive(toolchain.with_suffix('.zip'), toolchain, COMPILER_ARCHIVE_SHA256,
                       ('bin', 'include', 'lib', 'x86_64-w64-mingw32'))
        if digest(compiler) != COMPILER_SHA256:
            raise ValueError('QuickJS staging compiler differs')
    else:
        build(args.source, args.compiler, args.output)
    if args.stage_output:
        stage(args.output, args.stage_output)


if __name__ == '__main__':
    main()
