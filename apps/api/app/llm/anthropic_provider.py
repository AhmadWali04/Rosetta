"""Anthropic provider — deliberately NOT implemented in M1.

Deferred past M1: no `ANTHROPIC_API_KEY` is currently available/configured
for this project, so there is nothing to implement against and no way to
test a real implementation honestly. This is a documented scope cut (see
PROGRESS.md), not an oversight. `get_llm_provider()` still returns an
instance when `LLM_PROVIDER=anthropic` (so the factory's switch statement
stays exhaustive and `settings.llm_provider` stays meaningful), but calling
`generate_structured` raises immediately and loudly rather than silently
doing the wrong thing or pretending to call a real API.
"""

from __future__ import annotations

from app.llm.base import T


class AnthropicProvider:
    """Implements `app.llm.base.LLMProvider`'s shape but not its behavior."""

    async def generate_structured(
        self,
        *,
        system: str,
        prompt: str,
        output_model: type[T],
        temperature: float | None = None,
    ) -> T:
        raise NotImplementedError(
            "Anthropic provider deferred past M1 — no Anthropic key currently "
            "forces a real implementation"
        )
