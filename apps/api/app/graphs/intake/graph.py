"""Assembles the static `intake_graph` (PRD §7.1) and exposes the worker's
entry point.

Sync/async convention: this agent's own nodes (`skill_extractor`,
`skill_normalizer`, `requirement_matcher`, `scorer`, `hr_explainer`) are
plain sync `(IntakeState) -> dict` functions, each bridging its own async
work (an LLM call, hybrid search, embeddings) internally with exactly one
`asyncio.run(...)` — see e.g. `skill_extractor.py`'s
`_skill_extractor_async`. That choice is sync because the intake graph
runs inside a background worker process (PRD §13: "a simple poller,
deliberately not a task queue"), and `apps/worker/runner.py` (already
built) calls `run_intake_graph` as a plain blocking
`Callable[[str, str, str], None]` from a sync polling loop with no event
loop running — a sync top-level entry point is the natural fit — and
because `app/db/session.py`'s `session_scope()`/`get_session()` are sync
SQLAlchemy, so every node that touches Postgres is sync-first already.

Agent C's four nodes (`ingest_parse`, `sanitize`, `chunk_and_index`,
`persist`) were observed, over the course of this build, to change their
own sync/async convention more than once while being developed in
parallel (their docstrings explain each version's reasoning, which
disagreed with itself across edits — not a criticism, just a real
consequence of building six agents' files concurrently). Rather than bet
this file's correctness on whichever convention happens to be on disk at
any given instant, `build_intake_graph()` below normalizes every node
through `_as_sync_node()`: a node that's already sync passes through
unchanged; a node that turns out to be `async def` gets wrapped in a
one-line sync shim that drives it with `asyncio.run(...)`, exactly the
same bridge pattern this agent's own nodes already use by hand. This
makes the compiled graph safely callable via `.invoke()` (never
`.ainvoke()`) regardless of which convention Agent C's files land on,
including if they change again after this file is written. The real, sync
`PostgresSaver` checkpointer (verified against the installed
`langgraph-checkpoint-postgres` package below) is used either way — no
outer `asyncio.run` is needed at the graph level, only (at most) one per
node, same as today.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.graphs.intake.chunk_and_index import chunk_and_index
from app.graphs.intake.hr_explainer import hr_explainer
from app.graphs.intake.ingest_parse import ingest_parse
from app.graphs.intake.persist import persist
from app.graphs.intake.requirement_matcher import requirement_matcher
from app.graphs.intake.sanitize import sanitize
from app.graphs.intake.scorer import scorer
from app.graphs.intake.skill_extractor import skill_extractor
from app.graphs.intake.skill_normalizer import skill_normalizer
from app.graphs.state import IntakeState

logger = logging.getLogger("skillbridge.intake")


class StdoutTracingCallbackHandler(BaseCallbackHandler):
    """Structured stdout/logging of node start/end/duration — the hook
    point AGENTS.md's "Use Langfuse tracing in every graph via the
    callback handler" convention asks for, without standing up Langfuse
    itself (that's explicitly M5 scope per PROGRESS.md decision 6; this
    resolution was decided by the orchestrator, not re-decided here).

    Used whenever `settings.langfuse_public_key` is unset (i.e. always,
    until M5). Each "chain" LangGraph runs (the graph itself, and each
    node) fires `on_chain_start`/`on_chain_end`; the node's name arrives
    via `kwargs["name"]`, not `serialized` (verified directly against the
    installed `langgraph`/`langchain-core` versions — `serialized` is
    `None` for graph-internal chains).

    # TODO(M5): once Langfuse is wired into docker-compose.yml, replace
    # this handler with `langfuse.callback.CallbackHandler(...)` (or
    # whatever the then-current Langfuse SDK's LangChain/LangGraph
    # integration is called) whenever `settings.langfuse_public_key` is
    # set. Keep this stdout handler as the fallback for local dev without
    # a Langfuse key.
    """

    def __init__(self) -> None:
        self._starts: dict[Any, tuple[str, float]] = {}

    def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: dict[str, Any],
        *,
        run_id: Any,
        parent_run_id: Any | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        name = kwargs.get("name") or (serialized or {}).get("name") or "node"
        self._starts[run_id] = (name, time.monotonic())
        logger.info("intake_graph node_start name=%s run_id=%s", name, run_id)

    def on_chain_end(
        self,
        outputs: Any,
        *,
        run_id: Any,
        parent_run_id: Any | None = None,
        **kwargs: Any,
    ) -> None:
        name, started = self._starts.pop(run_id, ("node", time.monotonic()))
        duration_s = time.monotonic() - started
        logger.info(
            "intake_graph node_end name=%s run_id=%s duration_s=%.3f", name, run_id, duration_s
        )


def _tracing_callbacks() -> list[BaseCallbackHandler]:
    settings = get_settings()
    if settings.langfuse_public_key:
        # TODO(M5): swap in the real Langfuse handler here.
        logger.warning(
            "langfuse_public_key is set but no Langfuse callback handler is wired yet "
            "(M5 scope per PROGRESS.md decision 6) — falling back to stdout tracing"
        )
    return [StdoutTracingCallbackHandler()]


def _psycopg_conn_string(database_url: str) -> str:
    """`PostgresSaver` (psycopg3-based) wants a plain `postgresql://` DSN;
    `settings.database_url` is a SQLAlchemy-style URL with a `+psycopg`
    driver qualifier psycopg itself doesn't accept. Strip the qualifier
    rather than keeping a second, parallel DSN env var for the same
    Postgres instance."""
    parts = urlsplit(database_url)
    scheme = parts.scheme.split("+")[0]
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))


NodeFn = Callable[[IntakeState], dict[str, Any]]


def _as_sync_node(fn: Callable[..., Any]) -> NodeFn:
    """Normalizes a node callable to plain sync, regardless of whether it
    was written `def` or `async def` — see the module docstring for why
    this exists (Agent C's nodes were observed to change convention more
    than once during this build). An already-sync function passes through
    untouched; an async one is wrapped in a one-line `asyncio.run(...)`
    shim, the same bridge every sync node in this package already uses by
    hand internally."""
    if inspect.iscoroutinefunction(fn):

        def _sync_wrapper(state: IntakeState) -> dict[str, Any]:
            return asyncio.run(fn(state))

        return _sync_wrapper
    return fn


def build_intake_graph() -> StateGraph[IntakeState, None, IntakeState, IntakeState]:
    """Assembles the fixed linear pipeline, PRD §7.1's exact order
    (AGENTS.md invariant #6 — intake stays a fixed linear pipeline, never
    conditionally routed). Returns the *uncompiled* builder so callers
    choose their own checkpointer: `run_intake_graph` below compiles it
    with a real Postgres-backed one; tests compile it with none, to avoid
    needing a live Postgres connection just to exercise node logic
    end-to-end.
    """
    builder = StateGraph(IntakeState)

    # `# type: ignore[call-overload]` on every `add_node` call below: mypy
    # --strict's `add_node` overloads want a node argument that structurally
    # matches LangGraph's own `_Node[NodeInputT]` protocol family; a plain
    # `Callable[[IntakeState], dict[str, Any]]` (what `_as_sync_node` always
    # returns) doesn't satisfy that protocol under strict mode even though
    # it's exactly the shape LangGraph accepts at runtime — verified
    # directly (see this agent's report: a toy `StateGraph` with the same
    # plain-function node shape builds, compiles, and invokes correctly).
    # This is a rough edge between LangGraph's heavily-overloaded typed API
    # and a plain function reference, not a real type error.
    builder.add_node("ingest_parse", _as_sync_node(ingest_parse))  # type: ignore[call-overload]
    builder.add_node("sanitize", _as_sync_node(sanitize))  # type: ignore[call-overload]
    builder.add_node("chunk_and_index", _as_sync_node(chunk_and_index))  # type: ignore[call-overload]
    builder.add_node("skill_extractor", _as_sync_node(skill_extractor))  # type: ignore[call-overload]
    builder.add_node("skill_normalizer", _as_sync_node(skill_normalizer))  # type: ignore[call-overload]
    builder.add_node("requirement_matcher", _as_sync_node(requirement_matcher))  # type: ignore[call-overload]
    builder.add_node("scorer", _as_sync_node(scorer))  # type: ignore[call-overload]
    builder.add_node("hr_explainer", _as_sync_node(hr_explainer))  # type: ignore[call-overload]
    builder.add_node("persist", _as_sync_node(persist))  # type: ignore[call-overload]

    builder.add_edge(START, "ingest_parse")
    builder.add_edge("ingest_parse", "sanitize")
    builder.add_edge("sanitize", "chunk_and_index")
    builder.add_edge("chunk_and_index", "skill_extractor")
    builder.add_edge("skill_extractor", "skill_normalizer")
    builder.add_edge("skill_normalizer", "requirement_matcher")
    builder.add_edge("requirement_matcher", "scorer")
    builder.add_edge("scorer", "hr_explainer")
    builder.add_edge("hr_explainer", "persist")
    builder.add_edge("persist", END)

    return builder


def ensure_checkpointer_schema(database_url: str | None = None) -> None:
    """Creates the Postgres checkpointer's own tables (`checkpoints`,
    `checkpoint_writes`, etc) if they don't exist yet, via
    `PostgresSaver.setup()`.

    Call this ONCE at worker process startup (`apps/worker/main.py`,
    before its poll loop starts) — NOT per graph invocation: `setup()`
    runs `CREATE TABLE IF NOT EXISTS`-style DDL that would otherwise cost
    an extra round-trip on every single application processed.

    `PostgresSaver.from_conn_string` is a `@contextmanager` bound to a
    single psycopg connection (verified via `inspect.getsource` against
    the installed `langgraph-checkpoint-postgres==2.x` package — its
    classmethod opens a `psycopg.Connection`, yields a `PostgresSaver`
    wrapping it, and closes the connection when the `with` block exits).
    """
    settings = get_settings()
    conn_string = _psycopg_conn_string(database_url or settings.database_url)
    with PostgresSaver.from_conn_string(conn_string) as checkpointer:
        checkpointer.setup()


def run_intake_graph(application_id: str, job_id: str, resume_path: str) -> IntakeState:
    """Entry point the worker calls once per application (PRD §7.1's
    static pipeline, end to end). Matches `apps/worker/runner.py`'s
    expected `(application_id, job_id, resume_path)` signature (that file
    documents its own expectation as `Callable[[str, str, str], None]` —
    sync, return value ignored). Returns the final `IntakeState` anyway;
    the worker doesn't use it, but it's handy for direct testing/
    debugging.

    Compiles the graph with a real Postgres-backed checkpointer and runs
    it with `thread_id=application_id`, so each application's graph state
    is checkpointed independently (PRD §13).

    No `interrupt()` calls exist anywhere in this graph for M1 — nothing
    here needs human confirmation mid-run yet (that's M2/M3 scope, once a
    write tool like `update_status` is reachable from inside a graph). The
    checkpointer is wired for real per the PRD §13 tech-stack choice, but
    isn't yet exercised for mid-graph resumption; this is the intentional
    M1 scope boundary, not an oversight.

    A fresh connection is opened and closed per application here (the
    `with PostgresSaver.from_conn_string(...)` block), which is simple and
    correct for M1's one-poller-at-a-time worker; pooling the connection
    across applications is a reasonable later optimization if
    per-application connection overhead shows up in the PRD §11 p95
    latency numbers.
    """
    settings = get_settings()
    conn_string = _psycopg_conn_string(settings.database_url)
    initial_state = IntakeState(
        application_id=application_id, job_id=job_id, resume_path=resume_path
    )

    with PostgresSaver.from_conn_string(conn_string) as checkpointer:
        graph = build_intake_graph().compile(checkpointer=checkpointer)
        config: RunnableConfig = {
            "configurable": {"thread_id": application_id},
            "callbacks": _tracing_callbacks(),
        }
        result = graph.invoke(initial_state, config=config)

    return IntakeState.model_validate(result)
