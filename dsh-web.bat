@echo off
call "%~dp0dsh.bat" --profile web %*
exit /b %errorlevel%
