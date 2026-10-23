"""Durable claiming, confirmation resumption, safe failures and audit isolation."""

import pytest
from copilot_runner import process_pending_copilot
from runner import process_pending_applications

from app.db.models import Application, Event
from app.graphs.state import CopilotProposal, CopilotResult
from app.routes.copilot_schemas import CopilotRequest
from app.services import copilot

JOB = "job-ai-intern-procogia"


@pytest.fixture()
def queued(db_session):
    db_session.add(
        Application(
            id="candidate",
            job_id=JOB,
            name="Person",
            email="fake@example.com",
            resume_path="unused.pdf",
            status="analyzed",
        )
    )
    db_session.commit()
    return copilot.enqueue(
        db_session, CopilotRequest(job_id=JOB, scope="candidate:candidate", message="Verify Python")
    )


def test_claim_commits_running_and_completes_once(db_session, queued):
    calls = []

    def graph(state, confirmation):
        assert copilot.get_run(db_session, state.run_id).status == "running"
        assert confirmation is None
        calls.append(state)
        return CopilotResult(run_id=state.run_id, route="verify", steps=["supervisor", "verifier"])

    assert process_pending_copilot(db_session, graph) is True
    assert process_pending_copilot(db_session, graph) is False
    assert len(calls) == 1
    run = copilot.get_run(db_session, queued.id)
    assert run.status == "completed"
    assert run.result["route"] == "verify"
    actions = {event.action for event in db_session.query(Event).all()}
    assert {"copilot_requested", "copilot_started", "copilot_completed"} <= actions
    assert db_session.get(Application, "candidate").status == "analyzed"


@pytest.mark.parametrize("approve", [True, False])
def test_interrupt_then_explicit_confirm_resumes_same_run_once(db_session, queued, approve):
    calls = []

    def graph(state, confirmation):
        calls.append(confirmation)
        if confirmation is None:
            return CopilotResult(
                run_id=state.run_id,
                needs_confirmation=True,
                proposal=CopilotProposal(application_id="candidate", status="valid"),
            )
        assert confirmation is approve
        return CopilotResult(run_id=state.run_id, explanation="Approved" if approve else "Declined")

    process_pending_copilot(db_session, graph)
    assert copilot.get_run(db_session, queued.id).status == "awaiting_confirmation"
    assert process_pending_copilot(db_session, graph) is False
    assert db_session.get(Application, "candidate").status == "analyzed"
    copilot.confirm(db_session, queued.id, approve)
    process_pending_copilot(db_session, graph)
    run = copilot.get_run(db_session, queued.id)
    assert run.status == "completed" and run.result["needs_confirmation"] is False
    assert calls == [None, approve]
    assert process_pending_copilot(db_session, graph) is False
    assert db_session.query(Event).filter(Event.action == "copilot_confirmation").count() == 1


def test_provider_failure_is_safe_audited_and_does_not_crash_worker(db_session, queued):
    def broken(state, confirmation):
        raise RuntimeError("secret-provider-payload-api-key")

    assert process_pending_copilot(db_session, broken) is True
    run = copilot.get_run(db_session, queued.id)
    assert run.status == "failed" and run.error == copilot.SAFE_FAILURE
    assert run.result is None
    events = db_session.query(Event).filter(Event.action == "copilot_failed").all()
    assert len(events) == 1
    assert "secret-provider" not in str(events[0].payload)
    second = copilot.enqueue(
        db_session, CopilotRequest(job_id=JOB, scope="candidate:candidate", message="Try again")
    )
    process_pending_copilot(db_session, lambda state, _: CopilotResult(run_id=state.run_id))
    assert copilot.get_run(db_session, second.id).status == "completed"


def test_mismatched_graph_result_is_not_exposed(db_session, queued):
    process_pending_copilot(db_session, lambda state, _: CopilotResult(run_id="foreign-run"))
    run = copilot.get_run(db_session, queued.id)
    assert run.status == "failed" and run.result is None


def test_intake_batch_limit_leaves_room_for_copilot_poll(db_session):
    for identifier in ("first", "second"):
        db_session.add(
            Application(
                id=identifier,
                job_id=JOB,
                name=identifier,
                email="fake@example.com",
                resume_path="unused.pdf",
                status="submitted",
            )
        )
    db_session.commit()
    calls = []
    process_pending_applications(
        db_session, lambda application_id, *_: calls.append(application_id), max_applications=1
    )
    assert len(calls) == 1
    assert db_session.query(Application).filter(Application.status == "submitted").count() == 1
