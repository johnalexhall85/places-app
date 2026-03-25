from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.db_fqtn import analytics_table
from app.funding_models.constants import (
    BUILD_STATUS_FAILED,
    BUILD_STATUS_RUNNING,
    BUILD_STATUS_SUCCEEDED,
    DEFAULT_CREATED_BY,
    DEFAULT_TIMEOUT_MS,
    FUNDING_MODEL_BUILDER_BASE_VIEW,
    FUNDING_PROFILE_BUILD_RUNS_TABLE,
    FUNDING_PROFILE_MODELS_TABLE,
    FUNDING_PROFILE_VERSIONS_TABLE,
    MODEL_STATUS_ARCHIVED,
    MODEL_STATUS_BUILT,
    MODEL_STATUS_DRAFT,
    MODEL_STATUS_LOCKED,
    MODEL_STATUS_PUBLISHED,
    VALIDATION_STATUS_INVALID,
    VALIDATION_STATUS_VALID,
    funding_model_field_catalog,
)
from app.funding_models.models import (
    FundingModeRegistryEntry,
    FundingProfileBuildRun,
    FundingProfileModel,
    FundingProfileVersion,
)
from app.funding_models.registry import ensure_unique_mode_key
from app.funding_models.schemas import (
    FundingModelActionRequest,
    FundingModelBuildRunResponse,
    FundingModelCloneRequest,
    FundingModelDraftPayload,
    FundingModelPreviewRequest,
    FundingModelPreviewResponse,
    FundingModelPublishRequest,
    FundingModelResponse,
    FundingModelVersionDetail,
    FundingModelVersionSummary,
    PreviewSeriesRow,
    PreviewStateRow,
)
from app.funding_models.sql import (
    compose_definition_json,
    generate_scoped_records_sql,
    generate_visual_sql,
    validate_advanced_sql,
    validate_metadata_identifiers,
    with_generated_defaults,
    preview_warning_messages,
)
from app.funding_models.summary import build_plain_language_summary


def list_models(db: Session) -> list[dict[str, Any]]:
    if not _storage_ready(db):
        return []
    rows = (
        db.query(FundingProfileModel)
        .order_by(FundingProfileModel.updated_at.desc(), FundingProfileModel.id.desc())
        .all()
    )
    return [_serialize_model(model) for model in rows]


def list_field_catalog() -> list[dict[str, Any]]:
    return funding_model_field_catalog()


def create_model(db: Session, payload: FundingModelDraftPayload) -> dict[str, Any]:
    _ensure_storage_ready(db)
    normalized = _validated_payload(db, payload)
    _ensure_unique_model_fields(db, normalized)
    generated_sql = generate_visual_sql(normalized)
    advanced_sql = validate_advanced_sql(normalized.definition.advanced_sql_override)
    summary = build_plain_language_summary(normalized)

    model = FundingProfileModel(
        display_name=normalized.display_name,
        internal_model_id=normalized.internal_model_id,
        slug=normalized.slug,
        description=normalized.description,
        chip_methodology_version=normalized.chip_methodology_version,
        funding_mode_key=normalized.funding_mode_key,
        status=MODEL_STATUS_DRAFT,
        is_system=False,
        is_user_editable=True,
        is_visible_in_funding_mode=False,
        toolbar_page_enabled=True,
        created_by=DEFAULT_CREATED_BY,
    )
    db.add(model)
    db.flush()

    version = FundingProfileVersion(
        profile_model_id=model.id,
        version_number=1,
        version_label=normalized.version_label,
        definition_json=compose_definition_json(normalized),
        generated_sql=generated_sql,
        advanced_sql_override=advanced_sql,
        plain_language_summary=summary,
        chip_state_profile_source_version=normalized.chip_state_profile_source_version,
        chip_normalization_source_version=normalized.chip_normalization_source_version,
        validation_status=VALIDATION_STATUS_VALID,
        build_status=None,
        notes=normalized.notes,
        created_by=DEFAULT_CREATED_BY,
    )
    db.add(version)
    db.flush()

    model.current_version_id = version.id
    db.commit()
    db.refresh(model)
    db.refresh(version)
    return _serialize_model(model)


