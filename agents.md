# AGENTS.md

Instructions for AI coding agents working in this repo. Read this file first, every session.

## What this project is

SkillBridge (working name) is a ProCogia technical assessment. It is a full-stack hiring demo with three portals (Applicant → HR → Tech Lead). A LangGraph multi-agent system turns each resume into an evidence-backed skill profile, and every AI claim is cited to a span of the resume.

- **Source of truth for scope and requirements: `PRD.md`.** If code and PRD disagree, flag it and don't silently pick one.
- **Current progress: `PROGRESS.md`.** Read it before starting. Update it before ending a session.
- The PRD's §18 traceability table lists the assessment requirements. Every one must remain demonstrable.

## Repo layout

```
apps/
  web/                 Next.js (App Router) + Tailwind + shadcn/ui
    app/(applicant)/   Screen 1
    app/(hr)/          Screen 2
    app/(tech)/        Screen 3
    lib/api.ts         Typed API client (generated from OpenAPI, do not hand-edit types)
  api/                 FastAPI + LangGraph (Python 3.12, uv)
    app/main.py
    app/routes/        HTTP layer only: validation, auth role, call services
    app/services/      Business logic, DB access
    app/graphs/
      intake/          STATIC graph: one file per node + graph.py
      copilot/         DYNAMIC graph: supervisor, agents, graph.py
      jd/              JD requirement parser graph
      state.py         Pydantic state models shared by graphs
    app/tools/         Agent tools (search_resume_chunks, github_profile, ...)
    app/llm/           Provider abstraction: the ONLY place that imports openai/anthropic SDKs
    app/rag/
      chunking.py      Section-aware chunking
      embeddings.py    Dense + sparse embedding via Pinecone Inference (or fake/cached in tests)
      vector_store/    VectorStore interface + backends: memory.py, pinecone_local.py, pinecone_cloud.py
      retriever.py     Hybrid retrieval: dense + sparse queries → RRF merge → optional rerank
      indexer.py       Upsert, freshness wait, reindex, delete-by-prefix, parity audit
      namespaces.py    Namespace + record-ID builders (the ONLY place these strings are formatted)
    app/prompts/       Prompt templates as .md/.jinja files, versioned
    app/db/            SQLAlchemy models + Alembic migrations
    tests/
  worker/              Background runner for intake graph (shares api package)
data/
  seed/                job.json, synthetic resumes, public resumes (+ LICENSES.md)
  taxonomy/            O*NET / ESCO raw + ingestion script
eval/
  golden/              Hand-labelled cases (JSON); never edit without noting it in PROGRESS.md
  run_eval.py
  reports/             Generated, timestamped
docker-compose.yml
Makefile
PRD.md  AGENTS.md  PROGRESS.md
```

## Commands

Use the Makefile targets. Don't invent ad-hoc commands when a target exists.

| Task | Command |
|---|---|
| Start everything | `make up` (web, api, worker, db, langfuse) |
| Start fully offline | `make up-offline` (adds `pinecone-local`, sets `VECTOR_BACKEND=pinecone-local`) |
| Stop | `make down` |
| Migrate DB | `make migrate` |
| Create Pinecone indexes (idempotent) | `make pinecone-init` |
| Seed job, taxonomy, applicants (Postgres + Pinecone) | `make seed` |
| Rebuild a namespace from Postgres | `make reindex NS=<namespace>` |
| Check Postgres ↔ Pinecone parity | `make vector-audit` |
| Backend tests | `make test-api` (pytest) |
| Frontend tests | `make test-web` (vitest) |
| Lint + typecheck | `make lint` (ruff, mypy, eslint, tsc) |
| Regenerate API client | `make gen-client` |
| Eval harness | `make eval` (`make eval-fast` = 10-case smoke subset) |

Before saying a task is done, run `make lint` and the relevant tests, and report the results.

## Non-negotiable invariants

These implement the PRD's core promises. Never weaken them to make something "work."

