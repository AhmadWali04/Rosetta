"""Service-layer tests for app.services.applications (no HTTP layer
needed — AGENTS.md repo layout: services/ own business logic + DB
access)."""

from __future__ import annotations

import io

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.db.models import Event
from app.services.applications import (
    InvalidResumeError,
    JobNotFoundError,
    create_application,
    get_application,
    list_applications,
)

SEED_JOB_ID = "job-ai-intern-procogia"


def _upload_file(content: bytes, filename: str, content_type: str) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


async def test_create_application_success(db_session, settings_with_tmp_dir):
    application = await create_application(
        db_session,
        job_id=SEED_JOB_ID,
        name="Jordan Applicant",
        email="jordan@example.com",
        links={"github_url": "https://github.com/jordan"},
        resume_file=_upload_file(b"%PDF-1.4 fake resume bytes", "resume.pdf", "application/pdf"),
    )

    assert application.status == "submitted"
    assert application.vector_status == "pending"
    assert application.resume_path.endswith("resume.pdf")

    events = db_session.query(Event).filter_by(application_id=application.id).all()
    assert len(events) == 1
    assert events[0].action == "application_submitted"
    assert events[0].actor == "applicant"
    assert events[0].payload == {
        "job_id": SEED_JOB_ID,
        "name": "Jordan Applicant",
        "email": "jordan@example.com",
    }


async def test_create_application_rejects_bad_content_type(db_session, settings_with_tmp_dir):
    with pytest.raises(InvalidResumeError):
        await create_application(
            db_session,
            job_id=SEED_JOB_ID,
            name="Jordan",
            email="jordan@example.com",
            links={},
            resume_file=_upload_file(b"not a resume", "resume.txt", "text/plain"),
        )


async def test_create_application_rejects_oversized_file(db_session, settings_with_tmp_dir):
    settings_with_tmp_dir.resume_upload_max_mb = 0.001  # ~1 KB limit
    oversized = b"x" * 4096
    with pytest.raises(InvalidResumeError):
        await create_application(
            db_session,
            job_id=SEED_JOB_ID,
            name="Jordan",
            email="jordan@example.com",
            links={},
            resume_file=_upload_file(oversized, "resume.pdf", "application/pdf"),
        )


async def test_create_application_rejects_unknown_job(db_session, settings_with_tmp_dir):
    with pytest.raises(JobNotFoundError):
        await create_application(
            db_session,
            job_id="does-not-exist",
            name="Jordan",
            email="jordan@example.com",
            links={},
            resume_file=_upload_file(b"%PDF-1.4", "resume.pdf", "application/pdf"),
        )


def test_get_application_missing_returns_none(db_session):
    assert get_application(db_session, "nope") is None


async def test_list_applications_filters_by_job(db_session, settings_with_tmp_dir):
    await create_application(
        db_session,
        job_id=SEED_JOB_ID,
        name="A",
        email="a@example.com",
        links={},
        resume_file=_upload_file(b"%PDF-1.4", "a.pdf", "application/pdf"),
    )

    results = list_applications(db_session, job_id=SEED_JOB_ID)
    assert len(results) == 1

    assert list_applications(db_session, job_id="other-job") == []