def get_model(db: Session, model_id: str) -> dict[str, Any]:
    _ensure_storage_ready(db)
    model = _get_model_or_404(db, model_id)
    return _serialize_model(model)


def update_current_draft(db: Session, model_id: str, payload: FundingModelDraftPayload) -> dict[str, Any]:
    _ensure_storage_ready(db)
    model = _get_model_or_404(db, model_id)
    if model.status != MODEL_STATUS_DRAFT or model.current_version is None:
        raise HTTPException(status_code=409, detail="Only the current draft version may be edited directly.")
    normalized = _validated_payload(db, payload)
    _ensure_unique_model_fields(db, normalized, existing_model=model)

    version = model.current_version
    generated_sql = generate_visual_sql(normalized)
    advanced_sql = validate_advanced_sql(normalized.definition.advanced_sql_override)
    summary = build_plain_language_summary(normalized)

    model.display_name = normalized.display_name
    model.internal_model_id = normalized.internal_model_id
    model.slug = normalized.slug
    model.description = normalized.description
    model.chip_methodology_version = normalized.chip_methodology_version
    model.funding_mode_key = normalized.funding_mode_key
    model.updated_at = _now()
    version.version_label = normalized.version_label
    version.definition_json = compose_definition_json(normalized)
    version.generated_sql = generated_sql
    version.advanced_sql_override = advanced_sql
    version.plain_language_summary = summary
    version.chip_state_profile_source_version = normalized.chip_state_profile_source_version
    version.chip_normalization_source_version = normalized.chip_normalization_source_version
    version.validation_status = VALIDATION_STATUS_VALID
    version.notes = normalized.notes

    db.commit()
    db.refresh(model)
    return _serialize_model(model)


def create_version(db: Session, model_id: str, payload: FundingModelDraftPayload) -> dict[str, Any]:
    _ensure_storage_ready(db)
    model = _get_model_or_404(db, model_id)
    normalized = _validated_payload(db, payload)
    _ensure_unique_model_fields(db, normalized, existing_model=model)
    next_version_number = _next_version_number(db, model.id)
    generated_sql = generate_visual_sql(normalized)
    advanced_sql = validate_advanced_sql(normalized.definition.advanced_sql_override)
    summary = build_plain_language_summary(normalized)

    version = FundingProfileVersion(
        profile_model_id=model.id,
        version_number=next_version_number,
        version_label=normalized.version_label,
        definition_json=compose_definition_json(normalized),
        generated_sql=generated_sql,
        advanced_sql_override=advanced_sql,
        plain_language_summary=summary,
        chip_state_profile_source_version=normalized.chip_state_profile_source_version,
        chip_normalization_source_version=normalized.chip_normalization_source_version,
        validation_status=VALIDATION_STATUS_VALID,
        notes=normalized.notes,
        created_by=DEFAULT_CREATED_BY,
    )
    db.add(version)
    db.flush()

    model.display_name = normalized.display_name
    model.internal_model_id = normalized.internal_model_id
    model.slug = normalized.slug
    model.description = normalized.description
    model.chip_methodology_version = normalized.chip_methodology_version
    model.funding_mode_key = normalized.funding_mode_key
    model.current_version_id = version.id
    model.status = MODEL_STATUS_DRAFT
    model.is_visible_in_funding_mode = False
    model.updated_at = _now()
    db.commit()
    db.refresh(model)
    return _serialize_model(model)


