from __future__ import annotations

import math
import os
from dataclasses import dataclass
from decimal import Decimal
from numbers import Real
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db_fqtn import analytics_table, places_table
from app.services.chip_funding_model import CDCFundingMode, FUNDING_MODE_LABELS

VERSION_TAG = "v11_ec"
MODEL_VERSION = "v1_1_emergency_classification"
METHODOLOGY_VERSION = "v1.1"
ROLLOUT_STATUS = "partial_raw_total_only"
STATE_PROFILE_SOURCE_VERSION = "chip_state_profile_v1_1_emergency_classification"
NORMALIZATION_SOURCE_VERSION = "chip_normalized_v1_1_emergency_classification"
PROFILE_VERSION = "funding_profile_result_v1_1_emergency_classification_raw"
RULE_SET_VERSION = "rules_v1"
RAW_SOURCE_ENV = "CDC_STATE_PROFILE_RAW_SOURCE_VERSION"

FUNDING_CLASSIFICATION_VIEW = analytics_table("chip_funding_classification_v11_ec")
STATE_PROFILE_VIEW = analytics_table("chip_state_funding_profile_v11_ec")
CENTRALIZED_VIEW = analytics_table("chip_centralized_funding_v11_ec")
CLASSIFICATION_SUMMARY_VIEW = analytics_table("chip_funding_classification_summary_v11_ec")
STATE_PROFILE_VALIDATION_VIEW = analytics_table("chip_state_funding_profile_validation_v11_ec")
CONSERVATION_VIEW = analytics_table("chip_transaction_conservation_validation_v11_ec")
REVIEW_QUEUE_VIEW = analytics_table("chip_recipient_review_queue_v11_ec")
STATE_DIM_TABLE = places_table("dim_state_boundary")
POPULATION_VIEW_TABLE = places_table("v_geography_population")

METRIC_LABELS = {
    "total_funding": "Total Funding",
    "funding_per_capita": "Funding per Capita",
    "funding_per_100k": "Funding per 100K",
    "share_national": "Share of National Total",
}
FUNDING_TYPE_LABELS = {
    "total_cdc_funding": "State-Relevant CDC Funding",
    "emergency_response": "Emergency Distributed Funding",
    "non_emergency_program": "Core CDC Program Funding",
}
FUNDING_CATEGORY_LABELS = {
    "core_cdc_program": "Core CDC Program",
    "emergency_distributed": "Emergency Distributed",
    "emergency_centralized": "Emergency Centralized",
    "emergency_unresolved_excluded": "Emergency Unresolved Excluded",
    "other_explicitly_excluded": "Other Explicitly Excluded",
}
RECIPIENT_TYPE_LABELS = {
    "state_like": "State-Like Implementers",
    "local_public_health_like": "Local Public Health",
    "public_university_candidate": "University Candidates",
    "intermediary": "Centralized Intermediaries",
    "other": "Other / Review",
}


@dataclass(frozen=True)
class EmergencyStateProfileSupport:
    enabled: bool
    reason: str | None


def _json_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            return None
        return float(value)
    if isinstance(value, Real):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    return None


def _table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(
        text("SELECT to_regclass(:name) AS exists"),
        {"name": table_name},
    ).mappings().one()
    return row["exists"] is not None


def raw_source_version_setting() -> str:
    return str(os.getenv(RAW_SOURCE_ENV, "v1") or "v1").strip().lower()


def support_status(
    *,
    funding_mode: str | None,
    funding_type: str | None,
    cdc_center: str | None,
    program_area: str | None,
    mechanism: str | None,
    recipient_type: str | None,
) -> EmergencyStateProfileSupport:
    if raw_source_version_setting() not in {
        "v11_ec",
        "v1_1_emergency_classification",
        "v1.1",
        "enabled",
        "true",
        "1",
        "on",
    }:
        return EmergencyStateProfileSupport(enabled=False, reason="feature_flag_disabled")
    if str(funding_mode or "").strip().lower() != CDCFundingMode.RAW_TOTAL.value:
        return EmergencyStateProfileSupport(enabled=False, reason="non_raw_mode_uses_standard_normalization_path")
    if str(funding_type or "total_cdc_funding").strip().lower() not in {
        "total_cdc_funding",
        "emergency_response",
        "non_emergency_program",
    }:
        return EmergencyStateProfileSupport(enabled=False, reason="unsupported_funding_type_filter")
    if any(str(value or "").strip() for value in (cdc_center, program_area, mechanism, recipient_type)):
        return EmergencyStateProfileSupport(enabled=False, reason="subset_filters_not_supported_for_v1_1_raw")
    return EmergencyStateProfileSupport(enabled=True, reason=None)


def _ensure_required_views(db: Session) -> None:
    required = [
        FUNDING_CLASSIFICATION_VIEW,
        STATE_PROFILE_VIEW,
        CENTRALIZED_VIEW,
        CLASSIFICATION_SUMMARY_VIEW,
        STATE_PROFILE_VALIDATION_VIEW,
        CONSERVATION_VIEW,
        REVIEW_QUEUE_VIEW,
    ]
    missing = [table_name for table_name in required if not _table_exists(db, table_name)]
    if missing:
        joined = ", ".join(missing)
        raise HTTPException(
            status_code=503,
            detail=(
                "The v1.1 emergency-classification analytics layer is unavailable because these objects are missing: "
                f"{joined}. Run migrations first."
            ),
        )


def _normalize_state_code(value: str | None) -> str:
    token = str(value or "").strip().upper()
    if len(token) != 2:
        raise HTTPException(status_code=400, detail="state must be a valid 2-letter state code")
    return token


def _normalize_metric(value: str | None) -> str:
    token = str(value or "total_funding").strip().lower()
    if token not in METRIC_LABELS:
        allowed = ", ".join(sorted(METRIC_LABELS))
        raise HTTPException(status_code=400, detail=f"metric must be one of {allowed}")
    return token


def _normalize_time_aggregation(value: str | None) -> str:
    token = str(value or "single_fiscal_year").strip().lower()
    if token not in {"single_fiscal_year", "multi_year_total", "multi_year_average"}:
        raise HTTPException(
            status_code=400,
            detail="time_aggregation must be single_fiscal_year, multi_year_total, or multi_year_average",
        )
    return token


