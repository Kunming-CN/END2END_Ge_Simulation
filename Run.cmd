@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\scenario_cli.ps1" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo.
if not "%RC%"=="0" echo Run failed. Existing outputs were preserved; inspect the message above.
if "%~1"=="" pause
exit /b %RC%
