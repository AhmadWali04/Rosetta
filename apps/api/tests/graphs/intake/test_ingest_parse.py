"""Unit test for `ingest_parse` (PRD §7.1 node 1).

Mocks Agent A's `extract_pdf`/`extract_docx`/`segment_sections` at this
node's own import site, so this test exercises only `ingest_parse`'s own
branching logic (extension dispatch + state assembly), never Agent A's
actual parsing.

At the time this was written, `app/services/resume_parsing.py` did not
exist yet (Agent A's file, built in parallel) — this test file will fail
at collection with `ModuleNotFoundError` until that module lands. That is
expected per this milestone's cross-agent dependency note.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.graphs.intake.ingest_parse import ingest_parse
from app.graphs.state import IntakeState, Section


def _state(resume_path: str) -> IntakeState:
    return IntakeState(application_id="a1", job_id="j1", resume_path=resume_path)


@pytest.mark.asyncio
async def test_ingest_parse_pdf() -> None:
    raw_doc = SimpleNamespace(text="hello world", hidden_spans=[])
    sections = [Section(name="experience", text="hello world", char_start=0, char_end=11)]

    with (
        patch("app.graphs.intake.ingest_parse.extract_pdf", return_value=raw_doc) as mock_pdf,
        patch(
            "app.graphs.intake.ingest_parse.segment_sections", return_value=sections
        ) as mock_segment,
    ):
        result = await ingest_parse(_state("resume.pdf"))

    mock_pdf.assert_called_once_with("resume.pdf")
    mock_segment.assert_called_once_with("hello world")
    assert result == {"raw_text": "hello world", "sections": sections}


@pytest.mark.asyncio
async def test_ingest_parse_docx() -> None:
    raw_doc = SimpleNamespace(text="docx text", hidden_spans=[])

    with (
        patch("app.graphs.intake.ingest_parse.extract_docx", return_value=raw_doc) as mock_docx,
        patch("app.graphs.intake.ingest_parse.segment_sections", return_value=[]),
    ):
        result = await ingest_parse(_state("resume.docx"))

    mock_docx.assert_called_once_with("resume.docx")
    assert result["raw_text"] == "docx text"
    assert result["sections"] == []


@pytest.mark.asyncio
async def test_ingest_parse_rejects_unknown_extension() -> None:
    with pytest.raises(ValueError, match="unsupported resume file extension"):
        await ingest_parse(_state("resume.txt"))
