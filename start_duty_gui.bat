@echo off
setlocal
cd /d "%~dp0"

set "PYTHONW=C:\Users\User\AppData\Local\Python\bin\pythonw.exe"
set "PYTHON=C:\Users\User\AppData\Local\Python\bin\python.exe"

if exist "%PYTHONW%" (
  start "" "%PYTHONW%" "duty_gui.pyw"
  exit /b 0
)

if exist "%PYTHON%" (
  start "" "%PYTHON%" "duty_gui.pyw"
  exit /b 0
)

echo Python not found.
pause
exit /b 1
