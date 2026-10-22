@echo off
setlocal
cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
  echo Run install-windows.cmd first, or use the packaged Windows installer.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m curvedesk.launcher
if errorlevel 1 pause
