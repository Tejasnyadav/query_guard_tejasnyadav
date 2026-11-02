from decimal import Decimal, InvalidOperation

from typing import Any


 

from app.verification.models import (

    ReconciliationComparison,

    ReconciliationResult,

    VerificationPlan,

)



 

def reconcile_results(

    *,

    plan: VerificationPlan,

    analyst_rows: list[dict[str, Any]],

    verifier_rows: list[dict[str, Any]],

    verifier_truncated: bool,

) -> ReconciliationResult:

    issues: list[str] = []

    comparisons: list[ReconciliationComparison] = []


 

    if verifier_truncated:

        return ReconciliationResult(

            status="rejected",

            issues=["The verification query result was truncated."],

        )


 

    indexed: dict[str, tuple[int, dict[str, Any]]] = {}

    for row_index, row in enumerate(verifier_rows):

        check_id = str(row.get("check_id") or "").strip()

        if not check_id:

            issues.append(f"Verification row {row_index} has no check_id.")

            continue

        if check_id in indexed:

            issues.append(f"Verification result returned duplicate check_id '{check_id}'.")

            continue

        indexed[check_id] = (row_index, row)


 

    for check in plan.checks:

        source = check.analyst_source

        if source.row_index >= len(analyst_rows):

            issues.append(f"Analyst source row for '{check.check_id}' no longer exists.")

            continue

        analyst_value = analyst_rows[source.row_index].get(source.column)

        verifier_item = indexed.get(check.check_id)

        if verifier_item is None:

            issues.append(f"Verification result omitted check_id '{check.check_id}'.")

            continue


 

        verifier_row_index, verifier_row = verifier_item

        if check.value_type == "number":

            verifier_column = "numeric_value"

            verifier_value = verifier_row.get(verifier_column)

            comparison = _compare_numbers(

                check_id=check.check_id,

                label=check.label,

                analyst_source=source,

                analyst_value=analyst_value,

                verifier_value=verifier_value,

                verifier_row_index=verifier_row_index,

                absolute_tolerance=check.absolute_tolerance,

                relative_tolerance=check.relative_tolerance,

            )

        else:

            verifier_column = "text_value"

            verifier_value = verifier_row.get(verifier_column)

            comparison = _compare_text(

                check_id=check.check_id,

                label=check.label,

                analyst_source=source,

                analyst_value=analyst_value,

                verifier_value=verifier_value,

                verifier_row_index=verifier_row_index,

                case_sensitive=check.text_case_sensitive,

            )

        comparisons.append(comparison)


 

    expected_ids = {check.check_id for check in plan.checks}

    unexpected_ids = sorted(set(indexed) - expected_ids)

    if unexpected_ids:

        issues.append(f"Verification result returned unexpected checks: {unexpected_ids}.")


 

    if issues:

        status = "rejected"

    elif (

        all(comparison.passed for comparison in comparisons)

        and len(comparisons) == len(plan.checks)

    ):

        status = "pass"

    else:

        status = "mismatch"


 

    return ReconciliationResult(status=status, comparisons=comparisons, issues=issues)



 

def _compare_numbers(

    *,

    check_id: str,

    label: str,

    analyst_source,

    analyst_value: Any,

    verifier_value: Any,

    verifier_row_index: int,

    absolute_tolerance: float,

    relative_tolerance: float,

) -> ReconciliationComparison:

    try:

        analyst_number = _to_decimal(analyst_value)

        verifier_number = _to_decimal(verifier_value)

    except (InvalidOperation, ValueError, TypeError):

        return ReconciliationComparison(

            check_id=check_id,

            label=label,

            value_type="number",

            analyst_source=analyst_source,

            verifier_row_index=verifier_row_index,

            verifier_column="numeric_value",

            analyst_value=analyst_value,

            verifier_value=verifier_value,

            passed=False,

            message="One of the values could not be interpreted as a number.",

        )


 

    difference = abs(analyst_number - verifier_number)

    absolute = Decimal(str(absolute_tolerance))

    relative = Decimal(str(relative_tolerance)) * max(

        abs(analyst_number), abs(verifier_number), Decimal("1")

    )

    tolerance = max(absolute, relative)

    passed = difference <= tolerance


 

    return ReconciliationComparison(

        check_id=check_id,

        label=label,

        value_type="number",

        analyst_source=analyst_source,

        verifier_row_index=verifier_row_index,

        verifier_column="numeric_value",

        analyst_value=analyst_value,

        verifier_value=verifier_value,

        passed=passed,

        difference=str(difference),

        tolerance_used=str(tolerance),

        message=(

            "Analyst and Verifier values match within tolerance."

            if passed

            else "Analyst and Verifier values do not match within tolerance."

        ),

    )



 

def _compare_text(

    *,

    check_id: str,

    label: str,

    analyst_source,

    analyst_value: Any,

    verifier_value: Any,

    verifier_row_index: int,

    case_sensitive: bool,

) -> ReconciliationComparison:

    analyst_text = "" if analyst_value is None else str(analyst_value).strip()

    verifier_text = "" if verifier_value is None else str(verifier_value).strip()

    left = analyst_text if case_sensitive else analyst_text.casefold()

    right = verifier_text if case_sensitive else verifier_text.casefold()

    passed = left == right


 

    return ReconciliationComparison(

        check_id=check_id,

        label=label,

        value_type="text",

        analyst_source=analyst_source,

        verifier_row_index=verifier_row_index,

        verifier_column="text_value",

        analyst_value=analyst_value,

        verifier_value=verifier_value,

        passed=passed,

        message=(

            "Analyst and Verifier text values match."

            if passed

            else "Analyst and Verifier text values do not match."

        ),

    )



 

def _to_decimal(value: Any) -> Decimal:

    if value is None or isinstance(value, bool):

        raise ValueError("Not a numeric value")

    if isinstance(value, Decimal):

        return value

    if isinstance(value, (int, float)):

        return Decimal(str(value))

    text = str(value).strip().replace(",", "")

    if text.endswith("%"):

        text = text[:-1].strip()

    for symbol in ("₹", "$", "€", "£"):

        text = text.replace(symbol, "")

    return Decimal(text)


 