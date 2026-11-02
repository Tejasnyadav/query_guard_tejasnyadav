from datetime import date, datetime, timezone

from uuid import UUID, uuid4


 

from langgraph.checkpoint.memory import InMemorySaver

from langgraph.types import Command


 

from app.agents.models import (

    AnalysisPlanOutline,

    AnalysisStep,

    SQLCandidate,

    TermResolution,

)

from app.catalog.loader import load_semantic_catalog

from app.catalog.models import (

    ColumnDefinition,

    DatasetMetadata,

    SchemaSnapshot,

    TableDefinition,

)

from app.graph.builder import build_analysis_graph

from app.graph.nodes.analysis_nodes import AnalysisNodeDependencies

from app.schemas.query import QueryExecutionOutcome

from app.sql.models import PlanSummary, QueryResult, SqlValidationResult, ValidationIssue

from app.sql.policy import load_sql_policy

from app.verification.models import (

    ResultCellReference,

    VerificationCheck,

    VerificationPlan,

    VerificationSQLCandidate,

    VerifiedAnswer,

    VerifiedClaim,

)



 

class FakeAudit:

    def __getattr__(self, name):

        def no_op(*args, **kwargs):

            return None


 

        return no_op



 

class FakeSchemaService:

    def __init__(self) -> None:

        self.snapshot = SchemaSnapshot(

            dataset=DatasetMetadata(

                dataset_name="queryguard_synthetic_ecommerce",

                dataset_version="1.0.0",

                as_of_date=date(2026, 9, 15),

                business_timezone="Asia/Kolkata",

                reporting_currency="INR",

                generated_at=datetime(2026, 9, 15, tzinfo=timezone.utc),

            ),

            tables=[

                TableDefinition(

                    qualified_name="analytics.order_line_facts",

                    columns=[

                        ColumnDefinition(name="order_month", data_type="date", ordinal_position=1),

                        ColumnDefinition(name="order_status", data_type="text", ordinal_position=2),

                        ColumnDefinition(

                            name="customer_segment", data_type="text", ordinal_position=3

                        ),

                        ColumnDefinition(

                            name="net_revenue", data_type="numeric", ordinal_position=4

                        ),

                    ],

                )

            ],

        )


 

    def load_snapshot(self):

        return self.snapshot


 

    @staticmethod

    def compact_for_prompt(snapshot):

        return {

            "dataset": snapshot.dataset.model_dump(mode="json"),

            "tables": {

                table.qualified_name: [column.name for column in table.columns]

                for table in snapshot.tables

            },

        }



 

class FakeAnalyst:

    def resolve_terms(self, *, run_id, payload):

        return TermResolution(

            interpretation="Compare monthly revenue by segment",

            metric_ids=["net_revenue"],

            dimension_ids=["customer_segment"],

            needs_clarification=False,

            clarification_question=None,

            clarification_options=[],

            time_intent="last_complete_month_vs_previous",

            explicit_months=[],

            assumptions=[],

        )


 

    def create_plan(self, *, run_id, payload):

        return AnalysisPlanOutline(

            objective="Compare monthly net revenue by segment",

            required_views=["analytics.order_line_facts"],

            group_by_columns=["customer_segment", "order_month"],

            required_filters=["order_status = 'completed'"],

            output_grain="one row per customer segment",

            expected_columns=[

                "customer_segment",

                "july_revenue",

                "august_revenue",

                "revenue_change",

            ],

            steps=[

                AnalysisStep(order=1, description="Aggregate periods", rationale="Compare months")

            ],

            assumptions=[],

        )


 

    def generate_sql(self, *, run_id, payload):

        return SQLCandidate(

            purpose="Compare monthly net revenue by segment",

            sql=(

                "SELECT customer_segment, "

                "SUM(net_revenue) FILTER (WHERE order_month = DATE '2026-07-01') "

                "AS july_revenue, "

                "SUM(net_revenue) FILTER (WHERE order_month = DATE '2026-08-01') "

                "AS august_revenue, "

                "SUM(net_revenue) FILTER (WHERE order_month = DATE '2026-08-01') - "

                "SUM(net_revenue) FILTER (WHERE order_month = DATE '2026-07-01') "

                "AS revenue_change "

                "FROM analytics.order_line_facts "

                "WHERE order_status = 'completed' "

                "GROUP BY customer_segment"

            ),

            expected_columns=[

                "customer_segment",

                "july_revenue",

                "august_revenue",

                "revenue_change",

            ],

            expected_max_rows=10,

            tables_expected=["analytics.order_line_facts"],

        )


 

    def repair_sql(self, *, run_id, payload):

        return self.generate_sql(run_id=run_id, payload=payload)


 

    def repair_from_verifier(self, *, run_id, payload):

        return self.generate_sql(run_id=run_id, payload=payload)



 

