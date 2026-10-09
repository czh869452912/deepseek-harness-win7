import hashlib
import subprocess
import argparse
import json
import platform
import os
import shutil
import sys
import zipfile
import tempfile
import importlib.metadata
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
DIST_DIR = os.path.join(ROOT_DIR, "dist", "dsh-win7-portable")
VERSION = "0.1.0"
ZIP_OUTPUT = os.path.join(ROOT_DIR, "dist", f"dsh-win7-portable-v{VERSION}.zip")
RIPGREP_VERSION = "14.1.0"
RIPGREP_MANIFEST_SHA256 = '1e06b8d18d8dd34c0fa6cdebaeb5a4894a38b5377fc12e4af74329797e80e04e'
RIPGREP_FILES = {
    'rg.exe': ('1dce02aae98c0a48c2644abd1849fb90406296d4e0c95e239f95242ee8480ff8', 5332480),
    'COPYING': ('dfe7d0a6134a17d3de7409762e08dc02133303912875cab40a74ba07a390f85a', 129),
    'LICENSE-MIT': ('970813655a1bf777d2ead189cef71ab73ab92ce04dc864027d61a45de03e6728', 1102),
    'UNLICENSE': ('640514163b17f977adc997cb16f51871122cfb0555ebad1a3f01e167b7ba8857', 1235),
}


def resolve_pinned_ripgrep_source(root_dir=ROOT_DIR):
    source = os.path.join(root_dir, 'dsh', 'fs', 'tool_fs_search', 'bin', 'rg.exe')
    if not os.path.isfile(source):
        raise FileNotFoundError(
            "pinned ripgrep %s binary is missing: %s"
            % (RIPGREP_VERSION, source)
        )
    return source


def verify_pinned_ripgrep(root_dir, source=None):
    """Approve the exact licensed native input, including explicit overrides."""
    binary = Path(resolve_pinned_ripgrep_source(root_dir))
    directory = binary.parent
    manifest = directory / 'ripgrep-input.json'
    if (not manifest.is_file() or manifest.stat().st_nlink != 1
            or os.path.normcase(os.path.realpath(str(manifest))) != os.path.normcase(os.path.abspath(str(manifest)))):
        raise ValueError('Portable ripgrep manifest is missing or aliased')
    manifest_bytes = manifest.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != RIPGREP_MANIFEST_SHA256:
        raise ValueError('Portable ripgrep manifest bytes differ')
    metadata = json.loads(manifest_bytes.decode('utf-8'))
    if (metadata.get('schema') != 1 or metadata.get('name') != 'BurntSushi/ripgrep'
            or metadata.get('version') != RIPGREP_VERSION
            or metadata.get('target') != 'x86_64-pc-windows-msvc'
            or metadata.get('files') != {name: dict(sha256=identity[0], bytes=identity[1])
                                        for name, identity in RIPGREP_FILES.items()}):
        raise ValueError('Portable ripgrep input identity differs')
    for name, (expected, size) in RIPGREP_FILES.items():
        path = directory / name
        if (os.path.normcase(os.path.realpath(str(path))) != os.path.normcase(os.path.abspath(str(path)))
                or not path.is_file() or path.stat().st_nlink != 1):
            raise ValueError('Portable ripgrep input is missing or aliased: ' + name)
        data = path.read_bytes()
        if len(data) != size or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('Portable ripgrep input bytes differ: ' + name)
    selected = Path(source) if source is not None else binary
    if (not selected.is_file()
            or os.path.normcase(os.path.realpath(str(selected))) != os.path.normcase(os.path.abspath(str(selected)))
            or selected.stat().st_nlink != 1):
        raise ValueError('Portable ripgrep override is missing or aliased')
    data = selected.read_bytes()
    expected, size = RIPGREP_FILES['rg.exe']
    if len(data) != size or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('Portable requires the exact pinned ripgrep ' + RIPGREP_VERSION)
    return str(selected), metadata


def bundle_pinned_ripgrep(dist_dir=DIST_DIR, root_dir=ROOT_DIR, source=None):
    source_path, _ = verify_pinned_ripgrep(root_dir, source)
    target = os.path.join(dist_dir, "dsh", "fs", "tool_fs_search", "bin", "rg.exe")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copy2(source_path, target)
    for name in ('COPYING', 'LICENSE-MIT', 'UNLICENSE', 'ripgrep-input.json'):
        shutil.copyfile(os.path.join(os.path.dirname(resolve_pinned_ripgrep_source(root_dir)), name),
                        os.path.join(os.path.dirname(target), name))
    return target


