from uuid import uuid4


 

from app.provenance.claims import ClaimLedgerBuilder

from app.schemas.query import QueryExecutionOutcome

from app.sql.models import QueryResult, SqlValidationResult

from app.catalog.loader import load_semantic_catalog

from app.verification.models import (

    AnomalyReport,

    ReconciliationComparison,

    ReconciliationResult,

    ResultCellReference,

    VerificationCheck,

    VerificationPlan,

)



 

class FakeAudit:

    def __init__(self) -> None:

        self.sources: list[dict] = []

        self.artifacts: list[tuple[str, dict]] = []

        self.persisted_claims: list[dict] = []


 

    def replace_verified_claims(self, *, claims, **kwargs):

        self.persisted_claims = claims

        self.sources = [source for claim in claims for source in claim["sources"]]

        return [uuid4() for _ in claims]


 

    def save_artifact(self, *, artifact_type, payload, **kwargs):

        self.artifacts.append((artifact_type, payload))


 

    def log_tool_call(self, **kwargs):

        return None



 

def _outcome(*, rows, columns):

    return QueryExecutionOutcome(

        status="completed",

        run_id=uuid4(),

        query_id=uuid4(),

        validation=SqlValidationResult(

            accepted=True,

            normalized_sql="SELECT 1",

            executable_sql="SELECT 1",

        ),

        result=QueryResult(

            columns=columns,

            rows=rows,

            returned_row_count=len(rows),

            truncated=False,

            duration_ms=1,

        ),

    )



 

def test_claim_ledger_formats_negative_currency_and_links_both_queries() -> None:

    audit = FakeAudit()

    catalog = load_semantic_catalog(

        metrics_path="config/metrics.yml",

        dimensions_path="config/dimensions.yml",

        business_terms_path="config/business_terms.yml",

    )

    builder = ClaimLedgerBuilder(catalog=catalog, audit_repository=audit)  # type: ignore[arg-type]

    plan = VerificationPlan(

        decision="verify",

        summary="Verify the main decline.",

        independence_strategy="Recompute it independently.",

        checks=[

            VerificationCheck(

                check_id="smb_change",

                label="SMB revenue change",

                description="Recompute the change.",

                metric_id="net_revenue",

                value_type="number",

                unit="INR",

                importance="primary",

                analyst_source=ResultCellReference(row_index=0, column="revenue_change"),

            )

        ],

    )

    analyst = _outcome(

        rows=[{"customer_segment": "SMB", "revenue_change": "-20.00"}],

        columns=["customer_segment", "revenue_change"],

    )

    verifier = _outcome(

        rows=[{"check_id": "smb_change", "numeric_value": "-20.00", "text_value": None}],

        columns=["check_id", "numeric_value", "text_value"],

    )

    reconciliation = ReconciliationResult(

        status="pass",

        comparisons=[

            ReconciliationComparison(

                check_id="smb_change",

                label="SMB revenue change",

                value_type="number",

                analyst_source=ResultCellReference(row_index=0, column="revenue_change"),

                verifier_row_index=0,

                verifier_column="numeric_value",

                analyst_value="-20.00",

                verifier_value="-20.00",

                passed=True,

                difference="0.00",

                tolerance_used="0.01",

                message="Values match.",

            )

        ],

    )


 

    answer = builder.build(

        run_id=uuid4(),

        plan=plan,

        reconciliation=reconciliation,

        analyst_outcome=analyst,

        verifier_outcome=verifier,

        anomaly_report=AnomalyReport(status="pass"),

    )


 

    assert answer.headline == "SMB revenue change: -₹20.00."

    assert answer.claims[0].display_value == "-₹20.00"

    assert len(answer.claims[0].sources) == 2

    assert {source.role for source in answer.claims[0].sources} == {"analyst", "verifier"}

    assert len(audit.sources) == 2

    assert len(audit.persisted_claims) == 1


 