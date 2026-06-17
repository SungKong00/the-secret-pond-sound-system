@echo off
setlocal

cd /d "%~dp0"

set "SECRET_POND_PY="

call :try_python py
if defined SECRET_POND_PY goto run_secret_pond

call :try_python py -3.14
if defined SECRET_POND_PY goto run_secret_pond

call :try_python py -3.13
if defined SECRET_POND_PY goto run_secret_pond

call :try_python py -3.12
if defined SECRET_POND_PY goto run_secret_pond

call :try_python py -3.11
if defined SECRET_POND_PY goto run_secret_pond

call :try_python python
if defined SECRET_POND_PY goto run_secret_pond

echo Python 3.11-3.14 was not found.
echo Install Python 3.11-3.14, then run this file again.
pause
exit /b 1

:try_python
set "SECRET_POND_VERSION="
for /f "tokens=2 delims= " %%P in ('%* -VV 2^>nul') do set "SECRET_POND_VERSION=%%P"
if "%SECRET_POND_VERSION:~0,5%"=="3.14." set "SECRET_POND_PY=%*"
if "%SECRET_POND_VERSION:~0,5%"=="3.13." set "SECRET_POND_PY=%*"
if "%SECRET_POND_VERSION:~0,5%"=="3.12." set "SECRET_POND_PY=%*"
if "%SECRET_POND_VERSION:~0,5%"=="3.11." set "SECRET_POND_PY=%*"
exit /b 0

:run_secret_pond
%SECRET_POND_PY% scripts\launch_secret_pond.py %*
if not errorlevel 1 exit /b 0

echo.
echo Secret Pond failed to start. Check the messages above.
pause
exit /b 1
