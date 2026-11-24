@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
call tools\python.bat tools\test.py %*
exit /b %errorlevel%
