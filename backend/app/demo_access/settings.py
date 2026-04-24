from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    return normalized not in {"0", "false", "no", "off"}


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _as_str(value: str | None, default: str = "") -> str:
    if value is None:
        return default
    normalized = value.strip()
    return normalized if normalized else default


@dataclass(frozen=True)
class DemoAccessSettings:
    enabled: bool
    session_secret: str
    code_hash_secret: str
    admin_secret: str
    session_ttl_days: int
    cookie_name: str
    cookie_secure: bool
    cookie_samesite: str
    rate_limit_attempts: int
    rate_limit_window_seconds: int


@lru_cache(maxsize=1)
def get_demo_access_settings() -> DemoAccessSettings:
    session_secret = _as_str(os.getenv("DEMO_ACCESS_SESSION_SECRET"))
    code_hash_secret = _as_str(os.getenv("DEMO_ACCESS_CODE_PEPPER"), session_secret)
    cookie_samesite = _as_str(os.getenv("DEMO_ACCESS_COOKIE_SAMESITE"), "lax").lower()
    if cookie_samesite not in {"lax", "strict", "none"}:
        cookie_samesite = "lax"

    return DemoAccessSettings(
        enabled=_as_bool(os.getenv("DEMO_ACCESS_ENABLED"), True),
        session_secret=session_secret,
        code_hash_secret=code_hash_secret,
        admin_secret=_as_str(os.getenv("DEMO_ACCESS_ADMIN_SECRET")),
        session_ttl_days=max(1, _as_int(os.getenv("DEMO_ACCESS_SESSION_TTL_DAYS"), 7)),
        cookie_name=_as_str(os.getenv("DEMO_ACCESS_COOKIE_NAME"), "chip_demo_access"),
        cookie_secure=_as_bool(os.getenv("DEMO_ACCESS_COOKIE_SECURE"), False),
        cookie_samesite=cookie_samesite,
        rate_limit_attempts=max(1, _as_int(os.getenv("DEMO_ACCESS_RATE_LIMIT_ATTEMPTS"), 10)),
        rate_limit_window_seconds=max(
            30,
            _as_int(os.getenv("DEMO_ACCESS_RATE_LIMIT_WINDOW_SECONDS"), 300),
        ),
    )

