from __future__ import annotations


 

from decimal import Decimal, InvalidOperation

from typing import TYPE_CHECKING, Any

from uuid import UUID


 

from app.catalog.models import SemanticCatalog

from app.core.hashing import sha256_json

from app.schemas.query import QueryExecutionOutcome

from app.verification.models import (

    AnomalyReport,

    ClaimSourceReference,

    ReconciliationResult,

    VerificationPlan,

    VerifiedAnswer,

    VerifiedClaim,

)


 

if TYPE_CHECKING:

    from app.db.audit_repository import AuditRepository



 

class ClaimLedgerBuilder:

    def __init__(

        self,

        *,

        catalog: SemanticCatalog,

        audit_repository: AuditRepository,

    ) -> None:

        self.catalog = catalog

        self.audit = audit_repository


 

    def build(

        self,

        *,

        run_id: UUID,

        plan: VerificationPlan,

        reconciliation: ReconciliationResult,

        analyst_outcome: QueryExecutionOutcome,

        verifier_outcome: QueryExecutionOutcome,

        anomaly_report: AnomalyReport,

    ) -> VerifiedAnswer:

        if reconciliation.status != "pass":

            raise ValueError("Claims can only be built after reconciliation passes.")

        if analyst_outcome.result is None or verifier_outcome.result is None:

            raise ValueError("Both Analyst and Verifier results are required.")


 

        checks = {check.check_id: check for check in plan.checks}

        claim_drafts: list[dict[str, Any]] = []

        persistence_payloads: list[dict[str, Any]] = []


 

        ordered = sorted(

            reconciliation.comparisons,

            key=lambda comparison: (

                0 if checks[comparison.check_id].importance == "primary" else 1,

                comparison.check_id,

            ),

        )


 

        for comparison in ordered:

            if not comparison.passed:

                continue

            check = checks[comparison.check_id]

            raw_value = comparison.analyst_value

            display_value = self._format_value(raw_value, check.unit)

            statement = f"{check.label}: {display_value}."

            numeric_value = (

                self._numeric_or_none(raw_value)

                if check.value_type == "number"

                else None

            )

            text_value = str(raw_value) if check.value_type == "text" else None


 

            analyst_reference = {

                "role": "analyst",

                "row_index": comparison.analyst_source.row_index,

                "column": comparison.analyst_source.column,

                "check_id": comparison.check_id,

            }

            verifier_reference = {

                "role": "verifier",

                "row_index": comparison.verifier_row_index,

                "column": comparison.verifier_column,

                "check_id": comparison.check_id,

            }

            persistence_payloads.append(

                {

                    "claim_key": check.check_id,

                    "statement_text": statement,

                    "metric_id": check.metric_id,

                    "value_type": check.value_type,

                    "numeric_value": numeric_value,

                    "text_value": text_value,

                    "unit": check.unit,

                    "display_value": display_value,

                    "calculation": check.calculation,

                    "verification_status": "passed",

                    "source_check_id": check.check_id,

                    "importance": check.importance,

                    "sources": [

                        {

                            "query_id": analyst_outcome.query_id,

                            "result_reference": analyst_reference,

                        },

                        {

                            "query_id": verifier_outcome.query_id,

                            "result_reference": verifier_reference,

                        },

                    ],

                }

            )

            claim_drafts.append(

                {

                    "check": check,

                    "raw_value": raw_value,

                    "display_value": display_value,

                    "statement": statement,

                    "analyst_reference": analyst_reference,

                    "verifier_reference": verifier_reference,

                }

            )


 

        if not claim_drafts:

            raise ValueError("Reconciliation passed without any claimable comparisons.")


 

        claim_ids = self.audit.replace_verified_claims(

            run_id=run_id,

            claims=persistence_payloads,

        )

        if len(claim_ids) != len(claim_drafts):

            raise ValueError("The stored claim count did not match the verified claim count.")


 

        claims: list[VerifiedClaim] = []

        for claim_id, draft in zip(claim_ids, claim_drafts, strict=True):

            check = draft["check"]

            analyst_reference = draft["analyst_reference"]

            verifier_reference = draft["verifier_reference"]

            claims.append(

                VerifiedClaim(

                    claim_id=str(claim_id),

                    claim_key=check.check_id,

                    statement=draft["statement"],

                    metric_id=check.metric_id,

                    value_type=check.value_type,

                    raw_value=draft["raw_value"],

                    display_value=draft["display_value"],

                    analyst_query_id=str(analyst_outcome.query_id),

                    verifier_query_id=str(verifier_outcome.query_id),

                    citation=(

                        f"[A:{str(analyst_outcome.query_id)[:8]} "

                        f"V:{str(verifier_outcome.query_id)[:8]}]"

                    ),

                    sources=[

                        ClaimSourceReference(

                            role="analyst",

                            query_id=str(analyst_outcome.query_id),

                            row_index=analyst_reference["row_index"],

                            column=analyst_reference["column"],

                            check_id=analyst_reference["check_id"],

                        ),

                        ClaimSourceReference(

                            role="verifier",

                            query_id=str(verifier_outcome.query_id),

                            row_index=verifier_reference["row_index"],

                            column=verifier_reference["column"],

                            check_id=verifier_reference["check_id"],

                        ),

                    ],

                )

            )


 

        limitations = [

            finding.message

            for finding in anomaly_report.findings

            if finding.severity == "warning"

        ]

        limitations.extend(

            issue.description for issue in plan.issues if issue.severity in {"info", "warning"}

        )

        limitations.append(

            "Verification covers the material facts listed in the claim ledger, "

            "not every possible interpretation of the dataset."

        )

        limitations = list(dict.fromkeys(limitations))


 

        primary_claim = next(

            (claim for claim in claims if checks[claim.claim_key].importance == "primary"),

            claims[0] if claims else None,

        )

        answer = VerifiedAnswer(

            headline=(

                primary_claim.statement

                if primary_claim is not None

                else "The Analyst result passed independent verification."

            ),

            claims=claims,

            limitations=limitations,

        )

        payload = answer.model_dump(mode="json")

        self.audit.save_artifact(

            run_id=run_id,

            artifact_type="claim_ledger",

            payload={"claims": [claim.model_dump(mode="json") for claim in claims]},

        )

        self.audit.save_artifact(

            run_id=run_id,

            artifact_type="verified_answer",

            payload=payload,

        )

        self.audit.log_tool_call(

            run_id=run_id,

            graph_node="build_claim_ledger",

            tool_name="deterministic_claim_ledger_builder",

            status="success",

            input_hash=sha256_json(

                {

                    "verification_plan": plan.model_dump(mode="json"),

                    "reconciliation": reconciliation.model_dump(mode="json"),

                }

            ),

            output_reference=f"claims={len(claims)}",

            duration_ms=0,

        )

        return answer


 

    @staticmethod

    def _numeric_or_none(value: Any) -> str | None:

        try:

            if value is None or isinstance(value, bool):

                return None

            text = str(value).strip().replace(",", "")

            if text.endswith("%"):

                text = text[:-1].strip()

            for symbol in ("₹", "$", "€", "£"):

                text = text.replace(symbol, "")

            return str(Decimal(text))

        except (InvalidOperation, ValueError):

            return None


 

    @classmethod

    def _format_value(cls, value: Any, unit: str) -> str:

        if unit == "text":

            return str(value)


 

        number = cls._numeric_or_none(value)

        if number is None:

            return str(value)

        decimal_value = Decimal(number)


 

        if unit == "INR":

            sign = "-" if decimal_value < 0 else ""

            return f"{sign}₹{abs(decimal_value):,.2f}"

        if unit == "INR_per_order":

            sign = "-" if decimal_value < 0 else ""

            return f"{sign}₹{abs(decimal_value):,.2f} per order"

        if unit == "percent":

            return f"{decimal_value:,.2f}%"

        if unit in {"orders", "customers", "count"}:

            if decimal_value == decimal_value.to_integral_value():

                return f"{int(decimal_value):,}"

            return f"{decimal_value:,.2f}"

        return f"{decimal_value:,.2f} {unit}"


 