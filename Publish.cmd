@echo off
setlocal
"%ProgramFiles%\nodejs\node.exe" "%~dp0tools\publish.mjs"
if errorlevel 1 echo Publication stopped. Read the error above; no force push was attempted.
pause
