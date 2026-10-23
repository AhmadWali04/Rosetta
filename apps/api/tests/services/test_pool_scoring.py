"""PRD §9: pool normalization is job-scoped and cannot change human status."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.config import ScoringWeights, Settings
from app.db.models import Application, Event, Job, Profile
from app.services.pool_scoring import recompute_pool

JOB_ID = "job-ai-intern-procogia"


def _settings() -> Settings:
    return Settings(
        scoring_weights=ScoringWeights(
            must_have_coverage=0,
            nice_to_have_coverage=0,
            semantic_similarity=1,
            depth_signal=0,
        )
    )


def _profile(
    db: Session,
    application_id: str,
    raw: float | None,
    *,
    job_id: str = JOB_ID,
    status: str = "analyzed",
    legacy: bool = False,
) -> Profile:
    db.add(
        Application(
            id=application_id,
            job_id=job_id,
            name="Synthetic candidate",
            email="synthetic@example.com",
            resume_path="unused.pdf",
            status=status,
        )
    )
    profile = Profile(
        application_id=application_id,
        score=0.42,
        recommendation="review",
        confidence=0.42,
        score_components=None
        if legacy
        else {
            "must_have_coverage": 0.8,
            "nice_to_have_coverage": 0.5,
            "semantic_similarity_raw": raw,
            "depth_signal": 0.6,
            "penalty": 0,
            "citation_density": 1,
        },
    )
    db.add(profile)
    db.flush()
    return profile


def test_recompute_pool_updates_both_candidates_and_audits_changes(db_session: Session) -> None:
    low = _profile(db_session, "low", 0.2)
    high = _profile(db_session, "high", 0.8)

    recompute_pool(db_session, JOB_ID, _settings())
    db_session.flush()

    assert low.score == pytest.approx(0)
    assert high.score == pytest.approx(1)
    assert low.recommendation == "decline"
    assert high.recommendation == "advance"
    assert low.confidence == pytest.approx(0.6)
    assert high.confidence == pytest.approx(0.9)
    events = db_session.query(Event).filter_by(action="score_recomputed").all()
    assert {event.application_id for event in events} == {"low", "high"}
    assert all(event.actor == "system" for event in events)
    assert all(event.payload for event in events)

    # Repeating an unchanged computation must not manufacture audit changes.
    recompute_pool(db_session, JOB_ID, _settings())
    db_session.flush()
    assert db_session.query(Event).filter_by(action="score_recomputed").count() == 2


def test_new_extreme_recomputes_existing_pool_member(db_session: Session) -> None:
    low = _profile(db_session, "low", 0.2)
    middle = _profile(db_session, "middle", 0.5)
    recompute_pool(db_session, JOB_ID, _settings())
    assert middle.score == pytest.approx(1)
    high = _profile(db_session, "high", 0.8)

    recompute_pool(db_session, JOB_ID, _settings())

    assert low.score == pytest.approx(0)
    assert middle.score == pytest.approx(0.5)
    assert high.score == pytest.approx(1)


def test_pool_bounds_do_not_include_other_jobs_or_legacy_profiles(db_session: Session) -> None:
    db_session.add(Job(id="other-job", title="Other", raw_jd="JD", requirements=[]))
    db_session.flush()
    low = _profile(db_session, "low", 0.2)
    high = _profile(db_session, "high", 0.8)
    other = _profile(db_session, "other", 100, job_id="other-job")
    legacy = _profile(db_session, "legacy", 100, legacy=True)

    recompute_pool(db_session, JOB_ID, _settings())
    db_session.flush()

    assert low.score == pytest.approx(0)
    assert high.score == pytest.approx(1)
    assert other.score == pytest.approx(0.42)
    assert legacy.score == pytest.approx(0.42)
    assert other.confidence == pytest.approx(0.42)
    assert legacy.recommendation == "review"
    audited = {event.application_id for event in db_session.query(Event).all()}
    assert "other" not in audited
    assert "legacy" not in audited


@pytest.mark.parametrize(
    "raw_values, expected",
    [
        ([None, 0.2, 0.8], [0, 0, 1]),
        ([0.5, 0.5], [0, 0]),
        ([None, None], [0, 0]),
        ([0.5], [0]),
    ],
)
def test_missing_and_constant_similarity_have_no_relative_advantage(
    db_session: Session,
    raw_values: list[float | None],
    expected: list[float],
) -> None:
    profiles = [_profile(db_session, f"app-{index}", raw) for index, raw in enumerate(raw_values)]

    recompute_pool(db_session, JOB_ID, _settings())

    assert [profile.score for profile in profiles] == pytest.approx(expected)


@pytest.mark.parametrize("status", ["pending", "valid", "rejected", "tech_review", "invited"])
def test_recompute_never_changes_human_status(db_session: Session, status: str) -> None:
    _profile(db_session, "candidate", 0.8, status=status)

    recompute_pool(db_session, JOB_ID, _settings())
    db_session.flush()

    application = db_session.get(Application, "candidate")
    assert application is not None
    assert application.status == status
