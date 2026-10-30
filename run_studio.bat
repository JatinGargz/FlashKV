@echo off
title FlashKV Studio Launcher
echo ============================================================
echo           Launching FlashKV Server & Web Studio             
echo ============================================================
echo.

:: 1. Start C++ Server in background window
echo [1/3] Starting C++ Database Server on Port 6379...
start "FlashKV C++ Server (Port 6379)" build\flashkv_server.exe 6379 10000
timeout /t 1 >nul

:: 2. Start Python Web Studio Dashboard
echo [2/3] Starting Studio Web GUI on Port 8080...
start "FlashKV Studio Web Dashboard" python gui\dashboard.py
timeout /t 1 >nul

:: 3. Launch Default Browser
echo [3/3] Opening Dashboard in your Web Browser...
start http://localhost:8080

echo.
echo ============================================================
echo   FlashKV Studio is Live at: http://localhost:8080
echo ============================================================
echo.
pause
