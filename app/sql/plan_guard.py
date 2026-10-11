import json

from typing import Any


 

from app.sql.models import PlanSummary

from app.sql.policy import SqlPolicy



 

class PlanGuard:

    def __init__(self, policy: SqlPolicy) -> None:

        self.policy = policy


 

    def evaluate(self, payload: Any) -> PlanSummary:

        document = self._normalize_payload(payload)

        root_plan = document.get("Plan")

        if not isinstance(root_plan, dict):

            raise ValueError("PostgreSQL EXPLAIN output did not contain a Plan object.")


 

        nodes = list(self._walk_plan(root_plan))

        total_cost = float(root_plan.get("Total Cost", 0.0))

        top_plan_rows = int(root_plan.get("Plan Rows", 0) or 0)

        max_node_rows = max((int(node.get("Plan Rows", 0) or 0) for node in nodes), default=0)

        plan_width = int(root_plan.get("Plan Width", 0) or 0)


 

        sequential_scan_count = sum(

            1 for node in nodes if str(node.get("Node Type", "")) == "Seq Scan"

        )

        nested_loop_count = sum(

            1 for node in nodes if str(node.get("Node Type", "")) == "Nested Loop"

        )

        sort_count = sum(1 for node in nodes if "Sort" in str(node.get("Node Type", "")))

        relations = sorted(

            {

                str(node["Relation Name"])

                for node in nodes

                if node.get("Relation Name") is not None

            }

        )


 

        rejection_reasons: list[str] = []

        warnings: list[str] = []


 

        if total_cost > self.policy.max_plan_cost:

            rejection_reasons.append(

                f"Planner cost {total_cost:.2f} exceeds limit {self.policy.max_plan_cost:.2f}."

            )

        elif total_cost >= self.policy.max_plan_cost * self.policy.warn_plan_cost_ratio:

            warnings.append(

                f"Planner cost {total_cost:.2f} is close to the configured limit."

            )


 

        if max_node_rows > self.policy.max_plan_rows:

            rejection_reasons.append(

                f"A plan node estimates {max_node_rows} rows, above limit "

                f"{self.policy.max_plan_rows}."

            )


 

        if sequential_scan_count:

            warnings.append(

                f"Plan contains {sequential_scan_count} sequential scan(s); review indexes if slow."

            )


 

        if nested_loop_count >= 3:

            warnings.append(

                f"Plan contains {nested_loop_count} nested-loop join node(s)."

            )


 

        return PlanSummary(

            accepted=not rejection_reasons,

            total_cost=total_cost,

            top_plan_rows=top_plan_rows,

            max_node_rows=max_node_rows,

            plan_width=plan_width,

            node_count=len(nodes),

            sequential_scan_count=sequential_scan_count,

            nested_loop_count=nested_loop_count,

            sort_count=sort_count,

            relations=relations,

            warnings=warnings,

            rejection_reasons=rejection_reasons,

        )


 

    @staticmethod

    def _normalize_payload(payload: Any) -> dict[str, Any]:

        if isinstance(payload, str):

            payload = json.loads(payload)


 

        if isinstance(payload, list):

            if not payload:

                raise ValueError("PostgreSQL returned an empty EXPLAIN document.")

            payload = payload[0]


 

        if not isinstance(payload, dict):

            raise ValueError("PostgreSQL returned an unexpected EXPLAIN format.")

        return payload


 

    @classmethod

    def _walk_plan(cls, node: dict[str, Any]):

        yield node

        for child in node.get("Plans", []) or []:

            if isinstance(child, dict):

                yield from cls._walk_plan(child)


 