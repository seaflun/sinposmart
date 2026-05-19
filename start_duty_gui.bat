@echo off
setlocal
cd /d "%~dp0"

where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw duty_gui.pyw
  exit /b 0
)

where py >nul 2>nul
if %errorlevel%==0 (
  start "" py -3 duty_gui.pyw
  exit /b 0
)

where python >nul 2>nul
if %errorlevel%==0 (
  start "" python duty_gui.pyw
  exit /b 0
)

echo 找不到 Python，請先安裝 Python 3.11 以上。
pause