def bundle_vendor_identities(root_dir, dist_dir):
    """Keep pinned Cordis package provenance for real DeepSeek request inventory."""
    source_root = Path(root_dir) / 'reference' / 'vendor'
    selected = []
    names = set()
    for manifest in sorted(source_root.glob('*/package.json')):
        license_file = manifest.with_name('LICENSE')
        if manifest.is_symlink() or not license_file.is_file() or license_file.is_symlink():
            raise ValueError('Pinned vendor identity/license is missing or aliased: ' + str(manifest))
        data = json.loads(manifest.read_text(encoding='utf-8'))
        if any(not isinstance(data.get(key), str) or not data[key] for key in ('name', 'version')):
            raise ValueError('Pinned vendor manifest requires name and version: ' + str(manifest))
        if data['name'] in names:
            raise ValueError('Duplicate pinned vendor package identity: ' + data['name'])
        names.add(data['name'])
        selected.extend((manifest, license_file))
    if not selected:
        raise ValueError('Pinned vendor identity closure is missing')
    for source in selected:
        target = Path(dist_dir) / source.relative_to(Path(root_dir) / 'reference')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(source), str(target))
    return names


def bundle_python_runtime(dist_dir, runtime_dir):
    """Stage a supplied Python 3.8 Windows runtime without host PATH lookup."""
    required = ["python.exe", "python38.dll", "Lib/os.py"]
    for name in required:
        if not os.path.isfile(os.path.join(runtime_dir, name)):
            raise FileNotFoundError("Python 3.8 runtime input missing: " + name)
    if os.path.isfile(os.path.join(runtime_dir, "LICENSE.txt")):
        shutil.copy2(os.path.join(runtime_dir, "LICENSE.txt"), os.path.join(dist_dir, "PYTHON-LICENSE.txt"))
    for name in os.listdir(runtime_dir):
        if name.lower().endswith((".dll", ".exe")):
            shutil.copy2(os.path.join(runtime_dir, name), os.path.join(dist_dir, name))
    shutil.copytree(os.path.join(runtime_dir, "Lib"), os.path.join(dist_dir, "lib"),
                    ignore=shutil.ignore_patterns("site-packages", "__pycache__", "test", "tests"), dirs_exist_ok=True)
    if os.path.isdir(os.path.join(runtime_dir, "DLLs")):
        shutil.copytree(os.path.join(runtime_dir, "DLLs"), os.path.join(dist_dir, "DLLs"), dirs_exist_ok=True)
    with open(os.path.join(dist_dir, "python38._pth"), "w", encoding="utf-8") as stream:
        stream.write(".\nlib\nDLLs\nimport site\n")


def inspect_runtime(runtime_dir):
    command = [os.path.join(runtime_dir, 'python.exe'), '-I', '-c',
        'import json,sys,struct; print(json.dumps(dict(version=list(sys.version_info[:3]), platform=sys.platform, bits=struct.calcsize("P")*8)))']
    result = subprocess.run(command, capture_output=True, encoding='utf-8', timeout=30)
    if result.returncode:
        raise ValueError('supplied Portable Python runtime cannot execute')
    try:
        observed = json.loads(result.stdout)
    except ValueError:
        raise ValueError('supplied Portable Python returned invalid runtime identity') from None
    if observed != dict(version=[3, 8, 10], platform='win32', bits=64):
        raise ValueError('Portable requires actual Windows x64 Python 3.8.10, observed ' + repr(observed))
    observed['files'] = {name: hashlib.sha256(Path(runtime_dir, name).read_bytes()).hexdigest()
                         for name in ('python.exe', 'python38.dll')}
    return observed


