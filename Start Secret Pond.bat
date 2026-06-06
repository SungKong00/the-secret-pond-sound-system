@echo off
setlocal

cd /d "%~dp0"

set "SECRET_POND_PY="
py -3.11 -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 13) else 1)" >nul 2>nul
if not errorlevel 1 set "SECRET_POND_PY=py -3.11"

if not defined SECRET_POND_PY (
  py -3.12 -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 13) else 1)" >nul 2>nul
  if not errorlevel 1 set "SECRET_POND_PY=py -3.12"
)

if not defined SECRET_POND_PY (
  python -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 13) else 1)" >nul 2>nul
  if not errorlevel 1 set "SECRET_POND_PY=python"
)

if not defined SECRET_POND_PY (
  echo Python 3.11 또는 3.12를 찾을 수 없습니다.
  echo Python을 설치한 뒤 다시 실행하세요.
  pause
  exit /b 1
)

%SECRET_POND_PY% scripts\launch_secret_pond.py %*
if errorlevel 1 (
  echo.
  echo Secret Pond 실행에 실패했습니다. 위 메시지를 확인하세요.
  pause
  exit /b 1
)
