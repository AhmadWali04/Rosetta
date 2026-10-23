"""Tech Lead portal service (M4, F3.1-F3.6). Queue of `valid` candidates,
the same evidence-linked profile view HR already has (reused directly,
read-only functions are role-agnostic), rubric grading persisted as a
`Review` row, and the terminal invite/decline decision.

Reuses `app.services.hr`'s private `_record_label`/`_application`/`_row`
helpers rather than duplicating the override-detection and audit-event
logic — a deliberate, time-boxed shortcut (see PROGRESS.md) rather than
promoting them to a shared module under demo-deadline pressure.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import Review
from app.routes.hr_schemas import CandidateDetail, PipelineCandidate
from app.routes.tech_schemas import TechDecision
from app.services import hr


def queue(db: Session, *, job_id: str | None = None) -> list[PipelineCandidate]:
    return hr.pipeline(db, job_id=job_id, status="valid")


def detail(db: Session, application_id: str) -> CandidateDetail:
    return hr.detail(db, application_id)


def decide(db: Session, application_id: str, body: TechDecision) -> PipelineCandidate:
    application = hr._application(db, application_id, lock=True)
    if application.status != "valid":
        raise HTTPException(status_code=409, detail="candidate is not in the tech-review queue")

    if body.rubric or body.overall is not None or body.comment:
        db.add(
            Review(
                application_id=application_id,
                reviewer_role="tech_lead",
                rubric={item.requirement_id: item.score for item in body.rubric},
                overall=body.overall or 0.0,
                comments=[body.comment] if body.comment else [],
            )
        )

    hr._record_label(
        db,
        application,
        body.decision,
        body.comment,
        action="tech_lead_decision",
    )
    db.commit()
    return hr._row(application)
