from pathlib import Path

from typing import Literal


 

import yaml

from pydantic import BaseModel, Field, model_validator



 

class SqlPolicy(BaseModel):

    dialect: str = "postgres"


 

    allowed_schemas: set[str] = Field(default_factory=set)

    allowed_tables: set[str] = Field(default_factory=set)


 

    require_schema_qualification: bool = True

    forbid_select_star: bool = True

    allow_recursive_cte: bool = False

    allow_cross_join: bool = False

    require_join_condition: bool = True


 

    max_sql_length: int = Field(default=20_000, ge=1)

    max_joins: int = Field(default=6, ge=0)

    max_subquery_depth: int = Field(default=4, ge=1)

    max_offset: int = Field(default=10_000, ge=0)

    max_result_rows: int = Field(default=500, ge=1)

    fetch_probe_rows: int = Field(default=1, ge=0, le=10)


 

    max_plan_cost: float = Field(default=100_000, gt=0)

    max_plan_rows: int = Field(default=1_000_000, ge=1)

    warn_plan_cost_ratio: float = Field(default=0.8, ge=0, le=1)


 

    statement_timeout_ms: int = Field(default=8_000, ge=100, le=120_000)

    lock_timeout_ms: int = Field(default=1_000, ge=50, le=60_000)


 

    function_policy: Literal["allowlist", "denylist"] = "allowlist"

    allowed_functions: set[str] = Field(default_factory=set)

    denied_functions: set[str] = Field(default_factory=set)

    denied_columns: set[str] = Field(default_factory=set)


 

    @model_validator(mode="after")

    def normalize_names(self) -> "SqlPolicy":

        self.allowed_schemas = {value.lower() for value in self.allowed_schemas}

        self.allowed_tables = {value.lower() for value in self.allowed_tables}

        self.allowed_functions = {value.upper() for value in self.allowed_functions}

        self.denied_functions = {value.upper() for value in self.denied_functions}

        self.denied_columns = {value.lower() for value in self.denied_columns}

        return self



 

def load_sql_policy(path: str | Path) -> SqlPolicy:

    policy_path = Path(path)

    if not policy_path.exists():

        raise FileNotFoundError(f"SQL policy file not found: {policy_path}")


 

    with policy_path.open("r", encoding="utf-8") as file:

        data = yaml.safe_load(file) or {}


 

    return SqlPolicy.model_validate(data)


 