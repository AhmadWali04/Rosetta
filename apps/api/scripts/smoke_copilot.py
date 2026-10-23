"""Worker/SSE/checkpoint acceptance exercised inside smoke_hr's temporary DB."""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch


def exercise(job_id: str, application_ids: list[str]) -> None:
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app.config import get_settings
    from app.db.models import Application, Event, ResumeChunk
    from app.db.session import SessionLocal
    from app.graphs.copilot.common import AgentAnswer, RouteDecision
    from app.graphs.state import CopilotClaim
    from app.llm.fake import FakeLLMProvider
    from app.main import app

    worker_dir = str(Path(__file__).resolve().parents[2] / "worker")
    sys.path.insert(0, worker_dir)
    from copilot_runner import process_pending_copilot

    os.environ["COPILOT_STREAM_TIMEOUT_S"] = "10"
    os.environ["COPILOT_STREAM_POLL_S"] = "0.02"
    get_settings.cache_clear()
    candidate_id = application_ids[0]
    headers = {"X-Role": "hr"}
    with SessionLocal() as db:
        chunk = db.scalar(select(ResumeChunk).where(ResumeChunk.application_id == candidate_id))
        assert chunk is not None
        chunk_id = chunk.id

    def process_one() -> None:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            with SessionLocal() as db:
                if process_pending_copilot(db):
                    return
            time.sleep(0.02)
        raise AssertionError("Worker never received the queued copilot request")

    def request(client: TestClient, path: str, body: dict, fake: FakeLLMProvider) -> dict:
        with (
            patch("app.llm.factory._INSTANCES", {"openai": fake}),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            future = executor.submit(process_one)
            response = client.post(path, json=body, headers=headers)
            future.result(timeout=12)
        assert response.status_code == 200, f"Copilot HTTP status {response.status_code}"
        assert response.headers["content-type"].startswith("text/event-stream")
        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        result_events = [event for event in events if event["event"] == "result"]
        assert result_events, "Copilot did not finish with a result event"
        return result_events[-1]["result"]

    def fake_answer(route: str, *, invalid_first: bool = False) -> FakeLLMProvider:
        good = AgentAnswer(
            confidence=0.9,
            claims=[
                CopilotClaim(text="The resume describes Python services.", chunk_ids=[chunk_id])
            ],
        )
        answers = [AgentAnswer(confidence=0.9, claims=[CopilotClaim(text="Uncited claim")]), good]
        return FakeLLMProvider(
            responses={
                "RouteDecision": RouteDecision(route=route),
                "AgentAnswer": answers if invalid_first else good,
            }
        )

    body = {"job_id": job_id, "scope": f"candidate:{candidate_id}", "message": "Verify Python"}
    with TestClient(app) as client:
        result = request(client, "/copilot", body, fake_answer("verify"))
        assert result["route"] == "verify" and result["claims"]
        assert result["claims"][0]["chunk_ids"] == [chunk_id]
        assert result["citations"][0]["application_id"] == candidate_id

        result = request(client, "/copilot", body, fake_answer("verify", invalid_first=True))
        assert result["retries"] == 1 and result["claims"], "Grounding retry did not recover"

        low = FakeLLMProvider(
            responses={
                "RouteDecision": RouteDecision(route="verify"),
                "AgentAnswer": [
                    AgentAnswer(confidence=0.2, claims=[]),
                    AgentAnswer(confidence=0.8, claims=[]),
                ],
            }
        )
        result = request(client, "/copilot", body, low)
        assert "deep_verify" in result["steps"], "Low confidence did not branch"
        assert result["warnings"], "Missing GitHub should produce an explicit warning"

        # Actual Postgres checkpoint interrupts: no status write before HR acts.
        for approved in (False, True):
            with SessionLocal() as db:
                before = db.get(Application, candidate_id).status
            fake = FakeLLMProvider(
                responses={"RouteDecision": RouteDecision(route="update_status", status="rejected")}
            )
            proposal = request(
                client, "/copilot", {**body, "message": "Mark this candidate rejected"}, fake
            )
            assert proposal["needs_confirmation"] and proposal["proposal"]["status"] == "rejected"
            with SessionLocal() as db:
                assert db.get(Application, candidate_id).status == before
            resumed = request(
                client,
                f"/copilot/{proposal['run_id']}/confirm",
                {"approve": approved},
                fake,
            )
            assert not resumed["needs_confirmation"]
            with SessionLocal() as db:
                expected = "rejected" if approved else before
                assert db.get(Application, candidate_id).status == expected
                actions = set(
                    db.scalars(select(Event.action).where(Event.application_id == candidate_id))
                )
                assert {
                    "copilot_requested",
                    "copilot_started",
                    "copilot_completed",
                    "copilot_confirmation",
                } <= actions
            assert (
                client.post(
                    f"/copilot/{proposal['run_id']}/confirm",
                    json={"approve": approved},
                    headers=headers,
                ).status_code
                == 409
            )
    print("PASS: worker-backed Copilot SSE, cited answers, Deep Verify, grounding retry,")
    print("      real Postgres interrupt/resume, cancel/approve and audit.")
