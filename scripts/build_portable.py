import hashlib
import subprocess
import argparse
import json
import platform
import os
import shutil
import sys
import zipfile
import importlib.metadata
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(ROOT_DIR, "dist", "dsh-win7-portable")
VERSION = "0.1.0"
ZIP_OUTPUT = os.path.join(ROOT_DIR, "dist", f"dsh-win7-portable-v{VERSION}.zip")
RIPGREP_VERSION = "1.18.0"


def resolve_pinned_ripgrep_source(root_dir=ROOT_DIR):
    source = os.path.join(
        root_dir,
        "reference",
        "node_modules",
        ".pnpm",
        "@vscode+ripgrep-win32-x64@%s" % RIPGREP_VERSION,
        "node_modules",
        "@vscode",
        "ripgrep-win32-x64",
        "bin",
        "rg.exe",
    )
    if not os.path.isfile(source):
        raise FileNotFoundError(
            "pinned @vscode/ripgrep-win32-x64@%s binary is missing: %s"
            % (RIPGREP_VERSION, source)
        )
    return source


def bundle_pinned_ripgrep(dist_dir=DIST_DIR, root_dir=ROOT_DIR, source=None):
    source_path = source or resolve_pinned_ripgrep_source(root_dir)
    target = os.path.join(dist_dir, "dsh", "fs", "tool_fs_search", "bin", "rg.exe")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copy2(source_path, target)
    return target


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


def checked_inputs(root_dir, site_packages):
    """Resolve all external inputs before touching the last successful release."""
    root = Path(root_dir)
    manifest = json.loads((root / 'scripts/frontend-inputs.json').read_text(encoding='utf-8'))
    baseline = json.loads((root / 'migration/baseline.json').read_text(encoding='utf-8'))
    if manifest['target_upstream'] != baseline['target_upstream']:
        raise ValueError('frontend input target differs from pinned upstream')
    expected = {row['path']: row['sha256'] for row in manifest['files']}
    actual = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (root / 'apps/web/dist').rglob('*') if p.is_file()}
    if not expected or expected != actual or 'apps/web/dist/index.html' not in actual:
        raise ValueError('versioned frontend inputs missing or changed; rebuild and review their manifest')
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


