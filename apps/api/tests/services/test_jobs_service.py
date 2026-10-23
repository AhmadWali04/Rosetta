"""Service-layer tests for app.services.jobs."""

from __future__ import annotations

from app.services.jobs import get_job

SEED_JOB_ID = "job-ai-intern-procogia"


def test_get_job_returns_seeded_job(db_session):
    job = get_job(db_session, SEED_JOB_ID)
    assert job is not None
    assert job.id == SEED_JOB_ID


def test_get_job_missing_returns_none(db_session):
    assert get_job(db_session, "nope") is None
