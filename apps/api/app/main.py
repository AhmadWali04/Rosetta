"""FastAPI entrypoint.

Minimal on purpose: real routers land in later milestones (see AGENTS.md
repo layout — app/routes/ owns the HTTP layer). M0 only needs an app object
and a health check so docker-compose / the worker have something to boot
against.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="SkillBridge API")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
