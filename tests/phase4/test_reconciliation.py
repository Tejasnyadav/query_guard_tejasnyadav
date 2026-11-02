from app.verification.models import (

    ResultCellReference,

    VerificationCheck,

    VerificationPlan,

)

from app.verification.reconcile import reconcile_results



 

def _plan() -> VerificationPlan:

    return VerificationPlan(

        decision="verify",

        summary="Verify the key result cells.",

        independence_strategy="Recompute the values using a separate aggregation.",

        checks=[

            VerificationCheck(

                check_id="august_revenue",

                label="August net revenue",

                description="Recompute August net revenue.",

                metric_id="net_revenue",

                value_type="number",

                unit="INR",

                importance="primary",

                analyst_source=ResultCellReference(row_index=0, column="august_revenue"),

            ),

            VerificationCheck(

                check_id="top_segment",

                label="Segment with the largest decline",

                description="Recompute the segment ranking.",

                metric_id="net_revenue",

                value_type="text",

                unit="text",

                analyst_source=ResultCellReference(row_index=0, column="customer_segment"),

            ),

        ],

        issues=[],

    )



 

def test_numeric_and_text_checks_pass() -> None:

    result = reconcile_results(

        plan=_plan(),

        analyst_rows=[

            {"august_revenue": "7108000.13", "customer_segment": "SMB"}

        ],

        verifier_rows=[

            {

                "check_id": "august_revenue",

                "numeric_value": "7108000.130",

                "text_value": None,

            },

            {

                "check_id": "top_segment",

                "numeric_value": None,

                "text_value": "smb",

            },

        ],

        verifier_truncated=False,

    )


 

    assert result.status == "pass"

    assert all(comparison.passed for comparison in result.comparisons)



 

def test_numeric_mismatch_is_detected() -> None:

    result = reconcile_results(

        plan=_plan(),

        analyst_rows=[

            {"august_revenue": "7108000.13", "customer_segment": "SMB"}

        ],

        verifier_rows=[

            {

                "check_id": "august_revenue",

                "numeric_value": "7000000.00",

                "text_value": None,

            },

            {

                "check_id": "top_segment",

                "numeric_value": None,

                "text_value": "SMB",

            },

        ],

        verifier_truncated=False,

    )


 

    assert result.status == "mismatch"

    assert result.comparisons[0].passed is False



 

def test_missing_check_is_rejected() -> None:

    result = reconcile_results(

        plan=_plan(),

        analyst_rows=[

            {"august_revenue": "7108000.13", "customer_segment": "SMB"}

        ],

        verifier_rows=[

            {

                "check_id": "august_revenue",

                "numeric_value": "7108000.13",

                "text_value": None,

            }

        ],

        verifier_truncated=False,

    )


 

    assert result.status == "rejected"

    assert "top_segment" in result.issues[0]


 