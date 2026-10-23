"""Gemini provider — a free alternative to OpenAI (Google AI Studio issues
a no-billing-required API key with a generous free-tier quota, unlike
OpenAI/Anthropic). One of the few files that imports the `google-genai`
SDK directly, per AGENTS.md invariant #5.

The installed package is `google-genai==2.33.0`. The call shape below was
verified against the ACTUALLY INSTALLED package, not guessed from training
data, via:

    uv run python -c "
    from google.genai import types
    print(types.GenerateContentConfig.model_fields['response_schema'])
    "

which confirmed `GenerateContentConfig.response_schema` accepts a plain
Python `type` (so a Pydantic `BaseModel` subclass can be passed directly,
mirroring OpenAI's `response_format=SomePydanticModel` convenience), paired
with `response_mime_type="application/json"`. `system_instruction` takes a
plain `str`. `Client(...).aio.models.generate_content(model=..., contents=...,
config=...)` is the async entry point (confirmed via
`inspect.signature(google.genai.models.AsyncModels.generate_content)`), and
`GenerateContentResponse.parsed` is a real field on the response (confirmed
via `types.GenerateContentResponse.model_fields`), mirroring OpenAI's
`.choices[0].message.parsed`.

Model name, temperature, and the API key all come from `app.config.Settings`
— never hardcoded (AGENTS.md "No hardcoded keys, model names, thresholds").
Client lifecycle: built fresh per call, same rationale as
`openai_provider.py`'s module docstring (nodes bridge into this async
method via per-call `asyncio.run(...)`, so a cached client risks binding
its transport to a closed event loop).
"""

from __future__ import annotations

from google import genai
from google.genai import types

from app.config import get_settings
from app.llm.base import T


class GeminiProvider:
    """Implements `app.llm.base.LLMProvider` against the Gemini API."""

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.gemini_api_key
        self._model = settings.gemini_model
        self._default_temperature = settings.llm_temperature

    async def generate_structured(
        self,
        *,
        system: str,
        prompt: str,
        output_model: type[T],
        temperature: float | None = None,
    ) -> T:
        # Built fresh per call — see the module docstring's "Client
        # lifecycle" note for why this isn't cached on `self`.
        client = genai.Client(api_key=self._api_key)
        response = await client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=output_model,
                temperature=(temperature if temperature is not None else self._default_temperature),
            ),
        )
        parsed = response.parsed
        if parsed is None:
            # Can happen on a safety block or a response that didn't
            # satisfy the schema. Never return a half-built/garbage model.
            candidates = response.candidates or []
            finish_reason = candidates[0].finish_reason if candidates else None
            raise ValueError(
                f"Gemini returned no parsed {output_model.__name__} "
                f"(finish_reason={finish_reason!r})."
            )
        assert isinstance(parsed, output_model)
        return parsed
