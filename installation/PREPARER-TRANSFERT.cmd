@echo off
rem Double-clic sur l'ANCIEN PC : prepare le dossier a emporter (voir README.md).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0preparer-transfert.ps1" %*
echo.
pause
