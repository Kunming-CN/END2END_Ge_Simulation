@echo off
rem Finite opt-in gamma transport; existing locked Ubuntu runtime only.
wsl.exe --distribution Ubuntu-24.04 --cd "%~dp0." -- bash ./gamma.sh %*
