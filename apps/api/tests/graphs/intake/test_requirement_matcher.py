"""Unit test for `requirement_matcher` (PRD §7.1 node 6) — this is the
central implementation of AGENTS.md invariant #1 ("citations or it didn't
happen"), so these tests focus hardest on the resolve/downgrade logic.

Mocks `hybrid_search` (Agent B) and `get_llm_provider` (Agent A) at this
node's own import site; uses a real sqlite-in-memory DB for
`jd_requirements`/`resume_chunks` (same fixture pattern as the other node
tests in this package) so the actual citation-resolution SQL query is
exercised, not mocked.

`requirement_matcher` is a plain sync function; it bridges its own async
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
from app.db.models import Base, JdRequirement, ResumeChunk
from app.graphs.intake.requirement_matcher import RequirementJudgment, requirement_matcher
from app.graphs.state import IntakeState
from app.llm.fake import FakeLLMProvider
from app.rag.embeddings import get_embedder
from app.rag.retriever import RetrievedMatch


@pytest.fixture
def sqlite_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    test_session_local = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "SessionLocal", test_session_local)
    yield engine


def _seed(engine: Engine, *, application_id: str = "a1", job_id: str = "j1") -> None:
    session_local = sessionmaker(bind=engine)
    with session_local() as session:
        session.add(
            JdRequirement(
                id="r1",
                job_id=job_id,
                text="Experience with PyTorch",
                kind="must_have",
                weight=1.0,
                pinecone_id="req#r1",
            )
        )
        session.add(
            ResumeChunk(
                id="chunk-row-1",
                application_id=application_id,
                chunk_idx=0,
                section="experience",
                text="Shipped a production model using PyTorch.",
                char_start=0,
                char_end=42,
                pinecone_id=f"{application_id}#chunk#0",
                embed_model="llama-text-embed-v2",
            )
        )
        session.commit()


def _state(**overrides) -> IntakeState:
    base = dict(application_id="a1", job_id="j1", resume_path="resume.pdf")
    base.update(overrides)
    return IntakeState(**base)


def test_met_with_valid_citation_resolves(
    sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(sqlite_engine)
    monkeypatch.setattr(
        "app.graphs.intake.requirement_matcher.hybrid_search",
        AsyncMock(return_value=[RetrievedMatch(id="a1#chunk#0", score=0.9, metadata={})]),
    )
    fake = FakeLLMProvider(
        responses={
            "RequirementJudgment": RequirementJudgment(
                status="met",
                cited_chunk_ids=["a1#chunk#0"],
                rationale="Shipped a production PyTorch model.",
            )
        }
    )
    monkeypatch.setattr("app.graphs.intake.requirement_matcher.get_llm_provider", lambda: fake)

    result = requirement_matcher(_state())

    matches = result["requirement_matches"]
    assert len(matches) == 1
    assert matches[0].requirement_id == "r1"
    assert matches[0].status == "met"
    assert matches[0].resolved_chunk_ids == ["a1#chunk#0"]


def test_met_with_no_cited_ids_is_downgraded_to_missing(
    sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AGENTS.md invariant #1: an uncited "met"/"partial" claim is never
    shown as fact."""
    _seed(sqlite_engine)
    monkeypatch.setattr(
        "app.graphs.intake.requirement_matcher.hybrid_search",
        AsyncMock(return_value=[RetrievedMatch(id="a1#chunk#0", score=0.9, metadata={})]),
    )
    fake = FakeLLMProvider(
        responses={
            "RequirementJudgment": RequirementJudgment(
                status="met", cited_chunk_ids=[], rationale="Looks good."
            )
        }
    )
    monkeypatch.setattr("app.graphs.intake.requirement_matcher.get_llm_provider", lambda: fake)

    result = requirement_matcher(_state())

    match = result["requirement_matches"][0]
    assert match.status == "missing"
    assert match.resolved_chunk_ids == []
    assert "downgraded" in match.rationale


