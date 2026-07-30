@echo off
REM Example launcher: set your remote server URL, then start the desktop app
REM Replace the URL below with your server (ensure it's reachable and allowed by firewall)

set SEEDREAM_SERVER=http://YOUR_SERVER_HOST_OR_IP:8000

set APPDIR=%~dp0
set EXE=%APPDIR%dist\SeedreamDesktop\SeedreamDesktop.exe

if not exist "%EXE%" (
  echo Could not find %%EXE%%. Build the app first with build_exe.ps1.
  exit /b 1
)

start "Seedream Desktop" "%EXE%"


