from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DemoAccessValidateRequest(BaseModel):
    access_code: str = Field(min_length=1, max_length=128)


class DemoAccessValidateResponse(BaseModel):
    success: bool
    session_expires_at: datetime
    code_label: str


class DemoAccessSessionResponse(BaseModel):
    has_access: bool
    session_expires_at: datetime | None = None
    code_label: str | None = None
    recipient_name: str | None = None
    organization: str | None = None


class DemoAccessCodeCreateRequest(BaseModel):
    code_label: str = Field(min_length=1, max_length=200)
    recipient_name: str | None = Field(default=None, max_length=200)
    recipient_email: str | None = Field(default=None, max_length=320)
    organization: str | None = Field(default=None, max_length=200)
    notes: str | None = None
    created_by: str | None = Field(default=None, max_length=200)
    is_active: bool = True
    max_uses: int | None = Field(default=None, gt=0)
    expires_at: datetime | None = None
    access_code: str | None = Field(default=None, min_length=4, max_length=128)

    @field_validator("code_label", "recipient_name", "recipient_email", "organization", "created_by", mode="before")
    @classmethod
    def trim_text(cls, value):
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class DemoAccessCodeUpdateRequest(BaseModel):
    code_label: str | None = Field(default=None, min_length=1, max_length=200)
    recipient_name: str | None = Field(default=None, max_length=200)
    recipient_email: str | None = Field(default=None, max_length=320)
    organization: str | None = Field(default=None, max_length=200)
    notes: str | None = None
    is_active: bool | None = None
    max_uses: int | None = Field(default=None, gt=0)
    expires_at: datetime | None = None

    @field_validator("code_label", "recipient_name", "recipient_email", "organization", mode="before")
    @classmethod
    def trim_text(cls, value):
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class DemoAccessCodeAdmin(BaseModel):
    id: int
    code_label: str
    recipient_name: str | None = None
    recipient_email: str | None = None
    organization: str | None = None
    notes: str | None = None
    created_at: datetime
    created_by: str
    is_active: bool
    max_uses: int | None = None
    current_use_count: int
    expires_at: datetime | None = None
    last_used_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class DemoAccessCodeCreateResponse(BaseModel):
    code: DemoAccessCodeAdmin
    plaintext_access_code: str


class DemoAccessEventAdmin(BaseModel):
    id: int
    access_code_id: int | None = None
    event_type: str
    occurred_at: datetime
    ip_address: str | None = None
    user_agent: str | None = None
    session_id: str | None = None
    request_path: str | None = None
    referrer: str | None = None
    success: bool
    failure_reason: str | None = None
    code_label: str | None = None
    recipient_name: str | None = None
    organization: str | None = None


class DemoAccessCodeListResponse(BaseModel):
    items: list[DemoAccessCodeAdmin]


class DemoAccessEventListResponse(BaseModel):
    items: list[DemoAccessEventAdmin]
