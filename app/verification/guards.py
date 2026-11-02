import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.catalog.models import SemanticCatalog
from app.core.errors import AgentWorkflowError
from app.sql.policy import SqlPolicy
from app.verification.models import VerificationPlan, VerificationSQLCandidate

_REQUIRED_VERIFIER_COLUMNS = ["check_id", "numeric_value", "text_value"]

_UNSUPPORTED_CAUSAL_LABEL = re.compile(

    (

        r"\b(cause|caused|causes|because of|due to|driven by|responsible for|"

        r"led to|leads to|resulted in|results in)\b"

    ),

    flags=re.IGNORECASE,

)

_CURRENCY_OR_PERCENT_IN_LABEL = re.compile(r"[%₹$€£]")

_YEAR_TOKEN_IN_LABEL = re.compile(r"\b(?:19|20|21)\d{2}\b")

_MAX_RELATIVE_TOLERANCE = 0.000000001

_MAX_ABSOLUTE_TOLERANCE = {
    "INR": 0.01,
    "INR_per_order": 0.01,
    "percent": 0.01,
    "ratio": 0.000000001,
    "orders": 0.0,
    "customers": 0.0,
    "count": 0.0,

}

_ALLOWED_LITERAL_TEXT_CHECK_IDS = {
    "comparison_label",
}



 

def validate_verification_plan(

    *,

    plan: VerificationPlan,

    analyst_columns: list[str],

    analyst_rows: list[dict],

    catalog: SemanticCatalog,

    max_checks: int,

) -> VerificationPlan:

    if plan.decision == "reject":

        if not any(issue.severity == "error" for issue in plan.issues):

            raise AgentWorkflowError(

                code="VERIFIER_REJECTION_WITHOUT_ERROR",

                message="The Verifier rejected the methodology without identifying an error.",

            )

        return plan


 

    if any(issue.severity == "error" for issue in plan.issues):

        raise AgentWorkflowError(

            code="VERIFIER_PLAN_CONTRADICTION",

            message="The Verifier requested execution while reporting a methodology error.",

        )


 

    if not plan.checks:

        raise AgentWorkflowError(

            code="VERIFIER_CHECKS_REQUIRED",

            message="The Verifier must define at least one material check.",

        )

    if len(plan.checks) > max_checks:

        raise AgentWorkflowError(

            code="TOO_MANY_VERIFICATION_CHECKS",

            message=f"The Verifier requested more than {max_checks} checks.",

        )


 

    if not any(check.importance == "primary" for check in plan.checks):

        raise AgentWorkflowError(

            code="PRIMARY_VERIFICATION_CHECK_REQUIRED",

            message="At least one verification check must be marked as primary.",

        )


 

    check_ids = [check.check_id for check in plan.checks]

    if len(check_ids) != len(set(check_ids)):

        raise AgentWorkflowError(

            code="DUPLICATE_VERIFICATION_CHECK_ID",

            message="Every verification check must have a unique check_id.",

        )


 

    for check in plan.checks:

        label_without_years = _YEAR_TOKEN_IN_LABEL.sub("", check.label)

        if (

            _CURRENCY_OR_PERCENT_IN_LABEL.search(check.label)

            or re.search(r"\d", label_without_years)

        ):

            raise AgentWorkflowError(

                code="VERIFICATION_LABEL_CONTAINS_VALUE",

                message=(

                    f"Verification check '{check.check_id}' placed a number or currency "

                    "symbol in its label. Values must come only from reconciled result cells."

                ),

            )

        if _UNSUPPORTED_CAUSAL_LABEL.search(check.label):

            raise AgentWorkflowError(

                code="UNSUPPORTED_CAUSAL_CLAIM_LABEL",

                message=(

                    f"Verification check '{check.check_id}' used causal wording in a "

                    "descriptive-analysis claim label."

                ),

            )

        if check.metric_id not in catalog.metrics:

            raise AgentWorkflowError(

                code="UNKNOWN_VERIFICATION_METRIC",

                message=f"Verification check '{check.check_id}' used an unknown metric ID.",

            )

        allowed_units = {

            catalog.metrics[check.metric_id].unit,
            "percent",
            "ratio",
            "count",

            "text",

            "INR",

            "INR_per_order",

            "orders",

            "customers",

        }

        if check.unit not in allowed_units:

            raise AgentWorkflowError(

                code="UNKNOWN_VERIFICATION_UNIT",

                message=(

                    f"Verification check '{check.check_id}' used unsupported unit "

                    f"'{check.unit}'."

                ),

            )

        if check.value_type == "text" and check.unit != "text":

            raise AgentWorkflowError(

                code="TEXT_CHECK_UNIT_INVALID",

                message="Text verification checks must use unit 'text'.",

            )

        if check.value_type == "number" and check.unit == "text":

            raise AgentWorkflowError(

                code="NUMERIC_CHECK_UNIT_INVALID",

                message="Numeric verification checks cannot use unit 'text'.",

            )

        if check.value_type == "number":

            # Tolerances are safety policy, not model discretion. A model may request a

            # smaller tolerance, but deterministic code caps it at the unit-specific limit.

            max_absolute = _MAX_ABSOLUTE_TOLERANCE.get(check.unit, 0.01)

            check.absolute_tolerance = min(check.absolute_tolerance, max_absolute)

            check.relative_tolerance = min(

                check.relative_tolerance,

                _MAX_RELATIVE_TOLERANCE,

            )

        if check.analyst_source.column not in analyst_columns:

            raise AgentWorkflowError(

                code="VERIFIER_SOURCE_COLUMN_NOT_FOUND",

                message=(

                    f"Verification check '{check.check_id}' referenced missing Analyst column "

                    f"'{check.analyst_source.column}'."

                ),

            )

        if check.analyst_source.row_index >= len(analyst_rows):

            raise AgentWorkflowError(

                code="VERIFIER_SOURCE_ROW_NOT_FOUND",

                message=(

                    f"Verification check '{check.check_id}' referenced Analyst row "

                    f"{check.analyst_source.row_index}, which does not exist."

                ),

            )

        value = analyst_rows[check.analyst_source.row_index].get(check.analyst_source.column)

        if value is None:

            raise AgentWorkflowError(

                code="VERIFIER_SOURCE_VALUE_NULL",

                message=f"Verification check '{check.check_id}' referenced a null value.",

            )


 

    return plan



 

