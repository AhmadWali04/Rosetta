"""Scoped tools, Postgres hydration, safe retrieval fallback and confirmed writes."""

from contextlib import contextmanager

import pytest

from app.db.models import Application, Event, Job, Profile, ResumeChunk, SkillTaxonomy
from app.graphs.state import CopilotProposal
from app.rag.retriever import RetrievedMatch
from app.tools import copilot as tools

JOB = "job-ai-intern-procogia"


@pytest.fixture
def tool_db(db_session, monkeypatch):
    @contextmanager
    def scope():
        yield db_session

    monkeypatch.setattr(tools, "session_scope", scope)
    db_session.add(Job(id="other-job", title="Other", raw_jd="Other", requirements=[]))
    for identifier, job in [("own", JOB), ("peer", JOB), ("foreign", "other-job")]:
        db_session.add(
            Application(
                id=identifier,
                job_id=job,
                name=identifier,
                email=f"{identifier}@example.com",
                resume_path="unused",
                status="analyzed",
                vector_status="indexed",
            )
        )
        db_session.add(Profile(application_id=identifier, score=0.8, recommendation="advance"))
        db_session.add(
            ResumeChunk(
                id=f"{identifier}-row",
                application_id=identifier,
                chunk_idx=0,
                section="skills",
                text=f"{identifier} Python projects",
                char_start=0,
                char_end=19,
                pinecone_id=f"{identifier}#chunk#0",
                embed_model="fake",
            )
        )
    db_session.commit()
    return db_session


def test_profile_and_rank_pool_enforce_job_scope(tool_db):
    assert tools.get_candidate_profile(JOB, "own")["id"] == "own"
    with pytest.raises(ValueError):
        tools.get_candidate_profile(JOB, "foreign")
    assert {row["id"] for row in tools.rank_pool(JOB)} == {"own", "peer"}
    assert tools.get_jd_requirements(JOB) == []


def test_search_hydrates_db_and_rejects_foreign_vector_hits(tool_db, monkeypatch):
    async def hybrid(*args, **kwargs):
        assert kwargs["filter"] == {"application_id": {"$eq": "own"}}
        return [
            RetrievedMatch(
                id="own#chunk#0", score=1, metadata={"text": "forged", "char_start": 999}
            ),
            RetrievedMatch(id="foreign#chunk#0", score=1),
        ]

    monkeypatch.setattr(tools, "hybrid_search", hybrid)
    citations, warnings = tools.search_resume_chunks(JOB, "own", "Python")
    assert [item.chunk_id for item in citations] == ["own-row"]
    assert citations[0].text == "own Python projects"
    assert citations[0].char_start == 0
    assert warnings == []
    with pytest.raises(ValueError):
        tools.search_resume_chunks(JOB, "foreign", "Python")


@pytest.mark.parametrize("mode", ["error", "empty", "failed"])
def test_search_falls_back_to_pg_with_warning(tool_db, monkeypatch, mode):
    async def hybrid(*args, **kwargs):
        if mode == "error":
            raise RuntimeError("vector unavailable")
        return []

    if mode == "failed":
        tool_db.get(Application, "own").vector_status = "failed"
        tool_db.commit()
    monkeypatch.setattr(tools, "hybrid_search", hybrid)
    citations, warnings = tools.search_resume_chunks(JOB, "own", "Python")
    assert citations[0].text == "own Python projects"
    assert warnings


def test_grounding_rehydrates_only_scoped_row_ids(tool_db):
    ids = ["own-row", "peer-row", "foreign-row", "does-not-exist"]
    assert [item.chunk_id for item in tools.validate_citations(JOB, "candidate:own", ids)] == [
        "own-row"
    ]
    assert {item.chunk_id for item in tools.validate_citations(JOB, "pool", ids)} == {
        "own-row",
        "peer-row",
    }
    assert tools.validate_citations(JOB, "pool", []) == []


def test_status_tool_requires_true_confirmation_and_matching_job(tool_db):
    proposal = CopilotProposal(application_id="own", status="pending", reason="HR request")
    with pytest.raises(ValueError):
        tools.update_status(JOB, proposal, confirmed=False)
    assert tool_db.get(Application, "own").status == "analyzed"
    with pytest.raises(ValueError):
        tools.update_status("other-job", proposal, confirmed=True)
    tools.update_status(JOB, proposal, confirmed=True)
    assert tool_db.get(Application, "own").status == "pending"
    assert tool_db.query(Event).filter(Event.application_id == "own").count() == 2


def test_taxonomy_hydrates_pg_and_fallback_is_local(tool_db, monkeypatch):
    tool_db.add(
        SkillTaxonomy(
            id="py",
            canonical="Python",
            alt_labels=["Py"],
            description="A programming language",
            source="onet",
            pinecone_id="skill#py",
        )
    )
    tool_db.commit()

    async def hybrid(*args, **kwargs):
        return [RetrievedMatch(id="skill#py", score=1, metadata={"text": "forged"})]

    monkeypatch.setattr(tools, "hybrid_search", hybrid)
    assert tools.search_taxonomy("Python")[0]["description"] == "A programming language"

    async def failed(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(tools, "hybrid_search", failed)
    assert tools.search_taxonomy("Py")[0]["canonical"] == "Python"


def test_rank_pool_is_bounded_and_status_filtered(tool_db, monkeypatch):
    settings = tools.get_settings().model_copy(update={"copilot_pool_limit": 1})
    monkeypatch.setattr(tools, "get_settings", lambda: settings)
    tool_db.get(Profile, "peer").score = 0.9
    tool_db.commit()
    assert [row["id"] for row in tools.rank_pool(JOB)] == ["peer"]
    assert tools.rank_pool(JOB, status="pending") == []
