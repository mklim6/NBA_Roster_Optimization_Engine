@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build_v3_windows_bundle.ps1" %*
if errorlevel 1 (
    echo.
    echo V3 bundle build exited with an error.
    pause
)
