import os


 

import pytest


 

from app.config import get_settings

from app.db.pools import create_database_pools

from app.sql.executor import WarehouseExecutor

from app.sql.plan_guard import PlanGuard

from app.sql.policy import load_sql_policy

from app.sql.validator import SqlValidator


 

pytestmark = pytest.mark.integration



 

@pytest.mark.skipif(

    os.getenv("RUN_DB_TESTS") != "1",

    reason="Set RUN_DB_TESTS=1 to run tests against local PostgreSQL.",

)

def test_safe_query_can_be_planned_and_executed() -> None:

    get_settings.cache_clear()

    settings = get_settings()

    policy = load_sql_policy(settings.sql_policy_path)

    pools = create_database_pools(settings)


 

    try:

        validator = SqlValidator(policy)

        executor = WarehouseExecutor(pools.warehouse, policy)

        guard = PlanGuard(policy)


 

        validation = validator.validate(

            """

            SELECT order_month, customer_segment, net_revenue

            FROM analytics.revenue_monthly_by_segment

            ORDER BY order_month, customer_segment

            """

        )

        assert validation.accepted is True

        assert validation.executable_sql is not None


 

        payload, _ = executor.explain(validation.executable_sql)

        plan = guard.evaluate(payload)

        assert plan.accepted is True


 

        result = executor.execute(validation.executable_sql)

        assert result.returned_row_count > 0

        assert result.returned_row_count <= policy.max_result_rows

    finally:

        pools.close()


 