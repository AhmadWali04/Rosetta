"""FastAPI entrypoint.

M1 adds the real routers (app/routes/jobs.py, app/routes/applications.py)
and CORS for the Next.js dev origin. `GET /health` stays from M0.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes import applications, hr, jobs

settings = get_settings()

app = FastAPI(title="SkillBridge API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router)
app.include_router(applications.router)
app.include_router(hr.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
