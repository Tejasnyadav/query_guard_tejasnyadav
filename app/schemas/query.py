from typing import Literal

from uuid import UUID


 

from pydantic import BaseModel, Field


 

from app.sql.models import PlanSummary, QueryResult, SqlValidationResult



 

class ValidateSqlRequest(BaseModel):

    sql: str = Field(min_length=1, max_length=50_000)



 

class ExecuteSqlRequest(BaseModel):

    question: str = Field(min_length=1, max_length=2_000)

    purpose: str = Field(min_length=1, max_length=1_000)

    sql: str = Field(min_length=1, max_length=50_000)



 

class QueryExecutionOutcome(BaseModel):

    status: Literal["completed", "rejected", "failed"]

    run_id: UUID

    query_id: UUID

    validation: SqlValidationResult

    plan: PlanSummary | None = None

    result: QueryResult | None = None

    error_code: str | None = None

    error_message: str | None = None


 