$ErrorActionPreference = "Stop"


 

Write-Host "Running deterministic unit and security tests..."

uv run pytest tests/unit tests/security -q


 

Write-Host "Tests passed."


 