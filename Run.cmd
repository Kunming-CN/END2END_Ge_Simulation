@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\scenario_cli.ps1" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo. 1>&2
if not "%RC%"=="0" echo Command returned a nonzero status; see diagnostics. No automatic recovery was attempted. 1>&2
if "%~1"=="" pause
exit /b %RC%
