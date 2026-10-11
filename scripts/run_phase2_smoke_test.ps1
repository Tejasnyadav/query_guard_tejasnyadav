$ErrorActionPreference = "Stop"


 

$env:RUN_DB_TESTS = "1"

uv run pytest tests/integration -q

$ErrorActionPreference = "Stop"

uv run python scripts/phase2_smoke_test.py