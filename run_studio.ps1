Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "          Launching FlashKV Server & Web Studio             " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Start C++ Server
Write-Host "[1/3] Starting C++ Database Server on Port 6379..." -ForegroundColor Yellow
Start-Process -FilePath "build\flashkv_server.exe" -ArgumentList "6379", "10000"

Start-Sleep -Seconds 1

# 2. Start Python Web Studio Dashboard
Write-Host "[2/3] Starting Studio Web GUI on Port 8080..." -ForegroundColor Yellow
Start-Process -FilePath "python" -ArgumentList "gui\dashboard.py"

Start-Sleep -Seconds 1

# 3. Open browser
Write-Host "[3/3] Opening Dashboard in your Web Browser..." -ForegroundColor Green
Start-Process "http://localhost:8080"

Write-Host ""
Write-Host "FlashKV Studio is Live at: http://localhost:8080" -ForegroundColor Green
Write-Host "Press Ctrl+C or close the process windows to stop." -ForegroundColor Gray
