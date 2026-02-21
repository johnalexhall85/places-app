from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.assistant_runner import run_assistant

router = APIRouter(tags=["assistant"])


class AssistantContext(BaseModel):
    measure_id: str = Field(min_length=1)
    year: int
    data_value_type_id: str = Field(min_length=1)
    zoom: float | None = None
    bbox: list[float] | str | None = None
    active_layer: str | None = None


class AssistantQueryBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    context: AssistantContext


@router.post("/assistant/query")
def query_assistant(body: AssistantQueryBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    user_text = body.text.strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="text is required")
    return run_assistant(
        user_text=user_text,
        context=body.context.model_dump(),
        db=db,
    )
