from datetime import date


 

from app.agents.models import TermResolution

from app.analysis.time_periods import resolve_time_context



 

def _resolution(intent: str) -> TermResolution:

    return TermResolution(

        interpretation="test",

        metric_ids=["net_revenue"],

        dimension_ids=[],

        needs_clarification=False,

        clarification_question=None,

        clarification_options=[],

        time_intent=intent,

        explicit_months=[],

        assumptions=[],

    )



 

def test_last_month_decline_gets_comparison_month() -> None:

    context = resolve_time_context(

        question="Why did net revenue decrease last month?",

        resolution=_resolution("last_complete_month_vs_previous"),

        as_of_date=date(2026, 9, 15),

    )


 

    assert [window.start for window in context.windows] == [

        date(2026, 8, 1),

        date(2026, 7, 1),

    ]

    assert all(window.is_complete for window in context.windows)



 

def test_explicit_months_preserve_question_order() -> None:

    context = resolve_time_context(

        question="Compare August 2026 with July 2026",

        resolution=_resolution("explicit_months"),

        as_of_date=date(2026, 9, 15),

    )


 

    assert context.windows[0].role == "primary"

    assert context.windows[0].start == date(2026, 8, 1)

    assert context.windows[1].role == "comparison"

    assert context.windows[1].start == date(2026, 7, 1)


 