"""Unit tests for `app/rag/namespaces.py` — the only place namespace and
record-ID strings are formatted (AGENTS.md). Exact-string assertions here
are intentional: any accidental format drift here would silently break
Pinecone namespace partitioning or the delete-by-prefix invariant.

Run with: `cd apps/api && uv run pytest tests/rag/test_namespaces.py -v`
"""

from __future__ import annotations

from app.rag.namespaces import (
    application_id_prefix,
    candidate_summary_record_id,
    candidates_namespace,
    chunk_record_id,
    jd_namespace,
    requirement_record_id,
    resumes_namespace,
    skill_record_id,
    taxonomy_namespace,
)


def test_taxonomy_namespace() -> None:
    assert taxonomy_namespace("dev") == "dev-taxonomy"
    assert taxonomy_namespace("eval") == "eval-taxonomy"


def test_jd_namespace() -> None:
    assert jd_namespace("dev", "j_1") == "dev-jd-j_1"
    assert jd_namespace("demo", "j_42") == "demo-jd-j_42"


def test_resumes_namespace() -> None:
    assert resumes_namespace("dev", "j_1") == "dev-resumes-j_1"


def test_candidates_namespace() -> None:
    assert candidates_namespace("dev", "j_1") == "dev-candidates-j_1"


def test_skill_record_id() -> None:
    assert skill_record_id("onet_15-1252.00") == "skill#onet_15-1252.00"


def test_requirement_record_id() -> None:
    assert requirement_record_id("req_7") == "req#req_7"


def test_chunk_record_id() -> None:
    assert chunk_record_id("a_123", 4) == "a_123#chunk#4"
    assert chunk_record_id("a_123", 0) == "a_123#chunk#0"


def test_candidate_summary_record_id() -> None:
    assert candidate_summary_record_id("a_123") == "a_123#summary"


def test_application_id_prefix() -> None:
    assert application_id_prefix("a_123") == "a_123#"


def test_chunk_and_summary_ids_start_with_application_prefix() -> None:
    """Delete-by-prefix invariant (PRD §8.7 / AGENTS.md invariant 9): every
    record belonging to an application must be purgeable by prefix."""
    app_id = "a_999"
    prefix = application_id_prefix(app_id)

    assert chunk_record_id(app_id, 0).startswith(prefix)
    assert chunk_record_id(app_id, 17).startswith(prefix)
    assert candidate_summary_record_id(app_id).startswith(prefix)
