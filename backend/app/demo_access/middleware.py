from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.db import SessionLocal
from app.demo_access import service
from app.demo_access.settings import get_demo_access_settings


PUBLIC_PATHS = {
    "/health",
    "/api/health",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/favicon.ico",
    "/api/cdc/funding/map",
    "/api/cdc/funding/legend",
}


def _is_public_path(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    return (
        path.startswith("/docs/")
        or path.startswith("/redoc/")
        or path.startswith("/api/demo-access")
        or path.startswith("/demo-access")
    )


class DemoAccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_demo_access_settings()
        if (
            not settings.enabled
            or request.method.upper() == "OPTIONS"
            or _is_public_path(request.url.path)
        ):
            return await call_next(request)

        db = SessionLocal()
        try:
            resolved = service.resolve_session(
                db,
                raw_cookie=request.cookies.get(settings.cookie_name),
                settings=settings,
            )
            if not resolved.is_valid:
                return JSONResponse(
                    status_code=401,
                    content={
                        "detail": "Demo access required.",
                        "demo_access_required": True,
                    },
                )
            request.state.demo_access_code_id = resolved.access_code.id if resolved.access_code else None
            request.state.demo_access_session_id = resolved.session_id
            return await call_next(request)
        finally:
            db.close()
