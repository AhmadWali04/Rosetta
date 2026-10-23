"""Unit test for `scorer` (PRD §9) — deterministic, no LLM call, so there's
no excuse for an untested edge case (this agent's own task brief, verbatim).

Two layers of tests:
1. Pure-function tests against `_coverage`/`_depth_signal_average`/
   `_keyword_stuffing_penalty`/`_confidence`/`_recommendation`/`_cosine` —
   no DB, no settings, hand-computed expected values.
2. Full-node tests against `scorer(state)` with a real sqlite-in-memory
   `jobs`/`jd_requirements` table (same fixture pattern as the other node
   tests in this package), hand-computed end-to-end expected scores.

All full-node cases force `state.summary_vector = []` so `semantic_similarity`
is deterministically `0.0` without depending on `app.rag.embeddings`'s
hash-based fake embedder's exact output - keeps the hand-computed
arithmetic simple and exact.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

import app.db.session as db_session
from app.config import ScoringThresholds, ScoringWeights, get_settings
from app.db.models import Base, JdRequirement, Job
from app.graphs.intake.scorer import (
    _confidence,
    _coverage,
    _depth_signal_average,
    _keyword_stuffing_penalty,
    _recommendation,
    scorer,
)
from app.graphs.state import ExtractedSkill, IntakeState, NormalizedSkill, RequirementMatch

WEIGHTS = ScoringWeights()  # 0.50 / 0.20 / 0.15 / 0.15 defaults
THRESHOLDS = ScoringThresholds()  # advance_min=0.70, review_min=0.45


# ---------------------------------------------------------------------------
# Pure-function tests
# ---------------------------------------------------------------------------


def _match(req_id: str, status: str) -> RequirementMatch:
    return RequirementMatch(requirement_id=req_id, status=status, resolved_chunk_ids=["c0"])


def test_coverage_weighted_average() -> None:
    matches = [_match("r1", "met"), _match("r2", "missing")]
    weight_by_id = {"r1": 2.0, "r2": 1.0}
    kind_by_id = {"r1": "must_have", "r2": "must_have"}

    coverage = _coverage(matches, weight_by_id, kind_by_id, "must_have")

    # (2.0*1.0 + 1.0*0.0) / (2.0 + 1.0) = 2/3
    assert coverage == pytest.approx(2.0 / 3.0)


def test_coverage_partial_status_counts_as_half() -> None:
    matches = [_match("r1", "partial")]
    coverage = _coverage(matches, {"r1": 1.0}, {"r1": "must_have"}, "must_have")
    assert coverage == pytest.approx(0.5)


def test_coverage_ignores_other_kind() -> None:
    matches = [_match("r1", "met")]
    coverage = _coverage(matches, {"r1": 1.0}, {"r1": "nice_to_have"}, "must_have")
    assert coverage == 0.0


def test_coverage_defaults_to_zero_with_no_requirements_of_that_kind() -> None:
    assert _coverage([], {}, {}, "must_have") == 0.0


def test_depth_signal_average_known_values() -> None:
    skills = [
        NormalizedSkill(
            extracted=ExtractedSkill(
                skill="a", evidence_span="", context="", recency="", depth_signal=d
            ),
            canonical=None,
            taxonomy_id=None,
        )
        for d in ["list_only", "coursework", "project", "production"]
    ]
    state = IntakeState(
        application_id="a1", job_id="j1", resume_path="r.pdf", normalized_skills=skills
    )
    avg = _depth_signal_average(state)
    # (0.2 + 0.5 + 0.8 + 1.0) / 4 = 0.625
    assert avg == pytest.approx(0.625)


def test_depth_signal_average_empty_is_zero() -> None:
    state = IntakeState(application_id="a1", job_id="j1", resume_path="r.pdf")
    assert _depth_signal_average(state) == 0.0


def test_depth_signal_average_unknown_value_falls_back_to_list_only_weight() -> None:
    skill = NormalizedSkill(
        extracted=ExtractedSkill(
            skill="a", evidence_span="", context="", recency="", depth_signal="not_a_real_value"
        ),
        canonical=None,
        taxonomy_id=None,
    )
    state = IntakeState(
        application_id="a1", job_id="j1", resume_path="r.pdf", normalized_skills=[skill]
    )
    assert _depth_signal_average(state) == pytest.approx(0.2)


def test_keyword_stuffing_penalty_proportional() -> None:
    def _skill(depth: str) -> NormalizedSkill:
        return NormalizedSkill(
            extracted=ExtractedSkill(
                skill="a", evidence_span="", context="", recency="", depth_signal=depth
            ),
            canonical=None,
            taxonomy_id=None,
        )

    state = IntakeState(
        application_id="a1",
        job_id="j1",
        resume_path="r.pdf",
        normalized_skills=[_skill("list_only"), _skill("list_only"), _skill("production")],
    )
    # 2 of 3 are list_only -> 0.10 * (2/3)
    assert _keyword_stuffing_penalty(state) == pytest.approx(0.10 * (2 / 3))


def test_keyword_stuffing_penalty_zero_when_no_skills() -> None:
    state = IntakeState(application_id="a1", job_id="j1", resume_path="r.pdf")
    assert _keyword_stuffing_penalty(state) == 0.0


def test_recommendation_thresholds() -> None:
    assert _recommendation(0.70, THRESHOLDS) == "advance"
    assert _recommendation(0.69, THRESHOLDS) == "review"
    assert _recommendation(0.45, THRESHOLDS) == "review"
    assert _recommendation(0.44, THRESHOLDS) == "decline"


def test_confidence_high_citation_density_and_agreement() -> None:
    matches = [_match("r1", "met")]  # resolved_chunk_ids non-empty
    confidence = _confidence(matches, must_have_coverage=0.8, semantic_similarity=0.8)
    # citation_density=1.0, agreement=1-|0.8-0.8|=1.0 -> (1+1)/2 = 1.0
    assert confidence == pytest.approx(1.0)


def test_confidence_zero_requirement_matches() -> None:
    confidence = _confidence([], must_have_coverage=0.0, semantic_similarity=0.0)
    # citation_density=0.0 (no matches at all), agreement=1-|0-0|=1.0 -> 0.5
    assert confidence == pytest.approx(0.5)


def test_confidence_divergent_signals_lowers_agreement() -> None:
    matches = [RequirementMatch(requirement_id="r1", status="met", resolved_chunk_ids=[])]
    confidence = _confidence(matches, must_have_coverage=1.0, semantic_similarity=0.0)
    # citation_density=0.0 (no resolved citations), agreement=1-|1-0|=0.0 -> 0.0
    assert confidence == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Full-node tests
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    test_session_local = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "SessionLocal", test_session_local)
    yield engine


def _seed_job(
    engine: Engine, *, job_id: str = "j1", requirements: list[tuple[str, str, float]]
) -> None:
    """`requirements` is a list of (id, kind, weight) tuples."""
    session_local = sessionmaker(bind=engine)
    with session_local() as session:
        session.add(Job(id=job_id, title="t", raw_jd="irrelevant jd text", requirements=[]))
        for req_id, kind, weight in requirements:
            session.add(
                JdRequirement(
                    id=req_id,
                    job_id=job_id,
                    text=f"requirement {req_id}",
                    kind=kind,
                    weight=weight,
                    pinecone_id=f"req#{req_id}",
                )
            )
        session.commit()


def _production_skill() -> NormalizedSkill:
    return NormalizedSkill(
        extracted=ExtractedSkill(
            skill="PyTorch",
            evidence_span="",
            context="",
            recency="",
            depth_signal="production",
        ),
        canonical="PyTorch",
        taxonomy_id="tax1",
    )


def test_scorer_advance_case(sqlite_engine: Engine) -> None:
    _seed_job(sqlite_engine, requirements=[("r1", "must_have", 1.0), ("r2", "nice_to_have", 1.0)])
    state = IntakeState(
        application_id="a1",
        job_id="j1",
        resume_path="r.pdf",
        requirement_matches=[
            RequirementMatch(requirement_id="r1", status="met", resolved_chunk_ids=["c0"]),
            RequirementMatch(requirement_id="r2", status="met", resolved_chunk_ids=["c0"]),
        ],
        normalized_skills=[_production_skill()],
        summary_vector=[],  # forces semantic_similarity == 0.0
    )

    result = scorer(state)

    # 0.50*1.0 + 0.20*1.0 + 0.15*0.0 + 0.15*1.0 - 0 = 0.85
    assert result["score"] == pytest.approx(0.85)
    assert result["recommendation"] == "advance"
    # citation_density=1.0, agreement=1-|1.0-0.0|=0.0 -> confidence=0.5
    assert result["confidence"] == pytest.approx(0.5)


def test_scorer_injection_flag_forces_review_without_changing_score(
    sqlite_engine: Engine,
) -> None:
    _seed_job(sqlite_engine, requirements=[("r1", "must_have", 1.0), ("r2", "nice_to_have", 1.0)])
    state = IntakeState(
        application_id="a1",
        job_id="j1",
        resume_path="r.pdf",
        flags=["prompt_injection_suspected"],
        requirement_matches=[
            RequirementMatch(requirement_id="r1", status="met", resolved_chunk_ids=["c0"]),
            RequirementMatch(requirement_id="r2", status="met", resolved_chunk_ids=["c0"]),
        ],
        normalized_skills=[_production_skill()],
        summary_vector=[],
    )

    result = scorer(state)

    # Same honest score as the advance case above...
    assert result["score"] == pytest.approx(0.85)
    # ...but the recommendation is overridden to "review" regardless
    # (AGENTS.md invariant #3 / PRD §9).
    assert result["recommendation"] == "review"


def test_scorer_decline_case_no_matches_no_skills(sqlite_engine: Engine) -> None:
    _seed_job(sqlite_engine, requirements=[("r1", "must_have", 1.0), ("r2", "nice_to_have", 1.0)])
    state = IntakeState(application_id="a1", job_id="j1", resume_path="r.pdf", summary_vector=[])

    result = scorer(state)

    assert result["score"] == pytest.approx(0.0)
    assert result["recommendation"] == "decline"
    assert result["confidence"] == pytest.approx(0.5)


def test_scorer_review_band_case(sqlite_engine: Engine) -> None:
    _seed_job(sqlite_engine, requirements=[("r1", "must_have", 1.0)])
    state = IntakeState(
        application_id="a1",
        job_id="j1",
        resume_path="r.pdf",
        requirement_matches=[
            RequirementMatch(requirement_id="r1", status="met", resolved_chunk_ids=["c0"]),
        ],
        normalized_skills=[_production_skill()],
        summary_vector=[],
    )

    result = scorer(state)

    # 0.50*1.0 + 0.20*0.0(no nice_to_have reqs) + 0.15*0.0 + 0.15*1.0 = 0.65
    assert result["score"] == pytest.approx(0.65)
    assert result["recommendation"] == "review"


def test_scorer_score_is_clamped_to_zero_not_negative(sqlite_engine: Engine) -> None:
    _seed_job(sqlite_engine, requirements=[])
    list_only_skill = NormalizedSkill(
        extracted=ExtractedSkill(
            skill="a", evidence_span="", context="", recency="", depth_signal="list_only"
        ),
        canonical=None,
        taxonomy_id=None,
    )
    state = IntakeState(
        application_id="a1",
        job_id="j1",
        resume_path="r.pdf",
        normalized_skills=[list_only_skill],
        summary_vector=[],
    )

    result = scorer(state)

    # 0.15*0.2 - 0.10*1.0 = 0.03 - 0.10 = -0.07 -> clamped to 0.0
    assert result["score"] == pytest.approx(0.0)
    assert result["recommendation"] == "decline"


def test_scorer_reads_weights_from_settings_not_hardcoded(
    sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AGENTS.md: 'No hardcoded ... score weights' — scorer must actually
    consult `settings.scoring_weights`, not PRD §9's literal numbers."""
    _seed_job(sqlite_engine, requirements=[("r1", "must_have", 1.0)])
    custom_settings = get_settings().model_copy(
        update={
            "scoring_weights": ScoringWeights(
                must_have_coverage=1.0,
                nice_to_have_coverage=0.0,
                semantic_similarity=0.0,
                depth_signal=0.0,
            )
        }
    )
    monkeypatch.setattr("app.graphs.intake.scorer.get_settings", lambda: custom_settings)
    state = IntakeState(
        application_id="a1",
        job_id="j1",
        resume_path="r.pdf",
        requirement_matches=[
            RequirementMatch(requirement_id="r1", status="met", resolved_chunk_ids=["c0"]),
        ],
        summary_vector=[],
    )

    result = scorer(state)

    # With must_have_coverage weight=1.0 and everything else zeroed out:
    # score == must_have_coverage == 1.0
    assert result["score"] == pytest.approx(1.0)
