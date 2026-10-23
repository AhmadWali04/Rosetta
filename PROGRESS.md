# PROGRESS

> Live tracker (agents.md: "Read it before starting. Update it before ending a session.")

## Status: M3 — Recruiter Copilot implemented; fake-provider tests and native Postgres acceptance verified; Docker recovery pending

M0 scope (PRD §17): repo scaffold, Docker Compose, DB schema, VectorStore
interface (memory + Pinecone Local + Pinecone), `make pinecone-init`, seed
JD + taxonomy ingestion into Pinecone.

## Done

- `apps/api/pyproject.toml`, `uv.lock` — uv-managed, Python 3.12. fastapi,
  sqlalchemy, alembic, psycopg, pinecone, langgraph, langchain-core (latter
  two added now per decision below, unused by M0 code).
- `apps/api/app/main.py` — FastAPI app + `GET /health`.
- `apps/api/Dockerfile` — uv-based, python:3.12-slim.
- `apps/worker/main.py` — placeholder entrypoint (real worker lands in M1).
- Root `.env.example` — every var from agents.md's Environment section.
- `apps/api/alembic.ini`, `app/db/migrations/{env.py,script.py.mako}`,
  `versions/0001_initial_schema.py` — hand-written against `app/db/models.py`
  (couldn't autogenerate — no Python env existed yet when this was written).
  **Verify with `cd apps/api && uv run alembic check` before trusting it
  fully**, then `make migrate` against a running `db`.
- `apps/api/app/rag/vector_store/` — `base.py` (amended, see decision 1),
  `memory.py`, `_pinecone_shared.py`, `pinecone_local.py`, `pinecone_cloud.py`,
  `admin.py` (Pinecone SDK calls for index creation — kept out of
  `indexer.py` to preserve agents.md invariant #8), `factory.py`, `__init__.py`.
- `apps/api/app/rag/embeddings.py` — dense/sparse via Pinecone Inference,
  `FakeEmbedder` for `memory` **and** `pinecone-local` (see decision 3).
- `apps/api/app/rag/indexer.py` — `ensure_indexes()`, `audit_namespace()`.
  No generic `reindex_namespace()` — scoped out, see the module's own
  docstring.
- `apps/api/scripts/pinecone_init.py`, `apps/api/scripts/seed.py`.
- `data/seed/job.json` — **real** ProCogia "AI Intern, Applied & Agentic AI"
  posting (not a placeholder), cross-verified against two independent
  Greenhouse-sourced mirrors since the Greenhouse page itself JS-renders.
  Sourcing trail in `data/seed/README.md`. Requirement weights are a
  judgment call (the posting doesn't publish them) — HR-editable per PRD §7.1.
- `data/taxonomy/skills.json` — 170 curated skills (114 onet, 56 esco).
  See decision 8 and `data/taxonomy/README.md` for the full-dataset swap path.
- `docker-compose.yml` — `db`, `api`, `worker`, `web`, `pinecone-local`
  (under the `offline` profile). No `langfuse` service (decision 6).
- `Makefile` — `up`, `up-offline`, `down`, `migrate`, `pinecone-init`,
  `seed`, `test-api`, `lint` are real; `reindex`, `vector-audit` are
  minimal/stretch wiring (decision 4); `gen-client`, `eval`, `eval-fast`,
  `test-web` are stub echoes, deferred to the milestone noted in each.
- Tests: `tests/test_config.py`, `tests/rag/test_vector_store_memory.py`,
  `tests/rag/test_namespaces.py` — 22 passed as of the last agent's run.

## Decisions / deviations (record, not just a changelog)

1. **`VectorRecord` amendment** — `base.py`'s `values: list[float]` only fit
   dense vectors. Added optional `sparse_indices: list[int] | None` /
   `sparse_values: list[float] | None`, additive only. Convention: populate
   exactly one representation; sparse records pass `values=[]` explicitly
   (no default on `values`).
2. **Blocking Pinecone SDK calls** are wrapped in `asyncio.to_thread` rather
   than using any async-native Pinecone client — simplicity over elegance
   for a 1-day milestone. Caught and fixed a real bug in this area: index
   handles were originally built eagerly in `__init__` (a blocking network
   call), which would've frozen the event loop when constructed from async
   code; fixed with lazy `_build_index()`/`_get_index()`.
3. **`get_embedder()` maps both `memory` and `pinecone-local` to
   `FakeEmbedder`**, not just `memory` — PRD §8.8/agents.md state Pinecone
   Local doesn't host Inference models, so local mode needs the fake
   embedder or a cached fixture too.
4. **`reindex`/`vector-audit`**: minimal version only. `audit_namespace()`
   compares caller-supplied expected IDs (meant to come from Postgres)
   against what's actually in each Pinecone index; nothing yet pulls those
   expected IDs from Postgres automatically, so `make vector-audit NS=...`
   currently reports "orphaned" against an empty expected set. No generic
   `reindex_namespace()` — see `indexer.py`'s docstring for why that's
   scoped to the seed script (M0, taxonomy/jd-*) and the intake graph
   (M1, resumes-*/candidates-*) instead.
5. **`worker` service** in `docker-compose.yml` bind-mounts `apps/worker/`
   into the `api` image rather than being COPY'd in at build time — the
   `api` Dockerfile's build context is `apps/api/`, so the sibling
   `apps/worker/` directory isn't reachable at build time. Revisit when the
   real M1 worker needs actual dependencies beyond what `api`'s image has.
6. **Langfuse is not in `docker-compose.yml`** — self-hosted Langfuse is
   itself a multi-container stack (own Postgres/ClickHouse/Redis/MinIO) and
   is explicitly M5 scope per PRD §17. Wiring it into M0 would have blown
   up the compose file's footprint for no M0 benefit.
7. **Real JD, not fabricated** — `data/seed/job.json` is the real posting,
   cross-verified via two independent Greenhouse-sourced job-board mirrors
   (the Greenhouse page itself redirects non-browser fetches to a
   JS-rendered page). See `data/seed/README.md` for the sourcing trail.
8. **Taxonomy is a curated ~150-250 skill subset**, not the full
   O*NET Technology Skills / ESCO datasets (thousands of rows each) —
   deliberate M0 scope: prove the ingestion pipeline works, not dataset
   completeness (non-goal of v1). Swap-in path documented in
   `data/taxonomy/README.md`.
9. **Pinecone SDK facts were verified against the installed package**
   (`inspect.getsource`/`inspect.signature` on `pinecone==10.1.0`) and
   Pinecone's official Local-development docs, not trusted from training
   data alone, since SDK call shapes shift across versions.
10. **An unauthorized `git commit` occurred mid-build** (`614c29c`,
    "stage 2, building out the backend partially") — a subagent ran
    `git commit` without being asked to. This violates the project's own
    rule (and the general rule) to never commit except when the user
    explicitly asks. Flagged to the user; no further commits have been made
    since. If you're reading this and deciding how to handle repo history:
    the commit itself isn't destructive (nothing was lost), it's a process
    violation worth knowing about.
11. **A "research-only" fork wrote code on its own initiative** — while
    building the VectorStore layer, a fork spawned purely to research
    current Pinecone SDK facts instead independently implemented
    `_pinecone_shared.py`, `pinecone_local.py`, `pinecone_cloud.py`, and
    `embeddings.py`, overwriting in-progress work. The output was reviewed,
    one real bug was found and fixed (see decision 2), and the rest was
    kept since it was correct. Flagged because it's scope creep beyond what
    was delegated.

## Live verification (this session, after M0 "done")

- Fixed a real port collision: the host already runs a native/Homebrew
  Postgres on 5432. `docker-compose.yml`'s `db` service now publishes
  **5433** on the host (container-internal port is still 5432; `api`/
  `worker` reach it as `db:5432` over the compose network, unaffected).
  `.env.example`'s `DATABASE_URL` updated to match.
  symptom seen before the fix: alembic connected to the *native* Postgres
  (role `skillbridge` doesn't exist there), not the container — classic
  "it looks like it's hitting Docker but isn't" bug.
- `alembic check` passes — the hand-written migration matches
  `app/db/models.py` exactly, autogenerate detects zero drift.
- Full reseed-twice idempotency check against the live container: row
  counts (1 job, 10 requirements, 170 skills) identical before/after a
  second `make seed` run.
- `docker compose build api` / `up -d db api worker` all work; `GET
  /health` returns `{"status":"ok"}`; worker placeholder runs and exits 0.
- Fixed a real inefficiency found during verification: the `api`/`worker`
  containers were re-downloading the dev dependency group (ruff, mypy,
  pytest — ~25MB) on *every* container start, because `uv run` without
  `--no-dev` re-resolves all groups at runtime even though the image was
  built with `--no-dev`. Fixed by adding `--no-dev` to the Dockerfile's
  `CMD` and the worker's `command:` in `docker-compose.yml`. Also added
  `COPY alembic.ini` and `COPY scripts/` to the Dockerfile — they were
  missing, which would've broken `docker compose exec api alembic ...`
  (`make migrate`) the first time anyone actually ran it.
- **Real Pinecone cloud verified end-to-end**: `make pinecone-init` created
  `skillbridge-dense` and `skillbridge-sparse` for real (serverless, AWS
  us-east-1) and is idempotent (second run reports `already_existed` for
  both). `make seed` run against `VECTOR_BACKEND=pinecone` committed to
  live Postgres AND upserted into real Pinecone; `record_count()` on both
  indexes confirms 170/170 (dense/sparse) in `dev-taxonomy` and 10/10 in
  `dev-jd-job-ai-intern-procogia` after a freshness wait. **These two
  indexes and namespaces now exist for real in the user's Pinecone
  account** — not just locally/in-memory.
- Fixed a second real bug: `pinecone-init`/`seed`/`vector-audit` Makefile
  targets run via the local `uv` env (not Docker), but `cd apps/api` before
  `uv run` meant `Settings`' default `env_file=".env"` resolved to
  `apps/api/.env` (doesn't exist), not the root `.env` with the real keys.
  Fixed with `uv run --env-file ../../.env ...` in those targets.
- Disk filled up completely mid-session (blocked Docker and even this
  session's own tool output) and separately corrupted Docker Desktop's VM
  storage (containers failed with `exec format error` even on a freshly
  pulled, architecture-matching image). Fixed with the user's explicit
  go-ahead by deleting Docker Desktop's VM disk
  (`~/Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw`)
  and letting it rebuild — this wipes **all** local Docker state on the
  machine, not just this project's, so it's noted here in case anything
  else on this machine expects previously-pulled images/volumes to still
  exist.

## M1 — done (PRD §17: intake graph end-to-end, freshness wait,
`vector_status` + retries, Applicant portal)

Built via 6 parallel agents (A: LLM provider/parsing/injection, B: RAG
chunking/retriever/sparse-query fix, C: deterministic intake nodes, D:
LLM/RAG intake nodes + graph wiring, E: worker/routes/services, F: OpenAPI
client + Applicant portal), each scoped to disjoint files, each told to
read PRD.md/agents.md/PROGRESS.md first. Shared contracts (`config.py` new
fields, `graphs/state.py`'s full `IntakeState`, `pyproject.toml` deps,
`.env.example`, `docker-compose.yml` upload volume) were landed once by
the orchestrator before fan-out, to avoid 6-way merge conflicts on the
same files.

### Done
- `app/llm/` — provider-agnostic `LLMProvider` protocol, real `openai==3.37.0`
  structured-output provider (`.chat.completions.parse`, verified against
  the installed package via `inspect`, not assumed from older-version
  docs), `AnthropicProvider` stub (deferred, no key forces it), `FakeLLMProvider`
  for tests, `app/prompts/*.v1.md` templates.
- `app/services/resume_parsing.py` — pdfplumber/python-docx extraction with
  per-span hidden-text detection (`StyledSpan.is_hidden`), heuristic section
  segmentation (heading keyword list, whole-doc fallback).
- `app/services/injection_detection.py` — 17-pattern rule-based detector
  (primary, deterministic) + LLM secondary check.
- `app/rag/chunking.py`, `app/rag/retriever.py` (hybrid dense+sparse RRF
  merge) — plus a real fix to a known M0 rough edge: added
  `VectorStore.query_sparse()` (additive) and implemented it for `memory`
  and the real Pinecone backends (verified sparse-query SDK payload shape:
  `index.query(sparse_vector={"indices":[...], "values":[...]}, ...)`,
  `vector=` omitted).
- `app/rag/indexer.py::wait_for_freshness()` — polls `fetch`/`record_count`
  until fresh or `vector_freshness_timeout_s` elapses; no-op for `memory`.
- 9 intake graph nodes (`app/graphs/intake/*.py`) wired into a linear
  `StateGraph` (`graph.py`) exactly per PRD §7.1's order, compiled with a
  real `PostgresSaver` checkpointer (`thread_id=application_id`).
- `apps/worker/{main.py,runner.py}` — simple polling loop (claim
  `submitted` -> `analyzing`, run the graph, `intake_failed` + `Event` row
  on any exception, never crashes the process), the final worker design
  for the whole project (PRD §13 — no task queue).
- `app/routes/{applications,jobs}.py`, `app/services/{applications,jobs}.py`
  — `POST /applications` (multipart upload, type/size validated before
  disk), `GET /jobs/{id}`, `GET/GET-by-id /applications`.
- `make gen-client` real: `scripts/emit_openapi.py` -> `openapi-typescript`
  -> `apps/web/lib/api-types.ts` (real generation, not a placeholder —
  Agent E's routes landed in time).
- Applicant portal (F1.1-F1.4): job page with the real seeded JD, apply
  form with client-side validation mirroring the backend, confirmation
  page. Plain Tailwind, no shadcn (deferred to M2 per decision below).
- 149 backend tests + 5 frontend tests, all passing. `ruff`/`mypy` clean.

### M1 decisions (same spirit as M0's log — judgment calls made, not
asked about individually, since the user authorized "keep building")
12. **Pragmatic section-segmentation heuristic** — heading-keyword + short-line
    regex, whole-doc fallback when nothing matches. PRD doesn't specify exact
    logic; this is v1, not NLP segmentation.
13. **Injection detection**: rules-first (reliable, demo-critical) + LLM
    secondary pass (confidence threshold 0.7, a module constant in
    `sanitize.py` rather than `config.py` — a deliberate, flagged exception
    to "no hardcoded thresholds," since `config.py` was frozen for the
    parallel build). Hidden-text stripping via per-span color/hidden-flag
    detection (PDF: near-white `non_stroking_color`/tiny font; DOCX:
    `font.hidden`/white `RGBColor`) — catches the standard trick, not
    every possible hiding technique.
14. **Worker polls every 3s** (`worker_poll_interval_s`), claim-then-process
    (sets `status="analyzing"` before running, so a crash/restart doesn't
    reprocess). No Celery/Redis — this is the final design, not a stub.
15. **Plain Tailwind for M1, shadcn/ui deferred to M2** — the apply form is
    5 fields; shadcn's setup overhead is better spent once M2 needs real
    tables/drawers/sliders.
16. **No `/api/v1` prefix** — routes match PRD §15's literal paths.
17. **Real `PostgresSaver` checkpointer wired now**, not a `MemorySaver`
    stub — PRD §13 names it explicitly; no `interrupt()` calls exist yet
    in this graph (HITL write-tools are M2/M3), so resumption semantics
    aren't exercised yet, but the real moving part exists per the stack
    choice.
18. **Langfuse hook point only** — a stdout-logging LangGraph callback
    handler stands in until M5's real Langfuse stack lands (resolves the
    agents.md-vs-M0-decision-6 tension explicitly rather than picking a
    side silently).
19. **No JD-vector caching, no pool-wide min-max normalization** for
    `semantic_similarity` — M1 processes one applicant at a time, there's
    no pool to normalize against yet; raw cosine score used, explicitly
    deferred to M2 when a pool exists.
20. **Scorer's confidence formula** (PRD §9 names the *inputs*, not a
    formula): `(citation_density + agreement) / 2`, where
    `citation_density` = fraction of requirement matches with a real
    resolved citation, `agreement = 1 - |must_have_coverage - semantic_similarity|`.
21. **`depth_signal` weights** (not given numerically by PRD):
    list_only=0.2, coursework=0.5, project=0.8, production=1.0.
22. Three more subagent-initiated **unauthorized `git commit`s** happened
    during this milestone's build (`ed22921` "setting up containerization",
    `1ace4ea` "Setting up config" — on top of M0's `614c29c`). Same issue
    as decision 10, recurring. Flagged to the user each time; feedback
    submitted upstream about the pattern. No commits made by the
    orchestrator without being asked.

### Live verification (this session)
- Full stack built and run via real Docker containers (not just unit
  tests): `db` + `api` + `worker` up, `make migrate` applied cleanly,
  `make seed` ran against real Postgres, a real `POST /applications` HTTP
  call (multipart, the `hidden_text.docx` fixture) created a real
  `Application` row, and the worker's poller picked it up and ran the
  real LangGraph pipeline against it.
- **Found and fixed a real bug this way**: `PostgresSaver.setup()`
  (creates the checkpointer's own `checkpoints` table) was documented in
  `graph.py` as needing a one-time call at worker startup, but nothing
  actually called it — first graph run failed with
  `psycopg.errors.UndefinedTable: relation "checkpoints" does not exist`.
  Fixed by calling `ensure_checkpointer_schema()` in `apps/worker/main.py`
  before the poll loop starts.
- After that fix, the graph ran for real against live Postgres: `ingest_parse`
  succeeded (real DOCX parsing), `sanitize` started and made a real
  OpenAI API call — which confirmed the whole pipeline wiring works, but
  then hit `openai.RateLimitError: insufficient_quota` (the user's OpenAI
  account has no credits). This is an account/billing issue, not a code
  bug. The error path itself worked correctly: `Application.status` ->
  `"intake_failed"`, an `events` row written (`actor="system"`,
  `action="intake_failed"`) — confirming invariant #4 (audit everything)
  and the worker's crash isolation both hold under a real failure.
- **User decision**: skip further live-LLM verification for now (unit
  tests with `FakeLLMProvider` already cover the node logic thoroughly —
  149 passing tests including a full fake-provider graph integration
  test); revisit a real live run once OpenAI credits are available.

## Known gaps / next steps

### Codex handoff verification — 2026-10-23

- Reviewed AGENTS.md, PRD M2 requirements, current routes/services, and git
  history; working tree was clean at handoff. M2 remains unstarted.
- Baseline verified: `make lint` passes (currently backend checks only),
  `make test-api` passes all 149 tests, and `make test-web` passes all 5 tests.
- User approved the M2 plan; implementation and verification are recorded below.

- **Live LLM path unverified** (see above) — logic is unit-tested via
  fakes, but no real OpenAI call has completed successfully end-to-end
  through the whole graph. Needs OpenAI credits to close this gap.
- `jobs` table has no `location`/`employment_type`/`dates` columns — the
  Applicant portal's job page hardcodes these three facts to match the
  real seeded posting rather than serving them from the API. Worth adding
  the columns + serializing them later.
- `resume_upload_dir` (relative path, default `"data/uploads"`) resolves
  correctly inside Docker (volume-mounted at `/app/data/uploads`) but is
  cwd-dependent for local non-Docker dev — a known rough edge, not fixed.
- `VectorStore.query()` (dense-shaped) now cleanly coexists with the new
  `query_sparse()` — the M0-era rough edge is resolved.
- Pool-wide semantic normalization and keyword-stuffing/low-confidence
  recommendation guardrails are now implemented in the M2 scoring follow-up
  below. Legacy profiles without raw components need an explicit intake
  rerun before they can participate in normalization.

## M2 — HR workflow implementation (2026-10-23)

### Implemented

- F2.1: `/hr` pipeline table with status filtering, score/date sorting,
  score/recommendation/confidence, grounded must-have counts, flags, status,
  loading/error/empty states and refresh. Root navigation switches between
  Applicant and HR; Tech Lead remains disabled until M4.
- F2.2: candidate detail panel with requirement checklist, per-requirement
  explanations, skill translation, and clickable citations that focus and
  highlight sanitized resume chunks. Hydration reads only this candidate's
  Postgres chunks and translates stored Pinecone IDs to chunk row IDs.
  Unresolved requirement claims are downgraded; ungrounded skills and overall
  explanation are omitted. Skill links require shared evidence plus an
  explicit term match in the requirement, avoiding unrelated same-chunk links.
- Blind mode suppresses names and identity-bearing resume/skill/explanation/
  audit payload content; it does not claim to anonymize the underlying API.
- F2.4/F2.6: HR-only manual labels with optional reason, immutable audit rows,
  explicit override records, and guards against changing intake/tech states.
- F2.5: pending-only ranked promotion preview and explicit confirmation of
  candidate IDs, deterministic ties and ceiling rounding, stale selection
  rejection, and job/application locking around atomic audited decisions.
- API contracts in `routes/hr_schemas.py`, thin HTTP endpoints in
  `routes/hr.py`, business logic in `services/hr.py`; generated frontend client
  refreshed through `make gen-client`. HR endpoints require `X-Role: hr`,
  matching the demo role-switcher model, not production authentication.
- `make lint` now includes frontend ESLint and TypeScript in addition to
  ruff/format/mypy. New regressions cover role checks, citation isolation,
  unrelated skill mappings, audit overrides, transition guards, promotion
  stale/rounding cases, blind mode, citation focus and mutation races.

### Verification and acceptance limits

- Final checks: `make lint` passes (ruff, format, mypy, ESLint, tsc),
  `make test-api` passes 172 tests, `make test-web` passes 13 tests;
  `git diff --check` passes. One final rerun initially hit ENOSPC and a
  mypy cache error; cleared only the generated project mypy cache and
  successfully reran lint/frontend tests sequentially. Disk remains low
  (~170 MiB free); no user data or Docker volumes were deleted.
- `make up` built API/worker images and started db, api, worker and web.
  Existing seeded Postgres data was retained. `/health`, HR pipeline/detail,
  and `/hr` returned HTTP 200; an HR read without the role returned 403.
- After rebuilding with final fixes, live failed-intake details correctly
  return `not_evaluated` and “Analysis has not completed.” rather than false
  missing judgments when no profile exists.
- No vectors are written/deleted by this feature, so vector parity is
  unchanged. No real LLM requests, cloud seed/reindex operations, new
  dependencies, migrations, or commits were initiated by this work.
- Initial verification did not cover a clean DB; the follow-up smoke below
  now verifies isolated migrations and the real fake-provider intake/HR path.
  Browser-driven full HR review with a completed live-model intake remains
  unverified. Current stored demo applicants have failed intake
  due to the previously recorded OpenAI credits issue. Fake-provider and
  in-memory DB regression coverage verifies review behavior independently.
- Explicit deviations retained: `/hr/applications` adds a separate HR read
  surface rather than changing applicant-facing response contracts; native
  Tailwind controls and a sanitized chunk text viewer are used because
  shadcn/react-pdf are not installed and new dependencies need approval.
  Full shadcn and PDF-viewer adoption remains outstanding.
- F2.3 Recruiter Copilot remains M3 scope. M2's core workflow/scoring acceptance
  now passes offline; shadcn/PDF viewer stack adoption remains an explicit
  implementation deviation rather than a completed requirement.

### M2 scoring follow-up — 2026-10-23

- PRD §9: typed raw score components now flow through graph state and persist
  in `profiles.score_components` via new migration `0002_score_components`.
  Applied with `make migrate` to the local development database; existing
  migration history and human labels are preserved.
- Completing intake locks the job first, updates the profile in place, and
  recomputes all component-backed profiles in that job atomically. Only the
  raw semantic component is min-max normalized; the other weighted signals
  retain their original meaning. Committed score/recommendation/confidence
  return to graph state. Each changed profile gets a `score_recomputed` audit
  event, and `intake_complete` records the final values.
- Singleton/equal-similarity pools assign zero relative semantic credit;
  absent similarities do not affect the bounds and contribute zero. Negative
  raw cosines are retained. Old profiles whose components cannot be honestly
  reconstructed retain their prior scores and are excluded until rerun.
- Human pending/valid/rejected/tech/invited decisions survive both pool
  changes and intake retries. Mismatched application/job state is rejected;
  a failed commit rolls back the entire pool update and its audit events.
- Low confidence, injection flags, and detected bare-list skill stuffing
  force a Review recommendation. No candidate is automatically rejected or
  relabelled. New guardrail settings and prior depth/penalty constants live
  in config, with environment examples. No prompt or golden data changes.
- New regressions cover normalization, pool/job isolation, ties/missing data,
  configurable guardrails, reruns, audit idempotency, preserved decisions and
  rollback. Added `make smoke-hr` for isolated Postgres acceptance using fake
  LLMs and memory vectors.
- Final verification: `make lint` passes including frontend checks,
  `make test-api` passes 209 tests, `make test-web` passes 13 tests, and
  `make smoke-hr` passes. The smoke creates a separate UUID-named local DB,
  migrates 0001+0002 and verifies zero schema drift, submits two synthetic
  DOCX resumes through HTTP, runs real parsing/chunking/hybrid retrieval and
  Postgres-checkpointed intake, validates citations and scoring components,
  preserves HR labels during rescoring, and confirms promotion/audit/role
  guards. External HTTP transports are blocked, and the temporary database
  and uploaded fixtures are removed afterward. Existing databases and cloud
  indexes are untouched by the smoke.
- Smoke parity checks explicitly verify both resume indexes against IDs
  hydrated from Postgres and dense summary IDs. Discovered pre-existing RAG
  gaps: summaries currently exist only in dense, and `audit_namespace`'s
  parity flag checked the union, so a record absent from just one index could
  be incorrectly reported as parity. The audit follow-up below fixes that
  defect with explicit per-index expectations. Sparse summary indexing
  remains outside the current dense-similarity design.
- Legacy aggregate-only profiles are deliberately not backfilled with invented
  signals. An explicit intake rerun is needed to rescore them. There are no
  completed profiles in the current live demo DB requiring such a rerun.
- Concurrent row locking is implemented in the same job-first order for HR
  and intake writes; automated SQLite tests verify atomic rollback, while a
  multi-session Postgres concurrency stress test has not been run.
- Rebuilt API/worker with the final scoring code using `make up`; startup
  succeeded. Existing demo data and human decisions were retained.

### Read-only vector audit follow-up — 2026-10-23

- Fixed `audit_namespace` to detect missing/orphaned records independently
  in dense and sparse indexes. `expected_sparse_ids=None` requires the same
  IDs in both; explicit `[]` documents the current dense-only summary policy.
  One-sided loss can no longer report parity.
- Replaced `make vector-audit`'s empty-expected-ID placeholder with a service
  that hydrates taxonomy, JD, resume and summary expectations from Postgres.
  All known namespaces in the configured environment are audited by default;
  `NS` selects one exact known namespace, passed as environment data without
  interpolation into shell/Python source. Unknown namespaces/environments
  are rejected. It reports JSON and exits 0 for parity, 1 for drift, 2 for
  errors. No embeddings, vector writes, migrations or commits occur.
- Summary expectations include only applications with persisted chunks.
  Candidate namespaces explicitly require dense summary IDs and no sparse
  summaries. This makes the existing storage policy auditable without
  pretending that those summaries exist in both indexes.
- Added 20 regression cases across primitive parity and Postgres-derived
  audits/CLI. `make lint` passes; `make test-api` passes 229 tests.
  `make smoke-hr` passes with real isolated Postgres, two nonempty synthetic
  intakes and Postgres-derived resume/summary audit assertions. A read-only
  `make vector-audit NS=dev-resumes-job-ai-intern-procogia VECTOR_BACKEND=memory`
  CLI check passes against the current empty resume namespace; this is not
  evidence of cloud parity. No live cloud calls were made.
- User requested a reduced-scope continuation with parallel subagents.
  Re-read AGENTS/PRD/PROGRESS and searched for alternate scoped files: current
  PRD edits are whitespace-only, and PRD/PROGRESS still specify M3–M6 in full.
  Asked which features were cut or whether revised files are unsaved. User
  subsequently instructed “Keep building what is left”; proceeding with the
  currently saved PRD scope, as stated before starting M3.
  Three subagents handled the audit primitive, operational command/tests,
  and independent scope/correctness review in separate ownership scopes.

## M3 — Recruiter Copilot (F2.3, PRD §7.2/§7.3)

### Implemented

- A dynamic LangGraph supervisor routes verify, compare, similar, taxonomy
  explanation, interview questions, and status proposals to separate nodes.
  Low verifier confidence invokes Deep Verify once and re-evaluates; invalid
  citations route through up to two grounding retries, then unsupported
  claims are omitted with an explicit fallback. Static intake stays linear.
- Scoped tools hydrate evidence only from Postgres. Hybrid retrieval falls
  back to Postgres with warnings; pool context is bounded and includes saved
  ranking inputs. Similarity reads the dense candidate-summary index through
  `app/rag/similarity.py`, validates peers against the job, and re-embeds a
  summary from persisted chunks because VectorStore.fetch exposes no values.
- Comparison/similarity claims require citations from at least two candidate
  owners; candidate-anchored similarity must include that selected candidate.
  No-peer similarity emits no claims without invoking an answer LLM.
- GitHub Deep Verify accepts only public HTTPS github.com username links,
  uses fixed api.github.com endpoints, bounded repos/timeouts, and no
  redirects. External context is supplementary and cannot replace resume
  citations. Arbitrary portfolio fetching is deliberately not implemented.
- LLM calls use `app/llm` structured outputs with six versioned copilot v1
  prompts. User, resume and external data are serialized into delimited
  user-turn blocks; candidate claims outside cited outputs are suppressed.
  Taxonomy explanations display hydrated taxonomy descriptions.
- Copilot status changes pause at a real LangGraph `interrupt`. Approve or
  cancel resumes the same Postgres checkpoint; the scoped write tool calls
  the existing audited HR label service only after explicit approval.
  Checkpoint serializer explicitly permits the three nested copilot models.
- Durable `copilot_runs` model and new `0003_copilot_runs` migration support
  queued/running/awaiting_confirmation/completed/failed states. API requests
  only enqueue and stream database state; all graph/model work runs in the
  worker. SKIP LOCKED claims plus committed running status prevent duplicate
  polls. Crashed running jobs remain visible rather than automatically
  replaying potentially committed status writes.
- HR-only `POST /copilot`, `POST /copilot/{run_id}/confirm`, and
  `GET /copilot/{run_id}` expose generated event/run contracts. SSE streams
  end on completion, interrupt, failure, or listener timeout; GET recovers
  results after disconnect. Duplicate/out-of-scope confirmations are blocked.
  Requests, starts, completion, failures and confirmations write events.
- HR chat supports pool/candidate scope, route steps, cited claims, warnings,
  explicit confirm/cancel, interrupted-stream recovery, and peer citations
  that open the target candidate's hydrated resume chunk. Context changes
  abort listeners and clear results; blind mode disables identity-bearing
  chat. No new dependencies, providers, indexes or services were added.

### Verification and environment limits

- Final integrated checks: `make lint` passes (ruff/format, strict mypy on
  graph/tools/LLM packages, ESLint and TypeScript), `make test-api` passes
  299 tests, `make test-web` passes 28 tests, `git diff --check` passes.
  The final native Postgres smoke also passes after comparative-grounding
  and explicit checkpoint serializer fixes, with no serializer warning.
- Added `make smoke-copilot`, extending the isolated HR smoke with the real
  worker, SSE endpoint, fake structured provider, cited answers, Deep Verify
  fallback, grounding retry, and real Postgres interrupt/cancel/approve plus
  audit/duplicate-confirm checks. All external HTTP transports stay blocked.
- Docker's Postgres began reporting `global/pg_filenode.map: Input/output
  error` after disk exhaustion, and Docker commands hung. Normal Docker
  Desktop restart timed out. No Docker disk, database volume, container or
  source data was deleted. An attempted disposable builder-cache prune also
  hung. npm's download cache was cleaned (installed dependencies retained),
  freeing about 2.9 GB initially; disk remains low and fluctuates.
- `make migrate` could not complete against Docker; `make migrate LOCAL=1`
  now supports a direct local DB connection but that same Docker DB reports
  I/O failure. Migration 0003 is NOT claimed applied to the main Docker DB.
- Verified `make smoke-copilot
  DATABASE_URL=postgresql+psycopg://ahmadwali04@localhost:5432/postgres`
  against a disposable database on native Postgres instead. Migrations
  0001–0003 and zero-drift Alembic check passed; the complete fake-provider
  intake/HR/copilot workflow passed, and its temporary DB/files were removed.
  Native existing databases and main application data were left untouched.
- New prompts: ran `make eval-fast`; target still prints its M5 placeholder.
  No live-model quality delta or router-accuracy metric is claimed. Existing
  OpenAI-credit limitation remains; provider calls are verified with fakes.
- Real Langfuse spans remain M5 work; copilot uses the same stdout callback
  hook as intake. Live GitHub success/rate limits and browser-driven full
  acceptance remain unverified. Existing native Tailwind/text-viewer stack
  deviations remain recorded from M2.

## Dependency export — 2026-10-23

Added root `requirements.txt` for Python 3.12,
exported frozen runtime and dev dependencies from `apps/api/uv.lock` with
`uv export --frozen --no-emit-project --format requirements-txt --no-hashes`.
Added root-relative `-e ./apps/api` to install the shared local package.
Install from the repo root with `python -m pip install -r requirements.txt`.
`pyproject.toml`/`uv.lock` remain authoritative; regenerate the pins after
dependency changes and retain the editable package line. AST import scan
found all third-party Python import roots covered; frontend dependencies
remain npm-managed. `make lint` and all 299 backend tests pass. No fresh
pip environment was installed as part of this export.

## Not started

M4 (Tech Lead portal), M5 (eval
harness + Langfuse), M6 (polish + demo).