class FakeVerifier:

    def inspect_methodology(self, *, run_id, payload):

        return VerificationPlan(

            decision="verify",

            summary="The method is suitable for an independent recomputation.",

            independence_strategy="Recompute the key value in a standardized check row.",

            issues=[],

            checks=[

                VerificationCheck(

                    check_id="smb_revenue_change",

                    label="SMB revenue change",

                    description="Recompute the SMB period change.",

                    metric_id="net_revenue",

                    value_type="number",

                    unit="INR",

                    importance="primary",

                    analyst_source=ResultCellReference(

                        row_index=0,

                        column="revenue_change",

                    ),

                )

            ],

        )


 

    def generate_sql(self, *, run_id, payload):

        return VerificationSQLCandidate(

            purpose="Independently verify the SMB revenue change",

            sql=(

                "WITH monthly AS ("

                "SELECT order_month, SUM(net_revenue) AS amount "

                "FROM analytics.order_line_facts "

                "WHERE order_status = 'completed' AND customer_segment = 'SMB' "

                "AND order_month IN (DATE '2026-07-01', DATE '2026-08-01') "

                "GROUP BY order_month) "

                "SELECT 'smb_revenue_change'::text AS check_id, "

                "(SUM(amount) FILTER (WHERE order_month = DATE '2026-08-01') - "

                "SUM(amount) FILTER (WHERE order_month = DATE '2026-07-01')) "

                "AS numeric_value, NULL::text AS text_value FROM monthly"

            ),

            expected_columns=["check_id", "numeric_value", "text_value"],

            expected_max_rows=1,

            tables_expected=["analytics.order_line_facts"],

            covered_check_ids=["smb_revenue_change"],

        )


 

    def repair_sql(self, *, run_id, payload):

        return self.generate_sql(run_id=run_id, payload=payload)



 

class FakeClaimBuilder:

    def build(self, *, analyst_outcome, verifier_outcome, **kwargs):

        return VerifiedAnswer(

            headline="The Analyst result passed independent verification.",

            claims=[

                VerifiedClaim(

                    claim_id=str(uuid4()),

                    claim_key="smb_revenue_change",

                    statement="SMB revenue change: -₹20.00.",

                    metric_id="net_revenue",

                    value_type="number",

                    raw_value="-20.00",

                    display_value="-₹20.00",

                    analyst_query_id=str(analyst_outcome.query_id),

                    verifier_query_id=str(verifier_outcome.query_id),

                    citation="[A:test V:test]",

                )

            ],

            limitations=[],

        )



 

class RejectingQueryService:

    def __init__(self) -> None:

        self.calls = 0


 

    def execute_for_run(self, *, run_id: UUID, request):

        self.calls += 1

        return QueryExecutionOutcome(

            status="rejected",

            run_id=run_id,

            query_id=uuid4(),

            validation=SqlValidationResult(

                accepted=False,

                normalized_sql=request.sql,

                executable_sql=None,

                tables=["analytics.order_line_facts"],

                issues=[

                    ValidationIssue(

                        code="TEST_REJECTION",

                        message="The test service rejected this candidate.",

                    )

                ],

            ),

            error_code="TEST_REJECTION",

            error_message="The test service rejected this candidate.",

        )



 

