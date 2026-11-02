$ErrorActionPreference = "Stop"

$env:PYTHONPATH = (Get-Location).Path


 

Write-Host "Running QueryGuard Phase 4 end-to-end smoke test..."

Write-Host "FastAPI must already be running at http://127.0.0.1:8000"

uv run python scripts/phase4_smoke_test.py


 