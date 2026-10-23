"""Tests for `app.llm.fake.FakeLLMProvider` (AGENTS.md "Testing rules":
"unit tests never call a live LLM or the network").

Run with: `cd apps/api && uv run pytest tests/llm/test_fake_provider.py -v`
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.llm.fake import FakeLLMProvider


class _Dummy(BaseModel):
    name: str = ""
    count: int = 0
    score: float = 0.0
    ok: bool = False
    tags: list[str] = []


async def test_single_instance_returned_every_call() -> None:
    expected = _Dummy(name="fixed", count=3, score=0.5, ok=True, tags=["a"])
    provider = FakeLLMProvider(responses={"_Dummy": expected})

    first = await provider.generate_structured(system="s", prompt="p", output_model=_Dummy)
    second = await provider.generate_structured(system="s", prompt="p", output_model=_Dummy)

    assert first is expected
    assert second is expected


async def test_list_of_responses_consumed_fifo() -> None:
    first_expected = _Dummy(name="one")
    second_expected = _Dummy(name="two")
    provider = FakeLLMProvider(responses={"_Dummy": [first_expected, second_expected]})

    first = await provider.generate_structured(system="s", prompt="p", output_model=_Dummy)
    second = await provider.generate_structured(system="s", prompt="p", output_model=_Dummy)

    assert first is first_expected
    assert second is second_expected


async def test_exhausted_list_raises_value_error() -> None:
    provider = FakeLLMProvider(responses={"_Dummy": [_Dummy(name="only")]})
    await provider.generate_structured(system="s", prompt="p", output_model=_Dummy)

    with pytest.raises(ValueError, match="exhausted"):
        await provider.generate_structured(system="s", prompt="p", output_model=_Dummy)


async def test_mismatched_response_type_raises_type_error() -> None:
    class _Other(BaseModel):
        pass

    # Registered under _Dummy's name but actually an _Other instance.
    provider = FakeLLMProvider(responses={"_Dummy": _Other()})  # type: ignore[dict-item]

    with pytest.raises(TypeError):
        await provider.generate_structured(system="s", prompt="p", output_model=_Dummy)


async def test_unregistered_model_falls_back_to_default_with_warning() -> None:
    provider = FakeLLMProvider()  # nothing registered

    with pytest.warns(UserWarning, match="no response registered"):
        result = await provider.generate_structured(system="s", prompt="p", output_model=_Dummy)

    assert isinstance(result, _Dummy)
    assert result.name == ""
    assert result.count == 0
    assert result.score == 0.0
    assert result.ok is False
    assert result.tags == []


async def test_no_warning_when_response_is_registered() -> None:
    import warnings

    provider = FakeLLMProvider(responses={"_Dummy": _Dummy(name="registered")})

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = await provider.generate_structured(system="s", prompt="p", output_model=_Dummy)

    user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
    assert not user_warnings, f"unexpected warnings: {user_warnings}"
    assert result.name == "registered"
