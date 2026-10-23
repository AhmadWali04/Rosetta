"""M0 seed script (PRD §17 M0, PRD §6/F1.1, §8.2, §14).

Loads `data/seed/job.json` and `data/taxonomy/skills.json`, writes the seed
`Job` + `JdRequirement` + `SkillTaxonomy` rows to Postgres (the source of
truth per agents.md invariant 7), commits, then embeds and upserts the same
records into the Pinecone dense + sparse indexes under the namespaces from
`app/rag/namespaces.py`.

Invocation (see Makefile's `make seed` target):

    cd apps/api && uv run python -m scripts.seed

(equivalently `python -m scripts.seed` from `apps/api/` inside an
environment that already has the project's dependencies installed — `uv
run` just guarantees that). Requires `scripts/__init__.py` to exist (it
does) so `scripts` is an importable package and `app/` resolves on
`sys.path` via the current working directory.

Idempotent: re-running always deletes-then-reinserts the seed `Job` (fixed
id `job-ai-intern-procogia`), its `JdRequirement` rows, and the *entire*
`SkillTaxonomy` table (the whole table is seed-only content in M0), and
re-upserts vectors under deterministic record ids — so Pinecone upsert
overwrites in place instead of accumulating orphans. Safe to run repeatedly
against a dev DB and `VECTOR_BACKEND=memory`/`pinecone-local`/`pinecone`.

Contract note: `VectorRecord` (app/rag/vector_store/base.py) requires a
record to populate exactly one representation — dense `values` (with
`sparse_indices`/`sparse_values` left `None`), or the sparse pair (with
`values=[]`) — never both. This script follows that convention explicitly.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from sqlalchemy import create_engine, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import JdRequirement, Job, SkillTaxonomy
from app.rag import namespaces
from app.rag.embeddings import get_embedder
from app.rag.vector_store import VectorRecord, get_vector_store

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
JOB_PATH = REPO_ROOT / "data" / "seed" / "job.json"
TAXONOMY_PATH = REPO_ROOT / "data" / "taxonomy" / "skills.json"

# Fixed, deterministic id so reseeding is safe (never a random UUID).
JOB_ID = "job-ai-intern-procogia"

# Conservative batch size for *embedding* calls (independent of the vector
# store's own upsert batching, which the store handles internally per
# AGENTS.md "Pinecone rules" — we just pass it the full record list).
EMBED_BATCH_SIZE = 64


def _slug(text: str) -> str:
    """Deterministic, filesystem/Pinecone-id-safe slug for a skill name."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "skill"


def _chunks(seq: list, n: int) -> list[list]:
    return [seq[i : i + n] for i in range(0, len(seq), n)]


# ---------------------------------------------------------------------------
# Postgres phase
# ---------------------------------------------------------------------------


def _seed_postgres(
    settings,
) -> tuple[list[JdRequirement], list[SkillTaxonomy]]:
    job_data = json.loads(JOB_PATH.read_text())
    skills_data = json.loads(TAXONOMY_PATH.read_text())

    engine = create_engine(settings.database_url, future=True)

    # expire_on_commit=False: we read attributes off these ORM objects after
    # commit (to build embedding/vector-upsert inputs below), so they must
    # stay populated rather than expiring and needing a live session.
    with Session(engine, expire_on_commit=False) as session:
        try:
            # Idempotent reseed: wipe the seed job's own rows and the whole
            # (seed-only) taxonomy table before reinserting.
            session.execute(delete(JdRequirement).where(JdRequirement.job_id == JOB_ID))
            session.execute(delete(Job).where(Job.id == JOB_ID))
            session.execute(delete(SkillTaxonomy))

            session.add(
                Job(
                    id=JOB_ID,
                    title=job_data["title"],
                    raw_jd=job_data["raw_description"],
                    requirements=job_data["requirements"],
                )
            )

            requirements: list[JdRequirement] = []
            for idx, r in enumerate(job_data["requirements"]):
                req_id = f"{JOB_ID}-req-{idx:02d}"
                req = JdRequirement(
                    id=req_id,
                    job_id=JOB_ID,
                    text=r["text"],
                    kind=r["kind"],
                    weight=r["weight"],
                    pinecone_id=namespaces.requirement_record_id(req_id),
                )
                session.add(req)
                requirements.append(req)

            skills: list[SkillTaxonomy] = []
            seen_slugs: dict[str, int] = {}
            for entry in skills_data:
                slug = _slug(entry["canonical"])
                seen_slugs[slug] = seen_slugs.get(slug, 0) + 1
                if seen_slugs[slug] > 1:
                    slug = f"{slug}-{seen_slugs[slug]}"
                skill = SkillTaxonomy(
                    id=slug,
                    canonical=entry["canonical"],
                    alt_labels=entry.get("alt_labels", []),
                    description=entry.get("description", ""),
                    source=entry["source"],
                    pinecone_id=namespaces.skill_record_id(slug),
                )
                session.add(skill)
                skills.append(skill)

            # Postgres commits first (agents.md invariant 7) — Pinecone
            # upsert only happens after this succeeds.
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise RuntimeError(
                "Seed failed on an integrity error — if this is a FK "
                f"violation on jobs.id='{JOB_ID}', an Application probably "
                "still references this seed job; delete/reassign it before "
                "reseeding. Original error: " + repr(exc)
            ) from exc

    print(
        f"[seed] Postgres: job '{JOB_ID}' ({job_data['title']!r}), "
        f"{len(requirements)} requirements, {len(skills)} taxonomy skills committed."
    )
    return requirements, skills


