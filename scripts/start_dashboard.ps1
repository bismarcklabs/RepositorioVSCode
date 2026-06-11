# Crypto Dashboard — script de arranque para Windows
# Uso: Right-click → "Run with PowerShell"  o desde Task Scheduler

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $PSScriptRoot

Set-Location $ROOT

# Activar venv
& "$ROOT\venv\Scripts\Activate.ps1"

# Asegurarse de que el directorio de datos existe
New-Item -ItemType Directory -Force -Path "$ROOT\data"  | Out-Null
New-Item -ItemType Directory -Force -Path "$ROOT\logs"  | Out-Null

Write-Host "[start_dashboard] Lanzando Streamlit en http://localhost:8501" -ForegroundColor Cyan

& "$ROOT\venv\Scripts\python.exe" -m streamlit run app/main.py `
    --server.address=0.0.0.0 `
    --server.port=8501 `
    --server.headless=true `
    --browser.serverAddress=localhost
