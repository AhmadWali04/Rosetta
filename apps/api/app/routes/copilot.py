"""HR Copilot enqueue/read/SSE endpoints. Graph execution belongs to the worker."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.routes.copilot_schemas import (
    CopilotConfirmation,
    CopilotEvent,
    CopilotRequest,
    CopilotRunOut,
)
from app.routes.hr import require_hr
from app.services import copilot

router = APIRouter(prefix="/copilot", tags=["copilot"], dependencies=[Depends(require_hr)])
Db = Annotated[Session, Depends(get_session)]
SSE_DOCS = {200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}}


def _stream(run_id: str) -> StreamingResponse:
    return StreamingResponse(
        copilot.stream_run(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("", response_model=CopilotEvent, responses=SSE_DOCS)
async def ask(body: CopilotRequest, db: Db) -> StreamingResponse:
    run = copilot.enqueue(db, body)
    return _stream(run.id)


@router.post("/{run_id}/confirm", response_model=CopilotEvent, responses=SSE_DOCS)
async def confirm(run_id: str, body: CopilotConfirmation, db: Db) -> StreamingResponse:
    run = copilot.confirm(db, run_id, body.approve)
    return _stream(run.id)


@router.get("/{run_id}", response_model=CopilotRunOut)
async def get_run(run_id: str, db: Db) -> CopilotRunOut:
    return CopilotRunOut.model_validate(copilot.get_run(db, run_id))
