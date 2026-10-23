"""Tests for `app.llm.factory.get_llm_provider` (AGENTS.md invariant #5).

Mirrors `tests/rag/test_vector_store_memory.py`'s style for the analogous
`app/rag/vector_store/factory.py`. No network calls: constructing an
`OpenAIProvider`/`AnthropicProvider` doesn't itself make any HTTP request
(the SDK client only connects on first real call).

Run with: `cd apps/api && uv run pytest tests/llm/test_factory.py -v`
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.llm import factory
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.factory import get_llm_provider
from app.llm.openai_provider import OpenAIProvider


@pytest.fixture(autouse=True)
def _clear_caches():
    """`get_settings` is `@lru_cache`'d and `factory._INSTANCES` is a
    module-level dict cache — both must be reset between tests so one
    test's monkeypatched `LLM_PROVIDER` never leaks into the next."""
    get_settings.cache_clear()
    factory._INSTANCES.clear()
    yield
    get_settings.cache_clear()
    factory._INSTANCES.clear()


def test_returns_openai_provider_by_default() -> None:
    provider = get_llm_provider()
    assert isinstance(provider, OpenAIProvider)


def test_returns_anthropic_provider_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    get_settings.cache_clear()

    provider = get_llm_provider()
    assert isinstance(provider, AnthropicProvider)


def test_instances_are_cached_per_provider() -> None:
    first = get_llm_provider()
    second = get_llm_provider()
    assert first is second


def test_switching_provider_returns_a_different_cached_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    openai_provider = get_llm_provider()

    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    get_settings.cache_clear()
    anthropic_provider = get_llm_provider()

    assert openai_provider is not anthropic_provider
    assert isinstance(openai_provider, OpenAIProvider)
    assert isinstance(anthropic_provider, AnthropicProvider)


async def test_anthropic_provider_raises_not_implemented() -> None:
    from pydantic import BaseModel

    class _Dummy(BaseModel):
        pass

    provider = AnthropicProvider()
    with pytest.raises(NotImplementedError):
        await provider.generate_structured(system="s", prompt="p", output_model=_Dummy)
