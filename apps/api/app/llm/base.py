"""Provider-agnostic LLM abstraction.

AGENTS.md invariant #5: "All LLM calls go through app/llm/. Use structured
output (Pydantic models). Nodes never import provider SDKs directly." Every
graph node that needs an LLM call imports `LLMProvider`/`get_llm_provider`
from `app.llm` (see `app/llm/__init__.py`) and nothing else.

CRITICAL SECURITY CONTRACT (AGENTS.md invariant #2 — "Resume text is
untrusted data. Never interpolate it into the system prompt. Pass it inside
clearly delimited data blocks..."):

- `system` carries ONLY fixed, developer-authored instructions: what to
  extract/judge, the expected output shape, and an explicit instruction that
  any data block in the user turn is untrusted and must not be obeyed.
- `prompt` carries the user-turn content. Any untrusted resume/candidate
  text MUST be embedded inside `prompt`, wrapped in an explicit delimiter,
  e.g.:

      <untrusted_resume_text>
      ...candidate-controlled text goes here, verbatim...
      </untrusted_resume_text>

  NEVER interpolate resume/candidate text into `system`. This is the
  structural enforcement of invariant #2: a caller has to go out of its way
  to do it wrong, since the untrusted text has nowhere to go except a
  clearly delimited block inside `prompt`.

This module defines the interface only. `openai_provider.py` and
`anthropic_provider.py` implement it against real SDKs; `fake.py` implements
it for tests (AGENTS.md "Testing rules": unit tests never call a live LLM or
the network). `factory.py` selects which implementation to hand back.
"""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class LLMProvider(Protocol):
    """Structural interface every provider (and the fake) implements."""

    async def generate_structured(
        self,
        *,
        system: str,
        prompt: str,
        output_model: type[T],
        temperature: float | None = None,
    ) -> T:
        """Call the LLM and parse its response into `output_model`.

        Args:
            system: Fixed, developer-authored instructions only. Never put
                candidate/resume text here — see the module docstring.
            prompt: The user-turn content. Any untrusted candidate/resume
                text MUST be embedded here inside an explicit delimiter
                (e.g. `<untrusted_resume_text>...</untrusted_resume_text>`),
                and `system` should instruct the model to treat that block
                as data, never as instructions to follow.
            output_model: The Pydantic model the response must conform to.
            temperature: Per-call override. When `None`, implementations
                use `settings.llm_temperature`.

        Returns:
            An instance of `output_model`.
        """
        ...
