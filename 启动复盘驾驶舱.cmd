@echo off
setlocal
title Review Cockpit Launcher

echo [Review Cockpit] Starting local service...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_review_cockpit.ps1"

if errorlevel 1 (
  echo.
  echo [Review Cockpit] Startup failed.
  echo Send this log file to Codex:
  echo %~dp0review-cockpit-launcher.log
  echo.
  pause
  exit /b 1
)

echo [Review Cockpit] Ready. Opening the browser...
ping 127.0.0.1 -n 3 >nul
exit /b 0
