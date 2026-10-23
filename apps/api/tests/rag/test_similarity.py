"""Summary similarity resolves record IDs against job-scoped Postgres owners."""

from contextlib import contextmanager

import pytest

from app.db.models import Application, Job, ResumeChunk
from app.rag import similarity
from app.rag.vector_store import ScoredMatch

JOB = "job-ai-intern-procogia"


def test_similarity_uses_dense_summary_query_and_scopes_peer_ids(db_session, monkeypatch):
    @contextmanager
    def scope():
        yield db_session

    monkeypatch.setattr(similarity, "session_scope", scope)
    db_session.add(Job(id="other", title="Other", raw_jd="Other", requirements=[]))
    for identifier, job in [("a", JOB), ("b", JOB), ("foreign", "other")]:
        db_session.add(
            Application(
                id=identifier,
                job_id=job,
                name=identifier,
                email="x@example.com",
                resume_path="unused",
            )
        )
    db_session.add(
        ResumeChunk(
            id="chunk",
            application_id="a",
            chunk_idx=0,
            section="skills",
            text="Python",
            char_start=0,
            char_end=6,
            pinecone_id="a#chunk#0",
            embed_model="fake",
        )
    )
    db_session.commit()

    class Embedder:
        async def embed_dense(self, texts):
            assert texts == ["Python"]
            return [[1.0, 0.0]]

    class Store:
        async def query(self, namespace, vector, top_k):
            assert namespace.endswith(f"candidates-{JOB}")
            assert vector == [1, 0]
            return [
                ScoredMatch(id=key, score=1, metadata={"application_id": "forged"})
                for key in ["a#summary", "foreign#summary", "b#summary"]
            ]

    monkeypatch.setattr(similarity, "get_embedder", lambda: Embedder())
    monkeypatch.setattr(similarity, "get_vector_store", lambda kind: Store())
    assert similarity.find_similar_candidates(JOB, "a") == (["b"], [])
    with pytest.raises(ValueError):
        similarity.find_similar_candidates(JOB, "foreign")


def test_similarity_missing_candidate_rejected(db_session, monkeypatch):
    @contextmanager
    def scope():
        yield db_session

    monkeypatch.setattr(similarity, "session_scope", scope)
    with pytest.raises(ValueError):
        similarity.find_similar_candidates(JOB, "absent")
