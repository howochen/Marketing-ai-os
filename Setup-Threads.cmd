@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 goto failed
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -m scripts.threads_setup %*
if errorlevel 1 goto failed
exit /b 0
:failed
echo 設定已安全停止。請查看上方提示；既有資料保留，發文維持關閉。
pause
exit /b 1
