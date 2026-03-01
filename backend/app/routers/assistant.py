from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.map_context import MapContext
from app.services.assistant_context_summary import build_context_summary
from app.services.assistant_runner import run_assistant

router = APIRouter(tags=["assistant"])


class AssistantContext(BaseModel):
    measure_id: str | None = None
    year: int | None = None
    data_value_type_id: str | None = None
    zoom: float | None = None
    bbox: list[float] | str | None = None
    active_layer: str | None = None


class AssistantQueryBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    context: AssistantContext | None = None
    map_context: MapContext | None = None
    analyze: bool = False


@router.post("/assistant/query")
def query_assistant(body: AssistantQueryBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    user_text = body.text.strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="text is required")

    if body.analyze and body.map_context is not None:
        try:
            context_summary = build_context_summary(body.map_context, db)
        except Exception:
            context_summary = None
        if context_summary is not None:
            return {
                "actions": [],
                "answer_markdown": "",
                "context_summary": context_summary,
                "debug": {
                    "mode": "context_summary",
                    "data_source": context_summary.get("dataSource"),
                },
            }

    context_dict = (
        body.context.model_dump(exclude_none=True)
        if body.context is not None
        else {}
    )
    map_context_dict = (
        body.map_context.model_dump(exclude_none=True)
        if body.map_context is not None
        else None
    )
    return run_assistant(
        user_text=user_text,
        context=context_dict,
        map_context=map_context_dict,
        db=db,
    )