def preview_definition(db: Session, payload: FundingModelPreviewRequest) -> dict[str, Any]:
    _ensure_builder_base_view_ready(db)
    normalized = _validated_payload(db, payload)
    generated_sql = generate_visual_sql(normalized)
    scoped_sql = generate_scoped_records_sql(normalized)
    summary = build_plain_language_summary(normalized)
    row_count = _scalar_int(
        db,
        f"WITH scoped AS ({scoped_sql}) SELECT COUNT(*)::integer FROM scoped",
    )
    included_count = row_count
    excluded_count = _scalar_int(
        db,
        f"SELECT GREATEST(COUNT(*) - {row_count}, 0)::integer FROM ({generated_sql}) base_records",
    )
    national_rows = db.execute(
        text(
            f"""
            WITH scoped AS (
                {scoped_sql}
            )
            SELECT
                fiscal_year,
                COALESCE(SUM(obligation_amount), 0)::numeric AS total_amount,
                COUNT(*)::integer AS row_count
            FROM scoped
            WHERE fiscal_year IS NOT NULL
            GROUP BY fiscal_year
            ORDER BY fiscal_year DESC
            """
        ),
        {},
    ).mappings().all()
    selected_fiscal_year = payload.preview_fiscal_year or normalized.definition.aggregation.default_fiscal_year
    state_rows = db.execute(
        text(
            f"""
            WITH scoped AS (
                {scoped_sql}
            )
            SELECT
                recipient_state_code AS state_code,
                MAX(recipient_state_name) AS state_name,
                COALESCE(SUM(obligation_amount), 0)::numeric AS total_amount,
                COUNT(*)::integer AS row_count
            FROM scoped
            WHERE recipient_state_code IS NOT NULL
              AND (:preview_fiscal_year IS NULL OR fiscal_year = :preview_fiscal_year)
            GROUP BY recipient_state_code
            ORDER BY total_amount DESC, recipient_state_code ASC
            LIMIT 200
            """
        ),
        {
            "preview_fiscal_year": selected_fiscal_year,
        },
    ).mappings().all()
    warnings = preview_warning_messages(normalized, row_count=row_count)
    return FundingModelPreviewResponse(
        generated_sql=generated_sql,
        plain_language_summary=summary,
        warnings=warnings,
        row_count=row_count,
        included_record_count=included_count,
        excluded_record_count=excluded_count,
        national_totals_by_fiscal_year=[
            PreviewSeriesRow(
                fiscal_year=int(row["fiscal_year"]),
                total_amount=float(row["total_amount"] or 0),
                row_count=int(row["row_count"] or 0),
            )
            for row in national_rows
        ],
        state_totals_for_fiscal_year=[
            PreviewStateRow(
                state_code=str(row["state_code"]),
                state_name=str(row.get("state_name") or "").strip() or None,
                total_amount=float(row["total_amount"] or 0),
                row_count=int(row["row_count"] or 0),
            )
            for row in state_rows
        ],
    ).model_dump(mode="python")


def preview_saved_model(
    db: Session,
    model_id: str,
    *,
    preview_fiscal_year: int | None = None,
    preview_geography_level: str = "state",
    version_number: int | None = None,
) -> dict[str, Any]:
    _ensure_storage_ready(db)
    _ensure_builder_base_view_ready(db)
    model = _get_model_or_404(db, model_id)
    version = _get_version_or_404(model, version_number)
    payload = _payload_from_version(version)
    preview_payload = FundingModelPreviewRequest(
        **payload.model_dump(mode="python"),
        preview_fiscal_year=preview_fiscal_year,
        preview_geography_level=preview_geography_level,
    )
    return preview_definition(db, preview_payload)


def lock_model(db: Session, model_id: str, request: FundingModelActionRequest) -> dict[str, Any]:
    _ensure_storage_ready(db)
    model = _get_model_or_404(db, model_id)
    version = _get_version_or_404(model, request.version_number)
    if model.current_version_id != version.id or model.status != MODEL_STATUS_DRAFT:
        raise HTTPException(status_code=409, detail="Only the current draft version can be locked.")
    payload = _payload_from_version(version)
    payload = FundingModelDraftPayload(**(payload.model_dump(mode="python") | {"status": MODEL_STATUS_LOCKED}))
    validate_metadata_identifiers(payload, require_assets=True)
    validate_advanced_sql(payload.definition.advanced_sql_override if payload.definition.advanced_sql_enabled else None)
    version.definition_json = compose_definition_json(payload)
    version.generated_sql = generate_visual_sql(payload)
    version.plain_language_summary = build_plain_language_summary(payload)
    version.validation_status = VALIDATION_STATUS_VALID
    model.status = MODEL_STATUS_LOCKED
    model.updated_at = _now()
    db.commit()
    db.refresh(model)
    return _serialize_model(model)


