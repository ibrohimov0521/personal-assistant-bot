@echo off
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m venv .venv
)
call .venv\Scripts\activate
python -m http.server 8090 -d miniapp
