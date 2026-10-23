"""Tests for `app.llm.gemini_provider.GeminiProvider`.

AGENTS.md "Testing rules": unit tests never call a live LLM or the
network. The real `genai.Client` class is monkeypatched out entirely here
— these tests only exercise this provider's own request-shaping and
response-unwrapping logic (the structured-output call shape verified
against the installed `google-genai==2.33.0` package — see the module
docstring of `app/llm/gemini_provider.py`), never a real HTTP call.

Run with: `cd apps/api && uv run pytest tests/llm/test_gemini_provider.py -v`
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import BaseModel

import app.llm.gemini_provider as gemini_provider_module
from app.config import get_settings
from app.llm.gemini_provider import GeminiProvider


class _Verdict(BaseModel):
    label: str = ""
    confidence: float = 0.0


@dataclass
class _FakeCandidate:
    finish_reason: str | None = None


@dataclass
class _FakeResponse:
    parsed: BaseModel | None
    candidates: list[_FakeCandidate] | None = None


@dataclass
class _FakeAsyncModels:
    """Records every call's kwargs and returns a pre-set response."""

    to_return: _FakeResponse
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def generate_content(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        return self.to_return


@dataclass
class _FakeAio:
    models: _FakeAsyncModels


class _FakeClient:
    """Stands in for `genai.Client`. Captures the `api_key` it was
    constructed with and exposes `.aio.models.generate_content(...)` that
    records its kwargs, matching the real client's shape closely enough for
    this provider's logic to be exercised without any network call."""

    _next_response: _FakeResponse | None = None
    last_api_key: str | None = None
    last_instance: _FakeClient | None = None

    def __init__(self, api_key: str | None = None) -> None:
        _FakeClient.last_api_key = api_key
        assert _FakeClient._next_response is not None, (
            "test must set _FakeClient._next_response before constructing"
        )
        self.aio = _FakeAio(models=_FakeAsyncModels(to_return=_FakeClient._next_response))
        _FakeClient.last_instance = self


@pytest.fixture(autouse=True)
def _patch_genai_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gemini_provider_module.genai, "Client", _FakeClient)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_generate_structured_builds_system_instruction_and_contents() -> None:
    verdict = _Verdict(label="met", confidence=0.9)
    _FakeClient._next_response = _FakeResponse(parsed=verdict)

    provider = GeminiProvider()
    result = await provider.generate_structured(
        system="SYSTEM INSTRUCTIONS",
        prompt="<untrusted_resume_text>hello</untrusted_resume_text>",
        output_model=_Verdict,
    )

    assert result is verdict

    call = _FakeClient.last_instance.aio.models.calls[0]
    assert call["contents"] == "<untrusted_resume_text>hello</untrusted_resume_text>"
    config = call["config"]
    assert config.system_instruction == "SYSTEM INSTRUCTIONS"
    assert config.response_schema is _Verdict
    assert config.response_mime_type == "application/json"


async def test_generate_structured_uses_settings_model_and_default_temperature() -> None:
    settings = get_settings()
    _FakeClient._next_response = _FakeResponse(parsed=_Verdict())

    provider = GeminiProvider()
    await provider.generate_structured(system="s", prompt="p", output_model=_Verdict)

    call = _FakeClient.last_instance.aio.models.calls[0]
    assert call["model"] == settings.gemini_model
    assert call["config"].temperature == settings.llm_temperature


async def test_generate_structured_temperature_override_wins() -> None:
    _FakeClient._next_response = _FakeResponse(parsed=_Verdict())

    provider = GeminiProvider()
    await provider.generate_structured(
        system="s", prompt="p", output_model=_Verdict, temperature=0.9
    )

    call = _FakeClient.last_instance.aio.models.calls[0]
    assert call["config"].temperature == 0.9


async def test_generate_structured_raises_on_unparsed_response() -> None:
    _FakeClient._next_response = _FakeResponse(
        parsed=None, candidates=[_FakeCandidate(finish_reason="SAFETY")]
    )

    provider = GeminiProvider()
    with pytest.raises(ValueError, match="no parsed"):
        await provider.generate_structured(system="s", prompt="p", output_model=_Verdict)


async def test_api_key_comes_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings().model_copy(update={"gemini_api_key": "gm-test-123"})
    monkeypatch.setattr(gemini_provider_module, "get_settings", lambda: settings)
    _FakeClient._next_response = _FakeResponse(parsed=_Verdict())

    provider = GeminiProvider()
    await provider.generate_structured(system="s", prompt="p", output_model=_Verdict)

    assert _FakeClient.last_api_key == "gm-test-123"
