@echo off
setlocal
if /I "%~1"=="stop" goto stop
if /I "%~1"=="doctor" goto doctor
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\start.ps1" %*
exit /b %ERRORLEVEL%
:stop
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\stop.ps1"
exit /b %ERRORLEVEL%
:doctor
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\doctor.ps1"
exit /b %ERRORLEVEL%
