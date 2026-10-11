from pathlib import Path


 

import pytest


 

from app.sql.policy import load_sql_policy

from app.sql.validator import SqlValidator



 

@pytest.fixture(scope="module")

def validator() -> SqlValidator:

    policy = load_sql_policy(Path("config/sql_policy.yml"))

    return SqlValidator(policy)



 

def issue_codes(result) -> set[str]:

    return {issue.code for issue in result.issues}



 

def test_accepts_safe_aggregate_query_and_injects_limit(validator: SqlValidator) -> None:

    result = validator.validate(

        """

        SELECT

            order_month,

            ROUND(SUM(net_revenue), 2) AS net_revenue

        FROM analytics.order_line_facts

        WHERE order_status = 'completed'

        GROUP BY order_month

        ORDER BY order_month

        """

    )


 

    assert result.accepted is True

    assert result.executable_sql is not None

    assert "LIMIT 501" in result.executable_sql.upper()

    assert result.tables == ["analytics.order_line_facts"]

    assert {"ROUND", "SUM"}.issubset(set(result.functions))

    assert "ROW_LIMIT_INJECTED" in issue_codes(result)



 

def test_allows_count_star_but_not_select_star(validator: SqlValidator) -> None:

    count_result = validator.validate(

        "SELECT COUNT(*) AS row_count FROM analytics.order_line_facts"

    )

    star_result = validator.validate("SELECT * FROM analytics.order_line_facts")


 

    assert count_result.accepted is True

    assert star_result.accepted is False

    assert "SELECT_STAR_NOT_ALLOWED" in issue_codes(star_result)



 

def test_accepts_cte_reference_without_schema(validator: SqlValidator) -> None:

    result = validator.validate(

        """

        WITH monthly AS (

            SELECT order_month, SUM(net_revenue) AS revenue

            FROM analytics.order_line_facts

            WHERE order_status = 'completed'

            GROUP BY order_month

        )

        SELECT order_month, revenue

        FROM monthly

        ORDER BY order_month

        """

    )


 

    assert result.accepted is True

    assert result.tables == ["analytics.order_line_facts"]



 

def test_rejects_multiple_statements(validator: SqlValidator) -> None:

    result = validator.validate(

        "SELECT order_id FROM analytics.order_summary; DROP TABLE raw.orders;"

    )


 

    assert result.accepted is False

    assert "SINGLE_STATEMENT_REQUIRED" in issue_codes(result)



 

def test_rejects_raw_schema(validator: SqlValidator) -> None:

    result = validator.validate("SELECT email FROM raw.customers")


 

    assert result.accepted is False

    assert "SCHEMA_NOT_ALLOWED" in issue_codes(result)

    assert "PII_COLUMN_DENIED" in issue_codes(result)



 

def test_requires_schema_qualification(validator: SqlValidator) -> None:

    result = validator.validate("SELECT order_id FROM order_summary")


 

    assert result.accepted is False

    assert "SCHEMA_QUALIFICATION_REQUIRED" in issue_codes(result)



 

def test_rejects_cross_join(validator: SqlValidator) -> None:

    result = validator.validate(

        """

        SELECT a.order_id, b.order_item_id

        FROM analytics.order_summary AS a

        CROSS JOIN analytics.order_line_facts AS b

        """

    )


 

    assert result.accepted is False

    assert "CROSS_JOIN_NOT_ALLOWED" in issue_codes(result)



 

def test_rejects_join_without_condition(validator: SqlValidator) -> None:

    result = validator.validate(

        """

        SELECT a.order_id, b.order_item_id

        FROM analytics.order_summary AS a

        JOIN analytics.order_line_facts AS b

        """

    )


 

    assert result.accepted is False

    assert "JOIN_CONDITION_REQUIRED" in issue_codes(result)



 

def test_rejects_recursive_cte(validator: SqlValidator) -> None:

    result = validator.validate(

        """

        WITH RECURSIVE numbers(n) AS (

            SELECT 1

            UNION ALL

            SELECT n + 1 FROM numbers WHERE n < 10

        )

        SELECT n FROM numbers

        """

    )


 

    assert result.accepted is False

    assert "RECURSIVE_CTE_NOT_ALLOWED" in issue_codes(result)



 

def test_rejects_dangerous_function(validator: SqlValidator) -> None:

    result = validator.validate(

        "SELECT PG_SLEEP(1) AS slept FROM analytics.dataset_metadata"

    )


 

    assert result.accepted is False

    assert "FUNCTION_DENIED" in issue_codes(result)



 

def test_clamps_large_limit(validator: SqlValidator) -> None:

    result = validator.validate(

        "SELECT order_id FROM analytics.order_summary ORDER BY order_id LIMIT 5000"

    )


 

    assert result.accepted is True

    assert result.requested_limit == 5000

    assert result.enforced_limit == 501

    assert "LIMIT 501" in (result.executable_sql or "").upper()

    assert "ROW_LIMIT_CLAMPED" in issue_codes(result)



 

def test_rejects_non_literal_limit(validator: SqlValidator) -> None:

    result = validator.validate(

        "SELECT order_id FROM analytics.order_summary LIMIT (SELECT 10)"

    )


 

    assert result.accepted is False

    assert "NON_LITERAL_LIMIT" in issue_codes(result)



 

def test_rejects_row_lock_clause(validator: SqlValidator) -> None:

    result = validator.validate(

        "SELECT order_id FROM analytics.order_summary FOR UPDATE"

    )


 

    assert result.accepted is False

    assert "BLOCKED_SQL_OPERATION" in issue_codes(result)


 