def _normalize_funding_type(value: str | None) -> str:
    token = str(value or "total_cdc_funding").strip().lower()
    if token not in FUNDING_TYPE_LABELS:
        allowed = ", ".join(sorted(FUNDING_TYPE_LABELS))
        raise HTTPException(status_code=400, detail=f"funding_type must be one of {allowed}")
    return token


def _normalize_optional_fiscal_year(value: int | None) -> int | None:
    if value is None:
        return None
    return int(value)


def _metric_value(metric: str, *, total_funding: float | None, population: float | None, national_total: float | None) -> float | None:
    if metric == "total_funding":
        return total_funding
    if metric == "funding_per_capita":
        if total_funding is None or population in (None, 0):
            return None
        return total_funding / population
    if metric == "funding_per_100k":
        if total_funding is None or population in (None, 0):
            return None
        return (total_funding / population) * 100000
    if metric == "share_national":
        if total_funding is None or national_total in (None, 0):
            return None
        return (total_funding / national_total) * 100
    return None


def _timeframe_label(
    *,
    fiscal_year: int | None,
    min_fiscal_year: int | None,
    max_fiscal_year: int | None,
    time_aggregation: str,
) -> str:
    if time_aggregation == "single_fiscal_year":
        return f"FY{fiscal_year}" if fiscal_year is not None else "Single Fiscal Year"
    if min_fiscal_year is None or max_fiscal_year is None:
        return "Multi-Year"
    if min_fiscal_year == max_fiscal_year:
        return f"FY{min_fiscal_year}"
    if time_aggregation == "multi_year_average":
        return f"Average FY{min_fiscal_year}-FY{max_fiscal_year}"
    return f"FY{min_fiscal_year}-FY{max_fiscal_year}"


def _legend_title(*, metric: str, timeframe_label: str) -> str:
    return f"{METRIC_LABELS[metric]} • {timeframe_label}"


def _filter_context(
    *,
    fiscal_year: int | None,
    funding_type: str,
    time_aggregation: str,
) -> dict[str, Any]:
    return {
        "funding_type": funding_type,
        "funding_type_label": FUNDING_TYPE_LABELS[funding_type],
        "time_aggregation": time_aggregation,
        "time_aggregation_label": time_aggregation.replace("_", " ").title(),
        "legend_title": _legend_title(
            metric="total_funding",
            timeframe_label=_timeframe_label(
                fiscal_year=fiscal_year,
                min_fiscal_year=fiscal_year,
                max_fiscal_year=fiscal_year,
                time_aggregation=time_aggregation,
            ),
        ),
    }


def _amount_sql_for_funding_type(alias: str, funding_type: str) -> str:
    if funding_type == "emergency_response":
        return f"{alias}.emergency_distributed_funding"
    if funding_type == "non_emergency_program":
        return f"{alias}.core_cdc_program_funding"
    return f"{alias}.total_state_relevant_funding"


def _state_population(db: Session, state_code: str) -> float | None:
    row = db.execute(
        text(
            f"""
            SELECT population
            FROM {POPULATION_VIEW_TABLE}
            WHERE geography_type = 'state'
              AND UPPER(state_abbr) = :state_code
            LIMIT 1
            """
        ),
        {"state_code": state_code},
    ).mappings().one_or_none()
    if not row:
        return None
    return _json_number(row.get("population"))


def _summary_row(
    db: Session,
    *,
    state_code: str,
    fiscal_year: int | None,
    funding_type: str,
    time_aggregation: str,
) -> dict[str, Any]:
    amount_expr = _amount_sql_for_funding_type("p", funding_type)
    fy_filter = "AND p.fiscal_year = :fiscal_year" if fiscal_year is not None else ""
    params: dict[str, Any] = {"state_code": state_code, "time_aggregation": time_aggregation}
    if fiscal_year is not None:
        params["fiscal_year"] = fiscal_year
    sql = f"""
        WITH state_rows AS (
            SELECT *
            FROM {STATE_PROFILE_VIEW} AS p
            WHERE p.state_code = :state_code
              {fy_filter}
        ),
        national_rows AS (
            SELECT *
            FROM {STATE_PROFILE_VIEW} AS p
            WHERE 1 = 1
              {fy_filter}
        ),
        state_years AS (
            SELECT
                COUNT(DISTINCT fiscal_year)::numeric AS year_count,
                MIN(fiscal_year)::integer AS min_fiscal_year,
                MAX(fiscal_year)::integer AS max_fiscal_year
            FROM state_rows
        ),
        national_years AS (
            SELECT COUNT(DISTINCT fiscal_year)::numeric AS year_count
            FROM national_rows
        ),
        state_agg AS (
            SELECT
                CASE
                    WHEN :time_aggregation = 'multi_year_average' AND COALESCE(MAX(state_years.year_count), 0) > 0
                        THEN COALESCE(SUM({amount_expr}), 0)::numeric / MAX(state_years.year_count)
                    ELSE COALESCE(SUM({amount_expr}), 0)::numeric
                END AS total_funding,
                CASE
                    WHEN :time_aggregation = 'multi_year_average' AND COALESCE(MAX(state_years.year_count), 0) > 0
                        THEN COALESCE(SUM(p.core_cdc_program_funding), 0)::numeric / MAX(state_years.year_count)
                    ELSE COALESCE(SUM(p.core_cdc_program_funding), 0)::numeric
                END AS core_cdc_program_funding,
                CASE
                    WHEN :time_aggregation = 'multi_year_average' AND COALESCE(MAX(state_years.year_count), 0) > 0
                        THEN COALESCE(SUM(p.emergency_distributed_funding), 0)::numeric / MAX(state_years.year_count)
                    ELSE COALESCE(SUM(p.emergency_distributed_funding), 0)::numeric
                END AS emergency_distributed_funding,
                COALESCE(SUM(p.transaction_count), 0)::integer AS transaction_count,
                MAX(p.model_version) AS model_version,
                MAX(p.methodology_version) AS methodology_version,
                MAX(p.run_id) AS run_id,
                MAX(p.chip_rollout_status) AS chip_rollout_status,
                MAX(p.chip_state_profile_source_version) AS chip_state_profile_source_version,
                MAX(p.chip_normalization_source_version) AS chip_normalization_source_version,
                MAX(p.state) AS state_name,
                MAX(p.state_fips) AS state_fips
            FROM state_rows AS p
            CROSS JOIN state_years
        ),
        national_agg AS (
            SELECT
                CASE
                    WHEN :time_aggregation = 'multi_year_average' AND COALESCE(MAX(national_years.year_count), 0) > 0
                        THEN COALESCE(SUM({amount_expr}), 0)::numeric / MAX(national_years.year_count)
                    ELSE COALESCE(SUM({amount_expr}), 0)::numeric
                END AS national_total_funding
            FROM national_rows AS p
            CROSS JOIN national_years
        )
        SELECT
            state_agg.*,
            national_agg.national_total_funding,
            state_years.min_fiscal_year,
            state_years.max_fiscal_year
        FROM state_agg
        CROSS JOIN national_agg
        CROSS JOIN state_years
    """
    row = db.execute(text(sql), params).mappings().one_or_none()
    if row is None or (
        int(row.get("transaction_count") or 0) == 0
        and not str(row.get("state_name") or "").strip()
    ):
        raise HTTPException(status_code=404, detail=f"No v1.1 emergency state funding profile found for state {state_code}")
    return dict(row)


