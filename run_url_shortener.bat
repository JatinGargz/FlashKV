@echo off
cd /d "%~dp0"
title Mini-Redis URL Shortener
echo ============================================================
echo         Starting Mini-Redis Engine and URL Shortener        
echo ============================================================
echo.

:: 1. Start C++ Mini-Redis Server on port 6379
echo [1/3] Starting C++ In-Memory Engine (Port 6379)...
start "Mini-Redis C++ Server (Port 6379)" build\flashkv_server.exe 6379 10000
timeout /t 1 >nul

:: 2. Start URL Shortener App on port 5000
echo [2/3] Starting URL Shortener Web App (Port 5000)...
start "URL Shortener Web Service" python gui\urlshortener.py
timeout /t 1 >nul

:: 3. Launch Default Browser
echo [3/3] Opening Web App in Browser...
start http://localhost:5000

echo.
echo ============================================================
echo   URL Shortener is live at: http://localhost:5000
echo   Mini-Redis Server is running on port: 6379
echo ============================================================
echo.
pause
