"""Chunk & Index node (PRD §7.1/§8, third node in the static intake graph) —
the busiest node in this package.

Sequence (mirrors the task brief's numbered steps):
1. Re-segment `state.sanitized_text` (NOT remap `state.sections`' offsets —
   see `_resegment`) and chunk it via Agent B's `chunk_sections`.
2. Fill in each chunk's `pinecone_id` via `namespaces.chunk_record_id`.
3. Write `ResumeChunk` rows to Postgres, set `Application.vector_status =
   "indexing"`, commit — Postgres first (AGENTS.md invariant #7).
4. Embed chunk texts (dense + sparse) and upsert to both vector stores. On
   failure: `vector_status = "failed"`, write a `vector_upsert_failed`
   Event, flag it, and continue — never crash the node (PRD §8.5).
5. Build one candidate-level dense summary vector and upsert it too; store
   the raw vector in state so the Scorer doesn't need a second round-trip.
6. Wait for freshness on the resumes namespace; on timeout, flag it and
   rely on `chunk_vectors` held in state (PRD §8.6).
7. On success, set `vector_status = "indexed"` and write an
   `intake_vectors_indexed` Event.
8. Return the full partial state update.

Section re-derivation (step 1) — the one judgment call most worth
explaining: `state.sections` (from `ingest_parse`) carries `char_start`/
`char_end` offsets into `raw_text`, but `sanitize` may have shortened that
text by stripping hidden spans. The task brief offered two ways to
reconcile this: (a) re-run `segment_sections` on `sanitized_text` and
accept a small amount of redundant parsing work, or (b) remap every
offset through the cumulative length of every removed span. This node
takes (a), the explicitly recommended option — it is trivially correct
(the recomputed sections are offsets into the exact text being chunked),
whereas (b) is the kind of thing that's quietly wrong whenever a stripped
span straddles a section boundary. `ChunkData.char_start`/`char_end` are
documented in `graphs/state.py` as offsets into the *sanitized* text,
which is exactly what re-segmenting produces.

Failure containment: the dense+sparse embed-and-upsert sequence for
chunks, and the summary-vector embed-and-upsert, are each wrapped in their
own `try/except Exception`. This is intentionally broad — the PRD's
contract for this node is "degrade gracefully, never crash" for anything
vector-layer-shaped (network errors, index-not-found, batch failures after
the store's own internal retries are exhausted), and the two phases are
independent enough that a failure in one shouldn't block the other from
still being attempted.

`async def`, matching every other node in this package (see
`ingest_parse.py`'s docstring) — and genuinely needed here, since this
node awaits the embedder, both vector stores, and `wait_for_freshness`.
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.db.models import Application, Event, ResumeChunk
from app.db.session import session_scope
from app.graphs.state import ChunkData, IntakeState, Section
from app.rag import namespaces
from app.rag.chunking import chunk_sections
from app.rag.embeddings import get_embedder
from app.rag.indexer import wait_for_freshness
from app.rag.vector_store import VectorRecord, get_vector_store
from app.services.resume_parsing import segment_sections

# PRD §8.3/§7.1 step 5: the candidate summary vector prefers Skills +
# Experience section text; this is the fallback truncation length (chars,
# not tokens — a simple, provider-agnostic cutoff) when those sections
# aren't found and `sanitized_text` is used directly instead.
SUMMARY_TEXT_MAX_CHARS = 6000

# Flag appended when a vector-layer write fails after the store's own
# retries are exhausted. Not literally named in PRD §7.1's prose (which
# names "vector_freshness_timeout" and "hidden_text_removed" explicitly but
# not this one) — chosen to mirror that naming convention.
VECTOR_INDEX_FAILED_FLAG = "vector_index_failed"
VECTOR_FRESHNESS_TIMEOUT_FLAG = "vector_freshness_timeout"


def _resegment(sanitized_text: str) -> list[Section]:
    """Re-derive sections from `sanitized_text` rather than remapping
    `state.sections`' offsets through a text-shortening operation. See the
    module docstring's "Section re-derivation" note."""
    return segment_sections(sanitized_text)


def _chunk_metadata(
    chunk: ChunkData, application_id: str, job_id: str, embed_model: str
) -> dict[str, Any]:
    """PRD §8.3 record metadata shape."""
    return {
        "application_id": application_id,
        "job_id": job_id,
        "section": chunk.section,
        "chunk_idx": chunk.chunk_idx,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "text": chunk.text,
        "embed_model": embed_model,
        "schema_version": 1,
    }


def _summary_text(sections: list[Section], sanitized_text: str) -> str:
    """One dense summary vector per PRD §7.1 step 5: prefer Skills +
    Experience section text (case-insensitive name match); fall back to a
    truncated `sanitized_text` when section-finding is unreliable — the
    fallback the task brief itself suggests."""
    wanted = {"skills", "experience"}
    picked = [s.text for s in sections if s.name.strip().lower() in wanted]
    if picked:
        return "\n\n".join(picked)
    return sanitized_text[:SUMMARY_TEXT_MAX_CHARS]


def _write_failure_event(application_id: str, namespace: str, exc: Exception) -> None:
    with session_scope() as session:
        application = session.get(Application, application_id)
        if application is not None:
            application.vector_status = "failed"
        session.add(
            Event(
                application_id=application_id,
                actor="system",
                action="vector_upsert_failed",
                payload={"error": repr(exc), "namespace": namespace},
            )
        )
        session.commit()


