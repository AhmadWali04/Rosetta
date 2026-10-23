"""Pure, shared pool-normalized scoring. No database, network or LLM calls."""

import math

from app.config import Settings
from app.graphs.state import ScoreComponents


def normalize_similarities(values: dict[str, float | None]) -> dict[str, float]:
    """Min-max finite observed cosine values; missing values contribute zero.

    Singleton and tied pools yield zero: identical similarities provide no
    relative ranking evidence, and should not earn arbitrary full credit.
    Missing/nonfinite entries never influence the observed bounds.
    """
    finite = {
        key: value for key, value in values.items() if value is not None and math.isfinite(value)
    }
    if not finite:
        return dict.fromkeys(values, 0.0)
    low, high = min(finite.values()), max(finite.values())
    if low == high:
        return dict.fromkeys(values, 0.0)
    return {key: (finite[key] - low) / (high - low) if key in finite else 0.0 for key in values}


def score_profile(
    components: ScoreComponents,
    normalized_similarity: float,
    flags: list[str],
    settings: Settings,
) -> tuple[float, str, float]:
    """Apply configurable PRD weights, thresholds and human-review guardrails."""
    similarity = max(0.0, min(1.0, normalized_similarity))
    weights = settings.scoring_weights
    score = max(
        0.0,
        min(
            1.0,
            weights.must_have_coverage * components.must_have_coverage
            + weights.nice_to_have_coverage * components.nice_to_have_coverage
            + weights.semantic_similarity * similarity
            + weights.depth_signal * components.depth_signal
            - components.penalty,
        ),
    )
    thresholds = settings.scoring_thresholds
    recommendation = "decline"
    if score >= thresholds.advance_min:
        recommendation = "advance"
    elif score >= thresholds.review_min:
        recommendation = "review"
    agreement = 1.0 - abs(components.must_have_coverage - similarity)
    confidence = max(0.0, min(1.0, (components.citation_density + agreement) / 2.0))
    guarded = any(
        "injection" in flag
        or flag
        in {
            "keyword_stuffing",
            "keyword_stuffing_suspected",
        }
        for flag in flags
    )
    if guarded or confidence < settings.scoring_min_confidence:
        recommendation = "review"
    return score, recommendation, confidence
