"""Business logic / DB access for jobs (AGENTS.md repo layout)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Job


def get_job(db: Session, job_id: str) -> Job | None:
    return db.get(Job, job_id)
