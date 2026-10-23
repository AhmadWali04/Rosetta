"""M2 regression tests: grounding, HR authorization, audit and stale approvals."""

import json

import pytest

from app.db.models import Application, Event, JdRequirement, Profile, ResumeChunk

JOB_ID = "job-ai-intern-procogia"
HR = {"X-Role": "hr"}


def seed(db, application_id="candidate", score=0.8, status="analyzed"):
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
            score=score,
            recommendation="advance",
            confidence=0.8,
            flags=["injection_attempt"],
        )
    )
    db.commit()
    return application


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/hr/applications", None),
        ("get", "/hr/applications/candidate", None),
        ("get", "/applications/candidate/events", None),
        ("patch", "/applications/candidate/status", {"status": "valid"}),
        ("post", f"/pools/{JOB_ID}/promote/preview", {"percent": 50}),
        ("post", f"/pools/{JOB_ID}/promote", {"percent": 50, "application_ids": []}),
    ],
)
def test_hr_role_required(client, method, path, body):
    response = client.request(method, path, json=body)
    assert response.status_code == 403
    assert (
        client.request(method, path, json=body, headers={"X-Role": "applicant"}).status_code == 403
    )


def test_pipeline_filter_score_sort_and_missing_profile(client, db_session):
    seed(db_session, "low", 0.2, "pending")
    seed(db_session, "high", 0.9, "pending")
    seed(db_session, "other", 0.5, "valid")
    response = client.get("/hr/applications?status=pending&sort=score_desc", headers=HR)
    assert [item["id"] for item in response.json()] == ["high", "low"]
    response = client.get("/hr/applications?status=pending&sort=score_asc", headers=HR)
    assert [item["id"] for item in response.json()] == ["low", "high"]
    assert client.get("/hr/applications?job_id=another", headers=HR).json() == []
    assert client.get("/hr/applications?sort=invalid", headers=HR).status_code == 422


def test_candidate_hydrates_only_own_citations_and_skills(client, db_session):
    application = seed(db_session)
    seed(db_session, "foreign")
    db_session.add_all(
        [
            JdRequirement(
                id="req",
                job_id=JOB_ID,
                text="Python backend",
                kind="must_have",
                pinecone_id="req#req",
            ),
            JdRequirement(
                id="bad", job_id=JOB_ID, text="Go backend", kind="must_have", pinecone_id="req#bad"
            ),
            ResumeChunk(
                id="own-row",
                application_id=application.id,
                chunk_idx=0,
                section="projects",
                text="Built Python services",
                char_start=0,
                char_end=21,
                pinecone_id="candidate#chunk#0",
                embed_model="fake",
            ),
            ResumeChunk(
                id="foreign-row",
                application_id="foreign",
                chunk_idx=0,
                section="projects",
                text="Built Go services",
                char_start=0,
                char_end=17,
                pinecone_id="foreign#chunk#0",
                embed_model="fake",
            ),
        ]
    )
    profile = db_session.get(Profile, application.id)
    profile.requirement_matches = [
        {
            "requirement_id": "req",
            "status": "met",
            "resolved_chunk_ids": ["candidate#chunk#0", "foreign#chunk#0"],
        },
        {"requirement_id": "bad", "status": "met", "resolved_chunk_ids": ["foreign-row"]},
    ]
    profile.explanation = json.dumps(
        {
            "per_requirement": {
                "req": "Python supports this requirement.",
                "bad": "Untrusted claim",
            },
            "overall": "Untrusted overall",
        }
    )
    profile.skills = [
        {"extracted": {"skill": "Py", "evidence_span": "Python"}, "canonical": "Python"},
        {"extracted": {"skill": "Go", "evidence_span": "Go"}, "canonical": "Go"},
        {"extracted": {"skill": "Empty", "evidence_span": ""}, "canonical": "Empty"},
    ]
    db_session.commit()
    response = client.get("/hr/applications/candidate", headers=HR)
    assert response.status_code == 200
    data = response.json()
    requirements = {item["id"]: item for item in data["requirements"]}
    assert requirements["req"]["chunk_ids"] == ["own-row"]
    assert requirements["req"]["status"] == "met"
    assert requirements["bad"]["status"] == "missing"
    assert "Untrusted" not in response.text
    assert data["must_have_met"] == 1
    assert data["must_have_total"] == 2
    assert data["skills"] == [
        {"term": "Py", "canonical": "Python", "requirement_ids": ["req"], "chunk_ids": ["own-row"]}
    ]
    assert [chunk["id"] for chunk in data["chunks"]] == ["own-row"]


