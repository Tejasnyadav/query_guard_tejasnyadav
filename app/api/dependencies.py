from fastapi import Request


 

from app.db.audit_repository import AuditRepository

from app.services.analysis_service import AnalysisService

from app.services.query_service import QueryService

from app.sql.executor import WarehouseExecutor

from app.sql.validator import SqlValidator



 

def get_query_service(request: Request) -> QueryService:

    return request.app.state.query_service



 

def get_analysis_service(request: Request) -> AnalysisService:

    return request.app.state.analysis_service



 

def get_sql_validator(request: Request) -> SqlValidator:

    return request.app.state.sql_validator



 

def get_audit_repository(request: Request) -> AuditRepository:

    return request.app.state.audit_repository



 

def get_warehouse_executor(request: Request) -> WarehouseExecutor:

    return request.app.state.warehouse_executor


 