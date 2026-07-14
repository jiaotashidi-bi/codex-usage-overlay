@echo off
setlocal
cd /d "%~dp0"

where pythonw.exe >nul 2>nul
if errorlevel 1 goto console_fallback

start "" pythonw.exe "%~dp0main.py"
exit /b 0

:console_fallback
python "%~dp0main.py"
if errorlevel 1 pause