def build_portable(runtime_dir=None, ripgrep_source=None, site_packages=None):
    # Resolve before replacing an existing release so a missing pinned build input fails safely.
    ripgrep_source = ripgrep_source or resolve_pinned_ripgrep_source(ROOT_DIR)
    if not os.path.isfile(ripgrep_source):
        raise FileNotFoundError('pinned ripgrep binary is missing: ' + str(ripgrep_source))
    metadata_path = os.path.join(os.path.dirname(os.path.dirname(ripgrep_source)), "package.json")
    with open(metadata_path, "r", encoding="utf-8") as stream:
        metadata = json.load(stream)
    if metadata.get("name") != "@vscode/ripgrep-win32-x64" or metadata.get("version") != RIPGREP_VERSION:
        raise ValueError("portable requires pinned @vscode/ripgrep-win32-x64@" + RIPGREP_VERSION)
    runtime_dir = runtime_dir or sys.base_prefix
    if not os.path.isfile(os.path.join(runtime_dir, "python38.dll")):
        raise FileNotFoundError("Python 3.8 Windows runtime is required before staging")
    for name in ('python.exe', 'python38.dll', 'Lib/os.py'):
        if not os.path.isfile(os.path.join(runtime_dir, name)):
            raise FileNotFoundError('Python 3.8 runtime input missing: ' + name)
    site_packages = site_packages or os.path.join(ROOT_DIR, '.venv', 'Lib', 'site-packages')
    frontend, dependencies = checked_inputs(ROOT_DIR, site_packages)
    print(f"[Build Portable] Creating portable release directory at: {DIST_DIR}")
    if os.path.exists(DIST_DIR):
        shutil.rmtree(DIST_DIR)

    os.makedirs(DIST_DIR, exist_ok=True)

    bundle_python_runtime(DIST_DIR, runtime_dir)

    with open(ripgrep_source, "rb") as stream:
        ripgrep_digest = hashlib.sha256(stream.read()).hexdigest()
    provenance = {"python_builder": platform.python_version(), "python_runtime_source": runtime_dir,
                  "ripgrep_package": metadata["name"], "ripgrep_version": metadata["version"],
                  "ripgrep_sha256": ripgrep_digest,
                  "frontend": frontend,
                  "runtime_dependencies": {d.metadata['Name']: d.version for d in dependencies}}
    try:
        provenance["product_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT_DIR, encoding="utf-8").strip()
        provenance["worktree_dirty"] = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT_DIR, encoding="utf-8").strip())
    except subprocess.CalledProcessError:
        provenance["product_commit"] = None
    with open(os.path.join(DIST_DIR, "build-provenance.json"), "w", encoding="utf-8") as stream:
        json.dump(provenance, stream, indent=2)

    # 1. Copy dsh framework and apps application
    shutil.copytree(os.path.join(ROOT_DIR, "dsh"), os.path.join(DIST_DIR, "dsh"), ignore=shutil.ignore_patterns("__pycache__"))
    bundle_pinned_ripgrep(DIST_DIR, ROOT_DIR, source=ripgrep_source)
    if os.path.exists(os.path.join(ROOT_DIR, "apps", "cli")):
        shutil.copytree(
            os.path.join(ROOT_DIR, "apps", "cli"),
            os.path.join(DIST_DIR, "apps", "cli"),
            ignore=shutil.ignore_patterns("__pycache__"),
            dirs_exist_ok=True,
        )
    ref_cli_pkg = os.path.join(ROOT_DIR, "reference", "apps", "cli", "package.json")
    if os.path.exists(ref_cli_pkg):
        shutil.copy(ref_cli_pkg, os.path.join(DIST_DIR, "apps", "cli", "package.json"))
        shutil.copy(ref_cli_pkg, os.path.join(DIST_DIR, "package.json"))
    if os.path.exists(os.path.join(ROOT_DIR, "apps", "web")):
        shutil.copytree(os.path.join(ROOT_DIR, "apps", "web", "dist"), os.path.join(DIST_DIR, "apps", "web", "dist"))
    ref_pkgs = os.path.join(ROOT_DIR, "packages")
    if not os.path.exists(ref_pkgs):
        ref_pkgs = os.path.join(ROOT_DIR, "reference", "packages")
    if os.path.exists(ref_pkgs):
        os.makedirs(os.path.join(DIST_DIR, "packages"), exist_ok=True)
        shutil.copytree(
            ref_pkgs,
            os.path.join(DIST_DIR, "packages"),
            ignore=shutil.ignore_patterns("node_modules", ".git", "*.tsbuildinfo"),
            dirs_exist_ok=True,
        )

    shutil.copy(os.path.join(ROOT_DIR, "dsh.py"), os.path.join(DIST_DIR, "dsh.py"))
    shutil.copy(os.path.join(ROOT_DIR, "README.md"), os.path.join(DIST_DIR, "README.md"))
    if os.path.exists(os.path.join(ROOT_DIR, "AGENTS.md")):
        shutil.copy(os.path.join(ROOT_DIR, "AGENTS.md"), os.path.join(DIST_DIR, "AGENTS.md"))
    if os.path.exists(os.path.join(ROOT_DIR, "dsh-web.bat")):
        shutil.copy(os.path.join(ROOT_DIR, "dsh-web.bat"), os.path.join(DIST_DIR, "dsh-web.bat"))

    # Copy exactly the reviewed production dependencies, excluding pytest/pip/dev tooling.
    bundle_dependencies(dependencies, os.path.join(DIST_DIR, 'lib'))

    # 3. Create Windows batch launcher script dsh.bat
    for launcher, arguments in (("dsh.bat", "%*"), ("dsh-web.bat", "--profile web %*")):
        bat_content = '@echo off\nsetlocal\n"%~dp0python.exe" "%~dp0dsh.py" ' + arguments + '\nexit /b %errorlevel%\n'
        with open(os.path.join(DIST_DIR, launcher), "w", encoding="utf-8") as stream:
            stream.write(bat_content)

    print(f"[Build Portable] Successfully built Portable Release directory at: {DIST_DIR}")

    # 4. Create ZIP distribution package
    print(f"[Build Portable] Creating ZIP release package at: {ZIP_OUTPUT}")
    if os.path.exists(ZIP_OUTPUT):
        os.remove(ZIP_OUTPUT)

    with zipfile.ZipFile(ZIP_OUTPUT, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(DIST_DIR):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, os.path.dirname(DIST_DIR))
                zipf.write(file_path, arcname)

    size_mb = os.path.getsize(ZIP_OUTPUT) / (1024 * 1024)
    print(f"[Build Portable] Created Portable Release ZIP v{VERSION}: {ZIP_OUTPUT} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-runtime", default=sys.base_prefix)
    parser.add_argument("--ripgrep-source")
    parser.add_argument("--site-packages")
    args = parser.parse_args()
    build_portable(args.python_runtime, args.ripgrep_source, args.site_packages)
