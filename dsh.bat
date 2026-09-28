@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "PYTHONPATH=%SCRIPT_DIR%;%SCRIPT_DIR%lib"
if exist "%SCRIPT_DIR%python.exe" (
    "%SCRIPT_DIR%python.exe" "%SCRIPT_DIR%dsh.py" %*
) else if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
    "%SCRIPT_DIR%.venv\Scripts\python.exe" "%SCRIPT_DIR%dsh.py" %*
) else (
    python "%SCRIPT_DIR%dsh.py" %*
)
exit /b %errorlevel%
