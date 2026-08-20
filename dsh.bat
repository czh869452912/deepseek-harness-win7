@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "PYTHONPATH=%SCRIPT_DIR%"

python --version >nul 2>&1
if %errorlevel% equ 0 (
    python "%SCRIPT_DIR%dsh.py" %*
) else (
    echo [Error] Python executable not found in system PATH.
    echo Please install Python 3.8+ or use .venv\\Scripts\\python.exe.
    pause
)