def _profile_payload(
    *,
    state_code: str,
    summary_row: dict[str, Any],
    fiscal_year: int | None,
    metric: str,
    funding_type: str,
    time_aggregation: str,
    population: float | None,
) -> dict[str, Any]:
    total_funding = _json_number(summary_row.get("total_funding"))
    national_total = _json_number(summary_row.get("national_total_funding"))
    timeframe_label = _timeframe_label(
        fiscal_year=fiscal_year,
        min_fiscal_year=summary_row.get("min_fiscal_year"),
        max_fiscal_year=summary_row.get("max_fiscal_year"),
        time_aggregation=time_aggregation,
    )
    return {
        "geography_type": "state",
        "geography_id": state_code,
        "geography_name": summary_row.get("state_name") or state_code,
        "state_code": state_code,
        "state_name": summary_row.get("state_name") or state_code,
        "fiscal_year": fiscal_year,
        "time_aggregation": time_aggregation,
        "timeframe_label": timeframe_label,
        "funding_mode_requested": CDCFundingMode.RAW_TOTAL.value,
        "funding_mode_effective": CDCFundingMode.RAW_TOTAL.value,
        "funding_mode_label": FUNDING_MODE_LABELS[CDCFundingMode.RAW_TOTAL.value],
        "total_funding": total_funding,
        "funding_per_capita": _metric_value(
            "funding_per_capita",
            total_funding=total_funding,
            population=population,
            national_total=national_total,
        ),
        "funding_per_100k": _metric_value(
            "funding_per_100k",
            total_funding=total_funding,
            population=population,
            national_total=national_total,
        ),
        "national_share": _metric_value(
            "share_national",
            total_funding=total_funding,
            population=population,
            national_total=national_total,
        ),
        "raw_total_funding": total_funding,
        "chip_normalized_funding": None,
        "raw_funding_per_capita": _metric_value(
            "funding_per_capita",
            total_funding=total_funding,
            population=population,
            national_total=national_total,
        ),
        "chip_normalized_funding_per_capita": None,
        "raw_funding_per_100k": _metric_value(
            "funding_per_100k",
            total_funding=total_funding,
            population=population,
            national_total=national_total,
        ),
        "chip_normalized_funding_per_100k": None,
        "raw_share_of_national": _metric_value(
            "share_national",
            total_funding=total_funding,
            population=population,
            national_total=national_total,
        ),
        "chip_normalized_share_of_national": None,
        "awards_total": None,
        "subawards_total": None,
        "contracts_total": None,
        "award_count": int(summary_row.get("transaction_count") or 0),
        "subaward_count": 0,
        "contract_award_count": 0,
        "population": population,
        "normalization_supported": False,
        "normalization_applied": False,
        "normalization_note": (
            "This raw state-profile payload reports the v1.1 emergency-classification totals directly. "
            "Use CHIP Normalized Funding v1.1 when you want the within-state distribution rescaled to the same benchmark."
        ),
        "normalization_factor": None,
        "normalized_amount_type": None,
        "normalization_status_label": None,
        "normalization_method": None,
        "funding_stream_logic_version": None,
        "methodology_version": str(summary_row.get("methodology_version") or METHODOLOGY_VERSION),
        "profile_version": PROFILE_VERSION,
        "funding_model_version": str(summary_row.get("model_version") or MODEL_VERSION),
        "metadata": {
            "metric_context": _filter_context(
                fiscal_year=fiscal_year,
                funding_type=funding_type,
                time_aggregation=time_aggregation,
            ),
            "chip_rollout_status": summary_row.get("chip_rollout_status") or ROLLOUT_STATUS,
            "chip_state_profile_source_version": summary_row.get("chip_state_profile_source_version") or STATE_PROFILE_SOURCE_VERSION,
            "chip_normalization_source_version": NORMALIZATION_SOURCE_VERSION,
            "run_id": summary_row.get("run_id"),
        },
    }


