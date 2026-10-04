import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = 'f1b3db8ecd39d5b3a6eff4d5641b176c7f914dfb'
TOOLCHAIN_SHA256 = '1e936a4a694fc27f9625e3311f5ec5d6d99abfeaa514fd41c52a4f8347145d1a'
DATA_SHA256 = '7b85654a0bfa6d92ca4ce26515bcdf28d22e1571319d4f80820d227076dbdade'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_inputs(source, toolchain, toolchain_archive, data_archive):
    if digest(toolchain_archive) != TOOLCHAIN_SHA256 or digest(data_archive) != DATA_SHA256:
        raise ValueError('Pinned ICU build archive differs')
    commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
    dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], encoding='utf-8').strip()
    if commit != SOURCE_COMMIT or dirty:
        raise ValueError('ICU build requires the clean pinned release-78.2 source')
    with zipfile.ZipFile(str(toolchain_archive)) as archive:
        prefix = toolchain.name + '/'
        selected = [entry for entry in archive.infolist() if not entry.is_dir()
                    and entry.filename.startswith(prefix)
                    and entry.filename[len(prefix):].split('/')[0] in ('bin', 'include', 'lib', 'x86_64-w64-mingw32')]
        if not selected:
            raise ValueError('Pinned compiler archive layout differs')
        for entry in selected:
            relative = Path(entry.filename[len(prefix):])
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Compiler archive path is invalid')
            if digest(toolchain / relative) != hashlib.sha256(archive.read(entry)).hexdigest():
                raise ValueError('Extracted compiler input differs: ' + str(relative))
    with zipfile.ZipFile(str(data_archive)) as archive:
        if archive.read('LICENSE') != (source / 'LICENSE').read_bytes():
            raise ValueError('ICU source/data license identity differs')
    counts = {category: len((source / 'icu4c/source' / category / 'sources.txt').read_text(encoding='utf-8').split())
              for category in ('common', 'i18n')}
    if counts != dict(common=202, i18n=254):
        raise ValueError('Pinned ICU compilation inventory differs')


def build(source, toolchain, toolchain_archive, data_archive, output):
    checked_inputs(source, toolchain, toolchain_archive, data_archive)
    output.mkdir(parents=True, exist_ok=False)
    compiler = toolchain / 'bin/x86_64-w64-mingw32-clang++.exe'
    dlltool = toolchain / 'bin/x86_64-w64-mingw32-dlltool.exe'
    source_root = source / 'icu4c/source'
    with zipfile.ZipFile(str(data_archive)) as archive:
        (output / 'dsh_icudt78.dll').write_bytes(archive.read('bin64/icudt78.dll'))
    (output / 'data.def').write_text('LIBRARY dsh_icudt78.dll\nEXPORTS\nicudt78_dat DATA\n', encoding='utf-8')
    subprocess.run([str(dlltool), '-d', str(output / 'data.def'), '-l', str(output / 'data.a')], check=True, timeout=30)
    commands = []

    def compile_source(arguments):
        category, name = arguments
        destination = output / category / (Path(name).stem + '.o')
        command = [str(compiler), '-std=c++17', '-O2', '-DNDEBUG', '-D_WIN32_WINNT=0x0601', '-DWINVER=0x0601',
                   '-DU_COMMON_IMPLEMENTATION' if category == 'common' else '-DU_I18N_IMPLEMENTATION',
                   '-I' + str(source_root / 'common'), '-I' + str(source_root / category),
                   '-c', str(source_root / category / name), '-o', str(destination)]
        completed = subprocess.run(command, capture_output=True, encoding='utf-8', errors='replace', timeout=120)
        destination.with_suffix('.log').write_text(completed.stdout + completed.stderr, encoding='utf-8')
        if completed.returncode:
            raise RuntimeError(name + ': ' + completed.stderr[-3000:])
        return destination, command

    for category, binary in [('common', 'dsh_icuuc78.dll'), ('i18n', 'dsh_icuin78.dll')]:
        (output / category).mkdir()
        names = (source_root / category / 'sources.txt').read_text(encoding='utf-8').split()
        print('Compiling ' + category + ': ' + str(len(names)) + ' unchanged sources', flush=True)
        with ThreadPoolExecutor(max_workers=2) as executor:
            compiled = list(executor.map(compile_source, [(category, name) for name in names]))
        commands.extend(command for destination, command in compiled)
        response = output / (category + '.rsp')
        dependencies = [output / 'data.a'] if category == 'common' else [output / 'common.a']
        options = ['-shared', '-static', '-o', str(output / binary),
                   '-Wl,--out-implib,' + str(output / (category + '.a')), '-Wl,--major-subsystem-version,6',
                   '-Wl,--minor-subsystem-version,1', '-Wl,--no-insert-timestamp']
        options.extend(str(destination) for destination, command in compiled)
        options.extend(str(path) for path in dependencies)
        options.append('-ladvapi32')
        response.write_text('\n'.join('"' + item.replace('\\', '/') + '"' for item in options)+'\n', encoding='utf-8')
        command = [str(compiler), '@' + str(response)]
        completed = subprocess.run(command, capture_output=True, encoding='utf-8', errors='replace', timeout=120)
        (output / (category + '-link.log')).write_text(completed.stdout + completed.stderr, encoding='utf-8')
        if completed.returncode:
            raise RuntimeError(completed.stderr[-6000:])
        commands.append(command)
        print('Linked ' + binary, flush=True)
    licenses = {'ICU-LICENSE': source / 'LICENSE', 'LLVM-LICENSE.txt': toolchain / 'LICENSE.TXT'}
    licenses.update({'MinGW-' + path.name: path for path in (toolchain / 'x86_64-w64-mingw32/share/mingw32').glob('COPYING*')})
    for name, path in licenses.items():
        shutil.copy2(str(path), str(output / name))
    manifest = json.loads((ROOT / 'dsh/session/bin/icu/icu.json').read_text(encoding='utf-8'))
    manifest['dll_sha256'] = {name: digest(output / name) for name in manifest['dll_sha256']}
    manifest['license_sha256'] = {name: digest(output / name) for name in licenses}
    (output / 'icu.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    provenance = dict(source=SOURCE_COMMIT, toolchainArchiveSha256=TOOLCHAIN_SHA256,
                      dataArchiveSha256=DATA_SHA256, commands=commands,
                      compiler=subprocess.check_output([str(compiler), '--version'], encoding='utf-8'),
                      binaries=manifest['dll_sha256'], deterministicPeTimestamp=True)
    (output / 'build-provenance.json').write_text(json.dumps(provenance, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(manifest['dll_sha256']), flush=True)


def main():
    parser = argparse.ArgumentParser()
    for name in ('source', 'toolchain', 'toolchain-archive', 'data-archive', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    options = parser.parse_args()
    build(options.source.resolve(), options.toolchain.resolve(), options.toolchain_archive.resolve(),
          options.data_archive.resolve(), options.output.resolve())


if __name__ == '__main__':
    main()
