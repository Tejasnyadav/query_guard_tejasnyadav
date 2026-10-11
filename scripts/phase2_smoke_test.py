import json

import sys

from urllib.error import HTTPError, URLError

from urllib.request import Request, urlopen



 

BASE_URL = "http://127.0.0.1:8000"



 

def post_json(path: str, payload: dict) -> dict:

    request = Request(

        BASE_URL + path,

        data=json.dumps(payload).encode("utf-8"),

        headers={"Content-Type": "application/json"},

        method="POST",

    )

    with urlopen(request, timeout=15) as response:

        return json.loads(response.read().decode("utf-8"))



 

def main() -> int:

    try:

        safe = post_json(

            "/v1/queries/execute",

            {

                "question": "What was monthly net revenue?",

                "purpose": "Return completed-order net revenue by month.",

                "sql": """

                    SELECT

                        order_month,

                        ROUND(SUM(net_revenue), 2) AS net_revenue

                    FROM analytics.order_line_facts

                    WHERE order_status = 'completed'

                    GROUP BY order_month

                    ORDER BY order_month

                """,

            },

        )

        print("Safe query status:", safe["status"])

        print("Run ID:", safe["run_id"])

        print("Query ID:", safe["query_id"])

        print("Rows:", safe.get("result", {}).get("returned_row_count"))

        if safe["status"] != "completed":

            print(json.dumps(safe, indent=2))

            return 1


 

        unsafe = post_json(

            "/v1/queries/execute",

            {

                "question": "Delete all orders",

                "purpose": "Security test",

                "sql": "DELETE FROM raw.orders",

            },

        )

        print("Unsafe query status:", unsafe["status"])

        print("Unsafe query error:", unsafe.get("error_code"))

        if unsafe["status"] != "rejected":

            print(json.dumps(unsafe, indent=2))

            return 1


 

    except (HTTPError, URLError, TimeoutError) as exc:

        print(f"Smoke test could not call QueryGuard: {exc}", file=sys.stderr)

        return 1


 

    print("Phase 2 smoke test passed.")

    return 0



 

if __name__ == "__main__":

    raise SystemExit(main())


 