def validate_verification_sql_candidate(

    *,

    candidate: VerificationSQLCandidate,

    plan: VerificationPlan,

    analyst_sql: str,

    policy: SqlPolicy,

) -> VerificationSQLCandidate:

    expected_check_ids = {check.check_id for check in plan.checks}

    covered_check_ids = set(candidate.covered_check_ids)


 

    if candidate.expected_columns != _REQUIRED_VERIFIER_COLUMNS:

        raise AgentWorkflowError(

            code="VERIFIER_RESULT_CONTRACT_INVALID",

            message=(

                "The verification query must return exactly: check_id, numeric_value, "

                "text_value, in that order."

            ),

        )

    if covered_check_ids != expected_check_ids:

        raise AgentWorkflowError(

            code="VERIFIER_CHECK_COVERAGE_MISMATCH",

            message=(

                f"The verification SQL must cover checks {sorted(expected_check_ids)}; "

                f"it declared {sorted(covered_check_ids)}."

            ),

        )

    if candidate.expected_max_rows != len(expected_check_ids):

        raise AgentWorkflowError(

            code="VERIFIER_ROW_CONTRACT_MISMATCH",

            message="The verification query must declare one result row per check_id.",

        )

    if not candidate.tables_expected:

        raise AgentWorkflowError(

            code="VERIFIER_TABLES_REQUIRED",

            message="The verification candidate must declare its expected tables.",

        )

    if not set(candidate.tables_expected).issubset(policy.allowed_tables):

        raise AgentWorkflowError(

            code="VERIFIER_TABLE_NOT_ALLOWED",

            message="The verification candidate declared a table outside the SQL allowlist.",

        )


 

    if _canonical_sql(candidate.sql) == _canonical_sql(analyst_sql):

        raise AgentWorkflowError(

            code="VERIFIER_QUERY_NOT_INDEPENDENT",

            message="The Verifier query cannot be identical to the Analyst query.",

        )


 

    _validate_computed_check_rows(candidate.sql, plan, policy)

    return candidate



 

