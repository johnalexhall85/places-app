from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class MethodologyNote(BaseModel):
    source: str | None = None
    as_of_date: date | None = None
    calculation: str | None = None
    caveats: list[str] = Field(default_factory=list)
    fields: dict[str, str] = Field(default_factory=dict)
