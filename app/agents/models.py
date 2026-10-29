from datetime import date

from typing import Literal


 

from pydantic import BaseModel, Field



 

class ClarificationOption(BaseModel):

    choice_id: str

    label: str

    description: str



 

class ClarificationAnswer(BaseModel):

    choice_id: str = Field(min_length=1, max_length=100)



 

class TermResolution(BaseModel):

    interpretation: str

    metric_ids: list[str]

    dimension_ids: list[str]

    needs_clarification: bool

    clarification_question: str | None

    clarification_options: list[ClarificationOption]

    time_intent: Literal[

        "last_complete_month",

        "last_complete_month_vs_previous",

        "explicit_months",

        "all_available",

    ]

    explicit_months: list[str]

    assumptions: list[str]



 

class TimeWindow(BaseModel):

    role: Literal["primary", "comparison"]

    label: str

    start: date

    end_exclusive: date

    is_complete: bool



 

class ResolvedTimeContext(BaseModel):

    basis: str

    windows: list[TimeWindow]

    warnings: list[str] = Field(default_factory=list)



 

class AnalysisStep(BaseModel):

    order: int = Field(ge=1, le=20)

    description: str

    rationale: str



 

class AnalysisPlanOutline(BaseModel):

    objective: str

    required_views: list[str]

    group_by_columns: list[str]

    required_filters: list[str]

    output_grain: str

    expected_columns: list[str]

    steps: list[AnalysisStep]

    assumptions: list[str]



 

class AnalysisPlan(BaseModel):

    objective: str

    metric_ids: list[str]

    dimension_ids: list[str]

    time_context: ResolvedTimeContext

    required_views: list[str]

    group_by_columns: list[str]

    required_filters: list[str]

    output_grain: str

    expected_columns: list[str]

    steps: list[AnalysisStep]

    assumptions: list[str]



 

class SQLCandidate(BaseModel):

    purpose: str

    sql: str = Field(min_length=1, max_length=50_000)

    expected_columns: list[str]

    expected_max_rows: int = Field(ge=1, le=500)

    tables_expected: list[str]



 

class EvidenceReference(BaseModel):

    row_indices: list[int]

    columns: list[str]



 

class DraftObservation(BaseModel):

    text: str

    evidence: list[EvidenceReference]



 

class DraftSummary(BaseModel):

    headline: str

    observations: list[DraftObservation]

    limitations: list[str]

    verification_status: Literal["draft_unverified"] = "draft_unverified"


 