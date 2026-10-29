import json

from pathlib import Path

from time import perf_counter

from typing import Any, TypeVar

from uuid import UUID

import os
from langsmith import tracing_context


 

from langchain_openai import ChatOpenAI

from pydantic import BaseModel


 

from app.agents.models import (

    AnalysisPlanOutline,

    DraftSummary,

    SQLCandidate,

    TermResolution,

)

from app.config import Settings

from app.core.errors import AgentWorkflowError

from app.core.hashing import sha256_json

from app.db.audit_repository import AuditRepository


 

T = TypeVar("T", bound=BaseModel)



 

class OpenAIAnalyst:

    PROMPT_VERSIONS = {

        "resolve_business_terms": "resolve_terms.v1",

        "create_analysis_plan": "create_plan.v1",

        "generate_sql": "generate_sql.v1",

        "repair_sql": "repair_sql.v1",

        "summarize_result": "summarize_result.v1",

    }


 

    def __init__(

        self,

        *,

        settings: Settings,

        audit_repository: AuditRepository,

    ) -> None:

        self.settings = settings

        self.audit = audit_repository

        self.model_name = settings.openai_analyst_model

        self.prompts = self._load_prompts(settings.prompts_directory)

        self.model = ChatOpenAI(

            model=settings.openai_analyst_model,

            api_key=settings.openai_api_key.get_secret_value(),

            use_responses_api=True,

            reasoning_effort=settings.openai_reasoning_effort,

            timeout=settings.openai_timeout_seconds,

            max_retries=settings.openai_max_retries,

            store=False,

        )


 

    def resolve_terms(self, *, run_id: UUID, payload: dict[str, Any]) -> TermResolution:

        return self._invoke(

            run_id=run_id,

            node_name="resolve_business_terms",

            schema=TermResolution,

            payload=payload,

        )


 

    def create_plan(

        self,

        *,

        run_id: UUID,

        payload: dict[str, Any],

    ) -> AnalysisPlanOutline:

        return self._invoke(

            run_id=run_id,

            node_name="create_analysis_plan",

            schema=AnalysisPlanOutline,

            payload=payload,

        )


 

    def generate_sql(self, *, run_id: UUID, payload: dict[str, Any]) -> SQLCandidate:

        return self._invoke(

            run_id=run_id,

            node_name="generate_sql",

            schema=SQLCandidate,

            payload=payload,

        )


 

    def repair_sql(self, *, run_id: UUID, payload: dict[str, Any]) -> SQLCandidate:

        return self._invoke(

            run_id=run_id,

            node_name="repair_sql",

            schema=SQLCandidate,

            payload=payload,

        )


 

    def summarize(self, *, run_id: UUID, payload: dict[str, Any]) -> DraftSummary:

        return self._invoke(

            run_id=run_id,

            node_name="summarize_result",

            schema=DraftSummary,

            payload=payload,

        )


 

    def _invoke(

        self,

        *,

        run_id: UUID,

        node_name: str,

        schema: type[T],

        payload: dict[str, Any],

    ) -> T:

        prompt_version = self.PROMPT_VERSIONS[node_name]

        input_hash = sha256_json(payload)

        started = perf_counter()

        print("LANGSMITH_TRACING:", os.getenv("LANGSMITH_TRACING"))
        print("LANGSMITH_PROJECT:", os.getenv("LANGSMITH_PROJECT"))
        print("LANGSMITH_API_KEY configured:", bool(os.getenv("LANGSMITH_API_KEY")))

        structured_model = self.model.with_structured_output(

            schema,

            method="json_schema",

            include_raw=True,

        )

        messages = [

            ("system", self.prompts[node_name]),

            (

                "human",

                json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),

            ),

        ]


 

        try:

            response = structured_model.invoke(

                messages,

                prompt_cache_key=f"queryguard-{prompt_version}",

            )

            if isinstance(response, dict):

                parsed = response.get("parsed")

                raw = response.get("raw")

                parsing_error = response.get("parsing_error")

            else:

                parsed = response

                raw = None

                parsing_error = None


 

            if parsing_error is not None or parsed is None:

                raise AgentWorkflowError(

                    code="MODEL_STRUCTURED_OUTPUT_FAILED",

                    message=f"The model did not return valid {schema.__name__} output.",

                )

            if not isinstance(parsed, schema):

                parsed = schema.model_validate(parsed)


 

            usage = getattr(raw, "usage_metadata", None) or {}

            duration_ms = self._elapsed_ms(started)

            output_payload = parsed.model_dump(mode="json")

            self.audit.log_model_call(

                run_id=run_id,

                graph_node=node_name,

                model_name=self.model_name,

                prompt_version=prompt_version,

                input_hash=input_hash,

                output_payload=output_payload,

                input_tokens=self._usage_value(usage, "input_tokens"),

                output_tokens=self._usage_value(usage, "output_tokens"),

                total_tokens=self._usage_value(usage, "total_tokens"),

                duration_ms=duration_ms,

                status="success",

            )

            self.audit.log_tool_call(

                run_id=run_id,

                graph_node=node_name,

                tool_name="openai_structured_output",

                status="success",

                input_hash=input_hash,

                output_reference=f"schema={schema.__name__}; prompt={prompt_version}",

                duration_ms=duration_ms,

            )

            return parsed

        except AgentWorkflowError as exc:

            self._log_failure(

                run_id=run_id,

                node_name=node_name,

                prompt_version=prompt_version,

                input_hash=input_hash,

                started=started,

                message=exc.message,

            )

            raise

        except Exception as exc:

            message = "The OpenAI model call failed. Check the API key, model, and network."

            self._log_failure(

                run_id=run_id,

                node_name=node_name,

                prompt_version=prompt_version,

                input_hash=input_hash,

                started=started,

                message=message,

            )

            raise AgentWorkflowError(

                code="OPENAI_MODEL_CALL_FAILED",

                message=message,

                retryable=True,

            ) from exc


 

    def _log_failure(

        self,

        *,

        run_id: UUID,

        node_name: str,

        prompt_version: str,

        input_hash: str,

        started: float,

        message: str,

    ) -> None:

        duration_ms = self._elapsed_ms(started)

        self.audit.log_model_call(

            run_id=run_id,

            graph_node=node_name,

            model_name=self.model_name,

            prompt_version=prompt_version,

            input_hash=input_hash,

            output_payload=None,

            input_tokens=None,

            output_tokens=None,

            total_tokens=None,

            duration_ms=duration_ms,

            status="failed",

            error_message=message,

        )

        self.audit.log_tool_call(

            run_id=run_id,

            graph_node=node_name,

            tool_name="openai_structured_output",

            status="failed",

            input_hash=input_hash,

            output_reference=f"error={message}",

            duration_ms=duration_ms,

        )


 

    @classmethod

    def _load_prompts(cls, directory: Path) -> dict[str, str]:

        mapping = {

            "resolve_business_terms": "resolve_terms.md",

            "create_analysis_plan": "create_plan.md",

            "generate_sql": "generate_sql.md",

            "repair_sql": "repair_sql.md",

            "summarize_result": "summarize_result.md",

        }

        prompts: dict[str, str] = {}

        for node_name, filename in mapping.items():

            path = directory / filename

            if not path.exists():

                raise FileNotFoundError(f"Prompt file not found: {path}")

            prompts[node_name] = path.read_text(encoding="utf-8").strip()

        return prompts


 

    @staticmethod

    def _usage_value(usage: Any, key: str) -> int | None:

        if isinstance(usage, dict):

            value = usage.get(key)

        else:

            value = getattr(usage, key, None)

        return int(value) if value is not None else None


 

    @staticmethod

    def _elapsed_ms(started: float) -> int:

        return max(0, round((perf_counter() - started) * 1000))


 