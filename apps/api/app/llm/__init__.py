"""Provider-agnostic LLM abstraction (AGENTS.md invariant #5).

Everything outside `app/llm` imports from here — never a provider module
(`openai_provider`, `anthropic_provider`, `fake`) directly, and never the
`openai`/`anthropic` SDKs directly.
"""

from __future__ import annotations

from app.llm.base import LLMProvider
from app.llm.factory import get_llm_provider

__all__ = ["LLMProvider", "get_llm_provider"]