def _category_rows(
    db: Session,
    *,
    state_code: str,
    fiscal_year: int | None,
    funding_type: str,
    time_aggregation: str,
) -> list[dict[str, Any]]:
    fy_filter = "AND fiscal_year = :fiscal_year" if fiscal_year is not None else ""
    params: dict[str, Any] = {"state_code": state_code, "time_aggregation": time_aggregation}
    if fiscal_year is not None:
        params["fiscal_year"] = fiscal_year
    extra_filter = ""
    if funding_type == "emergency_response":
        extra_filter = "AND chip_funding_category = 'emergency_distributed'"
    elif funding_type == "non_emergency_program":
        extra_filter = "AND chip_funding_category = 'core_cdc_program'"
    sql = f"""
        WITH base AS (
            SELECT *
            FROM {FUNDING_CLASSIFICATION_VIEW}
            WHERE state_code = :state_code
              AND chip_include_in_state_profile IS TRUE
              {fy_filter}
              {extra_filter}
        ),
        year_stats AS (
            SELECT COUNT(DISTINCT fiscal_year)::numeric AS year_count
            FROM base
        )
        SELECT
            chip_funding_category,
            CASE
                WHEN :time_aggregation = 'multi_year_average' AND COALESCE(MAX(year_stats.year_count), 0) > 0
                    THEN COALESCE(SUM(raw_amount), 0)::numeric / MAX(year_stats.year_count)
                ELSE COALESCE(SUM(raw_amount), 0)::numeric
            END AS amount,
            COUNT(*)::integer AS transaction_count,
            COUNT(DISTINCT recipient_name_normalized)::integer AS subgroup_count
        FROM base
        CROSS JOIN year_stats
        GROUP BY chip_funding_category
        ORDER BY amount DESC NULLS LAST, chip_funding_category ASC
    """
    return [dict(row) for row in db.execute(text(sql), params).mappings().all()]


def _subcategory_rows(
    db: Session,
    *,
    state_code: str,
    fiscal_year: int | None,
    funding_type: str,
    time_aggregation: str,
) -> list[dict[str, Any]]:
    fy_filter = "AND fiscal_year = :fiscal_year" if fiscal_year is not None else ""
    params: dict[str, Any] = {"state_code": state_code, "time_aggregation": time_aggregation}
    if fiscal_year is not None:
        params["fiscal_year"] = fiscal_year
    extra_filter = ""
    if funding_type == "emergency_response":
        extra_filter = "AND chip_funding_category = 'emergency_distributed'"
    elif funding_type == "non_emergency_program":
        extra_filter = "AND chip_funding_category = 'core_cdc_program'"
    sql = f"""
        WITH base AS (
            SELECT
                chip_funding_category,
                CASE
                    WHEN chip_recipient_is_state_like THEN 'state_like'
                    WHEN chip_recipient_is_local_public_health_like THEN 'local_public_health_like'
                    WHEN chip_recipient_is_public_university_like THEN 'public_university_candidate'
                    WHEN chip_recipient_is_intermediary_like THEN 'intermediary'
                    ELSE 'other'
                END AS recipient_group,
                raw_amount,
                fiscal_year
            FROM {FUNDING_CLASSIFICATION_VIEW}
            WHERE state_code = :state_code
              AND chip_include_in_state_profile IS TRUE
              {fy_filter}
              {extra_filter}
        ),
        year_stats AS (
            SELECT COUNT(DISTINCT fiscal_year)::numeric AS year_count
            FROM base
        )
        SELECT
            chip_funding_category,
            recipient_group,
            CASE
                WHEN :time_aggregation = 'multi_year_average' AND COALESCE(MAX(year_stats.year_count), 0) > 0
                    THEN COALESCE(SUM(raw_amount), 0)::numeric / MAX(year_stats.year_count)
                ELSE COALESCE(SUM(raw_amount), 0)::numeric
            END AS amount,
            COUNT(*)::integer AS transaction_count
        FROM base
        CROSS JOIN year_stats
        GROUP BY chip_funding_category, recipient_group
        ORDER BY chip_funding_category ASC, amount DESC NULLS LAST, recipient_group ASC
    """
    return [dict(row) for row in db.execute(text(sql), params).mappings().all()]


