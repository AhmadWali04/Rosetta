"""HTTP layer only: validation, call services (AGENTS.md repo layout).

PRD F1.2/F1.4 — multipart apply form. `POST /applications` does NOT
trigger the intake graph itself: it just creates the `Application` row
with status="submitted" and returns. The worker (apps/worker) picks up
unprocessed submitted applications on its own polling cycle, keeping this
request handler fast (PRD §13's "background worker" framing).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.routes.schemas import ApplicationOut
from app.services import applications as applications_service
from app.services.applications import InvalidResumeError, JobNotFoundError

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
async def submit_application(
    job_id: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    github_url: str | None = Form(None),
    linkedin_url: str | None = Form(None),
    portfolio_url: str | None = Form(None),
    resume: UploadFile = File(...),  # noqa: B008
    db: Session = Depends(get_session),  # noqa: B008
) -> ApplicationOut:
    links = {
        k: v
        for k, v in {
            "github_url": github_url,
            "linkedin_url": linkedin_url,
            "portfolio_url": portfolio_url,
        }.items()
        if v is not None
    }

    try:
        application = await applications_service.create_application(
            db,
            job_id=job_id,
            name=name,
            email=email,
            links=links,
            resume_file=resume,
        )
    except JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidResumeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    return ApplicationOut.model_validate(application)


@router.get("", response_model=list[ApplicationOut])
async def list_applications(
    job_id: str | None = None,
    db: Session = Depends(get_session),  # noqa: B008
) -> list[ApplicationOut]:
    results = applications_service.list_applications(db, job_id=job_id)
    return [ApplicationOut.model_validate(a) for a in results]


@router.get("/{application_id}", response_model=ApplicationOut)
async def get_application(
    application_id: str,
    db: Session = Depends(get_session),  # noqa: B008
) -> ApplicationOut:
    application = applications_service.get_application(db, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="application not found")
    return ApplicationOut.model_validate(application)
