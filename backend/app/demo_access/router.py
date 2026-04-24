from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.demo_access import service
from app.demo_access.rate_limit import validation_rate_limiter
from app.demo_access.schemas import (
    DemoAccessCodeAdmin,
    DemoAccessCodeCreateRequest,
    DemoAccessCodeCreateResponse,
    DemoAccessCodeListResponse,
    DemoAccessCodeUpdateRequest,
    DemoAccessEventListResponse,
    DemoAccessSessionResponse,
    DemoAccessValidateRequest,
    DemoAccessValidateResponse,
)
from app.demo_access.settings import DemoAccessSettings, get_demo_access_settings

router = APIRouter(prefix="/api/demo-access", tags=["demo-access"])


def _request_metadata(request: Request) -> service.RequestMetadata:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    ip_address = forwarded_for.split(",", 1)[0].strip() if forwarded_for else None
    if not ip_address and request.client:
        ip_address = request.client.host
    return service.request_metadata_from_headers(
        ip_address=ip_address,
        user_agent=request.headers.get("user-agent"),
        request_path=str(request.url.path),
        referrer=request.headers.get("referer"),
    )


def _cookie_max_age(settings: DemoAccessSettings) -> int:
    return settings.session_ttl_days * 24 * 60 * 60


def _set_session_cookie(
    response: Response,
    *,
    value: str,
    settings: DemoAccessSettings,
) -> None:
    response.set_cookie(
        key=settings.cookie_name,
        value=value,
        max_age=_cookie_max_age(settings),
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )


def _clear_session_cookie(response: Response, *, settings: DemoAccessSettings) -> None:
    response.delete_cookie(
        key=settings.cookie_name,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )


def _extract_bearer_token(value: str | None) -> str | None:
    if not value:
        return None
    prefix = "bearer "
    if value.lower().startswith(prefix):
        return value[len(prefix):].strip()
    return None


def require_demo_access_admin(
    authorization: str | None = Header(default=None),
    x_demo_admin_secret: str | None = Header(default=None),
) -> None:
    settings = get_demo_access_settings()
    expected = settings.admin_secret
    if not expected:
        raise HTTPException(status_code=503, detail="Demo access admin secret is not configured.")
    supplied = (x_demo_admin_secret or _extract_bearer_token(authorization) or "").strip()
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="Invalid demo access admin secret.")


