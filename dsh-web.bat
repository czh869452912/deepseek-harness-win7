@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "PYTHONPATH=%SCRIPT_DIR%;%SCRIPT_DIR%lib"

python --version >nul 2>&1
if %errorlevel% equ 0 (
    python "%SCRIPT_DIR%dsh.py" --web %*
) else (
    echo [Error] Python executable not found in system PATH.
    echo Please install Python 3.8+ or place python.exe in this folder.
    pause
)
