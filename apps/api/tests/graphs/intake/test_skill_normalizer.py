"""Unit test for `skill_normalizer` (PRD §7.1 node 5).

Mocks `hybrid_search` (Agent B) and `get_llm_provider` (Agent A) at this
node's own import site, and uses a real sqlite-in-memory `skill_taxonomy`
table (same fixture pattern as `test_chunk_and_index.py`/`test_persist.py`)
so `_hydrate_candidates`'s real Postgres read is exercised, not mocked.

`skill_normalizer` is a plain sync function; it bridges its own async
retrieval/LLM work internally with a single `asyncio.run(...)`.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

import app.db.session as db_session
from app.db.models import Base, SkillTaxonomy
from app.graphs.intake.skill_normalizer import (
    SkillNormalizationItem,
    SkillNormalizationResult,
    skill_normalizer,
)
from app.graphs.state import ExtractedSkill, IntakeState
from app.llm.fake import FakeLLMProvider
from app.rag.retriever import RetrievedMatch


@pytest.fixture
def sqlite_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    test_session_local = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "SessionLocal", test_session_local)
    yield engine


def _seed_taxonomy(engine: Engine) -> None:
    session_local = sessionmaker(bind=engine)
    with session_local() as session:
        session.add(
            SkillTaxonomy(
                id="tax-pytorch",
                canonical="PyTorch",
                alt_labels=["PyTorch Lightning"],
                description="Deep learning framework",
                source="onet",
                pinecone_id="skill#tax-pytorch",
            )
        )
        session.add(
            SkillTaxonomy(
                id="tax-other",
                canonical="Something Else",
                alt_labels=[],
                description="unrelated",
                source="onet",
                pinecone_id="skill#tax-other",
            )
        )
        session.commit()


def _state(skills: list[ExtractedSkill]) -> IntakeState:
    return IntakeState(
        application_id="a1", job_id="j1", resume_path="resume.pdf", extracted_skills=skills
    )


def _skill(name: str = "PyTorch Lightning") -> ExtractedSkill:
    return ExtractedSkill(
        skill=name,
        evidence_span="used PyTorch Lightning",
        context="Experience",
        recency="current",
        depth_signal="project",
    )


def test_normalizer_accepts_grounded_match(
    sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_taxonomy(sqlite_engine)
    monkeypatch.setattr(
        "app.graphs.intake.skill_normalizer.hybrid_search",
        AsyncMock(return_value=[RetrievedMatch(id="skill#tax-pytorch", score=0.9, metadata={})]),
    )
    fake = FakeLLMProvider(
        responses={
            "SkillNormalizationResult": SkillNormalizationResult(
                items=[
                    SkillNormalizationItem(
                        skill_index=0, canonical="PyTorch", taxonomy_id="tax-pytorch"
                    )
                ]
            )
        }
    )
    monkeypatch.setattr("app.graphs.intake.skill_normalizer.get_llm_provider", lambda: fake)

    result = skill_normalizer(_state([_skill()]))

    normalized = result["normalized_skills"]
    assert len(normalized) == 1
    assert normalized[0].canonical == "PyTorch"
    assert normalized[0].taxonomy_id == "tax-pytorch"
    assert normalized[0].extracted.skill == "PyTorch Lightning"


def test_normalizer_rejects_hallucinated_taxonomy_id(
    sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The LLM picks a taxonomy_id that was never retrieved for this skill
    (borrowed from elsewhere, or invented outright) - must be discarded,
    never trusted (module docstring's grounding guarantee)."""
    _seed_taxonomy(sqlite_engine)
    monkeypatch.setattr(
        "app.graphs.intake.skill_normalizer.hybrid_search",
        AsyncMock(return_value=[RetrievedMatch(id="skill#tax-pytorch", score=0.9, metadata={})]),
    )
    fake = FakeLLMProvider(
        responses={
            "SkillNormalizationResult": SkillNormalizationResult(
                items=[
                    # tax-other was never in this skill's own candidate list.
                    SkillNormalizationItem(
                        skill_index=0, canonical="Something Else", taxonomy_id="tax-other"
                    )
                ]
            )
        }
    )
    monkeypatch.setattr("app.graphs.intake.skill_normalizer.get_llm_provider", lambda: fake)

    result = skill_normalizer(_state([_skill()]))

    normalized = result["normalized_skills"]
    assert normalized[0].canonical is None
    assert normalized[0].taxonomy_id is None


def test_normalizer_skips_llm_when_no_candidates_retrieved(
    sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A skill with zero retrieved candidates is grounded-by-construction to
    no_match - the LLM must not even be called for it."""
    _seed_taxonomy(sqlite_engine)
    monkeypatch.setattr(
        "app.graphs.intake.skill_normalizer.hybrid_search", AsyncMock(return_value=[])
    )

    def _boom() -> None:
        raise AssertionError("get_llm_provider should not be called with zero candidates")

    monkeypatch.setattr("app.graphs.intake.skill_normalizer.get_llm_provider", _boom)

    result = skill_normalizer(_state([_skill("Some Obscure Skill")]))

    normalized = result["normalized_skills"]
    assert len(normalized) == 1
    assert normalized[0].canonical is None
    assert normalized[0].taxonomy_id is None


def test_normalizer_empty_extracted_skills_short_circuits(
    sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom() -> None:
        raise AssertionError("hybrid_search should not be called for an empty skill list")

    monkeypatch.setattr("app.graphs.intake.skill_normalizer.hybrid_search", _boom)

    result = skill_normalizer(_state([]))

    assert result == {"normalized_skills": []}
