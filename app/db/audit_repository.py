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


 

    def create_run(self, question: str) -> UUID:

        sql = """

            INSERT INTO queryguard.analysis_runs (question, status)

            VALUES (%s, 'running')

            RETURNING run_id

        """

        row = self._fetch_one(sql, (question,))

        return row["run_id"]


 

    def finish_run(self, run_id: UUID, status: str) -> None:

        completed_at: datetime | None = (

            datetime.now().astimezone() if status in {"completed", "rejected", "failed"} else None

        )

        self._execute(

            """

                UPDATE queryguard.analysis_runs

                SET status = %s,

                    completed_at = %s

                WHERE run_id = %s

            """,

            (status, completed_at, run_id),

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

            (

                Jsonb(plan_summary),

                execution_status,

                error_code,

                error_message,

                query_id,

            ),

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

            (

                query_id,

                Jsonb(columns),

                Jsonb(rows),

                returned_row_count,

                truncated,

            ),

        )


 

    def log_tool_call(

        self,

        *,

        run_id: UUID,

        sequence_number: int,

        graph_node: str,

        tool_name: str,

        status: str,

        input_hash: str | None,

        output_reference: str | None,

        duration_ms: int | None,

    ) -> None:

        self._execute(

            """

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


 

    def get_run(self, run_id: UUID) -> dict[str, Any] | None:

        run = self._fetch_optional(

            """

                SELECT run_id, question, status, selected_metric_ids, assumptions,

                       created_at, completed_at

                FROM queryguard.analysis_runs

                WHERE run_id = %s

            """,

            (run_id,),

        )

        if run is None:

            return None


 

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


 