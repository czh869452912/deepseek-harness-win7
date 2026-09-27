import hashlib
import subprocess
import argparse
import json
import platform
import os
import shutil
import sys
import zipfile

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


def build_portable(runtime_dir=None, ripgrep_source=None):
    # Resolve before replacing an existing release so a missing pinned build input fails safely.
    ripgrep_source = ripgrep_source or resolve_pinned_ripgrep_source(ROOT_DIR)
    metadata_path = os.path.join(os.path.dirname(os.path.dirname(ripgrep_source)), "package.json")
    with open(metadata_path, "r", encoding="utf-8") as stream:
        metadata = json.load(stream)
    if metadata.get("name") != "@vscode/ripgrep-win32-x64" or metadata.get("version") != RIPGREP_VERSION:
        raise ValueError("portable requires pinned @vscode/ripgrep-win32-x64@" + RIPGREP_VERSION)
    runtime_dir = runtime_dir or sys.base_prefix
    if not os.path.isfile(os.path.join(runtime_dir, "python38.dll")):
        raise FileNotFoundError("Python 3.8 Windows runtime is required before staging")
    print(f"[Build Portable] Creating portable release directory at: {DIST_DIR}")
    if os.path.exists(DIST_DIR):
        shutil.rmtree(DIST_DIR)

    os.makedirs(DIST_DIR, exist_ok=True)

    bundle_python_runtime(DIST_DIR, runtime_dir)

    with open(ripgrep_source, "rb") as stream:
        ripgrep_digest = hashlib.sha256(stream.read()).hexdigest()
    provenance = {"python_builder": platform.python_version(), "python_runtime_source": runtime_dir,
                  "ripgrep_package": metadata["name"], "ripgrep_version": metadata["version"],
                  "ripgrep_sha256": ripgrep_digest}
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
    # Copy official compiled web dist and client packages
    ref_web_dist = os.path.join(ROOT_DIR, "reference", "apps", "web", "dist")
    if os.path.exists(ref_web_dist):
        os.makedirs(os.path.join(DIST_DIR, "apps", "web", "dist"), exist_ok=True)
        shutil.copytree(ref_web_dist, os.path.join(DIST_DIR, "apps", "web", "dist"), dirs_exist_ok=True)

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

    # 2. Bundle python site-packages from virtualenv
    venv_site_packages = os.path.join(ROOT_DIR, ".venv", "Lib", "site-packages")
    dist_lib_dir = os.path.join(DIST_DIR, "lib")
    if os.path.exists(venv_site_packages):
        print("[Build Portable] Bundling dependencies from virtualenv site-packages...")
        os.makedirs(dist_lib_dir, exist_ok=True)
        for item in os.listdir(venv_site_packages):
            if item.startswith('_pytest') or item.startswith('pytest'):
                continue
            s = os.path.join(venv_site_packages, item)
            d = os.path.join(dist_lib_dir, item)
            if os.path.isdir(s):
                shutil.copytree(s, d)
            else:
                shutil.copy(s, d)

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
    args = parser.parse_args()
    build_portable(args.python_runtime, args.ripgrep_source)
