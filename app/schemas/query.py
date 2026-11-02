from typing import Literal

from uuid import UUID


 

from pydantic import BaseModel, Field, model_validator


 

from app.sql.models import PlanSummary, QueryResult, SqlValidationResult



 

class ValidateSqlRequest(BaseModel):

    sql: str = Field(min_length=1, max_length=50_000)



 

class DirectExecuteSqlRequest(BaseModel):

    question: str = Field(min_length=1, max_length=2_000)

    purpose: str = Field(min_length=1, max_length=1_000)

    sql: str = Field(min_length=1, max_length=50_000)

    expected_tables: list[str] | None = Field(default=None, max_length=20)

    expected_columns: list[str] | None = Field(default=None, max_length=100)



 

class ExecuteSqlRequest(BaseModel):

    question: str = Field(min_length=1, max_length=2_000)

    purpose: str = Field(min_length=1, max_length=1_000)

    sql: str = Field(min_length=1, max_length=50_000)

    expected_tables: list[str] | None = Field(default=None, max_length=20)

    expected_columns: list[str] | None = Field(default=None, max_length=100)

    query_role: Literal["manual", "analyst", "verifier"] = "manual"

    parent_query_id: UUID | None = None

    candidate_key: str | None = Field(default=None, max_length=100)


 

    @model_validator(mode="after")

    def validate_role_metadata(self) -> "ExecuteSqlRequest":

        if self.query_role == "verifier" and self.parent_query_id is None:

            raise ValueError("Verifier queries must reference their Analyst parent query.")

        if self.query_role != "verifier" and self.parent_query_id is not None:

            raise ValueError("Only Verifier queries may set parent_query_id.")

        return self



 

class QueryExecutionOutcome(BaseModel):

    status: Literal["completed", "rejected", "failed"]

    run_id: UUID

    query_id: UUID

    validation: SqlValidationResult

    plan: PlanSummary | None = None

    result: QueryResult | None = None

    error_code: str | None = None

    error_message: str | None = None


 