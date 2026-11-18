# One-time setup on Windows PowerShell. Run from the repository root:
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "Creating the Python virtual environment in backend\.venv"
Push-Location (Join-Path $root "backend")
python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw "python -m venv failed" }
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
Pop-Location

Write-Host "Installing frontend packages and building the UI"
Push-Location (Join-Path $root "frontend")
npm ci
if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
npm run build
if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
Pop-Location

Write-Host "Done. Start the app with: powershell -ExecutionPolicy Bypass -File scripts\start.ps1"
