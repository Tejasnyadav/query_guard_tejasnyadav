import re

from decimal import Decimal, InvalidOperation

from typing import Any


 

from app.agents.models import (

    AnalysisPlan,

    AnalysisPlanOutline,

    ClarificationOption,

    DraftSummary,

    ResolvedTimeContext,

    SQLCandidate,

    TermResolution,

)

from app.catalog.models import SchemaSnapshot, SemanticCatalog

from app.core.errors import AgentWorkflowError

from app.sql.policy import SqlPolicy



 

def enforce_term_resolution(

    *,

    question: str,

    resolution: TermResolution,

    catalog: SemanticCatalog,

) -> TermResolution:

    invalid_metrics = sorted(set(resolution.metric_ids) - set(catalog.metrics))

    invalid_dimensions = sorted(set(resolution.dimension_ids) - set(catalog.dimensions))

    if invalid_metrics or invalid_dimensions:

        raise AgentWorkflowError(

            code="INVALID_CATALOG_SELECTION",

            message=(

                f"The model selected unknown metrics {invalid_metrics} or dimensions "

                f"{invalid_dimensions}."

            ),

        )


 

    normalized = question.casefold()

    metric_ids = list(dict.fromkeys(resolution.metric_ids))

    dimension_ids = list(dict.fromkeys(resolution.dimension_ids))


 

    if "segment" in normalized and "customer_segment" not in dimension_ids:

        dimension_ids.append("customer_segment")

    if "category" in normalized and "product_category" not in dimension_ids:

        dimension_ids.append("product_category")

    if "region" in normalized and "customer_region" not in dimension_ids:

        dimension_ids.append("customer_region")

    if "channel" in normalized and "marketing_channel" not in dimension_ids:

        dimension_ids.append("marketing_channel")


 

    explicit_gross = "gross revenue" in normalized or "before discounts" in normalized

    explicit_net = (

        "net revenue" in normalized

        or "after discounts" in normalized

        or "after refunds" in normalized

    )

    revenue_mentioned = "revenue" in normalized


 

    if explicit_gross:

        metric_ids = [metric for metric in metric_ids if metric not in {"net_revenue"}]

        if "gross_revenue" not in metric_ids:

            metric_ids.insert(0, "gross_revenue")

    elif explicit_net:

        metric_ids = [metric for metric in metric_ids if metric not in {"gross_revenue"}]

        if "net_revenue" not in metric_ids:

            metric_ids.insert(0, "net_revenue")

    elif revenue_mentioned:

        revenue_term = catalog.terms.get("revenue")

        choices = revenue_term.choices if revenue_term else ["gross_revenue", "net_revenue"]

        options = [

            ClarificationOption(

                choice_id=choice,

                label=catalog.metrics[choice].label,

                description=catalog.metrics[choice].description,

            )

            for choice in choices

            if choice in catalog.metrics

        ]

        return resolution.model_copy(

            update={

                "metric_ids": [m for m in metric_ids if m not in choices],

                "dimension_ids": dimension_ids,

                "needs_clarification": True,

                "clarification_question": (

                    "What should ‘revenue’ mean for this analysis?"

                ),

                "clarification_options": options,

            }

        )


 

    if resolution.needs_clarification:

        option_ids = {option.choice_id for option in resolution.clarification_options}

        # Phase 3 supports deterministic selectable metric clarifications only.

        # Date phrases are resolved against dataset metadata by code.

        if metric_ids and (not option_ids or not option_ids.issubset(catalog.metrics)):

            resolution = resolution.model_copy(

                update={

                    "needs_clarification": False,

                    "clarification_question": None,

                    "clarification_options": [],

                }

            )


 

    if not metric_ids and not resolution.needs_clarification:

        options = [

            ClarificationOption(

                choice_id=metric_id,

                label=metric.label,

                description=metric.description,

            )

            for metric_id, metric in catalog.metrics.items()

        ]

        return resolution.model_copy(

            update={

                "needs_clarification": True,

                "clarification_question": "Which business metric should QueryGuard analyze?",

                "clarification_options": options,

                "dimension_ids": dimension_ids,

            }

        )


 

    return resolution.model_copy(

        update={"metric_ids": metric_ids, "dimension_ids": dimension_ids}

    )



 

