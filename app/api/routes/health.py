from typing import Annotated, Any


 

from fastapi import APIRouter, Depends, HTTPException, Request


 

from app.api.dependencies import get_audit_repository, get_warehouse_executor

from app.core.errors import AuditStorageError, DatabaseOperationError

from app.db.audit_repository import AuditRepository

from app.sql.executor import WarehouseExecutor


 

router = APIRouter(tags=["health"])



 

@router.get("/healthz")

def healthz() -> dict[str, str]:

    return {"status": "ok"}



 

@router.get("/readyz")

def readyz(

    request: Request,

    executor: Annotated[WarehouseExecutor, Depends(get_warehouse_executor)],

    repository: Annotated[AuditRepository, Depends(get_audit_repository)],

) -> dict[str, Any]:

    try:

        warehouse = executor.check_identity()

        app_database = repository.check_connection()

    except (DatabaseOperationError, AuditStorageError) as exc:

        raise HTTPException(status_code=503, detail="Database readiness check failed.") from exc


 

    settings = request.app.state.settings

    if warehouse["user"] != settings.warehouse_expected_user:

        raise HTTPException(

            status_code=503,

            detail="Warehouse is connected with the wrong PostgreSQL role.",

        )

    if app_database["user"] != settings.app_expected_user:

        raise HTTPException(

            status_code=503,

            detail="App database is connected with the wrong PostgreSQL role.",

        )

    if warehouse["default_transaction_read_only"].lower() != "on":

        raise HTTPException(

            status_code=503,

            detail="Warehouse credential is not read-only by default.",

        )

    if warehouse["is_superuser"] == "true" or app_database["is_superuser"] == "true":

        raise HTTPException(

            status_code=503,

            detail="QueryGuard must not use a PostgreSQL superuser credential.",

        )


 

    return {

        "status": "ready",

        "warehouse": warehouse,

        "app_database": app_database,

    }


 