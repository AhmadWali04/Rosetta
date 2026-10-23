"""Tests for app/config.py's Settings, ScoringWeights, ScoringThresholds,
and get_settings.

AGENTS.md: "Config via pydantic-settings. No hardcoded keys, model names,
thresholds, or score weights. Scoring weights and the Advance/Review/Decline
thresholds live in app/config.py." These tests only exercise that module —
unit tests never call a live LLM or network (AGENTS.md "Testing rules").

Cannot run yet: no Python env exists until Agent A's pyproject.toml/uv.lock
land. Verify once they do with:
    cd apps/api && uv run pytest tests/test_config.py
"""

from __future__ import annotations

import pytest

from app.config import ScoringThresholds, ScoringWeights, Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """get_settings() is @lru_cache'd. Clear before and after every test so
    an env var monkeypatched in one test never leaks a stale cached
    Settings instance into another test.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_settings_load_with_defaults_and_do_not_raise() -> None:
    settings = Settings()

    assert settings.llm_provider == "openai"
    assert settings.vector_backend == "memory"
    assert settings.pinecone_env == "dev"
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert isinstance(settings.scoring_weights, ScoringWeights)
    assert isinstance(settings.scoring_thresholds, ScoringThresholds)


def test_scoring_weights_defaults_sum_to_one() -> None:
    weights = ScoringWeights()

    total = (
        weights.must_have_coverage
        + weights.nice_to_have_coverage
        + weights.semantic_similarity
        + weights.depth_signal
    )
    assert total == pytest.approx(1.0)
    assert weights.must_have_coverage == pytest.approx(0.50)
    assert weights.nice_to_have_coverage == pytest.approx(0.20)
    assert weights.semantic_similarity == pytest.approx(0.15)
    assert weights.depth_signal == pytest.approx(0.15)


def test_scoring_thresholds_defaults() -> None:
    thresholds = ScoringThresholds()

    assert thresholds.advance_min == pytest.approx(0.70)
    assert thresholds.review_min == pytest.approx(0.45)
    assert thresholds.ambiguous_band_low == pytest.approx(0.45)
    assert thresholds.ambiguous_band_high == pytest.approx(0.65)


def test_env_var_override_is_picked_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VECTOR_BACKEND", "pinecone-local")

    settings = Settings()

    assert settings.vector_backend == "pinecone-local"


def test_get_settings_is_cached() -> None:
    first = get_settings()
    second = get_settings()

    assert first is second


def test_get_settings_cache_clear_produces_new_instance() -> None:
    first = get_settings()
    get_settings.cache_clear()
    second = get_settings()

    assert first is not second
    assert first.llm_provider == second.llm_provider