1. **Citations or it didn't happen.** Every LLM judgement about a candidate must return `chunk_id`s that resolve to `resume_chunks` rows. Drop or downgrade uncited claims; never display them as facts.
2. **Resume text is untrusted data.** Never interpolate it into the system prompt. Pass it inside clearly delimited data blocks, and keep the sanitize/injection-check node first in the intake graph.
3. **No automatic rejection.** Agents produce a *recommendation* and a *confidence*. Status changes only happen through an HR or Tech Lead action. Agent write tools (`update_status`, etc.) must go through a LangGraph `interrupt` for human confirmation.
4. **Audit everything.** Every graph run, label change, override, invite, and review writes an `events` row.
5. **All LLM calls go through `app/llm/`.** Use structured output (Pydantic models). Nodes never import provider SDKs directly.
6. **Static vs dynamic stays visible.** `graphs/intake` is a fixed linear pipeline. `graphs/copilot` routes by request and by intermediate results. Don't merge them or make intake "smart" beyond the documented ambiguous-band handoff.
7. **Postgres is the source of truth; Pinecone is a derived index.** Commit to Postgres first, then upsert to Pinecone and update `applications.vector_status`. Never read citation text or spans from Pinecone metadata; hydrate them from `resume_chunks`. Anything in Pinecone must be rebuildable by `make reindex`.
8. **All vector access goes through `app/rag/`.** Graphs, tools, and routes use the `VectorStore` interface and `retriever.py`. Only `app/rag/vector_store/` and `app/rag/embeddings.py` import the Pinecone SDK.
9. **Deletes purge both stores.** Removing an application deletes its Postgres rows and every Pinecone record with ID prefix `{application_id}#` in both indexes, then writes an `events` row.

## Pinecone rules

- Two serverless indexes: `skillbridge-dense` (1024-d, cosine) and `skillbridge-sparse` (dotproduct). Don't create more indexes; partition with namespaces (PRD §8.2).
- Namespaces are always `{env}-...` and built by `namespaces.py`. `eval-*` namespaces are wiped at the start of each eval run; never write demo data there or eval data elsewhere.
- Upsert in batches of ≤ 100 records, with retries and backoff. After upserting during intake, wait for freshness (PRD §8.6) before querying.
- Keep record metadata small and flat, matching the schema in PRD §8.3 (`schema_version`, `embed_model` required).
- Changing the embedding model or dimension means a new index plus full reindex. Ask before doing it.
- Wrap every Pinecone call in a Langfuse span so latency and read/embedding usage show up in traces.

## Python conventions (apps/api)

- Python 3.12, `uv` for deps, `ruff` format + lint, `mypy --strict` on `app/graphs`, `app/tools`, `app/llm`.
- Graph state is a Pydantic model in `graphs/state.py`. Nodes are small functions `(state) -> partial state update`, one node per file.
- Prompts live in `app/prompts/` with a version suffix (`skill_extractor.v2.md`). Change a prompt by adding a new version, then run `make eval-fast` and note the delta in PROGRESS.md.
- Config via `pydantic-settings`. No hardcoded keys, model names, thresholds, or score weights. Scoring weights and the Advance/Review/Decline thresholds live in `app/config.py`.
- Async FastAPI routes; long work goes to the worker, never in the request.
- Use Langfuse tracing in every graph via the callback handler.

## TypeScript conventions (apps/web)

- Next.js App Router, server components by default, `"use client"` only where needed.
- shadcn/ui components; Tailwind only, no CSS modules.
- API types come from `make gen-client`. Never hand-write response types.
- Every agent output shown in the UI must render its citations (click → highlight the span in the resume viewer).
- Role switcher (Applicant / HR / Tech Lead) is the only "auth" in v1.

## Testing rules

