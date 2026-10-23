"""M4 regression tests: Tech Lead queue/detail/decision (F3.1-F3.6)."""

import pytest

from app.db.models import Application, Profile, Review

JOB_ID = "job-ai-intern-procogia"
TECH = {"X-Role": "tech"}


def seed(db, application_id="candidate", status="valid"):
    application = Application(
        id=application_id,
        job_id=JOB_ID,
        name=f"Person {application_id}",
        email="candidate@example.com",
        resume_path="unused.pdf",
        status=status,
    )
    db.add(application)
    db.add(
        Profile(
            application_id=application_id,
            score=0.8,
            recommendation="advance",
            confidence=0.8,
            flags=[],
        )
    )
    db.commit()
    return application


@pytest.mark.parametrize(
    "method,path",
    [("get", "/tech/applications"), ("get", "/tech/applications/candidate")],
)
def test_requires_tech_role(client, db_session, method, path):
    seed(db_session)
    response = getattr(client, method)(path)
    assert response.status_code == 403


def test_hr_role_cannot_access_tech_routes(client, db_session):
    seed(db_session)
    response = client.get("/tech/applications", headers={"X-Role": "hr"})
    assert response.status_code == 403


def test_queue_only_lists_valid_candidates(client, db_session):
    seed(db_session, "valid-one", status="valid")
    seed(db_session, "pending-one", status="pending")
    response = client.get("/tech/applications", headers=TECH)
    assert response.status_code == 200
    ids = [row["id"] for row in response.json()]
    assert ids == ["valid-one"]


def test_detail_returns_profile_for_valid_candidate(client, db_session):
    seed(db_session, "valid-two", status="valid")
    response = client.get("/tech/applications/valid-two", headers=TECH)
    assert response.status_code == 200
    assert response.json()["id"] == "valid-two"


def test_decision_requires_valid_status(client, db_session):
    seed(db_session, "already-invited", status="invited")
    response = client.post(
        "/tech/applications/already-invited/decision",
        headers=TECH,
        json={"decision": "invited"},
    )
    assert response.status_code == 409


def test_invite_persists_review_and_status(client, db_session):
    seed(db_session, "to-invite", status="valid")
    response = client.post(
        "/tech/applications/to-invite/decision",
        headers=TECH,
        json={
            "decision": "invited",
            "rubric": [{"requirement_id": "job-ai-intern-procogia-req-01", "score": 4}],
            "overall": 4,
            "comment": "Strong Python depth, invite to interview.",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "invited"

    application = db_session.get(Application, "to-invite")
    assert application.status == "invited"
    review = db_session.query(Review).filter_by(application_id="to-invite").one()
    assert review.reviewer_role == "tech_lead"
    assert review.overall == 4
    assert review.rubric == {"job-ai-intern-procogia-req-01": 4}


def test_decline_sets_rejected_status(client, db_session):
    seed(db_session, "to-decline", status="valid")
    response = client.post(
        "/tech/applications/to-decline/decision",
        headers=TECH,
        json={"decision": "rejected", "comment": "Not enough depth."},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
