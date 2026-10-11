from pathlib import Path


 

from app.sql.plan_guard import PlanGuard

from app.sql.policy import load_sql_policy



 

def test_accepts_small_plan() -> None:

    policy = load_sql_policy(Path("config/sql_policy.yml"))

    guard = PlanGuard(policy)

    payload = [

        {

            "Plan": {

                "Node Type": "Aggregate",

                "Total Cost": 1200.25,

                "Plan Rows": 12,

                "Plan Width": 24,

                "Plans": [

                    {

                        "Node Type": "Seq Scan",

                        "Relation Name": "order_line_facts",

                        "Total Cost": 1000.0,

                        "Plan Rows": 52074,

                        "Plan Width": 64,

                    }

                ],

            }

        }

    ]


 

    result = guard.evaluate(payload)


 

    assert result.accepted is True

    assert result.total_cost == 1200.25

    assert result.max_node_rows == 52074

    assert result.sequential_scan_count == 1

    assert result.relations == ["order_line_facts"]



 

def test_rejects_expensive_plan() -> None:

    policy = load_sql_policy(Path("config/sql_policy.yml"))

    guard = PlanGuard(policy)

    payload = [

        {

            "Plan": {

                "Node Type": "Nested Loop",

                "Total Cost": policy.max_plan_cost + 1,

                "Plan Rows": 10,

                "Plan Width": 24,

                "Plans": [],

            }

        }

    ]


 

    result = guard.evaluate(payload)


 

    assert result.accepted is False

    assert result.rejection_reasons


 