def clone_version(db: Session, model_id: str, request: FundingModelCloneRequest) -> dict[str, Any]:
    _ensure_storage_ready(db)
    model = _get_model_or_404(db, model_id)
    source_version = _get_version_or_404(model, request.version_number)
    source_payload = _payload_from_version(source_version)
    clone_data = source_payload.model_dump(mode="python")
    clone_data["status"] = MODEL_STATUS_DRAFT
    clone_data["version_label"] = request.version_label or source_version.version_label
    payload = FundingModelDraftPayload(**clone_data)
    return create_version(db, str(model.id), payload)


def build_model(db: Session, model_id: str, request: FundingModelActionRequest) -> dict[str, Any]:
    _ensure_storage_ready(db)
    model = _get_model_or_404(db, model_id)
    version = _get_version_or_404(model, request.version_number)
    payload = _payload_from_version(version)
    validate_metadata_identifiers(payload, require_assets=True)
    if model.current_version_id != version.id or model.status not in {MODEL_STATUS_LOCKED, MODEL_STATUS_BUILT, MODEL_STATUS_PUBLISHED}:
        raise HTTPException(status_code=409, detail="Only the current locked version may be built.")

    build_run = FundingProfileBuildRun(
        profile_version_id=version.id,
        run_type="build",
        script_name="build_funding_profile",
        started_at=_now(),
        status=BUILD_STATUS_RUNNING,
    )
    db.add(build_run)
    version.build_status = BUILD_STATUS_RUNNING
    db.flush()

    state_view_name = analytics_table(version.chip_state_profile_source_version)
    normalization_view_name = analytics_table(version.chip_normalization_source_version)
    state_totals_view = analytics_table(f"{version.chip_state_profile_source_version}_state_totals")
    national_totals_view = analytics_table(f"{version.chip_state_profile_source_version}_national_totals")
    county_totals_view = analytics_table(f"{version.chip_state_profile_source_version}_county_totals")

    try:
        scoped_sql = generate_scoped_records_sql(payload)
        generated_sql = generate_visual_sql(payload)
        db.execute(text("SET LOCAL statement_timeout = :timeout_ms"), {"timeout_ms": DEFAULT_TIMEOUT_MS})
        db.execute(text(f"CREATE OR REPLACE VIEW {state_view_name} AS {scoped_sql}"))
        db.execute(text(f"CREATE OR REPLACE VIEW {normalization_view_name} AS SELECT * FROM {state_view_name}"))
        db.execute(
            text(
                f"""
                CREATE OR REPLACE VIEW {state_totals_view} AS
                SELECT
                    fiscal_year,
                    recipient_state_code AS state_code,
                    MAX(recipient_state_name) AS state_name,
                    COALESCE(SUM(obligation_amount), 0)::numeric AS total_amount,
                    COUNT(*)::integer AS row_count
                FROM {state_view_name}
                WHERE recipient_state_code IS NOT NULL
                GROUP BY fiscal_year, recipient_state_code
                """
            )
        )
        db.execute(
            text(
                f"""
                CREATE OR REPLACE VIEW {national_totals_view} AS
                SELECT
                    fiscal_year,
                    COALESCE(SUM(obligation_amount), 0)::numeric AS total_amount,
                    COUNT(*)::integer AS row_count
                FROM {state_view_name}
                GROUP BY fiscal_year
                """
            )
        )
        db.execute(
            text(
                f"""
                CREATE OR REPLACE VIEW {county_totals_view} AS
                SELECT
                    fiscal_year,
                    recipient_county_fips AS county_fips,
                    recipient_state_code AS state_code,
                    MAX(recipient_county_name) AS county_name,
                    COALESCE(SUM(obligation_amount), 0)::numeric AS total_amount,
                    COUNT(*)::integer AS row_count
                FROM {state_view_name}
                WHERE recipient_county_fips IS NOT NULL
                GROUP BY fiscal_year, recipient_county_fips, recipient_state_code
                """
            )
        )
        version.generated_sql = generated_sql
        version.build_status = BUILD_STATUS_SUCCEEDED
        version.validation_status = VALIDATION_STATUS_VALID
        version.build_script_name = "build_funding_profile"
        build_run.status = BUILD_STATUS_SUCCEEDED
        build_run.completed_at = _now()
        build_run.output_view_name = normalization_view_name
        build_run.output_table_name = state_view_name
        build_run.log_excerpt = f"Built {state_view_name} and {normalization_view_name}"
        model.status = MODEL_STATUS_BUILT
        model.updated_at = _now()
        db.commit()
    except Exception as exc:
        db.rollback()
        model = _get_model_or_404(db, model_id)
        version = _get_version_or_404(model, request.version_number)
        build_run = FundingProfileBuildRun(
            profile_version_id=version.id,
            run_type="build",
            script_name="build_funding_profile",
            started_at=_now(),
            completed_at=_now(),
            status=BUILD_STATUS_FAILED,
            log_excerpt=str(exc)[:4000],
        )
        db.add(build_run)
        version.build_status = BUILD_STATUS_FAILED
        version.validation_status = VALIDATION_STATUS_INVALID
        model.updated_at = _now()
        db.commit()
        raise HTTPException(status_code=500, detail=f"Funding model build failed: {exc}") from exc

    db.refresh(model)
    return {
        "model": _serialize_model(model),
        "build_run": FundingModelBuildRunResponse(
            id=build_run.id,
            status=build_run.status,
            run_type=build_run.run_type,
            script_name=build_run.script_name,
            output_table_name=build_run.output_table_name,
            output_view_name=build_run.output_view_name,
            log_excerpt=build_run.log_excerpt,
        ).model_dump(mode="python"),
    }