def apply_clarification_choice(

    *,

    resolution: TermResolution,

    choice_id: str,

    catalog: SemanticCatalog,

) -> TermResolution:

    allowed = {option.choice_id for option in resolution.clarification_options}

    if choice_id not in allowed:

        raise AgentWorkflowError(

            code="INVALID_CLARIFICATION_CHOICE",

            message="The clarification choice was not one of the offered options.",

        )

    if choice_id not in catalog.metrics:

        raise AgentWorkflowError(

            code="UNSUPPORTED_CLARIFICATION_CHOICE",

            message="This Phase 3 starter only accepts metric clarification choices.",

        )


 

    metric_ids = [metric for metric in resolution.metric_ids if metric != choice_id]

    metric_ids.insert(0, choice_id)

    return resolution.model_copy(

        update={

            "metric_ids": list(dict.fromkeys(metric_ids)),

            "needs_clarification": False,

            "clarification_question": None,

            "clarification_options": [],

        }

    )



 

def build_validated_plan(

    *,

    outline: AnalysisPlanOutline,

    resolution: TermResolution,

    time_context: ResolvedTimeContext,

    catalog: SemanticCatalog,

    snapshot: SchemaSnapshot,

    policy: SqlPolicy,

) -> AnalysisPlan:

    allowed_views = policy.allowed_tables

    invalid_views = sorted(set(outline.required_views) - allowed_views)

    if invalid_views:

        raise AgentWorkflowError(

            code="PLAN_REFERENCES_DISALLOWED_VIEW",

            message=f"The analysis plan referenced disallowed views: {invalid_views}",

        )


 

    schema_columns = {

        column.name

        for table in snapshot.tables

        for column in table.columns

    }

    invalid_grouping = sorted(set(outline.group_by_columns) - schema_columns)

    if invalid_grouping:

        raise AgentWorkflowError(

            code="PLAN_REFERENCES_UNKNOWN_COLUMN",

            message=f"The plan referenced unknown grouping columns: {invalid_grouping}",

        )


 

    required_views = list(dict.fromkeys(outline.required_views))

    filters = list(dict.fromkeys(outline.required_filters))

    assumptions = list(dict.fromkeys([*resolution.assumptions, *outline.assumptions]))


 

    for metric_id in resolution.metric_ids:

        metric = catalog.metrics[metric_id]

        if metric.source_view not in required_views:

            required_views.append(metric.source_view)

        if metric.required_filter and metric.required_filter not in filters:

            filters.append(metric.required_filter)


 

    for dimension_id in resolution.dimension_ids:

        dimension = catalog.dimensions[dimension_id]

        if dimension.source_view not in required_views:

            required_views.append(dimension.source_view)


 

    invalid_after_merge = sorted(set(required_views) - allowed_views)

    if invalid_after_merge:

        raise AgentWorkflowError(

            code="CATALOG_REFERENCES_DISALLOWED_VIEW",

            message=f"The semantic catalog referenced disallowed views: {invalid_after_merge}",

        )


 

    expected_columns = list(dict.fromkeys(outline.expected_columns))

    if not expected_columns:

        raise AgentWorkflowError(

            code="PLAN_HAS_NO_EXPECTED_COLUMNS",

            message="The analysis plan did not define any expected result columns.",

        )


 

    return AnalysisPlan(

        objective=outline.objective,

        metric_ids=resolution.metric_ids,

        dimension_ids=resolution.dimension_ids,

        time_context=time_context,

        required_views=required_views,

        group_by_columns=list(dict.fromkeys(outline.group_by_columns)),

        required_filters=filters,

        output_grain=outline.output_grain,

        expected_columns=expected_columns,

        steps=sorted(outline.steps, key=lambda step: step.order),

        assumptions=assumptions,

    )



 

