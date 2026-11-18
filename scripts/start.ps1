# Start the app on http://127.0.0.1:8000 (local only). Run from the repository root:
#   powershell -ExecutionPolicy Bypass -File scripts\start.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location (Join-Path $root "backend")
try {
    .\.venv\Scripts\python run_server.py @args
} finally {
    Pop-Location
}