def publish_model(db: Session, model_id: str, request: FundingModelPublishRequest) -> dict[str, Any]:
    _ensure_storage_ready(db)
    model = _get_model_or_404(db, model_id)
    version = _get_version_or_404(model, request.version_number)
    if version.build_status != BUILD_STATUS_SUCCEEDED:
        raise HTTPException(status_code=409, detail="Only built versions may be published.")
    ensure_unique_mode_key(db, model.funding_mode_key, model_id=model.id)
    existing = (
        db.query(FundingModeRegistryEntry)
        .filter(FundingModeRegistryEntry.funding_mode_key == model.funding_mode_key)
        .one_or_none()
    )
    if existing is None:
        existing = FundingModeRegistryEntry(
            funding_mode_key=model.funding_mode_key,
            label=request.label or model.display_name,
            profile_model_id=model.id,
            profile_version_id=version.id,
            map_default=bool(request.map_default),
            sort_order=request.sort_order if request.sort_order is not None else 100,
            is_active=True,
        )
        db.add(existing)
    else:
        existing.label = request.label or model.display_name
        existing.profile_model_id = model.id
        existing.profile_version_id = version.id
        existing.map_default = bool(request.map_default)
        if request.sort_order is not None:
            existing.sort_order = request.sort_order
        existing.is_active = True
        existing.updated_at = _now()
    if request.map_default:
        db.query(FundingModeRegistryEntry).filter(FundingModeRegistryEntry.id != existing.id).update(
            {"map_default": False},
            synchronize_session=False,
        )
    model.status = MODEL_STATUS_PUBLISHED
    model.is_visible_in_funding_mode = True
    model.updated_at = _now()
    db.commit()
    db.refresh(model)
    return _serialize_model(model)


