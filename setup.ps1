# Setup script for Crypto Dashboard
# Run this in PowerShell with: .\setup.ps1

Set-Location $PSScriptRoot

Write-Host "Creating virtual environment..." -ForegroundColor Green
python -m venv venv

Write-Host "`nActivating virtual environment..." -ForegroundColor Green
& .\venv\Scripts\Activate.ps1

Write-Host "`nInstalling dependencies..." -ForegroundColor Green
pip install --upgrade pip
pip install -r requirements.txt

Write-Host "`nSetup complete!" -ForegroundColor Green
Write-Host "To run the dashboard, use:" -ForegroundColor Yellow
Write-Host "  streamlit run app/main.py" -ForegroundColor Yellow