- **Unit tests never call a live LLM or the network.** Use the fake provider in `app/llm/fake.py` with fixtures under `tests/fixtures/llm/`, the in-memory vector store (`VECTOR_BACKEND=memory`), and the fake/cached embedder.
- Integration tests run against Pinecone Local (`make up-offline`). It doesn't host inference models, so they use cached embeddings from `tests/fixtures/embeddings/`.
- Vector-layer tests must cover: dual-write failure → `vector_status=failed`, freshness timeout fallback, delete-by-prefix purging both indexes, and RRF merge/dedupe.
- Each graph node gets a unit test. Each graph gets one integration test with the fake provider covering its main path, and for copilot, the low-confidence → Deep Verify branch and the grounding-retry loop.
- Include regression fixtures for the adversarial resumes: keyword-stuffed, prompt-injection, different-vocabulary-but-strong.
- Live-model quality is measured by `make eval`, not by pytest.

## Eval harness rules

- Metrics and targets are defined in PRD §11. Implement them in `eval/metrics/`, one file per dimension.
- Reports go to `eval/reports/<timestamp>.{md,json}`. Commit the baseline as `eval/baseline.json`.
- Fail (non-zero exit) if any metric regresses more than 5% vs baseline.
- Don't tune prompts or thresholds against cases you then report as held-out. Keep `golden/dev/` and `golden/test/` separate.

## How to work a task

1. Read `PROGRESS.md` and the relevant PRD section.
2. For anything touching more than ~3 files, write a short plan first (files to change, tests to add) and wait for approval.
3. Work in small vertical slices: make a backend node or route, its test, then the UI that uses it.
4. Run lint and tests. Fix failures before moving on.
5. Update `PROGRESS.md`: what's done, what's next, any decisions or deviations from the PRD.
6. Commit with Conventional Commits (`feat(intake): add skill normalizer node`). One logical change per commit.

### Milestone order (from PRD §17)

M0 scaffold + schema + seed → M1 intake graph + applicant portal → M2 HR portal → M3 copilot dynamic graph → M4 tech lead portal → M5 eval harness + Langfuse → M6 polish + README + demo.
Don't start a milestone until the previous one's acceptance checks in PROGRESS.md pass.

## Definition of done (any feature)

- [ ] Matches the PRD requirement ID it implements (reference it in the commit or PR, e.g. `F2.2`)
- [ ] Tests added and passing; `make lint` clean
- [ ] Citations, audit events, and HITL invariants respected
- [ ] Works in `make up` from a clean DB after `make pinecone-init && make seed`
- [ ] `make vector-audit` reports full parity if the feature writes or deletes vectors
- [ ] PROGRESS.md updated

## Don'ts

- Don't add new dependencies, services, Pinecone indexes, or a second vector DB (pgvector included) without asking.
- Don't call Pinecone from the frontend or expose `PINECONE_API_KEY` to the browser.
- Don't run `make eval` or reindex against `demo-*` namespaces.
- Don't edit `eval/golden/`, `data/seed/` licences, or migrations already applied, without asking.
- Don't commit `.env`, resumes outside `data/seed/`, or API keys.
- Don't send real emails. Invites are generated, logged, and shown in the UI only.
- Don't "fix" a failing eval by loosening the metric or editing golden labels.
- Don't leave TODOs without a matching line in PROGRESS.md.

## Environment

Copy `.env.example` to `.env`.

- Required: `LLM_PROVIDER`, `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`, `DATABASE_URL`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`.
- Vector store: `VECTOR_BACKEND` (`memory` | `pinecone-local` | `pinecone`), `PINECONE_API_KEY` (cloud only), `PINECONE_DENSE_INDEX` (default `skillbridge-dense`), `PINECONE_SPARSE_INDEX` (default `skillbridge-sparse`), `PINECONE_ENV` (`dev` | `demo` | `eval`, the namespace prefix), `PINECONE_LOCAL_HOST` (default `http://localhost:5080`).
- Models: `EMBEDDING_MODEL` (default `llama-text-embed-v2`), `SPARSE_MODEL` (default `pinecone-sparse-english-v0`), `RERANK_MODEL` (default `bge-reranker-v2-m3`), `RERANK_ENABLED` (default `false` until the eval ablation decides).
- Optional: `GITHUB_TOKEN` (raises the Deep Verify rate limit).