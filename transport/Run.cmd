@echo off
rem Windows entry; source remains in this project, packages stay inside WSL.
wsl.exe --distribution Ubuntu-24.04 --cd "%~dp0." -- bash ./run.sh %*
