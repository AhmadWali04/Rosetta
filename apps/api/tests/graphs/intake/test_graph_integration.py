"""Integration test for the full 9-node static intake graph (PRD §7.1),
assembled by `app.graphs.intake.graph.build_intake_graph`.

Uses `VECTOR_BACKEND=memory` (real `MemoryVectorStore` + `FakeEmbedder`,
AGENTS.md "Testing rules") and a real sqlite-in-memory Postgres stand-in
(`Base.metadata.create_all()`, same fixture pattern as every other node
test in this package). The graph is compiled with NO checkpointer (`
build_intake_graph().compile()`, no `checkpointer=` kwarg) so this test
needs no live Postgres connection just to exercise node wiring end-to-end
- `run_intake_graph` (the real Postgres-checkpointed entry point) is
exercised separately, if at all, by a live/manual smoke test, not here.

External dependencies not owned by this agent (`extract_pdf`,
`segment_sections`, `chunk_sections`, `check_rules`, `check_llm`,
`wait_for_freshness`, `hybrid_search`, `get_llm_provider`) are mocked at
each node's own import site, same convention as the other node-level unit
tests in this package.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

import app.db.session as db_session
from app.config import get_settings
from app.db.models import Application, Base, JdRequirement, Job, Profile, SkillTaxonomy
from app.graphs.intake.graph import build_intake_graph
from app.graphs.intake.hr_explainer import HrExplanationResult, RequirementExplanation
from app.graphs.intake.requirement_matcher import RequirementJudgment
from app.graphs.intake.skill_extractor import SkillExtractionResult
from app.graphs.intake.skill_normalizer import SkillNormalizationItem, SkillNormalizationResult
from app.graphs.state import ChunkData, ExtractedSkill, IntakeState, Section
from app.llm.fake import FakeLLMProvider
from app.rag.retriever import RetrievedMatch

APPLICATION_ID = "app-1"
JOB_ID = "job-1"

RESUME_TEXT = "Jordan Example\n\nExperience\nShipped a production ML pipeline using PyTorch.\n"


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


def _seed(engine: Engine) -> None:
    session_local = sessionmaker(bind=engine)
    with session_local() as session:
        session.add(Job(id=JOB_ID, title="AI Intern", raw_jd="Looking for PyTorch experience."))
        session.add(
            JdRequirement(
                id="req-pytorch",
                job_id=JOB_ID,
                text="Experience with PyTorch",
                kind="must_have",
                weight=1.0,
                pinecone_id="req#req-pytorch",
            )
        )
        session.add(
            Application(
                id=APPLICATION_ID,
                job_id=JOB_ID,
                name="Jordan Example",
                email="jordan@example.com",
                resume_path="resume.pdf",
            )
        )
        session.add(
            SkillTaxonomy(
                id="tax-pytorch",
                canonical="PyTorch",
                alt_labels=[],
                description="Deep learning framework",
                source="onet",
                pinecone_id="skill#tax-pytorch",
            )
        )
        session.commit()


def _fake_sections(text: str) -> list[Section]:
    return [Section(name="experience", text=text, char_start=0, char_end=len(text))]


def _fake_chunks(sections: list[Section], *args, **kwargs) -> list[ChunkData]:
    text = sections[0].text
    return [
        ChunkData(
            chunk_idx=0,
            section=sections[0].name,
            text=text,
            char_start=0,
            char_end=len(text),
            pinecone_id="placeholder",
        )
    ]


@pytest.fixture
def mocked_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wires every cross-agent dependency this graph run touches, except
    the real `MemoryVectorStore`/`FakeEmbedder` path (VECTOR_BACKEND=memory)
    - those are exercised for real, matching `test_chunk_and_index.py`'s own
    precedent for this package.
    """
    raw_doc = SimpleNamespace(text=RESUME_TEXT, hidden_spans=[])

    # --- ingest_parse / sanitize (Agent C) ---
    monkeypatch.setattr("app.graphs.intake.ingest_parse.extract_pdf", lambda path: raw_doc)
    monkeypatch.setattr("app.graphs.intake.ingest_parse.segment_sections", _fake_sections)
    monkeypatch.setattr("app.graphs.intake.sanitize.extract_pdf", lambda path: raw_doc)
    monkeypatch.setattr("app.graphs.intake.sanitize.check_rules", lambda text: [])
    monkeypatch.setattr(
        "app.graphs.intake.sanitize.check_llm",
        AsyncMock(return_value=SimpleNamespace(confidence=0.0)),
    )

    # --- chunk_and_index (Agent C) ---
    monkeypatch.setattr("app.graphs.intake.chunk_and_index.segment_sections", _fake_sections)
    monkeypatch.setattr(
        "app.graphs.intake.chunk_and_index.chunk_sections",
        lambda sections, *a, **kw: _fake_chunks(sections),
    )
    monkeypatch.setattr(
        "app.graphs.intake.chunk_and_index.wait_for_freshness",
        AsyncMock(return_value=True),
    )

    # --- skill_extractor (this agent) ---
    extractor_fake = FakeLLMProvider(
        responses={
            "SkillExtractionResult": SkillExtractionResult(
                skills=[
                    ExtractedSkill(
                        skill="PyTorch",
                        evidence_span="Shipped a production ML pipeline using PyTorch",
                        context="Experience",
                        recency="current",
                        depth_signal="production",
                    )
                ]
            )
        }
    )
    monkeypatch.setattr(
        "app.graphs.intake.skill_extractor.get_llm_provider", lambda: extractor_fake
    )

    # --- skill_normalizer (this agent) ---
    normalizer_fake = FakeLLMProvider(
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
    monkeypatch.setattr(
        "app.graphs.intake.skill_normalizer.get_llm_provider", lambda: normalizer_fake
    )
    monkeypatch.setattr(
        "app.graphs.intake.skill_normalizer.hybrid_search",
        AsyncMock(return_value=[RetrievedMatch(id="skill#tax-pytorch", score=0.9, metadata={})]),
    )

    # --- requirement_matcher (this agent) ---
    matcher_fake = FakeLLMProvider(
        responses={
            "RequirementJudgment": RequirementJudgment(
                status="met",
                cited_chunk_ids=[f"{APPLICATION_ID}#chunk#0"],
                rationale="Shipped a production PyTorch pipeline.",
            )
        }
    )
    monkeypatch.setattr(
        "app.graphs.intake.requirement_matcher.get_llm_provider", lambda: matcher_fake
    )
    monkeypatch.setattr(
        "app.graphs.intake.requirement_matcher.hybrid_search",
        AsyncMock(
            return_value=[RetrievedMatch(id=f"{APPLICATION_ID}#chunk#0", score=0.95, metadata={})]
        ),
    )

    # --- hr_explainer (this agent) ---
    explainer_fake = FakeLLMProvider(
        responses={
            "HrExplanationResult": HrExplanationResult(
                per_requirement=[
                    RequirementExplanation(
                        requirement_id="req-pytorch",
                        explanation="PyTorch experience is clearly demonstrated.",
                    )
                ],
                overall="Strong match on the one requirement.",
            )
        }
    )
    monkeypatch.setattr("app.graphs.intake.hr_explainer.get_llm_provider", lambda: explainer_fake)


def test_full_intake_graph_happy_path(sqlite_engine: Engine, mocked_dependencies: None) -> None:
    _seed(sqlite_engine)

    graph = build_intake_graph().compile()
    initial_state = IntakeState(
        application_id=APPLICATION_ID, job_id=JOB_ID, resume_path="resume.pdf"
    )

    result = graph.invoke(initial_state)
    final_state = IntakeState.model_validate(result)

    assert final_state.vector_status == "indexed"
    assert len(final_state.extracted_skills) == 1
    assert final_state.normalized_skills[0].canonical == "PyTorch"
    assert len(final_state.requirement_matches) == 1
    assert final_state.requirement_matches[0].status == "met"
    assert final_state.requirement_matches[0].resolved_chunk_ids == [f"{APPLICATION_ID}#chunk#0"]
    assert final_state.recommendation in {"advance", "review", "decline"}
    assert 0.0 <= final_state.score <= 1.0
    assert final_state.explanation  # non-empty JSON string

    # persist actually wrote the profile row and flipped Application.status.
    session_local = sessionmaker(bind=sqlite_engine)
    with session_local() as session:
        profile = session.get(Profile, APPLICATION_ID)
        assert profile is not None
        assert profile.recommendation == final_state.recommendation

        application = session.get(Application, APPLICATION_ID)
        assert application is not None
        assert application.status == "analyzed"


def test_full_intake_graph_vector_failure_falls_back_in_requirement_matcher(
    sqlite_engine: Engine, mocked_dependencies: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PRD §8.5: a vector-layer upsert failure degrades `vector_status` to
    "failed" in `chunk_and_index`, and `requirement_matcher` must then take
    the in-state cosine fallback instead of calling `hybrid_search` at all.
    """
    _seed(sqlite_engine)

    monkeypatch.setattr(
        "app.graphs.intake.chunk_and_index.get_vector_store",
        lambda kind: (_ for _ in ()).throw(RuntimeError("pinecone is down")),
    )

    def _boom(*args, **kwargs):
        raise AssertionError("hybrid_search must not be called once vector_status == 'failed'")

    monkeypatch.setattr("app.graphs.intake.requirement_matcher.hybrid_search", _boom)

    graph = build_intake_graph().compile()
    initial_state = IntakeState(
        application_id=APPLICATION_ID, job_id=JOB_ID, resume_path="resume.pdf"
    )

    # Must complete without raising (PRD §8.5: degrade gracefully, never crash).
    result = graph.invoke(initial_state)
    final_state = IntakeState.model_validate(result)

    assert final_state.vector_status == "failed"
    assert "vector_index_failed" in final_state.flags
    # The fallback still found the chunk via cosine similarity against
    # state.chunk_vectors and the LLM still judged it "met" with a citation
    # that resolves against Postgres resume_chunks.
    assert final_state.requirement_matches[0].status == "met"
    assert final_state.requirement_matches[0].resolved_chunk_ids == [f"{APPLICATION_ID}#chunk#0"]
