@echo off
setlocal

cd /d "%~dp0"

set "SECRET_POND_PY="
set "SECRET_POND_PROBE=import sys; raise SystemExit(0 if sys.version_info.major == 3 and 11 <= sys.version_info.minor and sys.version_info.minor < 13 else 1)"

py -3.11 -c "%SECRET_POND_PROBE%" >nul 2>nul
if not errorlevel 1 set "SECRET_POND_PY=py -3.11"
if defined SECRET_POND_PY goto run_secret_pond

py -3.12 -c "%SECRET_POND_PROBE%" >nul 2>nul
if not errorlevel 1 set "SECRET_POND_PY=py -3.12"
if defined SECRET_POND_PY goto run_secret_pond

python -c "%SECRET_POND_PROBE%" >nul 2>nul
if not errorlevel 1 set "SECRET_POND_PY=python"
if defined SECRET_POND_PY goto run_secret_pond

echo Python 3.11 or 3.12 was not found.
echo Install Python 3.11 or 3.12, then run this file again.
pause
exit /b 1

:run_secret_pond
%SECRET_POND_PY% scripts\launch_secret_pond.py %*
if not errorlevel 1 exit /b 0

echo.
echo Secret Pond failed to start. Check the messages above.
pause
exit /b 1
