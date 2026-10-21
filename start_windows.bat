@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_windows.ps1"
if errorlevel 1 (
  echo.
  echo Setup or launch failed. Read the message above, then rerun this launcher after fixing it.
  pause
)
endlocal
