@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "OPENWRITE_PYTHON="
set "OPENWRITE_PY_VERSION="

if exist "%~dp0..\..\Scripts\python.exe" call :try_exe "%~dp0..\..\Scripts\python.exe"
if defined OPENWRITE_PYTHON goto :launch
if exist "%~dp0Scripts\python.exe" call :try_exe "%~dp0Scripts\python.exe"
if defined OPENWRITE_PYTHON goto :launch
if exist "%~dp0.venv\Scripts\python.exe" call :try_exe "%~dp0.venv\Scripts\python.exe"
if defined OPENWRITE_PYTHON goto :launch
if exist "%~dp0.venv312\Scripts\python.exe" call :try_exe "%~dp0.venv312\Scripts\python.exe"
if defined OPENWRITE_PYTHON goto :launch

where py >nul 2>nul
if not errorlevel 1 (
  for %%V in (-3.13 -3.12 -3.11 -3.10) do (
    if not defined OPENWRITE_PYTHON call :try_py %%V
  )
)
if defined OPENWRITE_PYTHON goto :launch

where python >nul 2>nul
if not errorlevel 1 call :try_exe python
if defined OPENWRITE_PYTHON goto :launch

echo [OpenWrite] 未找到 Python 3.10 或更高版本。
echo 请先从 https://www.python.org/downloads/windows/ 安装 Python。
echo 安装时请勾选 Add Python to PATH，然后再次双击此文件。
echo.
pause
exit /b 2

:try_exe
"%~1" -c "import sys; raise SystemExit(0 if sys.version_info ^>= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 set "OPENWRITE_PYTHON=%~1"
exit /b 0

:try_py
py %1 -c "import sys; raise SystemExit(0 if sys.version_info ^>= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 (
  set "OPENWRITE_PYTHON=py"
  set "OPENWRITE_PY_VERSION=%1"
)
exit /b 0

:launch
if "%OPENWRITE_PYTHON%"=="py" (
  if exist "%~dp0tools\desktop_launcher.py" (
    py %OPENWRITE_PY_VERSION% -u "%~dp0tools\desktop_launcher.py" %*
  ) else (
    py %OPENWRITE_PY_VERSION% -u -m tools.desktop_launcher %*
  )
) else (
  if exist "%~dp0tools\desktop_launcher.py" (
    "%OPENWRITE_PYTHON%" -u "%~dp0tools\desktop_launcher.py" %*
  ) else (
    "%OPENWRITE_PYTHON%" -u -m tools.desktop_launcher %*
  )
)
set "OPENWRITE_STATUS=%ERRORLEVEL%"
if not "%OPENWRITE_STATUS%"=="0" (
  echo.
  echo 启动未完成。
  pause
)
exit /b %OPENWRITE_STATUS%
