from typing import Any, Literal


 

from pydantic import BaseModel, Field



 

class AnomalyFinding(BaseModel):

    code: str

    severity: Literal["warning", "error"]

    message: str



 

class AnomalyReport(BaseModel):

    status: Literal["pass", "warn", "reject"]

    findings: list[AnomalyFinding] = Field(default_factory=list)



 

class ResultCellReference(BaseModel):

    row_index: int = Field(ge=0)

    column: str = Field(min_length=1, max_length=200)



 

class VerificationIssue(BaseModel):

    severity: Literal["info", "warning", "error"]

    category: Literal[

        "metric_definition",

        "time_range",

        "filter",

        "join",

        "grain",

        "anomaly",

        "independence",

        "reconciliation",

        "unsupported_conclusion",

        "other",

    ]

    description: str = Field(min_length=1, max_length=2_000)



 

class VerificationCheck(BaseModel):

    check_id: str = Field(

        min_length=1,

        max_length=100,

        pattern=r"^[a-z][a-z0-9_]*$",

    )

    label: str = Field(min_length=1, max_length=300)

    description: str = Field(min_length=1, max_length=1_000)

    metric_id: str = Field(min_length=1, max_length=100)

    value_type: Literal["number", "text"]

    unit: str = Field(min_length=1, max_length=50)

    calculation: str | None = Field(default=None, max_length=1_000)

    importance: Literal["primary", "supporting"] = "supporting"

    analyst_source: ResultCellReference

    absolute_tolerance: float = Field(default=0.01, ge=0, le=1_000_000)

    relative_tolerance: float = Field(default=0.000000001, ge=0, le=0.1)

    text_case_sensitive: bool = False



 

class VerificationPlan(BaseModel):

    decision: Literal["verify", "reject"]

    summary: str = Field(min_length=1, max_length=2_000)

    independence_strategy: str = Field(min_length=1, max_length=2_000)

    issues: list[VerificationIssue] = Field(default_factory=list, max_length=20)

    checks: list[VerificationCheck] = Field(default_factory=list, max_length=10)



 

class VerificationSQLCandidate(BaseModel):

    purpose: str = Field(min_length=1, max_length=1_000)

    sql: str = Field(min_length=1, max_length=50_000)

    expected_columns: list[str]

    expected_max_rows: int = Field(ge=1, le=100)

    tables_expected: list[str]

    covered_check_ids: list[str] = Field(min_length=1, max_length=10)



 

class ReconciliationComparison(BaseModel):

    check_id: str

    label: str

    value_type: Literal["number", "text"]

    analyst_source: ResultCellReference

    verifier_row_index: int = Field(ge=0)

    verifier_column: Literal["numeric_value", "text_value"]

    analyst_value: Any

    verifier_value: Any

    passed: bool

    difference: str | None = None

    tolerance_used: str | None = None

    message: str



 

class ReconciliationResult(BaseModel):

    status: Literal["pass", "mismatch", "rejected"]

    comparisons: list[ReconciliationComparison] = Field(default_factory=list)

    issues: list[str] = Field(default_factory=list)



 

class ClaimSourceReference(BaseModel):

    role: Literal["analyst", "verifier"]

    query_id: str

    row_index: int = Field(ge=0)

    column: str

    check_id: str | None = None



 

class VerifiedClaim(BaseModel):

    claim_id: str

    claim_key: str

    statement: str

    metric_id: str

    value_type: Literal["number", "text"]

    raw_value: Any

    display_value: str

    verification_status: Literal["passed"] = "passed"

    analyst_query_id: str

    verifier_query_id: str

    citation: str

    sources: list[ClaimSourceReference] = Field(default_factory=list)



 

class VerifiedAnswer(BaseModel):

    verification_status: Literal["passed"] = "passed"

    headline: str

    claims: list[VerifiedClaim]

    limitations: list[str] = Field(default_factory=list)


 