import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile


SOURCE_COMMIT = 'f8745da6ff1ad1e7bab384bd1f9d742439278e99'
COMPILER_ARCHIVE_SHA256 = '1e936a4a694fc27f9625e3311f5ec5d6d99abfeaa514fd41c52a4f8347145d1a'
COMPILER_SHA256 = '821f0bc3eca2915569861955f07fe615b2339efa97b62d45c59968a8d989c68c'
DLL_SHA256 = '93d87fd026179637db29580e1db2d1188954241293f0e2279f93a01e007a45cc'
DICTIONARY_SHA256 = 'dad18fa0247a8fdd886a62d8552eabd36cbd50c25af172873080d2f0ae770d17'
ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_inputs(source, compiler):
    source, compiler = source.resolve(), compiler.resolve()
    commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
    dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], encoding='utf-8').strip()
    if commit != SOURCE_COMMIT or dirty:
        raise ValueError('Zstandard build requires the unchanged pinned source')
    compiler_archive = compiler.parent.parent.with_suffix('.zip')
    if (not compiler.is_file() or 'msvcrt' not in str(compiler) or digest(compiler) != COMPILER_SHA256
            or digest(compiler_archive) != COMPILER_ARCHIVE_SHA256):
        raise ValueError('Zstandard build requires the pinned MSVCRT compiler')
    toolchain = compiler.parent.parent
    with zipfile.ZipFile(str(compiler_archive)) as archive:
        prefix = toolchain.name + '/'
        selected = [entry for entry in archive.infolist() if not entry.is_dir()
                    and entry.filename.startswith(prefix)
                    and entry.filename[len(prefix):].split('/')[0] in ('bin', 'include', 'lib', 'x86_64-w64-mingw32')]
        if not selected:
            raise ValueError('Pinned Zstandard compiler archive layout differs')
        for entry in selected:
            relative = Path(entry.filename[len(prefix):])
            if relative.is_absolute() or '..' in relative.parts or ':' in str(relative):
                raise ValueError('Pinned Zstandard compiler archive path is invalid')
            if digest(toolchain / relative) != hashlib.sha256(archive.read(entry)).hexdigest():
                raise ValueError('Extracted Zstandard compiler differs: ' + str(relative))
    return commit


def build(source, compiler, output):
    source, compiler, output = source.resolve(), compiler.resolve(), output.resolve()
    commit = checked_inputs(source, compiler)
    if output.exists():
        raise ValueError('Zstandard build output must be a new directory')
    output.mkdir(parents=True)
    objects, commands, inputs = [], [], {}
    for category in ('common', 'compress', 'decompress', 'dictBuilder'):
        for item in sorted((source / 'lib' / category).glob('*.c')):
            destination = output / (category + '-' + item.stem + '.o')
            command = [str(compiler), '-std=c99', '-O2', '-DNDEBUG', '-D_WIN32_WINNT=0x0601', '-DWINVER=0x0601',
                       '-DZSTD_DLL_EXPORT=1', '-DZSTD_DISABLE_ASM=1', '-DDYNAMIC_BMI2=0', '-I' + str(source / 'lib'),
                       '-I' + str(source / 'lib/common'), '-c', str(item), '-o', str(destination)]
            subprocess.run(command, check=True)
            inputs[item.relative_to(source).as_posix()] = digest(item)
            objects.append(str(destination))
            commands.append(command)
    binary = output / 'zstd.dll'
    command = [str(compiler), '-shared', '-static', '-o', str(binary), '-Wl,--major-subsystem-version,6',
               '-Wl,--minor-subsystem-version,1', '-Wl,--no-insert-timestamp'] + objects
    subprocess.run(command, check=True)
    commands.append(command)
    license_directory = output / 'licenses'
    license_directory.mkdir()
    shutil.copy2(source / 'LICENSE', license_directory / 'ZSTD-LICENSE')
    for path in (ROOT / 'dsh/session/bin/icu').glob('*'):
        if path.name.startswith(('LLVM-LICENSE', 'MinGW-COPYING')):
            shutil.copy2(path, license_directory / path.name)
    provenance = dict(version='1.5.7', source_commit=commit, source_inputs=inputs, commands=commands,
        compiler=subprocess.check_output([str(compiler), '--version'], encoding='utf-8'), compiler_sha256=digest(compiler),
        compiler_archive_sha256=COMPILER_ARCHIVE_SHA256, sha256=digest(binary), size=binary.stat().st_size,
        licenses={path.name: digest(path) for path in sorted(license_directory.iterdir())},
        scope='Unchanged-source Windows x64/MSVCRT build targeting Windows 6.1; not real Win7 execution certification.')
    (output / 'build-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(binary=str(binary), sha256=provenance['sha256'], source_files=len(inputs))))


def stage(output, destination):
    provenance = json.loads((output / 'build-provenance.json').read_text(encoding='utf-8'))
    dictionary = ROOT / 'reference/packages/session/session-persistence-sqlite/resources/zstd-dictionary.bin'
    if (provenance['source_commit'] != SOURCE_COMMIT or provenance['compiler_sha256'] != COMPILER_SHA256
            or provenance['compiler_archive_sha256'] != COMPILER_ARCHIVE_SHA256
            or provenance['sha256'] != DLL_SHA256 or digest(output / 'zstd.dll') != DLL_SHA256
            or digest(dictionary) != DICTIONARY_SHA256):
        raise ValueError('Zstandard staging provenance differs')
    from dsh.session.icu_collation import verify_icu_files
    _, compiler_licenses = verify_icu_files()
    expected_licenses = {name: value for name, value in compiler_licenses['license_sha256'].items() if name != 'ICU-LICENSE'}
    expected_licenses['ZSTD-LICENSE'] = '7055266497633c9025b777c78eb7235af13922117480ed5c674677adc381c9d8'
    if provenance['licenses'] != expected_licenses:
        raise ValueError('Zstandard staging license manifest differs')
    for name, expected in expected_licenses.items():
        if digest(output / 'licenses' / name) != expected:
            raise ValueError('Zstandard staging license differs: ' + name)
    if destination.exists():
        raise ValueError('Zstandard staging destination must be new')
    destination.mkdir(parents=True)
    shutil.copy2(output / 'zstd.dll', destination / 'dsh_zstd.dll')
    shutil.copy2(dictionary, destination / 'zstd-dictionary.bin')
    for name in expected_licenses:
        shutil.copy2(output / 'licenses' / name, destination / name)
    shutil.copy2(output / 'build-provenance.json', destination / 'build-provenance.json')
    manifest = dict(version='1.5.7', source_commit=SOURCE_COMMIT, dictionary_sha256=DICTIONARY_SHA256,
                    dll_sha256=DLL_SHA256, license_sha256=expected_licenses,
                    provenance_sha256=digest(destination / 'build-provenance.json'))
    (destination / 'zstd.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage-output', type=Path)
    parser.add_argument('--stage-only', action='store_true')
    args = parser.parse_args()
    if args.stage_only:
        checked_inputs(args.source, args.compiler)
    if not args.stage_only:
        build(args.source, args.compiler, args.output)
    if args.stage_output:
        import sys
        sys.path.insert(0, str(ROOT))
        stage(args.output, args.stage_output)


if __name__ == '__main__':
    main()
