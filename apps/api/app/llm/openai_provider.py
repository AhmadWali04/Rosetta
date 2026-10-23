"""OpenAI provider — one of the only two files that import the `openai` SDK
directly (the other is `anthropic_provider.py`'s Anthropic-SDK equivalent,
which is a stub). AGENTS.md invariant #5.

The installed package is `openai==3.37.0` — a much newer major version than
older 1.x-era documentation/training data assumes; method names and call
shapes have changed across major versions. The call shape below was
verified against the ACTUALLY INSTALLED package, not guessed from training
data, via:

    uv run python -c "
    from openai.resources.chat.completions.completions import AsyncCompletions
    import inspect
    print(inspect.getsource(AsyncCompletions.parse))
    "

which confirmed:

    async def parse(
        self, *, messages: Iterable[ChatCompletionMessageParam],
        model: Union[str, ChatModel],
        response_format: type[ResponseFormatT] | Omit = omit,
        ...,
    ) -> ParsedChatCompletion[ResponseFormatT]

`client.chat.completions.parse(model=..., messages=[...], response_format=SomePydanticModel)`
still exists unchanged in 3.37.0 and returns a `ParsedChatCompletion`; the
parsed Pydantic instance is at `completion.choices[0].message.parsed`
(`ParsedChatCompletionMessage.parsed: Optional[ContentType]`, confirmed via
`inspect.getsource` on that class too). A newer `client.responses.parse(text_format=...)`
API also exists in this version, but `chat.completions.parse` maps directly
onto this provider's system/user message shape, so that's what's used here.

Model name, temperature, and the API key all come from `app.config.Settings`
— never hardcoded (AGENTS.md "No hardcoded keys, model names, thresholds").

Client lifecycle note: `app/llm/factory.py` caches one `OpenAIProvider`
instance for the lifetime of the process, but several `app/graphs/intake/*`
nodes are sync functions that bridge into this async method via
`asyncio.run(...)` per node call — each of those creates and tears down its
own event loop. An `AsyncOpenAI` client built once (e.g. in `__init__`) and
reused across many different event loops can end up with its underlying
`httpx.AsyncClient` connection pool bound to a now-closed loop, surfacing as
a `RuntimeError: Event loop is closed` on a later call. To stay safe across
that calling pattern without needing those nodes to change, the client is
constructed fresh inside `generate_structured` on every call instead of
once in `__init__` — cheap (no connection is opened until the first actual
request) and immune to stale-loop reuse.
"""

from __future__ import annotations

from openai import AsyncOpenAI

from app.config import get_settings
from app.llm.base import T


class OpenAIProvider:
    """Implements `app.llm.base.LLMProvider` against the OpenAI SDK."""

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.openai_api_key
        self._model = settings.openai_model
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
        # lifecycle note" for why this isn't cached on `self`.
        client = AsyncOpenAI(api_key=self._api_key)
        completion = await client.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            response_format=output_model,
            temperature=(temperature if temperature is not None else self._default_temperature),
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            # Can happen on a refusal or a response that didn't satisfy the
            # schema. Never return a half-built/garbage model silently.
            refusal = getattr(completion.choices[0].message, "refusal", None)
            raise ValueError(
                f"OpenAI returned no parsed {output_model.__name__} (refusal={refusal!r})."
            )
        return parsed
