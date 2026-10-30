@echo off
title FlashKV Auth Gateway — Ephemeral In-Memory 2FA System
cls
echo ===============================================================
echo   Team RediSetGo: Jatin Garg (25/CS/174) & Kanav Gupta (25/CS/187)
echo   Evaluator: Dr. Gunjan Chugh -- DTU CSE 2nd Year
echo ===============================================================
echo.
echo [1/2] Starting C++ In-Memory Storage Daemon (Port 6379)...
start /B "" "build\flashkv_server.exe" 6379 10000 > nul 2>&1
timeout /t 1 /nobreak > nul

echo [2/2] Launching AuthKV Dual-Portal Web Console on Port 5000...
echo.
echo Available Portals:
echo   --^> Sender Portal   : http://localhost:5000/
echo   --^> Receiver Portal : http://localhost:5000/verify
echo.
start "" "http://localhost:5000/"
python "backend\auth_gateway.py"
pause
