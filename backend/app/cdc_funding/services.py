from __future__ import annotations

import json
import math
import re
from datetime import date
from decimal import Decimal
from numbers import Real
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.cdc_funding.appropriation import (
    APPROPRIATION_FILTER_ALL,
    APPROPRIATION_FILTER_VALUES,
    APPROPRIATION_TYPE_COVID_EMERGENCY,
    APPROPRIATION_TYPE_OTHER_EMERGENCY,
    APPROPRIATION_TYPE_REGULAR,
    APPROPRIATION_TYPE_UNKNOWN,
)
from app.db_fqtn import cdc_funding_table, places_table
from app.recon.normalization import (
    build_normalization_note,
    fetch_state_normalization_lookup,
    usaspending_normalization_compatibility,
)
from app.recon.profile_calibration import METHODOLOGY_VERSION as PROFILE_CALIBRATION_METHODOLOGY_VERSION
from app.services.chip_funding_model import (
    CDCFundingMode,
    FUNDING_MODE_LABELS,
    normalization_lookup_variant_for_mode,
)

PRIME_TABLE = cdc_funding_table("prime_awards")
PRIME_TX_TABLE = cdc_funding_table("prime_transactions")
SUBAWARD_TABLE = cdc_funding_table("subawards")
PRIME_STATE_SUMMARY_TABLE = cdc_funding_table("prime_state_summary")
PRIME_COUNTY_SUMMARY_TABLE = cdc_funding_table("prime_county_summary")
PRIME_TX_STATE_SUMMARY_TABLE = cdc_funding_table("prime_transaction_state_summary")
PRIME_TX_COUNTY_SUMMARY_TABLE = cdc_funding_table("prime_transaction_county_summary")
PRIME_TX_COUNTY_ALLOCATED_SUMMARY_TABLE = cdc_funding_table("prime_transaction_county_summary_allocated")
PRIME_TX_NATIONAL_SUMMARY_TABLE = cdc_funding_table("prime_transaction_national_summary")
SUBAWARD_STATE_SUMMARY_TABLE = cdc_funding_table("subaward_state_summary")
SUBAWARD_COUNTY_SUMMARY_TABLE = cdc_funding_table("subaward_county_summary")
SUBAWARD_NATIONAL_SUMMARY_TABLE = cdc_funding_table("subaward_national_summary")
AWARD_SCOPE_CLASSIFICATION_TABLE = cdc_funding_table("award_scope_classification")
APPROPRIATION_CLASSIFICATION_TABLE = cdc_funding_table("appropriation_classification")
COUNTY_BOUNDARY_TABLE = places_table("dim_county_boundary")
COUNTY_DIM_TABLE = places_table("dim_county")
STATE_BOUNDARY_TABLE = places_table("dim_state_boundary")
POPULATION_VIEW_TABLE = places_table("v_geography_population")

VALID_BASIS = {"prime", "subaward", "all"}
VALID_GEOGRAPHY = {"state", "county"}
VALID_METRICS = {
    "fy_obligated",
    "fy_outlayed_estimated",
    "transaction_count",
    "distinct_award_count",
    "total_subaward",
    "subaward_count",
}
VALID_SCOPE_CLASSIFICATIONS = {
    "local_county",
    "statewide",
    "multi_county",
    "multi_state",
    "unknown",
}
VALID_FUNDING_GEOGRAPHY_MODES = {
    "recipient_location",
    "statewide_allocation",
}
VALID_DISPLAY_MODES = {
    "total",
    "per_capita",
}

PRIME_METRICS = {
    "fy_obligated": "fy_obligated_amount",
    "fy_outlayed_estimated": "fy_outlayed_amount_estimated",
    "transaction_count": "transaction_count",
    "distinct_award_count": "distinct_award_count",
}

SUBAWARD_METRICS = {
    "total_subaward": "total_subaward_amount",
    "subaward_count": "subaward_count",
}

DOLLAR_METRICS = {
    "fy_obligated",
    "fy_outlayed_estimated",
    "total_subaward",
}

PER_CAPITA_COLUMN_BY_METRIC = {
    "fy_obligated": "fy_obligated_per_capita",
    "fy_outlayed_estimated": "fy_outlayed_amount_estimated_per_capita",
    "total_subaward": "total_subaward_per_capita",
}

METRIC_LABELS = {
    "fy_obligated": "Fiscal Year Obligated",
    "fy_outlayed_estimated": "Estimated Fiscal Year Outlayed",
    "transaction_count": "Transaction Count",
    "distinct_award_count": "Distinct Awards",
    "total_subaward": "Total Subaward Amount",
    "subaward_count": "Subaward Count",
}

APPROPRIATION_FILTER_LABELS = {
    APPROPRIATION_FILTER_ALL: "All funding",
    APPROPRIATION_TYPE_REGULAR: "Regular appropriations",
    APPROPRIATION_TYPE_COVID_EMERGENCY: "COVID / emergency supplemental",
    APPROPRIATION_TYPE_OTHER_EMERGENCY: "Other emergency/disaster funding",
    APPROPRIATION_TYPE_UNKNOWN: "Unknown/uncoded funding",
}

TREND_DEFAULT_START_FY = 2020
TREND_DEFAULT_END_FY = 2026
REPO_ROOT = Path(__file__).resolve().parents[3]
METHODOLOGY_DISPLAY_SUMMARY_PATH = REPO_ROOT / "data" / "recon" / "methodology_display_summary.json"


def _current_federal_fiscal_year(*, as_of: date | None = None) -> int:
    reference_date = as_of or date.today()
    return reference_date.year + 1 if reference_date.month >= 10 else reference_date.year


def _latest_completed_federal_fiscal_year(*, as_of: date | None = None) -> int:
    return _current_federal_fiscal_year(as_of=as_of) - 1


def fetch_methodology_display_summary() -> dict[str, Any]:
    if not METHODOLOGY_DISPLAY_SUMMARY_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                f"Required methodology artifact {METHODOLOGY_DISPLAY_SUMMARY_PATH.name} is missing. "
                "Rebuild the CDC funding normalization diagnostics."
            ),
        )
    payload = json.loads(METHODOLOGY_DISPLAY_SUMMARY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=500,
            detail="Methodology summary artifact is not a JSON object.",
        )
    return payload


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
    row = db.execute(
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
    ).mappings().one()
    return bool(row.get("exists"))


def _ensure_award_tables(db: Session) -> None:
    required = [PRIME_TABLE, PRIME_TX_TABLE, SUBAWARD_TABLE]
    for table_name in required:
        if not _table_exists(db, table_name):
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Required table {table_name} is missing. "
                    "Run migrations and CDC funding ingestion."
                ),
            )


def _ensure_scope_classification_table(db: Session) -> None:
    if not _table_exists(db, AWARD_SCOPE_CLASSIFICATION_TABLE):
        raise HTTPException(
            status_code=503,
            detail=(
                f"Required table {AWARD_SCOPE_CLASSIFICATION_TABLE} is missing. "
                "Run migrations and CDC funding ingestion."
            ),
        )


def _ensure_appropriation_classification_table(db: Session) -> None:
    if not _table_exists(db, APPROPRIATION_CLASSIFICATION_TABLE):
        raise HTTPException(
            status_code=503,
            detail=(
                f"Required table {APPROPRIATION_CLASSIFICATION_TABLE} is missing. "
                "Run migrations and CDC funding ingestion."
            ),
        )


def _ensure_required_tables(
    db: Session,
    *,
    basis: str,
    geography: str,
    funding_geography_mode: str = "recipient_location",
    include_national: bool = False,
) -> None:
    required = (
        [
            PRIME_TX_STATE_SUMMARY_TABLE,
            (
                PRIME_TX_COUNTY_ALLOCATED_SUMMARY_TABLE
                if geography == "county" and funding_geography_mode == "statewide_allocation"
                else PRIME_TX_COUNTY_SUMMARY_TABLE
            ),
        ]
        if basis == "prime"
        else [SUBAWARD_STATE_SUMMARY_TABLE, SUBAWARD_COUNTY_SUMMARY_TABLE]
    )
    if include_national:
        required.append(
            PRIME_TX_NATIONAL_SUMMARY_TABLE
            if basis == "prime"
            else SUBAWARD_NATIONAL_SUMMARY_TABLE
        )
    _ensure_award_tables(db)
    if geography == "county":
        required.extend([COUNTY_BOUNDARY_TABLE, COUNTY_DIM_TABLE])
    else:
        required.append(STATE_BOUNDARY_TABLE)

    for table_name in required:
        if not _table_exists(db, table_name):
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Required table {table_name} is missing. "
                    "Run migrations and CDC funding ingestion."
                ),
            )


