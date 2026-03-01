from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
from typing import Any

from app.services.report_branding import REPORT_BRANDING_VERSION

PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = Path(__file__).resolve().parents[1]
PROFILE_EXPORTS_ROOT = APP_ROOT / "data" / "profile_exports"

DEFAULT_FRONTEND_BASE_URL = "http://localhost:5173"
_PRESENTATION_FILES = (
    PROJECT_ROOT / "frontend" / "src" / "index.css",
    PROJECT_ROOT / "frontend" / "src" / "pages" / "ProfileReport.css",
    PROJECT_ROOT / "frontend" / "src" / "pages" / "ProfileCounty.jsx",
    PROJECT_ROOT / "frontend" / "src" / "pages" / "ProfileTract.jsx",
)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def profile_frontend_base_url() -> str:
    configured = _as_text(os.getenv("PROFILE_FRONTEND_BASE_URL"))
    if not configured:
        return DEFAULT_FRONTEND_BASE_URL
    return configured.rstrip("/")


def profile_presentation_signature() -> str:
    digest = sha256()
    digest.update(f"branding:{REPORT_BRANDING_VERSION}".encode("utf-8"))
    for path in _PRESENTATION_FILES:
        digest.update(str(path).encode("utf-8"))
        if not path.exists():
            digest.update(b":missing")
            continue
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def build_profile_pdf_cache_key(
    *,
    geography: str,
    geo_id: str,
    as_of: dict[str, Any],
) -> str:
    digest = sha256()
    digest.update(_as_text(geography).lower().encode("utf-8"))
    digest.update(_as_text(geo_id).encode("utf-8"))
    digest.update(_as_text(as_of.get("places_year")).encode("utf-8"))
    digest.update(_as_text(as_of.get("places_data_value_type_id")).encode("utf-8"))
    digest.update(_as_text(as_of.get("acs_year_window")).encode("utf-8"))
    digest.update(_as_text(as_of.get("acs_data_value_type_id")).encode("utf-8"))
    digest.update(_as_text(as_of.get("svi_year")).encode("utf-8"))
    digest.update(_as_text(as_of.get("hpsa_as_of_date")).encode("utf-8"))
    digest.update(profile_presentation_signature().encode("utf-8"))
    return digest.hexdigest()[:24]


def profile_pdf_cache_path(
    *,
    geography: str,
    geo_id: str,
    cache_key: str,
) -> Path:
    normalized_geography = _as_text(geography).lower()
    safe_geo_id = _as_text(geo_id).replace("/", "_")
    directory = PROFILE_EXPORTS_ROOT / normalized_geography / safe_geo_id
    return directory / f"profile-{cache_key}.pdf"


def cleanup_stale_profile_pdfs(
    *,
    geography: str,
    geo_id: str,
    keep_path: Path | None,
) -> None:
    normalized_geography = _as_text(geography).lower()
    safe_geo_id = _as_text(geo_id).replace("/", "_")
    directory = PROFILE_EXPORTS_ROOT / normalized_geography / safe_geo_id
    if not directory.exists():
        return
    for candidate in directory.glob("profile-*.pdf"):
        if keep_path is not None and candidate.resolve() == keep_path.resolve():
            continue
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            continue


def render_route_pdf_via_playwright(*, route_path: str) -> bytes:
    frontend_base = profile_frontend_base_url()
    normalized_path = route_path if route_path.startswith("/") else f"/{route_path}"
    target_url = f"{frontend_base}{normalized_path}"
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - import error path
        raise RuntimeError(
            "Playwright is required for profile PDF rendering. Install playwright in backend dependencies."
        ) from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(target_url, wait_until="networkidle", timeout=90_000)
            page.wait_for_selector('[data-testid="profile-ready"]', timeout=90_000)
            page.wait_for_load_state("networkidle")
            pdf_bytes = page.pdf(
                print_background=True,
                format="Letter",
                prefer_css_page_size=True,
                margin={
                    "top": "0.5in",
                    "right": "0.5in",
                    "bottom": "0.5in",
                    "left": "0.5in",
                },
            )
        finally:
            browser.close()
    return pdf_bytes
