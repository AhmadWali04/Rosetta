"""Dynamic copilot routing, confidence branching, grounding retries and HITL."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.config import get_settings
from app.graphs.copilot.comparator import comparator
from app.graphs.copilot.deep_verify import deep_verify
from app.graphs.copilot.explainer import explainer
from app.graphs.copilot.gather import gather
from app.graphs.copilot.grounding import grounding
from app.graphs.copilot.questions import questions
from app.graphs.copilot.similarity import similarity
from app.graphs.copilot.status_update import status_update
from app.graphs.copilot.supervisor import supervisor
from app.graphs.copilot.verifier import verifier
from app.graphs.intake.graph import _psycopg_conn_string, _tracing_callbacks
from app.graphs.state import CopilotProposal, CopilotResult, CopilotState


def after_verification(state: CopilotState) -> str:
    if state.confidence < get_settings().copilot_confidence_threshold and not state.deep_verified:
        return "deep_verify"
    return "grounding"


def after_grounding(state: CopilotState) -> str:
    return "done" if state.grounded else "supervisor"


def build_copilot_graph() -> StateGraph[CopilotState, None, CopilotState, CopilotState]:
    builder = StateGraph(CopilotState)
    nodes = {
        "supervisor": supervisor,
        "gather": gather,
        "verify": verifier,
        "compare": comparator,
        "similar": similarity,
        "explain": explainer,
        "questions": questions,
        "deep_verify": deep_verify,
        "grounding": grounding,
        "update_status": status_update,
    }
    for name, node in nodes.items():
        builder.add_node(name, node)
    builder.add_edge(START, "supervisor")
    builder.add_edge("supervisor", "gather")
    builder.add_conditional_edges(
        "gather",
        lambda state: state.route,
        {
            "verify": "verify",
            "compare": "compare",
            "similar": "similar",
            "explain": "explain",
            "questions": "questions",
            "update_status": "update_status",
        },
    )
    builder.add_conditional_edges(
        "verify", after_verification, {"deep_verify": "deep_verify", "grounding": "grounding"}
    )
    builder.add_edge("deep_verify", "verify")
    for name in ("compare", "similar", "explain", "questions"):
        builder.add_edge(name, "grounding")
    builder.add_conditional_edges(
        "grounding", after_grounding, {"done": END, "supervisor": "supervisor"}
    )
    builder.add_edge("update_status", END)
    return builder


def result_from_state(result: dict[str, Any]) -> CopilotResult:
    state = CopilotState.model_validate(result)
    interrupted = result.get("__interrupt__", ())
    proposal = state.proposal
    if interrupted:
        proposal = CopilotProposal.model_validate(interrupted[0].value)
    return CopilotResult(
        run_id=state.run_id,
        route=state.route,
        claims=state.claims,
        citations=state.evidence,
        explanation=state.explanation,
        confidence=state.confidence,
        warnings=state.warnings,
        steps=state.steps,
        retries=state.retries,
        needs_confirmation=bool(interrupted),
        proposal=proposal,
    )


def run_copilot_graph(state: CopilotState, confirmation: bool | None = None) -> CopilotResult:
    if not state.run_id:
        raise ValueError("Copilot run_id is required for checkpoint isolation")
    with PostgresSaver.from_conn_string(
        _psycopg_conn_string(get_settings().database_url)
    ) as checkpointer:
        checkpointer.serde = JsonPlusSerializer(
            allowed_msgpack_modules=[
                ("app.graphs.state", "CopilotProposal"),
                ("app.graphs.state", "CopilotClaim"),
                ("app.graphs.state", "CopilotCitation"),
            ]
        )
        checkpointer.setup()
        graph = build_copilot_graph().compile(checkpointer=checkpointer)
        config: RunnableConfig = {
            "configurable": {"thread_id": state.run_id},
            "callbacks": _tracing_callbacks(),
            "recursion_limit": 60,
        }
        if confirmation is None:
            output = graph.invoke(state, config=config)
        else:
            snapshot = graph.get_state(config)
            saved = CopilotState.model_validate(snapshot.values)
            if (
                saved.run_id != state.run_id
                or saved.job_id != state.job_id
                or saved.scope != state.scope
                or not snapshot.next
            ):
                raise ValueError("No matching pending confirmation checkpoint")
            output = graph.invoke(Command(resume=confirmation), config=config)
    return result_from_state(output)