@router.get("/session", response_model=DemoAccessSessionResponse)
def get_demo_access_session(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    settings = get_demo_access_settings()
    if not settings.enabled:
        return DemoAccessSessionResponse(has_access=True)

    resolved = service.resolve_session(
        db,
        raw_cookie=request.cookies.get(settings.cookie_name),
        settings=settings,
    )
    if not resolved.is_valid:
        _clear_session_cookie(response, settings=settings)
        return DemoAccessSessionResponse(has_access=False)

    service.log_event(
        db,
        event_type=service.EVENT_SESSION_RESTORED,
        success=True,
        metadata=_request_metadata(request),
        access_code_id=resolved.access_code.id if resolved.access_code else None,
        session_id=resolved.session_id,
    )
    db.commit()
    return DemoAccessSessionResponse(
        has_access=True,
        session_expires_at=resolved.expires_at,
        code_label=resolved.access_code.code_label if resolved.access_code else None,
        recipient_name=resolved.access_code.recipient_name if resolved.access_code else None,
        organization=resolved.access_code.organization if resolved.access_code else None,
    )


@router.post("/validate", response_model=DemoAccessValidateResponse)
def validate_demo_access(
    body: DemoAccessValidateRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    settings = get_demo_access_settings()
    metadata = _request_metadata(request)
    rate_key = metadata.ip_address or "unknown"
    if not validation_rate_limiter.allow(
        rate_key,
        max_attempts=settings.rate_limit_attempts,
        window_seconds=settings.rate_limit_window_seconds,
    ):
        service.log_event(
            db,
            event_type=service.EVENT_FAILED_ATTEMPT,
            success=False,
            metadata=metadata,
            failure_reason="rate_limited",
        )
        db.commit()
        raise HTTPException(status_code=429, detail="Too many attempts. Please wait and try again.")

    try:
        result = service.validate_access_code(
            db,
            raw_code=body.access_code,
            settings=settings,
            metadata=metadata,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not result.success or not result.access_code or not result.session_id or not result.session_expires_at:
        raise HTTPException(status_code=401, detail="Invalid or expired access code.")

    cookie_value = service.create_session_cookie_value(
        access_code_id=result.access_code.id,
        session_id=result.session_id,
        expires_at=result.session_expires_at,
        settings=settings,
    )
    _set_session_cookie(response, value=cookie_value, settings=settings)
    return DemoAccessValidateResponse(
        success=True,
        session_expires_at=result.session_expires_at,
        code_label=result.access_code.code_label,
    )


@router.post("/logout")
def logout_demo_access(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    settings = get_demo_access_settings()
    resolved = service.resolve_session(
        db,
        raw_cookie=request.cookies.get(settings.cookie_name),
        settings=settings,
    )
    service.log_event(
        db,
        event_type=service.EVENT_LOGOUT,
        success=resolved.is_valid,
        metadata=_request_metadata(request),
        access_code_id=resolved.access_code.id if resolved.access_code else None,
        session_id=resolved.session_id,
        failure_reason=None if resolved.is_valid else resolved.failure_reason,
    )
    db.commit()
    _clear_session_cookie(response, settings=settings)
    return {"success": True}


@router.get(
    "/admin/codes",
    response_model=DemoAccessCodeListResponse,
    dependencies=[Depends(require_demo_access_admin)],
)
def list_demo_access_codes(db: Session = Depends(get_db)):
    return DemoAccessCodeListResponse(items=service.list_codes(db))


@router.post(
    "/admin/codes",
    response_model=DemoAccessCodeCreateResponse,
    dependencies=[Depends(require_demo_access_admin)],
)
def create_demo_access_code(
    body: DemoAccessCodeCreateRequest,
    db: Session = Depends(get_db),
):
    try:
        code, plaintext = service.create_access_code(
            db,
            settings=get_demo_access_settings(),
            code_label=body.code_label,
            recipient_name=body.recipient_name,
            recipient_email=str(body.recipient_email) if body.recipient_email else None,
            organization=body.organization,
            notes=body.notes,
            created_by=body.created_by,
            is_active=body.is_active,
            max_uses=body.max_uses,
            expires_at=body.expires_at,
            plaintext_code=body.access_code,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return DemoAccessCodeCreateResponse(
        code=DemoAccessCodeAdmin.model_validate(code),
        plaintext_access_code=plaintext,
    )


@router.patch(
    "/admin/codes/{code_id}",
    response_model=DemoAccessCodeAdmin,
    dependencies=[Depends(require_demo_access_admin)],
)
def update_demo_access_code(
    code_id: int,
    body: DemoAccessCodeUpdateRequest,
    db: Session = Depends(get_db),
):
    values = body.model_dump(exclude_unset=True)
    if "code_label" in values and not values["code_label"]:
        raise HTTPException(status_code=400, detail="code_label cannot be blank.")
    if "recipient_email" in values and values["recipient_email"] is not None:
        values["recipient_email"] = str(values["recipient_email"])
    code = service.update_code(db, code_id, values)
    if code is None:
        raise HTTPException(status_code=404, detail="Access code not found.")
    return DemoAccessCodeAdmin.model_validate(code)


@router.get(
    "/admin/events",
    response_model=DemoAccessEventListResponse,
    dependencies=[Depends(require_demo_access_admin)],
)
def list_demo_access_events(
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    return DemoAccessEventListResponse(items=service.list_events(db, limit=limit, offset=offset))
