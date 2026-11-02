import os


 

import psycopg

import pytest


 

from app.config import get_settings



 

pytestmark = pytest.mark.integration



 

@pytest.mark.skipif(

    os.getenv("RUN_DB_TESTS") != "1",

    reason="Set RUN_DB_TESTS=1 to run local PostgreSQL integration tests.",

)

def test_phase4_app_migration_is_present() -> None:

    get_settings.cache_clear()

    settings = get_settings()


 

    with psycopg.connect(settings.app_database_url) as connection:

        with connection.cursor() as cursor:

            cursor.execute(

                """

                SELECT table_name

                FROM information_schema.tables

                WHERE table_schema = 'queryguard'

                  AND table_name IN ('verifier_reviews', 'reconciliation_results')

                ORDER BY table_name

                """

            )

            tables = [row[0] for row in cursor.fetchall()]

            assert tables == ["reconciliation_results", "verifier_reviews"]


 

            cursor.execute(

                """

                SELECT column_name

                FROM information_schema.columns

                WHERE table_schema = 'queryguard'

                  AND table_name = 'analysis_runs'

                  AND column_name IN (

                      'verification_status',

                      'verification_repair_attempts'

                  )

                ORDER BY column_name

                """

            )

            run_columns = {row[0] for row in cursor.fetchall()}

            assert run_columns == {

                "verification_repair_attempts",

                "verification_status",

            }


 

            cursor.execute(

                """

                SELECT column_name

                FROM information_schema.columns

                WHERE table_schema = 'queryguard'

                  AND table_name = 'query_executions'

                  AND column_name IN ('query_role', 'parent_query_id', 'candidate_key')

                """

            )

            query_columns = {row[0] for row in cursor.fetchall()}

            assert query_columns == {"query_role", "parent_query_id", "candidate_key"}


 