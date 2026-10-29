import sys


 

import httpx


 

BASE_URL = "http://127.0.0.1:8000"



 

def main() -> int:

    with httpx.Client(base_url=BASE_URL, timeout=180) as client:

        ready = client.get("/readyz")

        ready.raise_for_status()

        print("Readiness:", ready.json()["status"])


 

        first = client.post(

            "/v1/analyses",

            json={

                "question": (

                    "Why did revenue decrease last month, and which customer segment "

                    "contributed most?"

                )

            },

        )

        first.raise_for_status()

        first_payload = first.json()

        if first_payload["status"] != "needs_clarification":

            raise AssertionError(f"Expected clarification, received: {first_payload}")


 

        run_id = first_payload["run_id"]

        choices = {

            option["choice_id"]

            for option in first_payload["clarification"]["options"]

        }

        if "net_revenue" not in choices:

            raise AssertionError(f"net_revenue was not offered: {choices}")


 

        resumed = client.post(

            f"/v1/analyses/{run_id}/clarification",

            json={"choice_id": "net_revenue"},

        )

        resumed.raise_for_status()

        final_payload = resumed.json()

        if final_payload["status"] != "completed":

            raise AssertionError(f"Analysis did not complete: {final_payload}")

        if final_payload.get("query_outcome", {}).get("status") != "completed":

            raise AssertionError("The Phase 2 query service did not complete.")


 

        audit = client.get(f"/v1/analyses/{run_id}")

        audit.raise_for_status()

        audit_payload = audit.json()

        if not audit_payload.get("model_calls"):

            raise AssertionError("No model calls were audited.")

        if not audit_payload.get("tool_calls"):

            raise AssertionError("No tool calls were audited.")


 

        print("Run ID:", run_id)

        print("Final status:", final_payload["status"])

        print("Phase 3 smoke test passed.")

        return 0



 

if __name__ == "__main__":

    try:

        raise SystemExit(main())

    except (httpx.HTTPError, AssertionError) as exc:

        print(f"Phase 3 smoke test failed: {exc}", file=sys.stderr)

        raise SystemExit(1) from exc


 