def test_hallucinated_citation_does_not_resolve_and_downgrades(
    sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The LLM cites a chunk id that doesn't exist (for this application) in
    Postgres - it must not resolve, regardless of whether it was offered."""
    _seed(sqlite_engine)
    monkeypatch.setattr(
        "app.graphs.intake.requirement_matcher.hybrid_search",
        AsyncMock(return_value=[RetrievedMatch(id="a1#chunk#0", score=0.9, metadata={})]),
    )
    fake = FakeLLMProvider(
        responses={
            "RequirementJudgment": RequirementJudgment(
                status="partial",
                cited_chunk_ids=["a1#chunk#999"],  # never existed
                rationale="Some evidence.",
            )
        }
    )
    monkeypatch.setattr("app.graphs.intake.requirement_matcher.get_llm_provider", lambda: fake)

    result = requirement_matcher(_state())

    match = result["requirement_matches"][0]
    assert match.cited_chunk_ids == ["a1#chunk#999"]
    assert match.resolved_chunk_ids == []
    assert match.status == "missing"


def test_missing_status_is_not_downgraded_further(
    sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(sqlite_engine)
    monkeypatch.setattr(
        "app.graphs.intake.requirement_matcher.hybrid_search",
        AsyncMock(return_value=[RetrievedMatch(id="a1#chunk#0", score=0.9, metadata={})]),
    )
    fake = FakeLLMProvider(
        responses={
            "RequirementJudgment": RequirementJudgment(
                status="missing", cited_chunk_ids=[], rationale="No evidence found."
            )
        }
    )
    monkeypatch.setattr("app.graphs.intake.requirement_matcher.get_llm_provider", lambda: fake)

    result = requirement_matcher(_state())

    match = result["requirement_matches"][0]
    assert match.status == "missing"
    assert "downgraded" not in match.rationale


def test_vector_status_failed_uses_cosine_fallback_not_hybrid_search(
    sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PRD §8.5: when `vector_status == 'failed'`, skip the Pinecone round
    trip entirely and use the in-state `chunk_vectors` with a direct cosine
    comparison instead."""
    _seed(sqlite_engine)

    def _boom(*args, **kwargs):
        raise AssertionError("hybrid_search must not be called when vector_status == 'failed'")

    monkeypatch.setattr("app.graphs.intake.requirement_matcher.hybrid_search", _boom)

    import asyncio

    embedder = get_embedder()
    [req_vector] = asyncio.run(embedder.embed_dense(["Experience with PyTorch"]))

    fake = FakeLLMProvider(
        responses={
            "RequirementJudgment": RequirementJudgment(
                status="met",
                cited_chunk_ids=["a1#chunk#0"],
                rationale="Matches via fallback.",
            )
        }
    )
    monkeypatch.setattr("app.graphs.intake.requirement_matcher.get_llm_provider", lambda: fake)

    state = _state(
        vector_status="failed",
        chunk_vectors={"a1#chunk#0": req_vector},
    )
    result = requirement_matcher(state)

    match = result["requirement_matches"][0]
    assert match.status == "met"
    assert match.resolved_chunk_ids == ["a1#chunk#0"]


def test_vector_freshness_timeout_flag_also_triggers_fallback(
    sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(sqlite_engine)

    def _boom(*args, **kwargs):
        raise AssertionError("hybrid_search must not be called under a freshness timeout flag")

    monkeypatch.setattr("app.graphs.intake.requirement_matcher.hybrid_search", _boom)

    fake = FakeLLMProvider(
        responses={
            "RequirementJudgment": RequirementJudgment(
                status="missing", cited_chunk_ids=[], rationale="n/a"
            )
        }
    )
    monkeypatch.setattr("app.graphs.intake.requirement_matcher.get_llm_provider", lambda: fake)

    state = _state(
        vector_status="indexed",
        flags=["vector_freshness_timeout"],
        chunk_vectors={"a1#chunk#0": [0.1, 0.2, 0.3]},
    )
    # Should not raise despite hybrid_search being wired to blow up.
    requirement_matcher(state)
