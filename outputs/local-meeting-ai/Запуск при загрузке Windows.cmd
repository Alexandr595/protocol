@echo off
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0install-boot-task.ps1"
pause
