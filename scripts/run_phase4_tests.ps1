$ErrorActionPreference = "Stop"

$env:PYTHONPATH = (Get-Location).Path


 

Write-Host "Running QueryGuard Phase 2, Phase 3, and Phase 4 deterministic tests..."

uv run pytest tests/unit tests/security tests/phase3 tests/phase4 -q


 