"""PRD §9 pure scoring and normalization regression tests."""

import pytest

from app.config import ScoringThresholds, ScoringWeights, Settings
from app.graphs.state import ScoreComponents
from app.services.scoring import normalize_similarities, score_profile


def components(**changes):
    return ScoreComponents(
        must_have_coverage=1,
        nice_to_have_coverage=1,
        semantic_similarity_raw=0.8,
        depth_signal=1,
        penalty=0,
        citation_density=1,
    ).model_copy(update=changes)


def test_normalize_negative_cosines_missing_and_nonfinite():
    values = {
        "low": -0.8,
        "middle": -0.2,
        "high": 0.4,
        "absent": None,
        "nan": float("nan"),
        "infinite": float("inf"),
    }
    result = normalize_similarities(values)
    assert result == pytest.approx(
        {"low": 0, "middle": 0.5, "high": 1, "absent": 0, "nan": 0, "infinite": 0}
    )
    assert values["middle"] == -0.2


@pytest.mark.parametrize(
    "values", [{}, {"a": None}, {"a": 0.8}, {"a": 0.8, "b": 0.8, "missing": None}]
)
def test_equal_or_absent_values_provide_no_relative_credit(values):
    assert normalize_similarities(values) == dict.fromkeys(values, 0.0)


def test_formula_and_confidence_use_normalized_semantic_signal():
    result = score_profile(
        components(
            must_have_coverage=0.8, nice_to_have_coverage=0.5, penalty=0.1, citation_density=0.6
        ),
        0.2,
        [],
        Settings(),
    )
    score, recommendation, confidence = result
    assert score == pytest.approx(0.58)
    assert recommendation == "review"
    assert confidence == pytest.approx(0.5)


@pytest.mark.parametrize(
    "flag",
    [
        "prompt_injection_suspected",
        "keyword_stuffing",
        "keyword_stuffing_suspected",
        "injection_attempt",
    ],
)
def test_guardrails_override_high_score_without_altering_number(flag):
    score, recommendation, confidence = score_profile(components(), 1, [flag], Settings())
    assert score == 1
    assert confidence == 1
    assert recommendation == "review"


def test_low_confidence_forces_review_instead_of_automatic_decline():
    settings = Settings()
    weak = components(
        must_have_coverage=0.2, nice_to_have_coverage=0, depth_signal=0, citation_density=0
    )
    score, recommendation, confidence = score_profile(weak, 0, [], settings)
    assert score == pytest.approx(0.1)
    assert confidence == pytest.approx(0.4)
    assert recommendation == "review"
    assert (
        score_profile(weak, 0, [], settings.model_copy(update={"scoring_min_confidence": 0.3}))[1]
        == "decline"
    )


def test_exact_min_confidence_and_custom_weights_thresholds():
    settings = Settings(
        scoring_min_confidence=0.5,
        scoring_weights=ScoringWeights(
            must_have_coverage=1, nice_to_have_coverage=0, semantic_similarity=0, depth_signal=0
        ),
        scoring_thresholds=ScoringThresholds(advance_min=0.9, review_min=0.3),
    )
    assert score_profile(components(), 0, [], settings) == (1, "advance", 0.5)
    assert score_profile(components(must_have_coverage=0.4), 0.4, [], settings)[1] == "review"


def test_score_and_confidence_clamped():
    assert score_profile(components(penalty=3), 2, [], Settings())[0] == 0
    assert score_profile(components(depth_signal=10), 2, [], Settings())[0] == 1
