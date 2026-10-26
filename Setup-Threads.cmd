@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 goto failed
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe scripts\threads_setup.py %*
if errorlevel 1 goto failed
exit /b 0
:failed
echo Setup stopped. Read the message above; no publishing is enabled.
pause
exit /b 1
