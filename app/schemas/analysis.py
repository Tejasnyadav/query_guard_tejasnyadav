from typing import Any, Literal

from uuid import UUID


 

from pydantic import BaseModel, Field



 

class CreateAnalysisRequest(BaseModel):

    question: str = Field(min_length=3, max_length=2_000)



 

class ClarificationAnswerRequest(BaseModel):

    choice_id: str = Field(min_length=1, max_length=100)



 

class ClarificationPrompt(BaseModel):

    question: str

    options: list[dict[str, Any]]



 

class AnalysisOutcome(BaseModel):

    status: Literal["completed", "needs_clarification", "rejected", "failed"]

    run_id: UUID

    thread_id: str

    normalized_question: str | None = None

    clarification: ClarificationPrompt | None = None

    term_resolution: dict[str, Any] | None = None

    analysis_plan: dict[str, Any] | None = None

    sql_candidate: dict[str, Any] | None = None

    query_outcome: dict[str, Any] | None = None

    draft_summary: dict[str, Any] | None = None

    error_code: str | None = None

    error_message: str | None = None


 