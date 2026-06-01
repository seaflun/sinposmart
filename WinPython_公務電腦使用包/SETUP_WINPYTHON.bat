@echo off
setlocal
cd /d "%~dp0"

echo Duty automation WinPython setup
echo Project: %CD%
echo.

for /f "usebackq delims=" %%F in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0find_winpython.ps1"`) do (
  set "PYTHON_EXE=%%F"
  goto :found_python
)

:found_python
if not defined PYTHON_EXE (
  echo [ERROR] Cannot find WinPython python.exe.
  echo Put the WinPython folder beside this project, or set WINPYTHON_DIR to the WinPython folder.
  pause
  exit /b 1
)

echo Using Python:
echo %PYTHON_EXE%
echo.

"%PYTHON_EXE%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
  echo.
  echo [ERROR] pip install failed.
  pause
  exit /b 1
)

echo.
"%PYTHON_EXE%" "%~dp0check_environment.py"
if errorlevel 1 (
  echo.
  echo [ERROR] Environment check failed.
  pause
  exit /b 1
)

echo.
echo [OK] Setup completed. Use RUN_DUTY_GUI_WINPYTHON.vbs to start without a console window.
pause
