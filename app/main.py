from collections.abc import AsyncIterator

from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()


 

from fastapi import FastAPI, Request

from fastapi.responses import JSONResponse

from langgraph.checkpoint.postgres import PostgresSaver


 

from app.agents.openai_analyst import OpenAIAnalyst

from app.api.routes.analyses import router as analysis_router

from app.api.routes.health import router as health_router

from app.api.routes.queries import router as query_router

from app.catalog.loader import load_semantic_catalog

from app.catalog.schema_service import SchemaCatalogService

from app.config import get_settings

from app.core.errors import AgentWorkflowError, AuditStorageError

from app.db.audit_repository import AuditRepository

from app.db.pools import create_database_pools

from app.graph.builder import build_analysis_graph

from app.graph.nodes.analysis_nodes import AnalysisNodeDependencies

from app.services.analysis_service import AnalysisService

from app.services.query_service import QueryService

from app.sql.executor import WarehouseExecutor

from app.sql.plan_guard import PlanGuard

from app.sql.policy import load_sql_policy

from app.sql.validator import SqlValidator



 

@asynccontextmanager

async def lifespan(app: FastAPI) -> AsyncIterator[None]:

    settings = get_settings()

    policy = load_sql_policy(settings.sql_policy_path)

    semantic_catalog = load_semantic_catalog(

        metrics_path=settings.metrics_catalog_path,

        dimensions_path=settings.dimensions_catalog_path,

        business_terms_path=settings.business_terms_path,

    )

    pools = create_database_pools(settings)


 

    validator = SqlValidator(policy)

    plan_guard = PlanGuard(policy)

    executor = WarehouseExecutor(pools.warehouse, policy)

    audit_repository = AuditRepository(pools.app)

    query_service = QueryService(

        validator=validator,

        plan_guard=plan_guard,

        executor=executor,

        audit_repository=audit_repository,

    )

    schema_service = SchemaCatalogService(pools.warehouse, policy)

    analyst = OpenAIAnalyst(settings=settings, audit_repository=audit_repository)


 

    checkpoint_context = PostgresSaver.from_conn_string(settings.checkpoint_database_url)

    checkpointer = checkpoint_context.__enter__()

    try:

        checkpointer.setup()

        graph = build_analysis_graph(

            dependencies=AnalysisNodeDependencies(

                semantic_catalog=semantic_catalog,

                schema_service=schema_service,

                analyst=analyst,

                query_service=query_service,

                audit=audit_repository,

                sql_policy=policy,

                max_sql_repair_attempts=settings.max_sql_repair_attempts,

            ),

            checkpointer=checkpointer,

        )

        analysis_service = AnalysisService(

            graph=graph,

            audit_repository=audit_repository,

        )


 

        app.state.settings = settings

        app.state.sql_policy = policy

        app.state.semantic_catalog = semantic_catalog

        app.state.database_pools = pools

        app.state.sql_validator = validator

        app.state.plan_guard = plan_guard

        app.state.warehouse_executor = executor

        app.state.audit_repository = audit_repository

        app.state.query_service = query_service

        app.state.schema_service = schema_service

        app.state.openai_analyst = analyst

        app.state.analysis_graph = graph

        app.state.analysis_service = analysis_service

        app.state.langgraph_checkpointer = checkpointer


 

        yield

    finally:

        checkpoint_context.__exit__(None, None, None)

        pools.close()



 

app = FastAPI(

    title="QueryGuard",

    version="0.3.0",

    description=(

        "Phase 3 LangGraph Analyst workflow using structured OpenAI outputs and the "

        "Phase 2 deterministic SQL safety service."

    ),

    lifespan=lifespan,

)

app.include_router(health_router)

app.include_router(query_router)

app.include_router(analysis_router)



 

@app.exception_handler(AuditStorageError)

def audit_storage_error_handler(

    request: Request,

    exc: AuditStorageError,

) -> JSONResponse:

    del request, exc

    return JSONResponse(

        status_code=503,

        content={

            "detail": (

                "QueryGuard could not save the mandatory audit record. No result was returned."

            )

        },

    )



 

@app.exception_handler(AgentWorkflowError)

def agent_workflow_error_handler(

    request: Request,

    exc: AgentWorkflowError,

) -> JSONResponse:

    del request

    return JSONResponse(

        status_code=503 if exc.retryable else 422,

        content={"detail": {"code": exc.code, "message": exc.message}},

    )


 