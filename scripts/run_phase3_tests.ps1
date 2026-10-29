$ErrorActionPreference = "Stop"

uv run python -m pytest tests/unit tests/security tests/phase3 -q

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}