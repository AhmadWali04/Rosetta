"""Ingest & Parse node (PRD §7.1, first node in the static intake graph).

Deterministic: reads `state.resume_path`, picks the extractor by file
extension, extracts raw text, then section-segments it. Returns
`{"raw_text": ..., "sections": ...}`.

Hidden-span design decision (see `sanitize.py` for the other half of this):
this node does NOT strip hidden/white-text spans and does NOT try to smuggle
`RawDoc.hidden_spans` into the shared `IntakeState` through an undeclared
field. `IntakeState` (graphs/state.py) is a fixed, shared Pydantic contract
every intake node reads/writes against — adding a private field here whose
only consumer is the very next node would widen that contract for one
node's convenience. PRD §7.1 also scopes "strip hidden/white text"
explicitly to the Sanitize & Injection Check node, not this one, so
`raw_text` legitimately may still contain hidden text; `sanitize.py`
re-derives the hidden spans itself by re-running the same format-aware
extractor against `state.resume_path` (see that module's docstring for why
that's the cleaner of the two options the task brief offered).

Sync vs async: `async def`, matching every other node in `app/graphs/intake/`
(this package's own `sanitize`/`chunk_and_index`/`persist`, and the other
agent's `skill_extractor`/`skill_normalizer`/`requirement_matcher`/
`scorer`/`hr_explainer`). `graph.py` — the file that wires every node
together, and that gets final say on this convention — runs the whole
graph via `.ainvoke()` precisely because every node is async; a plain
`.invoke()` raises `TypeError: No synchronous function provided` against
an async-node graph. This node's own body has no awaited work
(`extract_pdf`/`extract_docx`/`segment_sections` are all sync per Agent
A's/B's contracts), so it's `async def` purely for that one-convention-
for-the-whole-package consistency, not because it needs to await anything
itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.graphs.state import IntakeState
from app.services.resume_parsing import extract_docx, extract_pdf, segment_sections


async def ingest_parse(state: IntakeState) -> dict[str, Any]:
    ext = Path(state.resume_path).suffix.lower()
    if ext == ".pdf":
        raw_doc = extract_pdf(state.resume_path)
    elif ext == ".docx":
        raw_doc = extract_docx(state.resume_path)
    else:
        raise ValueError(
            f"ingest_parse: unsupported resume file extension {ext!r} for "
            f"{state.resume_path!r} (expected .pdf or .docx, per PRD F1.2)"
        )

    sections = segment_sections(raw_doc.text)
    return {"raw_text": raw_doc.text, "sections": sections}
