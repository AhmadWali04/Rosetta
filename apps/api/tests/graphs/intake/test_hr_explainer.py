"""Unit test for `hr_explainer` (PRD §7.1 node 8).

Mocks `get_llm_provider` at this node's own import site; uses a real
sqlite-in-memory `jd_requirements` table (same fixture pattern as the other
node tests in this package) to exercise the real requirement-text hydration
query. `hr_explainer` is a plain sync function; it bridges its own async
LLM call internally with a single `asyncio.run(...)`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

import app.db.session as db_session
from app.db.models import Base, JdRequirement
from app.graphs.intake.hr_explainer import HrExplanationResult, hr_explainer
from app.graphs.state import IntakeState, RequirementMatch
from app.llm.fake import FakeLLMProvider


@pytest.fixture
def sqlite_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    test_session_local = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "SessionLocal", test_session_local)
    yield engine


def _seed_requirement(engine: Engine, req_id: str = "r1", job_id: str = "j1") -> None:
    session_local = sessionmaker(bind=engine)
    with session_local() as session:
        session.add(
            JdRequirement(
                id=req_id,
                job_id=job_id,
                text="Experience with backend frameworks such as FastAPI",
                kind="must_have",
                weight=1.0,
                pinecone_id=f"req#{req_id}",
            )
        )
        session.commit()


def _state(matches: list[RequirementMatch]) -> IntakeState:
    return IntakeState(
        application_id="a1", job_id="j1", resume_path="resume.pdf", requirement_matches=matches
    )


def test_hr_explainer_happy_path(sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_requirement(sqlite_engine)
    fake = FakeLLMProvider(
        responses={
            "HrExplanationResult": HrExplanationResult(
                per_requirement={"r1": "FastAPI is a Python backend framework - this fits."},
                overall="Strong overall fit.",
            )
        }
    )
    monkeypatch.setattr("app.graphs.intake.hr_explainer.get_llm_provider", lambda: fake)

    match = RequirementMatch(
        requirement_id="r1", status="met", resolved_chunk_ids=["a1#chunk#0"], rationale="r"
    )
    result = hr_explainer(_state([match]))

    payload = json.loads(result["explanation"])
    assert payload["per_requirement"]["r1"] == "FastAPI is a Python backend framework - this fits."
    assert payload["overall"] == "Strong overall fit."


def test_hr_explainer_filters_invented_requirement_ids(
    sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never invent new claims about a requirement not actually evaluated —
    an LLM response with an extra, unrelated requirement_id key must be
    dropped."""
    _seed_requirement(sqlite_engine)
    fake = FakeLLMProvider(
        responses={
            "HrExplanationResult": HrExplanationResult(
                per_requirement={
                    "r1": "Fits well.",
                    "r999": "This requirement was never evaluated.",
                },
                overall="Looks fine.",
            )
        }
    )
    monkeypatch.setattr("app.graphs.intake.hr_explainer.get_llm_provider", lambda: fake)

    match = RequirementMatch(requirement_id="r1", status="met", resolved_chunk_ids=["c0"])
    result = hr_explainer(_state([match]))

    payload = json.loads(result["explanation"])
    assert set(payload["per_requirement"].keys()) == {"r1"}


def test_hr_explainer_no_requirement_matches_skips_llm(
    sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom() -> None:
        raise AssertionError("get_llm_provider should not be called with no requirement_matches")

    monkeypatch.setattr("app.graphs.intake.hr_explainer.get_llm_provider", _boom)

    result = hr_explainer(_state([]))

    payload = json.loads(result["explanation"])
    assert payload["per_requirement"] == {}
    assert payload["overall"]
