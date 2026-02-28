from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.services.profile_builder import ProfileBuildError, build_profile
from app.services.profile_charts import generate_profile_charts
from app.services.profile_pdf import (
    PDFTemplate,
    pdf_asset_name,
    pdf_download_filename,
    pdf_storage_filename,
    render_profile_pdf,
)

router = APIRouter(tags=["profiles"])

APP_ROOT = Path(__file__).resolve().parents[1]
PROFILES_ROOT = APP_ROOT / "data" / "profiles"


class PlacesSelection(BaseModel):
    year: int
    measure_id: str = Field(min_length=1)
    data_value_type_id: str = Field(default="CrdPrv", min_length=1)


class AcsNmfSelection(BaseModel):
    year_window: str | None = None
    data_value_type_id: str = Field(default="Percent", min_length=1)


class ProfileGenerateRequest(BaseModel):
    geography: Literal["county", "tract"]
    location_id: str = Field(min_length=1)
    places: PlacesSelection
    acs_nmf: AcsNmfSelection = Field(default_factory=AcsNmfSelection)
    include_charts: bool = True
    include_full_narrative: bool = True


def _request_signature(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(serialized.encode("utf-8")).hexdigest()


def _asset_map_for_profile(
    db: Session,
    *,
    profile_id: str,
) -> dict[str, models.ProfileAsset]:
    rows = (
        db.query(models.ProfileAsset)
        .filter(models.ProfileAsset.profile_id == profile_id)
        .all()
    )
    return {row.asset_name: row for row in rows}


def _upsert_asset(
    db: Session,
    *,
    profile_id: str,
    asset_name: str,
    mime_type: str,
    asset_path: str,
) -> None:
    existing = (
        db.query(models.ProfileAsset)
        .filter(
            models.ProfileAsset.profile_id == profile_id,
            models.ProfileAsset.asset_name == asset_name,
        )
        .one_or_none()
    )
    if existing is None:
        db.add(
            models.ProfileAsset(
                profile_id=profile_id,
                asset_name=asset_name,
                mime_type=mime_type,
                asset_path=asset_path,
            )
        )
        return
    existing.mime_type = mime_type
    existing.asset_path = asset_path


def _profile_response_payload(
    profile: models.Profile,
    *,
    include_profile_json: bool,
) -> dict[str, Any]:
    payload = profile.payload_json if isinstance(profile.payload_json, dict) else {}
    narrative = payload.get("narrative") if isinstance(payload.get("narrative"), dict) else {}
    summary_text = str(narrative.get("summary_text") or "Summary unavailable.")
    response_payload = {
        "profile_id": str(profile.id),
        "summary_text": summary_text,
    }
    if include_profile_json:
        response_payload["profile_json"] = payload
    return response_payload


def _ensure_charts(
    db: Session,
    *,
    profile: models.Profile,
    chart_inputs: dict[str, Any] | None,
) -> None:
    if chart_inputs is None:
        return
    chart_assets = generate_profile_charts(
        profile_id=str(profile.id),
        profile_json=profile.payload_json,
        chart_inputs=chart_inputs,
        profiles_root=PROFILES_ROOT,
    )
    charts_payload = {}
    for chart_name, asset in chart_assets.items():
        _upsert_asset(
            db,
            profile_id=str(profile.id),
            asset_name=chart_name,
            mime_type=asset["mime_type"],
            asset_path=asset["path"],
        )
        charts_payload[chart_name] = {
            "url": f"/profiles/{profile.id}/charts/{chart_name}.png",
            "mime_type": asset["mime_type"],
        }
    payload = profile.payload_json if isinstance(profile.payload_json, dict) else {}
    payload["charts"] = charts_payload
    profile.payload_json = payload


@router.post("/profiles/generate")
def generate_profile(
    body: ProfileGenerateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    signature_payload = {
        "geography": body.geography,
        "location_id": body.location_id.strip(),
        "places": body.places.model_dump(),
        "acs_nmf": body.acs_nmf.model_dump(),
        "include_full_narrative": body.include_full_narrative,
    }
    signature = _request_signature(signature_payload)

    existing_profile = (
        db.query(models.Profile)
        .filter(models.Profile.request_signature == signature)
        .one_or_none()
    )

    if existing_profile is not None:
        if body.include_charts:
            existing_assets = _asset_map_for_profile(db, profile_id=str(existing_profile.id))
            has_all_charts = all(
                name in existing_assets and Path(existing_assets[name].asset_path).exists()
                for name in ("bars_comparison", "us_distribution", "scatter_top_correlate")
            )
            if not has_all_charts:
                try:
                    rebuilt = build_profile(
                        db,
                        geography=body.geography,
                        location_id=body.location_id.strip(),
                        places_year=body.places.year,
                        places_measure_id=body.places.measure_id.strip(),
                        places_data_value_type_id=body.places.data_value_type_id.strip(),
                        acs_year_window=body.acs_nmf.year_window,
                        acs_data_value_type_id=body.acs_nmf.data_value_type_id.strip(),
                        include_full_narrative=body.include_full_narrative,
                    )
                except ProfileBuildError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                _ensure_charts(
                    db,
                    profile=existing_profile,
                    chart_inputs=rebuilt.chart_inputs,
                )
                db.commit()
        return _profile_response_payload(
            existing_profile,
            include_profile_json=body.include_full_narrative,
        )

    try:
        build_result = build_profile(
            db,
            geography=body.geography,
            location_id=body.location_id.strip(),
            places_year=body.places.year,
            places_measure_id=body.places.measure_id.strip(),
            places_data_value_type_id=body.places.data_value_type_id.strip(),
            acs_year_window=body.acs_nmf.year_window,
            acs_data_value_type_id=body.acs_nmf.data_value_type_id.strip(),
            include_full_narrative=body.include_full_narrative,
        )
    except ProfileBuildError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    profile_id = str(uuid4())
    payload_json = build_result.profile_json
    payload_json["profile_id"] = profile_id

    profile = models.Profile(
        id=profile_id,
        geography=body.geography,
        location_id=body.location_id.strip(),
        request_signature=signature,
        payload_json=payload_json,
    )
    db.add(profile)
    db.flush()

    if body.include_charts:
        _ensure_charts(db, profile=profile, chart_inputs=build_result.chart_inputs)

    db.commit()
    db.refresh(profile)
    return _profile_response_payload(
        profile,
        include_profile_json=body.include_full_narrative,
    )


@router.get("/profiles/{profile_id}/charts/{chart_name}.png")
def get_profile_chart(
    profile_id: str,
    chart_name: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    profile = db.query(models.Profile).filter(models.Profile.id == profile_id).one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found.")

    asset = (
        db.query(models.ProfileAsset)
        .filter(
            models.ProfileAsset.profile_id == profile_id,
            models.ProfileAsset.asset_name == chart_name,
            models.ProfileAsset.mime_type == "image/png",
        )
        .one_or_none()
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Chart not found.")

    file_path = Path(asset.asset_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Chart file is missing.")

    return FileResponse(path=file_path, media_type="image/png")


@router.get("/profiles/{profile_id}.pdf")
def get_profile_pdf(
    profile_id: str,
    template: PDFTemplate = Query(default="full"),
    db: Session = Depends(get_db),
) -> Response:
    profile = db.query(models.Profile).filter(models.Profile.id == profile_id).one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found.")

    selected_asset_name = pdf_asset_name(template)
    download_filename = pdf_download_filename(profile_id, template)
    pdf_asset = (
        db.query(models.ProfileAsset)
        .filter(
            models.ProfileAsset.profile_id == profile_id,
            models.ProfileAsset.asset_name == selected_asset_name,
            models.ProfileAsset.mime_type == "application/pdf",
        )
        .one_or_none()
    )
    if pdf_asset is not None:
        pdf_path = Path(pdf_asset.asset_path)
        if pdf_path.exists():
            return FileResponse(
                path=pdf_path,
                media_type="application/pdf",
                filename=download_filename,
            )

    image_assets = (
        db.query(models.ProfileAsset)
        .filter(
            models.ProfileAsset.profile_id == profile_id,
            models.ProfileAsset.mime_type == "image/png",
        )
        .all()
    )
    chart_paths = {
        asset.asset_name: asset.asset_path
        for asset in image_assets
        if asset.asset_name and asset.asset_path
    }

    payload = profile.payload_json if isinstance(profile.payload_json, dict) else {}
    pdf_bytes = render_profile_pdf(
        profile_json=payload,
        chart_paths=chart_paths,
        template=template,
    )

    profile_dir = PROFILES_ROOT / profile_id
    profile_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = profile_dir / pdf_storage_filename(template)
    pdf_path.write_bytes(pdf_bytes)

    _upsert_asset(
        db,
        profile_id=profile_id,
        asset_name=selected_asset_name,
        mime_type="application/pdf",
        asset_path=str(pdf_path),
    )
    db.commit()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{download_filename}"'},
    )


@router.get("/profiles/{profile_id}")
def get_profile(profile_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    profile = db.query(models.Profile).filter(models.Profile.id == profile_id).one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found.")
    payload = profile.payload_json if isinstance(profile.payload_json, dict) else {}
    return payload
