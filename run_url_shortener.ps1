Set-Location $PSScriptRoot

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "       Starting Mini-Redis Engine and URL Shortener         " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Start C++ Mini-Redis Server
Write-Host "[1/3] Starting C++ In-Memory Engine (Port 6379)..." -ForegroundColor Yellow
Start-Process -FilePath "build\flashkv_server.exe" -ArgumentList "6379", "10000"

Start-Sleep -Seconds 1

# 2. Start URL Shortener Web App
Write-Host "[2/3] Starting URL Shortener Web App (Port 5000)..." -ForegroundColor Yellow
Start-Process -FilePath "python" -ArgumentList "gui\urlshortener.py"

Start-Sleep -Seconds 1

# 3. Open browser
Write-Host "[3/3] Opening Web App in Browser..." -ForegroundColor Green
Start-Process "http://localhost:5000"

Write-Host ""
Write-Host "URL Shortener is live at: http://localhost:5000" -ForegroundColor Green
Write-Host "Mini-Redis Server is running on port: 6379" -ForegroundColor Gray
Write-Host "Close the process windows or press Ctrl+C to stop." -ForegroundColor Gray
