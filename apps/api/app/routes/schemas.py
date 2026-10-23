"""Request/response DTOs for app/routes.

Kept separate from both the SQLAlchemy models (app.db.models) and the
intake graph's `IntakeState` (app.graphs.state) per AGENTS.md repo layout
("routes/: HTTP layer only"). `ApplicationCreate` is intentionally omitted:
`POST /applications` is multipart/form-data (file upload), so its fields
arrive as individual `Form(...)`/`File(...)` route parameters, not a JSON
body model — there's nothing for a request DTO to validate here that
FastAPI's `Form(...)` declarations don't already cover.

Single file for now — M1's API surface (jobs + applications only) is
small. Split into per-resource files (schemas/jobs.py, schemas/
applications.py, ...) once more resources land (HR portal, reviews,
invites, etc. in M2+).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    name: str
    email: str
    links: dict[str, str]
    status: str
    vector_status: str
    created_at: datetime


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    raw_jd: str
    requirements: list[dict[str, object]]
    created_at: datetime
