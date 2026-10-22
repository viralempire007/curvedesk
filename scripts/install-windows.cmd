@echo off
setlocal
cd /d "%~dp0\.."
where py >nul 2>nul
if errorlevel 1 goto missing
py -3 -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ required'"
if errorlevel 1 goto failed
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m unittest discover -s tests -q
if errorlevel 1 goto failed
".venv\Scripts\python.exe" scripts\desktop-shortcut.py
if errorlevel 1 goto failed
call scripts\start-windows.cmd
exit /b %errorlevel%
:missing
echo Python is required for source setup. Use the packaged CurveDesk installer to run without Python.
goto failed
:failed
echo Setup failed. Review the message above. Saved data was retained.
pause
exit /b 1