async def chunk_and_index(state: IntakeState) -> dict[str, Any]:
    settings = get_settings()
    flags = list(state.flags)

    sections = _resegment(state.sanitized_text)
    raw_chunks = chunk_sections(sections)
    chunks: list[ChunkData] = [
        c.model_copy(
            update={"pinecone_id": namespaces.chunk_record_id(state.application_id, c.chunk_idx)}
        )
        for c in raw_chunks
    ]

    # --- Step 3: Postgres first (AGENTS.md invariant #7) ---
    with session_scope() as session:
        application = session.get(Application, state.application_id)
        if application is None:
            raise ValueError(f"chunk_and_index: no Application row for id={state.application_id!r}")
        for chunk in chunks:
            session.add(
                ResumeChunk(
                    application_id=state.application_id,
                    chunk_idx=chunk.chunk_idx,
                    section=chunk.section,
                    text=chunk.text,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    pinecone_id=chunk.pinecone_id,
                    embed_model=settings.embedding_model,
                    indexed_at=None,
                )
            )
        application.vector_status = "indexing"
        session.commit()

    # --- Step 4: embed + upsert chunk vectors (dense + sparse) ---
    embedder = get_embedder()
    chunk_texts = [c.text for c in chunks]
    dense_vectors: list[list[float]] = (
        await embedder.embed_dense(chunk_texts) if chunk_texts else []
    )
    chunk_vectors: dict[str, list[float]] = {
        c.pinecone_id: vec for c, vec in zip(chunks, dense_vectors, strict=True)
    }

    resumes_ns = namespaces.resumes_namespace(settings.pinecone_env, state.job_id)
    vector_status = "indexed"
    try:
        if chunks:
            sparse_vectors = await embedder.embed_sparse(chunk_texts)
            dense_records = [
                VectorRecord(
                    id=c.pinecone_id,
                    values=vec,
                    metadata=_chunk_metadata(
                        c, state.application_id, state.job_id, settings.embedding_model
                    ),
                )
                for c, vec in zip(chunks, dense_vectors, strict=True)
            ]
            sparse_records = [
                VectorRecord(
                    id=c.pinecone_id,
                    values=[],
                    sparse_indices=sv.indices,
                    sparse_values=sv.values,
                    metadata=_chunk_metadata(
                        c, state.application_id, state.job_id, settings.sparse_model
                    ),
                )
                for c, sv in zip(chunks, sparse_vectors, strict=True)
            ]
            await get_vector_store("dense").upsert(resumes_ns, dense_records)
            await get_vector_store("sparse").upsert(resumes_ns, sparse_records)
    except Exception as exc:  # degrade gracefully, never crash the node (PRD §8.5)
        vector_status = "failed"
        if VECTOR_INDEX_FAILED_FLAG not in flags:
            flags.append(VECTOR_INDEX_FAILED_FLAG)
        _write_failure_event(state.application_id, resumes_ns, exc)

    # --- Step 5: candidate summary vector (dense only) ---
    summary_text = _summary_text(sections, state.sanitized_text)
    summary_vector: list[float] = []
    if summary_text.strip():
        summary_vectors = await embedder.embed_dense([summary_text])
        summary_vector = summary_vectors[0] if summary_vectors else []
        if summary_vector:
            candidates_ns = namespaces.candidates_namespace(settings.pinecone_env, state.job_id)
            summary_record = VectorRecord(
                id=namespaces.candidate_summary_record_id(state.application_id),
                values=summary_vector,
                metadata={
                    "application_id": state.application_id,
                    "job_id": state.job_id,
                    "embed_model": settings.embedding_model,
                    "schema_version": 1,
                },
            )
            try:
                await get_vector_store("dense").upsert(candidates_ns, [summary_record])
            except Exception as exc:  # same degrade-don't-crash contract as above
                if VECTOR_INDEX_FAILED_FLAG not in flags:
                    flags.append(VECTOR_INDEX_FAILED_FLAG)
                _write_failure_event(state.application_id, candidates_ns, exc)

    # --- Step 6: freshness wait (PRD §8.6) — only meaningful if the chunk
    # upsert above actually succeeded; a known failure shouldn't also pay a
    # freshness-poll timeout on top.
    if vector_status == "indexed" and chunks:
        fresh = await wait_for_freshness(
            resumes_ns,
            last_upserted_id=chunks[-1].pinecone_id,
            timeout_s=settings.vector_freshness_timeout_s,
        )
        if not fresh and VECTOR_FRESHNESS_TIMEOUT_FLAG not in flags:
            flags.append(VECTOR_FRESHNESS_TIMEOUT_FLAG)

    # --- Step 7: final status + event ---
    with session_scope() as session:
        application = session.get(Application, state.application_id)
        if application is not None:
            application.vector_status = vector_status
        if vector_status == "indexed":
            session.add(
                Event(
                    application_id=state.application_id,
                    actor="system",
                    action="intake_vectors_indexed",
                    payload={"namespace": resumes_ns, "chunk_count": len(chunks)},
                )
            )
        session.commit()

    return {
        "chunks": chunks,
        "chunk_vectors": chunk_vectors,
        "summary_vector": summary_vector,
        "vector_status": vector_status,
        "flags": flags,
    }
