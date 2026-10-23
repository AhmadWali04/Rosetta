"""Sanitize & Injection Check node (PRD §7.1, second node in the static
intake graph — runs after Ingest & Parse and, per AGENTS.md invariant #2,
always before Chunk & Index, so hidden text never reaches the vector
store).

Responsibilities, in order:
1. Re-derive hidden/white-text spans and strip them from `raw_text` to
   produce `sanitized_text`.
2. Run the rule-based (`check_rules`) and LLM-based (`check_llm`)
   injection detectors against the sanitized text.
3. Append flags only — never touch `state.recommendation`, `status`, or
   any other status-like field (AGENTS.md invariant #3: this node never
   auto-rejects; flags only ever influence the Scorer's recommendation
   downstream).
4. If any hidden text was stripped, write an audit `Event` row (AGENTS.md
   invariant #4).

Hidden-span design decision: rather than having `ingest_parse` smuggle
`RawDoc.hidden_spans` through an undeclared state field, this node
re-derives them itself by re-running the same format-aware extractor
(`extract_pdf`/`extract_docx`) against `state.resume_path`. Trade-off,
made explicit: one extra parse pass over a resume-sized document (cheap,
local, not network-bound) in exchange for keeping `ingest_parse` a pure
"parse -> text + sections" node, keeping this node fully self-contained
and independently unit-testable, and keeping `IntakeState`'s shape exactly
what `graphs/state.py` declares. PRD §7.1 also scopes "strip hidden/white
text" to THIS node, not Ingest & Parse, which matches.

Stripping mechanism: each hidden span's text is removed from `raw_text`
via a literal substring replace. This is a simplifying choice for M1 — if
a hidden span's exact text also happens to appear verbatim in legitimate
visible text, that occurrence would be stripped too. Acceptable for a
first pass; revisit with offset-based removal (using the span's own
position, once Agent A's `StyledSpan` shape is confirmed to carry one) if
that turns out to matter in eval.

Threshold note: AGENTS.md's Python conventions say thresholds belong in
`app/config.py`, not hardcoded. `INJECTION_LLM_CONFIDENCE_THRESHOLD` below
is a deliberate, documented exception — this task's brief lists
`app/config.py` under "Already built ... don't modify", so the threshold
lives here instead, as a clearly-named module constant, until it's
promoted into `ScoringThresholds`-style settings.

`async def`, matching every other node in this package (see
`ingest_parse.py`'s docstring) — and genuinely needed here, since this
node awaits `check_llm` (Agent A's contract) directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.db.models import Event
from app.db.session import session_scope
from app.graphs.state import IntakeState
from app.services.injection_detection import check_llm, check_rules
from app.services.resume_parsing import extract_docx, extract_pdf

# Tunable — see module docstring "Threshold note" for why this lives here
# rather than in app/config.py for M1.
INJECTION_LLM_CONFIDENCE_THRESHOLD = 0.7


def _span_text(span: Any) -> str:
    """`StyledSpan`'s exact shape isn't pinned down in the cross-agent
    contract handed to this node — accept either a plain string or an
    object exposing `.text`, so this node doesn't break on either
    reasonable shape Agent A's `resume_parsing.py` might ship."""
    if isinstance(span, str):
        return span
    return str(getattr(span, "text", ""))


def _strip_hidden_spans(raw_text: str, hidden_spans: list[Any]) -> tuple[str, list[str]]:
    """Removes each hidden span's text from `raw_text`. Returns the
    resulting text plus the list of non-empty strings actually stripped
    (for the audit payload)."""
    stripped: list[str] = []
    sanitized = raw_text
    for span in hidden_spans:
        text = _span_text(span)
        if text and text in sanitized:
            sanitized = sanitized.replace(text, "")
            stripped.append(text)
    return sanitized, stripped


def _extract_hidden_spans(resume_path: str) -> list[Any]:
    ext = Path(resume_path).suffix.lower()
    if ext == ".pdf":
        raw_doc = extract_pdf(resume_path)
    elif ext == ".docx":
        raw_doc = extract_docx(resume_path)
    else:
        return []
    return list(raw_doc.hidden_spans)


async def sanitize(state: IntakeState) -> dict[str, Any]:
    hidden_spans = _extract_hidden_spans(state.resume_path)
    sanitized_text, stripped = _strip_hidden_spans(state.raw_text, hidden_spans)

    rule_flags = check_rules(sanitized_text)
    llm_result = await check_llm(sanitized_text)

    new_flags = list(state.flags)
    injection_suspected = rule_flags or llm_result.confidence > INJECTION_LLM_CONFIDENCE_THRESHOLD
    if injection_suspected and "prompt_injection_suspected" not in new_flags:
        new_flags.append("prompt_injection_suspected")

    if stripped:
        if "hidden_text_removed" not in new_flags:
            new_flags.append("hidden_text_removed")
        with session_scope() as session:
            session.add(
                Event(
                    application_id=state.application_id,
                    actor="system",
                    action="hidden_text_removed",
                    payload={"stripped_spans": stripped, "rule_flags": rule_flags},
                )
            )
            session.commit()

    return {"sanitized_text": sanitized_text, "flags": new_flags}
