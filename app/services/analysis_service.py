from typing import Any

from uuid import UUID, uuid4


 

from langgraph.types import Command


 

from app.core.errors import AgentWorkflowError

from app.db.audit_repository import AuditRepository

from app.schemas.analysis import AnalysisOutcome, ClarificationPrompt



 

class AnalysisService:

    def __init__(self, *, graph: Any, audit_repository: AuditRepository) -> None:

        self.graph = graph

        self.audit = audit_repository


 

    def start(self, question: str) -> AnalysisOutcome:

        thread_id = str(uuid4())

        run_id = self.audit.create_run(question, thread_id=thread_id)

        state = {

            "run_id": str(run_id),

            "thread_id": thread_id,

            "question": question,

            "status": "running",

            "repair_attempts": 0,

            "error_code": None,

            "error_message": None,

        }

        return self._invoke_and_build(

            run_id=run_id,

            thread_id=thread_id,

            graph_input=state,

        )


 

    def resume(self, *, run_id: UUID, choice_id: str) -> AnalysisOutcome:

        thread_id = self.audit.get_thread_id(run_id)

        if thread_id is None:

            return AnalysisOutcome(

                status="failed",

                run_id=run_id,

                thread_id="",

                error_code="ANALYSIS_RUN_NOT_FOUND",

                error_message="The analysis run does not exist.",

            )


 

        pending = self.audit.get_pending_clarification(run_id)

        if pending is None:

            return AnalysisOutcome(

                status="rejected",

                run_id=run_id,

                thread_id=thread_id,

                error_code="NO_PENDING_CLARIFICATION",

                error_message="This analysis run is not waiting for clarification.",

            )


 

        allowed = {

            str(option.get("choice_id"))

            for option in pending.get("options", [])

            if option.get("choice_id") is not None

        }

        if choice_id not in allowed:

            return AnalysisOutcome(

                status="rejected",

                run_id=run_id,

                thread_id=thread_id,

                clarification=ClarificationPrompt(

                    question=str(pending["question"]),

                    options=list(pending.get("options", [])),

                ),

                error_code="INVALID_CLARIFICATION_CHOICE",

                error_message="Choose one of the offered choice_id values.",

            )


 

        return self._invoke_and_build(

            run_id=run_id,

            thread_id=thread_id,

            graph_input=Command(resume={"choice_id": choice_id}),

        )


 

    def _invoke_and_build(

        self,

        *,

        run_id: UUID,

        thread_id: str,

        graph_input: Any,

    ) -> AnalysisOutcome:

        config = {"configurable": {"thread_id": thread_id}}

        try:

            result = self.graph.invoke(graph_input, config=config)

        except AgentWorkflowError as exc:

            self.audit.finish_run(

                run_id,

                "failed",

                error_code=exc.code,

                error_message=exc.message,

            )

            return AnalysisOutcome(

                status="failed",

                run_id=run_id,

                thread_id=thread_id,

                error_code=exc.code,

                error_message=exc.message,

            )

        except Exception:

            message = "The analysis workflow stopped unexpectedly. Check the server logs."

            self.audit.finish_run(

                run_id,

                "failed",

                error_code="ANALYSIS_WORKFLOW_EXCEPTION",

                error_message=message,

            )

            return AnalysisOutcome(

                status="failed",

                run_id=run_id,

                thread_id=thread_id,

                error_code="ANALYSIS_WORKFLOW_EXCEPTION",

                error_message=message,

            )


 

        interrupts = result.get("__interrupt__", []) if isinstance(result, dict) else []

        if interrupts:

            value = interrupts[0].value

            return AnalysisOutcome(

                status="needs_clarification",

                run_id=run_id,

                thread_id=thread_id,

                normalized_question=result.get("normalized_question"),

                clarification=ClarificationPrompt(

                    question=str(value.get("question", "Clarification required")),

                    options=list(value.get("options", [])),

                ),

                term_resolution=result.get("term_resolution"),

            )


 

        return AnalysisOutcome(

            status=result.get("status", "failed"),

            run_id=run_id,

            thread_id=thread_id,

            normalized_question=result.get("normalized_question"),

            term_resolution=result.get("term_resolution"),

            analysis_plan=result.get("analysis_plan"),

            sql_candidate=result.get("sql_candidate"),

            query_outcome=result.get("query_outcome"),

            draft_summary=result.get("draft_summary"),

            error_code=result.get("error_code"),

            error_message=result.get("error_message"),

        )


 