"""Fake LLM provider for tests.

AGENTS.md "Testing rules": "Unit tests never call a live LLM or the
network. Use the fake provider in app/llm/fake.py ..." This is that file.

Usage in a test:

    from app.llm.fake import FakeLLMProvider
    from app.graphs.state import ExtractedSkill

    fake = FakeLLMProvider(responses={
        "ExtractedSkill": [ExtractedSkill(skill="Python", ...), ExtractedSkill(...)],
    })
    result = await fake.generate_structured(system="...", prompt="...", output_model=ExtractedSkill)

A node under test typically gets the fake injected by monkeypatching
`app.llm.factory._INSTANCES` or `app.llm.get_llm_provider` rather than this
class being imported by application code directly.
"""

from __future__ import annotations

import warnings
from typing import Any, get_args, get_origin

from pydantic import BaseModel

from app.llm.base import T


def _default_for_annotation(annotation: object) -> object:
    """Best-effort "empty" value for a field's annotation, used only for the
    fallback path when a test didn't bother registering a response. Keeps
    the fallback instance constructible even for fields of a type this
    function doesn't recognize (falls back to `None`, which is fine since
    `model_construct` skips validation)."""
    if annotation is str:
        return ""
    if annotation is int:
        return 0
    if annotation is float:
        return 0.0
    if annotation is bool:
        return False
    origin = get_origin(annotation)
    if origin in (list,):
        return []
    if origin in (dict,):
        return {}
    if origin in (set,):
        return set()
    if origin is tuple:
        return ()
    # Optional[X] / X | None -> default to None, which is a reasonable
    # "empty" value for an optional field.
    args = get_args(annotation)
    if origin is not None and type(None) in args:
        return None
    return None


class FakeLLMProvider:
    """Implements `app.llm.base.LLMProvider` with no network calls.

    `responses` is keyed by `output_model.__name__`:
    - A single `BaseModel` instance is returned on every call for that model
      name.
    - A `list[BaseModel]` is consumed FIFO (one popped per call), letting a
      test script a sequence of responses for repeated calls to the same
      model type (e.g. the Requirement Matcher calling once per
      requirement).
    - A model name that isn't registered at all falls back to a
      best-effort default instance built via `output_model.model_construct`
      (empty string/list/0.0/False per field, see `_default_for_annotation`)
      so a test that didn't bother stubbing every single model doesn't
      crash outright — but a `UserWarning` is raised so a test author
      notices if they forgot to register a response they actually needed.
    """

    def __init__(self, responses: dict[str, BaseModel | list[BaseModel]] | None = None) -> None:
        self._responses: dict[str, BaseModel | list[BaseModel]] = dict(responses or {})

    async def generate_structured(
        self,
        *,
        system: str,
        prompt: str,
        output_model: type[T],
        temperature: float | None = None,
    ) -> T:
        name = output_model.__name__

        if name in self._responses:
            value = self._responses[name]
            result: BaseModel
            if isinstance(value, list):
                if not value:
                    raise ValueError(
                        f"FakeLLMProvider: scripted responses for {name!r} are "
                        f"exhausted (generate_structured called more times than "
                        f"responses were registered)."
                    )
                result = value.pop(0)
            else:
                result = value
            if not isinstance(result, output_model):
                raise TypeError(
                    f"FakeLLMProvider: registered response for {name!r} is a "
                    f"{type(result).__name__}, not {output_model.__name__}."
                )
            return result

        warnings.warn(
            f"FakeLLMProvider: no response registered for {name!r}; constructing "
            f"a default instance with empty/zero field values. Register one via "
            f"responses={{{name!r}: ...}} if this test's assertions depend on "
            f"the content of this call's result.",
            stacklevel=2,
        )
        defaults: dict[str, Any] = {
            field_name: _default_for_annotation(field.annotation)
            for field_name, field in output_model.model_fields.items()
        }
        return output_model.model_construct(**defaults)
