"""HTTP layer only: validation, call services (AGENTS.md repo layout).

The seeded job's fixed id is "job-ai-intern-procogia" (apps/api/scripts/
seed.py, M0) — the Applicant portal frontend fetches this exact id.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.routes.schemas import JobOut
from app.services.jobs import get_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobOut)
async def get_job_route(job_id: str, db: Session = Depends(get_session)) -> JobOut:  # noqa: B008
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return JobOut.model_validate(job)
