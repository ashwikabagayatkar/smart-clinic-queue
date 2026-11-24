@echo off
setlocal DisableDelayedExpansion
where py >nul 2>nul
if errorlevel 1 goto try_python
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
if errorlevel 1 goto try_python
py -3 %*
exit /b %errorlevel%
:try_python
where python >nul 2>nul
if errorlevel 1 goto missing
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
if errorlevel 1 goto missing
python %*
exit /b %errorlevel%
:missing
echo Python 3.11 or newer was not found. Install native Windows Python and enable its launcher or PATH entry. 1>&2
exit /b 1
