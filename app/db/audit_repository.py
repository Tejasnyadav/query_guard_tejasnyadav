from datetime import datetime

from typing import Any

from uuid import UUID


 

import psycopg

from psycopg.rows import dict_row

from psycopg.types.json import Jsonb

from psycopg_pool import ConnectionPool, PoolTimeout


 

from app.core.errors import AuditStorageError



 

class AuditRepository:

    def __init__(self, pool: ConnectionPool) -> None:

        self.pool = pool


 

    def create_run(self, question: str, thread_id: str | None = None) -> UUID:

        sql = """

            INSERT INTO queryguard.analysis_runs (question, status, thread_id)

            VALUES (%s, 'running', %s)

            RETURNING run_id

        """

        row = self._fetch_one(sql, (question, thread_id))

        return row["run_id"]


 

    def update_run_context(

        self,

        *,

        run_id: UUID,

        normalized_question: str | None = None,

        selected_metric_ids: list[str] | None = None,

        selected_dimension_ids: list[str] | None = None,

        assumptions: list[str] | None = None,

        current_node: str | None = None,

    ) -> None:

        self._execute(

            """

                UPDATE queryguard.analysis_runs

                SET normalized_question = COALESCE(%s, normalized_question),

                    selected_metric_ids = COALESCE(%s, selected_metric_ids),

                    selected_dimension_ids = COALESCE(%s, selected_dimension_ids),

                    assumptions = COALESCE(%s, assumptions),

                    current_node = COALESCE(%s, current_node)

                WHERE run_id = %s

            """,

            (

                normalized_question,

                Jsonb(selected_metric_ids) if selected_metric_ids is not None else None,

                Jsonb(selected_dimension_ids) if selected_dimension_ids is not None else None,

                Jsonb(assumptions) if assumptions is not None else None,

                current_node,

                run_id,

            ),

        )


 

    def set_run_status(self, run_id: UUID, status: str, current_node: str | None = None) -> None:

        self._execute(

            """

                UPDATE queryguard.analysis_runs

                SET status = %s,

                    current_node = COALESCE(%s, current_node),

                    completed_at = NULL

                WHERE run_id = %s

            """,

            (status, current_node, run_id),

        )


 

    def finish_run(

        self,

        run_id: UUID,

        status: str,

        *,

        error_code: str | None = None,

        error_message: str | None = None,

    ) -> None:

        completed_at: datetime | None = (

            datetime.now().astimezone() if status in {"completed", "rejected", "failed"} else None

        )

        self._execute(

            """

                UPDATE queryguard.analysis_runs

                SET status = %s,

                    completed_at = %s,

                    error_code = %s,

                    error_message = %s

                WHERE run_id = %s

            """,

            (status, completed_at, error_code, error_message, run_id),

        )


 

    def create_query_execution(

        self,

        *,

        run_id: UUID,

        purpose: str,

        original_sql: str,

        normalized_sql: str | None,

        executable_sql: str | None,

        sql_hash: str,

        validation_status: str,

        execution_status: str,

        tables_used: list[str],

        functions_used: list[str],

    ) -> UUID:

        row = self._fetch_one(

            """

                INSERT INTO queryguard.query_executions (

                    run_id,

                    purpose,

                    sql_text,

                    normalized_sql,

                    executable_sql,

                    sql_hash,

                    validation_status,

                    execution_status,

                    tables_used,

                    functions_used

                )

                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)

                RETURNING query_id

            """,

            (

                run_id,

                purpose,

                original_sql,

                normalized_sql,

                executable_sql,

                sql_hash,

                validation_status,

                execution_status,

                Jsonb(tables_used),

                Jsonb(functions_used),

            ),

        )

        return row["query_id"]


 

    def update_plan(

        self,

        *,

        query_id: UUID,

        plan_summary: dict[str, Any],

        execution_status: str,

        error_code: str | None = None,

        error_message: str | None = None,

    ) -> None:

        self._execute(

            """

                UPDATE queryguard.query_executions

                SET plan_summary = %s,

                    execution_status = %s,

                    error_code = %s,

                    error_message = %s

                WHERE query_id = %s

            """,

            (Jsonb(plan_summary), execution_status, error_code, error_message, query_id),

        )


 

    def finish_query(

        self,

        *,

        query_id: UUID,

        execution_status: str,

        row_count: int | None,

        duration_ms: int | None,

        truncated: bool | None,

        error_code: str | None = None,

        error_message: str | None = None,

    ) -> None:

        self._execute(

            """

                UPDATE queryguard.query_executions

                SET execution_status = %s,

                    row_count = %s,

                    duration_ms = %s,

                    truncated = %s,

                    error_code = %s,

                    error_message = %s

                WHERE query_id = %s

            """,

            (

                execution_status,

                row_count,

                duration_ms,

                truncated,

                error_code,

                error_message,

                query_id,

            ),

        )


 

    def save_result_preview(

        self,

        *,

        query_id: UUID,

        columns: list[str],

        rows: list[dict[str, Any]],

        returned_row_count: int,

        truncated: bool,

    ) -> None:

        self._execute(

            """

                INSERT INTO queryguard.query_result_previews (

                    query_id,

                    columns,

                    rows,

                    returned_row_count,

                    truncated

                )

                VALUES (%s, %s, %s, %s, %s)

                ON CONFLICT (query_id) DO UPDATE

                SET columns = EXCLUDED.columns,

                    rows = EXCLUDED.rows,

                    returned_row_count = EXCLUDED.returned_row_count,

                    truncated = EXCLUDED.truncated

            """,

            (query_id, Jsonb(columns), Jsonb(rows), returned_row_count, truncated),

        )


 

    def log_tool_call(

        self,

        *,

        run_id: UUID,

        graph_node: str,

        tool_name: str,

        status: str,

        input_hash: str | None,

        output_reference: str | None,

        duration_ms: int | None,

        sequence_number: int | None = None,

    ) -> None:

        if sequence_number is None:

            self._execute(

                """

                    WITH acquired_lock AS (

                        SELECT pg_advisory_xact_lock(hashtext(%s))

                    ),

                    next_sequence AS (

                        SELECT COALESCE(MAX(sequence_number), 0) + 1 AS value

                        FROM queryguard.tool_calls

                        WHERE run_id = %s

                    )

                    INSERT INTO queryguard.tool_calls (

                        run_id,

                        sequence_number,

                        graph_node,

                        tool_name,

                        status,

                        input_hash,

                        output_reference,

                        duration_ms

                    )

                    SELECT %s, next_sequence.value, %s, %s, %s, %s, %s, %s

                    FROM next_sequence, acquired_lock

                """,

                (

                    str(run_id),

                    run_id,

                    run_id,

                    graph_node,

                    tool_name,

                    status,

                    input_hash,

                    output_reference,

                    duration_ms,

                ),

            )

            return


 

        self._execute(

            """

                INSERT INTO queryguard.tool_calls (

                    run_id, sequence_number, graph_node, tool_name, status,

                    input_hash, output_reference, duration_ms

                )

                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)

            """,

            (

                run_id,

                sequence_number,

                graph_node,

                tool_name,

                status,

                input_hash,

                output_reference,

                duration_ms,

            ),

        )


 

    def log_model_call(

        self,

        *,

        run_id: UUID,

        graph_node: str,

        model_name: str,

        prompt_version: str,

        input_hash: str,

        output_payload: dict[str, Any] | None,

        input_tokens: int | None,

        output_tokens: int | None,

        total_tokens: int | None,

        duration_ms: int | None,

        status: str,

        error_message: str | None = None,

    ) -> None:

        self._execute(

            """

                INSERT INTO queryguard.model_calls (

                    run_id, graph_node, model_name, prompt_version, input_hash,

                    output_payload, input_tokens, output_tokens, total_tokens,

                    duration_ms, status, error_message

                )

                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)

            """,

            (

                run_id,

                graph_node,

                model_name,

                prompt_version,

                input_hash,

                Jsonb(output_payload) if output_payload is not None else None,

                input_tokens,

                output_tokens,

                total_tokens,

                duration_ms,

                status,

                error_message,

            ),

        )


 

    def save_artifact(

        self,

        *,

        run_id: UUID,

        artifact_type: str,

        payload: dict[str, Any],

        artifact_version: int = 1,

    ) -> None:

        self._execute(

            """

                INSERT INTO queryguard.analysis_artifacts (

                    run_id, artifact_type, artifact_version, payload

                )

                VALUES (%s, %s, %s, %s)

                ON CONFLICT (run_id, artifact_type, artifact_version) DO UPDATE

                SET payload = EXCLUDED.payload,

                    created_at = now()

            """,

            (run_id, artifact_type, artifact_version, Jsonb(payload)),

        )


 

    def upsert_clarification(

        self,

        *,

        run_id: UUID,

        question: str,

        options: list[dict[str, Any]],

    ) -> None:

        self._execute(

            """

                INSERT INTO queryguard.clarifications (

                    run_id, question, options, status

                )

                VALUES (%s, %s, %s, 'pending')

                ON CONFLICT (run_id) DO UPDATE

                SET question = EXCLUDED.question,

                    options = EXCLUDED.options,

                    selected_choice_id = NULL,

                    status = 'pending',

                    answered_at = NULL

            """,

            (run_id, question, Jsonb(options)),

        )


 

    def answer_clarification(self, *, run_id: UUID, choice_id: str) -> None:

        self._execute(

            """

                UPDATE queryguard.clarifications

                SET selected_choice_id = %s,

                    status = 'answered',

                    answered_at = now()

                WHERE run_id = %s

            """,

            (choice_id, run_id),

        )


 

    def get_pending_clarification(self, run_id: UUID) -> dict[str, Any] | None:

        return self._fetch_optional(

            """

                SELECT clarification_id, run_id, question, options, status, created_at

                FROM queryguard.clarifications

                WHERE run_id = %s AND status = 'pending'

            """,

            (run_id,),

        )


 

    def get_thread_id(self, run_id: UUID) -> str | None:

        row = self._fetch_optional(

            "SELECT thread_id FROM queryguard.analysis_runs WHERE run_id = %s",

            (run_id,),

        )

        if row is None:

            return None

        value = row.get("thread_id")

        return str(value) if value is not None else None


 

    def get_run(self, run_id: UUID) -> dict[str, Any] | None:

        run = self._fetch_optional(

            """

                SELECT run_id, thread_id, question, normalized_question, status,

                       selected_metric_ids, selected_dimension_ids, assumptions,

                       current_node, error_code, error_message, created_at, completed_at

                FROM queryguard.analysis_runs

                WHERE run_id = %s

            """,

            (run_id,),

        )

        if run is None:

            return None


 

        run["clarification"] = self._fetch_optional(

            """

                SELECT clarification_id, question, options, selected_choice_id,

                       status, created_at, answered_at

                FROM queryguard.clarifications

                WHERE run_id = %s

            """,

            (run_id,),

        )

        run["artifacts"] = self._fetch_all(

            """

                SELECT artifact_id, artifact_type, artifact_version, payload, created_at

                FROM queryguard.analysis_artifacts

                WHERE run_id = %s

                ORDER BY created_at

            """,

            (run_id,),

        )

        run["model_calls"] = self._fetch_all(

            """

                SELECT model_call_id, graph_node, model_name, prompt_version,

                       input_hash, input_tokens, output_tokens, total_tokens,

                       duration_ms, status, error_message, created_at

                FROM queryguard.model_calls

                WHERE run_id = %s

                ORDER BY created_at

            """,

            (run_id,),

        )

        run["tool_calls"] = self._fetch_all(

            """

                SELECT tool_call_id, sequence_number, graph_node, tool_name, status,

                       input_hash, output_reference, duration_ms, created_at

                FROM queryguard.tool_calls

                WHERE run_id = %s

                ORDER BY sequence_number

            """,

            (run_id,),

        )

        run["queries"] = self._fetch_all(

            """

                SELECT query_id, purpose, sql_hash, validation_status, execution_status,

                       row_count, duration_ms, truncated, tables_used, functions_used,

                       plan_summary, error_code, error_message, created_at

                FROM queryguard.query_executions

                WHERE run_id = %s

                ORDER BY created_at

            """,

            (run_id,),

        )

        return run


 

    def get_query(self, query_id: UUID) -> dict[str, Any] | None:

        query = self._fetch_optional(

            """

                SELECT query_id, run_id, purpose, sql_text, normalized_sql, executable_sql,

                       sql_hash, validation_status, execution_status, row_count, duration_ms,

                       truncated, tables_used, functions_used, plan_summary,

                       error_code, error_message, created_at

                FROM queryguard.query_executions

                WHERE query_id = %s

            """,

            (query_id,),

        )

        if query is None:

            return None


 

        query["result_preview"] = self._fetch_optional(

            """

                SELECT columns, rows, returned_row_count, truncated, created_at

                FROM queryguard.query_result_previews

                WHERE query_id = %s

            """,

            (query_id,),

        )

        return query


 

    def check_connection(self) -> dict[str, str]:

        row = self._fetch_one(

            """

            SELECT

                current_database() AS database,

                current_user AS user,

                roles.rolsuper AS is_superuser,

                roles.rolcreatedb AS can_create_database,

                roles.rolcreaterole AS can_create_role

            FROM pg_catalog.pg_roles AS roles

            WHERE roles.rolname = current_user

            """

        )

        return {

            "database": str(row["database"]),

            "user": str(row["user"]),

            "is_superuser": str(bool(row["is_superuser"])).lower(),

            "can_create_database": str(bool(row["can_create_database"])).lower(),

            "can_create_role": str(bool(row["can_create_role"])).lower(),

        }


 

    def _execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> None:

        try:

            with self.pool.connection() as connection:

                connection.execute(sql, parameters)

        except (PoolTimeout, psycopg.Error) as exc:

            raise AuditStorageError("Could not write QueryGuard audit data.") from exc


 

    def _fetch_one(self, sql: str, parameters: tuple[Any, ...] = ()) -> dict[str, Any]:

        row = self._fetch_optional(sql, parameters)

        if row is None:

            raise AuditStorageError("Audit query returned no row.")

        return row


 

    def _fetch_optional(

        self,

        sql: str,

        parameters: tuple[Any, ...] = (),

    ) -> dict[str, Any] | None:

        try:

            with self.pool.connection() as connection:

                with connection.cursor(row_factory=dict_row) as cursor:

                    cursor.execute(sql, parameters)

                    return cursor.fetchone()

        except (PoolTimeout, psycopg.Error) as exc:

            raise AuditStorageError("Could not read QueryGuard audit data.") from exc


 

    def _fetch_all(

        self,

        sql: str,

        parameters: tuple[Any, ...] = (),

    ) -> list[dict[str, Any]]:

        try:

            with self.pool.connection() as connection:

                with connection.cursor(row_factory=dict_row) as cursor:

                    cursor.execute(sql, parameters)

                    return list(cursor.fetchall())

        except (PoolTimeout, psycopg.Error) as exc:

            raise AuditStorageError("Could not read QueryGuard audit data.") from exc


 