# ---------------------------------------------------------------------------
# Pinecone phase
# ---------------------------------------------------------------------------


async def _embed_dense(embedder, texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for batch in _chunks(texts, EMBED_BATCH_SIZE):
        out.extend(await embedder.embed_dense(batch))
    return out


async def _embed_sparse(embedder, texts: list[str]) -> list:
    out = []
    for batch in _chunks(texts, EMBED_BATCH_SIZE):
        out.extend(await embedder.embed_sparse(batch))
    return out


async def _upsert_vectors(
    settings, requirements: list[JdRequirement], skills: list[SkillTaxonomy]
) -> None:
    embedder = get_embedder()

    req_texts = [r.text for r in requirements]
    tax_texts = [
        f"{s.canonical}: {s.description}" if s.description else s.canonical for s in skills
    ]

    req_dense, req_sparse = await asyncio.gather(
        _embed_dense(embedder, req_texts), _embed_sparse(embedder, req_texts)
    )
    tax_dense, tax_sparse = await asyncio.gather(
        _embed_dense(embedder, tax_texts), _embed_sparse(embedder, tax_texts)
    )

    jd_ns = namespaces.jd_namespace(settings.pinecone_env, JOB_ID)
    tax_ns = namespaces.taxonomy_namespace(settings.pinecone_env)

    req_dense_records = [
        VectorRecord(
            id=req.pinecone_id,
            values=vec,
            metadata={
                "job_id": JOB_ID,
                "requirement_id": req.id,
                "kind": req.kind,
                "weight": req.weight,
                "text": req.text,
                "embed_model": settings.embedding_model,
                "schema_version": 1,
            },
        )
        for req, vec in zip(requirements, req_dense, strict=True)
    ]
    req_sparse_records = [
        VectorRecord(
            id=req.pinecone_id,
            values=[],
            sparse_indices=sv.indices,
            sparse_values=sv.values,
            metadata={
                "job_id": JOB_ID,
                "requirement_id": req.id,
                "kind": req.kind,
                "weight": req.weight,
                "text": req.text,
                "embed_model": settings.sparse_model,
                "schema_version": 1,
            },
        )
        for req, sv in zip(requirements, req_sparse, strict=True)
    ]
    tax_dense_records = [
        VectorRecord(
            id=skill.pinecone_id,
            values=vec,
            metadata={
                "taxonomy_id": skill.id,
                "canonical": skill.canonical,
                "source": skill.source,
                "text": tax_texts[i],
                "embed_model": settings.embedding_model,
                "schema_version": 1,
            },
        )
        for i, (skill, vec) in enumerate(zip(skills, tax_dense, strict=True))
    ]
    tax_sparse_records = [
        VectorRecord(
            id=skill.pinecone_id,
            values=[],
            sparse_indices=sv.indices,
            sparse_values=sv.values,
            metadata={
                "taxonomy_id": skill.id,
                "canonical": skill.canonical,
                "source": skill.source,
                "text": tax_texts[i],
                "embed_model": settings.sparse_model,
                "schema_version": 1,
            },
        )
        for i, (skill, sv) in enumerate(zip(skills, tax_sparse, strict=True))
    ]

    dense_store = get_vector_store("dense")
    sparse_store = get_vector_store("sparse")

    # Full lists passed through; the store implementation batches internally
    # at <= settings.pinecone_upsert_batch_size (AGENTS.md "Pinecone rules").
    await dense_store.upsert(jd_ns, req_dense_records)
    await sparse_store.upsert(jd_ns, req_sparse_records)
    await dense_store.upsert(tax_ns, tax_dense_records)
    await sparse_store.upsert(tax_ns, tax_sparse_records)

    print(
        f"[seed] Pinecone (VECTOR_BACKEND={settings.vector_backend}): "
        f"upserted {len(req_dense_records)} requirement vectors into dense+sparse "
        f"namespace '{jd_ns}', and {len(tax_dense_records)} taxonomy vectors into "
        f"dense+sparse namespace '{tax_ns}'."
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


async def main() -> None:
    settings = get_settings()

    requirements, skills = _seed_postgres(settings)

    if settings.vector_backend == "pinecone" and not settings.pinecone_api_key:
        print(
            "[seed] VECTOR_BACKEND=pinecone but PINECONE_API_KEY is not set — "
            "skipping the vector upsert phase. Postgres seed is complete and "
            "re-running is safe once a key (or VECTOR_BACKEND=memory / "
            "pinecone-local) is configured."
        )
        return

    try:
        await _upsert_vectors(settings, requirements, skills)
    except Exception as exc:
        # Postgres is already committed and correct (source of truth). Make
        # the vector-layer failure loud rather than silently swallowing it —
        # `applications`/taxonomy rows exist but search won't find them until
        # `make reindex` is re-run.
        print(
            f"[seed] Vector upsert FAILED against backend "
            f"'{settings.vector_backend}': {exc!r}. Postgres rows are intact; "
            "re-run `make seed` (or `make reindex`) once the vector backend "
            "is reachable."
        )
        raise


if __name__ == "__main__":
    asyncio.run(main())
