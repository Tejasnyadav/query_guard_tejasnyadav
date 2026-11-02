from uuid import uuid4


 

from app.agents.models import SQLCandidate

from app.schemas.query import QueryExecutionOutcome

from app.sql.models import QueryResult, SqlValidationResult

from app.verification.anomalies import inspect_result_anomalies



 

def _candidate(expected_max_rows: int = 10) -> SQLCandidate:

    return SQLCandidate(

        purpose="test",

        sql="SELECT order_month FROM analytics.order_line_facts",

        expected_columns=["order_month"],

        expected_max_rows=expected_max_rows,

        tables_expected=["analytics.order_line_facts"],

    )



 

def _outcome(*, rows, truncated=False) -> QueryExecutionOutcome:

    return QueryExecutionOutcome(

        status="completed",

        run_id=uuid4(),

        query_id=uuid4(),

        validation=SqlValidationResult(

            accepted=True,

            normalized_sql="SELECT 1",

            executable_sql="SELECT 1 LIMIT 501",

        ),

        result=QueryResult(

            columns=["order_month"],

            rows=rows,

            returned_row_count=len(rows),

            truncated=truncated,

            duration_ms=1,

        ),

    )



 

def test_empty_result_is_rejected() -> None:

    report = inspect_result_anomalies(candidate=_candidate(), outcome=_outcome(rows=[]))

    assert report.status == "reject"

    assert report.findings[0].code == "EMPTY_ANALYST_RESULT"



 

def test_truncated_result_is_rejected() -> None:

    report = inspect_result_anomalies(

        candidate=_candidate(),

        outcome=_outcome(rows=[{"order_month": "2026-08-01"}], truncated=True),

    )

    assert report.status == "reject"

    assert any(item.code == "TRUNCATED_ANALYST_RESULT" for item in report.findings)



 

def test_duplicate_rows_create_warning() -> None:

    report = inspect_result_anomalies(

        candidate=_candidate(),

        outcome=_outcome(

            rows=[

                {"order_month": "2026-08-01"},

                {"order_month": "2026-08-01"},

            ]

        ),

    )

    assert report.status == "warn"

    assert any(item.code == "DUPLICATE_RESULT_ROWS" for item in report.findings)


 