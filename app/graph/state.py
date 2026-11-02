from typing import Any, TypedDict



 

class AnalysisState(TypedDict, total=False):

    run_id: str

    thread_id: str

    question: str

    normalized_question: str


 

    schema_snapshot: dict[str, Any]

    term_resolution: dict[str, Any]

    term_resolution_version: int

    time_context: dict[str, Any]

    clarification_answer: dict[str, Any]

    analysis_plan: dict[str, Any]


 

    sql_candidate: dict[str, Any]

    repair_attempts: int

    query_outcome: dict[str, Any]

    draft_summary: dict[str, Any]


 

    anomaly_report: dict[str, Any]

    verification_plan: dict[str, Any]

    verification_sql_candidate: dict[str, Any]

    verification_candidate_error: dict[str, Any] | None

    verification_sql_repair_attempts: int

    verification_query_outcome: dict[str, Any]

    reconciliation: dict[str, Any]

    verification_repair_attempts: int

    claim_ledger: dict[str, Any]

    verified_answer: dict[str, Any]


 

    status: str

    error_code: str | None

    error_message: str | None


 