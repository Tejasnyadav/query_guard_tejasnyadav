from datetime import date


 

import pytest


 

from app.agents.models import (

    ClarificationOption,

    DraftObservation,

    DraftSummary,

    EvidenceReference,

    SQLCandidate,

    TermResolution,

)

from app.analysis.guards import (

    apply_clarification_choice,

    enforce_term_resolution,

    validate_draft_summary,

    validate_sql_candidate,

)

from app.catalog.loader import load_semantic_catalog

from app.core.errors import AgentWorkflowError

from app.sql.policy import load_sql_policy



 

@pytest.fixture

def catalog():

    return load_semantic_catalog(

        metrics_path="config/metrics.yml",  # type: ignore[arg-type]

        dimensions_path="config/dimensions.yml",  # type: ignore[arg-type]

        business_terms_path="config/business_terms.yml",  # type: ignore[arg-type]

    )



 

def _resolution(metric_ids: list[str]) -> TermResolution:

    return TermResolution(

        interpretation="Revenue analysis",

        metric_ids=metric_ids,

        dimension_ids=[],

        needs_clarification=False,

        clarification_question=None,

        clarification_options=[],

        time_intent="last_complete_month_vs_previous",

        explicit_months=[],

        assumptions=[],

    )



 

def test_plain_revenue_is_forced_to_clarification(catalog) -> None:

    result = enforce_term_resolution(

        question="Why did revenue decrease last month?",

        resolution=_resolution(["net_revenue"]),

        catalog=catalog,

    )


 

    assert result.needs_clarification is True

    assert {option.choice_id for option in result.clarification_options} == {

        "gross_revenue",

        "net_revenue",

    }



 

def test_explicit_net_revenue_does_not_need_clarification(catalog) -> None:

    result = enforce_term_resolution(

        question="Why did net revenue decrease last month?",

        resolution=_resolution(["net_revenue"]),

        catalog=catalog,

    )


 

    assert result.needs_clarification is False

    assert result.metric_ids[0] == "net_revenue"



 

def test_clarification_choice_must_be_offered(catalog) -> None:

    resolution = _resolution([]).model_copy(

        update={

            "needs_clarification": True,

            "clarification_question": "Choose",

            "clarification_options": [

                ClarificationOption(

                    choice_id="net_revenue",

                    label="Net revenue",

                    description="After discounts and refunds",

                )

            ],

        }

    )


 

    with pytest.raises(AgentWorkflowError, match="offered options"):

        apply_clarification_choice(

            resolution=resolution,

            choice_id="gross_revenue",

            catalog=catalog,

        )



 

def test_summary_numbers_must_appear_in_cited_cells() -> None:

    summary = DraftSummary(

        headline="Revenue result",

        observations=[

            DraftObservation(

                text="August net revenue was 7108000.13.",

                evidence=[EvidenceReference(row_indices=[0], columns=["net_revenue"])],

            )

        ],

        limitations=[],

    )


 

    validated = validate_draft_summary(

        summary=summary,

        columns=["order_month", "net_revenue"],

        rows=[{"order_month": date(2026, 8, 1).isoformat(), "net_revenue": "7108000.13"}],

    )

    assert validated == summary



 

def test_summary_rejects_unsupported_number() -> None:

    summary = DraftSummary(

        headline="Revenue result",

        observations=[

            DraftObservation(

                text="Revenue decreased by 18.81%.",

                evidence=[EvidenceReference(row_indices=[0], columns=["net_revenue"])],

            )

        ],

        limitations=[],

    )


 

    with pytest.raises(AgentWorkflowError, match="not present"):

        validate_draft_summary(

            summary=summary,

            columns=["net_revenue"],

            rows=[{"net_revenue": "7108000.13"}],

        )



 

def test_summary_rejects_numeric_headline() -> None:

    summary = DraftSummary(

        headline="Revenue decreased by 18.81%.",

        observations=[],

        limitations=[],

    )


 

    with pytest.raises(AgentWorkflowError, match="headlines cannot contain numbers"):

        validate_draft_summary(

            summary=summary,

            columns=["revenue_change_percent"],

            rows=[{"revenue_change_percent": "-18.81"}],

        )



 

def test_sql_candidate_must_match_validated_plan_contract() -> None:

    from types import SimpleNamespace


 

    policy = load_sql_policy("config/sql_policy.yml")

    candidate = SQLCandidate(

        purpose="test",

        sql="SELECT order_month FROM analytics.order_line_facts",

        expected_columns=["wrong_column"],

        expected_max_rows=10,

        tables_expected=["analytics.order_line_facts"],

    )

    plan = SimpleNamespace(

        required_views=["analytics.order_line_facts"],

        expected_columns=["order_month"],

    )


 

    with pytest.raises(AgentWorkflowError, match="expected columns"):

        validate_sql_candidate(candidate, policy, plan=plan)  # type: ignore[arg-type]


 