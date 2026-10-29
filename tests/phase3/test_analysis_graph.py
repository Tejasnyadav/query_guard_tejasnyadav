from datetime import date, datetime, timezone

from uuid import UUID, uuid4


 

from langgraph.checkpoint.memory import InMemorySaver

from langgraph.types import Command


 

from app.agents.models import (

    AnalysisPlanOutline,

    AnalysisStep,

    DraftObservation,

    DraftSummary,

    EvidenceReference,

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

from app.sql.models import (

    PlanSummary,

    QueryResult,

    SqlValidationResult,

    ValidationIssue,

)

from app.sql.policy import load_sql_policy



 

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


 

    def summarize(self, *, run_id, payload):

        return DraftSummary(

            headline="SMB had the largest displayed decline.",

            observations=[

                DraftObservation(

                    text="SMB revenue change was -20.00.",

                    evidence=[

                        EvidenceReference(

                            row_indices=[0],

                            columns=["customer_segment", "revenue_change"],

                        )

                    ],

                )

            ],

            limitations=["Draft only"],

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

                top_plan_rows=3,

                max_node_rows=100,

                plan_width=32,

                node_count=2,

                sequential_scan_count=1,

                nested_loop_count=0,

                sort_count=0,

            ),

            result=QueryResult(

                columns=[

                    "customer_segment",

                    "july_revenue",

                    "august_revenue",

                    "revenue_change",

                ],

                rows=[

                    {

                        "customer_segment": "SMB",

                        "july_revenue": "120.00",

                        "august_revenue": "100.00",

                        "revenue_change": "-20.00",

                    }

                ],

                returned_row_count=1,

                truncated=False,

                duration_ms=3,

            ),

        )



 

def test_graph_pauses_for_revenue_clarification_and_resumes() -> None:

    policy = load_sql_policy("config/sql_policy.yml")

    catalog = load_semantic_catalog(

        metrics_path="config/metrics.yml",  # type: ignore[arg-type]

        dimensions_path="config/dimensions.yml",  # type: ignore[arg-type]

        business_terms_path="config/business_terms.yml",  # type: ignore[arg-type]

    )

    graph = build_analysis_graph(

        dependencies=AnalysisNodeDependencies(

            semantic_catalog=catalog,

            schema_service=FakeSchemaService(),  # type: ignore[arg-type]

            analyst=FakeAnalyst(),  # type: ignore[arg-type]

            query_service=FakeQueryService(),  # type: ignore[arg-type]

            audit=FakeAudit(),  # type: ignore[arg-type]

            sql_policy=policy,

            max_sql_repair_attempts=2,

        ),

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

        },

        config=config,

    )


 

    assert "__interrupt__" in first

    payload = first["__interrupt__"][0].value

    assert payload["question"] == "What should ‘revenue’ mean for this analysis?"


 

    final = graph.invoke(

        Command(resume={"choice_id": "net_revenue"}),

        config=config,

    )


 

    assert final["status"] == "completed"

    assert final["term_resolution"]["metric_ids"][0] == "net_revenue"

    assert final["query_outcome"]["status"] == "completed"

    assert final["draft_summary"]["verification_status"] == "draft_unverified"



 

def test_graph_stops_after_two_sql_repairs() -> None:

    policy = load_sql_policy("config/sql_policy.yml")

    catalog = load_semantic_catalog(

        metrics_path="config/metrics.yml",

        dimensions_path="config/dimensions.yml",

        business_terms_path="config/business_terms.yml",

    )

    rejecting_service = RejectingQueryService()

    graph = build_analysis_graph(

        dependencies=AnalysisNodeDependencies(

            semantic_catalog=catalog,

            schema_service=FakeSchemaService(),  # type: ignore[arg-type]

            analyst=FakeAnalyst(),  # type: ignore[arg-type]

            query_service=rejecting_service,  # type: ignore[arg-type]

            audit=FakeAudit(),  # type: ignore[arg-type]

            sql_policy=policy,

            max_sql_repair_attempts=2,

        ),

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

        },

        config=config,

    )


 

    assert final["status"] == "rejected"

    assert final["repair_attempts"] == 2

    assert rejecting_service.calls == 3


 