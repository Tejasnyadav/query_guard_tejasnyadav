import pytest

from app.catalog.loader import load_semantic_catalog
from app.core.errors import AgentWorkflowError
from app.sql.policy import load_sql_policy
from app.verification.guards import (
    validate_verification_plan,
    validate_verification_sql_candidate,
)
from app.verification.models import (
    ResultCellReference,
    VerificationCheck,
    VerificationPlan,
    VerificationSQLCandidate,
)


def _plan() -> VerificationPlan:

    return VerificationPlan(

        decision="verify",

        summary="Check the main value.",

        independence_strategy="Use a separate aggregation.",

        issues=[],

        checks=[

            VerificationCheck(

                check_id="august_revenue",

                label="August net revenue",

                description="Recompute August revenue.",

                metric_id="net_revenue",

                value_type="number",

                unit="INR",

                importance="primary",

                analyst_source=ResultCellReference(row_index=0, column="net_revenue"),

            )

        ],

    )



 

def test_plan_source_must_exist() -> None:

    catalog = load_semantic_catalog(

        metrics_path="config/metrics.yml",

        dimensions_path="config/dimensions.yml",

        business_terms_path="config/business_terms.yml",

    )

    with pytest.raises(AgentWorkflowError, match="missing Analyst column"):

        validate_verification_plan(

            plan=_plan(),

            analyst_columns=["wrong"],

            analyst_rows=[{"wrong": "1"}],

            catalog=catalog,

            max_checks=5,

        )



 

def test_plan_rejects_a_number_inside_claim_label() -> None:

    catalog = load_semantic_catalog(

        metrics_path="config/metrics.yml",

        dimensions_path="config/dimensions.yml",

        business_terms_path="config/business_terms.yml",

    )

    plan = _plan().model_copy(deep=True)

    plan.checks[0].label = "August revenue fell 18.81%"


 

    with pytest.raises(AgentWorkflowError, match="number or currency symbol"):

        validate_verification_plan(

            plan=plan,

            analyst_columns=["net_revenue"],

            analyst_rows=[{"net_revenue": "7108000.13"}],

            catalog=catalog,

            max_checks=5,

        )



 

def test_plan_allows_a_year_inside_claim_label() -> None:

    catalog = load_semantic_catalog(

        metrics_path="config/metrics.yml",

        dimensions_path="config/dimensions.yml",

        business_terms_path="config/business_terms.yml",

    )

    plan = _plan().model_copy(deep=True)

    plan.checks[0].label = "August 2026 net revenue"


 

    validated = validate_verification_plan(

        plan=plan,

        analyst_columns=["net_revenue"],

        analyst_rows=[{"net_revenue": "7108000.13"}],

        catalog=catalog,

        max_checks=5,

    )

    assert validated.checks[0].label == "August 2026 net revenue"



 

def test_plan_caps_model_requested_numeric_tolerances() -> None:

    catalog = load_semantic_catalog(

        metrics_path="config/metrics.yml",

        dimensions_path="config/dimensions.yml",

        business_terms_path="config/business_terms.yml",

    )

    plan = _plan().model_copy(deep=True)

    plan.checks[0].absolute_tolerance = 999999

    plan.checks[0].relative_tolerance = 0.1


 

    validated = validate_verification_plan(

        plan=plan,

        analyst_columns=["net_revenue"],

        analyst_rows=[{"net_revenue": "7108000.13"}],

        catalog=catalog,

        max_checks=5,

    )


 

    assert validated.checks[0].absolute_tolerance == 0.01

    assert validated.checks[0].relative_tolerance == 0.000000001


def test_plan_accepts_ratio_unit_and_caps_its_tolerance() -> None:
    catalog = load_semantic_catalog(
        metrics_path="config/metrics.yml",
        dimensions_path="config/dimensions.yml",
        business_terms_path="config/business_terms.yml",
    )
    plan = _plan().model_copy(deep=True)
    plan.checks[0].unit = "ratio"
    plan.checks[0].absolute_tolerance = 0.01

    validated = validate_verification_plan(
        plan=plan,
        analyst_columns=["net_revenue"],
        analyst_rows=[{"net_revenue": "7108000.13"}],
        catalog=catalog,
        max_checks=5,
    )

    assert validated.checks[0].unit == "ratio"
    assert validated.checks[0].absolute_tolerance == 0.000000001



