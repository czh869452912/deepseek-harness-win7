import os
import shutil
import sys
import zipfile

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(ROOT_DIR, "dist", "dsh-win7-portable")
VERSION = "0.1.0"
ZIP_OUTPUT = os.path.join(ROOT_DIR, "dist", f"dsh-win7-portable-v{VERSION}.zip")


def build_portable():
    print(f"[Build Portable] Creating portable release directory at: {DIST_DIR}")
    if os.path.exists(DIST_DIR):
        shutil.rmtree(DIST_DIR)

    os.makedirs(DIST_DIR, exist_ok=True)

    # 1. Copy dsh framework and apps/cli application
    shutil.copytree(os.path.join(ROOT_DIR, "dsh"), os.path.join(DIST_DIR, "dsh"))
    os.makedirs(os.path.join(DIST_DIR, "apps", "cli"), exist_ok=True)
    shutil.copy(os.path.join(ROOT_DIR, "apps", "cli", "main.py"), os.path.join(DIST_DIR, "apps", "cli", "main.py"))
    shutil.copy(os.path.join(ROOT_DIR, "dsh.py"), os.path.join(DIST_DIR, "dsh.py"))
    shutil.copy(os.path.join(ROOT_DIR, "README.md"), os.path.join(DIST_DIR, "README.md"))
    if os.path.exists(os.path.join(ROOT_DIR, "AGENTS.md")):
        shutil.copy(os.path.join(ROOT_DIR, "AGENTS.md"), os.path.join(DIST_DIR, "AGENTS.md"))

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
    bat_content = """@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "PYTHONPATH=%SCRIPT_DIR%;%SCRIPT_DIR%lib"

python --version >nul 2>&1
if %errorlevel% equ 0 (
    python "%SCRIPT_DIR%dsh.py" %*
) else (
    echo [Error] Python executable not found in system PATH.
    echo Please install Python 3.8+ or place python.exe in this folder.
    pause
)
"""
    with open(os.path.join(DIST_DIR, "dsh.bat"), "w", encoding="utf-8") as f:
        f.write(bat_content)

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
    build_portable()
