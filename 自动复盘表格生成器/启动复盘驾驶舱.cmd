@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  py -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

".venv\Scripts\python.exe" -c "import fastapi, uvicorn" 2>nul
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

start "复盘驾驶舱本地服务" /min ".venv\Scripts\python.exe" run_cockpit.py
