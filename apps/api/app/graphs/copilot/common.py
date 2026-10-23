"""Structured output contracts and safe user-turn data serialization."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import get_settings
from app.graphs.state import CopilotClaim, CopilotState
from app.llm import get_llm_provider
from app.prompts import load_prompt

Route = Literal["verify", "compare", "similar", "explain", "questions", "update_status"]


class RouteDecision(BaseModel):
    route: Route
    term: str = ""
    status: Literal["valid", "pending", "rejected"] | None = None


class AgentAnswer(BaseModel):
    claims: list[CopilotClaim] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    explanation: str = ""


def data_block(name: str, data: Any) -> str:
    # JSON escapes angle brackets to prevent data from closing delimiters.
    text = json.dumps(data, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e")
    return f"<untrusted_{name}>\n{text}\n</untrusted_{name}>"


def generate_answer(state: CopilotState, prompt_name: str) -> dict[str, Any]:
    prompt = "\n".join(
        [
            data_block("user_request", state.message),
            data_block("resume_evidence", [item.model_dump() for item in state.evidence]),
            data_block("external_context", state.external_context),
            f"Prior grounding failures: {state.retries}. Cite ONLY evidence chunk_id row IDs.",
        ]
    )
    result = asyncio.run(
        get_llm_provider().generate_structured(
            system=load_prompt(prompt_name),
            prompt=prompt,
            output_model=AgentAnswer,
            temperature=get_settings().llm_temperature,
        )
    )
    return {
        "claims": result.claims,
        "confidence": result.confidence,
        "explanation": "",
        "steps": [*state.steps, prompt_name.split(".")[0]],
    }
