"""Taxonomy-backed general explanation, never a candidate judgment."""
from __future__ import annotations

import asyncio
from typing import Any

from app.config import get_settings
from app.graphs.copilot.common import AgentAnswer, data_block
from app.graphs.state import CopilotState
from app.llm import get_llm_provider
from app.prompts import load_prompt
from app.tools.copilot import search_taxonomy


def explainer(state: CopilotState) -> dict[str, Any]:
    entries = search_taxonomy(state.message)
    result = asyncio.run(get_llm_provider().generate_structured(
        system=load_prompt("copilot_explain.v1"),
        prompt=data_block("user_request", state.message) + "\n" + data_block("taxonomy", entries),
        output_model=AgentAnswer, temperature=get_settings().llm_temperature))
    # Surface the source taxonomy descriptions themselves; a general-answer
    # route cannot smuggle an uncited candidate assessment into free prose.
    explanation = "\n".join(f"{item['canonical']}: {item['description']}" for item in entries)
    return {"claims": [], "explanation": explanation or "No matching taxonomy explanation was found.",
            "confidence": result.confidence if entries else 0.0,
            "steps": [*state.steps, "skill_explainer"]}
