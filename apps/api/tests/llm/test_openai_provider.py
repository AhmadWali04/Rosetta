"""Tests for `app.llm.openai_provider.OpenAIProvider`.

AGENTS.md "Testing rules": unit tests never call a live LLM or the
network. The real `openai.AsyncOpenAI` class is monkeypatched out entirely
here — these tests only exercise this provider's own message-shaping and
response-unwrapping logic (the structured-output call shape verified
against the installed `openai==3.37.0` package — see the module docstring
of `app/llm/openai_provider.py`), never a real HTTP call.

Run with: `cd apps/api && uv run pytest tests/llm/test_openai_provider.py -v`
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import BaseModel

import app.llm.openai_provider as openai_provider_module
from app.config import get_settings
from app.llm.openai_provider import OpenAIProvider


class _Verdict(BaseModel):
    label: str = ""
    confidence: float = 0.0


@dataclass
class _FakeMessage:
    parsed: BaseModel | None
    refusal: str | None = None


@dataclass
class _FakeChoice:
    message: _FakeMessage


@dataclass
class _FakeCompletion:
    choices: list[_FakeChoice]


@dataclass
class _FakeCompletionsResource:
    """Records every call's kwargs and returns a pre-set completion."""

    to_return: _FakeCompletion
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def parse(self, **kwargs: Any) -> _FakeCompletion:
        self.calls.append(kwargs)
        return self.to_return


@dataclass
class _FakeChatResource:
    completions: _FakeCompletionsResource


class _FakeAsyncOpenAI:
    """Stands in for `openai.AsyncOpenAI`. Captures the `api_key` it was
    constructed with and exposes a `.chat.completions.parse(...)` that
    records its kwargs, matching the real client's shape closely enough
    for this provider's logic to be exercised without any network call."""

    _next_completion: _FakeCompletion | None = None
    last_api_key: str | None = None
    last_instance: _FakeAsyncOpenAI | None = None

    def __init__(self, api_key: str | None = None) -> None:
        _FakeAsyncOpenAI.last_api_key = api_key
        assert _FakeAsyncOpenAI._next_completion is not None, (
            "test must set _FakeAsyncOpenAI._next_completion before constructing"
        )
        completions = _FakeCompletionsResource(to_return=_FakeAsyncOpenAI._next_completion)
        self.chat = _FakeChatResource(completions=completions)
        _FakeAsyncOpenAI.last_instance = self


@pytest.fixture(autouse=True)
def _patch_async_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openai_provider_module, "AsyncOpenAI", _FakeAsyncOpenAI)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_generate_structured_builds_system_and_user_messages() -> None:
    verdict = _Verdict(label="met", confidence=0.9)
    _FakeAsyncOpenAI._next_completion = _FakeCompletion(
        choices=[_FakeChoice(message=_FakeMessage(parsed=verdict))]
    )

    provider = OpenAIProvider()
    result = await provider.generate_structured(
        system="SYSTEM INSTRUCTIONS",
        prompt="<untrusted_resume_text>hello</untrusted_resume_text>",
        output_model=_Verdict,
    )

    assert result is verdict

    call = _FakeAsyncOpenAI.last_instance.chat.completions.calls[0]
    assert call["messages"] == [
        {"role": "system", "content": "SYSTEM INSTRUCTIONS"},
        {"role": "user", "content": "<untrusted_resume_text>hello</untrusted_resume_text>"},
    ]
    assert call["response_format"] is _Verdict


async def test_generate_structured_uses_settings_model_and_default_temperature() -> None:
    settings = get_settings()
    _FakeAsyncOpenAI._next_completion = _FakeCompletion(
        choices=[_FakeChoice(message=_FakeMessage(parsed=_Verdict()))]
    )

    provider = OpenAIProvider()
    await provider.generate_structured(system="s", prompt="p", output_model=_Verdict)

    call = _FakeAsyncOpenAI.last_instance.chat.completions.calls[0]
    assert call["model"] == settings.openai_model
    assert call["temperature"] == settings.llm_temperature


async def test_generate_structured_temperature_override_wins() -> None:
    _FakeAsyncOpenAI._next_completion = _FakeCompletion(
        choices=[_FakeChoice(message=_FakeMessage(parsed=_Verdict()))]
    )

    provider = OpenAIProvider()
    await provider.generate_structured(
        system="s", prompt="p", output_model=_Verdict, temperature=0.9
    )

    call = _FakeAsyncOpenAI.last_instance.chat.completions.calls[0]
    assert call["temperature"] == 0.9


async def test_generate_structured_raises_on_unparsed_response() -> None:
    _FakeAsyncOpenAI._next_completion = _FakeCompletion(
        choices=[_FakeChoice(message=_FakeMessage(parsed=None, refusal="I can't help with that"))]
    )

    provider = OpenAIProvider()
    with pytest.raises(ValueError, match="no parsed"):
        await provider.generate_structured(system="s", prompt="p", output_model=_Verdict)


async def test_api_key_comes_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings().model_copy(update={"openai_api_key": "sk-test-123"})
    monkeypatch.setattr(openai_provider_module, "get_settings", lambda: settings)
    _FakeAsyncOpenAI._next_completion = _FakeCompletion(
        choices=[_FakeChoice(message=_FakeMessage(parsed=_Verdict()))]
    )

    provider = OpenAIProvider()
    await provider.generate_structured(system="s", prompt="p", output_model=_Verdict)

    assert _FakeAsyncOpenAI.last_api_key == "sk-test-123"