def _json_number(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            return None
        return float(value)
    if isinstance(value, Real):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    return value


def _serialize_value(value: Any) -> Any:
    numeric = _json_number(value)
    if numeric is not value:
        return numeric
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            return value
    return value


def _strip_optional(value: str | None) -> str | None:
    token = str(value or "").strip()
    return token or None


def _normalize_basis(value: str | None, *, allow_all: bool = False) -> str:
    token = str(value or "prime").strip().lower()
    allowed = VALID_BASIS if allow_all else {"prime", "subaward"}
    if token not in allowed:
        options = "prime, subaward, or all" if allow_all else "prime or subaward"
        raise HTTPException(status_code=400, detail=f"basis must be {options}")
    return token


def _normalize_geography(value: str | None) -> str:
    token = str(value or "county").strip().lower()
    if token not in VALID_GEOGRAPHY:
        raise HTTPException(status_code=400, detail="geography must be state or county")
    return token


def _normalize_metric(value: str | None, *, basis: str) -> str:
    default_metric = "fy_obligated" if basis == "prime" else "total_subaward"
    token = str(value or default_metric).strip().lower()
    if token not in VALID_METRICS:
        raise HTTPException(
            status_code=400,
            detail=(
                "metric must be one of fy_obligated, fy_outlayed_estimated, transaction_count, "
                "distinct_award_count, total_subaward, or subaward_count"
            ),
        )

    if basis == "prime" and token not in PRIME_METRICS:
        raise HTTPException(
            status_code=400,
            detail=(
                "For basis=prime, metric must be one of fy_obligated, fy_outlayed_estimated, "
                "transaction_count, or distinct_award_count"
            ),
        )
    if basis == "subaward" and token not in SUBAWARD_METRICS:
        raise HTTPException(
            status_code=400,
            detail="For basis=subaward, metric must be one of total_subaward or subaward_count",
        )
    return token


def _normalize_display_mode(value: str | None, *, metric: str) -> str:
    token = str(value or "total").strip().lower()
    if token not in VALID_DISPLAY_MODES:
        raise HTTPException(status_code=400, detail="display_mode must be total or per_capita")
    if token == "per_capita" and metric not in DOLLAR_METRICS:
        raise HTTPException(
            status_code=400,
            detail="display_mode=per_capita is only supported for dollar-based metrics",
        )
    return token


def _normalize_funding_geography_mode(value: str | None) -> str:
    token = str(value or "recipient_location").strip().lower()
    if token not in VALID_FUNDING_GEOGRAPHY_MODES:
        raise HTTPException(
            status_code=400,
            detail="funding_geography_mode must be recipient_location or statewide_allocation",
        )
    return token


def _normalize_appropriation_type(value: str | None) -> str:
    token = str(value or APPROPRIATION_FILTER_ALL).strip().lower()
    if token not in APPROPRIATION_FILTER_VALUES:
        options = ", ".join(sorted(APPROPRIATION_FILTER_VALUES))
        raise HTTPException(
            status_code=400,
            detail=f"appropriation_type must be one of {options}",
        )
    return token


def _normalize_state_code(value: str | None) -> str | None:
    if value is None:
        return None
    letters = re.sub(r"[^A-Za-z]", "", str(value).strip()).upper()
    if len(letters) != 2:
        raise HTTPException(status_code=400, detail="state must be a 2-letter state code")
    return letters


def _normalize_county_fips(value: str | None) -> str | None:
    token = str(value or "").strip()
    if not token:
        return None
    digits = re.sub(r"[^0-9]", "", token)
    if not digits:
        raise HTTPException(status_code=400, detail="selected_county_fips must contain 5 digits")
    if len(digits) > 5:
        raise HTTPException(status_code=400, detail="selected_county_fips must contain 5 digits")
    digits = digits.zfill(5)
    if len(digits) != 5:
        raise HTTPException(status_code=400, detail="selected_county_fips must contain 5 digits")
    return digits


def _normalize_name_filter(value: str | None) -> str | None:
    token = " ".join(str(value or "").strip().split())
    if not token:
        return None
    return token.lower()


def _normalize_required_geography_id(*, geography: str, geography_id: str | None) -> str:
    token = str(geography_id or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="geography_id is required")
    if geography == "state":
        normalized = _normalize_state_code(token)
        if normalized is None:
            raise HTTPException(status_code=400, detail="geography_id must be a 2-letter state code")
        return normalized
    normalized = _normalize_county_fips(token)
    if normalized is None:
        raise HTTPException(status_code=400, detail="geography_id must be a 5-digit county FIPS")
    return normalized


def _normalize_optional_fiscal_year(value: int | str | None, *, field_name: str) -> int | None:
    if value is None:
        return None
    try:
        year = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be an integer fiscal year") from exc
    if year < 1900 or year > 2100:
        raise HTTPException(status_code=400, detail=f"{field_name} must be between 1900 and 2100")
    return year


def _state_code_for_county_fips(db: Session, county_fips: str | None) -> str | None:
    normalized_fips = _normalize_county_fips(county_fips)
    if normalized_fips is None:
        return None
    row = db.execute(
        text(
            f"""
            SELECT state_abbr
            FROM {COUNTY_DIM_TABLE}
            WHERE location_id = :county_fips
            """
        ),
        {"county_fips": normalized_fips},
    ).mappings().one_or_none()
    code = str(row.get("state_abbr") or "").strip().upper() if row else ""
    return code or None


def _county_population_weight(db: Session, county_fips: str | None) -> dict[str, Any] | None:
    normalized_fips = _normalize_county_fips(county_fips)
    if normalized_fips is None:
        return None
    row = db.execute(
        text(
            f"""
            WITH state_totals AS (
                SELECT
                    state_abbr,
                    SUM(total_population)::numeric AS state_population
                FROM {COUNTY_DIM_TABLE}
                WHERE location_id ~ '^[0-9]{{5}}$'
                  AND total_population IS NOT NULL
                  AND total_population > 0
                GROUP BY state_abbr
            )
            SELECT
                county.location_id AS county_fips,
                county.county_name,
                county.state_abbr AS state_code,
                county.total_population::numeric AS county_population,
                state_totals.state_population,
                CASE
                    WHEN state_totals.state_population IS NULL OR state_totals.state_population = 0 THEN NULL
                    ELSE county.total_population::numeric / state_totals.state_population
                END AS population_weight
            FROM {COUNTY_DIM_TABLE} AS county
            LEFT JOIN state_totals
                ON state_totals.state_abbr = county.state_abbr
            WHERE county.location_id = :county_fips
            """
        ),
        {"county_fips": normalized_fips},
    ).mappings().one_or_none()
    if row is None:
        return None
    return {
        "county_fips": row.get("county_fips"),
        "county_name": row.get("county_name"),
        "state_code": row.get("state_code"),
        "county_population": _json_number(row.get("county_population")),
        "state_population": _json_number(row.get("state_population")),
        "population_weight": _json_number(row.get("population_weight")),
    }


def _parse_bbox(bbox: str | None) -> dict[str, float] | None:
    if bbox is None:
        return None
    try:
        minx, miny, maxx, maxy = (float(value) for value in bbox.split(","))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid bbox format") from exc

    if minx >= maxx or miny >= maxy:
        raise HTTPException(status_code=400, detail="Invalid bbox bounds")

    return {
        "minx": minx,
        "miny": miny,
        "maxx": maxx,
        "maxy": maxy,
    }


def _latest_prime_transaction_fiscal_year(db: Session) -> int | None:
    row = db.execute(
        text(
            f"""
            SELECT MAX(action_date_fiscal_year) AS fiscal_year
            FROM {PRIME_TX_TABLE}
            WHERE action_date_fiscal_year IS NOT NULL
            """
        )
    ).mappings().one()
    value = row.get("fiscal_year")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _metric_column(basis: str, metric: str) -> str:
    if basis == "prime":
        return PRIME_METRICS[metric]
    return SUBAWARD_METRICS[metric]


def _summary_table(*, basis: str, geography: str, funding_geography_mode: str) -> str:
    if basis == "prime":
        if geography == "nation":
            return PRIME_TX_NATIONAL_SUMMARY_TABLE
        if geography == "state":
            return PRIME_TX_STATE_SUMMARY_TABLE
        return (
            PRIME_TX_COUNTY_ALLOCATED_SUMMARY_TABLE
            if funding_geography_mode == "statewide_allocation"
            else PRIME_TX_COUNTY_SUMMARY_TABLE
        )
    if geography == "nation":
        return SUBAWARD_NATIONAL_SUMMARY_TABLE
    return SUBAWARD_STATE_SUMMARY_TABLE if geography == "state" else SUBAWARD_COUNTY_SUMMARY_TABLE


def _summary_filters_sql(
    *,
    basis: str,
    geography: str,
    appropriation_type: str,
    assistance_type: str | None,
    fiscal_year: int | None,
    awarding_office: str | None,
    funding_office: str | None,
    center: str | None,
    state: str | None,
) -> tuple[str, dict[str, Any]]:
    conditions: list[str] = []
    params: dict[str, Any] = {}

    if assistance_type and basis == "prime":
        conditions.append("s.assistance_type_description = :assistance_type")
        params["assistance_type"] = assistance_type

    if appropriation_type != APPROPRIATION_FILTER_ALL:
        conditions.append("s.appropriation_type = :appropriation_type")
        params["appropriation_type"] = appropriation_type

    if fiscal_year is not None:
        conditions.append("s.fiscal_year = :fiscal_year")
        params["fiscal_year"] = int(fiscal_year)

    if awarding_office:
        conditions.append("s.awarding_office_name = :awarding_office")
        params["awarding_office"] = awarding_office

    if funding_office:
        conditions.append("s.funding_office_name = :funding_office")
        params["funding_office"] = funding_office

    if center:
        conditions.append(
            "(s.awarding_sub_agency_name = :center OR s.funding_sub_agency_name = :center)"
        )
        params["center"] = center

    normalized_state = _normalize_state_code(state)
    if normalized_state:
        if geography == "state":
            conditions.append("s.geography_id = :state_code")
        elif geography == "county":
            conditions.append("s.state_code = :state_code")
        params["state_code"] = normalized_state

    if not conditions:
        return ("", params)
    return (" AND " + " AND ".join(conditions), params)


def _summary_year_bounds(db: Session, *, table_name: str) -> tuple[int | None, int | None]:
    row = db.execute(
        text(
            f"""
            SELECT
                MIN(s.fiscal_year) AS min_fiscal_year,
                MAX(s.fiscal_year) AS max_fiscal_year
            FROM {table_name} AS s
            WHERE s.fiscal_year IS NOT NULL
            """
        )
    ).mappings().one()
    min_year = row.get("min_fiscal_year")
    max_year = row.get("max_fiscal_year")
    return (
        int(min_year) if min_year is not None else None,
        int(max_year) if max_year is not None else None,
    )


def _resolve_trend_year_range(
    *,
    available_min_fy: int | None,
    available_max_fy: int | None,
    start_fy: int | None,
    end_fy: int | None,
) -> tuple[int, int]:
    latest_completed_fy = _latest_completed_federal_fiscal_year()

    if available_min_fy is None or available_max_fy is None:
        default_start = TREND_DEFAULT_START_FY
        default_end = min(TREND_DEFAULT_END_FY, latest_completed_fy)
        if default_start > default_end:
            default_start = default_end
    else:
        available_min = int(available_min_fy)
        available_max = int(available_max_fy)
        default_start = max(TREND_DEFAULT_START_FY, available_min)
        default_end = min(TREND_DEFAULT_END_FY, available_max, latest_completed_fy)
        if default_start > default_end:
            default_start = min(available_min, default_end)

    resolved_start = int(start_fy) if start_fy is not None else int(default_start)
    resolved_end = int(end_fy) if end_fy is not None else int(default_end)
    max_trend_end_fy = min(TREND_DEFAULT_END_FY, latest_completed_fy)
    resolved_start = min(resolved_start, max_trend_end_fy)
    resolved_end = min(resolved_end, max_trend_end_fy)
    if resolved_start > resolved_end:
        raise HTTPException(status_code=400, detail="start_fy must be <= end_fy")
    return resolved_start, resolved_end


def _resolve_trend_geography_metadata(
    db: Session,
    *,
    geography: str,
    geography_id: str,
) -> dict[str, Any]:
    if geography == "state":
        row = db.execute(
            text(
                f"""
                SELECT
                    sb.state_abbr AS geography_id,
                    COALESCE(NULLIF(TRIM(sb.state_name), ''), sb.state_abbr) AS geography_name,
                    sb.state_abbr AS state_code,
                    COALESCE(NULLIF(TRIM(sb.state_name), ''), sb.state_abbr) AS state_name
                FROM {STATE_BOUNDARY_TABLE} AS sb
                WHERE sb.state_abbr = :geography_id
                LIMIT 1
                """
            ),
            {"geography_id": geography_id},
        ).mappings().one_or_none()
        if row is None:
            return {
                "geography_id": geography_id,
                "geography_name": geography_id,
                "state_code": geography_id,
                "state_name": geography_id,
                "county_name": None,
            }
        return {
            "geography_id": row.get("geography_id"),
            "geography_name": row.get("geography_name"),
            "state_code": row.get("state_code"),
            "state_name": row.get("state_name"),
            "county_name": None,
        }

    row = db.execute(
        text(
            f"""
            SELECT
                county.location_id AS geography_id,
                COALESCE(NULLIF(TRIM(county.county_name), ''), county.location_id) AS county_name,
                county.state_abbr AS state_code,
                COALESCE(NULLIF(TRIM(county.state_desc), ''), county.state_abbr) AS state_name
            FROM {COUNTY_DIM_TABLE} AS county
            WHERE county.location_id = :geography_id
            LIMIT 1
            """
        ),
        {"geography_id": geography_id},
    ).mappings().one_or_none()
    if row is None:
        return {
            "geography_id": geography_id,
            "geography_name": geography_id,
            "state_code": geography_id[:2] if len(geography_id) >= 2 else None,
            "state_name": None,
            "county_name": None,
        }

    county_name = row.get("county_name")
    state_code = row.get("state_code")
    geography_name = (
        f"{county_name}, {state_code}"
        if county_name and state_code
        else county_name
        or geography_id
    )
    return {
        "geography_id": row.get("geography_id"),
        "geography_name": geography_name,
        "state_code": state_code,
        "state_name": row.get("state_name"),
        "county_name": county_name,
    }


def _summary_aggregate_sql(*, basis: str, metric_column: str, table_name: str, where_sql: str) -> str:
    if basis == "prime":
        return (
            "SELECT "
            "  s.geography_id,"
            f"  SUM(s.{metric_column}) AS metric_value,"
            "  MAX(s.population) AS population,"
            "  CASE"
            "    WHEN MAX(s.population) IS NULL OR MAX(s.population) = 0 THEN NULL"
            f"    ELSE SUM(s.{metric_column}) / NULLIF(MAX(s.population), 0)"
            "  END AS metric_per_capita,"
            "  SUM(s.fy_obligated_amount) AS fy_obligated_amount,"
            "  SUM(s.fy_outlayed_amount_estimated) AS fy_outlayed_amount_estimated,"
            "  SUM(s.transaction_count) AS transaction_count,"
            "  SUM(s.distinct_award_count) AS distinct_award_count,"
            "  SUM(s.total_funding_amount) AS total_funding_amount,"
            "  CASE"
            "    WHEN MAX(s.population) IS NULL OR MAX(s.population) = 0 THEN NULL"
            "    ELSE SUM(s.total_funding_amount) / NULLIF(MAX(s.population), 0)"
            "  END AS funding_per_capita,"
            "  SUM(s.fy_obligated_amount) AS total_obligated_amount,"
            "  SUM(s.fy_outlayed_amount_estimated) AS total_outlayed_amount,"
            "  SUM(s.distinct_award_count) AS award_count,"
            "  0::numeric AS total_subaward_amount,"
            "  0::numeric AS subaward_count "
            f"FROM {table_name} AS s "
            "WHERE 1=1"
            f"{where_sql} "
            "GROUP BY s.geography_id"
        )

    return (
        "SELECT "
        "  s.geography_id,"
        f"  SUM(s.{metric_column}) AS metric_value,"
        "  MAX(s.population) AS population,"
        "  CASE"
        "    WHEN MAX(s.population) IS NULL OR MAX(s.population) = 0 THEN NULL"
        f"    ELSE SUM(s.{metric_column}) / NULLIF(MAX(s.population), 0)"
        "  END AS metric_per_capita,"
        "  0::numeric AS fy_obligated_amount,"
        "  0::numeric AS fy_outlayed_amount_estimated,"
        "  0::numeric AS transaction_count,"
        "  0::numeric AS distinct_award_count,"
        "  SUM(s.total_funding_amount) AS total_funding_amount,"
        "  CASE"
        "    WHEN MAX(s.population) IS NULL OR MAX(s.population) = 0 THEN NULL"
        "    ELSE SUM(s.total_funding_amount) / NULLIF(MAX(s.population), 0)"
        "  END AS funding_per_capita,"
        "  SUM(s.total_obligated_amount) AS total_obligated_amount,"
        "  SUM(s.total_outlayed_amount) AS total_outlayed_amount,"
        "  SUM(s.award_count) AS award_count,"
        "  SUM(s.total_subaward_amount) AS total_subaward_amount,"
        "  SUM(s.subaward_count) AS subaward_count "
        f"FROM {table_name} AS s "
        "WHERE 1=1"
        f"{where_sql} "
        "GROUP BY s.geography_id"
    )


def _metric_label_for_display_mode(metric: str, display_mode: str) -> str:
    base_label = METRIC_LABELS.get(metric, metric)
    if display_mode == "per_capita":
        return f"{base_label} per capita"
    return base_label


def _metric_value_from_row(row: dict[str, Any], *, display_mode: str) -> Any:
    if display_mode == "per_capita":
        return _json_number(row.get("metric_per_capita"))
    return _json_number(row.get("metric_value"))


def _fetch_national_summary(
    db: Session,
    *,
    basis: str,
    funding_geography_mode: str,
    metric: str,
    display_mode: str,
    appropriation_type: str,
    assistance_type: str | None,
    fiscal_year: int | None,
    awarding_office: str | None,
    funding_office: str | None,
    center: str | None,
) -> dict[str, Any]:
    table_name = _summary_table(
        basis=basis,
        geography="nation",
        funding_geography_mode=funding_geography_mode,
    )
    metric_column = _metric_column(basis, metric)
    filter_sql, filter_params = _summary_filters_sql(
        basis=basis,
        geography="nation",
        appropriation_type=appropriation_type,
        assistance_type=assistance_type,
        fiscal_year=fiscal_year,
        awarding_office=awarding_office,
        funding_office=funding_office,
        center=center,
        state=None,
    )
    summary_sql = _summary_aggregate_sql(
        basis=basis,
        metric_column=metric_column,
        table_name=table_name,
        where_sql=filter_sql,
    )
    row = db.execute(
        text(
            f"""
            WITH summary AS ({summary_sql})
            SELECT
                SUM(summary.metric_value) AS metric_value,
                CASE
                    WHEN MAX(summary.population) IS NULL OR MAX(summary.population) = 0 THEN NULL
                    ELSE SUM(summary.metric_value) / NULLIF(MAX(summary.population), 0)
                END AS metric_per_capita,
                MAX(summary.population) AS population,
                SUM(summary.total_funding_amount) AS total_funding_amount,
                CASE
                    WHEN MAX(summary.population) IS NULL OR MAX(summary.population) = 0 THEN NULL
                    ELSE SUM(summary.total_funding_amount) / NULLIF(MAX(summary.population), 0)
                END AS funding_per_capita,
                SUM(summary.fy_obligated_amount) AS fy_obligated_amount,
                SUM(summary.fy_outlayed_amount_estimated) AS fy_outlayed_amount_estimated,
                SUM(summary.transaction_count) AS transaction_count,
                SUM(summary.distinct_award_count) AS distinct_award_count,
                SUM(summary.total_subaward_amount) AS total_subaward_amount,
                SUM(summary.subaward_count) AS subaward_count
            FROM summary
            """
        ),
        filter_params,
    ).mappings().one()
    return {
        "geography_id": "US",
        "geography_name": "United States",
        "metric": metric,
        "metric_label": _metric_label_for_display_mode(metric, display_mode),
        "metric_value": _json_number(row.get("metric_value")),
        "metric_per_capita": _json_number(row.get("metric_per_capita")),
        "value": _metric_value_from_row(row, display_mode=display_mode),
        "display_mode": display_mode,
        "population": _json_number(row.get("population")),
        "total_funding_amount": _json_number(row.get("total_funding_amount")),
        "funding_per_capita": _json_number(row.get("funding_per_capita")),
        "fy_obligated_amount": _json_number(row.get("fy_obligated_amount")),
        "fy_outlayed_amount_estimated": _json_number(row.get("fy_outlayed_amount_estimated")),
        "transaction_count": int(row.get("transaction_count") or 0),
        "distinct_award_count": int(row.get("distinct_award_count") or 0),
        "total_subaward_amount": _json_number(row.get("total_subaward_amount")),
        "subaward_count": int(row.get("subaward_count") or 0),
    }


def _quantile(sorted_values: list[float], fraction: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * fraction
    base = int(math.floor(position))
    remainder = position - base
    lower = sorted_values[base]
    upper = sorted_values[base + 1] if base + 1 < len(sorted_values) else lower
    return lower + (upper - lower) * remainder


def _compute_bins(values: list[float], *, bins: int = 5) -> list[dict[str, Any]]:
    if not values:
        return []
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        value = sorted_values[0]
        return [{"min": value, "max": value, "label": f"{value:,.1f}", "colorIndex": 0}]

    breakpoints: list[float] = []
    for index in range(bins + 1):
        fraction = index / bins
        value = _quantile(sorted_values, fraction)
        if value is None:
            continue
        breakpoints.append(float(value))

    deduped: list[float] = []
    for point in breakpoints:
        if not deduped or point > deduped[-1]:
            deduped.append(point)

    if len(deduped) < 2:
        deduped = [sorted_values[0], sorted_values[-1]]

    output: list[dict[str, Any]] = []
    for index in range(len(deduped) - 1):
        lower = deduped[index]
        upper = deduped[index + 1]
        output.append(
            {
                "min": lower,
                "max": upper,
                "label": f"{lower:,.1f} - {upper:,.1f}",
                "colorIndex": index,
            }
        )
    return output


def list_filter_options(
    db: Session,
    *,
    basis: str,
) -> dict[str, Any]:
    normalized_basis = _normalize_basis(basis, allow_all=True)
    _ensure_award_tables(db)

    def _distinct(table_name: str, column_name: str) -> list[str]:
        rows = db.execute(
            text(
                f"""
                SELECT DISTINCT {column_name} AS value
                FROM {table_name}
                WHERE {column_name} IS NOT NULL
                  AND NULLIF(TRIM(({column_name})::text), '') IS NOT NULL
                ORDER BY {column_name}
                """
            )
        ).mappings().all()
        return [str(row["value"]).strip() for row in rows if row.get("value") is not None]

    def _union_distinct(
        left_table: str,
        left_col: str,
        right_table: str,
        right_col: str,
    ) -> list[str]:
        rows = db.execute(
            text(
                f"""
                SELECT DISTINCT value
                FROM (
                    SELECT {left_col} AS value FROM {left_table}
                    UNION ALL
                    SELECT {right_col} AS value FROM {right_table}
                ) AS unioned
                WHERE value IS NOT NULL
                  AND NULLIF(TRIM(value), '') IS NOT NULL
                ORDER BY value
                """
            )
        ).mappings().all()
        return [str(row["value"]).strip() for row in rows if row.get("value") is not None]

    if normalized_basis == "prime":
        table_name = PRIME_TX_TABLE
        years = [
            int(value)
            for value in _distinct(PRIME_TX_TABLE, "action_date_fiscal_year")
            if str(value).isdigit()
        ]
        metric_options = [
            {"value": key, "label": METRIC_LABELS[key]}
            for key in ["fy_obligated", "fy_outlayed_estimated", "distinct_award_count", "transaction_count"]
        ]
        states = db.execute(
            text(
                f"""
                SELECT
                    COALESCE(t.recipient_state_code, p.recipient_state_code) AS code,
                    MAX(COALESCE(NULLIF(t.recipient_state_name, ''), p.recipient_state_name)) AS name
                FROM {PRIME_TX_TABLE} AS t
                LEFT JOIN {PRIME_TABLE} AS p
                    ON p.unique_key = t.assistance_award_unique_key
                WHERE COALESCE(t.recipient_state_code, p.recipient_state_code) IS NOT NULL
                GROUP BY COALESCE(t.recipient_state_code, p.recipient_state_code)
                ORDER BY COALESCE(t.recipient_state_code, p.recipient_state_code)
                """
            )
        ).mappings().all()
        assistance_types = _distinct(PRIME_TX_TABLE, "assistance_type_description")
    elif normalized_basis == "subaward":
        table_name = SUBAWARD_TABLE
        years = [
            int(value)
            for value in _distinct(SUBAWARD_TABLE, "subaward_action_date_fiscal_year")
            if str(value).isdigit()
        ]
        metric_options = [
            {"value": key, "label": METRIC_LABELS[key]}
            for key in ["total_subaward", "subaward_count"]
        ]
        states = db.execute(
            text(
                f"""
                SELECT subawardee_state_code AS code, MAX(subawardee_state_name) AS name
                FROM {SUBAWARD_TABLE}
                WHERE subawardee_state_code IS NOT NULL
                GROUP BY subawardee_state_code
                ORDER BY subawardee_state_code
                """
            )
        ).mappings().all()
        assistance_types = []
    else:
        table_name = PRIME_TABLE
        years_rows = db.execute(
            text(
                f"""
                SELECT action_date_fiscal_year::text AS fiscal_year FROM {PRIME_TX_TABLE}
                UNION
                SELECT subaward_action_date_fiscal_year::text AS fiscal_year FROM {SUBAWARD_TABLE}
                """
            )
        ).mappings().all()
        years = sorted(
            {
                int(str(row["fiscal_year"]))
                for row in years_rows
                if row.get("fiscal_year") is not None and str(row["fiscal_year"]).isdigit()
            },
            reverse=True,
        )
        metric_options = [
            {"value": key, "label": METRIC_LABELS[key]}
            for key in ["fy_obligated", "fy_outlayed_estimated", "distinct_award_count", "transaction_count"]
        ]
        states = db.execute(
            text(
                f"""
                SELECT
                    COALESCE(t.recipient_state_code, p.recipient_state_code) AS code,
                    MAX(COALESCE(NULLIF(t.recipient_state_name, ''), p.recipient_state_name)) AS name
                FROM {PRIME_TX_TABLE} AS t
                LEFT JOIN {PRIME_TABLE} AS p
                    ON p.unique_key = t.assistance_award_unique_key
                WHERE COALESCE(t.recipient_state_code, p.recipient_state_code) IS NOT NULL
                GROUP BY COALESCE(t.recipient_state_code, p.recipient_state_code)
                UNION
                SELECT subawardee_state_code AS code, MAX(subawardee_state_name) AS name
                FROM {SUBAWARD_TABLE}
                WHERE subawardee_state_code IS NOT NULL
                GROUP BY subawardee_state_code
                ORDER BY code
                """
            )
        ).mappings().all()
        assistance_types = _distinct(PRIME_TX_TABLE, "assistance_type_description")

    if normalized_basis == "prime":
        awarding_offices = _distinct(PRIME_TX_TABLE, "awarding_office_name")
        funding_offices = _distinct(PRIME_TX_TABLE, "funding_office_name")
        centers = _union_distinct(
            PRIME_TX_TABLE,
            "awarding_sub_agency_name",
            PRIME_TX_TABLE,
            "funding_sub_agency_name",
        )
    elif normalized_basis == "subaward":
        awarding_offices = _distinct(SUBAWARD_TABLE, "prime_award_awarding_office_name")
        funding_offices = _distinct(SUBAWARD_TABLE, "prime_award_funding_office_name")
        centers = _union_distinct(
            SUBAWARD_TABLE,
            "prime_award_awarding_sub_agency_name",
            SUBAWARD_TABLE,
            "prime_award_funding_sub_agency_name",
        )
    else:
        awarding_offices = _union_distinct(
            PRIME_TX_TABLE,
            "awarding_office_name",
            SUBAWARD_TABLE,
            "prime_award_awarding_office_name",
        )
        funding_offices = _union_distinct(
            PRIME_TX_TABLE,
            "funding_office_name",
            SUBAWARD_TABLE,
            "prime_award_funding_office_name",
        )
        centers = _union_distinct(
            PRIME_TX_TABLE,
            "awarding_sub_agency_name",
            SUBAWARD_TABLE,
            "prime_award_awarding_sub_agency_name",
        )

    years = sorted(set(years), reverse=True)

    return {
        "basis": normalized_basis,
        "funding_geography_modes": [
            {"value": "recipient_location", "label": "Recipient location"},
            {"value": "statewide_allocation", "label": "Estimated statewide allocation"},
        ],
        "appropriation_type_options": [
            {"value": APPROPRIATION_FILTER_ALL, "label": APPROPRIATION_FILTER_LABELS[APPROPRIATION_FILTER_ALL]},
            {
                "value": APPROPRIATION_TYPE_REGULAR,
                "label": APPROPRIATION_FILTER_LABELS[APPROPRIATION_TYPE_REGULAR],
            },
            {
                "value": APPROPRIATION_TYPE_COVID_EMERGENCY,
                "label": APPROPRIATION_FILTER_LABELS[APPROPRIATION_TYPE_COVID_EMERGENCY],
            },
            {
                "value": APPROPRIATION_TYPE_OTHER_EMERGENCY,
                "label": APPROPRIATION_FILTER_LABELS[APPROPRIATION_TYPE_OTHER_EMERGENCY],
            },
            {
                "value": APPROPRIATION_TYPE_UNKNOWN,
                "label": APPROPRIATION_FILTER_LABELS[APPROPRIATION_TYPE_UNKNOWN],
            },
        ],
        "metric_options": metric_options,
        "display_mode_options": [
            {"value": "total", "label": "Total"},
            {"value": "per_capita", "label": "Per capita (dollar metrics only)"},
        ],
        "assistance_types": assistance_types,
        "fiscal_years": years,
        "awarding_offices": awarding_offices,
        "funding_offices": funding_offices,
        "centers": centers,
        "states": [
            {
                "code": str(row.get("code") or "").strip(),
                "name": str(row.get("name") or row.get("code") or "").strip(),
            }
            for row in states
            if str(row.get("code") or "").strip()
        ],
        "normalization": {
            "available": True,
            "help_text": "Reconstructed to CDC Funding Profiles scope and benchmarked against observed profile years",
            "supported_basis": ["prime"],
            "supported_metrics": ["fy_obligated"],
            "training_years": [2020, 2021, 2022, 2023],
            "estimated_years": [2024, 2025, 2026],
            "methodology_version": PROFILE_CALIBRATION_METHODOLOGY_VERSION,
        },
    }


def fetch_map_geojson(
    db: Session,
    *,
    basis: str,
    geography: str,
    funding_geography_mode: str = "recipient_location",
    metric: str,
    display_mode: str = "total",
    appropriation_type: str = APPROPRIATION_FILTER_ALL,
    assistance_type: str | None = None,
    fiscal_year: int | None = None,
    awarding_office: str | None = None,
    funding_office: str | None = None,
    center: str | None = None,
    state: str | None = None,
    bbox: str | None = None,
    zoom: int = 6,
    limit: int = 6000,
    normalize: bool = False,
) -> dict[str, Any]:
    normalized_basis = _normalize_basis(basis)
    normalized_geography = _normalize_geography(geography)
    normalized_mode = _normalize_funding_geography_mode(funding_geography_mode)
    normalized_appropriation_type = _normalize_appropriation_type(appropriation_type)
    normalized_metric = _normalize_metric(metric, basis=normalized_basis)
    normalized_display_mode = _normalize_display_mode(display_mode, metric=normalized_metric)
    normalization_requested = bool(normalize)
    _ensure_required_tables(
        db,
        basis=normalized_basis,
        geography=normalized_geography,
        funding_geography_mode=normalized_mode,
    )

    effective_fiscal_year = fiscal_year
    if normalized_basis == "prime" and effective_fiscal_year is None:
        effective_fiscal_year = _latest_prime_transaction_fiscal_year(db)
    normalization_supported, normalization_reason = usaspending_normalization_compatibility(
        basis=normalized_basis,
        metric=normalized_metric,
        funding_geography_mode=normalized_mode,
        appropriation_type=normalized_appropriation_type,
        assistance_type=assistance_type,
        awarding_office=awarding_office,
        funding_office=funding_office,
        center=center,
    )
    normalization_lookup = (
        fetch_state_normalization_lookup(
            db,
            source_system="usaspending",
            fiscal_year=int(effective_fiscal_year),
        )
        if normalization_requested and normalization_supported and effective_fiscal_year is not None
        else {}
    )
    normalization_applied = normalization_requested and normalization_supported and bool(normalization_lookup)

    metric_column = _metric_column(normalized_basis, normalized_metric)
    effective_mode = (
        normalized_mode
        if normalized_basis == "prime"
        else "recipient_location"
    )
    summary_table = _summary_table(
        basis=normalized_basis,
        geography=normalized_geography,
        funding_geography_mode=effective_mode,
    )
    filter_sql, filter_params = _summary_filters_sql(
        basis=normalized_basis,
        geography=normalized_geography,
        appropriation_type=normalized_appropriation_type,
        assistance_type=assistance_type,
        fiscal_year=effective_fiscal_year,
        awarding_office=awarding_office,
        funding_office=funding_office,
        center=center,
        state=state,
    )
    bbox_params = _parse_bbox(bbox)

    simplify_degrees = 0.02
    if zoom <= 5:
        simplify_degrees = 0.04
    elif zoom >= 9:
        simplify_degrees = 0.01

    params: dict[str, Any] = {
        **filter_params,
        "limit": max(1, min(int(limit), 20000)),
        "simplify_degrees": simplify_degrees,
    }

    summary_sql = _summary_aggregate_sql(
        basis=normalized_basis,
        metric_column=metric_column,
        table_name=summary_table,
        where_sql=filter_sql,
    )

    if normalized_geography == "county":
        bbox_cte = ""
        bbox_join = ""
        bbox_filter = ""
        if bbox_params is not None:
            bbox_cte = (
                "WITH bbox AS (SELECT ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) AS geom), "
                "summary AS ("
                + summary_sql
                + ")"
            )
            bbox_join = "CROSS JOIN bbox"
            bbox_filter = "AND b.geom && bbox.geom AND ST_Intersects(b.geom, bbox.geom)"
            params.update(bbox_params)
        else:
            bbox_cte = f"WITH summary AS ({summary_sql})"

        rows = db.execute(
            text(
                f"""
                {bbox_cte}
                SELECT
                    b.geoid AS id,
                    COALESCE(c.county_name, b.name) AS area_name,
                    c.state_abbr AS state_code,
                    c.state_desc AS state_name,
                    summary.metric_value AS metric_value,
                    summary.metric_per_capita AS metric_per_capita,
                    summary.population AS population,
                    summary.funding_per_capita AS funding_per_capita,
                    summary.fy_obligated_amount,
                    summary.fy_outlayed_amount_estimated,
                    summary.transaction_count,
                    summary.distinct_award_count,
                    summary.total_funding_amount,
                    summary.total_obligated_amount,
                    summary.total_outlayed_amount,
                    summary.award_count,
                    summary.total_subaward_amount,
                    summary.subaward_count,
                    ST_AsGeoJSON(
                        ST_SimplifyPreserveTopology(b.geom, :simplify_degrees),
                        6
                    )::json AS geometry
                FROM {COUNTY_BOUNDARY_TABLE} AS b
                LEFT JOIN {COUNTY_DIM_TABLE} AS c
                    ON c.location_id = b.location_id
                LEFT JOIN summary
                    ON summary.geography_id = b.geoid
                {bbox_join}
                WHERE b.geom IS NOT NULL
                  {bbox_filter}
                ORDER BY b.geoid
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    else:
        bbox_filter = ""
        if bbox_params is not None:
            bbox_filter = (
                "AND sb.geom && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) "
                "AND ST_Intersects(sb.geom, ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326))"
            )
            params.update(bbox_params)

        rows = db.execute(
            text(
                f"""
                WITH summary AS ({summary_sql})
                SELECT
                    sb.state_abbr AS id,
                    COALESCE(sb.state_name, sb.state_abbr) AS area_name,
                    sb.state_abbr AS state_code,
                    COALESCE(sb.state_name, sb.state_abbr) AS state_name,
                    summary.metric_value AS metric_value,
                    summary.metric_per_capita AS metric_per_capita,
                    summary.population AS population,
                    summary.funding_per_capita AS funding_per_capita,
                    summary.fy_obligated_amount,
                    summary.fy_outlayed_amount_estimated,
                    summary.transaction_count,
                    summary.distinct_award_count,
                    summary.total_funding_amount,
                    summary.total_obligated_amount,
                    summary.total_outlayed_amount,
                    summary.award_count,
                    summary.total_subaward_amount,
                    summary.subaward_count,
                    ST_AsGeoJSON(
                        ST_SimplifyPreserveTopology(sb.geom, :simplify_degrees),
                        6
                    )::json AS geometry
                FROM {STATE_BOUNDARY_TABLE} AS sb
                LEFT JOIN summary
                    ON summary.geography_id = sb.state_abbr
                WHERE sb.geom IS NOT NULL
                  {bbox_filter}
                ORDER BY sb.state_abbr
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()

    features = []
    for row in rows:
        metric_value = _json_number(row.get("metric_value"))
        metric_per_capita = _json_number(row.get("metric_per_capita"))
        state_code = str(row.get("state_code") or "").strip().upper()
        normalization_row = normalization_lookup.get(state_code)
        normalized_metric_value = None
        normalized_metric_per_capita = None
        normalization_factor = None
        normalized_amount_type = None
        normalization_status = None
        confidence_note = None
        normalization_method = None
        funding_stream_logic_version = None
        if normalization_applied and normalization_row:
            normalization_factor = _json_number(normalization_row.get("normalization_factor"))
            normalized_amount_type = normalization_row.get("normalized_amount_type")
            normalization_status = normalization_row.get("status_label")
            confidence_note = normalization_row.get("confidence_note")
            normalization_method = normalization_row.get("normalization_method")
            funding_stream_logic_version = normalization_row.get("funding_stream_logic_version")
            if normalized_geography == "state":
                normalized_metric_value = _json_number(normalization_row.get("normalized_amount"))
            elif metric_value is not None and normalization_factor is not None:
                normalized_metric_value = float(metric_value) * float(normalization_factor)
            population_value = _json_number(row.get("population"))
            if normalized_metric_value is not None and population_value not in (None, 0):
                normalized_metric_per_capita = float(normalized_metric_value) / float(population_value)
            elif metric_per_capita is not None and normalization_factor is not None:
                normalized_metric_per_capita = float(metric_per_capita) * float(normalization_factor)
        selected_value = (
            normalized_metric_per_capita
            if normalization_applied and normalized_display_mode == "per_capita"
            else normalized_metric_value
            if normalization_applied
            else metric_per_capita
            if normalized_display_mode == "per_capita"
            else metric_value
        )
        features.append(
            {
                "type": "Feature",
                "geometry": row["geometry"],
                "properties": {
                    "id": row["id"],
                    "location_id": row["id"],
                    "name": row["area_name"],
                    "state_abbr": row["state_code"],
                    "state_name": row["state_name"],
                    "value": selected_value,
                    "metric_value": normalized_metric_value if normalization_applied else metric_value,
                    "metric_per_capita": (
                        normalized_metric_per_capita if normalization_applied else metric_per_capita
                    ),
                    "display_mode": normalized_display_mode,
                    "metric": normalized_metric,
                    "metric_label": _metric_label_for_display_mode(
                        normalized_metric,
                        normalized_display_mode,
                    ),
                    "basis": normalized_basis,
                    "appropriation_type_filter": normalized_appropriation_type,
                    "funding_geography_mode": effective_mode,
                    "is_estimated": bool(
                        normalized_basis == "prime"
                        and normalized_geography == "county"
                        and effective_mode == "statewide_allocation"
                    ),
                    "geo_level": normalized_geography,
                    "fiscal_year": effective_fiscal_year,
                    "population": _json_number(row.get("population")),
                    "funding_per_capita": (
                        normalized_metric_per_capita if normalization_applied else _json_number(row.get("funding_per_capita"))
                    ),
                    "raw_metric_value": metric_value,
                    "raw_metric_per_capita": metric_per_capita,
                    "fy_obligated_amount": (
                        normalized_metric_value if normalization_applied else _json_number(row["fy_obligated_amount"])
                    ),
                    "fy_outlayed_amount_estimated": _json_number(row["fy_outlayed_amount_estimated"]),
                    "transaction_count": int(row["transaction_count"] or 0),
                    "distinct_award_count": int(row["distinct_award_count"] or 0),
                    "total_funding_amount": (
                        normalized_metric_value if normalization_applied else _json_number(row["total_funding_amount"])
                    ),
                    "total_obligated_amount": _json_number(row["total_obligated_amount"]),
                    "total_outlayed_amount": _json_number(row["total_outlayed_amount"]),
                    "award_count": int(row["award_count"] or 0),
                    "total_subaward_amount": _json_number(row["total_subaward_amount"]),
                    "subaward_count": int(row["subaward_count"] or 0),
                    "normalization_requested": normalization_requested,
                    "normalization_applied": normalization_applied and normalization_row is not None,
                    "normalization_factor": normalization_factor,
                    "normalized_amount_type": normalized_amount_type,
                    "normalization_method": normalization_method,
                    "funding_stream_logic_version": funding_stream_logic_version,
                    "normalization_status_label": normalization_status,
                    "normalization_confidence_note": confidence_note,
                },
            }
        )

    if normalized_basis == "prime":
        if effective_fiscal_year is not None:
            base_note = (
                f"Prime award fiscal year {effective_fiscal_year} values are based on transaction records. "
                "Obligated amounts reflect transaction activity in that fiscal year."
            )
        else:
            base_note = "Prime award values are based on transaction records."
        if normalized_geography == "county" and effective_mode == "statewide_allocation":
            note = (
                f"{base_note} For awards classified as statewide, county values are estimated "
                "using state population weights; local awards remain at recipient county."
            )
        else:
            note = base_note
    else:
        if normalized_mode == "statewide_allocation":
            note = (
                "Subawards reported to entities in this geography. "
                "Statewide allocation mode is only applied to Prime Awards."
            )
        else:
            note = "Subawards reported to entities in this geography"

    if normalized_display_mode == "per_capita":
        note = (
            f"{note} Per-capita values use the app population denominator derived from dim_county total population."
        )

    if normalized_appropriation_type == APPROPRIATION_TYPE_COVID_EMERGENCY:
        note = (
            f"{note} COVID / emergency supplemental funding is identified using "
            "official emergency funding codes reported in the source data."
        )

    if normalization_applied:
        note = " ".join(
            part
            for part in [
                note,
                build_normalization_note(
                    fiscal_year=int(effective_fiscal_year),
                    normalization_applied=True,
                    reason=(
                        "County values preserve the raw within-state distribution and are rescaled to the normalized state total."
                        if normalized_geography == "county"
                        else None
                    ),
                ),
            ]
            if part
        )
    elif normalization_requested:
        note = " ".join(
            part for part in [note, normalization_reason] if part
        )

    return {
        "type": "FeatureCollection",
        "basis": normalized_basis,
        "appropriation_type": normalized_appropriation_type,
        "funding_geography_mode": effective_mode,
        "level": normalized_geography,
        "metric": normalized_metric,
        "display_mode": normalized_display_mode,
        "features": features,
        "meta": {
            "note": note,
            "funding_geography_mode": effective_mode,
            "appropriation_type": normalized_appropriation_type,
            "appropriation_type_label": APPROPRIATION_FILTER_LABELS.get(
                normalized_appropriation_type,
                normalized_appropriation_type,
            ),
            "metric_label": _metric_label_for_display_mode(normalized_metric, normalized_display_mode),
            "fiscal_year": effective_fiscal_year,
            "geojson_precision": 6,
            "simplify_tolerance_degrees": simplify_degrees,
            "display_mode": normalized_display_mode,
            "normalization_requested": normalization_requested,
            "normalization_applied": normalization_applied,
            "normalization_status_label": (
                normalization_lookup[next(iter(normalization_lookup))]["status_label"]
                if normalization_applied and normalization_lookup
                else None
            ),
            "methodology_version": (
                normalization_lookup[next(iter(normalization_lookup))]["methodology_version"]
                if normalization_applied and normalization_lookup
                else None
            ),
            "normalized_amount_type": (
                normalization_lookup[next(iter(normalization_lookup))]["normalized_amount_type"]
                if normalization_applied and normalization_lookup
                else None
            ),
            "normalization_method": (
                normalization_lookup[next(iter(normalization_lookup))]["normalization_method"]
                if normalization_applied and normalization_lookup
                else None
            ),
            "funding_stream_logic_version": (
                normalization_lookup[next(iter(normalization_lookup))]["funding_stream_logic_version"]
                if normalization_applied and normalization_lookup
                else None
            ),
        },
    }


def fetch_legend_stats(
    db: Session,
    *,
    basis: str,
    geography: str,
    funding_geography_mode: str = "recipient_location",
    metric: str,
    display_mode: str = "total",
    appropriation_type: str = APPROPRIATION_FILTER_ALL,
    assistance_type: str | None = None,
    fiscal_year: int | None = None,
    awarding_office: str | None = None,
    funding_office: str | None = None,
    center: str | None = None,
    state: str | None = None,
    bbox: str | None = None,
    normalize: bool = False,
) -> dict[str, Any]:
    normalized_basis = _normalize_basis(basis)
    normalized_geography = _normalize_geography(geography)
    normalized_mode = _normalize_funding_geography_mode(funding_geography_mode)
    normalized_appropriation_type = _normalize_appropriation_type(appropriation_type)
    normalized_metric = _normalize_metric(metric, basis=normalized_basis)
    normalized_display_mode = _normalize_display_mode(display_mode, metric=normalized_metric)
    normalization_requested = bool(normalize)
    _ensure_required_tables(
        db,
        basis=normalized_basis,
        geography=normalized_geography,
        funding_geography_mode=normalized_mode,
        include_national=True,
    )

    effective_fiscal_year = fiscal_year
    if normalized_basis == "prime" and effective_fiscal_year is None:
        effective_fiscal_year = _latest_prime_transaction_fiscal_year(db)
    normalization_supported, normalization_reason = usaspending_normalization_compatibility(
        basis=normalized_basis,
        metric=normalized_metric,
        funding_geography_mode=normalized_mode,
        appropriation_type=normalized_appropriation_type,
        assistance_type=assistance_type,
        awarding_office=awarding_office,
        funding_office=funding_office,
        center=center,
    )
    normalization_lookup = (
        fetch_state_normalization_lookup(
            db,
            source_system="usaspending",
            fiscal_year=int(effective_fiscal_year),
        )
        if normalization_requested and normalization_supported and effective_fiscal_year is not None
        else {}
    )
    normalization_applied = normalization_requested and normalization_supported and bool(normalization_lookup)

    metric_column = _metric_column(normalized_basis, normalized_metric)
    effective_mode = (
        normalized_mode
        if normalized_basis == "prime"
        else "recipient_location"
    )
    summary_table = _summary_table(
        basis=normalized_basis,
        geography=normalized_geography,
        funding_geography_mode=effective_mode,
    )
    filter_sql, filter_params = _summary_filters_sql(
        basis=normalized_basis,
        geography=normalized_geography,
        appropriation_type=normalized_appropriation_type,
        assistance_type=assistance_type,
        fiscal_year=effective_fiscal_year,
        awarding_office=awarding_office,
        funding_office=funding_office,
        center=center,
        state=state,
    )
    bbox_params = _parse_bbox(bbox)

    params: dict[str, Any] = dict(filter_params)
    summary_sql = _summary_aggregate_sql(
        basis=normalized_basis,
        metric_column=metric_column,
        table_name=summary_table,
        where_sql=filter_sql,
    )

    if normalized_geography == "county":
        bbox_join = ""
        bbox_filter = ""
        if bbox_params is not None:
            bbox_join = (
                f"JOIN {COUNTY_BOUNDARY_TABLE} AS b ON b.geoid = summary.geography_id"
            )
            bbox_filter = (
                "WHERE b.geom && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) "
                "AND ST_Intersects(b.geom, ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326))"
            )
            params.update(bbox_params)

        rows = db.execute(
            text(
                f"""
                WITH summary AS ({summary_sql})
                SELECT
                    summary.geography_id,
                    c.state_abbr AS state_code,
                    summary.metric_value,
                    summary.metric_per_capita,
                    summary.population,
                    summary.funding_per_capita,
                    summary.fy_obligated_amount,
                    summary.fy_outlayed_amount_estimated,
                    summary.transaction_count,
                    summary.distinct_award_count,
                    summary.total_funding_amount,
                    summary.total_obligated_amount,
                    summary.total_outlayed_amount,
                    summary.award_count,
                    summary.total_subaward_amount,
                    summary.subaward_count
                FROM summary
                {bbox_join}
                {bbox_filter}
                """
            ),
            params,
        ).mappings().all()
    else:
        bbox_join = ""
        bbox_filter = ""
        if bbox_params is not None:
            bbox_join = f"JOIN {STATE_BOUNDARY_TABLE} AS sb ON sb.state_abbr = summary.geography_id"
            bbox_filter = (
                "WHERE sb.geom && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) "
                "AND ST_Intersects(sb.geom, ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326))"
            )
            params.update(bbox_params)

        rows = db.execute(
            text(
                f"""
                WITH summary AS ({summary_sql})
                SELECT
                    summary.geography_id,
                    summary.metric_value,
                    summary.metric_per_capita,
                    summary.population,
                    summary.funding_per_capita,
                    summary.fy_obligated_amount,
                    summary.fy_outlayed_amount_estimated,
                    summary.transaction_count,
                    summary.distinct_award_count,
                    summary.total_funding_amount,
                    summary.total_obligated_amount,
                    summary.total_outlayed_amount,
                    summary.award_count,
                    summary.total_subaward_amount,
                    summary.subaward_count
                FROM summary
                {bbox_join}
                {bbox_filter}
                """
            ),
            params,
        ).mappings().all()

    metric_values = []
    normalized_visible_dollars = 0.0
    has_normalized_visible_dollars = False
    for row in rows:
        state_code = str(
            row.get("geography_id")
            if normalized_geography == "state"
            else row.get("state_code")
            or ""
        ).strip().upper()
        raw_value = (
            row.get("metric_per_capita")
            if normalized_display_mode == "per_capita"
            else row.get("metric_value")
        )
        if normalization_applied and state_code in normalization_lookup:
            normalized_total = _json_number(normalization_lookup[state_code].get("normalized_amount"))
            if normalized_geography == "county":
                factor = _json_number(normalization_lookup[state_code].get("normalization_factor"))
                if normalized_total is not None and row.get("metric_value") is not None and factor is not None:
                    normalized_total = float(row.get("metric_value")) * float(factor)
            if normalized_metric in DOLLAR_METRICS and normalized_total is not None:
                normalized_visible_dollars += float(normalized_total)
                has_normalized_visible_dollars = True
            if normalized_display_mode == "per_capita":
                population = _json_number(row.get("population"))
                raw_value = (
                    float(normalized_total) / float(population)
                    if normalized_total is not None and population not in (None, 0)
                    else None
                )
            else:
                raw_value = normalized_total
        if raw_value is None:
            continue
        numeric = float(raw_value)
        if math.isfinite(numeric):
            metric_values.append(numeric)
    bins = _compute_bins(metric_values, bins=5)

    def _sum_column(column: str) -> float:
        return float(
            sum(
                float(row.get(column) or 0)
                for row in rows
                if row.get(column) is not None and math.isfinite(float(row.get(column)))
            )
        )

    if normalized_basis == "prime":
        total_visible_awards = int(
            sum(int(row.get("distinct_award_count") or 0) for row in rows)
        )
    else:
        total_visible_awards = int(
            sum(int(row.get("subaward_count") or 0) for row in rows)
        )

    total_visible_dollars = _sum_column(_metric_column(normalized_basis, normalized_metric))
    if normalization_applied and normalized_metric == "fy_obligated":
        total_visible_dollars = normalized_visible_dollars if has_normalized_visible_dollars else None
    if normalized_metric not in DOLLAR_METRICS:
        total_visible_dollars = None

    national_summary = _fetch_national_summary(
        db,
        basis=normalized_basis,
        funding_geography_mode=effective_mode,
        metric=normalized_metric,
        display_mode=normalized_display_mode,
        appropriation_type=normalized_appropriation_type,
        assistance_type=assistance_type,
        fiscal_year=effective_fiscal_year,
        awarding_office=awarding_office,
        funding_office=funding_office,
        center=center,
    )
    note_parts: list[str] = []
    if normalized_display_mode == "per_capita":
        note_parts.append(
            "Per-capita values use the app population denominator derived from dim_county total population."
        )
    if normalized_appropriation_type == APPROPRIATION_TYPE_COVID_EMERGENCY:
        note_parts.append(
            "COVID / emergency supplemental funding is identified using official emergency funding codes "
            "reported in the source data."
        )
    if normalization_applied:
        note_parts.append(
            build_normalization_note(
                fiscal_year=int(effective_fiscal_year),
                normalization_applied=True,
                reason=(
                    "County values preserve the raw within-state distribution and are rescaled to the normalized state total."
                    if normalized_geography == "county"
                    else None
                ),
            )
        )
    elif normalization_requested and normalization_reason:
        note_parts.append(normalization_reason)

    return {
        "basis": normalized_basis,
        "appropriation_type": normalized_appropriation_type,
        "appropriation_type_label": APPROPRIATION_FILTER_LABELS.get(
            normalized_appropriation_type,
            normalized_appropriation_type,
        ),
        "funding_geography_mode": effective_mode,
        "geography": normalized_geography,
        "metric": normalized_metric,
        "metric_label": _metric_label_for_display_mode(normalized_metric, normalized_display_mode),
        "display_mode": normalized_display_mode,
        "min": min(metric_values) if metric_values else None,
        "max": max(metric_values) if metric_values else None,
        "bins": bins,
        "mapped_geographies": len(metric_values),
        "n": len(metric_values),
        "noDataCount": 0,
        "total_visible_dollars": total_visible_dollars,
        "total_visible_awards": total_visible_awards,
        "fiscal_year": effective_fiscal_year,
        "national_summary": national_summary,
        "note": " ".join(note_parts) if note_parts else None,
        "normalization_requested": normalization_requested,
        "normalization_applied": normalization_applied,
        "normalization_status_label": (
            normalization_lookup[next(iter(normalization_lookup))]["status_label"]
            if normalization_applied and normalization_lookup
            else None
        ),
        "methodology_version": (
            normalization_lookup[next(iter(normalization_lookup))]["methodology_version"]
            if normalization_applied and normalization_lookup
            else None
        ),
        "normalized_amount_type": (
            normalization_lookup[next(iter(normalization_lookup))]["normalized_amount_type"]
            if normalization_applied and normalization_lookup
            else None
        ),
        "normalization_method": (
            normalization_lookup[next(iter(normalization_lookup))]["normalization_method"]
            if normalization_applied and normalization_lookup
            else None
        ),
        "funding_stream_logic_version": (
            normalization_lookup[next(iter(normalization_lookup))]["funding_stream_logic_version"]
            if normalization_applied and normalization_lookup
            else None
        ),
    }


def fetch_national_summary(
    db: Session,
    *,
    basis: str,
    funding_geography_mode: str = "recipient_location",
    metric: str,
    display_mode: str = "total",
    appropriation_type: str = APPROPRIATION_FILTER_ALL,
    assistance_type: str | None = None,
    fiscal_year: int | None = None,
    awarding_office: str | None = None,
    funding_office: str | None = None,
    center: str | None = None,
) -> dict[str, Any]:
    normalized_basis = _normalize_basis(basis)
    normalized_mode = _normalize_funding_geography_mode(funding_geography_mode)
    normalized_appropriation_type = _normalize_appropriation_type(appropriation_type)
    normalized_metric = _normalize_metric(metric, basis=normalized_basis)
    normalized_display_mode = _normalize_display_mode(display_mode, metric=normalized_metric)
    _ensure_required_tables(
        db,
        basis=normalized_basis,
        geography="state",
        funding_geography_mode=normalized_mode,
        include_national=True,
    )

    effective_fiscal_year = fiscal_year
    if normalized_basis == "prime" and effective_fiscal_year is None:
        effective_fiscal_year = _latest_prime_transaction_fiscal_year(db)
    effective_mode = normalized_mode if normalized_basis == "prime" else "recipient_location"
    national_summary = _fetch_national_summary(
        db,
        basis=normalized_basis,
        funding_geography_mode=effective_mode,
        metric=normalized_metric,
        display_mode=normalized_display_mode,
        appropriation_type=normalized_appropriation_type,
        assistance_type=assistance_type,
        fiscal_year=effective_fiscal_year,
        awarding_office=awarding_office,
        funding_office=funding_office,
        center=center,
    )

    notes: list[str] = []
    if normalized_display_mode == "per_capita":
        notes.append(
            "Per-capita values use the app population denominator derived from dim_county total population."
        )
    if normalized_appropriation_type == APPROPRIATION_TYPE_COVID_EMERGENCY:
        notes.append(
            "COVID / emergency supplemental funding is identified using official emergency funding codes "
            "reported in the source data."
        )

    return {
        "basis": normalized_basis,
        "funding_geography_mode": effective_mode,
        "appropriation_type": normalized_appropriation_type,
        "appropriation_type_label": APPROPRIATION_FILTER_LABELS.get(
            normalized_appropriation_type,
            normalized_appropriation_type,
        ),
        "metric": normalized_metric,
        "metric_label": _metric_label_for_display_mode(normalized_metric, normalized_display_mode),
        "display_mode": normalized_display_mode,
        "fiscal_year": effective_fiscal_year,
        "summary": national_summary,
        "note": " ".join(notes) if notes else None,
    }


def _profile_state_name_from_code(db: Session, state_code: str) -> str:
    row = db.execute(
        text(
            f"""
            SELECT COALESCE(NULLIF(TRIM(state_name), ''), state_abbr) AS state_name
            FROM {STATE_BOUNDARY_TABLE}
            WHERE state_abbr = :state_code
            LIMIT 1
            """
        ),
        {"state_code": state_code},
    ).mappings().one_or_none()
    if row and row.get("state_name"):
        return str(row["state_name"])
    return state_code


def _profile_population_for_state(db: Session, state_code: str) -> tuple[float | None, str | None]:
    row = db.execute(
        text(
            f"""
            SELECT population, source_label
            FROM {POPULATION_VIEW_TABLE}
            WHERE geography_type = 'state'
              AND UPPER(state_abbr) = :state_code
            LIMIT 1
            """
        ),
        {"state_code": state_code},
    ).mappings().one_or_none()
    if not row:
        return None, None
    population = _json_number(row.get("population"))
    return (
        float(population) if population is not None else None,
        _strip_optional(row.get("source_label")),
    )


def _profile_timeframe_label(
    *,
    requested_fiscal_year: int | None,
    min_fiscal_year: int | None,
    max_fiscal_year: int | None,
) -> str:
    if requested_fiscal_year is not None:
        return f"Fiscal Year {requested_fiscal_year}"
    if min_fiscal_year is None and max_fiscal_year is None:
        return "All available years"
    if min_fiscal_year is None:
        return f"Through Fiscal Year {max_fiscal_year}"
    if max_fiscal_year is None:
        return f"Starting Fiscal Year {min_fiscal_year}"
    if min_fiscal_year == max_fiscal_year:
        return f"Fiscal Year {min_fiscal_year}"
    return f"Fiscal Years {min_fiscal_year}-{max_fiscal_year}"


def _profile_grouping_metadata() -> dict[str, str]:
    return {
        "category_label": "Derived category",
        "subcategory_label": "Derived sub-category",
        "category_method": (
            "Derived from CDC center / sub-agency metadata when available, "
            "with assistance type fallback when center metadata is missing."
        ),
        "subcategory_method": (
            "Derived from funding or awarding office metadata when available, "
            "with program and assistance title fallback when office metadata is missing."
        ),
    }


def _profile_methodology_notes(
    *,
    basis: str,
    funding_geography_mode: str,
    appropriation_type: str,
    fiscal_year: int | None,
    state_name: str,
    normalization_note: str | None = None,
) -> list[str]:
    notes = [
        f"This page summarizes CDC funding obligations for {state_name} using CHIP's CDC funding pipeline.",
        (
            "Category and sub-category groupings are inferred from CHIP's public CDC funding metadata, "
            "not copied from CDC profile PDFs."
        ),
        (
            "Totals may differ from CDC profile PDFs or other federal dashboards because timing, inclusion rules, "
            "recipient geography, and CHIP methodology can differ."
        ),
        (
            "Award-level rows originate from CHIP's CDC funding records. When normalized mode is active, detail amounts are proportionally rescaled to the normalized state total so the report stays internally consistent."
        ),
    ]
    if basis == "prime":
        notes.append(
            "Prime-award totals use summed federal action obligations from filtered CDC prime transaction rows."
        )
    else:
        notes.append(
            "Subaward totals use filtered CDC subaward amounts reported for recipients in the selected state."
        )
    if fiscal_year is not None:
        notes.append(f"The current report is filtered to Fiscal Year {fiscal_year}.")
    else:
        notes.append("No single fiscal year filter is applied, so totals span all currently available fiscal years in CHIP.")
    if appropriation_type == APPROPRIATION_TYPE_COVID_EMERGENCY:
        notes.append(
            "COVID / emergency supplemental funding is identified using official emergency funding codes present in the source data."
        )
    if funding_geography_mode == "statewide_allocation" and basis == "prime":
        notes.append(
            "The map was launched from estimated statewide allocation mode. That allocation changes county breakout logic, but state profile totals remain state-level obligations."
        )
    notes.append(
        "CHIP's current CDC methodology can include or exclude special transfer, procurement, or other funding streams according to the frozen funding-scope rules used in the pipeline."
    )
    if normalization_note:
        notes.append(normalization_note)
    return notes


def _normalize_profile_detail_sort(sort_by: str | None, sort_dir: str | None) -> tuple[str, str]:
    allowed_columns = {
        "category": "award_rows.category",
        "subcategory": "award_rows.subcategory",
        "project_title": "award_rows.project_title",
        "grantee_name": "award_rows.grantee_name",
        "city": "award_rows.city",
        "county": "award_rows.county",
        "amount": "award_rows.amount",
        "latest_action_date": "award_rows.latest_action_date",
        "fain": "award_rows.fain",
    }
    normalized_sort_by = str(sort_by or "amount").strip().lower()
    if normalized_sort_by not in allowed_columns:
        allowed = ", ".join(sorted(allowed_columns))
        raise HTTPException(status_code=400, detail=f"sort_by must be one of {allowed}")
    normalized_sort_dir = str(sort_dir or "desc").strip().lower()
    if normalized_sort_dir not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="sort_dir must be asc or desc")
    return allowed_columns[normalized_sort_by], normalized_sort_dir


def _build_state_profile_award_rows_sql(
    *,
    basis: str,
    state_code: str,
    funding_geography_mode: str,
    appropriation_type: str,
    assistance_type: str | None,
    fiscal_year: int | None,
    awarding_office: str | None,
    funding_office: str | None,
    center: str | None,
) -> tuple[str, dict[str, Any], str]:
    normalized_basis = _normalize_basis(basis)
    normalized_state_code = _normalize_state_code(state_code)
    if normalized_state_code is None:
        raise HTTPException(status_code=400, detail="state must be a 2-letter state code")
    normalized_mode = _normalize_funding_geography_mode(funding_geography_mode)
    normalized_appropriation_type = _normalize_appropriation_type(appropriation_type)
    normalized_fiscal_year = _normalize_optional_fiscal_year(fiscal_year, field_name="fiscal_year")
    normalized_assistance_type = _strip_optional(assistance_type)
    normalized_awarding_office = _strip_optional(awarding_office)
    normalized_funding_office = _strip_optional(funding_office)
    normalized_center = _strip_optional(center)

    effective_mode = normalized_mode if normalized_basis == "prime" else "recipient_location"
    params: dict[str, Any] = {"state_code": normalized_state_code}

    if normalized_basis == "prime":
        where_clauses = [
            "tx.assistance_award_unique_key IS NOT NULL",
            "COALESCE(NULLIF(BTRIM(tx.recipient_state_code), ''), NULLIF(BTRIM(p.recipient_state_code), '')) = :state_code",
        ]
        if normalized_assistance_type:
            params["assistance_type"] = normalized_assistance_type
            where_clauses.append(
                "COALESCE(NULLIF(BTRIM(tx.assistance_type_description), ''), NULLIF(BTRIM(p.assistance_type_description), '')) = :assistance_type"
            )
        if normalized_fiscal_year is not None:
            params["fiscal_year"] = normalized_fiscal_year
            where_clauses.append("tx.action_date_fiscal_year = :fiscal_year")
        if normalized_appropriation_type != APPROPRIATION_FILTER_ALL:
            params["appropriation_type"] = normalized_appropriation_type
            where_clauses.append("tx.appropriation_type = :appropriation_type")
        if normalized_awarding_office:
            params["awarding_office"] = normalized_awarding_office
            where_clauses.append(
                "COALESCE(NULLIF(BTRIM(tx.awarding_office_name), ''), NULLIF(BTRIM(p.awarding_office_name), '')) = :awarding_office"
            )
        if normalized_funding_office:
            params["funding_office"] = normalized_funding_office
            where_clauses.append(
                "COALESCE(NULLIF(BTRIM(tx.funding_office_name), ''), NULLIF(BTRIM(p.funding_office_name), '')) = :funding_office"
            )
        if normalized_center:
            params["center"] = normalized_center
            where_clauses.append(
                "("
                "COALESCE(NULLIF(BTRIM(tx.awarding_sub_agency_name), ''), NULLIF(BTRIM(p.awarding_sub_agency_name), '')) = :center "
                "OR COALESCE(NULLIF(BTRIM(tx.funding_sub_agency_name), ''), NULLIF(BTRIM(p.funding_sub_agency_name), '')) = :center"
                ")"
            )

        cte_sql = f"""
            WITH award_base AS (
                SELECT
                    p.unique_key AS record_id,
                    'prime_award'::text AS record_type,
                    p.fain,
                    COALESCE(NULLIF(BTRIM(p.recipient_name), ''), 'Not available') AS grantee_name,
                    MAX(NULLIF(BTRIM(tx.recipient_city_name), '')) AS city,
                    COALESCE(
                        NULLIF(BTRIM(p.recipient_county_name), ''),
                        MAX(NULLIF(BTRIM(tx.recipient_county_name), ''))
                    ) AS county,
                    MAX(
                        COALESCE(
                            NULLIF(BTRIM(tx.recipient_state_name), ''),
                            NULLIF(BTRIM(p.recipient_state_name), '')
                        )
                    ) AS state_name,
                    MAX(
                        COALESCE(
                            NULLIF(BTRIM(tx.recipient_state_code), ''),
                            NULLIF(BTRIM(p.recipient_state_code), '')
                        )
                    ) AS state_code,
                    MAX(
                        COALESCE(
                            NULLIF(BTRIM(p.funding_sub_agency_name), ''),
                            NULLIF(BTRIM(p.awarding_sub_agency_name), ''),
                            NULLIF(BTRIM(tx.funding_sub_agency_name), ''),
                            NULLIF(BTRIM(tx.awarding_sub_agency_name), '')
                        )
                    ) AS center_name,
                    MAX(
                        COALESCE(
                            NULLIF(BTRIM(p.funding_office_name), ''),
                            NULLIF(BTRIM(p.awarding_office_name), ''),
                            NULLIF(BTRIM(tx.funding_office_name), ''),
                            NULLIF(BTRIM(tx.awarding_office_name), '')
                        )
                    ) AS office_name,
                    MAX(
                        COALESCE(
                            NULLIF(BTRIM(p.cfda_program_title), ''),
                            NULLIF(BTRIM(tx.cfda_title), '')
                        )
                    ) AS program_title,
                    MAX(
                        COALESCE(
                            NULLIF(BTRIM(tx.transaction_description), ''),
                            NULLIF(BTRIM(tx.prime_award_base_transaction_description), ''),
                            NULLIF(BTRIM(p.prime_award_base_transaction_description), ''),
                            NULLIF(BTRIM(p.cfda_program_title), ''),
                            NULLIF(BTRIM(p.fain), '')
                        )
                    ) AS project_title,
                    COALESCE(NULLIF(BTRIM(p.assistance_type_description), ''), MAX(NULLIF(BTRIM(tx.assistance_type_description), ''))) AS assistance_type_description,
                    COALESCE(SUM(COALESCE(tx.federal_action_obligation, 0)), 0)::numeric AS amount,
                    MIN(tx.action_date_fiscal_year)::integer AS min_fiscal_year,
                    MAX(tx.action_date_fiscal_year)::integer AS max_fiscal_year,
                    MAX(tx.action_date) AS latest_action_date,
                    MAX(p.usaspending_permalink) AS usaspending_permalink,
                    MAX(p.total_funding_amount) AS lifetime_total_funding_amount
                FROM {PRIME_TX_TABLE} AS tx
                LEFT JOIN {PRIME_TABLE} AS p
                  ON p.unique_key = tx.assistance_award_unique_key
                WHERE {' AND '.join(where_clauses)}
                GROUP BY
                    p.unique_key,
                    p.fain,
                    p.recipient_name,
                    p.recipient_county_name,
                    p.assistance_type_description
            ),
            award_rows AS (
                SELECT
                    award_base.record_id,
                    award_base.record_type,
                    award_base.fain,
                    award_base.grantee_name,
                    award_base.city,
                    award_base.county,
                    COALESCE(
                        NULLIF(BTRIM(award_base.center_name), ''),
                        NULLIF(BTRIM(award_base.assistance_type_description), ''),
                        'Unclassified'
                    ) AS category,
                    COALESCE(
                        NULLIF(BTRIM(award_base.office_name), ''),
                        NULLIF(BTRIM(award_base.program_title), ''),
                        NULLIF(BTRIM(award_base.assistance_type_description), ''),
                        'Unspecified'
                    ) AS subcategory,
                    COALESCE(
                        NULLIF(BTRIM(award_base.project_title), ''),
                        NULLIF(BTRIM(award_base.program_title), ''),
                        NULLIF(BTRIM(award_base.fain), ''),
                        award_base.record_id
                    ) AS project_title,
                    award_base.amount,
                    award_base.min_fiscal_year,
                    award_base.max_fiscal_year,
                    award_base.latest_action_date,
                    award_base.state_name,
                    award_base.state_code,
                    award_base.usaspending_permalink,
                    award_base.lifetime_total_funding_amount
                FROM award_base
            )
        """
        return cte_sql, params, effective_mode

    where_clauses = [
        "s.subawardee_state_code = :state_code",
    ]
    if normalized_fiscal_year is not None:
        params["fiscal_year"] = normalized_fiscal_year
        where_clauses.append("s.subaward_action_date_fiscal_year = :fiscal_year")
    if normalized_appropriation_type != APPROPRIATION_FILTER_ALL:
        params["appropriation_type"] = normalized_appropriation_type
        where_clauses.append("s.appropriation_type = :appropriation_type")
    if normalized_awarding_office:
        params["awarding_office"] = normalized_awarding_office
        where_clauses.append("s.prime_award_awarding_office_name = :awarding_office")
    if normalized_funding_office:
        params["funding_office"] = normalized_funding_office
        where_clauses.append("s.prime_award_funding_office_name = :funding_office")
    if normalized_center:
        params["center"] = normalized_center
        where_clauses.append(
            "("
            "s.prime_award_awarding_sub_agency_name = :center "
            "OR s.prime_award_funding_sub_agency_name = :center"
            ")"
        )

    cte_sql = f"""
        WITH award_rows AS (
            SELECT
                s.id::text AS record_id,
                'subaward'::text AS record_type,
                s.prime_award_fain AS fain,
                COALESCE(NULLIF(BTRIM(s.subawardee_name), ''), 'Not available') AS grantee_name,
                NULLIF(BTRIM(s.subawardee_city_name), '') AS city,
                COALESCE(NULLIF(BTRIM(county.county_name), ''), NULL) AS county,
                COALESCE(
                    NULLIF(BTRIM(COALESCE(s.prime_award_funding_sub_agency_name, s.prime_award_awarding_sub_agency_name)), ''),
                    'Unclassified'
                ) AS category,
                COALESCE(
                    NULLIF(BTRIM(COALESCE(s.prime_award_funding_office_name, s.prime_award_awarding_office_name)), ''),
                    NULLIF(BTRIM(s.prime_award_base_transaction_description), ''),
                    NULLIF(BTRIM(s.prime_award_fain), ''),
                    'Unspecified'
                ) AS subcategory,
                COALESCE(
                    NULLIF(BTRIM(s.subaward_description), ''),
                    NULLIF(BTRIM(s.prime_award_base_transaction_description), ''),
                    NULLIF(BTRIM(s.prime_award_fain), ''),
                    s.subaward_unique_key
                ) AS project_title,
                COALESCE(s.subaward_amount, 0)::numeric AS amount,
                s.subaward_action_date_fiscal_year::integer AS min_fiscal_year,
                s.subaward_action_date_fiscal_year::integer AS max_fiscal_year,
                s.subaward_action_date AS latest_action_date,
                COALESCE(NULLIF(BTRIM(s.subawardee_state_name), ''), NULLIF(BTRIM(s.subaward_primary_place_of_performance_state_name), '')) AS state_name,
                s.subawardee_state_code AS state_code,
                s.usaspending_permalink,
                NULL::numeric AS lifetime_total_funding_amount
            FROM {SUBAWARD_TABLE} AS s
            LEFT JOIN {COUNTY_DIM_TABLE} AS county
              ON county.location_id = s.subawardee_county_fips
            WHERE {' AND '.join(where_clauses)}
        )
    """
    return cte_sql, params, effective_mode


def _build_state_profile_normalization_context(
    db: Session,
    *,
    normalize: bool,
    normalization_funding_mode: str | None = None,
    state_code: str,
    basis: str,
    funding_geography_mode: str,
    appropriation_type: str,
    assistance_type: str | None,
    fiscal_year: int | None,
    awarding_office: str | None,
    funding_office: str | None,
    center: str | None,
    raw_total_funding: Any,
) -> dict[str, Any]:
    normalized_state_code = _normalize_state_code(state_code)
    if normalized_state_code is None:
        raise HTTPException(status_code=400, detail="state must be a 2-letter state code")
    normalized_basis = _normalize_basis(basis)
    normalized_mode = _normalize_funding_geography_mode(funding_geography_mode)
    normalized_appropriation_type = _normalize_appropriation_type(appropriation_type)
    normalized_assistance_type = _strip_optional(assistance_type)
    normalized_awarding_office = _strip_optional(awarding_office)
    normalized_funding_office = _strip_optional(funding_office)
    normalized_center = _strip_optional(center)
    normalized_fiscal_year = _normalize_optional_fiscal_year(fiscal_year, field_name="fiscal_year")
    raw_total_amount = _json_number(raw_total_funding)
    normalization_requested = bool(normalize)
    normalization_supported = False
    normalization_reason = None
    normalization_row = None
    normalized_total_funding = None
    normalization_factor = None
    normalized_amount_type = None
    normalization_status_label = None
    normalization_method = None
    funding_stream_logic_version = None
    methodology_version = None
    confidence_note = None
    normalized_mode_token = str(normalization_funding_mode or CDCFundingMode.CHIP_NORMALIZED.value).strip().lower()
    normalized_mode_label = (
        "Normalized data"
        if normalization_funding_mode is None
        else FUNDING_MODE_LABELS.get(normalized_mode_token, "CHIP normalized funding")
    )

    if normalization_requested:
        if normalized_fiscal_year is None:
            normalization_reason = (
                f"{normalized_mode_label} requires an explicit fiscal year in the shared state funding profile URL."
            )
        else:
            normalization_supported, normalization_reason = usaspending_normalization_compatibility(
                basis=normalized_basis,
                metric="fy_obligated",
                funding_geography_mode=normalized_mode,
                appropriation_type=normalized_appropriation_type,
                assistance_type=normalized_assistance_type,
                awarding_office=normalized_awarding_office,
                funding_office=normalized_funding_office,
                center=normalized_center,
            )

    if normalization_requested and normalization_supported and normalized_fiscal_year is not None:
        normalization_lookup = fetch_state_normalization_lookup(
            db,
            source_system="usaspending",
            fiscal_year=int(normalized_fiscal_year),
            lookup_variant=normalization_lookup_variant_for_mode(normalized_mode_token),
        )
        normalization_row = normalization_lookup.get(normalized_state_code)
        if normalization_row is None:
            normalization_reason = (
                f"No {normalized_mode_label} benchmark is available for {normalized_state_code} "
                f"in Fiscal Year {normalized_fiscal_year}."
            )
        else:
            normalized_total_funding = _json_number(normalization_row.get("normalized_amount"))
            normalization_factor = _json_number(normalization_row.get("normalization_factor"))
            normalized_amount_type = normalization_row.get("normalized_amount_type")
            normalization_status_label = normalization_row.get("status_label")
            normalization_method = normalization_row.get("normalization_method")
            funding_stream_logic_version = normalization_row.get("funding_stream_logic_version")
            methodology_version = normalization_row.get("methodology_version")
            confidence_note = normalization_row.get("confidence_note")
            if normalized_total_funding is None and raw_total_amount is not None and normalization_factor is not None:
                normalized_total_funding = float(raw_total_amount) * float(normalization_factor)

            if normalized_total_funding is None:
                normalization_reason = (
                    f"Normalization metadata for {normalized_state_code} in Fiscal Year {normalized_fiscal_year} "
                    "did not include a usable state total."
                )
            elif raw_total_amount is None:
                normalization_reason = "The raw state funding total was unavailable, so normalized scaling could not be applied."
            elif float(raw_total_amount) == 0.0 and float(normalized_total_funding) != 0.0:
                normalization_reason = (
                    "The filtered raw state funding total is zero, so the profile cannot be rescaled to a non-zero normalized total."
                )
            elif float(raw_total_amount) == 0.0:
                normalization_factor = 0.0
            else:
                normalization_factor = float(normalized_total_funding) / float(raw_total_amount)

    normalization_applied = bool(
        normalization_requested
        and normalization_supported
        and normalized_total_funding is not None
        and normalization_factor is not None
        and normalization_reason is None
    )
    normalization_note = None
    if normalization_applied and normalized_fiscal_year is not None:
        normalization_note = build_normalization_note(
            fiscal_year=int(normalized_fiscal_year),
            normalization_applied=True,
            reason=(
                (
                    "State profile summary, grouped tables, and detail rows preserve the filtered raw award mix while rescaling amounts to CHIP's v1.1 emergency-classification state benchmark."
                    if normalized_mode_token == CDCFundingMode.CHIP_NORMALIZED_V11.value
                    else "State profile summary, grouped tables, and detail rows preserve the filtered raw award mix while rescaling amounts to CHIP's normalized state benchmark."
                )
            ),
        )
    elif normalization_requested and normalization_reason:
        normalization_note = normalization_reason

    return {
        "normalization_requested": normalization_requested,
        "normalization_supported": normalization_supported,
        "normalization_applied": normalization_applied,
        "data_mode_label": normalized_mode_label if normalization_applied else "Raw obligations",
        "normalization_note": normalization_note,
        "normalization_factor": normalization_factor,
        "normalized_total_funding": normalized_total_funding,
        "normalized_amount_type": normalized_amount_type,
        "normalization_status_label": normalization_status_label,
        "normalization_method": normalization_method,
        "funding_stream_logic_version": funding_stream_logic_version,
        "methodology_version": methodology_version,
        "normalization_confidence_note": confidence_note,
    }


def _apply_state_profile_normalized_amount(value: Any, normalization: dict[str, Any]) -> Any:
    amount = _json_number(value)
    if not normalization.get("normalization_applied") or amount is None:
        return amount
    factor = _json_number(normalization.get("normalization_factor"))
    if factor is None:
        return amount
    return _json_number(float(amount) * float(factor))


def _state_profile_normalization_payload(normalization: dict[str, Any]) -> dict[str, Any]:
    return {
        "normalization_requested": bool(normalization.get("normalization_requested")),
        "normalization_applied": bool(normalization.get("normalization_applied")),
        "data_mode_label": normalization.get("data_mode_label") or "Raw obligations",
        "normalization_note": normalization.get("normalization_note"),
        "normalization_factor": _json_number(normalization.get("normalization_factor")),
        "normalized_total_funding": _json_number(normalization.get("normalized_total_funding")),
        "normalized_amount_type": normalization.get("normalized_amount_type"),
        "normalization_status_label": normalization.get("normalization_status_label"),
        "normalization_method": normalization.get("normalization_method"),
        "funding_stream_logic_version": normalization.get("funding_stream_logic_version"),
        "methodology_version": normalization.get("methodology_version"),
        "normalization_confidence_note": normalization.get("normalization_confidence_note"),
    }


def fetch_state_profile_summary(
    db: Session,
    *,
    state: str,
    basis: str = "prime",
    funding_geography_mode: str = "recipient_location",
    appropriation_type: str = APPROPRIATION_FILTER_ALL,
    assistance_type: str | None = None,
    fiscal_year: int | None = None,
    normalize: bool = False,
    normalization_funding_mode: str | None = None,
    awarding_office: str | None = None,
    funding_office: str | None = None,
    center: str | None = None,
) -> dict[str, Any]:
    _ensure_award_tables(db)
    cte_sql, params, effective_mode = _build_state_profile_award_rows_sql(
        basis=basis,
        state_code=state,
        funding_geography_mode=funding_geography_mode,
        appropriation_type=appropriation_type,
        assistance_type=assistance_type,
        fiscal_year=fiscal_year,
        awarding_office=awarding_office,
        funding_office=funding_office,
        center=center,
    )
    state_code = params["state_code"]
    row = db.execute(
        text(
            f"""
            {cte_sql}
            SELECT
                COALESCE(SUM(award_rows.amount), 0)::numeric AS total_funding,
                COUNT(*)::integer AS detail_row_count,
                COUNT(DISTINCT COALESCE(NULLIF(BTRIM(award_rows.fain), ''), award_rows.record_id))::integer AS award_count,
                COUNT(DISTINCT award_rows.category)::integer AS category_count,
                MIN(award_rows.min_fiscal_year)::integer AS min_fiscal_year,
                MAX(award_rows.max_fiscal_year)::integer AS max_fiscal_year,
                MAX(NULLIF(BTRIM(award_rows.state_name), '')) AS state_name
            FROM award_rows
            """
        ),
        params,
    ).mappings().one()
    top_category_row = db.execute(
        text(
            f"""
            {cte_sql}
            SELECT
                award_rows.category,
                SUM(award_rows.amount)::numeric AS amount
            FROM award_rows
            GROUP BY award_rows.category
            ORDER BY amount DESC NULLS LAST, award_rows.category ASC
            LIMIT 1
            """
        ),
        params,
    ).mappings().one_or_none()

    state_name = str(row.get("state_name") or "").strip() or _profile_state_name_from_code(db, state_code)
    population, population_source = _profile_population_for_state(db, state_code)
    raw_total_funding = _json_number(row.get("total_funding")) or 0.0
    normalization = _build_state_profile_normalization_context(
        db,
        normalize=normalize,
        normalization_funding_mode=normalization_funding_mode,
        state_code=state_code,
        basis=basis,
        funding_geography_mode=effective_mode,
        appropriation_type=appropriation_type,
        assistance_type=assistance_type,
        fiscal_year=fiscal_year,
        awarding_office=awarding_office,
        funding_office=funding_office,
        center=center,
        raw_total_funding=raw_total_funding,
    )
    total_funding = (
        normalization["normalized_total_funding"]
        if normalization.get("normalization_applied")
        else raw_total_funding
    )
    funding_per_capita = (
        float(total_funding) / float(population)
        if population not in (None, 0)
        else None
    )
    requested_fiscal_year = _normalize_optional_fiscal_year(fiscal_year, field_name="fiscal_year")
    min_fiscal_year = row.get("min_fiscal_year")
    max_fiscal_year = row.get("max_fiscal_year")
    timeframe_label = _profile_timeframe_label(
        requested_fiscal_year=requested_fiscal_year,
        min_fiscal_year=int(min_fiscal_year) if min_fiscal_year is not None else None,
        max_fiscal_year=int(max_fiscal_year) if max_fiscal_year is not None else None,
    )

    return {
        "basis": _normalize_basis(basis),
        "state_code": state_code,
        "state_name": state_name,
        "fiscal_year": requested_fiscal_year,
        "timeframe_label": timeframe_label,
        "funding_geography_mode": effective_mode,
        "appropriation_type": _normalize_appropriation_type(appropriation_type),
        "appropriation_type_label": APPROPRIATION_FILTER_LABELS.get(
            _normalize_appropriation_type(appropriation_type),
            appropriation_type,
        ),
        "assistance_type": _strip_optional(assistance_type),
        "awarding_office": _strip_optional(awarding_office),
        "funding_office": _strip_optional(funding_office),
        "center": _strip_optional(center),
        "total_funding": float(total_funding),
        "award_count": int(row.get("award_count") or 0),
        "detail_row_count": int(row.get("detail_row_count") or 0),
        "category_count": int(row.get("category_count") or 0),
        "population": population,
        "population_source": population_source,
        "funding_per_capita": _json_number(funding_per_capita),
        "top_category": (
            {
                "name": top_category_row.get("category"),
                "amount": _apply_state_profile_normalized_amount(top_category_row.get("amount"), normalization),
            }
            if top_category_row
            else None
        ),
        "grouping": _profile_grouping_metadata(),
        "methodology_notes": _profile_methodology_notes(
            basis=_normalize_basis(basis),
            funding_geography_mode=effective_mode,
            appropriation_type=_normalize_appropriation_type(appropriation_type),
            fiscal_year=requested_fiscal_year,
            state_name=state_name,
            normalization_note=normalization.get("normalization_note"),
        ),
        **_state_profile_normalization_payload(normalization),
    }


def fetch_state_profile_categories(
    db: Session,
    *,
    state: str,
    basis: str = "prime",
    funding_geography_mode: str = "recipient_location",
    appropriation_type: str = APPROPRIATION_FILTER_ALL,
    assistance_type: str | None = None,
    fiscal_year: int | None = None,
    normalize: bool = False,
    normalization_funding_mode: str | None = None,
    awarding_office: str | None = None,
    funding_office: str | None = None,
    center: str | None = None,
) -> dict[str, Any]:
    _ensure_award_tables(db)
    cte_sql, params, effective_mode = _build_state_profile_award_rows_sql(
        basis=basis,
        state_code=state,
        funding_geography_mode=funding_geography_mode,
        appropriation_type=appropriation_type,
        assistance_type=assistance_type,
        fiscal_year=fiscal_year,
        awarding_office=awarding_office,
        funding_office=funding_office,
        center=center,
    )
    rows = db.execute(
        text(
            f"""
            {cte_sql}
            , category_totals AS (
                SELECT
                    award_rows.category,
                    SUM(award_rows.amount)::numeric AS amount,
                    COUNT(DISTINCT COALESCE(NULLIF(BTRIM(award_rows.fain), ''), award_rows.record_id))::integer AS award_count,
                    COUNT(DISTINCT award_rows.subcategory)::integer AS subcategory_count
                FROM award_rows
                GROUP BY award_rows.category
            ),
            totals AS (
                SELECT COALESCE(SUM(category_totals.amount), 0)::numeric AS total_funding
                FROM category_totals
            )
            SELECT
                category_totals.category,
                category_totals.amount,
                category_totals.award_count,
                category_totals.subcategory_count,
                CASE
                    WHEN totals.total_funding = 0 THEN 0
                    ELSE (category_totals.amount / totals.total_funding) * 100
                END AS share_pct
            FROM category_totals
            CROSS JOIN totals
            ORDER BY category_totals.amount DESC NULLS LAST, category_totals.category ASC
            """
        ),
        params,
    ).mappings().all()
    raw_total_funding = sum(float(_json_number(row.get("amount")) or 0.0) for row in rows)
    normalization = _build_state_profile_normalization_context(
        db,
        normalize=normalize,
        normalization_funding_mode=normalization_funding_mode,
        state_code=params["state_code"],
        basis=basis,
        funding_geography_mode=effective_mode,
        appropriation_type=appropriation_type,
        assistance_type=assistance_type,
        fiscal_year=fiscal_year,
        awarding_office=awarding_office,
        funding_office=funding_office,
        center=center,
        raw_total_funding=raw_total_funding,
    )
    return {
        "basis": _normalize_basis(basis),
        "state_code": params["state_code"],
        "funding_geography_mode": effective_mode,
        **_state_profile_normalization_payload(normalization),
        "rows": [
            {
                "category": row.get("category"),
                "amount": _apply_state_profile_normalized_amount(row.get("amount"), normalization),
                "share_pct": _json_number(row.get("share_pct")),
                "award_count": int(row.get("award_count") or 0),
                "subcategory_count": int(row.get("subcategory_count") or 0),
            }
            for row in rows
        ],
        "grouping": _profile_grouping_metadata(),
    }


def fetch_state_profile_subcategories(
    db: Session,
    *,
    state: str,
    basis: str = "prime",
    funding_geography_mode: str = "recipient_location",
    appropriation_type: str = APPROPRIATION_FILTER_ALL,
    assistance_type: str | None = None,
    fiscal_year: int | None = None,
    normalize: bool = False,
    normalization_funding_mode: str | None = None,
    awarding_office: str | None = None,
    funding_office: str | None = None,
    center: str | None = None,
) -> dict[str, Any]:
    _ensure_award_tables(db)
    cte_sql, params, effective_mode = _build_state_profile_award_rows_sql(
        basis=basis,
        state_code=state,
        funding_geography_mode=funding_geography_mode,
        appropriation_type=appropriation_type,
        assistance_type=assistance_type,
        fiscal_year=fiscal_year,
        awarding_office=awarding_office,
        funding_office=funding_office,
        center=center,
    )
    rows = db.execute(
        text(
            f"""
            {cte_sql}
            , subcategory_totals AS (
                SELECT
                    award_rows.category,
                    award_rows.subcategory,
                    SUM(award_rows.amount)::numeric AS amount,
                    COUNT(DISTINCT COALESCE(NULLIF(BTRIM(award_rows.fain), ''), award_rows.record_id))::integer AS award_count
                FROM award_rows
                GROUP BY award_rows.category, award_rows.subcategory
            ),
            category_totals AS (
                SELECT
                    subcategory_totals.category,
                    SUM(subcategory_totals.amount)::numeric AS category_amount
                FROM subcategory_totals
                GROUP BY subcategory_totals.category
            ),
            grand_total AS (
                SELECT COALESCE(SUM(subcategory_totals.amount), 0)::numeric AS total_funding
                FROM subcategory_totals
            )
            SELECT
                subcategory_totals.category,
                subcategory_totals.subcategory,
                subcategory_totals.amount,
                subcategory_totals.award_count,
                CASE
                    WHEN grand_total.total_funding = 0 THEN 0
                    ELSE (subcategory_totals.amount / grand_total.total_funding) * 100
                END AS share_total_pct,
                CASE
                    WHEN category_totals.category_amount = 0 THEN 0
                    ELSE (subcategory_totals.amount / category_totals.category_amount) * 100
                END AS share_category_pct
            FROM subcategory_totals
            JOIN category_totals
              ON category_totals.category = subcategory_totals.category
            CROSS JOIN grand_total
            ORDER BY subcategory_totals.category ASC, subcategory_totals.amount DESC NULLS LAST, subcategory_totals.subcategory ASC
            """
        ),
        params,
    ).mappings().all()
    raw_total_funding = sum(float(_json_number(row.get("amount")) or 0.0) for row in rows)
    normalization = _build_state_profile_normalization_context(
        db,
        normalize=normalize,
        normalization_funding_mode=normalization_funding_mode,
        state_code=params["state_code"],
        basis=basis,
        funding_geography_mode=effective_mode,
        appropriation_type=appropriation_type,
        assistance_type=assistance_type,
        fiscal_year=fiscal_year,
        awarding_office=awarding_office,
        funding_office=funding_office,
        center=center,
        raw_total_funding=raw_total_funding,
    )
    return {
        "basis": _normalize_basis(basis),
        "state_code": params["state_code"],
        "funding_geography_mode": effective_mode,
        **_state_profile_normalization_payload(normalization),
        "rows": [
            {
                "category": row.get("category"),
                "subcategory": row.get("subcategory"),
                "amount": _apply_state_profile_normalized_amount(row.get("amount"), normalization),
                "award_count": int(row.get("award_count") or 0),
                "share_total_pct": _json_number(row.get("share_total_pct")),
                "share_category_pct": _json_number(row.get("share_category_pct")),
            }
            for row in rows
        ],
        "grouping": _profile_grouping_metadata(),
    }


def fetch_state_profile_details(
    db: Session,
    *,
    state: str,
    basis: str = "prime",
    funding_geography_mode: str = "recipient_location",
    appropriation_type: str = APPROPRIATION_FILTER_ALL,
    assistance_type: str | None = None,
    fiscal_year: int | None = None,
    normalize: bool = False,
    normalization_funding_mode: str | None = None,
    awarding_office: str | None = None,
    funding_office: str | None = None,
    center: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "amount",
    sort_dir: str = "desc",
) -> dict[str, Any]:
    _ensure_award_tables(db)
    normalized_page = int(page)
    normalized_page_size = int(page_size)
    if normalized_page < 1:
        raise HTTPException(status_code=400, detail="page must be >= 1")
    if normalized_page_size < 1 or normalized_page_size > 200:
        raise HTTPException(status_code=400, detail="page_size must be between 1 and 200")

    sort_column_sql, normalized_sort_dir = _normalize_profile_detail_sort(sort_by, sort_dir)
    cte_sql, params, effective_mode = _build_state_profile_award_rows_sql(
        basis=basis,
        state_code=state,
        funding_geography_mode=funding_geography_mode,
        appropriation_type=appropriation_type,
        assistance_type=assistance_type,
        fiscal_year=fiscal_year,
        awarding_office=awarding_office,
        funding_office=funding_office,
        center=center,
    )

    query_token = str(q or "").strip()
    detail_filters: list[str] = []
    if query_token:
        params["q"] = f"%{query_token.lower()}%"
        detail_filters.append(
            "("
            "LOWER(COALESCE(award_rows.category, '')) LIKE :q "
            "OR LOWER(COALESCE(award_rows.subcategory, '')) LIKE :q "
            "OR LOWER(COALESCE(award_rows.project_title, '')) LIKE :q "
            "OR LOWER(COALESCE(award_rows.grantee_name, '')) LIKE :q "
            "OR LOWER(COALESCE(award_rows.city, '')) LIKE :q "
            "OR LOWER(COALESCE(award_rows.county, '')) LIKE :q "
            "OR LOWER(COALESCE(award_rows.fain, '')) LIKE :q"
            ")"
        )
    where_sql = f"WHERE {' AND '.join(detail_filters)}" if detail_filters else ""
    params["limit"] = normalized_page_size
    params["offset"] = (normalized_page - 1) * normalized_page_size

    rows = db.execute(
        text(
            f"""
            {cte_sql}
            SELECT
                award_rows.record_id,
                award_rows.record_type,
                award_rows.fain,
                award_rows.category,
                award_rows.subcategory,
                award_rows.project_title,
                award_rows.grantee_name,
                award_rows.city,
                award_rows.county,
                award_rows.amount,
                award_rows.min_fiscal_year,
                award_rows.max_fiscal_year,
                award_rows.latest_action_date,
                award_rows.state_name,
                award_rows.state_code,
                award_rows.usaspending_permalink,
                award_rows.lifetime_total_funding_amount
            FROM award_rows
            {where_sql}
            ORDER BY {sort_column_sql} {normalized_sort_dir.upper()} NULLS LAST, award_rows.record_id ASC
            LIMIT :limit
            OFFSET :offset
            """
        ),
        params,
    ).mappings().all()

    total_row = db.execute(
        text(
            f"""
            {cte_sql}
            SELECT COUNT(*)::integer AS total_rows
            FROM award_rows
            {where_sql}
            """
        ),
        params,
    ).mappings().one()
    profile_total_row = db.execute(
        text(
            f"""
            {cte_sql}
            SELECT COALESCE(SUM(award_rows.amount), 0)::numeric AS total_funding
            FROM award_rows
            """
        ),
        {key: value for key, value in params.items() if key not in {"limit", "offset", "q"}},
    ).mappings().one()
    normalization = _build_state_profile_normalization_context(
        db,
        normalize=normalize,
        normalization_funding_mode=normalization_funding_mode,
        state_code=params["state_code"],
        basis=basis,
        funding_geography_mode=effective_mode,
        appropriation_type=appropriation_type,
        assistance_type=assistance_type,
        fiscal_year=fiscal_year,
        awarding_office=awarding_office,
        funding_office=funding_office,
        center=center,
        raw_total_funding=profile_total_row.get("total_funding"),
    )

    serialized_rows = []
    for index, row in enumerate(rows, start=1):
        serialized_rows.append(
            {
                "line_number": params["offset"] + index,
                "record_id": row.get("record_id"),
                "record_type": row.get("record_type"),
                "fain": row.get("fain"),
                "category": row.get("category"),
                "subcategory": row.get("subcategory"),
                "project_title": row.get("project_title"),
                "grantee_name": row.get("grantee_name"),
                "city": row.get("city"),
                "county": row.get("county"),
                "amount": _apply_state_profile_normalized_amount(row.get("amount"), normalization),
                "min_fiscal_year": row.get("min_fiscal_year"),
                "max_fiscal_year": row.get("max_fiscal_year"),
                "latest_action_date": _serialize_value(row.get("latest_action_date")),
                "state_name": row.get("state_name"),
                "state_code": row.get("state_code"),
                "usaspending_permalink": row.get("usaspending_permalink"),
                "lifetime_total_funding_amount": _json_number(row.get("lifetime_total_funding_amount")),
            }
        )

    return {
        "basis": _normalize_basis(basis),
        "state_code": params["state_code"],
        "funding_geography_mode": effective_mode,
        "q": query_token or None,
        "page": normalized_page,
        "page_size": normalized_page_size,
        "sort_by": str(sort_by or "amount").strip().lower(),
        "sort_dir": normalized_sort_dir,
        "total_rows": int(total_row.get("total_rows") or 0),
        **_state_profile_normalization_payload(normalization),
        "rows": serialized_rows,
    }


def search_awards(
    db: Session,
    *,
    q: str | None,
    basis: str,
    funding_geography_mode: str = "recipient_location",
    appropriation_type: str = APPROPRIATION_FILTER_ALL,
    assistance_type: str | None,
    fiscal_year: int | None,
    awarding_office: str | None = None,
    funding_office: str | None = None,
    center: str | None = None,
    state: str | None = None,
    selected_state_code: str | None = None,
    selected_state_name: str | None = None,
    selected_county_fips: str | None = None,
    selected_county_name: str | None = None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    normalized_basis = _normalize_basis(basis, allow_all=True)
    normalized_mode = _normalize_funding_geography_mode(funding_geography_mode)
    normalized_appropriation_type = _normalize_appropriation_type(appropriation_type)
    normalized_state_filter = _normalize_state_code(state)
    normalized_selected_state_code = _normalize_state_code(selected_state_code)
    normalized_selected_state_name = _normalize_name_filter(selected_state_name)
    normalized_selected_county_fips = _normalize_county_fips(selected_county_fips)
    normalized_selected_county_name = _normalize_name_filter(selected_county_name)
    query_token = str(q or "").strip()
    _ensure_award_tables(db)
    scope_table_available = _table_exists(db, AWARD_SCOPE_CLASSIFICATION_TABLE)
    if normalized_mode == "statewide_allocation" and normalized_basis in {"prime", "all"}:
        _ensure_scope_classification_table(db)

    page = int(page)
    page_size = int(page_size)
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be >= 1")
    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="page_size must be between 1 and 100")

    params: dict[str, Any] = {
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }

    prime_filters: list[str] = []
    sub_filters: list[str] = []

    if query_token:
        params["q"] = f"%{query_token}%"
        prime_filters.append("(p.searchable_text ILIKE :q OR p.fain ILIKE :q OR p.recipient_name ILIKE :q)")
        sub_filters.append("(s.searchable_text ILIKE :q OR s.prime_award_fain ILIKE :q OR s.subawardee_name ILIKE :q)")

    assistance_type = _strip_optional(assistance_type)
    if assistance_type:
        params["assistance_type"] = assistance_type
        prime_filters.append("p.assistance_type_description = :assistance_type")

    if fiscal_year is not None:
        params["fiscal_year"] = int(fiscal_year)
        sub_filters.append("s.subaward_action_date_fiscal_year = :fiscal_year")

    prime_tx_scope_filters: list[str] = []
    if fiscal_year is not None:
        prime_tx_scope_filters.append("tx_filter.action_date_fiscal_year = :fiscal_year")
    if normalized_appropriation_type != APPROPRIATION_FILTER_ALL:
        params["appropriation_type"] = normalized_appropriation_type
        prime_tx_scope_filters.append("tx_filter.appropriation_type = :appropriation_type")
        sub_filters.append("s.appropriation_type = :appropriation_type")
    if prime_tx_scope_filters:
        prime_filters.append(
            "EXISTS ("
            f"SELECT 1 FROM {PRIME_TX_TABLE} AS tx_filter "
            "WHERE tx_filter.assistance_award_unique_key = p.unique_key "
            f"AND {' AND '.join(prime_tx_scope_filters)}"
            ")"
        )

    awarding_office = _strip_optional(awarding_office)
    if awarding_office:
        params["awarding_office"] = awarding_office
        prime_filters.append("p.awarding_office_name = :awarding_office")
        sub_filters.append("s.prime_award_awarding_office_name = :awarding_office")

    funding_office = _strip_optional(funding_office)
    if funding_office:
        params["funding_office"] = funding_office
        prime_filters.append("p.funding_office_name = :funding_office")
        sub_filters.append("s.prime_award_funding_office_name = :funding_office")

    center = _strip_optional(center)
    if center:
        params["center"] = center
        prime_filters.append("(p.awarding_sub_agency_name = :center OR p.funding_sub_agency_name = :center)")
        sub_filters.append(
            "(s.prime_award_awarding_sub_agency_name = :center OR s.prime_award_funding_sub_agency_name = :center)"
        )

    if normalized_state_filter:
        params["state_filter_code"] = normalized_state_filter
        prime_filters.append("p.recipient_state_code = :state_filter_code")
        sub_filters.append("s.subawardee_state_code = :state_filter_code")

    # County scope takes precedence over selected state scope.
    if normalized_selected_county_fips:
        params["selected_county_fips"] = normalized_selected_county_fips
        selected_county_state_code = (
            normalized_selected_state_code
            or _state_code_for_county_fips(db, normalized_selected_county_fips)
        )
        if normalized_mode == "statewide_allocation":
            params["selected_county_state_code"] = selected_county_state_code
            prime_filters.append(
                "("
                "p.recipient_county_fips = :selected_county_fips "
                "OR ("
                f"EXISTS (SELECT 1 FROM {AWARD_SCOPE_CLASSIFICATION_TABLE} AS cls "
                "WHERE cls.assistance_award_unique_key = p.unique_key "
                "AND cls.scope_classification = 'statewide' "
                "AND cls.is_allocatable_to_counties = true) "
                "AND :selected_county_state_code IS NOT NULL "
                "AND p.recipient_state_code = :selected_county_state_code"
                ")"
                ")"
            )
        else:
            prime_filters.append("p.recipient_county_fips = :selected_county_fips")
        sub_filters.append("s.subawardee_county_fips = :selected_county_fips")
        if normalized_selected_county_name:
            params["selected_county_name"] = normalized_selected_county_name
            if normalized_mode != "statewide_allocation":
                prime_filters.append("LOWER(TRIM(COALESCE(p.recipient_county_name, ''))) = :selected_county_name")
            sub_filters.append(
                "EXISTS ("
                f"SELECT 1 FROM {COUNTY_DIM_TABLE} AS county "
                "WHERE county.location_id = s.subawardee_county_fips "
                "AND LOWER(TRIM(COALESCE(county.county_name, ''))) = :selected_county_name"
                ")"
            )
    elif normalized_selected_state_code:
        params["selected_state_code"] = normalized_selected_state_code
        prime_filters.append("p.recipient_state_code = :selected_state_code")
        sub_filters.append("s.subawardee_state_code = :selected_state_code")
    elif normalized_selected_state_name:
        params["selected_state_name"] = normalized_selected_state_name
        prime_filters.append("LOWER(TRIM(COALESCE(p.recipient_state_name, ''))) = :selected_state_name")
        sub_filters.append("LOWER(TRIM(COALESCE(s.subawardee_state_name, ''))) = :selected_state_name")
    elif normalized_selected_county_name:
        params["selected_county_name"] = normalized_selected_county_name
        prime_filters.append("LOWER(TRIM(COALESCE(p.recipient_county_name, ''))) = :selected_county_name")
        sub_filters.append(
            "EXISTS ("
            f"SELECT 1 FROM {COUNTY_DIM_TABLE} AS county "
            "WHERE county.location_id = s.subawardee_county_fips "
            "AND LOWER(TRIM(COALESCE(county.county_name, ''))) = :selected_county_name"
            ")"
        )

    prime_where = ""
    if prime_filters:
        prime_where = "WHERE " + " AND ".join(prime_filters)

    sub_where = ""
    if sub_filters:
        sub_where = "WHERE " + " AND ".join(sub_filters)

    prime_scope_join = (
        f"LEFT JOIN {AWARD_SCOPE_CLASSIFICATION_TABLE} AS cls "
        "ON cls.assistance_award_unique_key = p.unique_key"
        if scope_table_available
        else ""
    )
    prime_scope_classification_sql = (
        "cls.scope_classification"
        if scope_table_available
        else "NULL::text"
    )
    prime_scope_allocatable_sql = (
        "COALESCE(cls.is_allocatable_to_counties, false)"
        if scope_table_available
        else "false"
    )

    prime_sql = f"""
        SELECT
            p.unique_key AS record_id,
            'prime_award'::text AS record_type,
            p.fain,
            p.recipient_name AS entity_name,
            p.assistance_type_description,
            p.total_funding_amount AS amount,
            p.award_latest_action_date AS latest_action_date,
            p.recipient_state_code AS state_code,
            p.recipient_state_name AS state_name,
            p.recipient_county_fips AS county_fips,
            p.recipient_county_name AS county_name,
            p.prime_award_base_transaction_description AS description,
            p.usaspending_permalink,
            p.award_latest_action_date_fiscal_year AS fiscal_year,
            p.awarding_sub_agency_name AS center_name,
            p.awarding_office_name AS awarding_office_name,
            p.funding_office_name AS funding_office_name,
            p.appropriation_type,
            p.appropriation_subtype,
            p.disaster_emergency_fund_codes_raw,
            p.appropriation_classification_source,
            {prime_scope_classification_sql} AS scope_classification,
            {prime_scope_allocatable_sql} AS is_allocatable_to_counties
        FROM {PRIME_TABLE} AS p
        {prime_scope_join}
        {prime_where}
    """

    sub_sql = f"""
        SELECT
            s.id::text AS record_id,
            'subaward'::text AS record_type,
            s.prime_award_fain AS fain,
            s.subawardee_name AS entity_name,
            NULL::text AS assistance_type_description,
            s.subaward_amount AS amount,
            s.subaward_action_date AS latest_action_date,
            s.subawardee_state_code AS state_code,
            s.subawardee_state_name AS state_name,
            s.subawardee_county_fips AS county_fips,
            county.county_name AS county_name,
            COALESCE(s.subaward_description, s.prime_award_base_transaction_description) AS description,
            s.usaspending_permalink,
            s.subaward_action_date_fiscal_year AS fiscal_year,
            s.prime_award_awarding_sub_agency_name AS center_name,
            s.prime_award_awarding_office_name AS awarding_office_name,
            s.prime_award_funding_office_name AS funding_office_name,
            s.appropriation_type,
            s.appropriation_subtype,
            s.prime_award_disaster_emergency_fund_codes_raw AS disaster_emergency_fund_codes_raw,
            s.appropriation_classification_source,
            NULL::text AS scope_classification,
            false AS is_allocatable_to_counties
        FROM {SUBAWARD_TABLE} AS s
        LEFT JOIN {COUNTY_DIM_TABLE} AS county
            ON county.location_id = s.subawardee_county_fips
        {sub_where}
    """

    if normalized_basis == "prime":
        combined_sql = prime_sql
    elif normalized_basis == "subaward":
        combined_sql = sub_sql
    else:
        combined_sql = f"{prime_sql} UNION ALL {sub_sql}"

    rows = db.execute(
        text(
            f"""
            SELECT *
            FROM ({combined_sql}) AS combined
            ORDER BY combined.latest_action_date DESC NULLS LAST, combined.amount DESC NULLS LAST
            LIMIT :limit
            OFFSET :offset
            """
        ),
        params,
    ).mappings().all()

    total_count = db.execute(
        text(f"SELECT COUNT(*)::integer AS total_count FROM ({combined_sql}) AS combined"),
        params,
    ).mappings().one()["total_count"]

    results = [
        {
            "record_id": row["record_id"],
            "record_type": row["record_type"],
            "fain": row["fain"],
            "entity_name": row["entity_name"],
            "assistance_type_description": row["assistance_type_description"],
            "amount": _json_number(row["amount"]),
            "latest_action_date": row["latest_action_date"].isoformat() if row["latest_action_date"] else None,
            "state_code": row["state_code"],
            "state_name": row["state_name"],
            "county_fips": row["county_fips"],
            "county_name": row["county_name"],
            "description": row["description"],
            "usaspending_permalink": row["usaspending_permalink"],
            "fiscal_year": row["fiscal_year"],
            "center_name": row["center_name"],
            "awarding_office_name": row["awarding_office_name"],
            "funding_office_name": row["funding_office_name"],
            "appropriation_type": row.get("appropriation_type"),
            "appropriation_subtype": row.get("appropriation_subtype"),
            "raw_emergency_code": row.get("disaster_emergency_fund_codes_raw"),
            "appropriation_classification_source": row.get("appropriation_classification_source"),
            "scope_classification": row.get("scope_classification"),
            "is_allocatable_to_counties": bool(row.get("is_allocatable_to_counties")),
        }
        for row in rows
    ]

    return {
        "basis": normalized_basis,
        "funding_geography_mode": normalized_mode,
        "appropriation_type": normalized_appropriation_type,
        "appropriation_type_label": APPROPRIATION_FILTER_LABELS.get(
            normalized_appropriation_type,
            normalized_appropriation_type,
        ),
        "q": query_token,
        "assistance_type": assistance_type,
        "fiscal_year": int(fiscal_year) if fiscal_year is not None else None,
        "awarding_office": awarding_office,
        "funding_office": funding_office,
        "center": center,
        "state": normalized_state_filter,
        "selected_state_code": normalized_selected_state_code,
        "selected_state_name": normalized_selected_state_name,
        "selected_county_fips": normalized_selected_county_fips,
        "selected_county_name": normalized_selected_county_name,
        "page": page,
        "page_size": page_size,
        "total": int(total_count or 0),
        "results": results,
    }


def fetch_scope_classification_debug(
    db: Session,
    *,
    q: str | None = None,
    scope_classification: str | None = None,
    min_score: int | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    _ensure_award_tables(db)
    _ensure_scope_classification_table(db)

    normalized_scope = _strip_optional(scope_classification)
    if normalized_scope is not None:
        normalized_scope = normalized_scope.lower()
        if normalized_scope not in VALID_SCOPE_CLASSIFICATIONS:
            allowed = ", ".join(sorted(VALID_SCOPE_CLASSIFICATIONS))
            raise HTTPException(status_code=400, detail=f"scope_classification must be one of {allowed}")

    page = int(page)
    page_size = int(page_size)
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be >= 1")
    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="page_size must be between 1 and 100")

    normalized_min_score = int(min_score) if min_score is not None else None
    query_token = str(q or "").strip()

    params: dict[str, Any] = {
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    filters: list[str] = []

    if query_token:
        params["q"] = f"%{query_token}%"
        filters.append(
            "("
            "COALESCE(c.award_id_fain, p.fain, '') ILIKE :q "
            "OR COALESCE(p.recipient_name, '') ILIKE :q "
            "OR COALESCE(p.cfda_program_title, '') ILIKE :q "
            "OR COALESCE(p.prime_award_base_transaction_description, '') ILIKE :q"
            ")"
        )

    if normalized_scope:
        params["scope_classification"] = normalized_scope
        filters.append("c.scope_classification = :scope_classification")

    if normalized_min_score is not None:
        params["min_score"] = normalized_min_score
        filters.append("c.scope_score >= :min_score")

    where_sql = ""
    if filters:
        where_sql = "WHERE " + " AND ".join(filters)

    base_sql = (
        f"FROM {AWARD_SCOPE_CLASSIFICATION_TABLE} AS c "
        f"LEFT JOIN {PRIME_TABLE} AS p ON p.unique_key = c.assistance_award_unique_key "
        f"{where_sql}"
    )

    rows = db.execute(
        text(
            f"""
            SELECT
                c.assistance_award_unique_key,
                COALESCE(c.award_id_fain, p.fain) AS award_id_fain,
                p.recipient_name,
                p.cfda_program_title,
                c.scope_classification,
                c.scope_score,
                c.scope_confidence,
                c.reason_codes,
                c.is_allocatable_to_counties,
                c.allocation_method_default,
                c.classifier_version
            {base_sql}
            ORDER BY
                c.scope_score DESC,
                c.scope_classification ASC,
                COALESCE(c.award_id_fain, p.fain) ASC NULLS LAST
            LIMIT :limit
            OFFSET :offset
            """
        ),
        params,
    ).mappings().all()

    total = db.execute(
        text(f"SELECT COUNT(*)::integer AS total_count {base_sql}"),
        params,
    ).mappings().one()["total_count"]

    result_rows: list[dict[str, Any]] = []
    for row in rows:
        reason_codes = row.get("reason_codes")
        if isinstance(reason_codes, str):
            try:
                parsed_reason_codes = json.loads(reason_codes)
            except json.JSONDecodeError:
                parsed_reason_codes = [reason_codes]
        elif isinstance(reason_codes, list):
            parsed_reason_codes = reason_codes
        else:
            parsed_reason_codes = []

        result_rows.append(
            {
                "assistance_award_unique_key": row.get("assistance_award_unique_key"),
                "award_id_fain": row.get("award_id_fain"),
                "recipient_name": row.get("recipient_name"),
                "program_title": row.get("cfda_program_title"),
                "scope_classification": row.get("scope_classification"),
                "scope_score": int(row.get("scope_score") or 0),
                "scope_confidence": row.get("scope_confidence"),
                "reason_codes": parsed_reason_codes,
                "is_allocatable_to_counties": bool(row.get("is_allocatable_to_counties")),
                "allocation_method_default": row.get("allocation_method_default"),
                "classifier_version": row.get("classifier_version"),
            }
        )

    return {
        "q": query_token or None,
        "scope_classification": normalized_scope,
        "min_score": normalized_min_score,
        "page": page,
        "page_size": page_size,
        "total": int(total or 0),
        "results": result_rows,
    }


def fetch_appropriation_classification_debug(
    db: Session,
    *,
    q: str | None = None,
    record_type: str | None = None,
    appropriation_type: str = APPROPRIATION_FILTER_ALL,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    _ensure_award_tables(db)
    _ensure_appropriation_classification_table(db)

    normalized_record_type = _strip_optional(record_type)
    if normalized_record_type:
        normalized_record_type = normalized_record_type.lower()
    valid_record_types = {"prime_transaction", "subaward", "prime_award"}
    if normalized_record_type and normalized_record_type not in valid_record_types:
        allowed = ", ".join(sorted(valid_record_types))
        raise HTTPException(status_code=400, detail=f"record_type must be one of {allowed}")

    normalized_appropriation_type = _normalize_appropriation_type(appropriation_type)
    query_token = str(q or "").strip()

    page = int(page)
    page_size = int(page_size)
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be >= 1")
    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="page_size must be between 1 and 100")

    params: dict[str, Any] = {
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    filters: list[str] = []
    if normalized_record_type:
        params["record_type"] = normalized_record_type
        filters.append("ac.record_type = :record_type")
    if normalized_appropriation_type != APPROPRIATION_FILTER_ALL:
        params["appropriation_type"] = normalized_appropriation_type
        filters.append("ac.appropriation_type = :appropriation_type")
    if query_token:
        params["q"] = f"%{query_token}%"
        filters.append(
            "("
            "COALESCE(ac.award_id_fain, '') ILIKE :q "
            "OR COALESCE(pt.recipient_name, p.recipient_name, s.subawardee_name, '') ILIKE :q "
            "OR COALESCE(ac.raw_emergency_code, '') ILIKE :q"
            ")"
        )

    where_sql = ""
    if filters:
        where_sql = "WHERE " + " AND ".join(filters)

    joined_sql = f"""
        FROM {APPROPRIATION_CLASSIFICATION_TABLE} AS ac
        LEFT JOIN {PRIME_TX_TABLE} AS pt
            ON ac.record_type = 'prime_transaction'
           AND ac.record_id = pt.assistance_transaction_unique_key
        LEFT JOIN {SUBAWARD_TABLE} AS s
            ON ac.record_type = 'subaward'
           AND ac.record_id = s.id::text
        LEFT JOIN {PRIME_TABLE} AS p
            ON ac.record_type = 'prime_award'
           AND ac.record_id = p.unique_key
        {where_sql}
    """

    rows = db.execute(
        text(
            f"""
            SELECT
                ac.record_type,
                ac.record_id,
                ac.assistance_award_unique_key,
                ac.award_id_fain,
                COALESCE(pt.recipient_name, p.recipient_name, s.subawardee_name) AS recipient_name,
                COALESCE(
                    pt.action_date_fiscal_year,
                    p.award_latest_action_date_fiscal_year,
                    s.subaward_action_date_fiscal_year
                ) AS fiscal_year,
                ac.raw_emergency_code,
                ac.appropriation_type,
                ac.appropriation_subtype,
                ac.appropriation_reason_code,
                ac.classification_source,
                ac.classifier_version
            {joined_sql}
            ORDER BY
                COALESCE(
                    pt.action_date_fiscal_year,
                    p.award_latest_action_date_fiscal_year,
                    s.subaward_action_date_fiscal_year
                ) DESC NULLS LAST,
                ac.record_type ASC,
                ac.record_id ASC
            LIMIT :limit
            OFFSET :offset
            """
        ),
        params,
    ).mappings().all()

    total = db.execute(
        text(f"SELECT COUNT(*)::integer AS total_count {joined_sql}"),
        params,
    ).mappings().one()["total_count"]

    code_counts = db.execute(
        text(
            f"""
            SELECT
                COALESCE(ac.raw_emergency_code, '') AS raw_emergency_code,
                ac.appropriation_type,
                COUNT(*)::integer AS record_count
            {joined_sql}
            GROUP BY
                COALESCE(ac.raw_emergency_code, ''),
                ac.appropriation_type
            ORDER BY COUNT(*) DESC, COALESCE(ac.raw_emergency_code, '') ASC
            LIMIT 200
            """
        ),
        params,
    ).mappings().all()

    type_counts = db.execute(
        text(
            f"""
            SELECT
                ac.appropriation_type,
                COUNT(*)::integer AS record_count
            {joined_sql}
            GROUP BY ac.appropriation_type
            ORDER BY COUNT(*) DESC, ac.appropriation_type ASC
            """
        ),
        params,
    ).mappings().all()

    return {
        "q": query_token or None,
        "record_type": normalized_record_type,
        "appropriation_type": normalized_appropriation_type,
        "appropriation_type_label": APPROPRIATION_FILTER_LABELS.get(
            normalized_appropriation_type,
            normalized_appropriation_type,
        ),
        "page": page,
        "page_size": page_size,
        "total": int(total or 0),
        "results": [
            {
                "record_type": row.get("record_type"),
                "record_id": row.get("record_id"),
                "assistance_award_unique_key": row.get("assistance_award_unique_key"),
                "award_id_fain": row.get("award_id_fain"),
                "recipient_name": row.get("recipient_name"),
                "fiscal_year": row.get("fiscal_year"),
                "raw_emergency_code": row.get("raw_emergency_code"),
                "appropriation_type": row.get("appropriation_type"),
                "appropriation_subtype": row.get("appropriation_subtype"),
                "appropriation_reason_code": row.get("appropriation_reason_code"),
                "classification_source": row.get("classification_source"),
                "classifier_version": row.get("classifier_version"),
            }
            for row in rows
        ],
        "counts_by_raw_code": [
            {
                "raw_emergency_code": row.get("raw_emergency_code") or None,
                "appropriation_type": row.get("appropriation_type"),
                "record_count": int(row.get("record_count") or 0),
            }
            for row in code_counts
        ],
        "counts_by_appropriation_type": [
            {
                "appropriation_type": row.get("appropriation_type"),
                "record_count": int(row.get("record_count") or 0),
            }
            for row in type_counts
        ],
    }


def fetch_allocation_debug(
    db: Session,
    *,
    assistance_award_unique_key: str | None = None,
    award_id_fain: str | None = None,
    fiscal_year: int | None = None,
    limit_counties: int = 10,
) -> dict[str, Any]:
    _ensure_award_tables(db)
    _ensure_scope_classification_table(db)

    unique_key = _strip_optional(assistance_award_unique_key)
    fain = _strip_optional(award_id_fain)
    if bool(unique_key) == bool(fain):
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of assistance_award_unique_key or award_id_fain",
        )

    award_row = db.execute(
        text(
            f"""
            SELECT
                p.unique_key,
                p.fain,
                p.recipient_name,
                p.recipient_state_code,
                p.recipient_state_name,
                c.scope_classification,
                c.scope_score,
                c.scope_confidence,
                c.reason_codes,
                c.is_allocatable_to_counties,
                c.classifier_version
            FROM {PRIME_TABLE} AS p
            LEFT JOIN {AWARD_SCOPE_CLASSIFICATION_TABLE} AS c
                ON c.assistance_award_unique_key = p.unique_key
            WHERE {"p.unique_key = :value" if unique_key else "p.fain = :value"}
            LIMIT 1
            """
        ),
        {"value": unique_key or fain},
    ).mappings().one_or_none()
    if award_row is None:
        return {
            "found": False,
            "assistance_award_unique_key": unique_key,
            "award_id_fain": fain,
            "message": "Award not found.",
        }

    effective_fiscal_year = int(fiscal_year) if fiscal_year is not None else _latest_prime_transaction_fiscal_year(db)
    fy_totals = {
        "fy_obligated_amount": 0.0,
        "fy_outlayed_amount_estimated": 0.0,
    }
    if effective_fiscal_year is not None:
        totals_row = db.execute(
            text(
                f"""
                WITH tx_ordered AS (
                    SELECT
                        tx.*,
                        LAG(tx.total_outlayed_amount_for_overall_award) OVER (
                            PARTITION BY COALESCE(
                                tx.assistance_award_unique_key,
                                tx.assistance_transaction_unique_key
                            )
                            ORDER BY
                                tx.action_date NULLS FIRST,
                                COALESCE(tx.modification_number, ''),
                                tx.assistance_transaction_unique_key
                        ) AS prior_total_outlayed_amount_for_overall_award
                    FROM {PRIME_TX_TABLE} AS tx
                    WHERE tx.assistance_award_unique_key = :unique_key
                )
                SELECT
                    COALESCE(SUM(tx_ordered.federal_action_obligation), 0) AS fy_obligated_amount,
                    COALESCE(
                        SUM(
                            CASE
                                WHEN tx_ordered.total_outlayed_amount_for_overall_award IS NULL THEN NULL
                                WHEN tx_ordered.prior_total_outlayed_amount_for_overall_award IS NULL
                                    THEN tx_ordered.total_outlayed_amount_for_overall_award
                                ELSE tx_ordered.total_outlayed_amount_for_overall_award
                                    - tx_ordered.prior_total_outlayed_amount_for_overall_award
                            END
                        ),
                        0
                    ) AS fy_outlayed_amount_estimated
                FROM tx_ordered
                WHERE tx_ordered.action_date_fiscal_year = :fiscal_year
                """
            ),
            {
                "unique_key": award_row["unique_key"],
                "fiscal_year": int(effective_fiscal_year),
            },
        ).mappings().one()
        fy_totals = {
            "fy_obligated_amount": float(totals_row.get("fy_obligated_amount") or 0),
            "fy_outlayed_amount_estimated": float(totals_row.get("fy_outlayed_amount_estimated") or 0),
        }

    limit_counties = max(1, min(int(limit_counties), 200))
    county_shares: list[dict[str, Any]] = []
    allocation_sum_obligated = 0.0
    allocation_sum_outlayed = 0.0
    if (
        award_row.get("is_allocatable_to_counties")
        and award_row.get("scope_classification") == "statewide"
        and award_row.get("recipient_state_code")
    ):
        county_rows = db.execute(
            text(
                f"""
                WITH state_totals AS (
                    SELECT
                        state_abbr,
                        SUM(total_population)::numeric AS state_population
                    FROM {COUNTY_DIM_TABLE}
                    WHERE location_id ~ '^[0-9]{{5}}$'
                      AND total_population IS NOT NULL
                      AND total_population > 0
                    GROUP BY state_abbr
                )
                SELECT
                    county.location_id AS county_fips,
                    county.county_name,
                    county.state_abbr AS state_code,
                    county.total_population::numeric AS county_population,
                    state_totals.state_population,
                    county.total_population::numeric / NULLIF(state_totals.state_population, 0)
                        AS population_weight
                FROM {COUNTY_DIM_TABLE} AS county
                JOIN state_totals
                    ON state_totals.state_abbr = county.state_abbr
                WHERE county.state_abbr = :state_code
                  AND county.location_id ~ '^[0-9]{{5}}$'
                  AND county.total_population IS NOT NULL
                  AND county.total_population > 0
                ORDER BY population_weight DESC NULLS LAST, county.location_id
                LIMIT :limit_counties
                """
            ),
            {
                "state_code": award_row["recipient_state_code"],
                "limit_counties": limit_counties,
            },
        ).mappings().all()
        for row in county_rows:
            weight = float(row.get("population_weight") or 0)
            obligated_share = fy_totals["fy_obligated_amount"] * weight
            outlayed_share = fy_totals["fy_outlayed_amount_estimated"] * weight
            allocation_sum_obligated += obligated_share
            allocation_sum_outlayed += outlayed_share
            county_shares.append(
                {
                    "county_fips": row.get("county_fips"),
                    "county_name": row.get("county_name"),
                    "state_code": row.get("state_code"),
                    "population_weight": _json_number(weight),
                    "estimated_fy_obligated_share": _json_number(obligated_share),
                    "estimated_fy_outlayed_share": _json_number(outlayed_share),
                }
            )

    return {
        "found": True,
        "assistance_award_unique_key": award_row.get("unique_key"),
        "award_id_fain": award_row.get("fain"),
        "recipient_name": award_row.get("recipient_name"),
        "home_state_code": award_row.get("recipient_state_code"),
        "home_state_name": award_row.get("recipient_state_name"),
        "scope_classification": award_row.get("scope_classification") or "unknown",
        "scope_score": int(award_row.get("scope_score") or 0),
        "scope_confidence": award_row.get("scope_confidence") or "low",
        "reason_codes": award_row.get("reason_codes") or [],
        "is_allocatable_to_counties": bool(award_row.get("is_allocatable_to_counties")),
        "classifier_version": award_row.get("classifier_version"),
        "allocation_mode": "statewide_allocation",
        "fiscal_year": effective_fiscal_year,
        "source_fy_obligated_amount": _json_number(fy_totals["fy_obligated_amount"]),
        "source_fy_outlayed_amount_estimated": _json_number(fy_totals["fy_outlayed_amount_estimated"]),
        "top_county_shares": county_shares,
        "top_county_shares_sum_fy_obligated": _json_number(allocation_sum_obligated),
        "top_county_shares_sum_fy_outlayed": _json_number(allocation_sum_outlayed),
    }


def fetch_detail(
    db: Session,
    *,
    prime_unique_key: str | None = None,
    subaward_id: int | None = None,
    fiscal_year: int | None = None,
    funding_geography_mode: str = "recipient_location",
    appropriation_type: str = APPROPRIATION_FILTER_ALL,
    selected_county_fips: str | None = None,
) -> dict[str, Any] | None:
    normalized_mode = _normalize_funding_geography_mode(funding_geography_mode)
    normalized_appropriation_type = _normalize_appropriation_type(appropriation_type)
    normalized_selected_county_fips = _normalize_county_fips(selected_county_fips)
    _ensure_award_tables(db)
    if bool(prime_unique_key) == bool(subaward_id):
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of prime_unique_key or subaward_id",
        )

    if prime_unique_key:
        unique_key = str(prime_unique_key).strip()
        row = db.execute(
            text(f"SELECT * FROM {PRIME_TABLE} WHERE unique_key = :unique_key"),
            {"unique_key": unique_key},
        ).mappings().one_or_none()
        if row is None:
            return None
        payload = {key: _serialize_value(value) for key, value in row.items()}
        payload["record_type"] = "prime_award"
        payload["funding_geography_mode"] = normalized_mode
        payload["selected_appropriation_type_filter"] = normalized_appropriation_type
        classification_row = None
        if _table_exists(db, AWARD_SCOPE_CLASSIFICATION_TABLE):
            classification_row = db.execute(
                text(
                    f"""
                    SELECT
                        scope_classification,
                        scope_score,
                        scope_confidence,
                        reason_codes,
                        is_allocatable_to_counties,
                        allocation_method_default,
                        classifier_version
                    FROM {AWARD_SCOPE_CLASSIFICATION_TABLE}
                    WHERE assistance_award_unique_key = :unique_key
                    """
                ),
                {"unique_key": unique_key},
            ).mappings().one_or_none()
        if classification_row:
            payload["scope_classification"] = classification_row.get("scope_classification")
            payload["scope_score"] = int(classification_row.get("scope_score") or 0)
            payload["scope_confidence"] = classification_row.get("scope_confidence")
            payload["reason_codes"] = classification_row.get("reason_codes") or []
            payload["is_allocatable_to_counties"] = bool(
                classification_row.get("is_allocatable_to_counties")
            )
            payload["allocation_method_default"] = classification_row.get("allocation_method_default")
            payload["classifier_version"] = classification_row.get("classifier_version")
        else:
            payload["scope_classification"] = "unknown"
            payload["scope_score"] = 0
            payload["scope_confidence"] = "low"
            payload["reason_codes"] = []
            payload["is_allocatable_to_counties"] = False
            payload["allocation_method_default"] = None
            payload["classifier_version"] = None

        payload["raw_emergency_code"] = payload.get("disaster_emergency_fund_codes_raw")
        mix_rows = db.execute(
            text(
                f"""
                SELECT
                    COALESCE(tx.appropriation_type, :unknown_type) AS appropriation_type,
                    COUNT(*)::integer AS transaction_count
                FROM {PRIME_TX_TABLE} AS tx
                WHERE tx.assistance_award_unique_key = :unique_key
                GROUP BY COALESCE(tx.appropriation_type, :unknown_type)
                ORDER BY COALESCE(tx.appropriation_type, :unknown_type)
                """
            ),
            {"unique_key": unique_key, "unknown_type": APPROPRIATION_TYPE_UNKNOWN},
        ).mappings().all()
        payload["award_appropriation_mix"] = [
            {
                "appropriation_type": row.get("appropriation_type"),
                "transaction_count": int(row.get("transaction_count") or 0),
            }
            for row in mix_rows
        ]
        cross_year_params: dict[str, Any] = {"unique_key": unique_key}
        cross_year_where_sql = "tx_ordered.action_date_fiscal_year IS NOT NULL"
        if normalized_appropriation_type != APPROPRIATION_FILTER_ALL:
            cross_year_params["appropriation_type"] = normalized_appropriation_type
            cross_year_where_sql += " AND tx_ordered.appropriation_type = :appropriation_type"
        cross_year_rows = db.execute(
            text(
                f"""
                WITH tx_ordered AS (
                    SELECT
                        tx.*,
                        LAG(tx.total_outlayed_amount_for_overall_award) OVER (
                            PARTITION BY COALESCE(
                                tx.assistance_award_unique_key,
                                tx.assistance_transaction_unique_key
                            )
                            ORDER BY
                                tx.action_date NULLS FIRST,
                                COALESCE(tx.modification_number, ''),
                                tx.assistance_transaction_unique_key
                        ) AS prior_total_outlayed_amount_for_overall_award
                    FROM {PRIME_TX_TABLE} AS tx
                    WHERE tx.assistance_award_unique_key = :unique_key
                )
                SELECT
                    tx_ordered.action_date_fiscal_year AS fiscal_year,
                    COALESCE(SUM(tx_ordered.federal_action_obligation), 0) AS fy_obligated_amount,
                    COALESCE(
                        SUM(
                            CASE
                                WHEN tx_ordered.total_outlayed_amount_for_overall_award IS NULL THEN NULL
                                WHEN tx_ordered.prior_total_outlayed_amount_for_overall_award IS NULL
                                    THEN tx_ordered.total_outlayed_amount_for_overall_award
                                ELSE tx_ordered.total_outlayed_amount_for_overall_award
                                    - tx_ordered.prior_total_outlayed_amount_for_overall_award
                            END
                        ),
                        0
                    ) AS fy_outlayed_amount_estimated,
                    COUNT(*)::integer AS transaction_count,
                    COUNT(DISTINCT tx_ordered.assistance_award_unique_key)::integer AS distinct_award_count
                FROM tx_ordered
                WHERE {cross_year_where_sql}
                GROUP BY tx_ordered.action_date_fiscal_year
                ORDER BY tx_ordered.action_date_fiscal_year DESC
                """
            ),
            cross_year_params,
        ).mappings().all()
        payload["fiscal_year_transaction_summaries"] = [
            {
                "fiscal_year": int(row.get("fiscal_year") or 0),
                "fy_obligated_amount": _json_number(row.get("fy_obligated_amount")),
                "fy_outlayed_amount_estimated": _json_number(row.get("fy_outlayed_amount_estimated")),
                "transaction_count": int(row.get("transaction_count") or 0),
                "distinct_award_count": int(row.get("distinct_award_count") or 0),
            }
            for row in cross_year_rows
            if row.get("fiscal_year") is not None
        ]
        payload["available_fiscal_years"] = [
            item["fiscal_year"] for item in payload["fiscal_year_transaction_summaries"]
        ]
        effective_fiscal_year = fiscal_year
        if effective_fiscal_year is None:
            effective_fiscal_year = _latest_prime_transaction_fiscal_year(db)
        if effective_fiscal_year is not None:
            params = {
                "unique_key": unique_key,
                "fiscal_year": int(effective_fiscal_year),
            }
            fy_tx_where_sql = "tx_ordered.action_date_fiscal_year = :fiscal_year"
            if normalized_appropriation_type != APPROPRIATION_FILTER_ALL:
                params["appropriation_type"] = normalized_appropriation_type
                fy_tx_where_sql += " AND tx_ordered.appropriation_type = :appropriation_type"
            fy_summary = db.execute(
                text(
                    f"""
                    WITH tx_ordered AS (
                        SELECT
                            tx.*,
                            LAG(tx.total_outlayed_amount_for_overall_award) OVER (
                                PARTITION BY COALESCE(
                                    tx.assistance_award_unique_key,
                                    tx.assistance_transaction_unique_key
                                )
                                ORDER BY
                                    tx.action_date NULLS FIRST,
                                    COALESCE(tx.modification_number, ''),
                                    tx.assistance_transaction_unique_key
                            ) AS prior_total_outlayed_amount_for_overall_award
                        FROM {PRIME_TX_TABLE} AS tx
                        WHERE tx.assistance_award_unique_key = :unique_key
                    ),
                    tx_year AS (
                        SELECT
                            tx_ordered.assistance_award_unique_key,
                            tx_ordered.federal_action_obligation,
                            CASE
                                WHEN tx_ordered.total_outlayed_amount_for_overall_award IS NULL THEN NULL
                                WHEN tx_ordered.prior_total_outlayed_amount_for_overall_award IS NULL
                                    THEN tx_ordered.total_outlayed_amount_for_overall_award
                                ELSE tx_ordered.total_outlayed_amount_for_overall_award
                                    - tx_ordered.prior_total_outlayed_amount_for_overall_award
                            END AS estimated_outlay_delta
                        FROM tx_ordered
                        WHERE {fy_tx_where_sql}
                    )
                    SELECT
                        COALESCE(SUM(tx_year.federal_action_obligation), 0) AS fy_obligated_amount,
                        COALESCE(SUM(tx_year.estimated_outlay_delta), 0) AS fy_outlayed_amount_estimated,
                        COUNT(*)::integer AS transaction_count,
                        COUNT(DISTINCT tx_year.assistance_award_unique_key)::integer AS distinct_award_count
                    FROM tx_year
                    """
                ),
                params,
            ).mappings().one()

            fy_transactions = db.execute(
                text(
                    f"""
                    WITH tx_ordered AS (
                        SELECT
                            tx.*,
                            LAG(tx.total_outlayed_amount_for_overall_award) OVER (
                                PARTITION BY COALESCE(
                                    tx.assistance_award_unique_key,
                                    tx.assistance_transaction_unique_key
                                )
                                ORDER BY
                                    tx.action_date NULLS FIRST,
                                    COALESCE(tx.modification_number, ''),
                                    tx.assistance_transaction_unique_key
                            ) AS prior_total_outlayed_amount_for_overall_award
                        FROM {PRIME_TX_TABLE} AS tx
                        WHERE tx.assistance_award_unique_key = :unique_key
                    )
                    SELECT
                        tx_ordered.assistance_transaction_unique_key,
                        tx_ordered.modification_number,
                        tx_ordered.action_date,
                        tx_ordered.action_date_fiscal_year,
                        tx_ordered.federal_action_obligation,
                        tx_ordered.total_outlayed_amount_for_overall_award,
                        CASE
                            WHEN tx_ordered.total_outlayed_amount_for_overall_award IS NULL THEN NULL
                            WHEN tx_ordered.prior_total_outlayed_amount_for_overall_award IS NULL
                                THEN tx_ordered.total_outlayed_amount_for_overall_award
                            ELSE tx_ordered.total_outlayed_amount_for_overall_award
                                - tx_ordered.prior_total_outlayed_amount_for_overall_award
                        END AS estimated_outlay_delta,
                        tx_ordered.transaction_description,
                        tx_ordered.awarding_office_name,
                        tx_ordered.funding_office_name,
                        tx_ordered.recipient_state_code,
                        tx_ordered.prime_award_transaction_recipient_county_fips_code,
                        tx_ordered.appropriation_type,
                        tx_ordered.appropriation_subtype,
                        tx_ordered.appropriation_reason_code,
                        tx_ordered.disaster_emergency_fund_codes_raw,
                        tx_ordered.appropriation_classification_source,
                        tx_ordered.usaspending_permalink
                    FROM tx_ordered
                    WHERE {fy_tx_where_sql}
                    ORDER BY
                        tx_ordered.action_date DESC NULLS LAST,
                        COALESCE(tx_ordered.modification_number, '') DESC,
                        tx_ordered.assistance_transaction_unique_key DESC
                    """
                ),
                params,
            ).mappings().all()

            payload["selected_fiscal_year"] = int(effective_fiscal_year)
            payload["fy_transaction_summary"] = {
                "fy_obligated_amount": _json_number(fy_summary.get("fy_obligated_amount")),
                "fy_outlayed_amount_estimated": _json_number(
                    fy_summary.get("fy_outlayed_amount_estimated")
                ),
                "transaction_count": int(fy_summary.get("transaction_count") or 0),
                "distinct_award_count": int(fy_summary.get("distinct_award_count") or 0),
            }
            payload["fy_transactions"] = [
                {key: _serialize_value(value) for key, value in tx_row.items()}
                for tx_row in fy_transactions
            ]
            if normalized_appropriation_type != APPROPRIATION_FILTER_ALL:
                payload["fy_transaction_filter_note"] = (
                    "Fiscal-year transaction values are filtered by the selected appropriation type. "
                    "Lifetime award totals are unfiltered."
                )
            if (
                normalized_mode == "statewide_allocation"
                and normalized_selected_county_fips
                and payload.get("scope_classification") == "statewide"
                and payload.get("is_allocatable_to_counties")
            ):
                county_weight = _county_population_weight(db, normalized_selected_county_fips)
                if county_weight is not None:
                    weight_value = float(county_weight.get("population_weight") or 0)
                    fy_obligated = float(fy_summary.get("fy_obligated_amount") or 0)
                    fy_outlayed = float(fy_summary.get("fy_outlayed_amount_estimated") or 0)
                    payload["allocation"] = {
                        "mode": normalized_mode,
                        "selected_county_fips": normalized_selected_county_fips,
                        "selected_county_name": county_weight.get("county_name"),
                        "selected_state_code": county_weight.get("state_code"),
                        "population_weight": _json_number(weight_value),
                        "estimated_county_share_fy_obligated_amount": _json_number(
                            fy_obligated * weight_value
                        ),
                        "estimated_county_share_fy_outlayed_amount": _json_number(
                            fy_outlayed * weight_value
                        ),
                        "award_fy_obligated_amount_total": _json_number(fy_obligated),
                        "award_fy_outlayed_amount_total": _json_number(fy_outlayed),
                    }
        return payload

    subaward_params: dict[str, Any] = {"subaward_id": int(subaward_id)}
    subaward_where_sql = "id = :subaward_id"
    if normalized_appropriation_type != APPROPRIATION_FILTER_ALL:
        subaward_params["appropriation_type"] = normalized_appropriation_type
        subaward_where_sql += " AND appropriation_type = :appropriation_type"

    row = db.execute(
        text(f"SELECT * FROM {SUBAWARD_TABLE} WHERE {subaward_where_sql}"),
        subaward_params,
    ).mappings().one_or_none()
    if row is None:
        return None
    payload = {key: _serialize_value(value) for key, value in row.items()}
    payload["record_type"] = "subaward"
    payload["funding_geography_mode"] = "recipient_location"
    payload["selected_appropriation_type_filter"] = normalized_appropriation_type
    payload["raw_emergency_code"] = payload.get("prime_award_disaster_emergency_fund_codes_raw")
    return payload


def fetch_trend(
    db: Session,
    *,
    basis: str,
    geography: str,
    geography_id: str,
    metric: str,
    funding_geography_mode: str = "recipient_location",
    appropriation_type: str = APPROPRIATION_FILTER_ALL,
    assistance_type: str | None = None,
    awarding_office: str | None = None,
    funding_office: str | None = None,
    center: str | None = None,
    state: str | None = None,
    start_fy: int | None = None,
    end_fy: int | None = None,
) -> dict[str, Any]:
    normalized_basis = _normalize_basis(basis)
    normalized_geography = _normalize_geography(geography)
    normalized_mode = _normalize_funding_geography_mode(funding_geography_mode)
    normalized_appropriation_type = _normalize_appropriation_type(appropriation_type)
    normalized_metric = _normalize_metric(metric, basis=normalized_basis)
    normalized_geography_id = _normalize_required_geography_id(
        geography=normalized_geography,
        geography_id=geography_id,
    )
    normalized_start_fy = _normalize_optional_fiscal_year(start_fy, field_name="start_fy")
    normalized_end_fy = _normalize_optional_fiscal_year(end_fy, field_name="end_fy")
    normalized_assistance_type = _strip_optional(assistance_type)
    normalized_awarding_office = _strip_optional(awarding_office)
    normalized_funding_office = _strip_optional(funding_office)
    normalized_center = _strip_optional(center)

    _ensure_required_tables(
        db,
        basis=normalized_basis,
        geography=normalized_geography,
        funding_geography_mode=normalized_mode,
    )

    effective_mode = (
        normalized_mode
        if normalized_basis == "prime"
        else "recipient_location"
    )
    summary_table = _summary_table(
        basis=normalized_basis,
        geography=normalized_geography,
        funding_geography_mode=effective_mode,
    )
    metric_column = _metric_column(normalized_basis, normalized_metric)

    available_min_fy, available_max_fy = _summary_year_bounds(db, table_name=summary_table)
    resolved_start_fy, resolved_end_fy = _resolve_trend_year_range(
        available_min_fy=available_min_fy,
        available_max_fy=available_max_fy,
        start_fy=normalized_start_fy,
        end_fy=normalized_end_fy,
    )

    filter_sql, filter_params = _summary_filters_sql(
        basis=normalized_basis,
        geography=normalized_geography,
        appropriation_type=normalized_appropriation_type,
        assistance_type=normalized_assistance_type,
        fiscal_year=None,
        awarding_office=normalized_awarding_office,
        funding_office=normalized_funding_office,
        center=normalized_center,
        state=state,
    )
    params: dict[str, Any] = {
        **filter_params,
        "geography_id": normalized_geography_id,
        "start_fy": resolved_start_fy,
        "end_fy": resolved_end_fy,
    }

    if normalized_basis == "prime":
        rows = db.execute(
            text(
                f"""
                WITH years AS (
                    SELECT generate_series(
                        CAST(:start_fy AS integer),
                        CAST(:end_fy AS integer)
                    )::integer AS fiscal_year
                ),
                aggregated AS (
                    SELECT
                        s.fiscal_year,
                        SUM(s.{metric_column})::numeric AS metric_value,
                        SUM(s.transaction_count)::numeric AS transaction_count,
                        SUM(s.distinct_award_count)::numeric AS distinct_award_count,
                        COUNT(*)::integer AS matched_rows
                    FROM {summary_table} AS s
                    WHERE s.geography_id = :geography_id
                      AND s.fiscal_year BETWEEN :start_fy AND :end_fy
                      {filter_sql}
                    GROUP BY s.fiscal_year
                )
                SELECT
                    years.fiscal_year,
                    COALESCE(aggregated.metric_value, 0)::numeric AS value,
                    COALESCE(aggregated.transaction_count, 0)::numeric AS transaction_count,
                    COALESCE(aggregated.distinct_award_count, 0)::numeric AS distinct_award_count,
                    COALESCE(aggregated.matched_rows, 0)::integer AS matched_rows
                FROM years
                LEFT JOIN aggregated
                    ON aggregated.fiscal_year = years.fiscal_year
                ORDER BY years.fiscal_year
                """
            ),
            params,
        ).mappings().all()
    else:
        rows = db.execute(
            text(
                f"""
                WITH years AS (
                    SELECT generate_series(
                        CAST(:start_fy AS integer),
                        CAST(:end_fy AS integer)
                    )::integer AS fiscal_year
                ),
                aggregated AS (
                    SELECT
                        s.fiscal_year,
                        SUM(s.{metric_column})::numeric AS metric_value,
                        SUM(s.subaward_count)::numeric AS subaward_count,
                        SUM(s.award_count)::numeric AS distinct_award_count,
                        COUNT(*)::integer AS matched_rows
                    FROM {summary_table} AS s
                    WHERE s.geography_id = :geography_id
                      AND s.fiscal_year BETWEEN :start_fy AND :end_fy
                      {filter_sql}
                    GROUP BY s.fiscal_year
                )
                SELECT
                    years.fiscal_year,
                    COALESCE(aggregated.metric_value, 0)::numeric AS value,
                    COALESCE(aggregated.subaward_count, 0)::numeric AS subaward_count,
                    COALESCE(aggregated.distinct_award_count, 0)::numeric AS distinct_award_count,
                    COALESCE(aggregated.matched_rows, 0)::integer AS matched_rows
                FROM years
                LEFT JOIN aggregated
                    ON aggregated.fiscal_year = years.fiscal_year
                ORDER BY years.fiscal_year
                """
            ),
            params,
        ).mappings().all()

    has_data = any(int(row.get("matched_rows") or 0) > 0 for row in rows)
    series: list[dict[str, Any]] = []
    for row in rows:
        entry: dict[str, Any] = {
            "fiscal_year": int(row.get("fiscal_year")),
            "value": _json_number(row.get("value")),
            "matched_row_count": int(row.get("matched_rows") or 0),
        }
        if normalized_basis == "prime":
            entry["transaction_count"] = int(round(float(row.get("transaction_count") or 0)))
            entry["distinct_award_count"] = int(round(float(row.get("distinct_award_count") or 0)))
        else:
            entry["subaward_count"] = int(round(float(row.get("subaward_count") or 0)))
            entry["distinct_award_count"] = int(round(float(row.get("distinct_award_count") or 0)))
        series.append(entry)

    geography_meta = _resolve_trend_geography_metadata(
        db,
        geography=normalized_geography,
        geography_id=normalized_geography_id,
    )
    note = (
        "Trend reflects the selected geography and active CDC funding filters across fiscal years. "
        f"Current in-progress fiscal year (FY{_current_federal_fiscal_year()}) is excluded."
    )
    if normalized_appropriation_type == APPROPRIATION_TYPE_COVID_EMERGENCY:
        note = (
            f"{note} COVID / emergency supplemental funding is identified using official emergency funding codes."
        )

    return {
        "basis": normalized_basis,
        "metric": normalized_metric,
        "metric_label": METRIC_LABELS.get(normalized_metric, normalized_metric),
        "geography_type": normalized_geography,
        "geography_id": geography_meta.get("geography_id") or normalized_geography_id,
        "geography_name": geography_meta.get("geography_name") or normalized_geography_id,
        "state_code": geography_meta.get("state_code"),
        "state_name": geography_meta.get("state_name"),
        "county_name": geography_meta.get("county_name"),
        "funding_geography_mode": effective_mode,
        "appropriation_type": normalized_appropriation_type,
        "appropriation_type_label": APPROPRIATION_FILTER_LABELS.get(
            normalized_appropriation_type,
            normalized_appropriation_type,
        ),
        "assistance_type": normalized_assistance_type,
        "awarding_office": normalized_awarding_office,
        "funding_office": normalized_funding_office,
        "center": normalized_center,
        "state_filter": _normalize_state_code(state),
        "start_fiscal_year": resolved_start_fy,
        "end_fiscal_year": resolved_end_fy,
        "has_data": has_data,
        "subtype_breakdown": None,
        "series": series,
        "note": note,
    }


def fetch_top_awards(
    db: Session,
    *,
    basis: str,
    geography: str,
    funding_geography_mode: str = "recipient_location",
    geography_id: str,
    metric: str,
    appropriation_type: str = APPROPRIATION_FILTER_ALL,
    assistance_type: str | None = None,
    fiscal_year: int | None = None,
    awarding_office: str | None = None,
    funding_office: str | None = None,
    center: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    normalized_basis = _normalize_basis(basis)
    normalized_geography = _normalize_geography(geography)
    normalized_mode = _normalize_funding_geography_mode(funding_geography_mode)
    normalized_appropriation_type = _normalize_appropriation_type(appropriation_type)
    normalized_metric = _normalize_metric(metric, basis=normalized_basis)
    _ensure_award_tables(db)
    if normalized_basis == "prime" and normalized_mode == "statewide_allocation":
        _ensure_scope_classification_table(db)

    if normalized_geography == "state":
        normalized_geo_id = _normalize_state_code(geography_id)
        if normalized_geo_id is None:
            raise HTTPException(status_code=400, detail="geography_id must be a 2-letter state code")
    else:
        digits = re.sub(r"[^0-9]", "", str(geography_id).strip())
        if len(digits) != 5:
            raise HTTPException(status_code=400, detail="geography_id must be a 5-digit county FIPS")
        normalized_geo_id = digits

    top_limit = max(1, min(int(limit), 50))

    params: dict[str, Any] = {
        "geography_id": normalized_geo_id,
        "limit": top_limit,
    }

    if normalized_basis == "prime":
        effective_fiscal_year = fiscal_year
        if effective_fiscal_year is None:
            effective_fiscal_year = _latest_prime_transaction_fiscal_year(db)
        if effective_fiscal_year is not None:
            params["fiscal_year"] = int(effective_fiscal_year)

        base_filters = ["tx.assistance_award_unique_key IS NOT NULL"]
        assistance_type = _strip_optional(assistance_type)
        if assistance_type:
            base_filters.append("tx.assistance_type_description = :assistance_type")
            params["assistance_type"] = assistance_type
        if effective_fiscal_year is not None:
            base_filters.append("tx.action_date_fiscal_year = :fiscal_year")
        if normalized_appropriation_type != APPROPRIATION_FILTER_ALL:
            base_filters.append("tx.appropriation_type = :appropriation_type")
            params["appropriation_type"] = normalized_appropriation_type
        if awarding_office:
            base_filters.append("tx.awarding_office_name = :awarding_office")
            params["awarding_office"] = awarding_office
        if funding_office:
            base_filters.append("tx.funding_office_name = :funding_office")
            params["funding_office"] = funding_office
        if center:
            base_filters.append("(tx.awarding_sub_agency_name = :center OR tx.funding_sub_agency_name = :center)")
            params["center"] = center

        default_order_column = {
            "fy_obligated": "fy_obligated_amount",
            "fy_outlayed_estimated": "fy_outlayed_amount_estimated",
            "transaction_count": "transaction_count",
            "distinct_award_count": "distinct_award_count",
        }.get(normalized_metric, "fy_obligated_amount")

        if normalized_mode == "statewide_allocation" and normalized_geography == "county":
            county_weight = _county_population_weight(db, normalized_geo_id)
            if (
                county_weight is None
                or county_weight.get("state_code") is None
                or county_weight.get("population_weight") is None
            ):
                rows = []
            else:
                params["county_state_code"] = county_weight.get("state_code")
                params["county_population_weight"] = float(
                    county_weight.get("population_weight") or 0
                )
                params["county_name"] = county_weight.get("county_name")
                base_where_sql = " AND ".join(base_filters)
                order_column = {
                    "fy_obligated": "fy_obligated_amount",
                    "fy_outlayed_estimated": "fy_outlayed_amount_estimated",
                    "transaction_count": "transaction_count",
                    "distinct_award_count": "distinct_award_count",
                }.get(normalized_metric, "fy_obligated_amount")
                rows = db.execute(
                    text(
                        f"""
                        WITH tx_ordered AS (
                            SELECT
                                t.*,
                                COALESCE(t.recipient_state_code, p.recipient_state_code) AS resolved_state_code,
                                COALESCE(NULLIF(t.recipient_state_name, ''), p.recipient_state_name) AS resolved_state_name,
                                COALESCE(
                                    t.prime_award_transaction_recipient_county_fips_code,
                                    p.recipient_county_fips
                                ) AS resolved_county_fips,
                                COALESCE(NULLIF(t.recipient_county_name, ''), p.recipient_county_name) AS resolved_county_name,
                                COALESCE(cls.scope_classification, 'unknown') AS scope_classification,
                                LAG(t.total_outlayed_amount_for_overall_award) OVER (
                                    PARTITION BY COALESCE(
                                        t.assistance_award_unique_key,
                                        t.assistance_transaction_unique_key
                                    )
                                    ORDER BY
                                        t.action_date NULLS FIRST,
                                        COALESCE(t.modification_number, ''),
                                        t.assistance_transaction_unique_key
                                ) AS prior_total_outlayed_amount_for_overall_award
                            FROM {PRIME_TX_TABLE} AS t
                            LEFT JOIN {PRIME_TABLE} AS p
                                ON p.unique_key = t.assistance_award_unique_key
                            LEFT JOIN {AWARD_SCOPE_CLASSIFICATION_TABLE} AS cls
                                ON cls.assistance_award_unique_key = t.assistance_award_unique_key
                        ),
                        tx_base AS (
                            SELECT
                                tx.*,
                                CASE
                                    WHEN tx.total_outlayed_amount_for_overall_award IS NULL THEN NULL
                                    WHEN tx.prior_total_outlayed_amount_for_overall_award IS NULL
                                        THEN tx.total_outlayed_amount_for_overall_award
                                    ELSE tx.total_outlayed_amount_for_overall_award
                                        - tx.prior_total_outlayed_amount_for_overall_award
                                END AS estimated_outlay_delta
                            FROM tx_ordered AS tx
                            WHERE {base_where_sql}
                        ),
                        tx_contrib AS (
                            SELECT
                                base.*,
                                COALESCE(base.federal_action_obligation, 0)::numeric AS county_contribution_fy_obligated_amount,
                                COALESCE(base.estimated_outlay_delta, 0)::numeric AS county_contribution_fy_outlayed_amount_estimated,
                                1::numeric AS county_contribution_transaction_count,
                                false AS includes_statewide_allocation
                            FROM tx_base AS base
                            WHERE base.scope_classification <> 'statewide'
                              AND base.resolved_county_fips = :geography_id
                            UNION ALL
                            SELECT
                                base.*,
                                COALESCE(base.federal_action_obligation, 0)::numeric
                                    * :county_population_weight
                                    AS county_contribution_fy_obligated_amount,
                                COALESCE(base.estimated_outlay_delta, 0)::numeric
                                    * :county_population_weight
                                    AS county_contribution_fy_outlayed_amount_estimated,
                                CAST(:county_population_weight AS numeric) AS county_contribution_transaction_count,
                                true AS includes_statewide_allocation
                            FROM tx_base AS base
                            WHERE base.scope_classification = 'statewide'
                              AND base.resolved_state_code = :county_state_code
                        ),
                        award_totals AS (
                            SELECT
                                base.assistance_award_unique_key AS record_id,
                                COALESCE(SUM(base.federal_action_obligation), 0) AS award_fy_obligated_amount,
                                COALESCE(SUM(base.estimated_outlay_delta), 0) AS award_fy_outlayed_amount_estimated
                            FROM tx_base AS base
                            GROUP BY base.assistance_award_unique_key
                        )
                        SELECT
                            contrib.assistance_award_unique_key AS record_id,
                            'prime_award'::text AS record_type,
                            MAX(COALESCE(p.fain, contrib.award_id_fain)) AS fain,
                            MAX(COALESCE(p.recipient_name, contrib.recipient_name)) AS entity_name,
                            MAX(contrib.assistance_type_description) AS assistance_type_description,
                            COALESCE(SUM(contrib.county_contribution_fy_obligated_amount), 0)
                                AS fy_obligated_amount,
                            COALESCE(SUM(contrib.county_contribution_fy_outlayed_amount_estimated), 0)
                                AS fy_outlayed_amount_estimated,
                            GREATEST(
                                0,
                                ROUND(COALESCE(SUM(contrib.county_contribution_transaction_count), 0))
                            )::integer AS transaction_count,
                            1::integer AS distinct_award_count,
                            MAX(p.total_funding_amount) AS lifetime_total_funding_amount,
                            MAX(contrib.action_date) AS latest_action_date,
                            MAX(contrib.resolved_state_code) AS state_code,
                            MAX(contrib.resolved_state_name) AS state_name,
                            CAST(:geography_id AS text) AS county_fips,
                            MAX(COALESCE(CAST(:county_name AS text), contrib.resolved_county_name)) AS county_name,
                            MAX(
                                COALESCE(
                                    contrib.transaction_description,
                                    contrib.prime_award_base_transaction_description,
                                    p.prime_award_base_transaction_description
                                )
                            ) AS description,
                            MAX(COALESCE(contrib.usaspending_permalink, p.usaspending_permalink))
                                AS usaspending_permalink,
                            bool_or(contrib.includes_statewide_allocation) AS includes_statewide_allocation,
                            MAX(contrib.scope_classification) AS scope_classification,
                            MAX(contrib.appropriation_type) AS appropriation_type,
                            MAX(contrib.appropriation_subtype) AS appropriation_subtype,
                            MAX(contrib.disaster_emergency_fund_codes_raw) AS raw_emergency_code,
                            MAX(contrib.appropriation_classification_source)
                                AS appropriation_classification_source,
                            COALESCE(MAX(totals.award_fy_obligated_amount), 0) AS award_fy_obligated_amount,
                            COALESCE(MAX(totals.award_fy_outlayed_amount_estimated), 0)
                                AS award_fy_outlayed_amount_estimated
                        FROM tx_contrib AS contrib
                        LEFT JOIN {PRIME_TABLE} AS p
                            ON p.unique_key = contrib.assistance_award_unique_key
                        LEFT JOIN award_totals AS totals
                            ON totals.record_id = contrib.assistance_award_unique_key
                        GROUP BY contrib.assistance_award_unique_key
                        ORDER BY {order_column} DESC NULLS LAST, MAX(contrib.action_date) DESC NULLS LAST
                        LIMIT :limit
                        """
                    ),
                    params,
                ).mappings().all()
        else:
            filters = [
                "tx.resolved_state_code = :geography_id"
                if normalized_geography == "state"
                else "tx.resolved_county_fips = :geography_id"
            ]
            filters.extend(base_filters)
            rows = db.execute(
                text(
                    f"""
                    WITH tx_ordered AS (
                        SELECT
                            t.*,
                            COALESCE(t.recipient_state_code, p.recipient_state_code) AS resolved_state_code,
                            COALESCE(NULLIF(t.recipient_state_name, ''), p.recipient_state_name) AS resolved_state_name,
                            COALESCE(
                                t.prime_award_transaction_recipient_county_fips_code,
                                p.recipient_county_fips
                            ) AS resolved_county_fips,
                            COALESCE(NULLIF(t.recipient_county_name, ''), p.recipient_county_name) AS resolved_county_name,
                            LAG(t.total_outlayed_amount_for_overall_award) OVER (
                                PARTITION BY COALESCE(
                                    t.assistance_award_unique_key,
                                    t.assistance_transaction_unique_key
                                )
                                ORDER BY
                                    t.action_date NULLS FIRST,
                                    COALESCE(t.modification_number, ''),
                                    t.assistance_transaction_unique_key
                            ) AS prior_total_outlayed_amount_for_overall_award
                        FROM {PRIME_TX_TABLE} AS t
                        LEFT JOIN {PRIME_TABLE} AS p
                            ON p.unique_key = t.assistance_award_unique_key
                    ),
                    tx_filtered AS (
                        SELECT
                            tx.*,
                            CASE
                                WHEN tx.total_outlayed_amount_for_overall_award IS NULL THEN NULL
                                WHEN tx.prior_total_outlayed_amount_for_overall_award IS NULL
                                    THEN tx.total_outlayed_amount_for_overall_award
                                ELSE tx.total_outlayed_amount_for_overall_award
                                    - tx.prior_total_outlayed_amount_for_overall_award
                            END AS estimated_outlay_delta
                        FROM tx_ordered AS tx
                        WHERE {' AND '.join(filters)}
                    )
                    SELECT
                        tx_filtered.assistance_award_unique_key AS record_id,
                        'prime_award'::text AS record_type,
                        MAX(COALESCE(p.fain, tx_filtered.award_id_fain)) AS fain,
                        MAX(COALESCE(p.recipient_name, tx_filtered.recipient_name)) AS entity_name,
                        MAX(tx_filtered.assistance_type_description) AS assistance_type_description,
                        COALESCE(SUM(tx_filtered.federal_action_obligation), 0) AS fy_obligated_amount,
                        COALESCE(SUM(tx_filtered.estimated_outlay_delta), 0) AS fy_outlayed_amount_estimated,
                        COUNT(*)::integer AS transaction_count,
                        COUNT(DISTINCT tx_filtered.assistance_award_unique_key)::integer AS distinct_award_count,
                        MAX(p.total_funding_amount) AS lifetime_total_funding_amount,
                        MAX(tx_filtered.action_date) AS latest_action_date,
                        MAX(tx_filtered.resolved_state_code) AS state_code,
                        MAX(tx_filtered.resolved_state_name) AS state_name,
                        MAX(tx_filtered.resolved_county_fips) AS county_fips,
                        MAX(tx_filtered.resolved_county_name) AS county_name,
                        MAX(
                            COALESCE(
                                tx_filtered.transaction_description,
                                tx_filtered.prime_award_base_transaction_description,
                                p.prime_award_base_transaction_description
                            )
                        ) AS description,
                        MAX(COALESCE(tx_filtered.usaspending_permalink, p.usaspending_permalink)) AS usaspending_permalink,
                        false AS includes_statewide_allocation,
                        NULL::text AS scope_classification,
                        MAX(tx_filtered.appropriation_type) AS appropriation_type,
                        MAX(tx_filtered.appropriation_subtype) AS appropriation_subtype,
                        MAX(tx_filtered.disaster_emergency_fund_codes_raw) AS raw_emergency_code,
                        MAX(tx_filtered.appropriation_classification_source)
                            AS appropriation_classification_source,
                        NULL::numeric AS award_fy_obligated_amount,
                        NULL::numeric AS award_fy_outlayed_amount_estimated
                    FROM tx_filtered
                    LEFT JOIN {PRIME_TABLE} AS p
                        ON p.unique_key = tx_filtered.assistance_award_unique_key
                    GROUP BY tx_filtered.assistance_award_unique_key
                    ORDER BY {default_order_column} DESC NULLS LAST, MAX(tx_filtered.action_date) DESC NULLS LAST
                    LIMIT :limit
                    """
                ),
                params,
            ).mappings().all()
    else:
        filters = [
            "s.subawardee_state_code = :geography_id"
            if normalized_geography == "state"
            else "s.subawardee_county_fips = :geography_id"
        ]

        if fiscal_year is not None:
            filters.append("s.subaward_action_date_fiscal_year = :fiscal_year")
            params["fiscal_year"] = int(fiscal_year)
        if normalized_appropriation_type != APPROPRIATION_FILTER_ALL:
            filters.append("s.appropriation_type = :appropriation_type")
            params["appropriation_type"] = normalized_appropriation_type
        if awarding_office:
            filters.append("s.prime_award_awarding_office_name = :awarding_office")
            params["awarding_office"] = awarding_office
        if funding_office:
            filters.append("s.prime_award_funding_office_name = :funding_office")
            params["funding_office"] = funding_office
        if center:
            filters.append(
                "(s.prime_award_awarding_sub_agency_name = :center OR s.prime_award_funding_sub_agency_name = :center)"
            )
            params["center"] = center

        rows = db.execute(
            text(
                f"""
                SELECT
                    s.id::text AS record_id,
                    'subaward'::text AS record_type,
                    s.prime_award_fain AS fain,
                    s.subawardee_name AS entity_name,
                    NULL::text AS assistance_type_description,
                    s.subaward_amount AS amount,
                    s.subaward_action_date AS latest_action_date,
                    s.subawardee_state_code AS state_code,
                    s.subawardee_state_name AS state_name,
                    s.subawardee_county_fips AS county_fips,
                    NULL::text AS county_name,
                    COALESCE(s.subaward_description, s.prime_award_base_transaction_description) AS description,
                    s.usaspending_permalink,
                    s.appropriation_type,
                    s.appropriation_subtype,
                    s.prime_award_disaster_emergency_fund_codes_raw AS raw_emergency_code,
                    s.appropriation_classification_source
                FROM {SUBAWARD_TABLE} AS s
                WHERE {' AND '.join(filters)}
                ORDER BY s.subaward_amount DESC NULLS LAST, s.subaward_action_date DESC NULLS LAST
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()

    if normalized_basis == "prime":
        if (
            normalized_mode == "statewide_allocation"
            and normalized_geography == "county"
        ):
            note = (
                "Top awards ranked by estimated county contribution. "
                "Statewide awards use county population shares; local awards use direct county geography."
            )
        else:
            note = (
                f"Top awards ranked by fiscal year {params.get('fiscal_year')} transaction activity."
                if params.get("fiscal_year") is not None
                else "Top awards ranked by transaction activity."
            )
    else:
        if normalized_mode == "statewide_allocation":
            note = (
                "Subawards reported to entities in this geography. "
                "Statewide allocation mode applies to Prime Awards only."
            )
        else:
            note = "Subawards reported to entities in this geography"

    if normalized_appropriation_type == APPROPRIATION_TYPE_COVID_EMERGENCY:
        note = (
            f"{note} COVID / emergency supplemental funding is identified using "
            "official emergency funding codes reported in the source data."
        )

    effective_mode = normalized_mode if normalized_basis == "prime" else "recipient_location"
    summary_table = _summary_table(
        basis=normalized_basis,
        geography=normalized_geography,
        funding_geography_mode=effective_mode,
    )
    summary_filter_sql, summary_filter_params = _summary_filters_sql(
        basis=normalized_basis,
        geography=normalized_geography,
        appropriation_type=normalized_appropriation_type,
        assistance_type=assistance_type if normalized_basis == "prime" else None,
        fiscal_year=params.get("fiscal_year"),
        awarding_office=awarding_office,
        funding_office=funding_office,
        center=center,
        state=None,
    )
    summary_filter_params["geography_id"] = normalized_geo_id
    summary_sql = _summary_aggregate_sql(
        basis=normalized_basis,
        metric_column=_metric_column(normalized_basis, normalized_metric),
        table_name=summary_table,
        where_sql=f"{summary_filter_sql} AND s.geography_id = :geography_id",
    )
    geography_summary_row = db.execute(
        text(
            f"""
            WITH summary AS ({summary_sql})
            SELECT
                SUM(summary.metric_value) AS metric_value,
                CASE
                    WHEN MAX(summary.population) IS NULL OR MAX(summary.population) = 0 THEN NULL
                    ELSE SUM(summary.metric_value) / NULLIF(MAX(summary.population), 0)
                END AS metric_per_capita,
                MAX(summary.population) AS population,
                SUM(summary.total_funding_amount) AS total_funding_amount,
                CASE
                    WHEN MAX(summary.population) IS NULL OR MAX(summary.population) = 0 THEN NULL
                    ELSE SUM(summary.total_funding_amount) / NULLIF(MAX(summary.population), 0)
                END AS funding_per_capita
            FROM summary
            """
        ),
        summary_filter_params,
    ).mappings().one()
    geography_summary = {
        "geography": normalized_geography,
        "geography_id": normalized_geo_id,
        "metric": normalized_metric,
        "metric_label": METRIC_LABELS.get(normalized_metric, normalized_metric),
        "metric_value": _json_number(geography_summary_row.get("metric_value")),
        "metric_per_capita": _json_number(geography_summary_row.get("metric_per_capita")),
        "population": _json_number(geography_summary_row.get("population")),
        "total_funding_amount": _json_number(geography_summary_row.get("total_funding_amount")),
        "funding_per_capita": _json_number(geography_summary_row.get("funding_per_capita")),
    }

    return {
        "basis": normalized_basis,
        "appropriation_type": normalized_appropriation_type,
        "appropriation_type_label": APPROPRIATION_FILTER_LABELS.get(
            normalized_appropriation_type,
            normalized_appropriation_type,
        ),
        "funding_geography_mode": effective_mode,
        "geography": normalized_geography,
        "geography_id": normalized_geo_id,
        "metric": normalized_metric,
        "fiscal_year": params.get("fiscal_year"),
        "note": note,
        "geography_summary": geography_summary,
        "rows": [
            {
                "record_id": row["record_id"],
                "record_type": row["record_type"],
                "fain": row["fain"],
                "entity_name": row["entity_name"],
                "assistance_type_description": row["assistance_type_description"],
                "amount": _json_number(
                    row["fy_obligated_amount"]
                    if normalized_basis == "prime" and normalized_metric == "fy_obligated"
                    else row["fy_outlayed_amount_estimated"]
                    if normalized_basis == "prime" and normalized_metric == "fy_outlayed_estimated"
                    else row["transaction_count"]
                    if normalized_basis == "prime" and normalized_metric == "transaction_count"
                    else row["distinct_award_count"]
                    if normalized_basis == "prime"
                    else row["amount"]
                ),
                "fy_obligated_amount": _json_number(row.get("fy_obligated_amount")),
                "fy_outlayed_amount_estimated": _json_number(row.get("fy_outlayed_amount_estimated")),
                "transaction_count": int(row.get("transaction_count") or 0),
                "distinct_award_count": int(row.get("distinct_award_count") or 0),
                "lifetime_total_funding_amount": _json_number(row.get("lifetime_total_funding_amount")),
                "latest_action_date": row["latest_action_date"].isoformat() if row["latest_action_date"] else None,
                "state_code": row["state_code"],
                "state_name": row["state_name"],
                "county_fips": row["county_fips"],
                "county_name": row["county_name"],
                "description": row["description"],
                "usaspending_permalink": row["usaspending_permalink"],
                "includes_statewide_allocation": bool(row.get("includes_statewide_allocation")),
                "scope_classification": row.get("scope_classification"),
                "appropriation_type": row.get("appropriation_type"),
                "appropriation_subtype": row.get("appropriation_subtype"),
                "raw_emergency_code": row.get("raw_emergency_code"),
                "appropriation_classification_source": row.get("appropriation_classification_source"),
                "award_fy_obligated_amount": _json_number(row.get("award_fy_obligated_amount")),
                "award_fy_outlayed_amount_estimated": _json_number(
                    row.get("award_fy_outlayed_amount_estimated")
                ),
            }
            for row in rows
        ],
    }


def fetch_ingestion_debug(db: Session) -> dict[str, Any]:
    _ensure_award_tables(db)

    counts_by_fiscal_year = db.execute(
        text(
            f"""
            SELECT
                record_type,
                fiscal_year,
                COUNT(*)::integer AS row_count
            FROM (
                SELECT
                    'prime_award'::text AS record_type,
                    p.award_latest_action_date_fiscal_year AS fiscal_year
                FROM {PRIME_TABLE} AS p
                UNION ALL
                SELECT
                    'prime_transaction'::text AS record_type,
                    tx.action_date_fiscal_year AS fiscal_year
                FROM {PRIME_TX_TABLE} AS tx
                UNION ALL
                SELECT
                    'subaward'::text AS record_type,
                    s.subaward_action_date_fiscal_year AS fiscal_year
                FROM {SUBAWARD_TABLE} AS s
            ) AS unioned
            GROUP BY record_type, fiscal_year
            ORDER BY record_type, fiscal_year
            """
        )
    ).mappings().all()

    source_file_available = (
        _column_exists(db, PRIME_TABLE, "source_file_name")
        and _column_exists(db, PRIME_TX_TABLE, "source_file_name")
        and _column_exists(db, SUBAWARD_TABLE, "source_file_name")
    )
    counts_by_source_file = (
        db.execute(
            text(
                f"""
                SELECT
                    record_type,
                    source_file_name,
                    COUNT(*)::integer AS row_count
                FROM (
                    SELECT
                        'prime_award'::text AS record_type,
                        COALESCE(NULLIF(TRIM(p.source_file_name), ''), '<unknown>') AS source_file_name
                    FROM {PRIME_TABLE} AS p
                    UNION ALL
                    SELECT
                        'prime_transaction'::text AS record_type,
                        COALESCE(NULLIF(TRIM(tx.source_file_name), ''), '<unknown>') AS source_file_name
                    FROM {PRIME_TX_TABLE} AS tx
                    UNION ALL
                    SELECT
                        'subaward'::text AS record_type,
                        COALESCE(NULLIF(TRIM(s.source_file_name), ''), '<unknown>') AS source_file_name
                    FROM {SUBAWARD_TABLE} AS s
                ) AS unioned
                GROUP BY record_type, source_file_name
                ORDER BY record_type, source_file_name
                """
            )
        ).mappings().all()
        if source_file_available
        else []
    )

    counts_by_appropriation = db.execute(
        text(
            f"""
            SELECT
                record_type,
                COALESCE(appropriation_type, 'unknown') AS appropriation_type,
                COALESCE(appropriation_subtype, 'UNKNOWN') AS appropriation_subtype,
                COUNT(*)::integer AS row_count
            FROM (
                SELECT
                    'prime_award'::text AS record_type,
                    p.appropriation_type,
                    p.appropriation_subtype
                FROM {PRIME_TABLE} AS p
                UNION ALL
                SELECT
                    'prime_transaction'::text AS record_type,
                    tx.appropriation_type,
                    tx.appropriation_subtype
                FROM {PRIME_TX_TABLE} AS tx
                UNION ALL
                SELECT
                    'subaward'::text AS record_type,
                    s.appropriation_type,
                    s.appropriation_subtype
                FROM {SUBAWARD_TABLE} AS s
            ) AS unioned
            GROUP BY
                record_type,
                COALESCE(appropriation_type, 'unknown'),
                COALESCE(appropriation_subtype, 'UNKNOWN')
            ORDER BY
                record_type,
                COALESCE(appropriation_type, 'unknown'),
                COALESCE(appropriation_subtype, 'UNKNOWN')
            """
        )
    ).mappings().all()

    distinct_counts_by_fiscal_year = db.execute(
        text(
            f"""
            SELECT
                metric_name,
                fiscal_year,
                metric_value
            FROM (
                SELECT
                    'prime_awards_distinct'::text AS metric_name,
                    p.award_latest_action_date_fiscal_year AS fiscal_year,
                    COUNT(DISTINCT p.unique_key)::integer AS metric_value
                FROM {PRIME_TABLE} AS p
                GROUP BY p.award_latest_action_date_fiscal_year
                UNION ALL
                SELECT
                    'prime_transactions_distinct'::text AS metric_name,
                    tx.action_date_fiscal_year AS fiscal_year,
                    COUNT(DISTINCT tx.assistance_transaction_unique_key)::integer AS metric_value
                FROM {PRIME_TX_TABLE} AS tx
                GROUP BY tx.action_date_fiscal_year
                UNION ALL
                SELECT
                    'prime_tx_awards_distinct'::text AS metric_name,
                    tx.action_date_fiscal_year AS fiscal_year,
                    COUNT(DISTINCT tx.assistance_award_unique_key)::integer AS metric_value
                FROM {PRIME_TX_TABLE} AS tx
                GROUP BY tx.action_date_fiscal_year
                UNION ALL
                SELECT
                    'subaward_rows_distinct'::text AS metric_name,
                    s.subaward_action_date_fiscal_year AS fiscal_year,
                    COUNT(*)::integer AS metric_value
                FROM {SUBAWARD_TABLE} AS s
                GROUP BY s.subaward_action_date_fiscal_year
            ) AS metrics
            ORDER BY metric_name, fiscal_year
            """
        )
    ).mappings().all()

    subaward_duplicate_key_column = (
        "subaward_unique_key"
        if _column_exists(db, SUBAWARD_TABLE, "subaward_unique_key")
        else "prime_award_unique_key"
    )
    duplicate_key_checks = {
        "prime_awards": db.execute(
            text(
                f"""
                SELECT
                    COUNT(*)::integer AS duplicate_group_count
                FROM (
                    SELECT unique_key
                    FROM {PRIME_TABLE}
                    GROUP BY unique_key
                    HAVING COUNT(*) > 1
                ) AS dupes
                """
            )
        ).mappings().one().get("duplicate_group_count"),
        "prime_transactions": db.execute(
            text(
                f"""
                SELECT
                    COUNT(*)::integer AS duplicate_group_count
                FROM (
                    SELECT assistance_transaction_unique_key
                    FROM {PRIME_TX_TABLE}
                    GROUP BY assistance_transaction_unique_key
                    HAVING COUNT(*) > 1
                ) AS dupes
                """
            )
        ).mappings().one().get("duplicate_group_count"),
        "subawards": db.execute(
            text(
                f"""
                SELECT
                    COUNT(*)::integer AS duplicate_group_count
                FROM (
                    SELECT {subaward_duplicate_key_column}
                    FROM {SUBAWARD_TABLE}
                    GROUP BY {subaward_duplicate_key_column}
                    HAVING COUNT(*) > 1
                ) AS dupes
                """
            )
        ).mappings().one().get("duplicate_group_count"),
        "subaward_duplicate_key_column": subaward_duplicate_key_column,
    }

    missing_geography_by_fiscal_year = db.execute(
        text(
            f"""
            SELECT
                record_type,
                fiscal_year,
                total_rows,
                missing_state_count,
                missing_county_count
            FROM (
                SELECT
                    'prime_award'::text AS record_type,
                    p.award_latest_action_date_fiscal_year AS fiscal_year,
                    COUNT(*)::integer AS total_rows,
                    COUNT(*) FILTER (WHERE p.recipient_state_code IS NULL)::integer AS missing_state_count,
                    COUNT(*) FILTER (WHERE p.recipient_county_fips IS NULL)::integer AS missing_county_count
                FROM {PRIME_TABLE} AS p
                GROUP BY p.award_latest_action_date_fiscal_year
                UNION ALL
                SELECT
                    'prime_transaction'::text AS record_type,
                    tx.action_date_fiscal_year AS fiscal_year,
                    COUNT(*)::integer AS total_rows,
                    COUNT(*) FILTER (
                        WHERE COALESCE(tx.recipient_state_code, p.recipient_state_code) IS NULL
                    )::integer AS missing_state_count,
                    COUNT(*) FILTER (
                        WHERE COALESCE(
                            tx.prime_award_transaction_recipient_county_fips_code,
                            p.recipient_county_fips
                        ) IS NULL
                    )::integer AS missing_county_count
                FROM {PRIME_TX_TABLE} AS tx
                LEFT JOIN {PRIME_TABLE} AS p
                    ON p.unique_key = tx.assistance_award_unique_key
                GROUP BY tx.action_date_fiscal_year
                UNION ALL
                SELECT
                    'subaward'::text AS record_type,
                    s.subaward_action_date_fiscal_year AS fiscal_year,
                    COUNT(*)::integer AS total_rows,
                    COUNT(*) FILTER (WHERE s.subawardee_state_code IS NULL)::integer AS missing_state_count,
                    COUNT(*) FILTER (WHERE s.subawardee_county_fips IS NULL)::integer AS missing_county_count
                FROM {SUBAWARD_TABLE} AS s
                GROUP BY s.subaward_action_date_fiscal_year
            ) AS unioned
            ORDER BY record_type, fiscal_year
            """
        )
    ).mappings().all()

    population_debug: dict[str, Any] = {}
    population_columns_available = _column_exists(db, PRIME_TX_STATE_SUMMARY_TABLE, "population")
    national_summary_available = _table_exists(db, PRIME_TX_NATIONAL_SUMMARY_TABLE) and _table_exists(
        db, SUBAWARD_NATIONAL_SUMMARY_TABLE
    )
    if population_columns_available and national_summary_available:
        missing_population_by_table = db.execute(
            text(
                f"""
                SELECT
                    summary_table,
                    COUNT(*)::integer AS total_rows,
                    COUNT(*) FILTER (
                        WHERE population IS NULL OR population <= 0
                    )::integer AS missing_population_count
                FROM (
                    SELECT 'prime_state'::text AS summary_table, population
                    FROM {PRIME_TX_STATE_SUMMARY_TABLE}
                    UNION ALL
                    SELECT 'prime_county'::text AS summary_table, population
                    FROM {PRIME_TX_COUNTY_SUMMARY_TABLE}
                    UNION ALL
                    SELECT 'prime_county_allocated'::text AS summary_table, population
                    FROM {PRIME_TX_COUNTY_ALLOCATED_SUMMARY_TABLE}
                    UNION ALL
                    SELECT 'subaward_state'::text AS summary_table, population
                    FROM {SUBAWARD_STATE_SUMMARY_TABLE}
                    UNION ALL
                    SELECT 'subaward_county'::text AS summary_table, population
                    FROM {SUBAWARD_COUNTY_SUMMARY_TABLE}
                ) AS unioned
                GROUP BY summary_table
                ORDER BY summary_table
                """
            )
        ).mappings().all()

        prime_national_recent = db.execute(
            text(
                f"""
                SELECT
                    fiscal_year,
                    total_funding_amount,
                    population,
                    funding_per_capita,
                    fy_obligated_amount,
                    fy_obligated_per_capita,
                    fy_outlayed_amount_estimated,
                    fy_outlayed_amount_estimated_per_capita
                FROM {PRIME_TX_NATIONAL_SUMMARY_TABLE}
                ORDER BY fiscal_year DESC NULLS LAST
                LIMIT 5
                """
            )
        ).mappings().all()
        subaward_national_recent = db.execute(
            text(
                f"""
                SELECT
                    fiscal_year,
                    total_funding_amount,
                    population,
                    funding_per_capita,
                    total_subaward_amount,
                    total_subaward_per_capita
                FROM {SUBAWARD_NATIONAL_SUMMARY_TABLE}
                ORDER BY fiscal_year DESC NULLS LAST
                LIMIT 5
                """
            )
        ).mappings().all()
        prime_state_sample = db.execute(
            text(
                f"""
                SELECT
                    geography_id,
                    fiscal_year,
                    total_funding_amount,
                    population,
                    funding_per_capita
                FROM {PRIME_TX_STATE_SUMMARY_TABLE}
                WHERE geography_id IS NOT NULL
                ORDER BY fiscal_year DESC NULLS LAST, total_funding_amount DESC NULLS LAST
                LIMIT 5
                """
            )
        ).mappings().all()
        prime_county_sample = db.execute(
            text(
                f"""
                SELECT
                    geography_id,
                    fiscal_year,
                    total_funding_amount,
                    population,
                    funding_per_capita
                FROM {PRIME_TX_COUNTY_SUMMARY_TABLE}
                WHERE geography_id IS NOT NULL
                ORDER BY fiscal_year DESC NULLS LAST, total_funding_amount DESC NULLS LAST
                LIMIT 5
                """
            )
        ).mappings().all()
        population_debug = {
            "missing_population_join_counts": [
                {
                    "summary_table": row.get("summary_table"),
                    "total_rows": int(row.get("total_rows") or 0),
                    "missing_population_count": int(row.get("missing_population_count") or 0),
                }
                for row in missing_population_by_table
            ],
            "prime_national_recent": [
                {key: _serialize_value(value) for key, value in dict(row).items()}
                for row in prime_national_recent
            ],
            "subaward_national_recent": [
                {key: _serialize_value(value) for key, value in dict(row).items()}
                for row in subaward_national_recent
            ],
            "prime_state_sample": [
                {key: _serialize_value(value) for key, value in dict(row).items()}
                for row in prime_state_sample
            ],
            "prime_county_sample": [
                {key: _serialize_value(value) for key, value in dict(row).items()}
                for row in prime_county_sample
            ],
        }

    return {
        "counts_by_fiscal_year": [
            {
                "record_type": row.get("record_type"),
                "fiscal_year": row.get("fiscal_year"),
                "row_count": int(row.get("row_count") or 0),
            }
            for row in counts_by_fiscal_year
        ],
        "counts_by_source_file": [
            {
                "record_type": row.get("record_type"),
                "source_file_name": row.get("source_file_name"),
                "row_count": int(row.get("row_count") or 0),
            }
            for row in counts_by_source_file
        ],
        "counts_by_appropriation_type_subtype": [
            {
                "record_type": row.get("record_type"),
                "appropriation_type": row.get("appropriation_type"),
                "appropriation_subtype": row.get("appropriation_subtype"),
                "row_count": int(row.get("row_count") or 0),
            }
            for row in counts_by_appropriation
        ],
        "distinct_counts_by_fiscal_year": [
            {
                "metric_name": row.get("metric_name"),
                "fiscal_year": row.get("fiscal_year"),
                "metric_value": int(row.get("metric_value") or 0),
            }
            for row in distinct_counts_by_fiscal_year
        ],
        "duplicate_key_checks": {
            "prime_awards_duplicate_groups": int(duplicate_key_checks["prime_awards"] or 0),
            "prime_transactions_duplicate_groups": int(duplicate_key_checks["prime_transactions"] or 0),
            "subawards_duplicate_groups": int(duplicate_key_checks["subawards"] or 0),
            "subaward_duplicate_key_column": duplicate_key_checks["subaward_duplicate_key_column"],
        },
        "missing_geography_by_fiscal_year": [
            {
                "record_type": row.get("record_type"),
                "fiscal_year": row.get("fiscal_year"),
                "total_rows": int(row.get("total_rows") or 0),
                "missing_state_count": int(row.get("missing_state_count") or 0),
                "missing_county_count": int(row.get("missing_county_count") or 0),
            }
            for row in missing_geography_by_fiscal_year
        ],
        "population_per_capita_debug": population_debug,
    }
