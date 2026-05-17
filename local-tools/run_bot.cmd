@echo off
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m venv .venv
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
".venv\Scripts\python.exe" assistant_bot.py
