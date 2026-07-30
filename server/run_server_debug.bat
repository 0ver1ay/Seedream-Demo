@echo off
setlocal
set SEEDREAM_HOST=0.0.0.0
set SEEDREAM_PORT=8000

echo [debug] Starting server with HOST=%SEEDREAM_HOST% PORT=%SEEDREAM_PORT%
python -m server.run_server 2>&1 | tee server_debug.log
echo.
echo [debug] Server exited. Log saved to server_debug.log
pause
endlocal




