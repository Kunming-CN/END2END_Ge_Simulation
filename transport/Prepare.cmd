@echo off
rem Opt-in geometry/source preparation only; uses the existing locked environment.
wsl.exe --distribution Ubuntu-24.04 --cd "%~dp0." -- bash ./prepare.sh %*
