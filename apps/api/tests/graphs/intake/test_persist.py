"""Unit test for `persist` (PRD §7.1 final node).

Unlike the other three node tests in this package, `persist` depends only
on files that already exist on disk (`app/db/models.py`, `app/db/session.py`,
`app/graphs/state.py`) — no dependency on Agent A's or Agent B's
in-progress files — so this test should run standalone right now.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

import app.db.session as db_session
from app.db.models import Application, Base, Event, Job, Profile
from app.graphs.intake.persist import persist
from app.graphs.state import ExtractedSkill, IntakeState, NormalizedSkill, RequirementMatch


@pytest.fixture
def sqlite_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    test_session_local = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "SessionLocal", test_session_local)
    yield engine


def _seed_application(engine: Engine, application_id: str, job_id: str) -> None:
    session_local = sessionmaker(bind=engine)
    with session_local() as session:
        session.add(Job(id=job_id, title="t", raw_jd="jd", requirements=[]))
        session.add(
            Application(
                id=application_id,
                job_id=job_id,
                name="n",
                email="e@example.com",
                resume_path="resume.pdf",
            )
        )
        session.commit()


def _state(score: float = 0.82, recommendation: str = "advance") -> IntakeState:
    extracted = ExtractedSkill(
        skill="PyTorch",
        evidence_span="used PyTorch",
        context="projects",
        recency="recent",
        depth_signal="project",
    )
    normalized = NormalizedSkill(extracted=extracted, canonical="PyTorch", taxonomy_id="pytorch")
    match = RequirementMatch(
        requirement_id="r1",
        status="met",
        cited_chunk_ids=["a1#chunk#0"],
        resolved_chunk_ids=["a1#chunk#0"],
        rationale="candidate used PyTorch in a shipped project",
    )
    return IntakeState(
        application_id="a1",
        job_id="j1",
        resume_path="resume.pdf",
        normalized_skills=[normalized],
        requirement_matches=[match],
        score=score,
        recommendation=recommendation,
        confidence=0.9,
        explanation="Strong match on PyTorch experience.",
    )


@pytest.mark.asyncio
async def test_persist_writes_profile_and_marks_analyzed(sqlite_engine: Engine) -> None:
    _seed_application(sqlite_engine, "a1", "j1")

    result = await persist(_state())

    assert result == {"score": 0.82, "recommendation": "advance", "confidence": 0.9}

    session_local = sessionmaker(bind=sqlite_engine)
    with session_local() as session:
        profile = session.get(Profile, "a1")
        assert profile is not None
        assert profile.recommendation == "advance"
        assert profile.score == pytest.approx(0.82)
        assert profile.skills[0]["canonical"] == "PyTorch"
        assert profile.requirement_matches[0]["requirement_id"] == "r1"

        app_row = session.get(Application, "a1")
        assert app_row is not None
        assert app_row.status == "analyzed"

        events = session.query(Event).filter_by(application_id="a1").all()
        assert any(e.action == "intake_complete" for e in events)


@pytest.mark.asyncio
async def test_persist_overwrites_existing_profile(sqlite_engine: Engine) -> None:
    _seed_application(sqlite_engine, "a1", "j1")
    await persist(_state())
    await persist(_state(score=0.1, recommendation="decline"))

    session_local = sessionmaker(bind=sqlite_engine)
    with session_local() as session:
        profile = session.get(Profile, "a1")
        assert profile is not None
        assert profile.recommendation == "decline"
        assert profile.score == pytest.approx(0.1)

        # Exactly one Profile row ever exists for this application.
        all_profiles = session.query(Profile).filter_by(application_id="a1").all()
        assert len(all_profiles) == 1


@pytest.mark.asyncio
async def test_persist_missing_application_raises(sqlite_engine: Engine) -> None:
    with pytest.raises(ValueError, match="no Application row"):
        await persist(_state())


@pytest.mark.asyncio
@pytest.mark.parametrize("human_status", ["pending", "valid", "rejected", "tech_review", "invited"])
async def test_persist_rerun_preserves_human_decision(
    sqlite_engine: Engine, human_status: str
) -> None:
    _seed_application(sqlite_engine, "a1", "j1")
    session_local = sessionmaker(bind=sqlite_engine)
    with session_local() as session:
        application = session.get(Application, "a1")
        assert application is not None
        application.status = human_status
        session.commit()

    await persist(_state())

    with session_local() as session:
        application = session.get(Application, "a1")
        assert application is not None
        assert application.status == human_status
        assert session.query(Event).filter_by(action="intake_complete").count() == 1


@pytest.mark.asyncio
async def test_persist_rerun_replaces_score_components_and_returns_pool_score(
    sqlite_engine: Engine,
) -> None:
    _seed_application(sqlite_engine, "a1", "j1")
    components = {
        "must_have_coverage": 0.4,
        "nice_to_have_coverage": 0.25,
        "semantic_similarity_raw": 0.2,
        "depth_signal": 0.6,
        "penalty": 0.05,
        "citation_density": 0.8,
    }
    first = IntakeState.model_validate({**_state().model_dump(), "score_components": components})
    await persist(first)
    second = IntakeState.model_validate(
        {
            **_state().model_dump(),
            "score_components": {**components, "semantic_similarity_raw": 0.9},
        }
    )

    result = await persist(second)

    session_local = sessionmaker(bind=sqlite_engine)
    with session_local() as session:
        profiles = session.query(Profile).filter_by(application_id="a1").all()
        assert len(profiles) == 1
        profile = profiles[0]
        assert profile.score_components == {**components, "semantic_similarity_raw": 0.9}
        # A one-candidate pool has no relative semantic advantage.
        assert profile.score == pytest.approx(0.29)
        assert result["score"] == pytest.approx(profile.score)
        assert result["recommendation"] == profile.recommendation
        assert result["confidence"] == pytest.approx(profile.confidence)
        assert session.query(Event).filter_by(action="intake_complete").count() == 2


@pytest.mark.asyncio
async def test_persist_mismatched_job_writes_nothing(sqlite_engine: Engine) -> None:
    _seed_application(sqlite_engine, "a1", "j1")
    state = _state().model_copy(update={"job_id": "different-job"})

    with pytest.raises(ValueError, match="does not belong"):
        await persist(state)

    with Session(sqlite_engine) as session:
        assert session.get(Profile, "a1") is None
        application = session.get(Application, "a1")
        assert application is not None
        assert application.status == "submitted"
        assert session.query(Event).count() == 0


@pytest.mark.asyncio
async def test_failed_intake_commit_rolls_back_pool_scores_and_audits(
    sqlite_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_application(sqlite_engine, "a1", "j1")
    await persist(_state())
    components = {
        "must_have_coverage": 0.4,
        "nice_to_have_coverage": 0.25,
        "semantic_similarity_raw": 0.1,
        "depth_signal": 0.6,
        "penalty": 0.05,
        "citation_density": 0.8,
    }
    with Session(sqlite_engine) as session:
        session.add(
            Application(
                id="peer",
                job_id="j1",
                name="Peer",
                email="peer@example.com",
                resume_path="unused.pdf",
                status="valid",
            )
        )
        session.add(
            Profile(
                application_id="peer",
                score=0.42,
                confidence=0.5,
                recommendation="review",
                score_components=components,
            )
        )
        session.commit()

    def fail_commit(_session: Session) -> None:
        raise RuntimeError("simulated final commit failure")

    state = IntakeState.model_validate(
        {
            **_state().model_dump(),
            "score_components": {**components, "semantic_similarity_raw": 0.9},
        }
    )
    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="simulated final commit failure"):
            await persist(state)

    with Session(sqlite_engine) as session:
        candidate = session.get(Profile, "a1")
        peer = session.get(Profile, "peer")
        assert candidate is not None and peer is not None
        assert candidate.score == pytest.approx(0.82)
        assert candidate.score_components is None
        assert peer.score == pytest.approx(0.42)
        assert peer.confidence == pytest.approx(0.5)
        assert peer.recommendation == "review"
        assert session.query(Event).filter_by(action="score_recomputed").count() == 0
        assert session.query(Event).filter_by(action="intake_complete").count() == 1
