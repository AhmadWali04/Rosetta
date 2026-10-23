"""Prompt templates as versioned `.md` files (AGENTS.md: "Prompts live in
app/prompts/ with a version suffix. Change a prompt by adding a new
version, then run make eval-fast and note the delta in PROGRESS.md.").

This module is just a tiny, dependency-free loader so every node/service
that needs a prompt reads it the same way instead of each inventing its own
file-path handling:

    from app.prompts import load_prompt
    system = load_prompt("skill_extractor.v1")

Templates are plain Markdown, used verbatim as the `system` argument to
`LLMProvider.generate_structured` — they contain no literal fill-in
placeholders for untrusted text. Each template documents, as prose, the
exact delimiter (e.g. `<untrusted_resume_text>...</untrusted_resume_text>`)
the caller must use when building the separate `prompt` (user-turn) string
that actually carries the untrusted resume/candidate text — see
`app/llm/base.py`'s module docstring for why that text must never be
interpolated into `system` itself. These files are NOT Jinja (no control
flow needed yet); if a future prompt needs real templating logic, switch
that one file to `.jinja` and extend `load_prompt` accordingly — don't add
a templating dependency preemptively.
"""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    """Read `app/prompts/{name}.md` and return its contents verbatim.

    `name` is the file stem including its version suffix, e.g.
    `"skill_extractor.v1"` for `skill_extractor.v1.md`. Raises
    `FileNotFoundError` with a clear message if the file doesn't exist
    (fails loudly rather than silently falling back to some default
    prompt).
    """
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"No prompt template at {path} (looked for app/prompts/{name}.md)")
    return path.read_text(encoding="utf-8")
