# AI Agent - Start script
# Run from app/: .\start.ps1

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

Write-Host "Starting backend..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "
    Set-Location '$backend'
    & '$backend\venv\Scripts\Activate.ps1'
    python main.py
" -WindowStyle Normal

Start-Sleep -Seconds 2

Write-Host "Starting frontend..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "
    Set-Location '$frontend'
    npm run dev
" -WindowStyle Normal

Write-Host "Done. Backend: http://localhost:8001 | Frontend: http://localhost:5173" -ForegroundColor Green
