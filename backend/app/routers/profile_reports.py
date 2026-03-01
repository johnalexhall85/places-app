from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.profile_bundle import ProfileBundleError, build_profile_bundle
from app.services.profile_pdf_playwright import (
    build_profile_pdf_cache_key,
    cleanup_stale_profile_pdfs,
    profile_pdf_cache_path,
    render_route_pdf_via_playwright,
)

router = APIRouter(tags=["profiles"])

_COUNTY_FIPS_RE = re.compile(r"^\d{5}$")
_TRACT_GEOID_RE = re.compile(r"^\d{11}$")


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_county_fips(value: str) -> str | None:
    digits = re.sub(r"[^0-9]", "", _as_text(value))
    if len(digits) == 5:
        return digits
    if digits and len(digits) < 5:
        return digits.zfill(5)
    return None


def _normalize_tract_geoid(value: str) -> str | None:
    digits = re.sub(r"[^0-9]", "", _as_text(value))
    if len(digits) == 11:
        return digits
    if len(digits) > 11:
        return digits[-11:]
    return None


def _bundle_or_http_error(
    db: Session,
    *,
    geography: str,
    identifier: str,
) -> dict[str, Any]:
    try:
        return build_profile_bundle(
            db,
            geography=geography,  # type: ignore[arg-type]
            identifier=identifier,
        )
    except ProfileBundleError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc


def _file_response(pdf_path: Path, *, download_name: str) -> FileResponse:
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=download_name,
    )


@router.get("/api/profiles/county/{county_fips}")
def get_county_profile_bundle(
    county_fips: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    normalized_fips = _normalize_county_fips(county_fips)
    if normalized_fips is None or not _COUNTY_FIPS_RE.fullmatch(normalized_fips):
        raise HTTPException(status_code=400, detail="county_fips must be a valid 5-digit county FIPS.")
    return _bundle_or_http_error(
        db,
        geography="county",
        identifier=normalized_fips,
    )


@router.get("/api/profiles/tract/{tract_geoid}")
def get_tract_profile_bundle(
    tract_geoid: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    normalized_geoid = _normalize_tract_geoid(tract_geoid)
    if normalized_geoid is None or not _TRACT_GEOID_RE.fullmatch(normalized_geoid):
        raise HTTPException(status_code=400, detail="tract_geoid must be a valid 11-digit tract GEOID.")
    return _bundle_or_http_error(
        db,
        geography="tract",
        identifier=normalized_geoid,
    )


@router.get("/api/profiles/county/{county_fips}/pdf")
def get_county_profile_pdf(
    county_fips: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    normalized_fips = _normalize_county_fips(county_fips)
    if normalized_fips is None or not _COUNTY_FIPS_RE.fullmatch(normalized_fips):
        raise HTTPException(status_code=400, detail="county_fips must be a valid 5-digit county FIPS.")

    bundle = _bundle_or_http_error(
        db,
        geography="county",
        identifier=normalized_fips,
    )
    as_of = bundle.get("as_of") if isinstance(bundle.get("as_of"), dict) else {}
    cache_key = build_profile_pdf_cache_key(
        geography="county",
        geo_id=normalized_fips,
        as_of=as_of,
    )
    pdf_path = profile_pdf_cache_path(
        geography="county",
        geo_id=normalized_fips,
        cache_key=cache_key,
    )
    if pdf_path.exists():
        cleanup_stale_profile_pdfs(geography="county", geo_id=normalized_fips, keep_path=pdf_path)
        return _file_response(pdf_path, download_name=f"county-{normalized_fips}-community-health-profile.pdf")

    try:
        pdf_bytes = render_route_pdf_via_playwright(route_path=f"/profile/county/{normalized_fips}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to render county profile PDF: {exc}") from exc

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(pdf_bytes)
    cleanup_stale_profile_pdfs(geography="county", geo_id=normalized_fips, keep_path=pdf_path)
    return _file_response(pdf_path, download_name=f"county-{normalized_fips}-community-health-profile.pdf")


@router.get("/api/profiles/tract/{tract_geoid}/pdf")
def get_tract_profile_pdf(
    tract_geoid: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    normalized_geoid = _normalize_tract_geoid(tract_geoid)
    if normalized_geoid is None or not _TRACT_GEOID_RE.fullmatch(normalized_geoid):
        raise HTTPException(status_code=400, detail="tract_geoid must be a valid 11-digit tract GEOID.")

    bundle = _bundle_or_http_error(
        db,
        geography="tract",
        identifier=normalized_geoid,
    )
    as_of = bundle.get("as_of") if isinstance(bundle.get("as_of"), dict) else {}
    cache_key = build_profile_pdf_cache_key(
        geography="tract",
        geo_id=normalized_geoid,
        as_of=as_of,
    )
    pdf_path = profile_pdf_cache_path(
        geography="tract",
        geo_id=normalized_geoid,
        cache_key=cache_key,
    )
    if pdf_path.exists():
        cleanup_stale_profile_pdfs(geography="tract", geo_id=normalized_geoid, keep_path=pdf_path)
        return _file_response(pdf_path, download_name=f"tract-{normalized_geoid}-community-health-profile.pdf")

    try:
        pdf_bytes = render_route_pdf_via_playwright(route_path=f"/profile/tract/{normalized_geoid}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to render tract profile PDF: {exc}") from exc

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(pdf_bytes)
    cleanup_stale_profile_pdfs(geography="tract", geo_id=normalized_geoid, keep_path=pdf_path)
    return _file_response(pdf_path, download_name=f"tract-{normalized_geoid}-community-health-profile.pdf")