def fetch_state_profile_overview(
    db: Session,
    *,
    state: str,
    fiscal_year: int | None = None,
    metric: str | None = None,
    funding_type: str | None = None,
    funding_mode: str | None = None,
    cdc_center: str | None = None,
    program_area: str | None = None,
    mechanism: str | None = None,
    recipient_type: str | None = None,
    time_aggregation: str | None = None,
) -> dict[str, Any]:
    support = support_status(
        funding_mode=funding_mode,
        funding_type=funding_type,
        cdc_center=cdc_center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
    )
    if not support.enabled:
        raise HTTPException(status_code=409, detail=f"v1.1 emergency raw state profile path unavailable: {support.reason}")
    _ensure_required_views(db)
    state_code = _normalize_state_code(state)
    metric_token = _normalize_metric(metric)
    fy = _normalize_optional_fiscal_year(fiscal_year)
    funding_type_token = _normalize_funding_type(funding_type)
    aggregation = _normalize_time_aggregation(time_aggregation)
    summary_row = _summary_row(
        db,
        state_code=state_code,
        fiscal_year=fy,
        funding_type=funding_type_token,
        time_aggregation=aggregation,
    )
    population = _state_population(db, state_code)
    profile = _profile_payload(
        state_code=state_code,
        summary_row=summary_row,
        fiscal_year=fy,
        metric=metric_token,
        funding_type=funding_type_token,
        time_aggregation=aggregation,
        population=population,
    )
    selected_metric_value = _metric_value(
        metric_token,
        total_funding=profile["total_funding"],
        population=population,
        national_total=_json_number(summary_row.get("national_total_funding")),
    )
    category_rows = _category_rows(
        db,
        state_code=state_code,
        fiscal_year=fy,
        funding_type=funding_type_token,
        time_aggregation=aggregation,
    )
    subcategory_rows = _subcategory_rows(
        db,
        state_code=state_code,
        fiscal_year=fy,
        funding_type=funding_type_token,
        time_aggregation=aggregation,
    )
    category_total_by_key = {
        str(row["chip_funding_category"]): _json_number(row.get("amount")) or 0.0
        for row in category_rows
    }
    timeframe_label = profile["timeframe_label"]
    filter_context = _filter_context(
        fiscal_year=fy,
        funding_type=funding_type_token,
        time_aggregation=aggregation,
    )
    summary_payload = {
        "state_code": state_code,
        "state_name": profile["state_name"],
        "fiscal_year": fy,
        "time_aggregation": aggregation,
        "timeframe_label": timeframe_label,
        "funding_mode_requested": profile["funding_mode_requested"],
        "funding_mode_effective": profile["funding_mode_effective"],
        "funding_mode_label": profile["funding_mode_label"],
        "selected_metric": metric_token,
        "selected_metric_label": METRIC_LABELS[metric_token],
        "selected_metric_value": selected_metric_value,
        "profile": profile,
        "raw_total_funding": profile["raw_total_funding"],
        "chip_normalized_funding": None,
        "chip_total_funding": None,
        "chip_per_capita_funding": None,
        "chip_per_100k_funding": None,
        "chip_share_of_national": None,
        "chip_equity_adjusted_metrics": {},
        "total_funding": profile["total_funding"],
        "funding_per_capita": profile["funding_per_capita"],
        "funding_per_100k": profile["funding_per_100k"],
        "share_national_pct": profile["national_share"],
        "population": profile["population"],
        "awards_amount": None,
        "subawards_amount": None,
        "contracts_amount": None,
        "award_count": profile["award_count"],
        "subaward_count": 0,
        "contract_award_count": 0,
        "normalization_supported": False,
        "normalization_applied": False,
        "normalization_note": profile["normalization_note"],
        "normalization_factor": None,
        "normalized_amount_type": None,
        "normalization_status_label": None,
        "normalization_method": None,
        "funding_stream_logic_version": None,
        "methodology_version": profile["methodology_version"],
        "profile_version": profile["profile_version"],
        "funding_model_version": profile["funding_model_version"],
        "chip_rollout_status": profile["metadata"]["chip_rollout_status"],
        "chip_state_profile_source_version": profile["metadata"]["chip_state_profile_source_version"],
        "chip_normalization_source_version": profile["metadata"]["chip_normalization_source_version"],
        "run_id": profile["metadata"]["run_id"],
        "top_program_area": (
            {
                "value": category_rows[0]["chip_funding_category"],
                "label": FUNDING_CATEGORY_LABELS.get(category_rows[0]["chip_funding_category"], category_rows[0]["chip_funding_category"]),
                "amount": _json_number(category_rows[0].get("amount")),
                "chip_total_funding": _json_number(category_rows[0].get("amount")),
            }
            if category_rows
            else None
        ),
        "grouping": {
            "category_label": "Funding Category",
            "subcategory_label": "Recipient Classification",
            "count_label": "Transactions",
            "subcategory_count_label": "Recipient Groups",
            "category_method": "Rows are grouped into core CDC program funding and emergency distributed funding from the SQL-first emergency-classification layer. Emergency centralized and unresolved excluded rows stay outside the state profile.",
            "subcategory_method": "Recipient breakdown uses curated intermediary overrides first, then normalized-name matches, then narrow heuristic rules. Public universities are treated as candidates and can still be excluded when they look intermediary-like.",
        },
        "legend_title": _legend_title(metric=metric_token, timeframe_label=timeframe_label),
        "filter_context": filter_context,
        "methodology_notes": [
            "This state profile uses CHIP's v1.1 emergency-classification raw-total layer.",
            "The rollout is still partial: raw state-profile totals use the v1.1 emergency-classification source, and CHIP Normalized Funding v1.1 now rescales to that state benchmark while the legacy normalized mode remains available for comparison.",
            "Emergency centralized funding is preserved for transparency but excluded from state totals when recipient geography is not a reliable proxy for final use geography.",
        ],
    }
    categories_payload = {
        "state_code": state_code,
        "profile": profile,
        "funding_mode_requested": profile["funding_mode_requested"],
        "funding_mode_effective": profile["funding_mode_effective"],
        "funding_mode_label": profile["funding_mode_label"],
        "methodology_version": profile["methodology_version"],
        "profile_version": profile["profile_version"],
        "funding_model_version": profile["funding_model_version"],
        "chip_rollout_status": profile["metadata"]["chip_rollout_status"],
        "chip_state_profile_source_version": profile["metadata"]["chip_state_profile_source_version"],
        "chip_normalization_source_version": profile["metadata"]["chip_normalization_source_version"],
        "run_id": profile["metadata"]["run_id"],
        "rows": [
            {
                "geography_id": state_code,
                "category": FUNDING_CATEGORY_LABELS.get(row["chip_funding_category"], row["chip_funding_category"]),
                "category_value": row["chip_funding_category"],
                "chip_total_funding": _json_number(row.get("amount")),
                "amount": _json_number(row.get("amount")),
                "share_pct": _metric_value(
                    "share_national",
                    total_funding=_json_number(row.get("amount")),
                    population=population,
                    national_total=profile["total_funding"],
                )
                or 0.0,
                "award_count": int(row.get("transaction_count") or 0),
                "subcategory_count": int(row.get("subgroup_count") or 0),
            }
            for row in category_rows
        ],
        "grouping": summary_payload["grouping"],
        "filter_context": filter_context,
    }
    subcategories_payload = {
        "state_code": state_code,
        "profile": profile,
        "funding_mode_requested": profile["funding_mode_requested"],
        "funding_mode_effective": profile["funding_mode_effective"],
        "funding_mode_label": profile["funding_mode_label"],
        "methodology_version": profile["methodology_version"],
        "profile_version": profile["profile_version"],
        "funding_model_version": profile["funding_model_version"],
        "chip_rollout_status": profile["metadata"]["chip_rollout_status"],
        "chip_state_profile_source_version": profile["metadata"]["chip_state_profile_source_version"],
        "chip_normalization_source_version": profile["metadata"]["chip_normalization_source_version"],
        "run_id": profile["metadata"]["run_id"],
        "rows": [
            {
                "geography_id": state_code,
                "category": FUNDING_CATEGORY_LABELS.get(row["chip_funding_category"], row["chip_funding_category"]),
                "category_value": row["chip_funding_category"],
                "subcategory": RECIPIENT_TYPE_LABELS.get(row["recipient_group"], row["recipient_group"]),
                "chip_total_funding": _json_number(row.get("amount")),
                "amount": _json_number(row.get("amount")),
                "award_count": int(row.get("transaction_count") or 0),
                "share_total_pct": _metric_value(
                    "share_national",
                    total_funding=_json_number(row.get("amount")),
                    population=population,
                    national_total=profile["total_funding"],
                )
                or 0.0,
                "share_category_pct": _metric_value(
                    "share_national",
                    total_funding=_json_number(row.get("amount")),
                    population=population,
                    national_total=category_total_by_key.get(str(row["chip_funding_category"])),
                )
                or 0.0,
            }
            for row in subcategory_rows
        ],
        "grouping": summary_payload["grouping"],
        "filter_context": filter_context,
    }
    return {
        "summary": summary_payload,
        "categories": categories_payload,
        "subcategories": subcategories_payload,
    }


