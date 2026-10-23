"""HR-only read and explicit human decision endpoints (PRD F2.1–F2.6)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.routes.hr_schemas import (
    CandidateDetail,
    EventOut,
    PipelineCandidate,
    PromotionConfirm,
    PromotionPreview,
    PromotionRequest,
    StatusChange,
)
from app.services import hr


def require_hr(x_role: Annotated[str | None, Header()] = None) -> None:
    if x_role != "hr":
        raise HTTPException(status_code=403, detail="HR role required")


router = APIRouter(tags=["hr"], dependencies=[Depends(require_hr)])
Db = Annotated[Session, Depends(get_session)]


@router.get("/hr/applications", response_model=list[PipelineCandidate])
async def pipeline(
    db: Db,
    job_id: str | None = None,
    status: str | None = None,
    sort: Literal["score_desc", "score_asc", "created_desc"] = "score_desc",
) -> list[PipelineCandidate]:
    return hr.pipeline(db, job_id=job_id, status=status, sort=sort)


@router.get("/hr/applications/{application_id}", response_model=CandidateDetail)
async def candidate(application_id: str, db: Db) -> CandidateDetail:
    return hr.detail(db, application_id)


@router.patch("/applications/{application_id}/status", response_model=PipelineCandidate)
async def label(application_id: str, body: StatusChange, db: Db) -> PipelineCandidate:
    return hr.label(db, application_id, body)


@router.get("/applications/{application_id}/events", response_model=list[EventOut])
async def events(application_id: str, db: Db) -> list[EventOut]:
    return hr.events(db, application_id)


@router.post("/pools/{job_id}/promote/preview", response_model=PromotionPreview)
async def preview(job_id: str, body: PromotionRequest, db: Db) -> PromotionPreview:
    return hr.promotion_preview(db, job_id, body.percent)


@router.post("/pools/{job_id}/promote", response_model=PromotionPreview)
async def promote(job_id: str, body: PromotionConfirm, db: Db) -> PromotionPreview:
    return hr.promote(db, job_id, body)
