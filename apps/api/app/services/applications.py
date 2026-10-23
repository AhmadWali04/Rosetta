"""Business logic / DB access for applications (AGENTS.md repo layout,
PRD F1.2/F1.4).

`create_application` is the only interesting function here: it validates
the uploaded resume, saves it to disk, inserts the `Application` row
(status="submitted", vector_status="pending"), and writes the audit
`Event` row (AGENTS.md invariant #4: audit everything) — all before the
worker ever looks at the row. The route handler calling this stays fast;
it does NOT trigger the intake graph itself (PRD §13 "background worker"
framing — apps/worker polls for submitted rows on its own cycle).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Application, Event, Job, _uuid

ACCEPTED_RESUME_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# Chunk size for the bounded read below — arbitrary but small enough to
# avoid ever holding more than ~1 MiB extra over the configured limit in
# memory at once.
_READ_CHUNK_SIZE = 1024 * 1024


class JobNotFoundError(ValueError):
    """Raised when `create_application` is given a job_id that doesn't exist."""


class InvalidResumeError(ValueError):
    """Raised when the uploaded resume fails content-type or size validation
    (F1.2: PDF/DOCX, <= `settings.resume_upload_max_mb`)."""


async def _read_limited(upload: UploadFile, max_bytes: int) -> bytes:
    """Reads at most `max_bytes` + 1 bytes, in chunks, aborting as soon as
    the limit is exceeded rather than unconditionally loading an
    arbitrarily large upload into memory first."""
    data = bytearray()
    while True:
        chunk = await upload.read(_READ_CHUNK_SIZE)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > max_bytes:
            break
    await upload.seek(0)
    return bytes(data)


async def create_application(
    db: Session,
    *,
    job_id: str,
    name: str,
    email: str,
    links: dict[str, str],
    resume_file: UploadFile,
) -> Application:
    """Validates and persists a new application.

    NOTE on signature: the brief for this function specified `def`, but
    validating the upload requires `await resume_file.read(...)`, so this
    is `async def` — the caller (the route handler) is already async, so
    this is a one-line `await` at the call site, not a design change.
    """
    settings = get_settings()

    if db.get(Job, job_id) is None:
        raise JobNotFoundError(f"job '{job_id}' does not exist")

    if resume_file.content_type not in ACCEPTED_RESUME_CONTENT_TYPES:
        raise InvalidResumeError(
            f"unsupported file type '{resume_file.content_type}'; only PDF and "
            "DOCX resumes are accepted"
        )

    max_bytes = int(settings.resume_upload_max_mb * 1024 * 1024)
    content = await _read_limited(resume_file, max_bytes)
    if len(content) > max_bytes:
        raise InvalidResumeError(f"resume exceeds the {settings.resume_upload_max_mb} MB limit")

    application_id = _uuid()
    original_filename = resume_file.filename or "resume"

    # KNOWN ROUGH EDGE (flagged per Agent E's brief, not fixed here):
    # `resume_upload_dir` defaults to the *relative* path "data/uploads".
    # Inside the api/worker containers this resolves correctly because
    # WORKDIR=/app and docker-compose.yml bind-mounts the repo's
    # data/uploads/ to /app/data/uploads. Outside Docker (e.g. running
    # `uvicorn` directly from a shell), it resolves relative to whatever
    # the process's cwd happens to be at start time — fragile for local
    # non-Docker dev. Left as-is to match the container contract rather
    # than silently diverging from it.
    app_dir = Path(settings.resume_upload_dir) / application_id
    app_dir.mkdir(parents=True, exist_ok=True)
    resume_path = app_dir / original_filename
    resume_path.write_bytes(content)

    application = Application(
        id=application_id,
        job_id=job_id,
        name=name,
        email=email,
        links=links,
        resume_path=str(resume_path),
        status="submitted",
        vector_status="pending",
    )
    db.add(application)
    db.add(
        Event(
            application_id=application_id,
            actor="applicant",
            action="application_submitted",
            payload={"job_id": job_id, "name": name, "email": email},
        )
    )
    db.commit()
    db.refresh(application)
    return application


def get_application(db: Session, application_id: str) -> Application | None:
    return db.get(Application, application_id)


def list_applications(db: Session, job_id: str | None = None) -> list[Application]:
    stmt = select(Application).order_by(Application.created_at.desc())
    if job_id is not None:
        stmt = stmt.where(Application.job_id == job_id)
    return list(db.execute(stmt).scalars().all())
