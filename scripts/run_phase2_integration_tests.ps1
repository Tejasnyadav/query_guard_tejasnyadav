$ErrorActionPreference = "Stop"


 

$env:RUN_DB_TESTS = "1"

uv run pytest tests/integration -q