def archive_model(db: Session, model_id: str) -> dict[str, Any]:
    _ensure_storage_ready(db)
    model = _get_model_or_404(db, model_id)
    db.query(FundingModeRegistryEntry).filter(FundingModeRegistryEntry.profile_model_id == model.id).update(
        {
            FundingModeRegistryEntry.is_active: False,
            FundingModeRegistryEntry.updated_at: _now(),
        },
        synchronize_session=False,
    )
    model.status = MODEL_STATUS_ARCHIVED
    model.is_visible_in_funding_mode = False
    model.updated_at = _now()
    db.commit()
    db.refresh(model)
    return _serialize_model(model)


def _validated_payload(db: Session, payload: FundingModelDraftPayload) -> FundingModelDraftPayload:
    normalized = with_generated_defaults(payload)
    validate_metadata_identifiers(normalized, require_assets=False)
    validate_advanced_sql(normalized.definition.advanced_sql_override if normalized.definition.advanced_sql_enabled else None)
    return normalized


def _storage_ready(db: Session) -> bool:
    required = (
        FUNDING_PROFILE_MODELS_TABLE,
        FUNDING_PROFILE_VERSIONS_TABLE,
        FUNDING_PROFILE_BUILD_RUNS_TABLE,
    )
    return all(_relation_exists(db, relation_name) for relation_name in required)


def _ensure_storage_ready(db: Session) -> None:
    if _storage_ready(db):
        return
    raise HTTPException(
        status_code=503,
        detail="Funding model tables are missing. Run `alembic upgrade head` before using the Funding Model Builder.",
    )


def _ensure_builder_base_view_ready(db: Session) -> None:
    if _relation_exists(db, FUNDING_MODEL_BUILDER_BASE_VIEW):
        return
    raise HTTPException(
        status_code=503,
        detail="Funding Model Builder base view is missing. Run `alembic upgrade head` before previewing funding models.",
    )


def _relation_exists(db: Session, relation_name: str) -> bool:
    row = db.execute(
        text("SELECT to_regclass(:name) AS exists"),
        {"name": relation_name},
    ).mappings().one()
    return row.get("exists") is not None


def _ensure_unique_model_fields(
    db: Session,
    payload: FundingModelDraftPayload,
    *,
    existing_model: FundingProfileModel | None = None,
) -> None:
    internal_query = db.query(FundingProfileModel).filter(FundingProfileModel.internal_model_id == payload.internal_model_id)
    slug_query = db.query(FundingProfileModel).filter(FundingProfileModel.slug == payload.slug)
    mode_query = db.query(FundingProfileModel).filter(FundingProfileModel.funding_mode_key == payload.funding_mode_key)
    if existing_model is not None:
        internal_query = internal_query.filter(FundingProfileModel.id != existing_model.id)
        slug_query = slug_query.filter(FundingProfileModel.id != existing_model.id)
        mode_query = mode_query.filter(FundingProfileModel.id != existing_model.id)
    if internal_query.first() is not None:
        raise HTTPException(status_code=409, detail="internal_model_id already exists.")
    if slug_query.first() is not None:
        raise HTTPException(status_code=409, detail="slug already exists.")
    if mode_query.first() is not None:
        raise HTTPException(status_code=409, detail="funding_mode_key already exists.")


def _get_model_or_404(db: Session, model_id: str) -> FundingProfileModel:
    token = str(model_id or "").strip()
    query = db.query(FundingProfileModel)
    model = None
    if token.isdigit():
        model = query.filter(FundingProfileModel.id == int(token)).one_or_none()
    if model is None:
        model = (
            query.filter(
                (FundingProfileModel.internal_model_id == token)
                | (FundingProfileModel.slug == token)
            )
            .one_or_none()
        )
    if model is None:
        raise HTTPException(status_code=404, detail="Funding model not found.")
    return model


