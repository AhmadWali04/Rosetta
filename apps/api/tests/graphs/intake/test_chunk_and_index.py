"""Unit test for `chunk_and_index` (PRD §7.1/§8 node 3) — the busiest node
in this package.

Uses `VECTOR_BACKEND=memory` (AGENTS.md "Testing rules") so the real
`MemoryVectorStore` + `FakeEmbedder` path is exercised end-to-end (metadata
shape, namespaces, DB writes), and mocks only the two functions owned by
Agent A/B: `segment_sections` and `chunk_sections`, plus `wait_for_freshness`
(also Agent B's, added to `app/rag/indexer.py` in parallel).

At write time, `app/rag/chunking.py` (`chunk_sections`) and
`wait_for_freshness` in `app/rag/indexer.py` (both Agent B's, built in
parallel) do not exist yet — this file will fail at collection with
`ModuleNotFoundError`/`ImportError` until that module lands. Expected per
the cross-agent dependency note.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

import app.db.session as db_session
from app.config import get_settings
from app.db.models import Application, Base, Event, Job, ResumeChunk
from app.graphs.intake.chunk_and_index import chunk_and_index
from app.graphs.state import ChunkData, IntakeState, Section


@pytest.fixture
def sqlite_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    test_session_local = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "SessionLocal", test_session_local)
    yield engine


@pytest.fixture(autouse=True)
def memory_vector_backend(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("VECTOR_BACKEND", "memory")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _seed_application(engine: Engine, application_id: str, job_id: str) -> None:
    session_local = sessionmaker(bind=engine)
    with session_local() as session:
        session.add(Job(id=job_id, title="t", raw_jd="jd", requirements=[]))
        session.add(
            Application(
                id=application_id,
                job_id=job_id,
                name="n",
                email="e@example.com",
                resume_path="resume.pdf",
            )
        )
        session.commit()


def _state() -> IntakeState:
    return IntakeState(
        application_id="a1",
        job_id="j1",
        resume_path="resume.pdf",
        sanitized_text="Built a RAG pipeline with LangChain.",
    )


def _fake_sections(text: str) -> list[Section]:
    return [Section(name="experience", text=text, char_start=0, char_end=len(text))]


def _fake_chunks(sections: list[Section]) -> list[ChunkData]:
    return [
        ChunkData(
            chunk_idx=0,
            section=sections[0].name,
            text=sections[0].text,
            char_start=0,
            char_end=len(sections[0].text),
            pinecone_id="placeholder",
        )
    ]


@pytest.mark.asyncio
async def test_chunk_and_index_happy_path(sqlite_engine: Engine) -> None:
    _seed_application(sqlite_engine, "a1", "j1")

    with (
        patch(
            "app.graphs.intake.chunk_and_index.segment_sections",
            side_effect=_fake_sections,
        ),
        patch(
            "app.graphs.intake.chunk_and_index.chunk_sections",
            side_effect=lambda sections, **_: _fake_chunks(sections),
        ),
        patch(
            "app.graphs.intake.chunk_and_index.wait_for_freshness",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        result = await chunk_and_index(_state())

    assert result["vector_status"] == "indexed"
    assert len(result["chunks"]) == 1
    assert result["chunks"][0].pinecone_id == "a1#chunk#0"
    assert result["chunks"][0].pinecone_id in result["chunk_vectors"]
    assert len(result["summary_vector"]) > 0
    assert "vector_freshness_timeout" not in result["flags"]
    assert "vector_index_failed" not in result["flags"]

    session_local = sessionmaker(bind=sqlite_engine)
    with session_local() as session:
        chunks = session.query(ResumeChunk).filter_by(application_id="a1").all()
        assert len(chunks) == 1
        assert chunks[0].pinecone_id == "a1#chunk#0"

        app_row = session.get(Application, "a1")
        assert app_row is not None
        assert app_row.vector_status == "indexed"

        events = session.query(Event).filter_by(application_id="a1").all()
        assert any(e.action == "intake_vectors_indexed" for e in events)


@pytest.mark.asyncio
async def test_chunk_and_index_freshness_timeout_is_non_fatal(sqlite_engine: Engine) -> None:
    _seed_application(sqlite_engine, "a1", "j1")

    with (
        patch(
            "app.graphs.intake.chunk_and_index.segment_sections",
            side_effect=_fake_sections,
        ),
        patch(
            "app.graphs.intake.chunk_and_index.chunk_sections",
            side_effect=lambda sections, **_: _fake_chunks(sections),
        ),
        patch(
            "app.graphs.intake.chunk_and_index.wait_for_freshness",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        result = await chunk_and_index(_state())

    # PRD §8.6: a freshness timeout is non-fatal — status still "indexed",
    # just flagged, and chunk_vectors is still populated as the fallback.
    assert result["vector_status"] == "indexed"
    assert "vector_freshness_timeout" in result["flags"]
    assert result["chunk_vectors"]


@pytest.mark.asyncio
async def test_chunk_and_index_upsert_failure_sets_failed_status(sqlite_engine: Engine) -> None:
    _seed_application(sqlite_engine, "a1", "j1")

    with (
        patch(
            "app.graphs.intake.chunk_and_index.segment_sections",
            side_effect=_fake_sections,
        ),
        patch(
            "app.graphs.intake.chunk_and_index.chunk_sections",
            side_effect=lambda sections, **_: _fake_chunks(sections),
        ),
        patch(
            "app.graphs.intake.chunk_and_index.get_vector_store",
            side_effect=RuntimeError("pinecone is down"),
        ),
    ):
        result = await chunk_and_index(_state())

    # PRD §8.5: a vector-layer failure degrades gracefully, never crashes
    # the node, and chunk_vectors still holds the in-state fallback.
    assert result["vector_status"] == "failed"
    assert "vector_index_failed" in result["flags"]
    assert result["chunk_vectors"]

    session_local = sessionmaker(bind=sqlite_engine)
    with session_local() as session:
        app_row = session.get(Application, "a1")
        assert app_row is not None
        assert app_row.vector_status == "failed"

        events = session.query(Event).filter_by(application_id="a1").all()
        assert any(e.action == "vector_upsert_failed" for e in events)
