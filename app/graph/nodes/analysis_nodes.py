import re

from dataclasses import dataclass

from time import perf_counter

from typing import Literal

from uuid import UUID


 

from langgraph.types import interrupt


 

from app.agents.models import (

    AnalysisPlan,

    ClarificationAnswer,

    DraftSummary,

    SQLCandidate,

    TermResolution,

)

from app.agents.openai_analyst import OpenAIAnalyst

from app.agents.openai_verifier import OpenAIVerifier

from app.analysis.guards import (

    apply_clarification_choice,

    build_validated_plan,

    enforce_term_resolution,

    validate_draft_summary,

    validate_sql_candidate,

)

from app.analysis.time_periods import resolve_time_context

from app.catalog.models import SchemaSnapshot, SemanticCatalog

from app.catalog.schema_service import SchemaCatalogService

from app.core.errors import AgentWorkflowError

from app.core.hashing import sha256_json

from app.db.audit_repository import AuditRepository

from app.graph.state import AnalysisState

from app.provenance.claims import ClaimLedgerBuilder

from app.schemas.query import ExecuteSqlRequest, QueryExecutionOutcome

from app.services.query_service import QueryService

from app.sql.policy import SqlPolicy

from app.verification.anomalies import inspect_result_anomalies

from app.verification.guards import (

    validate_verification_plan,

    validate_verification_sql_candidate,

)

from app.verification.models import (

    AnomalyReport,

    ReconciliationResult,

    VerificationPlan,

    VerificationSQLCandidate,

)

from app.verification.reconcile import reconcile_results



 

@dataclass(slots=True)

class AnalysisNodeDependencies:

    semantic_catalog: SemanticCatalog

    schema_service: SchemaCatalogService

    analyst: OpenAIAnalyst

    verifier: OpenAIVerifier

    query_service: QueryService

    claim_builder: ClaimLedgerBuilder

    audit: AuditRepository

    sql_policy: SqlPolicy

    max_sql_repair_attempts: int

    max_verifier_sql_repair_attempts: int

    max_verification_repair_attempts: int

    max_verification_checks: int



 