def test_plan_rejects_causal_claim_label() -> None:

    catalog = load_semantic_catalog(

        metrics_path="config/metrics.yml",

        dimensions_path="config/dimensions.yml",

        business_terms_path="config/business_terms.yml",

    )

    plan = _plan().model_copy(deep=True)

    plan.checks[0].label = "Discounts caused the revenue decline"


 

    with pytest.raises(AgentWorkflowError, match="causal wording"):

        validate_verification_plan(

            plan=plan,

            analyst_columns=["net_revenue"],

            analyst_rows=[{"net_revenue": "7108000.13"}],

            catalog=catalog,

            max_checks=5,

        )



 

def test_verification_query_must_not_copy_analyst_sql() -> None:

    policy = load_sql_policy("config/sql_policy.yml")

    sql = (

        "SELECT 'august_revenue' AS check_id, SUM(net_revenue) AS numeric_value, "

        "NULL::text AS text_value FROM analytics.order_line_facts"

    )

    candidate = VerificationSQLCandidate(

        purpose="Verify revenue",

        sql=sql,

        expected_columns=["check_id", "numeric_value", "text_value"],

        expected_max_rows=1,

        tables_expected=["analytics.order_line_facts"],

        covered_check_ids=["august_revenue"],

    )


 

    with pytest.raises(AgentWorkflowError, match="cannot be identical"):

        validate_verification_sql_candidate(

            candidate=candidate,

            plan=_plan(),

            analyst_sql=sql,

            policy=policy,

        )



 

def test_verification_query_must_cover_every_check() -> None:

    policy = load_sql_policy("config/sql_policy.yml")

    candidate = VerificationSQLCandidate(

        purpose="Verify revenue",

        sql=(

            "SELECT 'other_check' AS check_id, SUM(net_revenue) AS numeric_value, "

            "NULL::text AS text_value FROM analytics.order_line_facts"

        ),

        expected_columns=["check_id", "numeric_value", "text_value"],

        expected_max_rows=1,

        tables_expected=["analytics.order_line_facts"],

        covered_check_ids=["other_check"],

    )


 

    with pytest.raises(AgentWorkflowError, match="must cover checks"):

        validate_verification_sql_candidate(

            candidate=candidate,

            plan=_plan(),

            analyst_sql="SELECT net_revenue FROM analytics.order_line_facts",

            policy=policy,

        )



 

def test_verification_query_rejects_hardcoded_numeric_value() -> None:

    policy = load_sql_policy("config/sql_policy.yml")

    candidate = VerificationSQLCandidate(

        purpose="Fake verification",

        sql=(

            "SELECT 'august_revenue'::text AS check_id, "

            "7108000.13::numeric AS numeric_value, NULL::text AS text_value "

            "FROM analytics.dataset_metadata"

        ),

        expected_columns=["check_id", "numeric_value", "text_value"],

        expected_max_rows=1,

        tables_expected=["analytics.dataset_metadata"],

        covered_check_ids=["august_revenue"],

    )


 

    with pytest.raises(AgentWorkflowError, match="hard-coded numeric value"):

        validate_verification_sql_candidate(

            candidate=candidate,

            plan=_plan(),

            analyst_sql="SELECT net_revenue FROM analytics.order_line_facts",

            policy=policy,

        )



 