class FakeQueryService:

    def execute_for_run(self, *, run_id: UUID, request):

        if request.query_role == "verifier":

            columns = ["check_id", "numeric_value", "text_value"]

            rows = [

                {

                    "check_id": "smb_revenue_change",

                    "numeric_value": "-20.00",

                    "text_value": None,

                }

            ]

        else:

            columns = [

                "customer_segment",

                "july_revenue",

                "august_revenue",

                "revenue_change",

            ]

            rows = [

                {

                    "customer_segment": "SMB",

                    "july_revenue": "120.00",

                    "august_revenue": "100.00",

                    "revenue_change": "-20.00",

                }

            ]


 

        return QueryExecutionOutcome(

            status="completed",

            run_id=run_id,

            query_id=uuid4(),

            validation=SqlValidationResult(

                accepted=True,

                normalized_sql=request.sql,

                executable_sql=request.sql + " LIMIT 501",

                tables=["analytics.order_line_facts"],

            ),

            plan=PlanSummary(

                accepted=True,

                total_cost=10,

                top_plan_rows=len(rows),

                max_node_rows=100,

                plan_width=32,

                node_count=2,

                sequential_scan_count=1,

                nested_loop_count=0,

                sort_count=0,

            ),

            result=QueryResult(

                columns=columns,

                rows=rows,

                returned_row_count=len(rows),

                truncated=False,

                duration_ms=3,

            ),

        )



 

def _dependencies(query_service):

    policy = load_sql_policy("config/sql_policy.yml")

    catalog = load_semantic_catalog(

        metrics_path="config/metrics.yml",

        dimensions_path="config/dimensions.yml",

        business_terms_path="config/business_terms.yml",

    )

    return AnalysisNodeDependencies(

        semantic_catalog=catalog,

        schema_service=FakeSchemaService(),  # type: ignore[arg-type]

        analyst=FakeAnalyst(),  # type: ignore[arg-type]

        verifier=FakeVerifier(),  # type: ignore[arg-type]

        query_service=query_service,  # type: ignore[arg-type]

        claim_builder=FakeClaimBuilder(),  # type: ignore[arg-type]

        audit=FakeAudit(),  # type: ignore[arg-type]

        sql_policy=policy,

        max_sql_repair_attempts=2,

        max_verifier_sql_repair_attempts=2,

        max_verification_repair_attempts=1,

        max_verification_checks=5,

    )



 

def test_graph_pauses_for_revenue_clarification_then_verifies() -> None:

    graph = build_analysis_graph(

        dependencies=_dependencies(FakeQueryService()),

        checkpointer=InMemorySaver(),

    )


 

    run_id = uuid4()

    config = {"configurable": {"thread_id": str(uuid4())}}

    first = graph.invoke(

        {

            "run_id": str(run_id),

            "thread_id": config["configurable"]["thread_id"],

            "question": "Why did revenue decrease last month by segment?",

            "status": "running",

            "repair_attempts": 0,

            "verification_sql_repair_attempts": 0,

            "verification_repair_attempts": 0,

        },

        config=config,

    )


 

    assert "__interrupt__" in first

    payload = first["__interrupt__"][0].value

    assert payload["question"] == "What should ‘revenue’ mean for this analysis?"


 

    final = graph.invoke(Command(resume={"choice_id": "net_revenue"}), config=config)


 

    assert final["status"] == "completed"

    assert final["reconciliation"]["status"] == "pass"

    assert final["verified_answer"]["verification_status"] == "passed"

    assert final["verified_answer"]["claims"][0]["claim_key"] == "smb_revenue_change"



 

def test_graph_stops_after_two_analyst_sql_repairs() -> None:

    rejecting_service = RejectingQueryService()

    graph = build_analysis_graph(

        dependencies=_dependencies(rejecting_service),

        checkpointer=InMemorySaver(),

    )


 

    config = {"configurable": {"thread_id": str(uuid4())}}

    final = graph.invoke(

        {

            "run_id": str(uuid4()),

            "thread_id": config["configurable"]["thread_id"],

            "question": "Why did net revenue decrease last month by segment?",

            "status": "running",

            "repair_attempts": 0,

            "verification_sql_repair_attempts": 0,

            "verification_repair_attempts": 0,

        },

        config=config,

    )


 

    assert final["status"] == "rejected"

    assert final["repair_attempts"] == 2

    assert rejecting_service.calls == 3


 