def fetch_state_profile_details(
    db: Session,
    *,
    state: str,
    fiscal_year: int | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "amount",
    sort_dir: str = "desc",
) -> dict[str, Any]:
    _ensure_required_views(db)
    state_code = _normalize_state_code(state)
    fy = _normalize_optional_fiscal_year(fiscal_year)
    allowed_columns = {
        "category": "chip_funding_category",
        "subcategory": "recipient_type",
        "project_title": "chip_classification_reason",
        "grantee_name": "recipient_name_raw",
        "amount": "raw_amount",
        "latest_action_date": "source_transaction_id",
        "fain": "source_transaction_id",
    }
    normalized_sort_by = str(sort_by or "amount").strip().lower()
    if normalized_sort_by not in allowed_columns:
        normalized_sort_by = "amount"
    normalized_sort_dir = str(sort_dir or "desc").strip().lower()
    if normalized_sort_dir not in {"asc", "desc"}:
        normalized_sort_dir = "desc"
    params: dict[str, Any] = {
        "state_code": state_code,
        "limit": max(1, min(int(page_size), 200)),
        "offset": max(0, (max(1, int(page)) - 1) * max(1, min(int(page_size), 200))),
    }
    fy_filter = "AND c.fiscal_year = :fiscal_year" if fy is not None else ""
    if fy is not None:
        params["fiscal_year"] = fy
    search_sql = ""
    if str(q or "").strip():
        params["q"] = f"%{str(q).strip().lower()}%"
        search_sql = (
            "AND (LOWER(COALESCE(c.recipient_name_raw, '')) LIKE :q "
            "OR LOWER(COALESCE(c.chip_classification_reason, '')) LIKE :q "
            "OR LOWER(COALESCE(c.chip_funding_category, '')) LIKE :q "
            "OR LOWER(COALESCE(c.recipient_type, '')) LIKE :q)"
        )
    base_sql = f"""
        FROM {FUNDING_CLASSIFICATION_VIEW} AS c
        WHERE c.state_code = :state_code
          AND c.chip_include_in_state_profile IS TRUE
          {fy_filter}
          {search_sql}
    """
    total_rows = int(
        db.execute(
            text(f"SELECT COUNT(*)::integer AS total_count {base_sql}"),
            params,
        ).mappings().one()["total_count"]
    )
    sql = f"""
        SELECT
            c.source_system || ':' || c.source_transaction_id AS record_id,
            'classified_transaction'::text AS record_type,
            NULL::text AS fain,
            c.recipient_name_raw AS grantee_name,
            NULL::text AS city,
            NULL::text AS county,
            c.chip_funding_category AS category,
            COALESCE(c.recipient_type, c.recipient_classification_source, 'unclassified') AS subcategory,
            c.chip_classification_reason AS project_title,
            c.raw_amount AS amount,
            c.fiscal_year AS min_fiscal_year,
            c.fiscal_year AS max_fiscal_year,
            NULL::date AS latest_action_date,
            c.state AS state_name,
            c.state_code,
            NULL::text AS usaspending_permalink,
            NULL::numeric AS lifetime_total_funding_amount
        {base_sql}
        ORDER BY {allowed_columns[normalized_sort_by]} {normalized_sort_dir}, c.source_transaction_id ASC
        LIMIT :limit
        OFFSET :offset
    """
    rows = [dict(row) for row in db.execute(text(sql), params).mappings().all()]
    for index, row in enumerate(rows, start=params["offset"] + 1):
        row["line_number"] = index
        row["category"] = FUNDING_CATEGORY_LABELS.get(str(row.get("category") or ""), row.get("category"))
        row["subcategory"] = RECIPIENT_TYPE_LABELS.get(str(row.get("subcategory") or ""), row.get("subcategory"))
    return {
        "state_code": state_code,
        "page": max(1, int(page)),
        "page_size": params["limit"],
        "total_rows": total_rows,
        "rows": rows,
        "funding_mode_requested": CDCFundingMode.RAW_TOTAL.value,
        "funding_mode_effective": CDCFundingMode.RAW_TOTAL.value,
        "funding_mode_label": FUNDING_MODE_LABELS[CDCFundingMode.RAW_TOTAL.value],
        "funding_model_version": MODEL_VERSION,
        "profile_version": PROFILE_VERSION,
        "chip_rollout_status": ROLLOUT_STATUS,
        "chip_state_profile_source_version": STATE_PROFILE_SOURCE_VERSION,
        "chip_normalization_source_version": NORMALIZATION_SOURCE_VERSION,
    }


def _bbox_params(bbox: str | None) -> dict[str, float] | None:
    token = str(bbox or "").strip()
    if not token:
        return None
    parts = [part.strip() for part in token.split(",")]
    if len(parts) != 4:
        raise HTTPException(status_code=400, detail="bbox must be minx,miny,maxx,maxy")
    try:
        minx, miny, maxx, maxy = (float(part) for part in parts)
    except ValueError as exc:  # pragma: no cover - defensive path
        raise HTTPException(status_code=400, detail="bbox must contain numeric values") from exc
    return {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy}


def _raw_only_normalization_note() -> str:
    return (
        "This raw state-profile payload reports the v1.1 emergency-classification totals directly. "
        "Use CHIP Normalized Funding v1.1 when you want the within-state distribution rescaled to the same benchmark."
    )


