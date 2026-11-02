import json

import math

from typing import Any


 

from app.agents.models import SQLCandidate

from app.schemas.query import QueryExecutionOutcome

from app.verification.models import AnomalyFinding, AnomalyReport



 

_NON_FINITE_TEXT = {

    "nan",

    "+nan",

    "-nan",

    "infinity",

    "+infinity",

    "-infinity",

    "inf",

    "+inf",

    "-inf",

}



 

def inspect_result_anomalies(

    *,

    candidate: SQLCandidate,

    outcome: QueryExecutionOutcome,

) -> AnomalyReport:

    findings: list[AnomalyFinding] = []


 

    if outcome.status != "completed" or outcome.result is None:

        return AnomalyReport(

            status="reject",

            findings=[

                AnomalyFinding(

                    code="MISSING_COMPLETED_RESULT",

                    severity="error",

                    message="The Analyst query did not produce a completed result.",

                )

            ],

        )


 

    result = outcome.result

    if result.returned_row_count == 0:

        findings.append(

            AnomalyFinding(

                code="EMPTY_ANALYST_RESULT",

                severity="error",

                message="The Analyst query returned no rows, so there is nothing to verify.",

            )

        )


 

    if result.truncated:

        findings.append(

            AnomalyFinding(

                code="TRUNCATED_ANALYST_RESULT",

                severity="error",

                message=(

                    "The Analyst result was truncated. Verification requires the complete compact "

                    "result, so the query must be rewritten to aggregate more strongly."

                ),

            )

        )


 

    if result.returned_row_count > candidate.expected_max_rows:

        findings.append(

            AnomalyFinding(

                code="EXPECTED_ROW_COUNT_EXCEEDED",

                severity="error",

                message=(

                    f"The Analyst declared at most {candidate.expected_max_rows} rows but returned "

                    f"{result.returned_row_count}."

                ),

            )

        )


 

    if result.rows:

        row_signatures = [json.dumps(row, sort_keys=True, default=str) for row in result.rows]

        if len(row_signatures) != len(set(row_signatures)):

            findings.append(

                AnomalyFinding(

                    code="DUPLICATE_RESULT_ROWS",

                    severity="warning",

                    message="The Analyst result contains exact duplicate rows.",

                )

            )


 

        all_values = [value for row in result.rows for value in row.values()]

        if all(value is None for value in all_values):

            findings.append(

                AnomalyFinding(

                    code="ALL_RESULT_VALUES_NULL",

                    severity="error",

                    message="Every value in the Analyst result is null.",

                )

            )


 

        for column in result.columns:

            column_values = [row.get(column) for row in result.rows]

            if column_values and all(value is None for value in column_values):

                findings.append(

                    AnomalyFinding(

                        code="ALL_NULL_COLUMN",

                        severity="warning",

                        message=f"Result column '{column}' contains only null values.",

                    )

                )


 

        if any(_is_non_finite(value) for value in all_values):

            findings.append(

                AnomalyFinding(

                    code="NON_FINITE_RESULT_VALUE",

                    severity="error",

                    message="The Analyst result contains NaN or an infinite numeric value.",

                )

            )


 

    if any(finding.severity == "error" for finding in findings):

        status = "reject"

    elif findings:

        status = "warn"

    else:

        status = "pass"


 

    return AnomalyReport(status=status, findings=findings)



 

def _is_non_finite(value: Any) -> bool:

    if isinstance(value, float):

        return not math.isfinite(value)

    if isinstance(value, str):

        return value.strip().lower() in _NON_FINITE_TEXT

    return False


 