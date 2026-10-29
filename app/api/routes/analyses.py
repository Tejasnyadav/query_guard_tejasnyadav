from typing import Annotated, Any

from uuid import UUID


 

from fastapi import APIRouter, Depends, HTTPException, Request


 

from app.api.dependencies import get_analysis_service, get_audit_repository

from app.db.audit_repository import AuditRepository

from app.schemas.analysis import (

    AnalysisOutcome,

    ClarificationAnswerRequest,

    CreateAnalysisRequest,

)

from app.services.analysis_service import AnalysisService


 

router = APIRouter(prefix="/v1", tags=["analyses"])



 

@router.post("/analyses", response_model=AnalysisOutcome)

def create_analysis(

    payload: CreateAnalysisRequest,

    http_request: Request,

    service: Annotated[AnalysisService, Depends(get_analysis_service)],

) -> AnalysisOutcome:

    if not http_request.app.state.settings.enable_analysis_api:

        raise HTTPException(status_code=403, detail="The analysis API is disabled.")

    return service.start(payload.question)



 

@router.post("/analyses/{run_id}/clarification", response_model=AnalysisOutcome)

def answer_clarification(

    run_id: UUID,

    payload: ClarificationAnswerRequest,

    http_request: Request,

    service: Annotated[AnalysisService, Depends(get_analysis_service)],

) -> AnalysisOutcome:

    if not http_request.app.state.settings.enable_analysis_api:

        raise HTTPException(status_code=403, detail="The analysis API is disabled.")

    return service.resume(run_id=run_id, choice_id=payload.choice_id)



 

@router.get("/analyses/{run_id}")

def get_analysis(

    run_id: UUID,

    repository: Annotated[AuditRepository, Depends(get_audit_repository)],

) -> dict[str, Any]:

    run = repository.get_run(run_id)

    if run is None:

        raise HTTPException(status_code=404, detail="Analysis run not found.")

    return run


 