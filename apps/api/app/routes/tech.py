"""Tech-Lead-only read and decision endpoints (PRD F3.1-F3.6, M4)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.routes.hr_schemas import CandidateDetail, PipelineCandidate
from app.routes.tech_schemas import TechDecision
from app.services import tech


def require_tech_lead(x_role: Annotated[str | None, Header()] = None) -> None:
    if x_role != "tech":
        raise HTTPException(status_code=403, detail="Tech Lead role required")


router = APIRouter(tags=["tech"], dependencies=[Depends(require_tech_lead)])
Db = Annotated[Session, Depends(get_session)]


@router.get("/tech/applications", response_model=list[PipelineCandidate])
def list_queue(db: Db, job_id: str | None = None) -> list[PipelineCandidate]:
    return tech.queue(db, job_id=job_id)


@router.get("/tech/applications/{application_id}", response_model=CandidateDetail)
def get_detail(db: Db, application_id: str) -> CandidateDetail:
    return tech.detail(db, application_id)


@router.post("/tech/applications/{application_id}/decision", response_model=PipelineCandidate)
def decide(db: Db, application_id: str, body: TechDecision) -> PipelineCandidate:
    return tech.decide(db, application_id, body)
