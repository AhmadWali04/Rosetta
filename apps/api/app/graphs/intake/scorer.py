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

from app.config import ScoringThresholds, Settings, get_settings
from app.db.models import JdRequirement, Job
from app.db.session import session_scope
from app.graphs.state import IntakeState, RequirementMatch, ScoreComponents
from app.rag.embeddings import get_embedder
from app.services.scoring import score_profile

logger = logging.getLogger("skillbridge.intake.scorer")

_STATUS_VALUE = {"met": 1.0, "partial": 0.5, "missing": 0.0}


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


def _depth_signal_average(state: IntakeState, settings: Settings | None = None) -> float:
    if not state.normalized_skills:
        # No skills extracted/normalized at all — no depth evidence exists,
        # so 0.0 rather than some assumed middle value.
        return 0.0
    depth_values = (settings or get_settings()).scoring_depth_values
    values = [
        depth_values.get(ns.extracted.depth_signal, depth_values["list_only"])
        for ns in state.normalized_skills
    ]
    return sum(values) / len(values)


def _keyword_stuffing_penalty(state: IntakeState, settings: Settings | None = None) -> float:
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
    return (settings or get_settings()).keyword_stuffing_max_penalty * ratio


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
    """Raw cosine retained for transactional pool normalization at persistence.

    This node computes a provisional score; committed profile scores are
    recomputed across the job pool from these reproducible components.
    """
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
    settings: Settings,
) -> dict[str, Any]:
    similarity = await _semantic_similarity(state, job_raw_jd) if state.summary_vector else None
    components = ScoreComponents(
        must_have_coverage=_coverage(
            state.requirement_matches, weight_by_id, kind_by_id, "must_have"
        ),
        nice_to_have_coverage=_coverage(
            state.requirement_matches, weight_by_id, kind_by_id, "nice_to_have"
        ),
        semantic_similarity_raw=similarity,
        depth_signal=_depth_signal_average(state, settings),
        penalty=_keyword_stuffing_penalty(state, settings),
        citation_density=(
            sum(bool(match.resolved_chunk_ids) for match in state.requirement_matches)
            / len(state.requirement_matches)
            if state.requirement_matches
            else 0.0
        ),
    )
    flags = list(state.flags)
    total = len(state.normalized_skills)
    list_only = sum(
        skill.extracted.depth_signal == "list_only" for skill in state.normalized_skills
    )
    if (
        total >= settings.keyword_stuffing_min_skills
        and list_only / total >= settings.keyword_stuffing_ratio_threshold
        and "keyword_stuffing_suspected" not in flags
    ):
        flags.append("keyword_stuffing_suspected")
    score, recommendation, confidence = score_profile(
        components,
        max(0.0, min(1.0, similarity or 0.0)),
        flags,
        settings,
    )
    return {
        "score": score,
        "recommendation": recommendation,
        "confidence": confidence,
        "score_components": components,
        "flags": flags,
    }


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
            settings,
        )
    )
