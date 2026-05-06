@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0setup_forwarder.ps1"
pause