def _get_version_or_404(model: FundingProfileModel, version_number: int | None) -> FundingProfileVersion:
    if version_number is None:
        if model.current_version is None:
            raise HTTPException(status_code=404, detail="Funding model has no current version.")
        return model.current_version
    for version in model.versions:
        if version.version_number == version_number:
            return version
    raise HTTPException(status_code=404, detail="Funding model version not found.")


def _payload_from_version(version: FundingProfileVersion) -> FundingModelDraftPayload:
    data = version.definition_json or {}
    definition = data.get("definition") or {}
    return FundingModelDraftPayload(
        display_name=data.get("display_name") or "",
        internal_model_id=data.get("internal_model_id") or "",
        chip_methodology_version=data.get("chip_methodology_version") or "",
        funding_mode_key=data.get("funding_mode_key"),
        slug=data.get("slug"),
        description=data.get("description"),
        chip_state_profile_source_version=data.get("chip_state_profile_source_version"),
        chip_normalization_source_version=data.get("chip_normalization_source_version"),
        status=data.get("status") or MODEL_STATUS_DRAFT,
        version_label=version.version_label,
        notes=version.notes,
        definition=definition,
    )


def _next_version_number(db: Session, model_id: int) -> int:
    row = (
        db.query(func.max(FundingProfileVersion.version_number))
        .filter(FundingProfileVersion.profile_model_id == model_id)
        .scalar()
    )
    return int(row or 0) + 1


def _serialize_model(model: FundingProfileModel) -> dict[str, Any]:
    current_version = model.current_version
    return FundingModelResponse(
        id=model.id,
        display_name=model.display_name,
        internal_model_id=model.internal_model_id,
        slug=model.slug,
        description=model.description,
        chip_methodology_version=model.chip_methodology_version,
        funding_mode_key=model.funding_mode_key,
        status=model.status,
        is_system=bool(model.is_system),
        is_user_editable=bool(model.is_user_editable),
        is_visible_in_funding_mode=bool(model.is_visible_in_funding_mode),
        toolbar_page_enabled=bool(model.toolbar_page_enabled),
        created_by=model.created_by,
        created_at=_iso(model.created_at),
        updated_at=_iso(model.updated_at),
        current_version_id=model.current_version_id,
        current_version=_serialize_version_detail(model, current_version) if current_version else None,
        versions=[_serialize_version_summary(model, version) for version in model.versions],
    ).model_dump(mode="python")


def _serialize_version_summary(model: FundingProfileModel, version: FundingProfileVersion) -> FundingModelVersionSummary:
    return FundingModelVersionSummary(
        id=version.id,
        version_number=version.version_number,
        version_label=version.version_label,
        status=_resolve_version_status(model, version),
        build_status=version.build_status,
        validation_status=version.validation_status,
        plain_language_summary=version.plain_language_summary,
        chip_state_profile_source_version=version.chip_state_profile_source_version,
        chip_normalization_source_version=version.chip_normalization_source_version,
        created_by=version.created_by,
        created_at=_iso(version.created_at),
    )


def _serialize_version_detail(model: FundingProfileModel, version: FundingProfileVersion) -> FundingModelVersionDetail:
    summary = _serialize_version_summary(model, version)
    return FundingModelVersionDetail(
        **summary.model_dump(mode="python"),
        definition_json=version.definition_json or {},
        generated_sql=version.generated_sql,
        advanced_sql_override=version.advanced_sql_override,
        notes=version.notes,
    )


def _resolve_version_status(model: FundingProfileModel, version: FundingProfileVersion) -> str:
    if model.current_version_id == version.id:
        return model.status
    if version.build_status == BUILD_STATUS_SUCCEEDED:
        return MODEL_STATUS_BUILT
    status = str((version.definition_json or {}).get("status") or MODEL_STATUS_DRAFT).strip().lower()
    return status or MODEL_STATUS_DRAFT


def _scalar_int(db: Session, sql: str) -> int:
    row = db.execute(text(sql)).scalar()
    return int(row or 0)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
