from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Select, desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.demo_access.models import DemoAccessCode, DemoAccessEvent
from app.demo_access.settings import DemoAccessSettings

EVENT_VALIDATED = "validated"
EVENT_FAILED_ATTEMPT = "failed_attempt"
EVENT_LOGOUT = "logout"
EVENT_SESSION_RESTORED = "session_restored"

CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


@dataclass(frozen=True)
class RequestMetadata:
    ip_address: str | None = None
    user_agent: str | None = None
    request_path: str | None = None
    referrer: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    success: bool
    access_code: DemoAccessCode | None = None
    session_id: str | None = None
    session_expires_at: datetime | None = None
    failure_reason: str | None = None


@dataclass(frozen=True)
class ResolvedSession:
    is_valid: bool
    session_id: str | None = None
    access_code: DemoAccessCode | None = None
    expires_at: datetime | None = None
    failure_reason: str | None = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_access_code(raw_code: str) -> str:
    token = "".join(ch for ch in str(raw_code or "").strip().upper() if ch not in {" ", "-", "\t", "\n", "\r"})
    return token


def hash_access_code(raw_code: str, settings: DemoAccessSettings) -> str:
    normalized = normalize_access_code(raw_code)
    if not normalized:
        raise ValueError("access code is required")
    if not settings.code_hash_secret:
        raise RuntimeError("DEMO_ACCESS_CODE_PEPPER or DEMO_ACCESS_SESSION_SECRET must be configured")
    digest = hmac.new(
        settings.code_hash_secret.encode("utf-8"),
        normalized.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


def generate_access_code() -> str:
    groups = [
        "".join(secrets.choice(CODE_ALPHABET) for _ in range(4)),
        "".join(secrets.choice(CODE_ALPHABET) for _ in range(4)),
        "".join(secrets.choice(CODE_ALPHABET) for _ in range(4)),
    ]
    return f"CHIP-{'-'.join(groups)}"


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _sign_payload(payload: str, settings: DemoAccessSettings) -> str:
    if not settings.session_secret:
        raise RuntimeError("DEMO_ACCESS_SESSION_SECRET must be configured")
    return _base64url_encode(
        hmac.new(
            settings.session_secret.encode("utf-8"),
            payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
    )


def create_session_cookie_value(
    *,
    access_code_id: int,
    session_id: str,
    expires_at: datetime,
    settings: DemoAccessSettings,
) -> str:
    payload = {
        "cid": int(access_code_id),
        "sid": session_id,
        "exp": int(coerce_utc(expires_at).timestamp()),
    }
    encoded_payload = _base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return f"{encoded_payload}.{_sign_payload(encoded_payload, settings)}"


def read_session_cookie_value(raw_cookie: str | None, settings: DemoAccessSettings) -> dict[str, Any] | None:
    if not raw_cookie or "." not in raw_cookie:
        return None
    payload, supplied_signature = raw_cookie.split(".", 1)
    try:
        expected_signature = _sign_payload(payload, settings)
    except RuntimeError:
        return None
    if not hmac.compare_digest(supplied_signature, expected_signature):
        return None
    try:
        decoded = json.loads(_base64url_decode(payload).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(decoded, dict):
        return None
    return decoded


def request_metadata_from_headers(
    *,
    ip_address: str | None,
    user_agent: str | None,
    request_path: str | None,
    referrer: str | None,
) -> RequestMetadata:
    return RequestMetadata(
        ip_address=ip_address,
        user_agent=user_agent,
        request_path=request_path,
        referrer=referrer,
    )


def log_event(
    db: Session,
    *,
    event_type: str,
    success: bool,
    metadata: RequestMetadata,
    access_code_id: int | None = None,
    session_id: str | None = None,
    failure_reason: str | None = None,
) -> DemoAccessEvent:
    event = DemoAccessEvent(
        access_code_id=access_code_id,
        event_type=event_type,
        ip_address=metadata.ip_address,
        user_agent=metadata.user_agent,
        session_id=session_id,
        request_path=metadata.request_path,
        referrer=metadata.referrer,
        success=success,
        failure_reason=failure_reason,
    )
    db.add(event)
    return event


def create_access_code(
    db: Session,
    *,
    settings: DemoAccessSettings,
    code_label: str,
    recipient_name: str | None = None,
    recipient_email: str | None = None,
    organization: str | None = None,
    notes: str | None = None,
    created_by: str | None = None,
    is_active: bool = True,
    max_uses: int | None = None,
    expires_at: datetime | None = None,
    plaintext_code: str | None = None,
) -> tuple[DemoAccessCode, str]:
    plain_code = plaintext_code or generate_access_code()
    code = DemoAccessCode(
        code_hash=hash_access_code(plain_code, settings),
        code_label=code_label.strip(),
        recipient_name=recipient_name,
        recipient_email=recipient_email,
        organization=organization,
        notes=notes,
        created_by=(created_by or "system").strip() or "system",
        is_active=is_active,
        max_uses=max_uses,
        expires_at=expires_at,
    )
    db.add(code)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("That access code already exists.") from exc
    db.refresh(code)
    return code, plain_code


def _code_is_expired(code: DemoAccessCode, now: datetime) -> bool:
    expires_at = coerce_utc(code.expires_at)
    return bool(expires_at and expires_at <= now)


def _code_is_exhausted(code: DemoAccessCode) -> bool:
    return bool(code.max_uses is not None and int(code.current_use_count or 0) >= int(code.max_uses))


def validate_access_code(
    db: Session,
    *,
    raw_code: str,
    settings: DemoAccessSettings,
    metadata: RequestMetadata,
) -> ValidationResult:
    now = utcnow()
    try:
        code_hash = hash_access_code(raw_code, settings)
    except (RuntimeError, ValueError) as exc:
        log_event(
            db,
            event_type=EVENT_FAILED_ATTEMPT,
            success=False,
            metadata=metadata,
            failure_reason="configuration_error" if isinstance(exc, RuntimeError) else "empty_code",
        )
        db.commit()
        if isinstance(exc, RuntimeError):
            raise
        return ValidationResult(success=False, failure_reason="invalid_code")

    code = db.execute(select(DemoAccessCode).where(DemoAccessCode.code_hash == code_hash)).scalar_one_or_none()
    if code is None:
        log_event(
            db,
            event_type=EVENT_FAILED_ATTEMPT,
            success=False,
            metadata=metadata,
            failure_reason="not_found",
        )
        db.commit()
        return ValidationResult(success=False, failure_reason="invalid_code")

    failure_reason = None
    if not code.is_active:
        failure_reason = "disabled"
    elif _code_is_expired(code, now):
        failure_reason = "expired"
    elif _code_is_exhausted(code):
        failure_reason = "max_uses_reached"

    if failure_reason:
        log_event(
            db,
            event_type=EVENT_FAILED_ATTEMPT,
            success=False,
            metadata=metadata,
            access_code_id=code.id,
            failure_reason=failure_reason,
        )
        db.commit()
        return ValidationResult(success=False, access_code=code, failure_reason=failure_reason)

    session_id = secrets.token_urlsafe(24)
    session_expires_at = now + timedelta(days=settings.session_ttl_days)
    code.current_use_count = int(code.current_use_count or 0) + 1
    code.last_used_at = now
    log_event(
        db,
        event_type=EVENT_VALIDATED,
        success=True,
        metadata=metadata,
        access_code_id=code.id,
        session_id=session_id,
    )
    db.commit()
    db.refresh(code)
    return ValidationResult(
        success=True,
        access_code=code,
        session_id=session_id,
        session_expires_at=session_expires_at,
    )


def resolve_session(
    db: Session,
    *,
    raw_cookie: str | None,
    settings: DemoAccessSettings,
) -> ResolvedSession:
    payload = read_session_cookie_value(raw_cookie, settings)
    if payload is None:
        return ResolvedSession(is_valid=False, failure_reason="missing_or_invalid_cookie")

    session_id = str(payload.get("sid") or "").strip()
    try:
        access_code_id = int(payload.get("cid"))
        expires_at = datetime.fromtimestamp(int(payload.get("exp")), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return ResolvedSession(is_valid=False, session_id=session_id or None, failure_reason="invalid_cookie_payload")

    now = utcnow()
    if expires_at <= now:
        return ResolvedSession(
            is_valid=False,
            session_id=session_id or None,
            expires_at=expires_at,
            failure_reason="session_expired",
        )

    code = db.get(DemoAccessCode, access_code_id)
    if code is None:
        return ResolvedSession(
            is_valid=False,
            session_id=session_id or None,
            expires_at=expires_at,
            failure_reason="code_not_found",
        )
    if not code.is_active:
        return ResolvedSession(
            is_valid=False,
            session_id=session_id or None,
            access_code=code,
            expires_at=expires_at,
            failure_reason="code_disabled",
        )
    if _code_is_expired(code, now):
        return ResolvedSession(
            is_valid=False,
            session_id=session_id or None,
            access_code=code,
            expires_at=expires_at,
            failure_reason="code_expired",
        )
    return ResolvedSession(
        is_valid=True,
        session_id=session_id,
        access_code=code,
        expires_at=expires_at,
    )


def list_codes(db: Session) -> list[DemoAccessCode]:
    return list(db.execute(select(DemoAccessCode).order_by(desc(DemoAccessCode.created_at))).scalars())


def update_code(db: Session, code_id: int, values: dict[str, Any]) -> DemoAccessCode | None:
    code = db.get(DemoAccessCode, code_id)
    if code is None:
        return None
    for field, value in values.items():
        if hasattr(code, field):
            setattr(code, field, value)
    db.commit()
    db.refresh(code)
    return code


def list_events(db: Session, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    stmt: Select[tuple[DemoAccessEvent, DemoAccessCode | None]] = (
        select(DemoAccessEvent, DemoAccessCode)
        .outerjoin(DemoAccessCode, DemoAccessEvent.access_code_id == DemoAccessCode.id)
        .order_by(desc(DemoAccessEvent.occurred_at), desc(DemoAccessEvent.id))
        .limit(limit)
        .offset(offset)
    )
    rows = db.execute(stmt).all()
    items: list[dict[str, Any]] = []
    for event, code in rows:
        items.append(
            {
                "id": event.id,
                "access_code_id": event.access_code_id,
                "event_type": event.event_type,
                "occurred_at": event.occurred_at,
                "ip_address": event.ip_address,
                "user_agent": event.user_agent,
                "session_id": event.session_id,
                "request_path": event.request_path,
                "referrer": event.referrer,
                "success": event.success,
                "failure_reason": event.failure_reason,
                "code_label": code.code_label if code else None,
                "recipient_name": code.recipient_name if code else None,
                "organization": code.organization if code else None,
            }
        )
    return items