def test_label_records_override_and_reason(client, db_session):
    seed(db_session)
    response = client.patch(
        "/applications/candidate/status",
        headers=HR,
        json={"status": "pending", "reason": "Needs manual verification"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    events = client.get("/applications/candidate/events", headers=HR).json()
    assert {event["action"] for event in events} == {"label_changed", "recommendation_overridden"}
    assert all(event["actor"] == "hr" for event in events)
    assert all(event["payload"]["reason"] == "Needs manual verification" for event in events)


@pytest.mark.parametrize(
    "status", ["submitted", "analyzing", "intake_failed", "tech_review", "invited"]
)
def test_label_rejects_non_hr_states(client, db_session, status):
    seed(db_session, status=status)
    response = client.patch("/applications/candidate/status", headers=HR, json={"status": "valid"})
    assert response.status_code == 409
    assert db_session.query(Event).count() == 0


def test_unknown_and_invalid_status(client, db_session):
    assert client.get("/hr/applications/missing", headers=HR).status_code == 404
    assert client.get("/applications/missing/events", headers=HR).status_code == 404
    seed(db_session)
    assert (
        client.patch(
            "/applications/candidate/status", headers=HR, json={"status": "invited"}
        ).status_code
        == 422
    )


def test_promotion_preview_then_confirm_with_ties_and_rounding(client, db_session):
    for identifier, score in [("b", 0.8), ("a", 0.8), ("c", 0.5)]:
        seed(db_session, identifier, score, "pending")
    preview = client.post(f"/pools/{JOB_ID}/promote/preview", headers=HR, json={"percent": 50})
    assert preview.status_code == 200
    assert preview.json()["application_ids"] == ["a", "b"]
    assert preview.json()["pending_count"] == 3
    assert db_session.get(Application, "a").status == "pending"
    response = client.post(
        f"/pools/{JOB_ID}/promote", headers=HR, json={"percent": 50, "application_ids": ["a", "b"]}
    )
    assert response.status_code == 200
    assert db_session.get(Application, "a").status == "valid"
    assert db_session.get(Application, "c").status == "pending"
    assert db_session.query(Event).filter(Event.action == "pool_promoted").count() == 2


def test_stale_promotion_is_atomic_and_requires_preview_ids(client, db_session):
    seed(db_session, "a", 0.9, "pending")
    seed(db_session, "b", 0.7, "pending")
    response = client.post(
        f"/pools/{JOB_ID}/promote", headers=HR, json={"percent": 50, "application_ids": ["b"]}
    )
    assert response.status_code == 409
    assert db_session.get(Application, "b").status == "pending"
    assert db_session.query(Event).count() == 0
    assert (
        client.post(f"/pools/{JOB_ID}/promote", headers=HR, json={"percent": 50}).status_code == 422
    )


@pytest.mark.parametrize("percent", [-1, 101])
def test_promotion_invalid_percentage(client, percent):
    assert (
        client.post(
            f"/pools/{JOB_ID}/promote/preview", headers=HR, json={"percent": percent}
        ).status_code
        == 422
    )


def test_zero_percent_empty_and_unknown_pool(client, db_session):
    seed(db_session, status="pending")
    assert (
        client.post(f"/pools/{JOB_ID}/promote/preview", headers=HR, json={"percent": 0}).json()[
            "application_ids"
        ]
        == []
    )
    assert (
        client.post("/pools/missing/promote/preview", headers=HR, json={"percent": 50}).status_code
        == 404
    )


def test_skill_links_require_explicit_terms_and_nonblank_evidence(client, db_session):
    application = seed(db_session)
    db_session.add(
        JdRequirement(
            id="python",
            job_id=JOB_ID,
            text="Ongoing PYTHON backend development",
            kind="must_have",
            pinecone_id="req#python",
        )
    )
    db_session.add(
        ResumeChunk(
            id="shared",
            application_id=application.id,
            chunk_idx=0,
            section="projects",
            text="Used Python and Go and Kubernetes in a project",
            char_start=0,
            char_end=45,
            pinecone_id="candidate#chunk#0",
            embed_model="fake",
        )
    )
    profile = db_session.get(Profile, application.id)
    profile.requirement_matches = [
        {
            "requirement_id": "python",
            "status": "met",
            "resolved_chunk_ids": ["candidate#chunk#0"],
        }
    ]
    profile.skills = [
        {"extracted": {"skill": term, "evidence_span": term}, "canonical": term}
        for term in ["Python", "Go", "Kubernetes"]
    ] + [{"extracted": {"skill": "Blank", "evidence_span": " "}, "canonical": "Blank"}]
    db_session.commit()
    response = client.get("/hr/applications/candidate", headers=HR)
    assert response.status_code == 200
    skills = {skill["term"]: skill for skill in response.json()["skills"]}
    assert skills["Python"]["requirement_ids"] == ["python"]
    assert skills["Go"]["requirement_ids"] == []
    assert skills["Kubernetes"]["requirement_ids"] == []
    assert "Blank" not in skills


@pytest.mark.parametrize("status", ["submitted", "intake_failed"])
def test_candidate_without_profile_does_not_claim_missing_requirements(client, db_session, status):
    db_session.add(
        Application(
            id="unfinished",
            job_id=JOB_ID,
            name="Unfinished Candidate",
            email="unfinished@example.com",
            resume_path="unused.pdf",
            status=status,
        )
    )
    db_session.add(
        JdRequirement(
            id="python",
            job_id=JOB_ID,
            text="Python backend",
            kind="must_have",
            pinecone_id="req#python",
        )
    )
    db_session.commit()
    response = client.get("/hr/applications/unfinished", headers=HR)
    assert response.status_code == 200
    data = response.json()
    assert data["score"] is None
    assert data["recommendation"] is None
    assert data["skills"] == []
    assert data["requirements"] == [
        {
            "id": "python",
            "text": "Python backend",
            "kind": "must_have",
            "status": "not_evaluated",
            "explanation": "Analysis has not completed.",
            "chunk_ids": [],
        }
    ]
