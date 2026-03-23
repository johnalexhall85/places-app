from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db import DEFAULT_DB_URL
from app.db_fqtn import analytics_table, cdc_funding_table, cdc_profiles_table, recon_table, taggs_table
from app.recon.funding_streams import (
    ESTIMATED_FISCAL_YEARS,
    FUNDING_STREAM_LOGIC_VERSION,
    FUNDING_STREAM_REGULAR,
    METHODOLOGY_VERSION,
    SOURCE_TAGGS,
    SOURCE_USASPENDING,
    TRAINING_FISCAL_YEARS,
    build_major_difference_drivers,
    classify_taggs_record,
    classify_usaspending_record,
    load_rule_payloads,
)

NORMALIZED_AMOUNT_TYPE_OBSERVED = "observed_cdc_profile_aligned"
NORMALIZED_AMOUNT_TYPE_ESTIMATED = "estimated_cdc_profile_aligned"

CDC_PROFILE_TOTALS_TABLE = cdc_profiles_table("state_year_totals")
CALIBRATION_TABLE = recon_table("cdc_profile_calibration")
RULES_TABLE = recon_table("normalization_rules_by_year")
NORMALIZED_TABLE = recon_table("normalized_state_funding")
V11_EMERGENCY_NORMALIZED_TABLE = analytics_table("chip_normalized_state_funding_v11_ec")
METHODOLOGY_LOG_TABLE = recon_table("normalization_methodology_log")
DEFC_RULES_TABLE = recon_table("defc_classification_rules")
APPROPRIATION_RULES_TABLE = recon_table("appropriation_type_rules")
FEDERAL_ACCOUNT_RULES_TABLE = recon_table("federal_account_inclusion_rules")
PROFILE_SCOPE_RULES_TABLE = recon_table("cdc_profile_scope_rules")
USASPENDING_STREAMS_TABLE = recon_table("usaspending_funding_streams")
TAGGS_STREAMS_TABLE = recon_table("taggs_funding_streams")

TAGGS_AWARD_SUMMARY_TABLE = taggs_table("award_funding_summary")
TAGGS_CAN_CLASSIFICATION_TABLE = taggs_table("can_classification")
CDC_PRIME_AWARDS_TABLE = cdc_funding_table("prime_awards")
CDC_PRIME_TRANSACTIONS_TABLE = cdc_funding_table("prime_transactions")
RECON_SCHEMA = "recon"

NORMALIZATION_LOOKUP_VARIANT_LEGACY_V1 = "legacy_v1"
NORMALIZATION_LOOKUP_VARIANT_V11_EMERGENCY = "v1_1_emergency_classification"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild CDC Funding Profile normalization and reconciliation tables.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or the local development DSN).",
    )
    parser.add_argument(
        "--truncate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Truncate reconciliation tables before writing (default: true).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build reconciliation payloads without writing to the database.",
    )
    return parser.parse_args()


