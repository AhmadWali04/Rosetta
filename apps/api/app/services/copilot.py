"""Durable Copilot requests, audited confirmations, and database-only SSE polling."""

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Literal, cast

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.copilot import CopilotRun
from app.db.models import Application, Event, Job, _uuid
from app.db.session import SessionLocal
from app.graphs.state import CopilotResult
from app.routes.copilot_schemas import CopilotEvent, CopilotRequest, RunStatus

SAFE_FAILURE = "Copilot analysis failed. Please try again."


def _scope_ids(db: Session, job_id: str, scope: str) -> list[str]:
    statement = select(Application.id).where(Application.job_id == job_id)
    if scope != "pool":
        statement = statement.where(Application.id == scope.removeprefix("candidate:"))
    return list(db.scalars(statement.order_by(Application.id)).all())


def audit_run(
    db: Session,
    run: CopilotRun,
    action: str,
    *,
    actor: str = "system",
    payload: dict | None = None,
) -> None:
    """Audit the scoped applications without persisting resume/prompt content."""
    for application_id in _scope_ids(db, run.job_id, run.scope):
        db.add(
            Event(
                application_id=application_id,
                actor=actor,
                action=action,
                payload={"run_id": run.id, "scope": run.scope, **(payload or {})},
            )
        )


def get_run(db: Session, run_id: str, *, lock: bool = False) -> CopilotRun:
    statement = select(CopilotRun).where(CopilotRun.id == run_id)
    if lock:
        statement = statement.with_for_update()
    run = db.scalar(statement.execution_options(populate_existing=True))
    if run is None:
        raise HTTPException(status_code=404, detail="copilot run not found")
    return run


def enqueue(db: Session, body: CopilotRequest) -> CopilotRun:
    if db.get(Job, body.job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    if not _scope_ids(db, body.job_id, body.scope):
        if body.scope == "pool":
            raise HTTPException(status_code=400, detail="job has no candidates to analyze")
        raise HTTPException(status_code=404, detail="candidate not found in this job")
    run = CopilotRun(
        id=_uuid(), job_id=body.job_id, scope=body.scope, message=body.message, status="queued"
    )
    db.add(run)
    audit_run(db, run, "copilot_requested", actor="hr")
    db.commit()
    db.refresh(run)
    return run


def confirm(db: Session, run_id: str, approve: bool) -> CopilotRun:
    run = get_run(db, run_id, lock=True)
    if run.status != "awaiting_confirmation" or run.confirmation is not None:
        raise HTTPException(status_code=409, detail="run is not awaiting a new confirmation")
    try:
        result = CopilotResult.model_validate(run.result)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=409, detail="run has no valid pending action") from exc
    if not result.needs_confirmation or result.proposal is None:
        raise HTTPException(status_code=409, detail="run has no action awaiting confirmation")
    proposal = result.proposal
    if proposal.application_id not in _scope_ids(db, run.job_id, run.scope):
        raise HTTPException(
            status_code=409, detail="proposed candidate is outside this run's scope"
        )
    run.confirmation = approve
    run.status = "queued"
    run.error = None
    audit_run(
        db,
        run,
        "copilot_confirmation",
        actor="hr",
        payload={"approved": approve, "proposal": proposal.model_dump()},
    )
    db.commit()
    db.refresh(run)
    return run


def _event(
    run: CopilotRun, event: Literal["queued", "progress", "result", "error"]
) -> CopilotEvent:
    # Queued/running confirmations may retain the previous interrupt result in
    # storage. Do not resend that stale proposal as a new actionable result.
    result = None
    if event == "result" and run.result is not None:
        result = CopilotResult.model_validate(run.result)
    return CopilotEvent(
        event=event,
        run_id=run.id,
        status=cast(RunStatus, run.status),
        result=result,
        error=run.error if event == "error" else None,
    )


def encode_event(event: CopilotEvent) -> str:
    return f"event: {event.event}\ndata: {event.model_dump_json()}\n\n"


async def stream_run(run_id: str) -> AsyncIterator[str]:
    """Stream durable status snapshots; never execute graphs in an HTTP request.

    A disconnected/timed-out client can recover with GET /copilot/{run_id}.
    Each poll owns a short-lived session so no DB connection or row lock is
    held during sleeps. Interrupt results end the stream until HR confirms.
    """
    settings = get_settings()
    deadline = time.monotonic() + settings.copilot_stream_timeout_s
    previous_status = None
    first = True
    while True:
        messages = []
        finished = False
        with SessionLocal() as db:
            run = get_run(db, run_id)
            if first:
                messages.append(_event(run, "queued"))
                first = False
            if run.status in {"completed", "awaiting_confirmation"}:
                messages.append(_event(run, "result"))
                finished = True
            elif run.status == "failed":
                messages.append(_event(run, "error"))
                finished = True
            elif run.status != previous_status:
                messages.append(_event(run, "progress"))
                previous_status = run.status
            if not finished and time.monotonic() >= deadline:
                event = _event(run, "error")
                event.error = (
                    "Stream timed out; the run continues. Retrieve its status to reconnect."
                )
                messages.append(event)
                finished = True
        for event in messages:
            yield encode_event(event)
        if finished:
            return
        await asyncio.sleep(settings.copilot_stream_poll_s)
