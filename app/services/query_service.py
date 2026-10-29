from time import perf_counter


 

from app.core.errors import DatabaseOperationError

from app.core.hashing import sha256_json, sha256_text

from app.db.audit_repository import AuditRepository

from app.schemas.query import ExecuteSqlRequest, QueryExecutionOutcome

from app.sql.executor import WarehouseExecutor

from app.sql.models import SqlValidationResult, ValidationIssue

from app.sql.plan_guard import PlanGuard

from app.sql.validator import SqlValidator



 

class QueryService:

    def __init__(

        self,

        *,

        validator: SqlValidator,

        plan_guard: PlanGuard,

        executor: WarehouseExecutor,

        audit_repository: AuditRepository,

    ) -> None:

        self.validator = validator

        self.plan_guard = plan_guard

        self.executor = executor

        self.audit = audit_repository


 

    def execute(self, request: ExecuteSqlRequest) -> QueryExecutionOutcome:

        run_id = self.audit.create_run(request.question)

        return self._execute_for_run(

            run_id=run_id,

            request=request,

            manage_run_lifecycle=True,

        )


 

    def execute_for_run(

        self,

        *,

        run_id,

        request: ExecuteSqlRequest,

    ) -> QueryExecutionOutcome:

        """Execute under an existing analysis run created by the LangGraph workflow."""

        return self._execute_for_run(

            run_id=run_id,

            request=request,

            manage_run_lifecycle=False,

        )


 

    def _execute_for_run(

        self,

        *,

        run_id,

        request: ExecuteSqlRequest,

        manage_run_lifecycle: bool,

    ) -> QueryExecutionOutcome:

        validation_started = perf_counter()

        validation = self.validator.validate(request.sql)

        validation = self._apply_request_contract(validation, request)

        validation_duration_ms = self._elapsed_ms(validation_started)

        sql_for_hash = validation.normalized_sql or request.sql.strip()


 

        query_id = self.audit.create_query_execution(

            run_id=run_id,

            purpose=request.purpose,

            original_sql=request.sql,

            normalized_sql=validation.normalized_sql,

            executable_sql=validation.executable_sql,

            sql_hash=sha256_text(sql_for_hash),

            validation_status="accepted" if validation.accepted else "rejected",

            execution_status="awaiting_plan" if validation.accepted else "validation_rejected",

            tables_used=validation.tables,

            functions_used=validation.functions,

        )

        self.audit.log_tool_call(

            run_id=run_id,

            sequence_number=None,

            graph_node="validate_sql",

            tool_name="deterministic_sql_validator",

            status="success" if validation.accepted else "rejected",

            input_hash=sha256_json({"sql": request.sql}),

            output_reference=(

                f"query_id={query_id}; accepted={validation.accepted}; "

                f"issues={','.join(issue.code for issue in validation.issues) or 'none'}"

            ),

            duration_ms=validation_duration_ms,

        )


 

        if not validation.accepted or validation.executable_sql is None:

            issue_codes = [issue.code for issue in validation.issues if issue.severity == "error"]

            error_message = self._validation_error_message(validation)

            self.audit.finish_query(

                query_id=query_id,

                execution_status="validation_rejected",

                row_count=None,

                duration_ms=None,

                truncated=None,

                error_code=issue_codes[0] if issue_codes else "SQL_VALIDATION_REJECTED",

                error_message=error_message,

            )

            self._finish_run_if_managed(run_id, "rejected", manage_run_lifecycle)

            return QueryExecutionOutcome(

                status="rejected",

                run_id=run_id,

                query_id=query_id,

                validation=validation,

                error_code=issue_codes[0] if issue_codes else "SQL_VALIDATION_REJECTED",

                error_message=error_message,

            )


 

        plan_started = perf_counter()

        try:

            explain_payload, explain_duration_ms = self.executor.explain(validation.executable_sql)

            plan = self.plan_guard.evaluate(explain_payload)

        except DatabaseOperationError as exc:

            duration_ms = self._elapsed_ms(plan_started)

            self.audit.log_tool_call(

                run_id=run_id,

                sequence_number=None,

                graph_node="estimate_query_cost",

                tool_name="postgres_explain",

                status="failed",

                input_hash=sha256_text(validation.executable_sql),

                output_reference=f"error_code={exc.code}; sqlstate={exc.sqlstate or 'none'}",

                duration_ms=duration_ms,

            )

            run_status = "failed" if exc.retryable else "rejected"

            self.audit.finish_query(

                query_id=query_id,

                execution_status="planning_failed",

                row_count=None,

                duration_ms=duration_ms,

                truncated=None,

                error_code=exc.code,

                error_message=exc.message,

            )

            self._finish_run_if_managed(run_id, run_status, manage_run_lifecycle)

            return QueryExecutionOutcome(

                status=run_status,

                run_id=run_id,

                query_id=query_id,

                validation=validation,

                error_code=exc.code,

                error_message=exc.message,

            )

        except ValueError:

            duration_ms = self._elapsed_ms(plan_started)

            error_message = "QueryGuard could not understand the PostgreSQL EXPLAIN result."

            self.audit.log_tool_call(

                run_id=run_id,

                sequence_number=None,

                graph_node="estimate_query_cost",

                tool_name="postgres_explain",

                status="failed",

                input_hash=sha256_text(validation.executable_sql),

                output_reference="error_code=INVALID_EXPLAIN_RESULT",

                duration_ms=duration_ms,

            )

            self.audit.finish_query(

                query_id=query_id,

                execution_status="planning_failed",

                row_count=None,

                duration_ms=duration_ms,

                truncated=None,

                error_code="INVALID_EXPLAIN_RESULT",

                error_message=error_message,

            )

            self._finish_run_if_managed(run_id, "failed", manage_run_lifecycle)

            return QueryExecutionOutcome(

                status="failed",

                run_id=run_id,

                query_id=query_id,

                validation=validation,

                error_code="INVALID_EXPLAIN_RESULT",

                error_message=error_message,

            )


 

        plan_dump = plan.model_dump(mode="json")

        self.audit.log_tool_call(

            run_id=run_id,

            sequence_number=None,

            graph_node="estimate_query_cost",

            tool_name="postgres_explain",

            status="success" if plan.accepted else "rejected",

            input_hash=sha256_text(validation.executable_sql),

            output_reference=(

                f"query_id={query_id}; total_cost={plan.total_cost}; "

                f"max_node_rows={plan.max_node_rows}; accepted={plan.accepted}"

            ),

            duration_ms=explain_duration_ms,

        )

        self.audit.update_plan(

            query_id=query_id,

            plan_summary=plan_dump,

            execution_status="ready_to_execute" if plan.accepted else "cost_rejected",

            error_code=None if plan.accepted else "QUERY_COST_REJECTED",

            error_message=None if plan.accepted else "; ".join(plan.rejection_reasons),

        )


 

        if not plan.accepted:

            error_message = "; ".join(plan.rejection_reasons)

            self._finish_run_if_managed(run_id, "rejected", manage_run_lifecycle)

            return QueryExecutionOutcome(

                status="rejected",

                run_id=run_id,

                query_id=query_id,

                validation=validation,

                plan=plan,

                error_code="QUERY_COST_REJECTED",

                error_message=error_message,

            )


 

        execution_started = perf_counter()

        try:

            result = self.executor.execute(validation.executable_sql)

        except DatabaseOperationError as exc:

            duration_ms = self._elapsed_ms(execution_started)

            self.audit.log_tool_call(

                run_id=run_id,

                sequence_number=None,

                graph_node="execute_sql",

                tool_name="warehouse_query",

                status="failed",

                input_hash=sha256_text(validation.executable_sql),

                output_reference=f"error_code={exc.code}; sqlstate={exc.sqlstate or 'none'}",

                duration_ms=duration_ms,

            )

            run_status = "failed" if exc.retryable else "rejected"

            self.audit.finish_query(

                query_id=query_id,

                execution_status="execution_failed",

                row_count=None,

                duration_ms=duration_ms,

                truncated=None,

                error_code=exc.code,

                error_message=exc.message,

            )

            self._finish_run_if_managed(run_id, run_status, manage_run_lifecycle)

            return QueryExecutionOutcome(

                status=run_status,

                run_id=run_id,

                query_id=query_id,

                validation=validation,

                plan=plan,

                error_code=exc.code,

                error_message=exc.message,

            )


 

        self.audit.save_result_preview(

            query_id=query_id,

            columns=result.columns,

            rows=result.rows,

            returned_row_count=result.returned_row_count,

            truncated=result.truncated,

        )


 

        if request.expected_columns is not None and result.columns != request.expected_columns:

            error_message = (

                "The query result columns did not match the Analyst's validated contract. "

                f"Expected {request.expected_columns}; received {result.columns}."

            )

            self.audit.finish_query(

                query_id=query_id,

                execution_status="result_schema_rejected",

                row_count=result.returned_row_count,

                duration_ms=result.duration_ms,

                truncated=result.truncated,

                error_code="RESULT_SCHEMA_MISMATCH",

                error_message=error_message,

            )

            self.audit.log_tool_call(

                run_id=run_id,

                sequence_number=None,

                graph_node="execute_sql",

                tool_name="warehouse_query",

                status="rejected",

                input_hash=sha256_text(validation.executable_sql),

                output_reference=(

                    f"query_id={query_id}; error_code=RESULT_SCHEMA_MISMATCH"

                ),

                duration_ms=result.duration_ms,

            )

            self._finish_run_if_managed(run_id, "rejected", manage_run_lifecycle)

            return QueryExecutionOutcome(

                status="rejected",

                run_id=run_id,

                query_id=query_id,

                validation=validation,

                plan=plan,

                error_code="RESULT_SCHEMA_MISMATCH",

                error_message=error_message,

            )


 

        self.audit.finish_query(

            query_id=query_id,

            execution_status="completed",

            row_count=result.returned_row_count,

            duration_ms=result.duration_ms,

            truncated=result.truncated,

        )

        self.audit.log_tool_call(

            run_id=run_id,

            sequence_number=None,

            graph_node="execute_sql",

            tool_name="warehouse_query",

            status="success",

            input_hash=sha256_text(validation.executable_sql),

            output_reference=(

                f"query_id={query_id}; rows={result.returned_row_count}; "

                f"truncated={result.truncated}"

            ),

            duration_ms=result.duration_ms,

        )

        self._finish_run_if_managed(run_id, "completed", manage_run_lifecycle)


 

        return QueryExecutionOutcome(

            status="completed",

            run_id=run_id,

            query_id=query_id,

            validation=validation,

            plan=plan,

            result=result,

        )


 

    @staticmethod

    def _apply_request_contract(

        validation: SqlValidationResult,

        request: ExecuteSqlRequest,

    ) -> SqlValidationResult:

        if not validation.accepted or request.expected_tables is None:

            return validation


 

        expected_tables = set(request.expected_tables)

        actual_tables = set(validation.tables)

        if actual_tables == expected_tables:

            return validation


 

        issue = ValidationIssue(

            code="SQL_TABLE_CONTRACT_MISMATCH",

            message=(

                "The SQL referenced a different table set than the Analyst declared. "

                f"Expected {sorted(expected_tables)}; received {sorted(actual_tables)}."

            ),

        )

        return validation.model_copy(

            update={

                "accepted": False,

                "executable_sql": None,

                "issues": [*validation.issues, issue],

            }

        )


 

    def _finish_run_if_managed(

        self,

        run_id,

        status: str,

        manage_run_lifecycle: bool,

    ) -> None:

        if manage_run_lifecycle:

            self.audit.finish_run(run_id, status)


 

    @staticmethod

    def _validation_error_message(validation) -> str:

        messages = [issue.message for issue in validation.issues if issue.severity == "error"]

        return " ".join(messages) or "The SQL validation policy rejected the query."


 

    @staticmethod

    def _elapsed_ms(started: float) -> int:

        return max(0, round((perf_counter() - started) * 1000))


 