class AnalysisNodes:

    _MUTATING_REQUEST = re.compile(

        r"^\s*(delete|drop|update|insert|alter|truncate|create|grant|revoke|merge|copy)\b",

        flags=re.IGNORECASE,

    )


 

    def __init__(self, dependencies: AnalysisNodeDependencies) -> None:

        self.deps = dependencies


 

    def normalize_request(self, state: AnalysisState) -> AnalysisState:

        started = perf_counter()

        run_id = UUID(state["run_id"])

        question = " ".join(state["question"].split())


 

        if self._MUTATING_REQUEST.search(question):

            error_code = "UNSUPPORTED_MUTATING_REQUEST"

            error_message = "QueryGuard only supports read-only business analysis questions."

            self.deps.audit.log_tool_call(

                run_id=run_id,

                graph_node="normalize_request",

                tool_name="deterministic_intake_guard",

                status="rejected",

                input_hash=sha256_json({"question": question}),

                output_reference=f"error_code={error_code}",

                duration_ms=self._elapsed_ms(started),

            )

            return {

                "normalized_question": question,

                "status": "rejected",

                "error_code": error_code,

                "error_message": error_message,

            }


 

        self.deps.audit.update_run_context(

            run_id=run_id,

            normalized_question=question,

            current_node="normalize_request",

        )

        self.deps.audit.log_tool_call(

            run_id=run_id,

            graph_node="normalize_request",

            tool_name="deterministic_request_normalizer",

            status="success",

            input_hash=sha256_json({"question": state["question"]}),

            output_reference="normalized_question_saved",

            duration_ms=self._elapsed_ms(started),

        )

        return {

            "normalized_question": question,

            "status": "running",

            "repair_attempts": 0,

        }


 

    def load_schema(self, state: AnalysisState) -> AnalysisState:

        started = perf_counter()

        run_id = UUID(state["run_id"])

        snapshot = self.deps.schema_service.load_snapshot()

        payload = snapshot.model_dump(mode="json")

        self.deps.audit.save_artifact(

            run_id=run_id,

            artifact_type="schema_snapshot",

            payload=payload,

        )

        self.deps.audit.update_run_context(run_id=run_id, current_node="load_schema")

        self.deps.audit.log_tool_call(

            run_id=run_id,

            graph_node="load_schema",

            tool_name="trusted_schema_introspector",

            status="success",

            input_hash=sha256_json({"allowed_tables": sorted(self.deps.sql_policy.allowed_tables)}),

            output_reference=f"tables={len(snapshot.tables)}; as_of={snapshot.dataset.as_of_date}",

            duration_ms=self._elapsed_ms(started),

        )

        return {"schema_snapshot": payload}


 

    def resolve_business_terms(self, state: AnalysisState) -> AnalysisState:

        run_id = UUID(state["run_id"])

        snapshot = SchemaSnapshot.model_validate(state["schema_snapshot"])

        payload = {

            "question": state["normalized_question"],

            "semantic_catalog": self.deps.semantic_catalog.compact_for_prompt(),

            "dataset": snapshot.dataset.model_dump(mode="json"),

        }

        resolution = self.deps.analyst.resolve_terms(run_id=run_id, payload=payload)

        resolution = enforce_term_resolution(

            question=state["normalized_question"],

            resolution=resolution,

            catalog=self.deps.semantic_catalog,

        )

        time_context = resolve_time_context(

            question=state["normalized_question"],

            resolution=resolution,

            as_of_date=snapshot.dataset.as_of_date,

        )


 

        resolution_payload = resolution.model_dump(mode="json")

        time_payload = time_context.model_dump(mode="json")

        self.deps.audit.save_artifact(

            run_id=run_id,

            artifact_type="term_resolution",

            payload=resolution_payload,

            artifact_version=1,

        )

        self.deps.audit.save_artifact(

            run_id=run_id,

            artifact_type="time_context",

            payload=time_payload,

        )

        self.deps.audit.update_run_context(

            run_id=run_id,

            selected_metric_ids=resolution.metric_ids,

            selected_dimension_ids=resolution.dimension_ids,

            assumptions=resolution.assumptions,

            current_node="resolve_business_terms",

        )


 

        if resolution.needs_clarification:

            if not resolution.clarification_question or not resolution.clarification_options:

                raise AgentWorkflowError(

                    code="INVALID_CLARIFICATION_OUTPUT",

                    message="The terminology resolver requested clarification without options.",

                )

            self.deps.audit.upsert_clarification(

                run_id=run_id,

                question=resolution.clarification_question,

                options=[

                    option.model_dump(mode="json")

                    for option in resolution.clarification_options

                ],

            )

            self.deps.audit.set_run_status(

                run_id,

                "needs_clarification",

                current_node="request_clarification",

            )


 

        return {

            "term_resolution": resolution_payload,

            "term_resolution_version": 1,

            "time_context": time_payload,

            "status": "needs_clarification" if resolution.needs_clarification else "running",

        }


 

    def request_clarification(self, state: AnalysisState) -> AnalysisState:

        resolution = TermResolution.model_validate(state["term_resolution"])

        answer = interrupt(

            {

                "type": "business_term_clarification",

                "question": resolution.clarification_question,

                "options": [

                    option.model_dump(mode="json")

                    for option in resolution.clarification_options

                ],

            },

            response_schema=ClarificationAnswer,

        )

        if not isinstance(answer, ClarificationAnswer):

            answer = ClarificationAnswer.model_validate(answer)

        return {"clarification_answer": answer.model_dump(mode="json")}


 

    def apply_clarification(self, state: AnalysisState) -> AnalysisState:

        run_id = UUID(state["run_id"])

        resolution = TermResolution.model_validate(state["term_resolution"])

        answer = ClarificationAnswer.model_validate(state["clarification_answer"])

        updated = apply_clarification_choice(

            resolution=resolution,

            choice_id=answer.choice_id,

            catalog=self.deps.semantic_catalog,

        )

        version = int(state.get("term_resolution_version", 1)) + 1

        payload = updated.model_dump(mode="json")

        self.deps.audit.answer_clarification(run_id=run_id, choice_id=answer.choice_id)

        self.deps.audit.save_artifact(

            run_id=run_id,

            artifact_type="term_resolution",

            artifact_version=version,

            payload=payload,

        )

        self.deps.audit.set_run_status(run_id, "running", current_node="apply_clarification")

        self.deps.audit.update_run_context(

            run_id=run_id,

            selected_metric_ids=updated.metric_ids,

            selected_dimension_ids=updated.dimension_ids,

            assumptions=updated.assumptions,

        )

        self.deps.audit.log_tool_call(

            run_id=run_id,

            graph_node="apply_clarification",

            tool_name="deterministic_clarification_mapper",

            status="success",

            input_hash=sha256_json(answer.model_dump(mode="json")),

            output_reference=f"selected_metric={answer.choice_id}",

            duration_ms=0,

        )

        return {

            "term_resolution": payload,

            "term_resolution_version": version,

            "status": "running",

        }


 

    def create_analysis_plan(self, state: AnalysisState) -> AnalysisState:

        run_id = UUID(state["run_id"])

        snapshot = SchemaSnapshot.model_validate(state["schema_snapshot"])

        resolution = TermResolution.model_validate(state["term_resolution"])

        payload = {

            "question": state["normalized_question"],

            "term_resolution": resolution.model_dump(mode="json"),

            "time_context": state["time_context"],

            "semantic_catalog": self.deps.semantic_catalog.compact_for_prompt(),

            "schema": self.deps.schema_service.compact_for_prompt(snapshot),

            "allowed_views": sorted(self.deps.sql_policy.allowed_tables),

        }

        outline = self.deps.analyst.create_plan(run_id=run_id, payload=payload)

        plan = build_validated_plan(

            outline=outline,

            resolution=resolution,

            time_context=state_time_context(state),

            catalog=self.deps.semantic_catalog,

            snapshot=snapshot,

            policy=self.deps.sql_policy,

        )

        plan_payload = plan.model_dump(mode="json")

        self.deps.audit.save_artifact(

            run_id=run_id,

            artifact_type="analysis_plan",

            payload=plan_payload,

        )

        self.deps.audit.update_run_context(run_id=run_id, current_node="create_analysis_plan")

        return {"analysis_plan": plan_payload}


 

    def generate_sql(self, state: AnalysisState) -> AnalysisState:

        run_id = UUID(state["run_id"])

        snapshot = SchemaSnapshot.model_validate(state["schema_snapshot"])

        plan = AnalysisPlan.model_validate(state["analysis_plan"])

        payload = {

            "question": state["normalized_question"],

            "analysis_plan": plan.model_dump(mode="json"),

            "metric_definitions": {

                metric_id: self.deps.semantic_catalog.metrics[metric_id].model_dump(mode="json")

                for metric_id in plan.metric_ids

            },

            "dimension_definitions": {

                dimension_id: self.deps.semantic_catalog.dimensions[dimension_id].model_dump(

                    mode="json"

                )

                for dimension_id in plan.dimension_ids

            },

            "schema": self.deps.schema_service.compact_for_prompt(snapshot),

            "sql_policy": {

                "allowed_tables": sorted(self.deps.sql_policy.allowed_tables),

                "max_result_rows": self.deps.sql_policy.max_result_rows,

                "forbid_select_star": self.deps.sql_policy.forbid_select_star,

                "max_joins": self.deps.sql_policy.max_joins,

            },

        }

        candidate = self.deps.analyst.generate_sql(run_id=run_id, payload=payload)

        candidate = validate_sql_candidate(

            candidate,

            self.deps.sql_policy,

            plan=plan,

        )

        candidate_payload = candidate.model_dump(mode="json")

        self.deps.audit.save_artifact(

            run_id=run_id,

            artifact_type="sql_candidate",

            artifact_version=1,

            payload=candidate_payload,

        )

        self.deps.audit.update_run_context(run_id=run_id, current_node="generate_sql")

        return {"sql_candidate": candidate_payload, "repair_attempts": 0}


 

    def execute_sql(self, state: AnalysisState) -> AnalysisState:

        run_id = UUID(state["run_id"])

        candidate = SQLCandidate.model_validate(state["sql_candidate"])

        outcome = self.deps.query_service.execute_for_run(

            run_id=run_id,

            request=ExecuteSqlRequest(

                question=state["normalized_question"],

                purpose=candidate.purpose,

                sql=candidate.sql,

                expected_tables=candidate.tables_expected,

                expected_columns=candidate.expected_columns,

                query_role="analyst",

                candidate_key=f"analyst_v{int(state.get('verification_repair_attempts', 0)) + 1}",

            ),

        )

        self.deps.audit.update_run_context(run_id=run_id, current_node="execute_sql")

        return {

            "query_outcome": outcome.model_dump(mode="json"),

            "status": "running" if outcome.status == "completed" else outcome.status,

            "error_code": None if outcome.status == "completed" else outcome.error_code,

            "error_message": None if outcome.status == "completed" else outcome.error_message,

        }


 

    def repair_sql(self, state: AnalysisState) -> AnalysisState:

        run_id = UUID(state["run_id"])

        previous = SQLCandidate.model_validate(state["sql_candidate"])

        outcome = QueryExecutionOutcome.model_validate(state["query_outcome"])

        snapshot = SchemaSnapshot.model_validate(state["schema_snapshot"])

        repair_attempts = int(state.get("repair_attempts", 0)) + 1

        payload = {

            "question": state["normalized_question"],

            "analysis_plan": state["analysis_plan"],

            "metric_definitions": {

                metric_id: self.deps.semantic_catalog.metrics[metric_id].model_dump(mode="json")

                for metric_id in AnalysisPlan.model_validate(state["analysis_plan"]).metric_ids

            },

            "dimension_definitions": {

                dimension_id: self.deps.semantic_catalog.dimensions[dimension_id].model_dump(

                    mode="json"

                )

                for dimension_id in AnalysisPlan.model_validate(

                    state["analysis_plan"]

                ).dimension_ids

            },

            "previous_candidate": previous.model_dump(mode="json"),

            "failure": {

                "status": outcome.status,

                "error_code": outcome.error_code,

                "error_message": outcome.error_message,

                "validation_issues": [

                    issue.model_dump(mode="json") for issue in outcome.validation.issues

                ],

                "plan_rejection_reasons": (

                    outcome.plan.rejection_reasons if outcome.plan else []

                ),

            },

            "schema": self.deps.schema_service.compact_for_prompt(snapshot),

            "sql_policy": {

                "allowed_tables": sorted(self.deps.sql_policy.allowed_tables),

                "max_result_rows": self.deps.sql_policy.max_result_rows,

                "forbid_select_star": self.deps.sql_policy.forbid_select_star,

                "max_joins": self.deps.sql_policy.max_joins,

            },

            "repair_attempt": repair_attempts,

            "maximum_repairs": self.deps.max_sql_repair_attempts,

        }

        candidate = self.deps.analyst.repair_sql(run_id=run_id, payload=payload)

        candidate = validate_sql_candidate(

            candidate,

            self.deps.sql_policy,

            plan=AnalysisPlan.model_validate(state["analysis_plan"]),

        )

        candidate_payload = candidate.model_dump(mode="json")

        self.deps.audit.save_artifact(

            run_id=run_id,

            artifact_type="sql_candidate",

            artifact_version=repair_attempts + 1,

            payload=candidate_payload,

        )

        self.deps.audit.update_run_context(run_id=run_id, current_node="repair_sql")

        return {

            "sql_candidate": candidate_payload,

            "repair_attempts": repair_attempts,

            "status": "running",

            "error_code": None,

            "error_message": None,

        }


 

    def inspect_anomalies(self, state: AnalysisState) -> AnalysisState:

        run_id = UUID(state["run_id"])

        candidate = SQLCandidate.model_validate(state["sql_candidate"])

        outcome = QueryExecutionOutcome.model_validate(state["query_outcome"])

        report = inspect_result_anomalies(candidate=candidate, outcome=outcome)

        version = int(state.get("verification_repair_attempts", 0)) + 1

        payload = report.model_dump(mode="json")

        self.deps.audit.save_artifact(

            run_id=run_id,

            artifact_type="anomaly_report",

            artifact_version=version,

            payload=payload,

        )

        self.deps.audit.log_tool_call(

            run_id=run_id,

            graph_node="inspect_anomalies",

            tool_name="deterministic_result_anomaly_checker",

            status="rejected" if report.status == "reject" else "success",

            input_hash=sha256_json(

                {

                    "query_id": str(outcome.query_id),

                    "result": outcome.result.model_dump(mode="json") if outcome.result else None,

                }

            ),

            output_reference=(

                f"status={report.status}; "

                f"findings={','.join(item.code for item in report.findings) or 'none'}"

            ),

            duration_ms=0,

        )

        self.deps.audit.update_run_context(run_id=run_id, current_node="inspect_anomalies")

        if report.status == "reject":

            message = " ".join(item.message for item in report.findings if item.severity == "error")

            return {

                "anomaly_report": payload,

                "status": "rejected",

                "error_code": "ANALYST_RESULT_ANOMALY_REJECTED",

                "error_message": message or "The Analyst result failed anomaly checks.",

            }

        return {"anomaly_report": payload}


 

    def review_methodology(self, state: AnalysisState) -> AnalysisState:

        run_id = UUID(state["run_id"])

        snapshot = SchemaSnapshot.model_validate(state["schema_snapshot"])

        candidate = SQLCandidate.model_validate(state["sql_candidate"])

        outcome = QueryExecutionOutcome.model_validate(state["query_outcome"])

        anomaly_report = AnomalyReport.model_validate(state["anomaly_report"])

        if outcome.result is None:

            raise AgentWorkflowError(

                code="MISSING_ANALYST_RESULT_FOR_VERIFIER",

                message="The Verifier requires the completed Analyst result.",

            )


 

        payload = {

            "question": state["normalized_question"],

            "analysis_plan": state["analysis_plan"],

            "metric_definitions": {

                metric_id: self.deps.semantic_catalog.metrics[metric_id].model_dump(mode="json")

                for metric_id in AnalysisPlan.model_validate(state["analysis_plan"]).metric_ids

            },

            "dimension_definitions": {

                dimension_id: self.deps.semantic_catalog.dimensions[dimension_id].model_dump(

                    mode="json"

                )

                for dimension_id in AnalysisPlan.model_validate(

                    state["analysis_plan"]

                ).dimension_ids

            },

            "schema": self.deps.schema_service.compact_for_prompt(snapshot),

            "analyst_sql_candidate": candidate.model_dump(mode="json"),

            "analyst_query": {

                "query_id": str(outcome.query_id),

                "validation": outcome.validation.model_dump(mode="json"),

                "plan": outcome.plan.model_dump(mode="json") if outcome.plan else None,

                "result": outcome.result.model_dump(mode="json"),

            },

            "anomaly_report": anomaly_report.model_dump(mode="json"),

            "maximum_checks": self.deps.max_verification_checks,

        }

        plan = self.deps.verifier.inspect_methodology(run_id=run_id, payload=payload)

        plan = validate_verification_plan(

            plan=plan,

            analyst_columns=outcome.result.columns,

            analyst_rows=outcome.result.rows,

            catalog=self.deps.semantic_catalog,

            max_checks=self.deps.max_verification_checks,

        )

        version = int(state.get("verification_repair_attempts", 0)) + 1

        plan_payload = plan.model_dump(mode="json")

        self.deps.audit.save_artifact(

            run_id=run_id,

            artifact_type="verification_plan",

            artifact_version=version,

            payload=plan_payload,

        )

        self.deps.audit.save_verifier_review(

            run_id=run_id,

            review_version=version,

            analyst_query_id=outcome.query_id,

            decision=plan.decision,

            summary=plan.summary,

            independence_strategy=plan.independence_strategy,

            issues=[item.model_dump(mode="json") for item in plan.issues],

            checks=[item.model_dump(mode="json") for item in plan.checks],

        )

        self.deps.audit.update_verification_status(

            run_id=run_id,

            verification_status="reviewing" if plan.decision == "verify" else "rejected",

            repair_attempts=int(state.get("verification_repair_attempts", 0)),

            current_node="review_methodology",

        )

        if plan.decision == "reject":

            message = " ".join(

                issue.description for issue in plan.issues if issue.severity == "error"

            ) or plan.summary

            return {

                "verification_plan": plan_payload,

                "status": "rejected",

                "error_code": "VERIFIER_METHODOLOGY_REJECTED",

                "error_message": message,

            }

        return {

            "verification_plan": plan_payload,

            "verification_sql_repair_attempts": 0,

        }


 

    def generate_verification_sql(self, state: AnalysisState) -> AnalysisState:

        run_id = UUID(state["run_id"])

        snapshot = SchemaSnapshot.model_validate(state["schema_snapshot"])

        analyst_candidate = SQLCandidate.model_validate(state["sql_candidate"])

        plan = VerificationPlan.model_validate(state["verification_plan"])


 

        payload = {

            "question": state["normalized_question"],

            "analysis_plan": state["analysis_plan"],

            "verification_plan": plan.model_dump(mode="json"),

            "analyst_sql": analyst_candidate.sql,

            "metric_definitions": {

                metric_id: self.deps.semantic_catalog.metrics[metric_id].model_dump(

                    mode="json"

                )

                for metric_id in AnalysisPlan.model_validate(

                    state["analysis_plan"]

                ).metric_ids

            },

            "schema": self.deps.schema_service.compact_for_prompt(snapshot),

            "sql_policy": {

                "allowed_tables": sorted(self.deps.sql_policy.allowed_tables),

                "max_result_rows": self.deps.sql_policy.max_result_rows,

                "forbid_select_star": self.deps.sql_policy.forbid_select_star,

                "max_joins": self.deps.sql_policy.max_joins,

            },

        }

        candidate = self.deps.verifier.generate_sql(run_id=run_id, payload=payload)

        verification_round = int(state.get("verification_repair_attempts", 0))

        version = verification_round * 100 + 1

        return self._store_verification_candidate(

            state=state,

            candidate=candidate,

            analyst_sql=analyst_candidate.sql,

            plan=plan,

            artifact_version=version,

            repair_attempts=0,

            node_name="generate_verification_sql",

        )


 

    def execute_verification_sql(self, state: AnalysisState) -> AnalysisState:

        run_id = UUID(state["run_id"])

        candidate = VerificationSQLCandidate.model_validate(

            state["verification_sql_candidate"]

        )

        analyst_outcome = QueryExecutionOutcome.model_validate(state["query_outcome"])

        outcome = self.deps.query_service.execute_for_run(

            run_id=run_id,

            request=ExecuteSqlRequest(

                question=state["normalized_question"],

                purpose=candidate.purpose,

                sql=candidate.sql,

                expected_tables=candidate.tables_expected,

                expected_columns=candidate.expected_columns,

                query_role="verifier",

                parent_query_id=analyst_outcome.query_id,

                candidate_key=(

                    f"verifier_v{int(state.get('verification_repair_attempts', 0)) + 1}_"

                    f"r{int(state.get('verification_sql_repair_attempts', 0))}"

                ),

            ),

        )

        self.deps.audit.update_run_context(

            run_id=run_id,

            current_node="execute_verification_sql",

        )

        update: AnalysisState = {

            "verification_query_outcome": outcome.model_dump(mode="json"),

            "status": "running" if outcome.status == "completed" else outcome.status,

        }

        if outcome.status != "completed":

            update.update(

                {

                    "error_code": outcome.error_code,

                    "error_message": outcome.error_message,

                }

            )

        return update


 

    def repair_verification_sql(self, state: AnalysisState) -> AnalysisState:

        run_id = UUID(state["run_id"])

        previous = VerificationSQLCandidate.model_validate(

            state["verification_sql_candidate"]

        )

        snapshot = SchemaSnapshot.model_validate(state["schema_snapshot"])

        plan = VerificationPlan.model_validate(state["verification_plan"])

        analyst_candidate = SQLCandidate.model_validate(state["sql_candidate"])

        repair_attempts = int(state.get("verification_sql_repair_attempts", 0)) + 1


 

        candidate_error = state.get("verification_candidate_error")

        if candidate_error:

            failure = candidate_error

        else:

            outcome = QueryExecutionOutcome.model_validate(

                state["verification_query_outcome"]

            )

            failure = {

                "status": outcome.status,

                "error_code": outcome.error_code,

                "error_message": outcome.error_message,

                "validation_issues": [

                    issue.model_dump(mode="json") for issue in outcome.validation.issues

                ],

                "plan_rejection_reasons": (

                    outcome.plan.rejection_reasons if outcome.plan else []

                ),

            }


 

        payload = {

            "question": state["normalized_question"],

            "verification_plan": plan.model_dump(mode="json"),

            "analyst_sql": analyst_candidate.sql,

            "previous_candidate": previous.model_dump(mode="json"),

            "failure": failure,

            "schema": self.deps.schema_service.compact_for_prompt(snapshot),

            "sql_policy": {

                "allowed_tables": sorted(self.deps.sql_policy.allowed_tables),

                "max_result_rows": self.deps.sql_policy.max_result_rows,

                "forbid_select_star": self.deps.sql_policy.forbid_select_star,

                "max_joins": self.deps.sql_policy.max_joins,

            },

            "repair_attempt": repair_attempts,

            "maximum_repairs": self.deps.max_verifier_sql_repair_attempts,

        }

        candidate = self.deps.verifier.repair_sql(run_id=run_id, payload=payload)

        verification_round = int(state.get("verification_repair_attempts", 0))

        artifact_version = verification_round * 100 + repair_attempts + 1

        return self._store_verification_candidate(

            state=state,

            candidate=candidate,

            analyst_sql=analyst_candidate.sql,

            plan=plan,

            artifact_version=artifact_version,

            repair_attempts=repair_attempts,

            node_name="repair_verification_sql",

        )


 

    def _store_verification_candidate(

        self,

        *,

        state: AnalysisState,

        candidate: VerificationSQLCandidate,

        analyst_sql: str,

        plan: VerificationPlan,

        artifact_version: int,

        repair_attempts: int,

        node_name: str,

    ) -> AnalysisState:

        run_id = UUID(state["run_id"])

        candidate_payload = candidate.model_dump(mode="json")

        self.deps.audit.save_artifact(

            run_id=run_id,

            artifact_type="verification_sql_candidate",

            artifact_version=artifact_version,

            payload=candidate_payload,

        )


 

        try:

            validate_verification_sql_candidate(

                candidate=candidate,

                plan=plan,

                analyst_sql=analyst_sql,

                policy=self.deps.sql_policy,

            )

        except AgentWorkflowError as exc:

            error_payload = {

                "status": "rejected",

                "error_code": exc.code,

                "error_message": exc.message,

            }

            self.deps.audit.log_tool_call(

                run_id=run_id,

                graph_node=node_name,

                tool_name="deterministic_verifier_result_contract",

                status="rejected",

                input_hash=sha256_json(candidate_payload),

                output_reference=f"error_code={exc.code}",

                duration_ms=0,

            )

            self.deps.audit.update_run_context(run_id=run_id, current_node=node_name)

            return {

                "verification_sql_candidate": candidate_payload,

                "verification_candidate_error": error_payload,

                "verification_sql_repair_attempts": repair_attempts,

                "status": "rejected",

                "error_code": exc.code,

                "error_message": exc.message,

            }


 

        self.deps.audit.log_tool_call(

            run_id=run_id,

            graph_node=node_name,

            tool_name="deterministic_verifier_result_contract",

            status="success",

            input_hash=sha256_json(candidate_payload),

            output_reference=f"checks={len(plan.checks)}",

            duration_ms=0,

        )

        self.deps.audit.update_verification_status(

            run_id=run_id,

            verification_status="querying",

            current_node=node_name,

        )

        return {

            "verification_sql_candidate": candidate_payload,

            "verification_candidate_error": None,

            "verification_sql_repair_attempts": repair_attempts,

            "status": "running",

            "error_code": None,

            "error_message": None,

        }


 

    def reconcile_results(self, state: AnalysisState) -> AnalysisState:

        run_id = UUID(state["run_id"])

        plan = VerificationPlan.model_validate(state["verification_plan"])

        analyst_outcome = QueryExecutionOutcome.model_validate(state["query_outcome"])

        verifier_outcome = QueryExecutionOutcome.model_validate(

            state["verification_query_outcome"]

        )

        if analyst_outcome.result is None or verifier_outcome.result is None:

            raise AgentWorkflowError(

                code="MISSING_RESULT_FOR_RECONCILIATION",

                message="Both Analyst and Verifier results are required for reconciliation.",

            )


 

        result = reconcile_results(

            plan=plan,

            analyst_rows=analyst_outcome.result.rows,

            verifier_rows=verifier_outcome.result.rows,

            verifier_truncated=verifier_outcome.result.truncated,

        )

        version = int(state.get("verification_repair_attempts", 0)) + 1

        payload = result.model_dump(mode="json")

        self.deps.audit.save_artifact(

            run_id=run_id,

            artifact_type="reconciliation",

            artifact_version=version,

            payload=payload,

        )

        self.deps.audit.save_reconciliation(

            run_id=run_id,

            reconciliation_version=version,

            analyst_query_id=analyst_outcome.query_id,

            verifier_query_id=verifier_outcome.query_id,

            status=result.status,

            comparisons=[item.model_dump(mode="json") for item in result.comparisons],

            issues=result.issues,

        )

        verification_status = "passed" if result.status == "pass" else "reconciling"

        self.deps.audit.update_verification_status(

            run_id=run_id,

            verification_status=verification_status,

            repair_attempts=int(state.get("verification_repair_attempts", 0)),

            current_node="reconcile_results",

        )

        if result.status == "pass":

            return {

                "reconciliation": payload,

                "error_code": None,

                "error_message": None,

            }

        if result.status == "mismatch":

            return {

                "reconciliation": payload,

                "status": "rejected",

                "error_code": "ANALYST_VERIFIER_MISMATCH",

                "error_message": "The Analyst and Verifier results did not match.",

            }

        return {

            "reconciliation": payload,

            "status": "rejected",

            "error_code": "RECONCILIATION_REJECTED",

            "error_message": " ".join(result.issues) or "Reconciliation could not be completed.",

        }


 

    def repair_analyst_from_verifier(self, state: AnalysisState) -> AnalysisState:

        run_id = UUID(state["run_id"])

        previous = SQLCandidate.model_validate(state["sql_candidate"])

        snapshot = SchemaSnapshot.model_validate(state["schema_snapshot"])

        repair_attempts = int(state.get("verification_repair_attempts", 0)) + 1

        payload = {

            "question": state["normalized_question"],

            "analysis_plan": state["analysis_plan"],

            "metric_definitions": {

                metric_id: self.deps.semantic_catalog.metrics[metric_id].model_dump(mode="json")

                for metric_id in AnalysisPlan.model_validate(state["analysis_plan"]).metric_ids

            },

            "dimension_definitions": {

                dimension_id: self.deps.semantic_catalog.dimensions[dimension_id].model_dump(

                    mode="json"

                )

                for dimension_id in AnalysisPlan.model_validate(

                    state["analysis_plan"]

                ).dimension_ids

            },

            "previous_candidate": previous.model_dump(mode="json"),

            "verification_plan": state["verification_plan"],

            "verification_sql_candidate": state["verification_sql_candidate"],

            "analyst_result": QueryExecutionOutcome.model_validate(

                state["query_outcome"]

            ).model_dump(mode="json"),

            "verifier_result": QueryExecutionOutcome.model_validate(

                state["verification_query_outcome"]

            ).model_dump(mode="json"),

            "reconciliation": state["reconciliation"],

            "schema": self.deps.schema_service.compact_for_prompt(snapshot),

            "sql_policy": {

                "allowed_tables": sorted(self.deps.sql_policy.allowed_tables),

                "max_result_rows": self.deps.sql_policy.max_result_rows,

                "forbid_select_star": self.deps.sql_policy.forbid_select_star,

                "max_joins": self.deps.sql_policy.max_joins,

            },

            "verification_repair_attempt": repair_attempts,

            "maximum_verification_repairs": self.deps.max_verification_repair_attempts,

        }

        candidate = self.deps.analyst.repair_from_verifier(run_id=run_id, payload=payload)

        candidate = validate_sql_candidate(

            candidate,

            self.deps.sql_policy,

            plan=AnalysisPlan.model_validate(state["analysis_plan"]),

        )

        candidate_payload = candidate.model_dump(mode="json")

        self.deps.audit.save_artifact(

            run_id=run_id,

            artifact_type="verification_driven_sql_candidate",

            artifact_version=repair_attempts,

            payload=candidate_payload,

        )

        self.deps.audit.update_verification_status(

            run_id=run_id,

            verification_status="repairing",

            repair_attempts=repair_attempts,

            current_node="repair_analyst_from_verifier",

        )

        return {

            "sql_candidate": candidate_payload,

            "repair_attempts": 0,

            "verification_repair_attempts": repair_attempts,

            "verification_sql_repair_attempts": 0,

            "status": "running",

            "error_code": None,

            "error_message": None,

        }


 

    def build_claim_ledger(self, state: AnalysisState) -> AnalysisState:

        run_id = UUID(state["run_id"])

        answer = self.deps.claim_builder.build(

            run_id=run_id,

            plan=VerificationPlan.model_validate(state["verification_plan"]),

            reconciliation=ReconciliationResult.model_validate(state["reconciliation"]),

            analyst_outcome=QueryExecutionOutcome.model_validate(state["query_outcome"]),

            verifier_outcome=QueryExecutionOutcome.model_validate(

                state["verification_query_outcome"]

            ),

            anomaly_report=AnomalyReport.model_validate(state["anomaly_report"]),

        )

        self.deps.audit.update_run_context(run_id=run_id, current_node="build_claim_ledger")

        return {

            "claim_ledger": {

                "claims": [claim.model_dump(mode="json") for claim in answer.claims]

            },

            "verified_answer": answer.model_dump(mode="json"),

        }


 

    def summarize_result(self, state: AnalysisState) -> AnalysisState:

        run_id = UUID(state["run_id"])

        outcome = QueryExecutionOutcome.model_validate(state["query_outcome"])

        if outcome.result is None:

            raise AgentWorkflowError(

                code="MISSING_QUERY_RESULT",

                message="The completed query did not contain a result payload.",

            )


 

        payload = {

            "question": state["normalized_question"],

            "analysis_plan": state["analysis_plan"],

            "result": outcome.result.model_dump(mode="json"),

            "warning": (

                "This is a Phase 3 draft. No independent verifier or claim ledger has run yet."

            ),

        }

        try:

            summary = self.deps.analyst.summarize(run_id=run_id, payload=payload)

            summary = validate_draft_summary(

                summary=summary,

                columns=outcome.result.columns,

                rows=outcome.result.rows,

            )

            grounding_status = "success"

        except AgentWorkflowError as exc:

            summary = DraftSummary(

                headline="The query completed; review the result table for the measured values.",

                observations=[],

                limitations=[

                    (

                        "The automatic draft summary was omitted because it could not be "

                        "fully grounded."

                    ),

                    exc.message,

                    "Independent verification and a claim ledger are added in Phase 4.",

                ],

            )

            grounding_status = "fallback"


 

        summary_payload = summary.model_dump(mode="json")

        self.deps.audit.save_artifact(

            run_id=run_id,

            artifact_type="draft_summary",

            payload=summary_payload,

        )

        self.deps.audit.log_tool_call(

            run_id=run_id,

            graph_node="summarize_result",

            tool_name="deterministic_summary_grounding_check",

            status=grounding_status,

            input_hash=sha256_json(summary_payload),

            output_reference=f"observations={len(summary.observations)}",

            duration_ms=0,

        )

        self.deps.audit.update_run_context(run_id=run_id, current_node="summarize_result")

        return {"draft_summary": summary_payload}


 

    def finalize_success(self, state: AnalysisState) -> AnalysisState:

        run_id = UUID(state["run_id"])

        self.deps.audit.update_verification_status(

            run_id=run_id,

            verification_status="passed",

            repair_attempts=int(state.get("verification_repair_attempts", 0)),

            current_node="finalize_success",

        )

        self.deps.audit.finish_run(run_id, "completed")

        return {"status": "completed", "error_code": None, "error_message": None}


 

    def finalize_failure(self, state: AnalysisState) -> AnalysisState:

        run_id = UUID(state["run_id"])

        error_code = state.get("error_code")

        error_message = state.get("error_message")

        status = "rejected" if state.get("status") == "rejected" else "failed"


 

        if error_code is None and state.get("verification_query_outcome"):

            outcome = QueryExecutionOutcome.model_validate(state["verification_query_outcome"])

            status = "rejected" if outcome.status == "rejected" else "failed"

            error_code = outcome.error_code

            error_message = outcome.error_message

        if error_code is None and state.get("query_outcome"):

            outcome = QueryExecutionOutcome.model_validate(state["query_outcome"])

            status = "rejected" if outcome.status == "rejected" else "failed"

            error_code = outcome.error_code

            error_message = outcome.error_message


 

        error_code = error_code or "ANALYSIS_WORKFLOW_FAILED"

        error_message = error_message or "The analysis workflow failed."

        verification_status = "rejected" if status == "rejected" else "failed"

        self.deps.audit.update_verification_status(

            run_id=run_id,

            verification_status=verification_status,

            repair_attempts=int(state.get("verification_repair_attempts", 0)),

            current_node="finalize_failure",

        )

        self.deps.audit.finish_run(

            run_id,

            status,

            error_code=error_code,

            error_message=error_message,

        )

        return {

            "status": status,

            "error_code": error_code,

            "error_message": error_message,

        }


 

    def route_after_intake(self, state: AnalysisState) -> Literal["continue", "stop"]:

        return "stop" if state.get("status") == "rejected" else "continue"


 

    def route_after_terms(self, state: AnalysisState) -> Literal["clarify", "plan"]:

        resolution = TermResolution.model_validate(state["term_resolution"])

        return "clarify" if resolution.needs_clarification else "plan"


 

    def route_after_execution(

        self,

        state: AnalysisState,

    ) -> Literal["verify", "repair", "stop"]:

        outcome = QueryExecutionOutcome.model_validate(state["query_outcome"])

        if outcome.status == "completed":

            return "verify"

        if (

            outcome.status == "rejected"

            and int(state.get("repair_attempts", 0)) < self.deps.max_sql_repair_attempts

        ):

            return "repair"

        return "stop"


 

    def route_after_anomalies(self, state: AnalysisState) -> Literal["verify", "stop"]:

        report = AnomalyReport.model_validate(state["anomaly_report"])

        return "stop" if report.status == "reject" else "verify"


 

    def route_after_verifier_review(

        self, state: AnalysisState

    ) -> Literal["query", "stop"]:

        plan = VerificationPlan.model_validate(state["verification_plan"])

        return "query" if plan.decision == "verify" else "stop"


 

    def route_after_verification_candidate(

        self,

        state: AnalysisState,

    ) -> Literal["execute", "repair", "stop"]:

        if not state.get("verification_candidate_error"):

            return "execute"

        if (

            int(state.get("verification_sql_repair_attempts", 0))

            < self.deps.max_verifier_sql_repair_attempts

        ):

            return "repair"

        return "stop"


 

    def route_after_verifier_execution(

        self,

        state: AnalysisState,

    ) -> Literal["reconcile", "repair", "stop"]:

        outcome = QueryExecutionOutcome.model_validate(state["verification_query_outcome"])

        if outcome.status == "completed":

            return "reconcile"

        if (

            outcome.status == "rejected"

            and int(state.get("verification_sql_repair_attempts", 0))

            < self.deps.max_verifier_sql_repair_attempts

        ):

            return "repair"

        return "stop"


 

    def route_after_reconciliation(

        self,

        state: AnalysisState,

    ) -> Literal["claims", "repair", "stop"]:

        result = ReconciliationResult.model_validate(state["reconciliation"])

        if result.status == "pass":

            return "claims"

        if (

            result.status == "mismatch"

            and int(state.get("verification_repair_attempts", 0))

            < self.deps.max_verification_repair_attempts

        ):

            return "repair"

        return "stop"


 

    @staticmethod

    def _elapsed_ms(started: float) -> int:

        return max(0, round((perf_counter() - started) * 1000))



 

def state_time_context(state: AnalysisState):

    from app.agents.models import ResolvedTimeContext


 

    return ResolvedTimeContext.model_validate(state["time_context"])


 