def checked_inputs(root_dir, site_packages):
    """Resolve all external inputs before touching the last successful release."""
    root = Path(root_dir)
    from dsh.session.icu_collation import verify_icu_files
    verify_icu_files(root / 'dsh/session/bin/icu')
    from dsh.session.zstd import verify_zstd_files
    verify_zstd_files(root / 'dsh/session/bin/zstd')
    from dsh.session.sqlite_sql import verify_sql_files
    verify_sql_files(root / 'dsh/session/resources/sql')
    from dsh.session.text import verify_case_folding
    verify_case_folding(root / 'dsh/session/bin/unicode/CaseFolding.txt')
    manifest = json.loads((root / 'scripts/frontend-inputs.json').read_text(encoding='utf-8'))
    baseline = json.loads((root / 'migration/baseline.json').read_text(encoding='utf-8'))
    if manifest['target_upstream'] != baseline['target_upstream']:
        raise ValueError('frontend input target differs from pinned upstream')
    expected = {row['path']: row['sha256'] for row in manifest['files']}
    actual = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (root / 'apps/web/dist').rglob('*') if p.is_file()}
    if not expected or expected != actual or 'apps/web/dist/index.html' not in actual:
        raise ValueError('versioned frontend inputs missing or changed; rebuild and review their manifest')
    from scripts.import_frontend import validate_import
    validate_import(root, manifest)
    if not (root / 'reference/apps/cli/package.json').is_file():
        raise FileNotFoundError('pinned reference CLI package metadata is missing; initialize submodules')
    distributions = {d.metadata['Name'].lower().replace('_', '-'): d
                     for d in importlib.metadata.distributions(path=[str(site_packages)])}
    selected = []
    from packaging.requirements import Requirement
    for line in (root / 'requirements-runtime.lock').read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'):
            continue
        requirement = Requirement(line)
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        pins = list(requirement.specifier)
        if len(pins) != 1 or pins[0].operator != '==':
            raise ValueError('runtime dependency missing or unpinned: ' + line)
        name, version = requirement.name, pins[0].version
        dist = distributions.get(name.lower().replace('_', '-'))
        if dist is None or dist.version != version or not dist.files:
            raise ValueError('runtime dependency missing or unpinned: ' + line)
        for relative in dist.files:
            if relative.suffix != '.pyc' and '..' not in relative.parts:
                if not Path(dist.locate_file(relative)).is_file():
                    raise FileNotFoundError('runtime distribution file missing: ' + str(relative))
        selected.append(dist)
    if not selected:
        raise ValueError('runtime dependency lock is empty')
    return manifest, selected


def bundle_dependencies(distributions, destination):
    """Copy only locked runtime distributions, never the development environment."""
    for dist in distributions:
        for relative in dist.files:
            if relative.suffix == '.pyc' or '..' in relative.parts:
                continue  # entrypoint scripts and cache files are not runtime modules
            source = Path(dist.locate_file(relative))
            if not source.is_file():
                raise FileNotFoundError('runtime distribution file missing: ' + str(source))
            target = Path(destination) / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(source), str(target))


