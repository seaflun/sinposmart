@echo off
setlocal
cd /d "%~dp0"

if /i not "%~1"=="--hidden" (
  wscript.exe "%~dp0RUN_DUTY_GUI_WINPYTHON.vbs" --check-update
  exit /b 0
)

for /f "usebackq delims=" %%F in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0find_winpython.ps1" -Windowed`) do (
  set "UPDATE_PYTHONW=%%F"
  goto :found_pythonw
)

:found_pythonw
if not defined UPDATE_PYTHONW exit /b 1
start "" /b /wait "%UPDATE_PYTHONW%" -m qt_app.controllers.update_controller --check
exit /b %ERRORLEVEL%
