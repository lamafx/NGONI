@echo off
rem Double-clic : installe et lance NGONI ia-service (voir README.md).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer.ps1" %*
echo.
pause
