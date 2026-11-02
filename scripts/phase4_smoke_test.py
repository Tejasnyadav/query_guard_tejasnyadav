import sys


 

import httpx



 

BASE_URL = "http://127.0.0.1:8000"



 

def main() -> int:

    with httpx.Client(base_url=BASE_URL, timeout=180) as client:

        ready = client.get("/readyz")

        ready.raise_for_status()

        if ready.json().get("status") != "ready":

            raise RuntimeError(f"QueryGuard is not ready: {ready.text}")


 

        response = client.post(

            "/v1/analyses",

            json={

                "question": (

                    "What was net revenue in August 2026 compared with July 2026, "

                    "and which customer segment had the largest decline?"

                )

            },

        )

        response.raise_for_status()

        payload = response.json()


 

        if payload.get("status") == "needs_clarification":

            run_id = payload["run_id"]

            response = client.post(

                f"/v1/analyses/{run_id}/clarification",

                json={"choice_id": "net_revenue"},

            )

            response.raise_for_status()

            payload = response.json()


 

        if payload.get("status") != "completed":

            raise RuntimeError(f"Analysis did not complete: {payload}")

        if payload.get("reconciliation", {}).get("status") != "pass":

            raise RuntimeError(f"Reconciliation did not pass: {payload}")

        claims = payload.get("verified_answer", {}).get("claims", [])

        if not claims:

            raise RuntimeError("No verified claims were returned.")


 

        run_id = payload["run_id"]

        stored = client.get(f"/v1/analyses/{run_id}")

        stored.raise_for_status()

        stored_payload = stored.json()

        if not stored_payload.get("verifier_reviews"):

            raise RuntimeError("No verifier review was stored.")

        if not stored_payload.get("reconciliations"):

            raise RuntimeError("No reconciliation was stored.")

        if not stored_payload.get("claims"):

            raise RuntimeError("No claim ledger was stored.")


 

        first_claim_id = claims[0]["claim_id"]

        claim_response = client.get(f"/v1/claims/{first_claim_id}")

        claim_response.raise_for_status()

        sources = claim_response.json().get("sources", [])

        if len(sources) < 2:

            raise RuntimeError("The claim is not linked to both Analyst and Verifier queries.")


 

    print("Phase 4 smoke test passed.")

    return 0



 

if __name__ == "__main__":

    try:

        raise SystemExit(main())

    except Exception as exc:

        print(f"Phase 4 smoke test failed: {exc}", file=sys.stderr)

        raise


 