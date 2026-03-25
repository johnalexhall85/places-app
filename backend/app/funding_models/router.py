from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.funding_models.permissions import ensure_funding_model_builder_access
from app.funding_models.registry import list_funding_mode_options
from app.funding_models.schemas import (
    FundingModelActionRequest,
    FundingModelCloneRequest,
    FundingModelDraftPayload,
    FundingModelPreviewRequest,
    FundingModelPublishRequest,
    FundingModelSavedPreviewRequest,
)
from app.funding_models import service

router = APIRouter(tags=["funding-model-builder"])


def _guard_access() -> None:
    try:
        ensure_funding_model_builder_access()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/api/funding-models")
def get_funding_models(db: Session = Depends(get_db)):
    _guard_access()
    return service.list_models(db)


@router.get("/api/funding-models/field-catalog")
def get_funding_model_field_catalog():
    _guard_access()
    return {
        "items": service.list_field_catalog(),
    }


@router.post("/api/funding-models")
def create_funding_model(body: FundingModelDraftPayload, db: Session = Depends(get_db)):
    _guard_access()
    return service.create_model(db, body)


@router.post("/api/funding-models/preview")
def preview_funding_model(body: FundingModelPreviewRequest, db: Session = Depends(get_db)):
    _guard_access()
    return service.preview_definition(db, body)


@router.get("/api/funding-models/{model_id}")
def get_funding_model(model_id: str, db: Session = Depends(get_db)):
    _guard_access()
    return service.get_model(db, model_id)


@router.put("/api/funding-models/{model_id}")
def update_funding_model(model_id: str, body: FundingModelDraftPayload, db: Session = Depends(get_db)):
    _guard_access()
    return service.update_current_draft(db, model_id, body)


@router.post("/api/funding-models/{model_id}/versions")
def create_funding_model_version(model_id: str, body: FundingModelDraftPayload, db: Session = Depends(get_db)):
    _guard_access()
    return service.create_version(db, model_id, body)


@router.post("/api/funding-models/{model_id}/preview")
def preview_saved_funding_model(model_id: str, body: FundingModelSavedPreviewRequest, db: Session = Depends(get_db)):
    _guard_access()
    return service.preview_saved_model(
        db,
        model_id,
        preview_fiscal_year=body.preview_fiscal_year,
        preview_geography_level=body.preview_geography_level,
        version_number=body.version_number,
    )


@router.post("/api/funding-models/{model_id}/lock")
def lock_funding_model(model_id: str, body: FundingModelActionRequest, db: Session = Depends(get_db)):
    _guard_access()
    return service.lock_model(db, model_id, body)


@router.post("/api/funding-models/{model_id}/build")
def build_funding_model(model_id: str, body: FundingModelActionRequest, db: Session = Depends(get_db)):
    _guard_access()
    return service.build_model(db, model_id, body)


@router.post("/api/funding-models/{model_id}/publish")
def publish_funding_model(model_id: str, body: FundingModelPublishRequest, db: Session = Depends(get_db)):
    _guard_access()
    return service.publish_model(db, model_id, body)


@router.post("/api/funding-models/{model_id}/clone")
def clone_funding_model(model_id: str, body: FundingModelCloneRequest, db: Session = Depends(get_db)):
    _guard_access()
    return service.clone_version(db, model_id, body)


@router.post("/api/funding-models/{model_id}/archive")
def archive_funding_model(model_id: str, db: Session = Depends(get_db)):
    _guard_access()
    return service.archive_model(db, model_id)


@router.get("/api/funding-modes")
def get_funding_modes(db: Session = Depends(get_db)):
    return {
        "items": list_funding_mode_options(db),
    }