def fetch_state_geography_rows(
    db: Session,
    *,
    fiscal_year: int | None = None,
    funding_type: str | None = None,
    time_aggregation: str | None = None,
    include_geometry: bool = False,
    bbox: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    _ensure_required_views(db)
    fy = _normalize_optional_fiscal_year(fiscal_year)
    funding_type_token = _normalize_funding_type(funding_type)
    aggregation = _normalize_time_aggregation(time_aggregation)
    amount_expr = _amount_sql_for_funding_type("p", funding_type_token)
    params: dict[str, Any] = {
        "time_aggregation": aggregation,
        "limit": max(1, min(int(limit), 10000)),
        "simplify_degrees": 0.04,
    }
    fy_filter = "AND p.fiscal_year = :fiscal_year" if fy is not None else ""
    if fy is not None:
        params["fiscal_year"] = fy
    bbox_filter = ""
    bbox_args = _bbox_params(bbox)
    if bbox_args is not None:
        params.update(bbox_args)
        bbox_filter = (
            "AND sb.geom && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) "
            "AND ST_Intersects(sb.geom, ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326))"
        )
    select_geometry = (
        "ST_AsGeoJSON(ST_SimplifyPreserveTopology(sb.geom, :simplify_degrees), 6)::json AS geometry,"
        if include_geometry
        else "NULL::json AS geometry,"
    )
    sql = f"""
        WITH base AS (
            SELECT *
            FROM {STATE_PROFILE_VIEW} AS p
            WHERE 1 = 1
              {fy_filter}
        ),
        year_stats AS (
            SELECT
                COUNT(DISTINCT fiscal_year)::numeric AS year_count,
                MIN(fiscal_year)::integer AS min_fiscal_year,
                MAX(fiscal_year)::integer AS max_fiscal_year
            FROM base
        ),
        adjusted AS (
            SELECT
                p.state_code,
                MAX(p.state_fips) AS state_fips,
                MAX(p.state) AS state_name,
                CASE
                    WHEN :time_aggregation = 'multi_year_average' AND COALESCE(MAX(year_stats.year_count), 0) > 0
                        THEN COALESCE(SUM({amount_expr}), 0)::numeric / MAX(year_stats.year_count)
                    ELSE COALESCE(SUM({amount_expr}), 0)::numeric
                END AS total_amount,
                COALESCE(SUM(p.transaction_count), 0)::integer AS transaction_count,
                MAX(p.model_version) AS model_version,
                MAX(p.methodology_version) AS methodology_version,
                MAX(p.run_id) AS run_id,
                MAX(p.chip_rollout_status) AS chip_rollout_status,
                MAX(p.chip_state_profile_source_version) AS chip_state_profile_source_version,
                MAX(p.chip_normalization_source_version) AS chip_normalization_source_version
            FROM base AS p
            CROSS JOIN year_stats
            GROUP BY p.state_code
        ),
        national_total AS (
            SELECT COALESCE(SUM(total_amount), 0)::numeric AS national_total_funding
            FROM adjusted
        )
        SELECT
            sb.state_abbr AS geography_id,
            COALESCE(sb.state_name, sb.state_abbr) AS geography_name,
            sb.state_abbr AS state_code,
            COALESCE(sb.state_name, sb.state_abbr) AS state_name,
            adjusted.state_fips,
            adjusted.total_amount,
            adjusted.transaction_count,
            adjusted.model_version,
            adjusted.methodology_version,
            adjusted.run_id,
            adjusted.chip_rollout_status,
            adjusted.chip_state_profile_source_version,
            adjusted.chip_normalization_source_version,
            year_stats.min_fiscal_year,
            year_stats.max_fiscal_year,
            national_total.national_total_funding,
            pop.population::numeric AS population,
            {select_geometry}
            COALESCE(adjusted.total_amount, 0)::numeric AS raw_total_amount
        FROM {STATE_DIM_TABLE} AS sb
        LEFT JOIN adjusted
          ON adjusted.state_code = sb.state_abbr
        LEFT JOIN {POPULATION_VIEW_TABLE} AS pop
          ON pop.geography_type = 'state'
         AND UPPER(pop.state_abbr) = sb.state_abbr
        CROSS JOIN year_stats
        CROSS JOIN national_total
        WHERE sb.geom IS NOT NULL
          {bbox_filter}
        ORDER BY sb.state_abbr
        LIMIT :limit
    """
    rows = [dict(row) for row in db.execute(text(sql), params).mappings().all()]
    note = _raw_only_normalization_note()
    output: list[dict[str, Any]] = []
    for row in rows:
        total_funding = _json_number(row.get("total_amount"))
        national_total = _json_number(row.get("national_total_funding"))
        population = _json_number(row.get("population"))
        per_capita = _metric_value(
            "funding_per_capita",
            total_funding=total_funding,
            population=population,
            national_total=national_total,
        )
        per_100k = _metric_value(
            "funding_per_100k",
            total_funding=total_funding,
            population=population,
            national_total=national_total,
        )
        share = _metric_value(
            "share_national",
            total_funding=total_funding,
            population=population,
            national_total=national_total,
        )
        output.append(
            {
                "geography_id": row.get("geography_id"),
                "geography_name": row.get("geography_name"),
                "state_code": row.get("state_code"),
                "state_name": row.get("state_name"),
                "state_fips": row.get("state_fips"),
                "min_fiscal_year": row.get("min_fiscal_year"),
                "max_fiscal_year": row.get("max_fiscal_year"),
                "population": population,
                "geometry": row.get("geometry"),
                "funding_mode_requested": CDCFundingMode.RAW_TOTAL.value,
                "funding_mode_effective": CDCFundingMode.RAW_TOTAL.value,
                "funding_mode_label": FUNDING_MODE_LABELS[CDCFundingMode.RAW_TOTAL.value],
                "raw_total_funding": total_funding,
                "chip_normalized_funding": None,
                "total_funding_amount": total_funding,
                "funding_per_capita": per_capita,
                "funding_per_100k": per_100k,
                "share_national_pct": share,
                "raw_funding_per_capita": per_capita,
                "chip_normalized_funding_per_capita": None,
                "raw_funding_per_100k": per_100k,
                "chip_normalized_funding_per_100k": None,
                "raw_share_of_national": share,
                "chip_normalized_share_of_national": None,
                "chip_total_funding": total_funding,
                "chip_per_capita_funding": per_capita,
                "chip_per_100k_funding": per_100k,
                "chip_share_of_national": share,
                "award_count": int(row.get("transaction_count") or 0),
                "subaward_count": 0,
                "contract_award_count": 0,
                "awards_amount": total_funding,
                "subawards_amount": 0.0 if total_funding is not None else None,
                "contracts_amount": 0.0 if total_funding is not None else None,
                "normalization_supported": False,
                "normalization_applied": False,
                "normalization_note": note,
                "normalization_factor": None,
                "normalized_amount_type": None,
                "normalization_status_label": None,
                "normalization_method": None,
                "funding_stream_logic_version": None,
                "methodology_version": row.get("methodology_version") or METHODOLOGY_VERSION,
                "profile_version": PROFILE_VERSION,
                "funding_model_version": row.get("model_version") or MODEL_VERSION,
                "chip_rollout_status": row.get("chip_rollout_status") or ROLLOUT_STATUS,
                "chip_state_profile_source_version": row.get("chip_state_profile_source_version")
                or STATE_PROFILE_SOURCE_VERSION,
                "chip_normalization_source_version": NORMALIZATION_SOURCE_VERSION,
                "run_id": row.get("run_id"),
            }
        )
    return output


def fetch_national_summary_row(
    db: Session,
    *,
    fiscal_year: int | None = None,
    funding_type: str | None = None,
    time_aggregation: str | None = None,
) -> dict[str, Any]:
    _ensure_required_views(db)
    fy = _normalize_optional_fiscal_year(fiscal_year)
    funding_type_token = _normalize_funding_type(funding_type)
    aggregation = _normalize_time_aggregation(time_aggregation)
    amount_expr = _amount_sql_for_funding_type("p", funding_type_token)
    params: dict[str, Any] = {"time_aggregation": aggregation}
    fy_filter = "AND p.fiscal_year = :fiscal_year" if fy is not None else ""
    if fy is not None:
        params["fiscal_year"] = fy
    sql = f"""
        WITH base AS (
            SELECT *
            FROM {STATE_PROFILE_VIEW} AS p
            WHERE 1 = 1
              {fy_filter}
        ),
        year_stats AS (
            SELECT
                COUNT(DISTINCT fiscal_year)::numeric AS year_count,
                MIN(fiscal_year)::integer AS min_fiscal_year,
                MAX(fiscal_year)::integer AS max_fiscal_year
            FROM base
        )
        SELECT
            CASE
                WHEN :time_aggregation = 'multi_year_average' AND COALESCE(MAX(year_stats.year_count), 0) > 0
                    THEN COALESCE(SUM({amount_expr}), 0)::numeric / MAX(year_stats.year_count)
                ELSE COALESCE(SUM({amount_expr}), 0)::numeric
            END AS total_amount,
            COALESCE(SUM(p.transaction_count), 0)::integer AS transaction_count,
            MAX(p.model_version) AS model_version,
            MAX(p.methodology_version) AS methodology_version,
            MAX(p.run_id) AS run_id,
            MAX(p.chip_rollout_status) AS chip_rollout_status,
            MAX(p.chip_state_profile_source_version) AS chip_state_profile_source_version,
            MAX(p.chip_normalization_source_version) AS chip_normalization_source_version,
            MAX(year_stats.min_fiscal_year) AS min_fiscal_year,
            MAX(year_stats.max_fiscal_year) AS max_fiscal_year
        FROM base AS p
        CROSS JOIN year_stats
    """
    row = dict(db.execute(text(sql), params).mappings().one())
    population_row = db.execute(
        text(
            f"""
            SELECT population
            FROM {POPULATION_VIEW_TABLE}
            WHERE geography_type = 'nation'
              AND geography_id = 'US'
            LIMIT 1
            """
        )
    ).mappings().one_or_none()
    total_funding = _json_number(row.get("total_amount"))
    population = _json_number(population_row.get("population") if population_row else None)
    per_capita = _metric_value(
        "funding_per_capita",
        total_funding=total_funding,
        population=population,
        national_total=total_funding,
    )
    per_100k = _metric_value(
        "funding_per_100k",
        total_funding=total_funding,
        population=population,
        national_total=total_funding,
    )
    share = 100.0 if total_funding not in (None, 0.0) else None
    note = _raw_only_normalization_note()
    return {
        "geography_id": "US",
        "geography_name": "United States",
        "state_code": "US",
        "state_name": "United States",
        "population": population,
        "min_fiscal_year": row.get("min_fiscal_year"),
        "max_fiscal_year": row.get("max_fiscal_year"),
        "funding_mode_requested": CDCFundingMode.RAW_TOTAL.value,
        "funding_mode_effective": CDCFundingMode.RAW_TOTAL.value,
        "funding_mode_label": FUNDING_MODE_LABELS[CDCFundingMode.RAW_TOTAL.value],
        "raw_total_funding": total_funding,
        "chip_normalized_funding": None,
        "total_funding_amount": total_funding,
        "funding_per_capita": per_capita,
        "funding_per_100k": per_100k,
        "share_national_pct": share,
        "raw_funding_per_capita": per_capita,
        "chip_normalized_funding_per_capita": None,
        "raw_funding_per_100k": per_100k,
        "chip_normalized_funding_per_100k": None,
        "raw_share_of_national": share,
        "chip_normalized_share_of_national": None,
        "chip_total_funding": total_funding,
        "chip_per_capita_funding": per_capita,
        "chip_per_100k_funding": per_100k,
        "chip_share_of_national": share,
        "award_count": int(row.get("transaction_count") or 0),
        "subaward_count": 0,
        "contract_award_count": 0,
        "awards_amount": total_funding,
        "subawards_amount": 0.0 if total_funding is not None else None,
        "contracts_amount": 0.0 if total_funding is not None else None,
        "normalization_supported": False,
        "normalization_applied": False,
        "normalization_note": note,
        "normalization_factor": None,
        "normalized_amount_type": None,
        "normalization_status_label": None,
        "normalization_method": None,
        "funding_stream_logic_version": None,
        "methodology_version": row.get("methodology_version") or METHODOLOGY_VERSION,
        "profile_version": PROFILE_VERSION,
        "funding_model_version": row.get("model_version") or MODEL_VERSION,
        "chip_rollout_status": row.get("chip_rollout_status") or ROLLOUT_STATUS,
        "chip_state_profile_source_version": row.get("chip_state_profile_source_version")
        or STATE_PROFILE_SOURCE_VERSION,
        "chip_normalization_source_version": NORMALIZATION_SOURCE_VERSION,
        "run_id": row.get("run_id"),
    }
