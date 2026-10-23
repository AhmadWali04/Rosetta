"""Tests the single-iteration worker body (apps/worker/runner.py), not the
infinite polling loop in apps/worker/main.py — that loop (sleep-forever)
is exercised in Docker/manually, not in pytest.

apps/worker is a sibling of apps/api, not part of the installed `app`
package; tests/conftest.py puts it on sys.path (the same way the worker
container's script directory ends up on sys.path[0]) before this module
imports it.

Per AGENTS.md "Testing rules" (unit tests never touch the network/a live
LLM), `run_intake_graph` is never the real one here — it's injected as a
fake via `process_pending_applications(db, run_intake_graph=...)`.
"""

from __future__ import annotations

from runner import process_pending_applications

from app.db.models import Application, Event

SEED_JOB_ID = "job-ai-intern-procogia"


def _make_application(db_session, **overrides) -> Application:
    defaults: dict = dict(
        job_id=SEED_JOB_ID,
        name="Jordan",
        email="jordan@example.com",
        links={},
        resume_path="data/uploads/fake/resume.pdf",
        status="submitted",
        vector_status="pending",
    )
    defaults.update(overrides)
    application = Application(**defaults)
    db_session.add(application)
    db_session.commit()
    return application


def test_claims_and_processes_submitted_applications(db_session):
    app_row = _make_application(db_session)
    calls: list[tuple[str, str, str]] = []

    def fake_runner(application_id: str, job_id: str, resume_path: str) -> None:
        calls.append((application_id, job_id, resume_path))

    process_pending_applications(db_session, run_intake_graph=fake_runner)

    db_session.refresh(app_row)
    assert calls == [(app_row.id, app_row.job_id, app_row.resume_path)]
    # the fake runner doesn't itself advance status past the claim
    assert app_row.status == "analyzing"


def test_failed_intake_marks_application_and_writes_event(db_session):
    app_row = _make_application(db_session)

    def failing_runner(application_id: str, job_id: str, resume_path: str) -> None:
        raise RuntimeError("boom")

    process_pending_applications(db_session, run_intake_graph=failing_runner)

    db_session.refresh(app_row)
    assert app_row.status == "intake_failed"

    events = db_session.query(Event).filter_by(application_id=app_row.id).all()
    assert len(events) == 1
    assert events[0].action == "intake_failed"
    assert events[0].actor == "system"
    assert events[0].payload["error"] == "boom"


def test_ignores_applications_not_submitted(db_session):
    _make_application(db_session, status="analyzing")
    calls: list[tuple] = []

    process_pending_applications(db_session, run_intake_graph=lambda *a: calls.append(a))

    assert calls == []


def test_one_bad_application_does_not_block_the_rest(db_session):
    bad = _make_application(db_session, email="bad@example.com")
    good = _make_application(db_session, email="good@example.com")
    calls: list[str] = []

    def runner(application_id: str, job_id: str, resume_path: str) -> None:
        if application_id == bad.id:
            raise RuntimeError("boom")
        calls.append(application_id)

    process_pending_applications(db_session, run_intake_graph=runner)

    db_session.refresh(bad)
    db_session.refresh(good)
    assert bad.status == "intake_failed"
    assert good.status == "analyzing"
    assert calls == [good.id]
