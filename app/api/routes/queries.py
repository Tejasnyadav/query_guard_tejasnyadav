from typing import Annotated, Any

from uuid import UUID


 

from fastapi import APIRouter, Depends, HTTPException, Request


 

from app.api.dependencies import get_audit_repository, get_query_service, get_sql_validator

from app.db.audit_repository import AuditRepository

from app.schemas.query import ExecuteSqlRequest, QueryExecutionOutcome, ValidateSqlRequest

from app.services.query_service import QueryService

from app.sql.models import SqlValidationResult

from app.sql.validator import SqlValidator


 

router = APIRouter(prefix="/v1", tags=["queries"])



 

@router.post("/queries/validate", response_model=SqlValidationResult)

def validate_query(

    request: ValidateSqlRequest,

    validator: Annotated[SqlValidator, Depends(get_sql_validator)],

) -> SqlValidationResult:

    return validator.validate(request.sql)



 

@router.post("/queries/execute", response_model=QueryExecutionOutcome)

def execute_query(

    payload: ExecuteSqlRequest,

    http_request: Request,

    service: Annotated[QueryService, Depends(get_query_service)],

) -> QueryExecutionOutcome:

    if not http_request.app.state.settings.enable_query_execution_api:

        raise HTTPException(status_code=403, detail="The query execution API is disabled.")

    return service.execute(payload)



 

@router.get("/runs/{run_id}")

def get_run(

    run_id: UUID,

    repository: Annotated[AuditRepository, Depends(get_audit_repository)],

) -> dict[str, Any]:

    run = repository.get_run(run_id)

    if run is None:

        raise HTTPException(status_code=404, detail="Run not found.")

    return run



 

@router.get("/queries/{query_id}")

def get_query(

    query_id: UUID,

    repository: Annotated[AuditRepository, Depends(get_audit_repository)],

) -> dict[str, Any]:

    query = repository.get_query(query_id)

    if query is None:

        raise HTTPException(status_code=404, detail="Query not found.")

    return query


 