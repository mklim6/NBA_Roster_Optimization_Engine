@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\run_v3_desktop.ps1"
if errorlevel 1 (
    echo.
    echo V3 launcher exited with an error.
    pause
)
