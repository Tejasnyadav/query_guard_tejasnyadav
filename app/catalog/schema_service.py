from typing import Any


 

import psycopg

from psycopg.rows import dict_row

from psycopg_pool import ConnectionPool, PoolTimeout


 

from app.catalog.models import (

    ColumnDefinition,

    DatasetMetadata,

    SchemaSnapshot,

    TableDefinition,

)

from app.core.errors import DatabaseOperationError

from app.sql.policy import SqlPolicy



 

class SchemaCatalogService:

    """Loads schema metadata using fixed trusted SQL, never model-generated SQL."""


 

    def __init__(self, pool: ConnectionPool, policy: SqlPolicy) -> None:

        self.pool = pool

        self.policy = policy


 

    def load_snapshot(self) -> SchemaSnapshot:

        allowed_tables = sorted(self.policy.allowed_tables)

        table_names = [name.split(".", maxsplit=1)[1] for name in allowed_tables]


 

        try:

            with self.pool.connection() as connection:

                with connection.cursor(row_factory=dict_row) as cursor:

                    cursor.execute(

                        """

                        SELECT

                            dataset_name,

                            dataset_version,

                            as_of_date,

                            business_timezone,

                            reporting_currency,

                            generated_at

                        FROM analytics.dataset_metadata

                        LIMIT 1

                        """

                    )

                    metadata_row = cursor.fetchone()

                    if metadata_row is None:

                        raise DatabaseOperationError(

                            code="DATASET_METADATA_MISSING",

                            message="analytics.dataset_metadata returned no row.",

                        )


 

                    cursor.execute(

                        """

                        SELECT

                            table_schema,

                            table_name,

                            column_name,

                            data_type,

                            ordinal_position

                        FROM information_schema.columns

                        WHERE table_schema = 'analytics'

                          AND table_name = ANY(%s)

                        ORDER BY table_name, ordinal_position

                        """,

                        (table_names,),

                    )

                    rows = list(cursor.fetchall())

        except DatabaseOperationError:

            raise

        except PoolTimeout as exc:

            raise DatabaseOperationError(

                code="WAREHOUSE_POOL_TIMEOUT",

                message="No warehouse connection became available while loading the schema.",

                retryable=True,

            ) from exc

        except psycopg.Error as exc:

            primary = getattr(getattr(exc, "diag", None), "message_primary", None)

            raise DatabaseOperationError(

                code="SCHEMA_INTROSPECTION_FAILED",

                message=primary or "Could not inspect the analytics schema.",

                sqlstate=getattr(exc, "sqlstate", None),

                retryable=False,

            ) from exc


 

        grouped: dict[str, list[ColumnDefinition]] = {name: [] for name in allowed_tables}

        for row in rows:

            qualified = f"{row['table_schema']}.{row['table_name']}"

            if qualified not in grouped:

                continue

            grouped[qualified].append(

                ColumnDefinition(

                    name=str(row["column_name"]),

                    data_type=str(row["data_type"]),

                    ordinal_position=int(row["ordinal_position"]),

                )

            )


 

        missing = [table for table, columns in grouped.items() if not columns]

        if missing:

            raise DatabaseOperationError(

                code="ALLOWED_TABLE_NOT_VISIBLE",

                message=(

                    "The read-only role cannot inspect these allowed tables: "

                    + ", ".join(missing)

                ),

            )


 

        return SchemaSnapshot(

            dataset=DatasetMetadata.model_validate(dict(metadata_row)),

            tables=[

                TableDefinition(qualified_name=table, columns=columns)

                for table, columns in grouped.items()

            ],

        )


 

    @staticmethod

    def compact_for_prompt(snapshot: SchemaSnapshot) -> dict[str, Any]:

        return {

            "dataset": snapshot.dataset.model_dump(mode="json"),

            "tables": {

                table.qualified_name: [column.name for column in table.columns]

                for table in snapshot.tables

            },

        }


 