from collections.abc import AsyncIterator

from contextlib import asynccontextmanager


 

from fastapi import FastAPI, Request

from fastapi.responses import JSONResponse


 

from app.api.routes.health import router as health_router

from app.api.routes.queries import router as query_router

from app.config import get_settings

from app.core.errors import AuditStorageError

from app.db.audit_repository import AuditRepository

from app.db.pools import create_database_pools

from app.services.query_service import QueryService

from app.sql.executor import WarehouseExecutor

from app.sql.plan_guard import PlanGuard

from app.sql.policy import load_sql_policy

from app.sql.validator import SqlValidator



 

@asynccontextmanager

async def lifespan(app: FastAPI) -> AsyncIterator[None]:

    settings = get_settings()

    policy = load_sql_policy(settings.sql_policy_path)

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


 

    app.state.settings = settings

    app.state.sql_policy = policy

    app.state.database_pools = pools

    app.state.sql_validator = validator

    app.state.plan_guard = plan_guard

    app.state.warehouse_executor = executor

    app.state.audit_repository = audit_repository

    app.state.query_service = query_service


 

    try:

        yield

    finally:

        pools.close()



 

app = FastAPI(

    title="QueryGuard",

    version="0.2.0",

    description="Phase 2 deterministic SQL validation and read-only execution service.",

    lifespan=lifespan,

)

app.include_router(health_router)

app.include_router(query_router)



 

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

                "QueryGuard could not save the mandatory audit record. "

                "No result was returned."

            )

        },

    )


 