def test_verification_query_rejects_constant_hidden_inside_aggregate() -> None:

    policy = load_sql_policy("config/sql_policy.yml")

    candidate = VerificationSQLCandidate(

        purpose="Fake verification",

        sql=(

            "SELECT 'august_revenue'::text AS check_id, "

            "MAX(7108000.13)::numeric AS numeric_value, NULL::text AS text_value "

            "FROM analytics.dataset_metadata"

        ),

        expected_columns=["check_id", "numeric_value", "text_value"],

        expected_max_rows=1,

        tables_expected=["analytics.dataset_metadata"],

        covered_check_ids=["august_revenue"],

    )


 

    with pytest.raises(AgentWorkflowError, match="hard-coded numeric value"):

        validate_verification_sql_candidate(

            candidate=candidate,

            plan=_plan(),

            analyst_sql="SELECT net_revenue FROM analytics.order_line_facts",

            policy=policy,

        )



def test_verification_query_rejects_check_id_selected_from_results_cte() -> None:
    policy = load_sql_policy("config/sql_policy.yml")
    candidate = VerificationSQLCandidate(
        purpose="Verify revenue",
        sql=(
            "WITH totals AS ("
            "SELECT SUM(net_revenue) AS revenue "
            "FROM analytics.order_line_facts"
            "), checks AS ("
            "SELECT 'august_revenue'::text AS check_id, "
            "revenue AS numeric_value, NULL::text AS text_value "
            "FROM totals"
            ") "
            "SELECT check_id, numeric_value, text_value FROM checks"
        ),
        expected_columns=["check_id", "numeric_value", "text_value"],
        expected_max_rows=1,
        tables_expected=["analytics.order_line_facts"],
        covered_check_ids=["august_revenue"],
    )

    with pytest.raises(
        AgentWorkflowError,
        match="project its own literal check_id",
    ):
        validate_verification_sql_candidate(
            candidate=candidate,
            plan=_plan(),
            analyst_sql="SELECT SUM(net_revenue) FROM analytics.order_line_facts",
            policy=policy,
        )



def test_verification_query_accepts_database_derived_value() -> None:

    policy = load_sql_policy("config/sql_policy.yml")

    candidate = VerificationSQLCandidate(

        purpose="Verify revenue",

        sql=(

            "SELECT 'august_revenue'::text AS check_id, "

            "SUM(net_revenue) AS numeric_value, NULL::text AS text_value "

            "FROM analytics.order_line_facts "

            "WHERE order_month = DATE '2026-08-01'"

        ),

        expected_columns=["check_id", "numeric_value", "text_value"],

        expected_max_rows=1,

        tables_expected=["analytics.order_line_facts"],

        covered_check_ids=["august_revenue"],

    )


 

    validated = validate_verification_sql_candidate(

        candidate=candidate,

        plan=_plan(),

        analyst_sql=(

            "SELECT order_month, SUM(net_revenue) "

            "FROM analytics.order_line_facts GROUP BY order_month"

        ),

        policy=policy,

    )

    assert validated.covered_check_ids == ["august_revenue"]



 

def test_verification_query_accepts_count_star() -> None:

    policy = load_sql_policy("config/sql_policy.yml")

    plan = _plan().model_copy(

        update={

            "checks": [

                _plan().checks[0].model_copy(

                    update={

                        "check_id": "completed_order_count",

                        "label": "Completed order count",

                        "metric_id": "order_count",

                        "unit": "orders",

                    }

                )

            ]

        }

    )

    candidate = VerificationSQLCandidate(

        purpose="Verify completed order count",

        sql=(

            "SELECT 'completed_order_count'::text AS check_id, "

            "COUNT(*)::numeric AS numeric_value, NULL::text AS text_value "

            "FROM analytics.order_summary WHERE order_status = 'completed'"

        ),

        expected_columns=["check_id", "numeric_value", "text_value"],

        expected_max_rows=1,

        tables_expected=["analytics.order_summary"],

        covered_check_ids=["completed_order_count"],

    )


 

    validated = validate_verification_sql_candidate(

        candidate=candidate,

        plan=plan,

        analyst_sql=(

            "SELECT COUNT(DISTINCT order_id) AS completed_order_count "

            "FROM analytics.order_line_facts WHERE order_status = 'completed'"

        ),

        policy=policy,

    )

    assert validated.covered_check_ids == ["completed_order_count"]


 