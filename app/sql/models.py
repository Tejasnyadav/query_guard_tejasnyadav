from typing import Any, Literal


from pydantic import BaseModel, Field



 

class ValidationIssue(BaseModel):

    code: str

    message: str

    severity: Literal["error", "warning"] = "error"



 

class SqlValidationResult(BaseModel):

    accepted: bool

    normalized_sql: str | None = None

    executable_sql: str | None = None

    tables: list[str] = Field(default_factory=list)

    functions: list[str] = Field(default_factory=list)

    join_count: int = 0

    subquery_depth: int = 0

    requested_limit: int | None = None

    enforced_limit: int | None = None

    truncation_probe_enabled: bool = False

    issues: list[ValidationIssue] = Field(default_factory=list)



 

class PlanSummary(BaseModel):

    accepted: bool

    total_cost: float

    top_plan_rows: int

    max_node_rows: int

    plan_width: int

    node_count: int

    sequential_scan_count: int

    nested_loop_count: int

    sort_count: int

    relations: list[str] = Field(default_factory=list)

    warnings: list[str] = Field(default_factory=list)

    rejection_reasons: list[str] = Field(default_factory=list)



 

class QueryResult(BaseModel):

    columns: list[str]

    rows: list[dict[str, Any]]

    returned_row_count: int

    truncated: bool

    duration_ms: int


 