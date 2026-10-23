"""PRD §9 Scorer node — deterministic, no LLM call.

    score = w.must_have_coverage   * must_have_coverage
          + w.nice_to_have_coverage * nice_to_have_coverage
          + w.semantic_similarity   * semantic_similarity
          + w.depth_signal          * depth_signal
          - penalties

Weights come from `settings.scoring_weights` (never hardcoded here, per
AGENTS.md "No hardcoded ... score weights"), even though their current
defaults happen to equal the PRD's literal 0.50/0.20/0.15/0.15.

Depends on, and confirmed against, Agent C's `app.db.session.session_scope`
(`with session_scope() as session: ...`) to fetch
`JdRequirement.weight`/`.kind` and `Job.raw_jd`.

Sync, matching the convention `graph.py` settled on for the whole intake
graph — the only awaited call anywhere in this module is the on-the-fly
JD embedding in `_semantic_similarity`, bridged with a single
`asyncio.run(...)` at the node's entry point.
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

from sqlalchemy.orm import Session

from app.config import ScoringThresholds, ScoringWeights, Settings, get_settings
from app.db.models import JdRequirement, Job
from app.db.session import session_scope
from app.graphs.state import IntakeState, RequirementMatch
from app.rag.embeddings import get_embedder

logger = logging.getLogger("skillbridge.intake.scorer")

_STATUS_VALUE = {"met": 1.0, "partial": 0.5, "missing": 0.0}

# PRD §9: "depth signal distinguishes 'listed in Skills' vs 'used in a
# shipped project'". PRD gives no exact numbers for the four tiers — this
# mapping is a documented judgment call. Unknown/unrecognised depth_signal
# strings fall back to the `list_only` weight (treat unverifiable depth as
# minimal-evidence, not zero-evidence and not full credit).
_DEPTH_SIGNAL_VALUE = {
    "list_only": 0.2,
    "coursework": 0.5,
    "project": 0.8,
    "production": 1.0,
}
_DEPTH_SIGNAL_UNKNOWN_DEFAULT = _DEPTH_SIGNAL_VALUE["list_only"]

# Simple, optional keyword-stuffing signal (PRD §9 lists the full detector
# as a stretch item). Proportional penalty capped at this many score
# points, scaled by the fraction of skills that are list_only-only
# evidence — deliberately small so it nudges, rather than dominates, the
# score.
_KEYWORD_STUFFING_MAX_PENALTY = 0.10


def _coverage(
    requirement_matches: list[RequirementMatch],
    weight_by_id: dict[str, float],
    kind_by_id: dict[str, str],
    kind: str,
) -> float:
    """Weighted average of met=1/partial=0.5/missing=0 over the
    must-have or nice-to-have requirement subset (PRD §9)."""
    total_weight = 0.0
    weighted_sum = 0.0
    for match in requirement_matches:
        if kind_by_id.get(match.requirement_id) != kind:
            continue
        weight = weight_by_id.get(match.requirement_id, 1.0)
        value = _STATUS_VALUE.get(match.status, 0.0)
        weighted_sum += weight * value
        total_weight += weight
    if total_weight == 0.0:
        # No requirements of this kind for the job (or none matched) — PRD
        # doesn't specify a default; 0.0 is the conservative choice (no
        # claimed coverage of a subset that was never evaluated), rather
        # than silently inflating the score via a 1.0 default.
        return 0.0
    return weighted_sum / total_weight


def _depth_signal_average(state: IntakeState) -> float:
    if not state.normalized_skills:
        # No skills extracted/normalized at all — no depth evidence exists,
        # so 0.0 rather than some assumed middle value.
        return 0.0
    values = [
        _DEPTH_SIGNAL_VALUE.get(ns.extracted.depth_signal, _DEPTH_SIGNAL_UNKNOWN_DEFAULT)
        for ns in state.normalized_skills
    ]
    return sum(values) / len(values)


def _keyword_stuffing_penalty(state: IntakeState) -> float:
    """Optional, cheap stuffing signal: ratio of skills with no evidence
    beyond a bare list vs total skills, scaled into a small penalty. Not
    PRD §9's full keyword-stuffing detector (n-gram JD overlap etc) — that
    stays a stretch item; this is the "simple proportional penalty" the
    task brief explicitly says is enough for M1."""
    if not state.normalized_skills:
        return 0.0
    total = len(state.normalized_skills)
    list_only = sum(1 for ns in state.normalized_skills if ns.extracted.depth_signal == "list_only")
    ratio = list_only / total
    return _KEYWORD_STUFFING_MAX_PENALTY * ratio


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


async def _semantic_similarity(state: IntakeState, job_raw_jd: str) -> float:
    """Cosine of the candidate summary vector vs a fresh embedding of the
    job's raw JD text. PRD §9's literal wording says "min-max normalised
    across pool" — deliberately NOT implemented here: M1 processes one
    applicant at a time, there is no pool to normalize against yet. Using
    the raw cosine directly is a documented M2 deferral (the HR portal's
    pool-wide table/ranking is where a pool-wide min-max normalization
    actually makes sense). No caching of the JD embedding either — embedded
    fresh every call, flagged as a known latency cost, not a bug (PRD §11
    p95 < 30s is the thing to watch if this becomes a problem)."""
    if not state.summary_vector:
        return 0.0
    embedder = get_embedder()
    [job_vector] = await embedder.embed_dense([job_raw_jd])
    return _cosine(state.summary_vector, job_vector)


def _confidence(
    requirement_matches: list[RequirementMatch],
    must_have_coverage: float,
    semantic_similarity: float,
) -> float:
    """PRD §9: "agreement between LLM judgement and embedding signal +
    citation density". No exact formula given — documented judgment call:

        citation_density = fraction of requirement_matches whose
                            resolved_chunk_ids is non-empty
                            (0.0 if there are no requirement_matches at all)

        agreement = 1 - |must_have_coverage - semantic_similarity|
                    (both signals high, or both low, => high agreement;
                    a sharp divergence between the LLM-judged coverage and
                    the raw embedding similarity => low agreement)

        confidence = (citation_density + agreement) / 2, clamped to [0, 1]
    """
    if requirement_matches:
        cited = sum(1 for m in requirement_matches if m.resolved_chunk_ids)
        citation_density = cited / len(requirement_matches)
    else:
        citation_density = 0.0

    agreement = 1.0 - abs(must_have_coverage - semantic_similarity)
    confidence = (citation_density + agreement) / 2.0
    return max(0.0, min(1.0, confidence))


def _recommendation(score: float, thresholds: ScoringThresholds) -> str:
    if score >= thresholds.advance_min:
        return "advance"
    if score >= thresholds.review_min:
        return "review"
    return "decline"


def _fetch_job_and_requirements(
    session: Session, job_id: str
) -> tuple[str, dict[str, float], dict[str, str]]:
    job = session.get(Job, job_id)
    job_raw_jd = job.raw_jd if job is not None else ""
    if job is None:
        logger.warning("scorer: job %s not found in Postgres; treating raw_jd as empty", job_id)

    requirements = session.query(JdRequirement).filter(JdRequirement.job_id == job_id).all()
    weight_by_id = {r.id: r.weight for r in requirements}
    kind_by_id = {r.id: r.kind for r in requirements}
    return job_raw_jd, weight_by_id, kind_by_id


async def _compute(
    state: IntakeState,
    job_raw_jd: str,
    weight_by_id: dict[str, float],
    kind_by_id: dict[str, str],
    weights: ScoringWeights,
    thresholds: ScoringThresholds,
) -> dict[str, Any]:
    must_have_coverage = _coverage(state.requirement_matches, weight_by_id, kind_by_id, "must_have")
    nice_to_have_coverage = _coverage(
        state.requirement_matches, weight_by_id, kind_by_id, "nice_to_have"
    )
    semantic_similarity = await _semantic_similarity(state, job_raw_jd)
    depth_signal = _depth_signal_average(state)
    penalty = _keyword_stuffing_penalty(state)

    raw_score = (
        weights.must_have_coverage * must_have_coverage
        + weights.nice_to_have_coverage * nice_to_have_coverage
        + weights.semantic_similarity * semantic_similarity
        + weights.depth_signal * depth_signal
        - penalty
    )
    score = max(0.0, min(1.0, raw_score))

    recommendation = _recommendation(score, thresholds)

    # AGENTS.md invariant #3 / PRD §9: an injection flag must force
    # "review" regardless of score — applied AFTER the threshold lookup,
    # as an override on `recommendation`, not by mangling `score` into
    # meaninglessness. `score` stays an honest number either way.
    if "prompt_injection_suspected" in state.flags:
        if recommendation != "review":
            logger.info(
                "scorer: application %s recommendation overridden %s -> review "
                "(prompt_injection_suspected flag set; score=%.4f unchanged)",
                state.application_id,
                recommendation,
                score,
            )
        recommendation = "review"

    confidence = _confidence(state.requirement_matches, must_have_coverage, semantic_similarity)

    return {"score": score, "recommendation": recommendation, "confidence": confidence}


def scorer(state: IntakeState) -> dict[str, Any]:
    """Node function: `(IntakeState) -> partial state update`. Sync entry
    point; deterministic and LLM-free, but bridges the one awaited call
    (the on-the-fly JD embedding) with `asyncio.run(...)`, same pattern as
    every other node in this package."""
    settings: Settings = get_settings()
    with session_scope() as session:
        job_raw_jd, weight_by_id, kind_by_id = _fetch_job_and_requirements(session, state.job_id)
    return asyncio.run(
        _compute(
            state,
            job_raw_jd,
            weight_by_id,
            kind_by_id,
            settings.scoring_weights,
            settings.scoring_thresholds,
        )
    )