def _validate_computed_check_rows(

    sql: str,

    plan: VerificationPlan,

    policy: SqlPolicy,

) -> None:

    """Reject verification rows that merely echo hard-coded values.


 

    Phase 2 still performs the full SQL security validation. This guard only enforces the

    verifier-specific result contract: each final check row must identify a literal check_id,

    and its value must be computed from database columns, an aggregate, or a subquery.

    """


 

    try:

        statement = sqlglot.parse_one(sql, read=policy.dialect)

    except ParseError as exc:

        raise AgentWorkflowError(

            code="VERIFIER_SQL_PARSE_ERROR",

            message="The verification SQL could not be parsed for result-contract checks.",

        ) from exc


 

    expected = {check.check_id: check for check in plan.checks}

    discovered: dict[

        str,

        tuple[exp.Select, exp.Expression, exp.Expression],

    ] = {}


 

    for select in statement.find_all(exp.Select):

        projections = {

            projection.alias_or_name.lower(): projection

            for projection in select.expressions

            if projection.alias_or_name

        }

        if "check_id" not in projections:

            # CTEs used to prepare data do not need the final three-column contract.

            continue

        if set(_REQUIRED_VERIFIER_COLUMNS) - set(projections):

            raise AgentWorkflowError(

                code="VERIFIER_RESULT_CONTRACT_INVALID",

                message=(

                    "Every final verification SELECT branch must produce check_id, "

                    "numeric_value, and text_value."

                ),

            )


 

        check_id = _string_literal_value(_projection_expression(projections["check_id"]))

        if not check_id:

            raise AgentWorkflowError(

                code="VERIFIER_CHECK_ID_MUST_BE_LITERAL",
                message=(
                    "Every final verification result branch must project its own literal "
                    "check_id; do not select check_id from a table or CTE."
                ),

            )

        if check_id in discovered:

            raise AgentWorkflowError(

                code="DUPLICATE_VERIFIER_SQL_CHECK_ID",

                message=f"The verification SQL defines check_id '{check_id}' more than once.",

            )


 

        numeric_expression = _projection_expression(projections["numeric_value"])

        text_expression = _projection_expression(projections["text_value"])

        discovered[check_id] = (select, numeric_expression, text_expression)


 

    if set(discovered) != set(expected):

        raise AgentWorkflowError(

            code="VERIFIER_SQL_CHECK_IDS_MISMATCH",

            message=(

                f"The verification SQL must contain literal check rows {sorted(expected)}; "

                f"it contains {sorted(discovered)}."

            ),

        )


 

    for check_id, check in expected.items():

        select, numeric_expression, text_expression = discovered[check_id]

        if check.value_type == "number":

            if _is_null_expression(numeric_expression):

                raise AgentWorkflowError(

                    code="VERIFIER_NUMERIC_VALUE_REQUIRED",

                    message=f"Check '{check_id}' must compute numeric_value.",

                )

            if not _is_database_derived(numeric_expression, select):

                raise AgentWorkflowError(

                    code="VERIFIER_HARDCODED_VALUE_REJECTED",

                    message=(

                        f"Check '{check_id}' returned a hard-coded numeric value instead of "

                        "computing it from database data."

                    ),

                )

            if not _is_null_expression(text_expression):

                raise AgentWorkflowError(

                    code="VERIFIER_TEXT_VALUE_MUST_BE_NULL",

                    message=f"Numeric check '{check_id}' must return NULL in text_value.",

                )

        else:

            # Text checks must return a non-NULL text value.
            if _is_null_expression(text_expression):
                raise AgentWorkflowError(
                    code="VERIFIER_TEXT_VALUE_REQUIRED",
                    message=f"Check '{check_id}' must provide text_value.",
                )

            # Literal text is allowed only for explicitly approved metadata checks.
            # Example: comparison_label = 'August 2026 vs July 2026'
            is_approved_literal_metadata = (
                check_id in _ALLOWED_LITERAL_TEXT_CHECK_IDS
                and _string_literal_value(text_expression) is not None
            )

            # All other text checks must be derived from database data.
            if (
                not is_approved_literal_metadata
                and not _is_database_derived(text_expression, select)
            ):
                raise AgentWorkflowError(
                    code="VERIFIER_HARDCODED_VALUE_REJECTED",
                    message=(
                        f"Check '{check_id}' returned a hard-coded text value "
                        "instead of computing it from database data."
                    ),
                )

            # Text checks must not also return a numeric result.
            if not _is_null_expression(numeric_expression):
                raise AgentWorkflowError(
                    code="VERIFIER_NUMERIC_VALUE_MUST_BE_NULL",
                    message=(
                        f"Text check '{check_id}' must return NULL in numeric_value."
                    ),
                )


 

def _projection_expression(projection: exp.Expression) -> exp.Expression:

    return projection.this if isinstance(projection, exp.Alias) else projection



 

def _unwrap(expression: exp.Expression) -> exp.Expression:

    current = expression

    while isinstance(current, (exp.Cast, exp.Paren)):

        current = current.this

    return current



 

def _string_literal_value(expression: exp.Expression) -> str | None:

    unwrapped = _unwrap(expression)

    if isinstance(unwrapped, exp.Literal) and unwrapped.is_string:

        return str(unwrapped.this)

    return None



 

def _is_null_expression(expression: exp.Expression) -> bool:

    return isinstance(_unwrap(expression), exp.Null)



 

def _is_database_derived(

    expression: exp.Expression,

    select: exp.Select,

) -> bool:

    unwrapped = _unwrap(expression)

    if isinstance(unwrapped, (exp.Literal, exp.Null)):

        return False


 

    # Most useful verification expressions reference a source column directly or inside

    # an aggregate/window expression. This intentionally rejects MAX(123), SUM(123), and

    # similar ways of disguising a constant as an aggregate result.

    if unwrapped.find(exp.Column):

        return True


 

    # COUNT(*) is legitimately database-derived despite containing no Column node. Keep

    # this exception narrow: the projected expression itself must be COUNT, not arbitrary

    # arithmetic that merely contains COUNT somewhere.

    count_type = getattr(exp, "Count", None)

    if count_type is not None and isinstance(unwrapped, count_type):

        return bool(select.find(exp.Table))


 

    # A scalar subquery is acceptable only when its selected value is itself derived by

    # one of the rules above. A subquery such as SELECT 123 remains rejected.

    if isinstance(unwrapped, exp.Subquery):

        subquery_select = unwrapped.this

        if isinstance(subquery_select, exp.Select) and len(subquery_select.expressions) == 1:

            nested_expression = _projection_expression(subquery_select.expressions[0])

            return _is_database_derived(nested_expression, subquery_select)


 

    return False



 

def _canonical_sql(sql: str) -> str:

    return re.sub(r"\s+", " ", sql.strip().rstrip(";")).casefold()


 