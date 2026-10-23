"""Vector parity uses persisted IDs and never modifies either store."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest
from scripts import vector_audit
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Application, JdRequirement, Job, ResumeChunk, SkillTaxonomy
from app.rag import namespaces
from app.rag.vector_store.base import VectorRecord
from app.rag.vector_store.memory import MemoryVectorStore
from app.services import vector_health

JOB_ID = "job-ai-intern-procogia"


@pytest.fixture
def stores(monkeypatch: pytest.MonkeyPatch) -> dict[str, MemoryVectorStore]:
    stores = {"dense": MemoryVectorStore(), "sparse": MemoryVectorStore()}
    monkeypatch.setattr("app.rag.indexer.get_vector_store", lambda kind: stores[kind])
    monkeypatch.setattr(vector_health, "get_settings", lambda: Settings(pinecone_env="dev"))
    return stores


def _seed(db: Session) -> None:
    db.add(
        SkillTaxonomy(
            id="python",
            canonical="Python",
            alt_labels=[],
            description="Language",
            source="onet",
            pinecone_id=namespaces.skill_record_id("python"),
        )
    )
    db.add(
        JdRequirement(
            id="req",
            job_id=JOB_ID,
            text="Python",
            kind="must_have",
            weight=1,
            pinecone_id=namespaces.requirement_record_id("req"),
        )
    )
    for identifier in ("with-chunks", "empty"):
        db.add(
            Application(
                id=identifier,
                job_id=JOB_ID,
                name="Synthetic",
                email="synthetic@example.com",
                resume_path="unused.pdf",
                vector_status="failed",
            )
        )
    db.flush()
    for index in range(2):
        db.add(
            ResumeChunk(
                id=f"row-{index}",
                application_id="with-chunks",
                chunk_idx=index,
                section="experience",
                text="Python",
                char_start=index * 10,
                char_end=index * 10 + 6,
                pinecone_id=namespaces.chunk_record_id("with-chunks", index),
                embed_model="fake",
            )
        )
    db.flush()


async def _upsert(store: MemoryVectorStore, namespace: str, identifiers: list[str]) -> None:
    await store.upsert(
        namespace, [VectorRecord(id=value, values=[1.0], metadata={}) for value in identifiers]
    )


@pytest.mark.asyncio
async def test_all_namespaces_derive_ids_from_postgres_with_dense_only_summaries(
    db_session: Session,
    stores: dict[str, MemoryVectorStore],
) -> None:
    _seed(db_session)
    both = {
        namespaces.taxonomy_namespace("dev"): [namespaces.skill_record_id("python")],
        namespaces.jd_namespace("dev", JOB_ID): [namespaces.requirement_record_id("req")],
        namespaces.resumes_namespace("dev", JOB_ID): [
            namespaces.chunk_record_id("with-chunks", index) for index in range(2)
        ],
    }
    for namespace, identifiers in both.items():
        for store in stores.values():
            await _upsert(store, namespace, identifiers)
    summary_ns = namespaces.candidates_namespace("dev", JOB_ID)
    await _upsert(
        stores["dense"], summary_ns, [namespaces.candidate_summary_record_id("with-chunks")]
    )

    reports = await vector_health.audit_vectors(db_session)

    assert len(reports) == 4
    assert {report["namespace"] for report in reports} == {*both, summary_ns}
    assert all(report["parity"] for report in reports)
    assert all(not report["missing_sparse"] for report in reports)
    assert db_session.get(Application, "with-chunks").vector_status == "failed"
    assert await stores["sparse"].list_ids(summary_ns) == []


@pytest.mark.asyncio
async def test_one_sided_resume_drift_and_orphans_fail_without_mutating_stores(
    db_session: Session,
    stores: dict[str, MemoryVectorStore],
) -> None:
    _seed(db_session)
    namespace = namespaces.resumes_namespace("dev", JOB_ID)
    chunk_ids = [namespaces.chunk_record_id("with-chunks", index) for index in range(2)]
    orphan = namespaces.chunk_record_id("orphan", 0)
    await _upsert(stores["dense"], namespace, chunk_ids)
    await _upsert(stores["sparse"], namespace, [chunk_ids[0], orphan])

    reports = await vector_health.audit_vectors(db_session, namespace)

    assert len(reports) == 1
    report = reports[0]
    assert not report["parity"]
    assert report["missing_sparse"] == [chunk_ids[1]]
    assert orphan in report["orphaned"]
    assert await stores["dense"].list_ids(namespace) == chunk_ids
    assert await stores["sparse"].list_ids(namespace) == [chunk_ids[0], orphan]


@pytest.mark.asyncio
async def test_no_chunks_means_no_expected_candidate_summary(
    db_session: Session,
    stores: dict[str, MemoryVectorStore],
) -> None:
    namespace = namespaces.candidates_namespace("dev", JOB_ID)
    db_session.add(
        Application(
            id="empty",
            job_id=JOB_ID,
            name="Empty",
            email="empty@example.com",
            resume_path="unused.pdf",
        )
    )
    db_session.flush()
    reports = await vector_health.audit_vectors(db_session, namespace)
    assert reports[0]["parity"]
    await _upsert(stores["dense"], namespace, [namespaces.candidate_summary_record_id("empty")])
    reports = await vector_health.audit_vectors(db_session, namespace)
    assert not reports[0]["parity"]
    assert reports[0]["orphaned"] == [namespaces.candidate_summary_record_id("empty")]


@pytest.mark.asyncio
async def test_all_jobs_are_audited_and_namespaces_are_isolated(
    db_session: Session,
    stores: dict[str, MemoryVectorStore],
) -> None:
    db_session.add(Job(id="other-job", title="Other", raw_jd="JD", requirements=[]))
    db_session.flush()
    reports = await vector_health.audit_vectors(db_session)
    assert len(reports) == 7
    assert all(report["parity"] for report in reports)
    assert namespaces.resumes_namespace("dev", "other-job") in {
        report["namespace"] for report in reports
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "namespace",
    [
        namespaces.taxonomy_namespace("demo"),
        namespaces.taxonomy_namespace("eval"),
        namespaces.jd_namespace("dev", "unknown-job"),
        "unknown",
    ],
)
async def test_unknown_or_foreign_environment_namespace_rejected_before_vector_access(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    namespace: str,
) -> None:
    monkeypatch.setattr(vector_health, "get_settings", lambda: Settings(pinecone_env="dev"))
    audit = AsyncMock()
    monkeypatch.setattr(vector_health, "audit_namespace", audit)
    with pytest.raises(ValueError, match="Unknown namespace"):
        await vector_health.audit_vectors(db_session, namespace)
    audit.assert_not_awaited()


@pytest.mark.parametrize("parity, exit_code", [(True, 0), (False, 1)])
def test_cli_reports_parity_and_uses_nonzero_exit_for_drift(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    parity: bool,
    exit_code: int,
) -> None:
    namespace = namespaces.taxonomy_namespace("dev")
    report = [{"namespace": namespace, "parity": parity}]
    audit = AsyncMock(return_value=report)
    monkeypatch.setattr(vector_audit, "audit_vectors", audit)

    @contextmanager
    def fake_session():
        yield "fake-db"

    monkeypatch.setattr(vector_audit, "session_scope", fake_session)
    assert vector_audit.main(["--namespace", namespace]) == exit_code
    audit.assert_awaited_once_with("fake-db", namespace)
    assert namespace in capsys.readouterr().out


def test_cli_redacts_connection_error_details(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(vector_audit, "_run", AsyncMock(side_effect=RuntimeError("secret-token")))
    assert vector_audit.main([]) == 2
    output = capsys.readouterr().out
    assert "secret-token" not in output
    assert "RuntimeError" in output


def test_cli_uses_exported_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    namespace = namespaces.taxonomy_namespace("dev")
    monkeypatch.setenv("NS", namespace)
    run = AsyncMock(return_value=[{"namespace": namespace, "parity": True}])
    monkeypatch.setattr(vector_audit, "_run", run)
    assert vector_audit.main([]) == 0
    run.assert_awaited_once_with(namespace)
