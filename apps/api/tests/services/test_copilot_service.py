"""Copilot database-only SSE states and audited scope; no live model/network calls."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.copilot import CopilotRun
from app.db.models import Application, Event
from app.graphs.state import CopilotResult
from app.routes.copilot_schemas import CopilotRequest
from app.services import copilot

JOB = "job-ai-intern-procogia"


@pytest.fixture()
def seeded(db_session):
    for identifier in ("one", "two"):
        db_session.add(
            Application(
                id=identifier,
                job_id=JOB,
                name=identifier,
                email="fake@example.com",
                resume_path="fake.pdf",
            )
        )
    db_session.commit()


def test_pool_enqueue_audits_each_affected_candidate(db_session, seeded):
    run = copilot.enqueue(db_session, CopilotRequest(job_id=JOB, scope="pool", message="Compare"))
    events = db_session.query(Event).all()
    assert {event.application_id for event in events} == {"one", "two"}
    assert all(event.payload["run_id"] == run.id for event in events)
    assert all("message" not in event.payload for event in events)


@pytest.mark.parametrize(
    "status,event",
    [("completed", "result"), ("awaiting_confirmation", "result"), ("failed", "error")],
)
def test_stream_returns_terminal_result_and_safe_failure(
    db_session, monkeypatch, seeded, status, event
):
    run = CopilotRun(
        id="run",
        job_id=JOB,
        scope="pool",
        message="Compare",
        status=status,
        result=CopilotResult(
            run_id="run",
            steps=["supervisor", "grounding"],
            needs_confirmation=status == "awaiting_confirmation",
        ).model_dump()
        if status != "failed"
        else None,
        error=copilot.SAFE_FAILURE if status == "failed" else None,
    )
    db_session.add(run)
    db_session.commit()
    monkeypatch.setattr(copilot, "SessionLocal", sessionmaker(bind=db_session.get_bind()))

    async def read():
        return [item async for item in copilot.stream_run("run")]

    chunks = asyncio.run(read())
    assert len(chunks) == 2
    assert chunks[0].startswith("event: queued\n")
    assert chunks[1].startswith(f"event: {event}\n")
    data = json.loads(chunks[1].split("data: ")[1])
    assert data["status"] == status
    if status != "failed":
        assert data["result"]["steps"] == ["supervisor", "grounding"]
        assert data["result"]["needs_confirmation"] is (status == "awaiting_confirmation")
    else:
        assert data["error"] == copilot.SAFE_FAILURE


def test_stream_timeout_does_not_cancel_durable_run(db_session, monkeypatch, seeded):
    db_session.add(CopilotRun(id="run", job_id=JOB, scope="pool", message="Rank", status="queued"))
    db_session.commit()
    monkeypatch.setattr(copilot, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    monkeypatch.setattr(
        copilot,
        "get_settings",
        lambda: SimpleNamespace(copilot_stream_timeout_s=0, copilot_stream_poll_s=0),
    )

    async def read():
        return [item async for item in copilot.stream_run("run")]

    chunks = asyncio.run(read())
    assert len(chunks) == 3
    assert "run continues" in chunks[-1]
    assert copilot.get_run(db_session, "run").status == "queued"