def _table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(
        text("SELECT to_regclass(:name) AS exists"),
        {"name": table_name},
    ).mappings().one()
    return row["exists"] is not None


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    if "." not in table_name:
        return False
    schema_name, raw_table_name = table_name.split(".", 1)
    result = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = :schema_name
                  AND table_name = :table_name
                  AND column_name = :column_name
            ) AS exists
            """
        ),
        {
            "schema_name": schema_name,
            "table_name": raw_table_name,
            "column_name": column_name,
        },
    ).mappings()
    row = result.one() if hasattr(result, "one") else result.all()[0]
    return bool(row.get("exists"))


def _ensure_normalization_tables(db: Session, *, require_calibration: bool = False) -> None:
    required = [NORMALIZED_TABLE]
    if require_calibration:
        required.append(CALIBRATION_TABLE)
    missing = [table_name for table_name in required if not _table_exists(db, table_name)]
    if missing:
        raise HTTPException(
            status_code=503,
            detail=(
                "Required normalization tables are missing: "
                + ", ".join(missing)
                + ". Run migrations and the funding normalization rebuild."
            ),
        )


def _as_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def normalization_status_label(normalized_amount_type: str | None) -> str | None:
    token = str(normalized_amount_type or "").strip().lower()
    if token == NORMALIZED_AMOUNT_TYPE_OBSERVED:
        return "Profile-aligned"
    if token == NORMALIZED_AMOUNT_TYPE_ESTIMATED:
        return "Profile-aligned estimate"
    if token == "state_profile_v11_emergency_classification_aligned":
        return "State-profile aligned v1.1"
    return None


def build_normalization_note(
    *,
    fiscal_year: int,
    normalization_applied: bool,
    reason: str | None = None,
) -> str | None:
    if not normalization_applied:
        return reason
    parts = [
        "Reconstructed from public federal data using deterministic funding-scope classification and profile-scope rules benchmarked against CDC Funding Profiles."
    ]
    parts.append(
        "The normalized view centers core public health funding, treats emergency public health funding conditionally, excludes Medicaid-like federal health financing transfers from the core CDC public health total, and keeps other public health, biomedical research, and international health assistance outside the core CDC map."
    )
    if fiscal_year in ESTIMATED_FISCAL_YEARS:
        parts.append(
            "No official CDC Funding Profiles total exists for this year, so later-year values remain profile-aligned estimates using the FY2020-FY2023 profile-scope calibration rules."
        )
    else:
        parts.append(
            "Observed FY2020-FY2023 CDC Funding Profiles are calibration references only; normalized values remain reconstructed totals, not copied CDC profile amounts."
        )
    if reason:
        parts.append(reason)
    return " ".join(parts)


def taggs_normalization_compatibility(
    *,
    metric: str,
    program_office: str | None,
    aln: str | None,
    can_code: str | None,
    funding_stream: str | None,
) -> tuple[bool, str | None]:
    if metric not in {"total_funding", "funding_per_capita"}:
        return (
            False,
            "Normalization is available for TAGGS funding amount metrics only.",
        )
    if any(str(value or "").strip() for value in (program_office, aln, can_code, funding_stream)):
        return (
            False,
            "Normalization is calibrated to statewide overall TAGGS totals and is not applied to filtered TAGGS subsets.",
        )
    return True, None


def usaspending_normalization_compatibility(
    *,
    basis: str,
    metric: str,
    funding_geography_mode: str,
    appropriation_type: str,
    assistance_type: str | None,
    awarding_office: str | None,
    funding_office: str | None,
    center: str | None,
) -> tuple[bool, str | None]:
    if basis != "prime":
        return (
            False,
            "Normalization is currently available for USA Spending prime-award obligations only.",
        )
    if metric != "fy_obligated":
        return (
            False,
            "Normalization is currently available for the Fiscal Year Obligated metric only.",
        )
    if funding_geography_mode != "recipient_location":
        return (
            False,
            "Normalization is aligned to recipient-address geography and is not applied in estimated statewide-allocation mode.",
        )
    if appropriation_type != "all":
        return (
            False,
            "Normalization is calibrated to all-funding state totals and is not applied to appropriation-type subsets.",
        )
    if any(str(value or "").strip() for value in (assistance_type, awarding_office, funding_office, center)):
        return (
            False,
            "Normalization is calibrated to statewide overall USA Spending totals and is not applied to filtered program subsets.",
        )
    return True, None


def fetch_state_normalization_lookup(
    db: Session,
    *,
    source_system: str,
    fiscal_year: int,
    lookup_variant: str = NORMALIZATION_LOOKUP_VARIANT_LEGACY_V1,
) -> dict[str, dict[str, Any]]:
    variant = str(lookup_variant or NORMALIZATION_LOOKUP_VARIANT_LEGACY_V1).strip().lower()
    if variant == NORMALIZATION_LOOKUP_VARIANT_V11_EMERGENCY:
        return _fetch_v11_emergency_state_normalization_lookup(
            db,
            source_system=source_system,
            fiscal_year=fiscal_year,
        )
    return _fetch_legacy_state_normalization_lookup(
        db,
        source_system=source_system,
        fiscal_year=fiscal_year,
    )


def _fetch_legacy_state_normalization_lookup(
    db: Session,
    *,
    source_system: str,
    fiscal_year: int,
) -> dict[str, dict[str, Any]]:
    _ensure_normalization_tables(db)
    normalization_method_expr = (
        "normalization_method"
        if _column_exists(db, NORMALIZED_TABLE, "normalization_method")
        else "NULL::text AS normalization_method"
    )
    funding_stream_logic_expr = (
        "funding_stream_logic_version"
        if _column_exists(db, NORMALIZED_TABLE, "funding_stream_logic_version")
        else "NULL::text AS funding_stream_logic_version"
    )
    cdc_profile_reference_expr = (
        "cdc_profile_reference_amount"
        if _column_exists(db, NORMALIZED_TABLE, "cdc_profile_reference_amount")
        else "NULL::numeric AS cdc_profile_reference_amount"
    )
    residual_amount_expr = (
        "residual_amount"
        if _column_exists(db, NORMALIZED_TABLE, "residual_amount")
        else "NULL::numeric AS residual_amount"
    )
    residual_pct_expr = (
        "residual_pct"
        if _column_exists(db, NORMALIZED_TABLE, "residual_pct")
        else "NULL::numeric AS residual_pct"
    )
    calibration_basis_expr = (
        "calibration_basis"
        if _column_exists(db, NORMALIZED_TABLE, "calibration_basis")
        else "NULL::text AS calibration_basis"
    )
    core_public_health_expr = (
        "core_public_health_amount"
        if _column_exists(db, NORMALIZED_TABLE, "core_public_health_amount")
        else "NULL::numeric AS core_public_health_amount"
    )
    emergency_public_health_expr = (
        "emergency_public_health_amount"
        if _column_exists(db, NORMALIZED_TABLE, "emergency_public_health_amount")
        else "NULL::numeric AS emergency_public_health_amount"
    )
    federal_health_transfer_expr = (
        "federal_health_transfer_amount"
        if _column_exists(db, NORMALIZED_TABLE, "federal_health_transfer_amount")
        else "NULL::numeric AS federal_health_transfer_amount"
    )
    procurement_support_scope_expr = (
        "procurement_support_scope_amount"
        if _column_exists(db, NORMALIZED_TABLE, "procurement_support_scope_amount")
        else "NULL::numeric AS procurement_support_scope_amount"
    )
    special_transfer_expr = (
        "special_transfer_amount"
        if _column_exists(db, NORMALIZED_TABLE, "special_transfer_amount")
        else "NULL::numeric AS special_transfer_amount"
    )
    other_public_health_expr = (
        "other_public_health_amount"
        if _column_exists(db, NORMALIZED_TABLE, "other_public_health_amount")
        else "NULL::numeric AS other_public_health_amount"
    )
    biomedical_research_expr = (
        "biomedical_research_amount"
        if _column_exists(db, NORMALIZED_TABLE, "biomedical_research_amount")
        else "NULL::numeric AS biomedical_research_amount"
    )
    international_health_assistance_expr = (
        "international_health_assistance_amount"
        if _column_exists(db, NORMALIZED_TABLE, "international_health_assistance_amount")
        else "NULL::numeric AS international_health_assistance_amount"
    )
    unknown_funding_scope_expr = (
        "unknown_funding_scope_amount"
        if _column_exists(db, NORMALIZED_TABLE, "unknown_funding_scope_amount")
        else "NULL::numeric AS unknown_funding_scope_amount"
    )
    funding_scope_components_expr = (
        "funding_scope_components_json"
        if _column_exists(db, NORMALIZED_TABLE, "funding_scope_components_json")
        else "NULL::jsonb AS funding_scope_components_json"
    )
    refreshed_at_expr = (
        "refreshed_at"
        if _column_exists(db, NORMALIZED_TABLE, "refreshed_at")
        else "updated_at AS refreshed_at"
        if _column_exists(db, NORMALIZED_TABLE, "updated_at")
        else "NULL::timestamptz AS refreshed_at"
    )
    rows = db.execute(
        text(
            f"""
            SELECT
                state_code,
                raw_amount,
                normalized_amount,
                normalized_amount_type,
                {normalization_method_expr},
                {funding_stream_logic_expr},
                {cdc_profile_reference_expr},
                {residual_amount_expr},
                {residual_pct_expr},
                {calibration_basis_expr},
                {core_public_health_expr},
                {emergency_public_health_expr},
                {federal_health_transfer_expr},
                {procurement_support_scope_expr},
                {special_transfer_expr},
                {other_public_health_expr},
                {biomedical_research_expr},
                {international_health_assistance_expr},
                {unknown_funding_scope_expr},
                {funding_scope_components_expr},
                methodology_version,
                confidence_note,
                {refreshed_at_expr},
                CASE
                    WHEN raw_amount IS NULL OR raw_amount = 0 THEN NULL
                    ELSE normalized_amount / raw_amount
                END AS normalization_factor
            FROM {NORMALIZED_TABLE}
            WHERE source_system = :source_system
              AND fiscal_year = :fiscal_year
            """
        ),
        {
            "source_system": source_system,
            "fiscal_year": int(fiscal_year),
        },
    ).mappings().all()
    return {
        str(row["state_code"]).strip().upper(): {
            **dict(row),
            "status_label": normalization_status_label(row.get("normalized_amount_type")),
        }
        for row in rows
        if str(row.get("state_code") or "").strip()
    }


def _fetch_v11_emergency_state_normalization_lookup(
    db: Session,
    *,
    source_system: str,
    fiscal_year: int,
) -> dict[str, dict[str, Any]]:
    if str(source_system or "").strip().lower() != SOURCE_USASPENDING:
        return {}
    if _table_exists(db, V11_EMERGENCY_NORMALIZED_TABLE):
        rows = db.execute(
            text(
                f"""
                SELECT
                    state_code,
                    raw_amount,
                    normalized_amount,
                    normalized_amount_type,
                    normalization_method,
                    funding_stream_logic_version,
                    cdc_profile_reference_amount,
                    residual_amount,
                    residual_pct,
                    calibration_basis,
                    core_public_health_amount,
                    emergency_public_health_amount,
                    federal_health_transfer_amount,
                    procurement_support_scope_amount,
                    special_transfer_amount,
                    other_public_health_amount,
                    biomedical_research_amount,
                    international_health_assistance_amount,
                    unknown_funding_scope_amount,
                    funding_scope_components_json,
                    methodology_version,
                    confidence_note,
                    refreshed_at,
                    normalization_factor
                FROM {V11_EMERGENCY_NORMALIZED_TABLE}
                WHERE source_system = :source_system
                  AND fiscal_year = :fiscal_year
                """
            ),
            {
                "source_system": SOURCE_USASPENDING,
                "fiscal_year": int(fiscal_year),
            },
        ).mappings().all()
    else:
        normalized_recipient_name = (
            "NULLIF(BTRIM(REGEXP_REPLACE("
            "REGEXP_REPLACE("
            "REGEXP_REPLACE(UPPER(COALESCE(tx.recipient_name, '')), '[^A-Z0-9]+', ' ', 'g'), "
            "'(^| )(INCORPORATED|INC|LLC|LTD|CORPORATION|CORP|CO)( |$)', ' ', 'g'"
            "), "
            "'\\s+', ' ', 'g'"
            ")), '')"
        )
        rows = db.execute(
            text(
                f"""
                WITH legacy AS (
                    SELECT
                        state_code,
                        raw_amount,
                        cdc_profile_reference_amount
                    FROM {NORMALIZED_TABLE}
                    WHERE source_system = 'usaspending'
                      AND fiscal_year = :fiscal_year
                ),
                classified AS (
                    SELECT
                        tx.state_code,
                        tx.raw_amount,
                        tx.include_in_profile_scope,
                        (
                            POSITION('075-0140' IN COALESCE(tx.federal_account_combination_key, '')) > 0
                            OR COALESCE(tx.mixed_scope_contains_emergency, false)
                            OR COALESCE(tx.effective_funding_scope, '') = 'emergency_public_health'
                        ) AS chip_emergency_flag,
                        LOWER(COALESCE(tx.recipient_name, '')) ~ '(state of |commonwealth of |department of health|department of public health|state health)' AS is_state_like,
                        LOWER(COALESCE(tx.recipient_name, '')) ~ '(county|city of |parish|borough|municipal|public health district|local health department|health department)' AS is_local_public_health_like,
                        LOWER(COALESCE(tx.recipient_name, '')) ~ '(state university|university of |college of medicine|school of public health)' AS is_public_university_like,
                        (
                            {normalized_recipient_name} LIKE '%PUBLIC HEALTH FOUNDATION ENTERPRISES%'
                            OR {normalized_recipient_name} LIKE '%PHFE MANAGEMENT SOLUTIONS%'
                            OR LOWER(COALESCE(tx.recipient_name, '')) ~ '(fiscal agent|foundation enterprises|phfe management solutions)'
                        ) AS is_intermediary
                    FROM {RECON_SCHEMA}.profile_scope_transactions AS tx
                    WHERE tx.fiscal_year = :fiscal_year
                      AND NULLIF(BTRIM(tx.state_code), '') IS NOT NULL
                ),
                aggregated AS (
                    SELECT
                        classified.state_code,
                        COALESCE(SUM(
                            CASE
                                WHEN classified.chip_emergency_flag IS FALSE AND classified.include_in_profile_scope IS TRUE
                                    THEN classified.raw_amount
                                WHEN classified.chip_emergency_flag IS TRUE
                                     AND classified.is_intermediary IS FALSE
                                     AND (
                                         classified.is_state_like
                                         OR classified.is_local_public_health_like
                                         OR classified.is_public_university_like
                                     )
                                    THEN classified.raw_amount
                                ELSE 0
                            END
                        ), 0)::numeric AS normalized_amount,
                        COALESCE(SUM(
                            CASE
                                WHEN classified.chip_emergency_flag IS FALSE AND classified.include_in_profile_scope IS TRUE
                                    THEN classified.raw_amount
                                ELSE 0
                            END
                        ), 0)::numeric AS core_public_health_amount,
                        COALESCE(SUM(
                            CASE
                                WHEN classified.chip_emergency_flag IS TRUE
                                     AND classified.is_intermediary IS FALSE
                                     AND (
                                         classified.is_state_like
                                         OR classified.is_local_public_health_like
                                         OR classified.is_public_university_like
                                     )
                                    THEN classified.raw_amount
                                ELSE 0
                            END
                        ), 0)::numeric AS emergency_public_health_amount
                    FROM classified
                    GROUP BY classified.state_code
                )
                SELECT
                    aggregated.state_code,
                    legacy.raw_amount,
                    aggregated.normalized_amount,
                    'state_profile_v11_emergency_classification_aligned'::text AS normalized_amount_type,
                    'v1_1_emergency_classification_state_profile_alignment'::text AS normalization_method,
                    'chip_state_profile_v1_1_emergency_classification'::text AS funding_stream_logic_version,
                    legacy.cdc_profile_reference_amount,
                    (COALESCE(aggregated.normalized_amount, 0) - COALESCE(legacy.raw_amount, 0))::numeric(18, 2) AS residual_amount,
                    CASE
                        WHEN legacy.raw_amount IS NULL OR legacy.raw_amount = 0 THEN NULL
                        ELSE (
                            (COALESCE(aggregated.normalized_amount, 0) - COALESCE(legacy.raw_amount, 0))
                            / NULLIF(legacy.raw_amount, 0)
                        )::numeric(12, 6)
                    END AS residual_pct,
                    'v1_1_emergency_classification_state_profile'::text AS calibration_basis,
                    aggregated.core_public_health_amount,
                    aggregated.emergency_public_health_amount,
                    NULL::numeric AS federal_health_transfer_amount,
                    NULL::numeric AS procurement_support_scope_amount,
                    NULL::numeric AS special_transfer_amount,
                    NULL::numeric AS other_public_health_amount,
                    NULL::numeric AS biomedical_research_amount,
                    NULL::numeric AS international_health_assistance_amount,
                    NULL::numeric AS unknown_funding_scope_amount,
                    jsonb_build_object(
                        'core_cdc_program_funding', aggregated.core_public_health_amount,
                        'emergency_distributed_funding', aggregated.emergency_public_health_amount,
                        'source', 'direct_sql_fallback'
                    ) AS funding_scope_components_json,
                    'v1.1'::text AS methodology_version,
                    'CHIP Normalized Funding v1.1 is using the direct SQL fallback because the analytics normalization view has not been migrated into this database yet.'::text AS confidence_note,
                    NOW() AS refreshed_at,
                    CASE
                        WHEN legacy.raw_amount IS NULL OR legacy.raw_amount = 0 THEN NULL
                        ELSE aggregated.normalized_amount / NULLIF(legacy.raw_amount, 0)
                    END AS normalization_factor
                FROM aggregated
                LEFT JOIN legacy
                  ON legacy.state_code = aggregated.state_code
                """
            ),
            {
                "fiscal_year": int(fiscal_year),
            },
        ).mappings().all()
    return {
        str(row["state_code"]).strip().upper(): {
            **dict(row),
            "status_label": normalization_status_label(row.get("normalized_amount_type")),
        }
        for row in rows
        if str(row.get("state_code") or "").strip()
    }


def _fetch_profile_targets(connection: Any) -> dict[tuple[int, str], dict[str, Any]]:
    rows = connection.execute(
        text(
            f"""
            SELECT fiscal_year, state_code, state_name, amount
            FROM {CDC_PROFILE_TOTALS_TABLE}
            WHERE fiscal_year BETWEEN 2020 AND 2023
            """
        )
    ).mappings().all()
    return {
        (int(row["fiscal_year"]), str(row["state_code"]).strip().upper()): {
            "state_name": row.get("state_name"),
            "amount": _as_decimal(row.get("amount")),
        }
        for row in rows
        if str(row.get("state_code") or "").strip()
    }


def _empty_rollup() -> dict[str, Any]:
    return {
        "raw_amount": Decimal("0"),
        "classified_profile_scope_amount": Decimal("0"),
        "domestic_exclusion_amount": Decimal("0"),
        "included_special_stream_amount": Decimal("0"),
        "action_duplication_adjustment": Decimal("0"),
        "vfc_adjustment": Decimal("0"),
        "other_identified_adjustment": Decimal("0"),
        "funding_stream_totals": defaultdict(lambda: {"raw_amount": Decimal("0"), "included_amount": Decimal("0")}),
    }


def _upsert_rollup(
    rollups: dict[tuple[int, str], dict[str, Any]],
    *,
    fiscal_year: int,
    state_code: str,
    raw_amount: Decimal,
    included_amount: Decimal,
    funding_stream: str,
    domestic_excluded: bool = False,
    is_special_included: bool = False,
    is_vfc: bool = False,
) -> None:
    key = (int(fiscal_year), str(state_code).strip().upper())
    accumulator = rollups.setdefault(key, _empty_rollup())
    accumulator["raw_amount"] += raw_amount
    accumulator["classified_profile_scope_amount"] += included_amount
    if domestic_excluded:
        accumulator["domestic_exclusion_amount"] += raw_amount
    if is_special_included:
        accumulator["included_special_stream_amount"] += included_amount
    if is_vfc:
        accumulator["vfc_adjustment"] += included_amount
    stream_bucket = accumulator["funding_stream_totals"][funding_stream]
    stream_bucket["raw_amount"] += raw_amount
    stream_bucket["included_amount"] += included_amount


def _fetch_usaspending_base_rows(connection: Any) -> list[dict[str, Any]]:
    return connection.execute(
        text(
            f"""
            SELECT
                tx.assistance_transaction_unique_key,
                tx.assistance_award_unique_key,
                tx.award_id_fain,
                tx.action_date_fiscal_year AS fiscal_year,
                UPPER(COALESCE(tx.recipient_state_code, p.recipient_state_code)) AS state_code,
                COALESCE(tx.federal_action_obligation, 0)::numeric AS raw_amount,
                tx.appropriation_type AS appropriation_type_raw,
                tx.appropriation_subtype AS appropriation_subtype_raw,
                tx.disaster_emergency_fund_codes_raw AS raw_emergency_code,
                COALESCE(
                    NULLIF(BTRIM(tx.raw ->> 'federal_account_symbol'), ''),
                    NULLIF(BTRIM(tx.raw ->> 'federal_account_identifier'), ''),
                    NULLIF(BTRIM(p.raw ->> 'federal_account_symbol'), ''),
                    NULLIF(BTRIM(p.raw ->> 'federal_account_identifier'), '')
                ) AS federal_account_symbol,
                COALESCE(
                    NULLIF(BTRIM(tx.raw ->> 'treasury_account_symbol'), ''),
                    NULLIF(BTRIM(tx.raw ->> 'treasury_account_identifier'), ''),
                    NULLIF(BTRIM(p.raw ->> 'treasury_account_symbol'), ''),
                    NULLIF(BTRIM(p.raw ->> 'treasury_account_identifier'), '')
                ) AS treasury_account_symbol,
                COALESCE(
                    NULLIF(BTRIM(tx.raw ->> 'appropriation_account'), ''),
                    NULLIF(BTRIM(p.raw ->> 'appropriation_account'), '')
                ) AS appropriation_account,
                COALESCE(
                    NULLIF(BTRIM(tx.raw ->> 'program_activity_name'), ''),
                    NULLIF(BTRIM(tx.raw ->> 'program_activity'), ''),
                    NULLIF(BTRIM(p.raw ->> 'program_activity_name'), '')
                ) AS program_activity_name,
                tx.transaction_description,
                tx.prime_award_base_transaction_description,
                tx.cfda_title,
                p.cfda_program_title,
                p.cfda_numbers_and_titles
            FROM {CDC_PRIME_TRANSACTIONS_TABLE} AS tx
            LEFT JOIN {CDC_PRIME_AWARDS_TABLE} AS p
              ON p.unique_key = tx.assistance_award_unique_key
            WHERE tx.action_date_fiscal_year BETWEEN 2020 AND 2026
              AND COALESCE(tx.recipient_state_code, p.recipient_state_code) IS NOT NULL
            """
        )
    ).mappings().all()


def _fetch_taggs_base_rows(connection: Any) -> list[dict[str, Any]]:
    return connection.execute(
        text(
            f"""
            SELECT
                s.award_number,
                s.funding_fiscal_year AS fiscal_year,
                UPPER(s.legal_entity_state_normalized) AS state_code,
                s.can_code,
                COALESCE(s.total_sum_of_actions, 0)::numeric AS raw_amount,
                s.funding_stream AS raw_funding_stream,
                s.appropriation_type,
                s.is_domestic_scope,
                s.award_title,
                s.assistance_listing_title,
                s.effective_program_name,
                s.effective_category,
                s.effective_subcategory,
                s.can_mapping_version,
                c.is_covid_related,
                c.is_arpa_related,
                c.is_supplemental,
                c.is_regular_appropriation
            FROM {TAGGS_AWARD_SUMMARY_TABLE} AS s
            LEFT JOIN {TAGGS_CAN_CLASSIFICATION_TABLE} AS c
              ON c.can_code = s.can_code
            WHERE s.funding_fiscal_year BETWEEN 2020 AND 2026
              AND NULLIF(BTRIM(s.legal_entity_state_normalized), '') IS NOT NULL
            """
        )
    ).mappings().all()


def _build_usaspending_rows(
    connection: Any,
    *,
    rules: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[tuple[int, str], dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    rollups: dict[tuple[int, str], dict[str, Any]] = {}
    for row in _fetch_usaspending_base_rows(connection):
        state_code = str(row.get("state_code") or "").strip().upper()
        fiscal_year = row.get("fiscal_year")
        if not state_code or fiscal_year is None:
            continue
        raw_amount = _as_decimal(row.get("raw_amount"))
        classification = classify_usaspending_record(dict(row), rules=rules)
        inclusion_weight = _as_decimal(classification["inclusion_weight"])
        included_amount = (raw_amount * inclusion_weight).quantize(Decimal("0.01"))
        descriptor = " ".join(
            part
            for part in (
                str(row.get("program_activity_name") or "").strip(),
                str(row.get("transaction_description") or "").strip(),
                str(row.get("prime_award_base_transaction_description") or "").strip(),
            )
            if part
        ).lower()
        is_vfc = "vaccines for children" in descriptor
        rows.append(
            {
                "assistance_transaction_unique_key": row.get("assistance_transaction_unique_key"),
                "assistance_award_unique_key": row.get("assistance_award_unique_key"),
                "award_id_fain": row.get("award_id_fain"),
                "fiscal_year": int(fiscal_year),
                "state_code": state_code,
                "raw_amount": raw_amount,
                "appropriation_type_raw": row.get("appropriation_type_raw"),
                "appropriation_type_normalized": classification["appropriation_type_normalized"],
                "appropriation_subtype_raw": row.get("appropriation_subtype_raw"),
                "defc_code_normalized": classification["defc_code_normalized"],
                "federal_account_symbol": row.get("federal_account_symbol"),
                "treasury_account_symbol": row.get("treasury_account_symbol"),
                "appropriation_account": row.get("appropriation_account"),
                "program_activity_name": row.get("program_activity_name"),
                "funding_stream": classification["funding_stream"],
                "include_in_cdc_profile_scope": classification["include_in_cdc_profile_scope"],
                "inclusion_weight": inclusion_weight,
                "inclusion_reason": classification["inclusion_reason"],
                "exclusion_reason": classification["exclusion_reason"],
                "methodology_version": METHODOLOGY_VERSION,
                "funding_stream_logic_version": FUNDING_STREAM_LOGIC_VERSION,
            }
        )
        _upsert_rollup(
            rollups,
            fiscal_year=int(fiscal_year),
            state_code=state_code,
            raw_amount=raw_amount,
            included_amount=included_amount,
            funding_stream=classification["funding_stream"],
            is_special_included=(
                classification["include_in_cdc_profile_scope"]
                and classification["funding_stream"] != FUNDING_STREAM_REGULAR
            ),
            is_vfc=is_vfc and classification["include_in_cdc_profile_scope"],
        )
    return rows, rollups


def _build_taggs_rows(
    connection: Any,
    *,
    rules: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[tuple[int, str], dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    rollups: dict[tuple[int, str], dict[str, Any]] = {}
    for row in _fetch_taggs_base_rows(connection):
        state_code = str(row.get("state_code") or "").strip().upper()
        fiscal_year = row.get("fiscal_year")
        if not state_code or fiscal_year is None:
            continue
        raw_amount = _as_decimal(row.get("raw_amount"))
        classification = classify_taggs_record(dict(row), rules=rules)
        inclusion_weight = _as_decimal(classification["inclusion_weight"])
        included_amount = (raw_amount * inclusion_weight).quantize(Decimal("0.01"))
        raw_stream_blob = str(row.get("raw_funding_stream") or "").strip().lower()
        is_vfc = "vaccines for children" in raw_stream_blob or "vaccines for children" in str(row.get("award_title") or "").lower()
        rows.append(
            {
                "award_number": row.get("award_number"),
                "fiscal_year": int(fiscal_year),
                "state_code": state_code,
                "can_code": row.get("can_code"),
                "raw_amount": raw_amount,
                "raw_funding_stream": row.get("raw_funding_stream"),
                "funding_stream": classification["funding_stream"],
                "include_in_cdc_profile_scope": classification["include_in_cdc_profile_scope"],
                "inclusion_weight": inclusion_weight,
                "profile_scope_reason": classification["profile_scope_reason"],
                "methodology_version": METHODOLOGY_VERSION,
                "funding_stream_logic_version": FUNDING_STREAM_LOGIC_VERSION,
                "can_mapping_version": row.get("can_mapping_version"),
            }
        )
        _upsert_rollup(
            rollups,
            fiscal_year=int(fiscal_year),
            state_code=state_code,
            raw_amount=raw_amount,
            included_amount=included_amount,
            funding_stream=classification["funding_stream"],
            domestic_excluded=not bool(row.get("is_domestic_scope")),
            is_special_included=(
                classification["include_in_cdc_profile_scope"]
                and classification["funding_stream"] != FUNDING_STREAM_REGULAR
            ),
            is_vfc=is_vfc and classification["include_in_cdc_profile_scope"],
        )
    return rows, rollups


def _build_calibration_rows(
    *,
    source_system: str,
    source_rows: dict[tuple[int, str], dict[str, Any]],
    profile_targets: dict[tuple[int, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    calibration_rows: list[dict[str, Any]] = []
    normalized_rows: list[dict[str, Any]] = []

    all_state_years = {
        key
        for key in source_rows
        if key[0] in (*TRAINING_FISCAL_YEARS, *ESTIMATED_FISCAL_YEARS)
    }
    all_state_years.update(
        key
        for key in profile_targets
        if key[0] in TRAINING_FISCAL_YEARS
    )
    for fiscal_year, state_code in sorted(all_state_years):
        source = source_rows.get((fiscal_year, state_code), _empty_rollup())
        raw_amount = _as_decimal(source.get("raw_amount"))
        classified_profile_scope_amount = _as_decimal(source.get("classified_profile_scope_amount"))
        normalized_amount_type = (
            NORMALIZED_AMOUNT_TYPE_OBSERVED
            if fiscal_year in TRAINING_FISCAL_YEARS
            else NORMALIZED_AMOUNT_TYPE_ESTIMATED
        )
        normalized_rows.append(
            {
                "source_system": source_system,
                "fiscal_year": fiscal_year,
                "state_code": state_code,
                "raw_amount": raw_amount,
                "normalized_amount": classified_profile_scope_amount,
                "normalized_amount_type": normalized_amount_type,
                "normalization_method": "funding_scope_reconstruction_calibration_layer",
                "funding_stream_logic_version": FUNDING_STREAM_LOGIC_VERSION,
                "methodology_version": METHODOLOGY_VERSION,
                "confidence_note": (
                    "Profile-aligned using explicit funding-scope rules benchmarked against observed CDC Funding Profiles FY2020-FY2023 totals."
                    if fiscal_year in TRAINING_FISCAL_YEARS
                    else "Profile-aligned estimate using the FY2020-FY2023 funding-scope rules without an official CDC Funding Profiles target."
                ),
            }
        )

        target = profile_targets.get((fiscal_year, state_code))
        if target is None:
            continue
        cdc_profile_amount = _as_decimal(target.get("amount"))
        residual_difference = cdc_profile_amount - classified_profile_scope_amount
        major_difference_drivers = build_major_difference_drivers(
            funding_stream_totals=source.get("funding_stream_totals") or {},
            cdc_profile_amount=cdc_profile_amount,
            classified_profile_scope_amount=classified_profile_scope_amount,
        )
        calibration_rows.append(
            {
                "fiscal_year": fiscal_year,
                "state_code": state_code,
                "source_system": source_system,
                "raw_amount": raw_amount,
                "classified_profile_scope_amount": classified_profile_scope_amount,
                "cdc_profile_amount": cdc_profile_amount,
                "residual_difference": residual_difference,
                "major_difference_drivers": json.dumps(major_difference_drivers, default=str),
                "normalization_method": "funding_scope_reconstruction_calibration_layer",
                "normalized_amount_target": cdc_profile_amount,
                "raw_minus_target": raw_amount - cdc_profile_amount,
                "domestic_exclusion_amount": _as_decimal(source.get("domestic_exclusion_amount")),
                "included_special_stream_amount": _as_decimal(source.get("included_special_stream_amount")),
                "action_duplication_adjustment": _as_decimal(source.get("action_duplication_adjustment")),
                "vfc_adjustment": _as_decimal(source.get("vfc_adjustment")),
                "other_identified_adjustment": _as_decimal(source.get("other_identified_adjustment")),
                "unresolved_residual": residual_difference,
                "normalization_factor": (
                    None if raw_amount == 0 else classified_profile_scope_amount / raw_amount
                ),
                "methodology_version": METHODOLOGY_VERSION,
                "confidence_note": (
                    "Observed CDC Funding Profiles FY2020-FY2023 are used as calibration references. CHIP now compares those targets to rule-based profile-scope totals instead of forcing an exact state-level factor match."
                ),
            }
        )
    return calibration_rows, normalized_rows


def _build_rules_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_system in (SOURCE_TAGGS, SOURCE_USASPENDING):
        for fiscal_year in (*TRAINING_FISCAL_YEARS, *ESTIMATED_FISCAL_YEARS):
            start = date(fiscal_year - 1, 10, 1)
            end = date(fiscal_year, 9, 30)
            rows.extend(
                [
                    {
                        "fiscal_year": fiscal_year,
                        "source_system": source_system,
                        "rule_name": "defc_priority_classification",
                        "rule_type": "lookup_priority",
                        "parameter_json": json.dumps(
                            {
                                "priority": [
                                    "disaster_emergency_fund_codes",
                                    "appropriation_type",
                                    "federal_account_symbol",
                                    "program_activity_name",
                                ],
                                "rule_tables": [
                                    DEFC_RULES_TABLE,
                                    APPROPRIATION_RULES_TABLE,
                                    FEDERAL_ACCOUNT_RULES_TABLE,
                                    PROFILE_SCOPE_RULES_TABLE,
                                ],
                            }
                        ),
                        "effective_start": start,
                        "effective_end": end,
                        "methodology_version": METHODOLOGY_VERSION,
                    },
                    {
                        "fiscal_year": fiscal_year,
                        "source_system": source_system,
                        "rule_name": "cdc_profile_scope_rules",
                        "rule_type": "deterministic_inclusion_exclusion",
                        "parameter_json": json.dumps(
                            {
                                "default_include_stream": FUNDING_STREAM_REGULAR,
                                "default_exclude_streams": [
                                    "covid_emergency",
                                    "arpa",
                                    "other_emergency_or_disaster",
                                    "non_covid_supplemental",
                                    "transfer_or_special",
                                    "unknown",
                                ],
                                "supports_partial_weights": True,
                            }
                        ),
                        "effective_start": start,
                        "effective_end": end,
                        "methodology_version": METHODOLOGY_VERSION,
                    },
                ]
            )
    return rows


def _insert_seed_tables(connection: Any, rules: dict[str, Any]) -> None:
    connection.execute(text(f"TRUNCATE TABLE {PROFILE_SCOPE_RULES_TABLE} RESTART IDENTITY"))
    connection.execute(text(f"TRUNCATE TABLE {FEDERAL_ACCOUNT_RULES_TABLE} RESTART IDENTITY"))
    connection.execute(text(f"TRUNCATE TABLE {APPROPRIATION_RULES_TABLE}"))
    connection.execute(text(f"TRUNCATE TABLE {DEFC_RULES_TABLE}"))

    connection.execute(
        text(
            f"""
            INSERT INTO {DEFC_RULES_TABLE} (
                defc_code,
                funding_stream,
                appropriation_type_normalized,
                is_covid_related,
                is_arpa_related,
                include_in_cdc_profile_scope_default,
                default_inclusion_weight,
                notes
            ) VALUES (
                :defc_code,
                :funding_stream,
                :appropriation_type_normalized,
                :is_covid_related,
                :is_arpa_related,
                :include_in_cdc_profile_scope_default,
                :default_inclusion_weight,
                :notes
            )
            """
        ),
        rules["defc_rules"],
    )
    connection.execute(
        text(
            f"""
            INSERT INTO {APPROPRIATION_RULES_TABLE} (
                appropriation_type_raw,
                appropriation_type_normalized,
                default_funding_stream,
                default_include_in_cdc_profile_scope,
                default_inclusion_weight,
                notes
            ) VALUES (
                :appropriation_type_raw,
                :appropriation_type_normalized,
                :default_funding_stream,
                :default_include_in_cdc_profile_scope,
                :default_inclusion_weight,
                :notes
            )
            """
        ),
        rules["appropriation_type_rules"],
    )
    connection.execute(
        text(
            f"""
            INSERT INTO {FEDERAL_ACCOUNT_RULES_TABLE} (
                federal_account_symbol,
                treasury_account_symbol,
                program_activity_name,
                can_like_program_hint,
                default_funding_stream,
                include_in_cdc_profile_scope_default,
                default_inclusion_weight,
                notes
            ) VALUES (
                :federal_account_symbol,
                :treasury_account_symbol,
                :program_activity_name,
                :can_like_program_hint,
                :default_funding_stream,
                :include_in_cdc_profile_scope_default,
                :default_inclusion_weight,
                :notes
            )
            """
        ),
        rules["federal_account_rules"],
    )
    connection.execute(
        text(
            f"""
            INSERT INTO {PROFILE_SCOPE_RULES_TABLE} (
                source_system,
                funding_stream,
                can_code,
                federal_account_symbol,
                treasury_account_symbol,
                program_activity_name,
                include_in_profile_scope,
                inclusion_weight,
                rationale,
                methodology_version
            ) VALUES (
                :source_system,
                :funding_stream,
                :can_code,
                :federal_account_symbol,
                :treasury_account_symbol,
                :program_activity_name,
                :include_in_profile_scope,
                :inclusion_weight,
                :rationale,
                :methodology_version
            )
            """
        ),
        rules["scope_rules"],
    )


def rebuild(
    *,
    db_url: str,
    truncate: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    rules = load_rule_payloads()
    engine = create_engine(db_url, pool_pre_ping=True)
    with engine.begin() as connection:
        profile_targets = _fetch_profile_targets(connection)
        usaspending_rows, usaspending_rollups = _build_usaspending_rows(connection, rules=rules)
        taggs_rows, taggs_rollups = _build_taggs_rows(connection, rules=rules)

        taggs_calibration_rows, taggs_normalized_rows = _build_calibration_rows(
            source_system=SOURCE_TAGGS,
            source_rows=taggs_rollups,
            profile_targets=profile_targets,
        )
        usaspending_calibration_rows, usaspending_normalized_rows = _build_calibration_rows(
            source_system=SOURCE_USASPENDING,
            source_rows=usaspending_rollups,
            profile_targets=profile_targets,
        )
        calibration_rows = taggs_calibration_rows + usaspending_calibration_rows
        normalized_rows = taggs_normalized_rows + usaspending_normalized_rows
        rules_rows = _build_rules_rows()
        methodology_log_rows = [
            {
                "methodology_version": METHODOLOGY_VERSION,
                "note": (
                    "CHIP now normalizes TAGGS and USA Spending totals with explicit funding-stream scope rules. "
                    "USA Spending classification prioritizes emergency/disaster coding, then appropriation type, then federal account and program descriptors. "
                    "TAGGS rows inherit the same framework through CAN-driven funding-stream mapping."
                ),
                "metadata_json": json.dumps(
                    {
                        "training_years": list(TRAINING_FISCAL_YEARS),
                        "estimated_years": list(ESTIMATED_FISCAL_YEARS),
                        "funding_stream_logic_version": FUNDING_STREAM_LOGIC_VERSION,
                        "rule_tables": [
                            DEFC_RULES_TABLE,
                            APPROPRIATION_RULES_TABLE,
                            FEDERAL_ACCOUNT_RULES_TABLE,
                            PROFILE_SCOPE_RULES_TABLE,
                        ],
                    }
                ),
            }
        ]

        summary = {
            "methodology_version": METHODOLOGY_VERSION,
            "funding_stream_logic_version": FUNDING_STREAM_LOGIC_VERSION,
            "profile_target_state_years": len(profile_targets),
            "taggs_funding_stream_rows": len(taggs_rows),
            "usaspending_funding_stream_rows": len(usaspending_rows),
            "calibration_rows": len(calibration_rows),
            "normalized_rows": len(normalized_rows),
            "rules_rows": len(rules_rows),
        }
        if dry_run:
            return summary

        if truncate:
            connection.execute(text(f"TRUNCATE TABLE {METHODOLOGY_LOG_TABLE} RESTART IDENTITY"))
            connection.execute(text(f"TRUNCATE TABLE {RULES_TABLE} RESTART IDENTITY"))
            connection.execute(text(f"TRUNCATE TABLE {NORMALIZED_TABLE} RESTART IDENTITY"))
            connection.execute(text(f"TRUNCATE TABLE {CALIBRATION_TABLE} RESTART IDENTITY"))
            connection.execute(text(f"TRUNCATE TABLE {USASPENDING_STREAMS_TABLE}"))
            connection.execute(text(f"TRUNCATE TABLE {TAGGS_STREAMS_TABLE} RESTART IDENTITY"))

        _insert_seed_tables(connection, rules)

        if usaspending_rows:
            connection.execute(
                text(
                    f"""
                    INSERT INTO {USASPENDING_STREAMS_TABLE} (
                        assistance_transaction_unique_key,
                        assistance_award_unique_key,
                        award_id_fain,
                        fiscal_year,
                        state_code,
                        raw_amount,
                        appropriation_type_raw,
                        appropriation_type_normalized,
                        appropriation_subtype_raw,
                        defc_code_normalized,
                        federal_account_symbol,
                        treasury_account_symbol,
                        appropriation_account,
                        program_activity_name,
                        funding_stream,
                        include_in_cdc_profile_scope,
                        inclusion_weight,
                        inclusion_reason,
                        exclusion_reason,
                        methodology_version,
                        funding_stream_logic_version
                    ) VALUES (
                        :assistance_transaction_unique_key,
                        :assistance_award_unique_key,
                        :award_id_fain,
                        :fiscal_year,
                        :state_code,
                        :raw_amount,
                        :appropriation_type_raw,
                        :appropriation_type_normalized,
                        :appropriation_subtype_raw,
                        :defc_code_normalized,
                        :federal_account_symbol,
                        :treasury_account_symbol,
                        :appropriation_account,
                        :program_activity_name,
                        :funding_stream,
                        :include_in_cdc_profile_scope,
                        :inclusion_weight,
                        :inclusion_reason,
                        :exclusion_reason,
                        :methodology_version,
                        :funding_stream_logic_version
                    )
                    """
                ),
                usaspending_rows,
            )

        if taggs_rows:
            connection.execute(
                text(
                    f"""
                    INSERT INTO {TAGGS_STREAMS_TABLE} (
                        award_number,
                        fiscal_year,
                        state_code,
                        can_code,
                        raw_amount,
                        raw_funding_stream,
                        funding_stream,
                        include_in_cdc_profile_scope,
                        inclusion_weight,
                        profile_scope_reason,
                        methodology_version,
                        funding_stream_logic_version,
                        can_mapping_version
                    ) VALUES (
                        :award_number,
                        :fiscal_year,
                        :state_code,
                        :can_code,
                        :raw_amount,
                        :raw_funding_stream,
                        :funding_stream,
                        :include_in_cdc_profile_scope,
                        :inclusion_weight,
                        :profile_scope_reason,
                        :methodology_version,
                        :funding_stream_logic_version,
                        :can_mapping_version
                    )
                    """
                ),
                taggs_rows,
            )

        if calibration_rows:
            connection.execute(
                text(
                    f"""
                    INSERT INTO {CALIBRATION_TABLE} (
                        fiscal_year,
                        state_code,
                        source_system,
                        raw_amount,
                        classified_profile_scope_amount,
                        cdc_profile_amount,
                        residual_difference,
                        major_difference_drivers,
                        normalization_method,
                        normalized_amount_target,
                        raw_minus_target,
                        domestic_exclusion_amount,
                        included_special_stream_amount,
                        action_duplication_adjustment,
                        vfc_adjustment,
                        other_identified_adjustment,
                        unresolved_residual,
                        normalization_factor,
                        methodology_version,
                        confidence_note
                    ) VALUES (
                        :fiscal_year,
                        :state_code,
                        :source_system,
                        :raw_amount,
                        :classified_profile_scope_amount,
                        :cdc_profile_amount,
                        :residual_difference,
                        CAST(:major_difference_drivers AS jsonb),
                        :normalization_method,
                        :normalized_amount_target,
                        :raw_minus_target,
                        :domestic_exclusion_amount,
                        :included_special_stream_amount,
                        :action_duplication_adjustment,
                        :vfc_adjustment,
                        :other_identified_adjustment,
                        :unresolved_residual,
                        :normalization_factor,
                        :methodology_version,
                        :confidence_note
                    )
                    """
                ),
                calibration_rows,
            )

        if normalized_rows:
            connection.execute(
                text(
                    f"""
                    INSERT INTO {NORMALIZED_TABLE} (
                        source_system,
                        fiscal_year,
                        state_code,
                        raw_amount,
                        normalized_amount,
                        normalized_amount_type,
                        normalization_method,
                        funding_stream_logic_version,
                        methodology_version,
                        confidence_note
                    ) VALUES (
                        :source_system,
                        :fiscal_year,
                        :state_code,
                        :raw_amount,
                        :normalized_amount,
                        :normalized_amount_type,
                        :normalization_method,
                        :funding_stream_logic_version,
                        :methodology_version,
                        :confidence_note
                    )
                    """
                ),
                normalized_rows,
            )

        if rules_rows:
            connection.execute(
                text(
                    f"""
                    INSERT INTO {RULES_TABLE} (
                        fiscal_year,
                        source_system,
                        rule_name,
                        rule_type,
                        parameter_json,
                        effective_start,
                        effective_end,
                        methodology_version
                    ) VALUES (
                        :fiscal_year,
                        :source_system,
                        :rule_name,
                        :rule_type,
                        CAST(:parameter_json AS jsonb),
                        :effective_start,
                        :effective_end,
                        :methodology_version
                    )
                    """
                ),
                rules_rows,
            )

        connection.execute(
            text(
                f"""
                INSERT INTO {METHODOLOGY_LOG_TABLE} (
                    methodology_version,
                    note,
                    metadata_json
                ) VALUES (
                    :methodology_version,
                    :note,
                    CAST(:metadata_json AS jsonb)
                )
                """
            ),
            methodology_log_rows,
        )

    return summary


def main() -> None:
    args = parse_args()
    summary = rebuild(
        db_url=args.db_url,
        truncate=bool(args.truncate),
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
