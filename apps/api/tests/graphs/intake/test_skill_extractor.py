"""Unit test for `skill_extractor` (PRD §7.1 node 4).

Uses `app.llm.fake.FakeLLMProvider` (AGENTS.md "Testing rules") monkeypatched
in place of `get_llm_provider` at this node's own import site. `skill_extractor`
is a plain sync function (matching `graph.py`'s package-wide convention —
see that module's docstring); it bridges the async `generate_structured`
call internally with a single `asyncio.run(...)`, so these tests call it
directly, with no `await`/`pytest.mark.asyncio` needed.
"""

from __future__ import annotations

import pytest

from app.graphs.intake.skill_extractor import SkillExtractionResult, skill_extractor
from app.graphs.state import ExtractedSkill, IntakeState
from app.llm.fake import FakeLLMProvider


def _state(sanitized_text: str = "Built a RAG pipeline with PyTorch.") -> IntakeState:
    return IntakeState(
        application_id="a1", job_id="j1", resume_path="resume.pdf", sanitized_text=sanitized_text
    )


def test_skill_extractor_returns_skills_from_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = [
        ExtractedSkill(
            skill="PyTorch",
            evidence_span="Built a RAG pipeline with PyTorch",
            context="Experience",
            recency="current",
            depth_signal="production",
        )
    ]
    fake = FakeLLMProvider(
        responses={"SkillExtractionResult": SkillExtractionResult(skills=expected)}
    )
    monkeypatch.setattr("app.graphs.intake.skill_extractor.get_llm_provider", lambda: fake)

    result = skill_extractor(_state())

    assert result == {"extracted_skills": expected}


def test_skill_extractor_only_returns_extracted_skills_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """AGENTS.md invariant #3-adjacent discipline: a node only ever returns
    the state keys it owns."""
    fake = FakeLLMProvider(responses={"SkillExtractionResult": SkillExtractionResult(skills=[])})
    monkeypatch.setattr("app.graphs.intake.skill_extractor.get_llm_provider", lambda: fake)

    result = skill_extractor(_state())

    assert set(result.keys()) == {"extracted_skills"}


def test_skill_extractor_never_puts_resume_text_in_system_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AGENTS.md invariant #2: untrusted resume text must go in `prompt`,
    inside a delimited block — never in `system`."""
    captured: dict = {}

    class _CapturingProvider:
        async def generate_structured(self, *, system, prompt, output_model, temperature=None):
            captured["system"] = system
            captured["prompt"] = prompt
            return output_model(skills=[])

    monkeypatch.setattr(
        "app.graphs.intake.skill_extractor.get_llm_provider", lambda: _CapturingProvider()
    )

    marker = "UNIQUE_RESUME_MARKER_12345"
    skill_extractor(_state(sanitized_text=marker))

    assert marker not in captured["system"]
    assert marker in captured["prompt"]
    assert (
        "<untrusted_resume_text>" in captured["prompt"]
        and "</untrusted_resume_text>" in captured["prompt"]
    )
