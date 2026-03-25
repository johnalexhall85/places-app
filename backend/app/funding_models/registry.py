from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload

from app.funding_models.constants import (
    BUILT_IN_FUNDING_MODES,
    FUNDING_MODE_REGISTRY_TABLE,
)
from app.funding_models.models import FundingModeRegistryEntry
from app.funding_models.schemas import FundingModeOption


def registry_tables_available(db: Session) -> bool:
    if db is None:
        return False
    row = db.execute(
        text("SELECT to_regclass(:name) AS exists"),
        {"name": FUNDING_MODE_REGISTRY_TABLE},
    ).mappings().one()
    return row.get("exists") is not None


def list_funding_mode_options(db: Session) -> list[dict[str, Any]]:
    built_ins = [FundingModeOption(**row).model_dump(mode="python") for row in BUILT_IN_FUNDING_MODES]
    if not registry_tables_available(db):
        return built_ins

    rows = (
        db.query(FundingModeRegistryEntry)
        .options(
            joinedload(FundingModeRegistryEntry.profile_model),
            joinedload(FundingModeRegistryEntry.profile_version),
        )
        .filter(FundingModeRegistryEntry.is_active.is_(True))
        .order_by(FundingModeRegistryEntry.sort_order.asc(), FundingModeRegistryEntry.label.asc())
        .all()
    )
    dynamic_rows = [
        FundingModeOption(
            value=row.funding_mode_key,
            label=row.label,
            system=False,
            is_active=bool(row.is_active),
            sort_order=row.sort_order,
        ).model_dump(mode="python")
        for row in rows
    ]
    return built_ins + dynamic_rows


def is_custom_funding_mode(db: Session, funding_mode: str | None) -> bool:
    token = str(funding_mode or "").strip().lower()
    if not token or not registry_tables_available(db):
        return False
    row = (
        db.query(FundingModeRegistryEntry.id)
        .filter(
            FundingModeRegistryEntry.funding_mode_key == token,
            FundingModeRegistryEntry.is_active.is_(True),
        )
        .first()
    )
    return row is not None


def resolve_custom_mode(db: Session, funding_mode: str) -> FundingModeRegistryEntry | None:
    token = str(funding_mode or "").strip().lower()
    if not token or not registry_tables_available(db):
        return None
    return (
        db.query(FundingModeRegistryEntry)
        .options(
            joinedload(FundingModeRegistryEntry.profile_model),
            joinedload(FundingModeRegistryEntry.profile_version),
        )
        .filter(
            FundingModeRegistryEntry.funding_mode_key == token,
            FundingModeRegistryEntry.is_active.is_(True),
        )
        .one_or_none()
    )


def ensure_unique_mode_key(db: Session, funding_mode_key: str, *, model_id: int | None = None) -> None:
    if not registry_tables_available(db):
        return
    query = (
        db.query(FundingModeRegistryEntry.id)
        .filter(FundingModeRegistryEntry.funding_mode_key == str(funding_mode_key).strip().lower())
    )
    if model_id is not None:
        query = query.filter(FundingModeRegistryEntry.profile_model_id != model_id)
    if query.first() is not None:
        raise ValueError("funding_mode_key is already registered.")


def published_registry_metadata(db: Session, funding_mode: str | None) -> dict[str, Any] | None:
    row = resolve_custom_mode(db, str(funding_mode or "").strip().lower())
    if row is None:
        return None
    return {
        "funding_mode_key": row.funding_mode_key,
        "label": row.label,
        "profile_model_id": row.profile_model_id,
        "profile_version_id": row.profile_version_id,
        "internal_model_id": row.profile_model.internal_model_id if row.profile_model else None,
        "display_name": row.profile_model.display_name if row.profile_model else row.label,
        "chip_methodology_version": row.profile_model.chip_methodology_version if row.profile_model else None,
        "chip_state_profile_source_version": (
            row.profile_version.chip_state_profile_source_version if row.profile_version else None
        ),
        "chip_normalization_source_version": (
            row.profile_version.chip_normalization_source_version if row.profile_version else None
        ),
    }
