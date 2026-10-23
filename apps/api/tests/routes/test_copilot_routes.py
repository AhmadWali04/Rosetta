"""Copilot HTTP contracts enqueue work without executing models in requests."""

import json

import pytest

from app.db.copilot import CopilotRun
from app.db.models import Application, Event, Job
from app.graphs.state import CopilotProposal, CopilotResult
from app.routes.copilot_schemas import CopilotEvent
from app.services import copilot

JOB = "job-ai-intern-procogia"
HR = {"X-Role": "hr"}


@pytest.fixture()
def candidate(db_session):
    row = Application(
        id="candidate", job_id=JOB, name="Person", email="fake@example.com", resume_path="fake.pdf"
    )
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture()
def finite_stream(monkeypatch, db_session):
    async def stream(run_id):
        run = copilot.get_run(db_session, run_id)
        yield copilot.encode_event(CopilotEvent(event="queued", run_id=run_id, status=run.status))

    monkeypatch.setattr(copilot, "stream_run", stream)


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/copilot", {"job_id": JOB, "scope": "pool", "message": "Compare"}),
        ("get", "/copilot/unknown", None),
        ("post", "/copilot/unknown/confirm", {"approve": True}),
    ],
)
def test_hr_role_required(client, method, path, body):
    assert client.request(method, path, json=body).status_code == 403
    assert (
        client.request(method, path, json=body, headers={"X-Role": "applicant"}).status_code == 403
    )


def test_enqueue_sse_durable_run_audit_and_get(client, db_session, candidate, finite_stream):
    response = client.post(
        "/copilot",
        headers=HR,
        json={"job_id": JOB, "scope": "candidate:candidate", "message": "  Verify Python  "},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    payload = json.loads(response.text.split("data: ")[1].strip())
    assert payload["event"] == "queued"
    run = db_session.get(CopilotRun, payload["run_id"])
    assert run.status == "queued" and run.message == "Verify Python"
    assert candidate.status == "submitted"
    events = db_session.query(Event).filter(Event.action == "copilot_requested").all()
    assert len(events) == 1 and events[0].payload["run_id"] == run.id
    assert events[0].actor == "hr"
    fetched = client.get(f"/copilot/{run.id}", headers=HR)
    assert fetched.status_code == 200 and fetched.json()["status"] == "queued"
    assert fetched.json()["result"] is None
    assert client.get("/copilot/missing", headers=HR).status_code == 404


def test_scope_must_belong_to_job_and_empty_pool_rejected(client, db_session, candidate):
    db_session.add(Job(id="other", title="Other", raw_jd="Other role"))
    db_session.commit()
    assert (
        client.post(
            "/copilot",
            headers=HR,
            json={"job_id": "other", "scope": "candidate:candidate", "message": "Verify"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/copilot", headers=HR, json={"job_id": "other", "scope": "pool", "message": "Rank"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/copilot", headers=HR, json={"job_id": "unknown", "scope": "pool", "message": "Rank"}
        ).status_code
        == 404
    )
    assert db_session.query(CopilotRun).count() == 0


@pytest.mark.parametrize(
    "updates",
    [{"scope": "candidate:"}, {"scope": "invalid"}, {"message": " "}, {"message": "x" * 4001}],
)
def test_request_validation(client, updates):
    body = {"job_id": JOB, "scope": "pool", "message": "Compare"} | updates
    assert client.post("/copilot", headers=HR, json=body).status_code == 422


@pytest.mark.parametrize("approve", [True, False])
def test_confirmation_queues_once_without_changing_candidate(
    client, db_session, candidate, finite_stream, approve
):
    result = CopilotResult(
        run_id="run",
        needs_confirmation=True,
        proposal=CopilotProposal(application_id=candidate.id, status="valid"),
    )
    run = CopilotRun(
        id="run",
        job_id=JOB,
        scope="candidate:candidate",
        message="Mark valid",
        status="awaiting_confirmation",
        result=result.model_dump(),
    )
    db_session.add(run)
    db_session.commit()
    response = client.post("/copilot/run/confirm", headers=HR, json={"approve": approve})
    assert response.status_code == 200
    db_session.refresh(run)
    assert run.confirmation is approve and run.status == "queued"
    assert candidate.status == "submitted"
    assert (
        client.post("/copilot/run/confirm", headers=HR, json={"approve": approve}).status_code
        == 409
    )
    audit = db_session.query(Event).filter(Event.action == "copilot_confirmation").all()
    assert len(audit) == 1 and audit[0].payload["approved"] is approve


def test_confirmation_requires_existing_pending_proposal(client, db_session, candidate):
    run = CopilotRun(id="run", job_id=JOB, scope="pool", message="Rank", status="completed")
    db_session.add(run)
    db_session.commit()
    assert (
        client.post("/copilot/run/confirm", headers=HR, json={"approve": True}).status_code == 409
    )
    assert (
        client.post("/copilot/missing/confirm", headers=HR, json={"approve": True}).status_code
        == 404
    )


def test_confirmation_rejects_proposal_outside_original_scope(
    client, db_session, candidate, finite_stream
):
    db_session.add(
        Application(
            id="other-candidate",
            job_id=JOB,
            name="Other",
            email="fake@example.com",
            resume_path="unused.pdf",
        )
    )
    result = CopilotResult(
        run_id="run",
        needs_confirmation=True,
        proposal=CopilotProposal(application_id="other-candidate", status="valid"),
    )
    run = CopilotRun(
        id="run",
        job_id=JOB,
        scope="candidate:candidate",
        message="Mark valid",
        status="awaiting_confirmation",
        result=result.model_dump(),
    )
    db_session.add(run)
    db_session.commit()
    assert (
        client.post("/copilot/run/confirm", headers=HR, json={"approve": True}).status_code == 409
    )
    db_session.refresh(run)
    assert run.confirmation is None and run.status == "awaiting_confirmation"


def test_confirmation_rejects_incomplete_pending_result(client, db_session, candidate):
    run = CopilotRun(
        id="run",
        job_id=JOB,
        scope="candidate:candidate",
        message="Mark valid",
        status="awaiting_confirmation",
        result=None,
    )
    db_session.add(run)
    db_session.commit()
    assert (
        client.post("/copilot/run/confirm", headers=HR, json={"approve": True}).status_code == 409
    )


def test_openapi_registers_sse_and_nested_copilot_result(client):
    schema = client.get("/openapi.json").json()
    assert "CopilotEvent" in schema["components"]["schemas"]
    assert "CopilotResult" in schema["components"]["schemas"]
    response = schema["paths"]["/copilot"]["post"]["responses"]["200"]
    assert "text/event-stream" in response["content"]
