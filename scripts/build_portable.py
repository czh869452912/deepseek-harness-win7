import os
import shutil
import sys
import zipfile
import urllib.request

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(ROOT_DIR, "dist", "dsh-win7-portable")


def build_portable():
    print(f"[Build Portable] Creating portable release directory at: {DIST_DIR}")
    if os.path.exists(DIST_DIR):
        shutil.rmtree(DIST_DIR)

    os.makedirs(DIST_DIR, exist_ok=True)

    # 1. Copy source code packages
    shutil.copytree(os.path.join(ROOT_DIR, "dsh"), os.path.join(DIST_DIR, "dsh"))
    shutil.copy(os.path.join(ROOT_DIR, "dsh_cli.py"), os.path.join(DIST_DIR, "dsh_cli.py"))
    shutil.copy(os.path.join(ROOT_DIR, "README.md"), os.path.join(DIST_DIR, "README.md"))
    if os.path.exists(os.path.join(ROOT_DIR, "AGENTS.md")):
        shutil.copy(os.path.join(ROOT_DIR, "AGENTS.md"), os.path.join(DIST_DIR, "AGENTS.md"))

    # 2. Bundle python site-packages / virtualenv libs if available
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
    bat_content = """@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "PYTHONPATH=%SCRIPT_DIR%;%SCRIPT_DIR%lib"

rem Check if python executable exists in PATH or system
python --version >nul 2>&1
if %errorlevel% equ 0 (
    python "%SCRIPT_DIR%dsh_cli.py" %*
) else (
    echo [Error] Python executable not found in system PATH.
    echo Please install Python 3.8+ or place python.exe in this folder.
    pause
)
"""
    with open(os.path.join(DIST_DIR, "dsh.bat"), "w", encoding="utf-8") as f:
        f.write(bat_content)

    print(f"[Build Portable] Successfully built Portable Release at: {DIST_DIR}")
    print("Contents of Portable Release:")
    for root, dirs, files in os.walk(DIST_DIR):
        rel = os.path.relpath(root, DIST_DIR)
        if rel == ".":
            print(" -", ", ".join(files))
        else:
            print(f" - {rel}/: {len(files)} files")


if __name__ == "__main__":
    build_portable()
