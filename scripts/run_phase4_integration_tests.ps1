$ErrorActionPreference = "Stop"

$env:PYTHONPATH = (Get-Location).Path


 

Write-Host "Running QueryGuard Phase 4 PostgreSQL integration tests..."

$env:RUN_DB_TESTS = "1"

uv run pytest tests/integration -q


 