def assemble_portable(dist_dir, zip_output, runtime_dir=None, ripgrep_source=None, site_packages=None):
    # Resolve before replacing an existing release so a missing pinned build input fails safely.
    ripgrep_source, metadata = verify_pinned_ripgrep(ROOT_DIR, ripgrep_source)
    from scripts.ucrt_inputs import verify_pinned_ucrt, bundle_ucrt
    ucrt = verify_pinned_ucrt(ROOT_DIR)
    runtime_dir = runtime_dir or sys.base_prefix
    if not os.path.isfile(os.path.join(runtime_dir, "python38.dll")):
        raise FileNotFoundError("Python 3.8 Windows runtime is required before staging")
    for name in ('python.exe', 'python38.dll', 'Lib/os.py'):
        if not os.path.isfile(os.path.join(runtime_dir, name)):
            raise FileNotFoundError('Python 3.8 runtime input missing: ' + name)
    site_packages = site_packages or os.path.join(ROOT_DIR, '.venv', 'Lib', 'site-packages')
    frontend, dependencies = checked_inputs(ROOT_DIR, site_packages)
    runtime = inspect_runtime(runtime_dir)
    print(f"[Build Portable] Creating portable release directory at: {dist_dir}")
    if os.path.exists(dist_dir):
        shutil.rmtree(dist_dir)

    os.makedirs(dist_dir, exist_ok=True)

    bundle_python_runtime(dist_dir, runtime_dir)
    bundle_ucrt(ROOT_DIR, dist_dir)

    with open(ripgrep_source, "rb") as stream:
        ripgrep_digest = hashlib.sha256(stream.read()).hexdigest()
    provenance = {"python_builder": platform.python_version(), "python_runtime_source": runtime_dir,
                  "python_runtime": runtime,
                  "ucrt_input": ucrt,
                  "ripgrep_package": metadata["name"], "ripgrep_version": metadata["version"],
                  "ripgrep_sha256": ripgrep_digest,
                  "ripgrep_input": metadata,
                  "frontend": frontend,
                  "runtime_dependencies": {d.metadata['Name']: d.version for d in dependencies}}
    try:
        provenance["product_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT_DIR, encoding="utf-8").strip()
        provenance["worktree_dirty"] = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT_DIR, encoding="utf-8").strip())
    except subprocess.CalledProcessError:
        provenance["product_commit"] = None
    with open(os.path.join(dist_dir, "build-provenance.json"), "w", encoding="utf-8") as stream:
        json.dump(provenance, stream, indent=2)

    # 1. Copy dsh framework and apps application
    shutil.copytree(os.path.join(ROOT_DIR, "dsh"), os.path.join(dist_dir, "dsh"), ignore=shutil.ignore_patterns("__pycache__"))
    bundle_pinned_ripgrep(dist_dir, ROOT_DIR, source=ripgrep_source)
    if os.path.exists(os.path.join(ROOT_DIR, "apps", "cli")):
        shutil.copytree(
            os.path.join(ROOT_DIR, "apps", "cli"),
            os.path.join(dist_dir, "apps", "cli"),
            ignore=shutil.ignore_patterns("__pycache__"),
            dirs_exist_ok=True,
        )
    ref_cli_pkg = os.path.join(ROOT_DIR, "reference", "apps", "cli", "package.json")
    if os.path.exists(ref_cli_pkg):
        shutil.copy(ref_cli_pkg, os.path.join(dist_dir, "apps", "cli", "package.json"))
        shutil.copy(ref_cli_pkg, os.path.join(dist_dir, "package.json"))
    if os.path.exists(os.path.join(ROOT_DIR, "apps", "web")):
        shutil.copytree(os.path.join(ROOT_DIR, "apps", "web", "dist"), os.path.join(dist_dir, "apps", "web", "dist"))
    ref_pkgs = os.path.join(ROOT_DIR, "packages")
    if not os.path.exists(ref_pkgs):
        ref_pkgs = os.path.join(ROOT_DIR, "reference", "packages")
    if os.path.exists(ref_pkgs):
        os.makedirs(os.path.join(dist_dir, "packages"), exist_ok=True)
        shutil.copytree(
            ref_pkgs,
            os.path.join(dist_dir, "packages"),
            ignore=shutil.ignore_patterns("node_modules", ".git", "*.tsbuildinfo"),
            dirs_exist_ok=True,
        )

    bundle_vendor_identities(ROOT_DIR, dist_dir)
    shutil.copy(os.path.join(ROOT_DIR, "dsh.py"), os.path.join(dist_dir, "dsh.py"))
    shutil.copy(os.path.join(ROOT_DIR, "README.md"), os.path.join(dist_dir, "README.md"))
    if os.path.exists(os.path.join(ROOT_DIR, "AGENTS.md")):
        shutil.copy(os.path.join(ROOT_DIR, "AGENTS.md"), os.path.join(dist_dir, "AGENTS.md"))
    if os.path.exists(os.path.join(ROOT_DIR, "dsh-web.bat")):
        shutil.copy(os.path.join(ROOT_DIR, "dsh-web.bat"), os.path.join(dist_dir, "dsh-web.bat"))

    # Copy exactly the reviewed production dependencies, excluding pytest/pip/dev tooling.
    bundle_dependencies(dependencies, os.path.join(dist_dir, 'lib'))

    # 3. Create Windows batch launcher script dsh.bat
    for launcher, arguments in (("dsh.bat", "%*"), ("dsh-web.bat", "--profile web %*")):
        bat_content = '@echo off\nsetlocal\n"%~dp0python.exe" "%~dp0dsh.py" ' + arguments + '\nexit /b %errorlevel%\n'
        with open(os.path.join(dist_dir, launcher), "w", encoding="utf-8") as stream:
            stream.write(bat_content)

    print(f"[Build Portable] Successfully built Portable Release directory at: {dist_dir}")

    # 4. Create ZIP distribution package
    print(f"[Build Portable] Creating ZIP release package at: {zip_output}")
    if os.path.exists(zip_output):
        os.remove(zip_output)

    with zipfile.ZipFile(zip_output, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(dist_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, os.path.dirname(dist_dir))
                zipf.write(file_path, arcname)

    size_mb = os.path.getsize(zip_output) / (1024 * 1024)
    print(f"[Build Portable] Created Portable Release ZIP v{VERSION}: {zip_output} ({size_mb:.2f} MB)")


def publish_candidate(candidate_dir, candidate_zip, dist_dir, zip_output, backup_root):
    """Roll back both artifacts if an in-process publication step fails."""
    backups, published = [], []
    try:
        for target in (dist_dir, zip_output):
            if os.path.exists(target):
                backup = os.path.join(backup_root, 'previous-' + str(len(backups)))
                os.replace(target, backup)
                backups.append((target, backup))
        for source, target in ((candidate_dir, dist_dir), (candidate_zip, zip_output)):
            os.replace(source, target)
            published.append(target)
    except BaseException:
        # These are exact validated output paths, never inferred input trees.
        for target in reversed(published):
            if os.path.isdir(target):
                shutil.rmtree(target)
            else:
                os.unlink(target)
        for target, backup in reversed(backups):
            os.replace(backup, target)
        raise


def build_portable(runtime_dir=None, ripgrep_source=None, site_packages=None, output_dir=None):
    parent = os.path.abspath(output_dir) if output_dir is not None else os.path.dirname(os.path.abspath(DIST_DIR))
    dist_dir = os.path.join(parent, 'dsh-win7-portable') if output_dir is not None else os.path.abspath(DIST_DIR)
    zip_output = os.path.join(parent, 'dsh-win7-portable-v' + VERSION + '.zip') if output_dir is not None else os.path.abspath(ZIP_OUTPUT)
    if os.path.dirname(zip_output) != parent or dist_dir == zip_output:
        raise ValueError('Portable directory and ZIP must be distinct siblings')
    for path in (parent, dist_dir, zip_output):
        if os.path.normcase(os.path.realpath(path)) != os.path.normcase(os.path.abspath(path)):
            raise ValueError('Portable output must not traverse links or junctions')
    for source in (runtime_dir or sys.base_prefix, site_packages or os.path.join(ROOT_DIR, '.venv/Lib/site-packages'),
                   *[os.path.join(ROOT_DIR, name) for name in ('dsh', 'apps', 'packages', 'reference', 'scripts')]):
        for target in (dist_dir, zip_output):
            try:
                common = os.path.normcase(os.path.commonpath([os.path.realpath(source), os.path.realpath(target)]))
            except ValueError:
                continue
            if common in (os.path.normcase(os.path.realpath(source)), os.path.normcase(os.path.realpath(target))):
                raise ValueError('Portable output overlaps a build input')
    if os.path.lexists(dist_dir) and not os.path.isdir(dist_dir):
        raise ValueError('Portable directory output is not a directory')
    if os.path.lexists(zip_output) and not os.path.isfile(zip_output):
        raise ValueError('Portable ZIP output is not a regular file')
    os.makedirs(parent, exist_ok=True)
    staging = tempfile.mkdtemp(prefix='.dsh-portable-candidate-', dir=parent)
    published = False
    try:
        candidate_dir = os.path.join(staging, os.path.basename(dist_dir))
        candidate_zip = os.path.join(staging, os.path.basename(zip_output))
        assemble_portable(candidate_dir, candidate_zip, runtime_dir, ripgrep_source, site_packages)
        publish_candidate(candidate_dir, candidate_zip, dist_dir, zip_output, staging)
        published = True
    finally:
        retained = any(name.startswith('previous-') for name in os.listdir(staging))
        if published or not retained:
            shutil.rmtree(staging)
        else:
            sys.stderr.write('Portable publication rollback incomplete; retained previous artifacts at ' + staging + '\n')
    print('[Build Portable] Published candidate directory and ZIP at: ' + parent)
    return dist_dir, zip_output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-runtime", default=sys.base_prefix)
    parser.add_argument("--ripgrep-source")
    parser.add_argument("--site-packages")
    parser.add_argument('--output-dir', help='Build an isolated candidate under this directory')
    args = parser.parse_args()
    build_portable(args.python_runtime, args.ripgrep_source, args.site_packages, args.output_dir)
