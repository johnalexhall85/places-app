from __future__ import annotations

from datetime import timedelta

from app.demo_access import service
from app.demo_access.middleware import _is_public_path
from app.demo_access.settings import DemoAccessSettings
from app.main import app


def _settings() -> DemoAccessSettings:
    return DemoAccessSettings(
        enabled=True,
        session_secret="session-secret",
        code_hash_secret="code-secret",
        admin_secret="admin-secret",
        session_ttl_days=7,
        cookie_name="chip_demo_access",
        cookie_secure=False,
        cookie_samesite="lax",
        rate_limit_attempts=10,
        rate_limit_window_seconds=300,
    )


def test_demo_access_routes_are_registered() -> None:
    route_paths = {route.path for route in app.routes}

    assert "/api/demo-access/validate" in route_paths
    assert "/api/demo-access/logout" in route_paths
    assert "/api/demo-access/session" in route_paths
    assert "/api/demo-access/admin/codes" in route_paths
    assert "/api/demo-access/admin/events" in route_paths


def test_access_code_hashing_normalizes_spacing_and_case() -> None:
    settings = _settings()

    assert service.hash_access_code("CHIP-ABCD-2345-EFGH", settings) == service.hash_access_code(
        "chip abcd2345efgh",
        settings,
    )


def test_signed_session_cookie_round_trip() -> None:
    settings = _settings()
    expires_at = service.utcnow() + timedelta(days=7)

    cookie = service.create_session_cookie_value(
        access_code_id=42,
        session_id="session-123",
        expires_at=expires_at,
        settings=settings,
    )
    payload = service.read_session_cookie_value(cookie, settings)

    assert payload["cid"] == 42
    assert payload["sid"] == "session-123"


def test_demo_access_middleware_public_paths() -> None:
    assert _is_public_path("/health")
    assert _is_public_path("/api/demo-access/session")
    assert _is_public_path("/api/cdc/funding/map")
    assert _is_public_path("/api/cdc/funding/legend")
    assert not _is_public_path("/counties")
    assert not _is_public_path("/api/cdc/funding/filters")
    assert not _is_public_path("/api/cdc/funding/profile/overview")
