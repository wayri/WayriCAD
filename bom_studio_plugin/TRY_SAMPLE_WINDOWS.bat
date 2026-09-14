@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_windows.ps1" --demo %*
if errorlevel 1 pause
endlocal
