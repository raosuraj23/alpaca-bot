Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "Alpaca Bot Local Environment Setup" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

Write-Host "[1/3] Creating Python virtual environment..." -ForegroundColor Yellow
python -m venv venv

Write-Host "[2/3] Activating virtual environment..." -ForegroundColor Yellow
& .\venv\Scripts\Activate.ps1

Write-Host "[3/3] Installing dependencies..." -ForegroundColor Yellow
python -m pip install --upgrade pip
pip install -r backend/requirements.txt

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "To activate the environment: .\venv\Scripts\Activate.ps1" -ForegroundColor Cyan
Write-Host "To start the backend:        cd backend; uvicorn main:app --reload" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
