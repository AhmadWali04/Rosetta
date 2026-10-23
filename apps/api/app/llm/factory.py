"""Builds the right `LLMProvider` for the configured provider (AGENTS.md
invariant #5).

Mirrors `app/rag/vector_store/factory.py`'s pattern exactly: a module-level
dict cache keyed by the settings value, not `functools.lru_cache` — a plain
dict is just as clear and, importantly, easy for a test to clear/monkeypatch
(`app.llm.factory._INSTANCES.clear()`) when it needs a fresh provider
instance (e.g. after swapping `LLM_PROVIDER` or injecting a fake).
"""

from __future__ import annotations

from app.config import get_settings
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import LLMProvider
from app.llm.openai_provider import OpenAIProvider

_INSTANCES: dict[str, LLMProvider] = {}


def get_llm_provider() -> LLMProvider:
    """Return the `LLMProvider` for `settings.llm_provider` ("openai" or
    "anthropic"). Cached per provider name for the lifetime of the process.
    """
    settings = get_settings()
    key = settings.llm_provider
    if key in _INSTANCES:
        return _INSTANCES[key]

    provider: LLMProvider
    if key == "openai":
        provider = OpenAIProvider()
    elif key == "anthropic":
        provider = AnthropicProvider()
    else:  # pragma: no cover - Literal in config.py prevents this at type-check time
        raise ValueError(f"Unknown LLM_PROVIDER: {key!r}")

    _INSTANCES[key] = provider
    return provider
