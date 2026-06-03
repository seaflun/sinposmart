@echo off
setlocal
cd /d "%~dp0"

set "PYTHONW="
set "PYTHON="

if exist "%~dp0find_winpython.ps1" (
  for /f "usebackq delims=" %%F in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0find_winpython.ps1" -Windowed`) do (
    set "PYTHONW=%%F"
    goto :found_pythonw
  )
)

:found_pythonw
if not defined PYTHONW (
  for %%F in (pythonw.exe) do set "PYTHONW=%%~$PATH:F"
)

if not defined PYTHONW (
  for %%F in (pyw.exe) do set "PYTHONW=%%~$PATH:F"
)

if exist "%PYTHONW%" (
  start "" "%PYTHONW%" "duty_gui.pyw"
  exit /b 0
)

if exist "%~dp0find_winpython.ps1" (
  for /f "usebackq delims=" %%F in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0find_winpython.ps1"`) do (
    set "PYTHON=%%F"
    goto :found_python
  )
)

:found_python
if not defined PYTHON (
  for %%F in (python.exe) do set "PYTHON=%%~$PATH:F"
)

if not defined PYTHON (
  for %%F in (py.exe) do set "PYTHON=%%~$PATH:F"
)

if exist "%PYTHON%" (
  start "" "%PYTHON%" "duty_gui.pyw"
  exit /b 0
)

echo Python not found.
pause
exit /b 1