def validate_sql_candidate(

    candidate: SQLCandidate,

    policy: SqlPolicy,

    plan: AnalysisPlan | None = None,

) -> SQLCandidate:

    invalid_tables = sorted(set(candidate.tables_expected) - policy.allowed_tables)

    if invalid_tables:

        raise AgentWorkflowError(

            code="SQL_CANDIDATE_EXPECTS_DISALLOWED_TABLE",

            message=f"The model expected disallowed tables: {invalid_tables}",

        )

    if len(candidate.expected_columns) != len(set(candidate.expected_columns)):

        raise AgentWorkflowError(

            code="SQL_CANDIDATE_DUPLICATE_COLUMNS",

            message="The SQL candidate contains duplicate expected column names.",

        )


 

    if plan is not None:

        unexpected_tables = sorted(set(candidate.tables_expected) - set(plan.required_views))

        if unexpected_tables:

            raise AgentWorkflowError(

                code="SQL_CANDIDATE_DEVIATES_FROM_PLAN",

                message=(

                    "The SQL candidate expected tables that were not approved by the plan: "

                    f"{unexpected_tables}"

                ),

            )

        if candidate.expected_columns != plan.expected_columns:

            raise AgentWorkflowError(

                code="SQL_CANDIDATE_COLUMNS_DO_NOT_MATCH_PLAN",

                message=(

                    "The SQL candidate's expected columns must exactly match the validated "

                    "analysis plan."

                ),

            )

    return candidate



 

_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?%?")



 

def _normalize_number(value: str) -> str | None:

    cleaned = value.strip().replace(",", "").replace("%", "")

    try:

        number = Decimal(cleaned)

    except InvalidOperation:

        return None

    normalized = format(number.normalize(), "f")

    return "0" if normalized in {"-0", "+0"} else normalized



 

def _numbers_in_value(value: Any) -> set[str]:

    return {

        normalized

        for token in _NUMBER_PATTERN.findall(str(value))

        if (normalized := _normalize_number(token)) is not None

    }



 

def validate_draft_summary(

    *,

    summary: DraftSummary,

    columns: list[str],

    rows: list[dict[str, Any]],

) -> DraftSummary:

    allowed_columns = set(columns)


 

    if _NUMBER_PATTERN.search(summary.headline):

        raise AgentWorkflowError(

            code="SUMMARY_NUMERIC_HEADLINE_NOT_ALLOWED",

            message=(

                "Phase 3 headlines cannot contain numbers because headline fields do not "

                "carry cell-level evidence references."

            ),

        )


 

    for observation in summary.observations:

        evidence_numbers: set[str] = set()

        if not observation.evidence:

            raise AgentWorkflowError(

                code="SUMMARY_MISSING_EVIDENCE",

                message="Every draft observation must cite result rows and columns.",

            )


 

        for reference in observation.evidence:

            invalid_columns = set(reference.columns) - allowed_columns

            if invalid_columns:

                raise AgentWorkflowError(

                    code="SUMMARY_UNKNOWN_EVIDENCE_COLUMN",

                    message=f"Summary cited unknown columns: {sorted(invalid_columns)}",

                )

            for row_index in reference.row_indices:

                if row_index < 0 or row_index >= len(rows):

                    raise AgentWorkflowError(

                        code="SUMMARY_UNKNOWN_EVIDENCE_ROW",

                        message=f"Summary cited nonexistent row index {row_index}.",

                    )

                for column in reference.columns:

                    evidence_numbers.update(_numbers_in_value(rows[row_index].get(column)))


 

        stated_numbers = {

            normalized

            for token in _NUMBER_PATTERN.findall(observation.text)

            if (normalized := _normalize_number(token)) is not None

        }

        unsupported = stated_numbers - evidence_numbers

        if unsupported:

            raise AgentWorkflowError(

                code="SUMMARY_UNSUPPORTED_NUMBER",

                message=(

                    "The draft summary used numbers not present in its cited cells: "

                    + ", ".join(sorted(unsupported))

                ),

            )


 

    return summary


 