from datetime import date, datetime, time

from decimal import Decimal

from time import perf_counter

from typing import Any

from uuid import UUID


 

import psycopg

from psycopg_pool import ConnectionPool, PoolTimeout


 

from app.core.errors import DatabaseOperationError

from app.sql.models import QueryResult

from app.sql.policy import SqlPolicy



 

class WarehouseExecutor:

    def __init__(self, pool: ConnectionPool, policy: SqlPolicy) -> None:

        self.pool = pool

        self.policy = policy


 

    def explain(self, sql: str) -> tuple[Any, int]:

        started = perf_counter()

        try:

            with self.pool.connection() as connection:

                try:

                    with connection.cursor() as cursor:

                        self._begin_read_only(cursor)

                        cursor.execute(

                            "EXPLAIN (FORMAT JSON, COSTS TRUE, VERBOSE FALSE, SETTINGS FALSE) "

                            + sql

                        )

                        row = cursor.fetchone()

                        if row is None:

                            raise DatabaseOperationError(

                                code="EMPTY_EXPLAIN_RESULT",

                                message="PostgreSQL returned no EXPLAIN result.",

                            )

                        payload = row[0]

                finally:

                    connection.rollback()

        except DatabaseOperationError:

            raise

        except PoolTimeout as exc:

            raise DatabaseOperationError(

                code="WAREHOUSE_POOL_TIMEOUT",

                message="No warehouse database connection became available.",

                retryable=True,

            ) from exc

        except psycopg.Error as exc:

            raise self._translate_database_error(exc, operation="planning") from exc


 

        duration_ms = max(0, round((perf_counter() - started) * 1000))

        return payload, duration_ms


 

    def execute(self, sql: str) -> QueryResult:

        started = perf_counter()

        try:

            with self.pool.connection() as connection:

                try:

                    with connection.cursor() as cursor:

                        self._begin_read_only(cursor)

                        cursor.execute(sql)


 

                        if cursor.description is None:

                            raise DatabaseOperationError(

                                code="QUERY_RETURNED_NO_COLUMNS",

                                message="The validated query did not return a result set.",

                            )


 

                        columns = [column.name for column in cursor.description]

                        if len(columns) != len(set(columns)):

                            raise DatabaseOperationError(

                                code="DUPLICATE_OUTPUT_COLUMNS",

                                message=(

                                    "The query returned duplicate column names. Add unique aliases "

                                    "to every output column."

                                ),

                            )


 

                        fetch_limit = self.policy.max_result_rows + self.policy.fetch_probe_rows

                        records = cursor.fetchmany(fetch_limit)

                finally:

                    connection.rollback()

        except DatabaseOperationError:

            raise

        except PoolTimeout as exc:

            raise DatabaseOperationError(

                code="WAREHOUSE_POOL_TIMEOUT",

                message="No warehouse database connection became available.",

                retryable=True,

            ) from exc

        except psycopg.Error as exc:

            raise self._translate_database_error(exc, operation="execution") from exc


 

        truncated = len(records) > self.policy.max_result_rows

        visible_records = records[: self.policy.max_result_rows]

        rows = [

            {

                column: self._json_safe(value)

                for column, value in zip(columns, record, strict=True)

            }

            for record in visible_records

        ]

        duration_ms = max(0, round((perf_counter() - started) * 1000))


 

        return QueryResult(

            columns=columns,

            rows=rows,

            returned_row_count=len(rows),

            truncated=truncated,

            duration_ms=duration_ms,

        )


 

    def check_identity(self) -> dict[str, str]:

        try:

            with self.pool.connection() as connection:

                with connection.cursor() as cursor:

                    cursor.execute(

                        """

                        SELECT

                            current_database(),

                            current_user,

                            current_setting('default_transaction_read_only'),

                            roles.rolsuper,

                            roles.rolcreatedb,

                            roles.rolcreaterole

                        FROM pg_catalog.pg_roles AS roles

                        WHERE roles.rolname = current_user

                        """

                    )

                    row = cursor.fetchone()

                    if row is None:

                        raise DatabaseOperationError(

                            code="WAREHOUSE_IDENTITY_NOT_FOUND",

                            message="Could not verify the warehouse database role.",

                        )

                    (

                        database,

                        user,

                        default_read_only,

                        is_superuser,

                        can_create_db,

                        can_create_role,

                    ) = row

            return {

                "database": str(database),

                "user": str(user),

                "default_transaction_read_only": str(default_read_only),

                "is_superuser": str(bool(is_superuser)).lower(),

                "can_create_database": str(bool(can_create_db)).lower(),

                "can_create_role": str(bool(can_create_role)).lower(),

            }

        except (PoolTimeout, psycopg.Error) as exc:

            raise DatabaseOperationError(

                code="WAREHOUSE_HEALTH_CHECK_FAILED",

                message="Warehouse database health check failed.",

                retryable=True,

            ) from exc


 

    def _begin_read_only(self, cursor: psycopg.Cursor[Any]) -> None:

        cursor.execute("BEGIN READ ONLY")

        cursor.execute(

            "SELECT set_config('statement_timeout', %s, true)",

            (f"{self.policy.statement_timeout_ms}ms",),

        )

        cursor.execute(

            "SELECT set_config('lock_timeout', %s, true)",

            (f"{self.policy.lock_timeout_ms}ms",),

        )

        cursor.execute("SET LOCAL search_path = analytics, pg_catalog")


 

    @staticmethod

    def _translate_database_error(

        exc: psycopg.Error,

        *,

        operation: str,

    ) -> DatabaseOperationError:

        sqlstate = getattr(exc, "sqlstate", None)

        primary = getattr(getattr(exc, "diag", None), "message_primary", None)


 

        if sqlstate == "57014":

            return DatabaseOperationError(

                code="QUERY_TIMEOUT",

                message=f"The query exceeded the configured timeout during {operation}.",

                sqlstate=sqlstate,

                retryable=False,

            )


 

        if sqlstate in {"42P01", "42703", "42883", "42601", "42P10"}:

            return DatabaseOperationError(

                code="DATABASE_REJECTED_SQL",

                message=primary or f"PostgreSQL rejected the SQL during {operation}.",

                sqlstate=sqlstate,

                retryable=False,

            )


 

        if sqlstate == "42501":

            return DatabaseOperationError(

                code="DATABASE_PERMISSION_DENIED",

                message="The read-only database role denied the requested operation.",

                sqlstate=sqlstate,

                retryable=False,

            )


 

        return DatabaseOperationError(

            code="WAREHOUSE_DATABASE_ERROR",

            message=primary or f"The warehouse database failed during {operation}.",

            sqlstate=sqlstate,

            retryable=sqlstate is not None and sqlstate.startswith("08"),

        )


 

    @classmethod

    def _json_safe(cls, value: Any) -> Any:

        if value is None or isinstance(value, (str, int, float, bool)):

            return value

        if isinstance(value, Decimal):

            # Preserve exact money values rather than converting them to binary floating point.

            return str(value)

        if isinstance(value, (datetime, date, time)):

            return value.isoformat()

        if isinstance(value, UUID):

            return str(value)

        if isinstance(value, memoryview):

            return value.tobytes().hex()

        if isinstance(value, bytes):

            return value.hex()

        if isinstance(value, dict):

            return {str(key): cls._json_safe(item) for key, item in value.items()}

        if isinstance(value, (list, tuple)):

            return [cls._json_safe(item) for item in value]

        return str(value)


 