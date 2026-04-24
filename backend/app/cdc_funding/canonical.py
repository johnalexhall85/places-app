from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db_fqtn import cdc_funding_table, places_table

FUNDING_MODEL_KEY = "canonical_v1"
FUNDING_MODEL_LABEL = "Canonical CDC Funding"
MODEL_VERSION = "canonical_cdc_funding_api_v1"
FACT_VIEW = cdc_funding_table("canonical_funding_fact_v1")
STATE_BOUNDARY_TABLE = places_table("dim_state_boundary")
COUNTY_BOUNDARY_TABLE = places_table("dim_county_boundary")
COUNTY_DIM_TABLE = places_table("dim_county")
POPULATION_VIEW_TABLE = places_table("v_geography_population")

VALID_METRICS = {
    "total_funding": "Total CDC Funding",
    "funding_per_capita": "CDC Funding Per Capita",
    "funding_per_100k": "CDC Funding Per 100,000",
    "share_national": "Share of National CDC Funding",
}
FUNDING_TYPE_LABELS = {
    "total_cdc_funding": "All canonical CDC funding",
    "discretionary_only": "Discretionary funding only",
    "mandatory_only": "Mandatory funding only",
    "emergency_response": "Emergency response funding",
    "non_emergency_program": "Non-emergency program funding",
}
VALID_GEOGRAPHY_LEVELS = {"state", "county", "national"}
VALID_TIME_AGGREGATIONS = {"single_fiscal_year", "multi_year_total", "multi_year_average"}
VALID_REVIEW_MODES = {"analyst_only", "trusted_auto", "all_master_universe"}
DEFAULT_INCLUDE_MANDATORY = True
DEFAULT_INCLUDE_EMERGENCY = False
DEFAULT_INCLUDE_SUPPLEMENTAL = False
DEFAULT_INCLUDE_PPHF = True
DEFAULT_INCLUDE_TRANSFERS = True
DEFAULT_REVIEW_MODE = "all_master_universe"
STATE_SIMPLIFY_DEGREES = 0.04
COUNTY_SIMPLIFY_DEGREES = 0.02
STATE_BBOX_MAX_WIDTH = 140.0
STATE_BBOX_MAX_HEIGHT = 70.0
COUNTY_BBOX_MAX_WIDTH = 40.0
COUNTY_BBOX_MAX_HEIGHT = 24.0


@dataclass(frozen=True)
class CanonicalFilters:
    fiscal_year: int | None
    metric: str
    funding_type: str
    geography_level: str
    time_aggregation: str
    include_mandatory: bool
    include_emergency: bool
    include_supplemental: bool
    include_pphf: bool
    include_transfers: bool
    review_mode: str


@dataclass(frozen=True)
class NormalizedBbox:
    west: float
    south: float
    east: float
    north: float
    applied: bool
    ignored_reason: str | None = None


def is_canonical_mode(value: str | None) -> bool:
    return str(value or "").strip().lower() == FUNDING_MODEL_KEY


def mode_option() -> dict[str, Any]:
    return {
        "value": FUNDING_MODEL_KEY,
        "label": FUNDING_MODEL_LABEL,
        "system": True,
        "is_active": True,
        "sort_order": 40,
    }


def review_mode_options() -> list[dict[str, str]]:
    return [
        {"value": "all_master_universe", "label": "All canonical-universe rows"},
        {"value": "trusted_auto", "label": "Trusted auto + analyst reviewed"},
        {"value": "analyst_only", "label": "Analyst reviewed only"},
    ]


def filter_defaults() -> dict[str, Any]:
    return {
        "include_mandatory": DEFAULT_INCLUDE_MANDATORY,
        "include_emergency": DEFAULT_INCLUDE_EMERGENCY,
        "include_supplemental": DEFAULT_INCLUDE_SUPPLEMENTAL,
        "include_pphf": DEFAULT_INCLUDE_PPHF,
        "include_transfers": DEFAULT_INCLUDE_TRANSFERS,
        "review_mode": DEFAULT_REVIEW_MODE,
    }


def _table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(
        text("SELECT to_regclass(:name) AS exists"),
        {"name": table_name},
    ).mappings().one()
    return row.get("exists") is not None


def _ensure_required_views(db: Session) -> None:
    if not _table_exists(db, FACT_VIEW):
        raise HTTPException(
            status_code=503,
            detail=(
                "The canonical CDC funding model is unavailable because "
                f"{FACT_VIEW} is missing. Run migrations to create the canonical fact view."
            ),
        )


def available_fiscal_years_by_geography(db: Session) -> dict[str, list[int]]:
    _ensure_required_views(db)
    rows = db.execute(
        text(
            f"""
            SELECT
                fiscal_year,
                COUNT(*) FILTER (
                    WHERE include_in_canonical_universe = TRUE
                      AND state_abbr IS NOT NULL
                )::integer AS state_row_count,
                COUNT(*) FILTER (
                    WHERE include_in_canonical_universe = TRUE
                      AND geography_type = 'county'
                      AND county_fips IS NOT NULL
                )::integer AS county_row_count
            FROM {FACT_VIEW}
            WHERE fiscal_year IS NOT NULL
            GROUP BY fiscal_year
            ORDER BY fiscal_year DESC
            """
        )
    ).mappings().all()
    state_years = [int(row["fiscal_year"]) for row in rows if int(row.get("state_row_count") or 0) > 0]
    county_years = [int(row["fiscal_year"]) for row in rows if int(row.get("county_row_count") or 0) > 0]
    return {
        "state": state_years,
        "county": county_years,
        "national": state_years,
    }


def available_fiscal_years(db: Session, *, geography_level: str = "state") -> list[int]:
    availability = available_fiscal_years_by_geography(db)
    level = str(geography_level or "state").strip().lower()
    return availability.get(level, availability["state"])


def _latest_completed_federal_fiscal_year(reference_date: date | None = None) -> int:
    today = reference_date or date.today()
    return today.year if today.month >= 10 else today.year - 1


def default_fiscal_year(db: Session, *, geography_level: str = "state") -> int | None:
    years = available_fiscal_years(db, geography_level=geography_level)
    if not years:
        return None
    latest_completed_year = _latest_completed_federal_fiscal_year()
    for year in years:
        if year <= latest_completed_year:
            return year
    return years[0]


def _normalize_metric(value: str | None) -> str:
    token = str(value or "total_funding").strip().lower()
    if token not in VALID_METRICS:
        raise HTTPException(status_code=400, detail=f"metric must be one of {', '.join(sorted(VALID_METRICS))}")
    return token


def _normalize_geography_level(value: str | None) -> str:
    token = str(value or "state").strip().lower()
    if token not in VALID_GEOGRAPHY_LEVELS:
        raise HTTPException(
            status_code=400,
            detail=f"geography_level must be one of {', '.join(sorted(VALID_GEOGRAPHY_LEVELS))}",
        )
    return token


def _normalize_time_aggregation(value: str | None, *, fiscal_year: int | None) -> str:
    default_value = "single_fiscal_year" if fiscal_year is not None else "multi_year_total"
    token = str(value or default_value).strip().lower()
    if token not in VALID_TIME_AGGREGATIONS:
        raise HTTPException(
            status_code=400,
            detail=f"time_aggregation must be one of {', '.join(sorted(VALID_TIME_AGGREGATIONS))}",
        )
    if fiscal_year is None and token == "single_fiscal_year":
        raise HTTPException(
            status_code=400,
            detail="time_aggregation=single_fiscal_year requires a specific fiscal_year",
        )
    return token


def _normalize_review_mode(value: str | None) -> str:
    token = str(value or DEFAULT_REVIEW_MODE).strip().lower()
    if token not in VALID_REVIEW_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"review_mode must be one of {', '.join(sorted(VALID_REVIEW_MODES))}",
        )
    return token


def _normalize_bool(value: bool | None, *, default: bool) -> bool:
    return default if value is None else bool(value)


def _normalize_funding_type(value: str | None) -> str:
    token = str(value or "total_cdc_funding").strip().lower()
    if not token:
        return "total_cdc_funding"
    return token


def _normalize_filters(
    *,
    fiscal_year: int | None,
    metric: str | None,
    funding_type: str | None,
    geography_level: str | None,
    time_aggregation: str | None,
    include_mandatory: bool | None,
    include_emergency: bool | None,
    include_supplemental: bool | None,
    include_pphf: bool | None,
    include_transfers: bool | None,
    review_mode: str | None,
) -> CanonicalFilters:
    effective_fiscal_year = int(fiscal_year) if fiscal_year is not None else None
    return CanonicalFilters(
        fiscal_year=effective_fiscal_year,
        metric=_normalize_metric(metric),
        funding_type=_normalize_funding_type(funding_type),
        geography_level=_normalize_geography_level(geography_level),
        time_aggregation=_normalize_time_aggregation(time_aggregation, fiscal_year=effective_fiscal_year),
        include_mandatory=_normalize_bool(include_mandatory, default=DEFAULT_INCLUDE_MANDATORY),
        include_emergency=_normalize_bool(include_emergency, default=DEFAULT_INCLUDE_EMERGENCY),
        include_supplemental=_normalize_bool(include_supplemental, default=DEFAULT_INCLUDE_SUPPLEMENTAL),
        include_pphf=_normalize_bool(include_pphf, default=DEFAULT_INCLUDE_PPHF),
        include_transfers=_normalize_bool(include_transfers, default=DEFAULT_INCLUDE_TRANSFERS),
        review_mode=_normalize_review_mode(review_mode),
    )


def _normalize_bbox(
    bbox: str | None,
    *,
    geography_level: str,
) -> NormalizedBbox:
    text_value = str(bbox or "").strip()
    if not text_value:
        return NormalizedBbox(0.0, 0.0, 0.0, 0.0, applied=False)
    parts = [part.strip() for part in text_value.split(",")]
    if len(parts) != 4:
        return NormalizedBbox(0.0, 0.0, 0.0, 0.0, applied=False, ignored_reason="Malformed bbox ignored.")
    try:
        west, south, east, north = (float(part) for part in parts)
    except ValueError:
        return NormalizedBbox(0.0, 0.0, 0.0, 0.0, applied=False, ignored_reason="Malformed bbox ignored.")
    if not all(math.isfinite(value) for value in (west, south, east, north)):
        return NormalizedBbox(0.0, 0.0, 0.0, 0.0, applied=False, ignored_reason="Invalid bbox ignored.")
    if west < -180 or east > 180 or south < -90 or north > 90 or east <= west or north <= south:
        return NormalizedBbox(0.0, 0.0, 0.0, 0.0, applied=False, ignored_reason="Invalid bbox ignored.")
    if geography_level == "national":
        return NormalizedBbox(
            west,
            south,
            east,
            north,
            applied=False,
            ignored_reason="National bbox ignored.",
        )

    width = east - west
    height = north - south
    if geography_level == "county":
        if width > COUNTY_BBOX_MAX_WIDTH or height > COUNTY_BBOX_MAX_HEIGHT:
            return NormalizedBbox(
                west,
                south,
                east,
                north,
                applied=False,
                ignored_reason="Broad county bbox ignored until the map is zoomed in further.",
            )
    elif geography_level == "state":
        if width > STATE_BBOX_MAX_WIDTH or height > STATE_BBOX_MAX_HEIGHT:
            return NormalizedBbox(
                west,
                south,
                east,
                north,
                applied=False,
                ignored_reason="Broad state bbox ignored.",
            )
    return NormalizedBbox(west, south, east, north, applied=True)


def _scoped_records_cte(
    filters: CanonicalFilters,
    *,
    state: str | None = None,
) -> tuple[str, dict[str, Any]]:
    clauses = [
        "include_in_canonical_universe = TRUE",
        "state_abbr IS NOT NULL",
    ]
    params: dict[str, Any] = {
        "time_aggregation": filters.time_aggregation,
    }
    if filters.fiscal_year is not None:
        clauses.append("fiscal_year = :fiscal_year")
        params["fiscal_year"] = filters.fiscal_year
    if state:
        clauses.append("state_abbr = :state_code")
        params["state_code"] = str(state).strip().upper()
    if filters.funding_type == "mandatory_only":
        clauses.append("discretionary_mandatory_type = 'mandatory'")
    elif filters.funding_type == "discretionary_only":
        clauses.append("discretionary_mandatory_type <> 'mandatory'")
    elif not filters.include_mandatory:
        clauses.append("discretionary_mandatory_type <> 'mandatory'")
    if not filters.include_emergency:
        clauses.append("COALESCE(emergency_flag, FALSE) = FALSE")
    if not filters.include_supplemental:
        clauses.append("COALESCE(supplemental_flag, FALSE) = FALSE")
    if not filters.include_pphf:
        clauses.append("COALESCE(pphf_flag, FALSE) = FALSE")
    if not filters.include_transfers:
        clauses.append("COALESCE(transfer_flag, FALSE) = FALSE")
    if filters.review_mode == "analyst_only":
        clauses.append("review_mode_eligible_analyst_only = TRUE")
    elif filters.review_mode == "trusted_auto":
        clauses.append("review_mode_eligible_trusted_auto = TRUE")
    else:
        clauses.append("review_mode_eligible_all_universe = TRUE")

    if filters.funding_type == "emergency_response":
        clauses.append("COALESCE(emergency_flag, FALSE) = TRUE")
    elif filters.funding_type == "non_emergency_program":
        clauses.append("COALESCE(emergency_flag, FALSE) = FALSE")

    where_sql = " AND ".join(clauses)
    return (
        f"""
        WITH base_records AS (
            SELECT *
            FROM {FACT_VIEW}
            WHERE {where_sql}
        ),
        scope_years AS (
            SELECT GREATEST(COUNT(DISTINCT fiscal_year), 1)::numeric AS year_count
            FROM base_records
            WHERE fiscal_year IS NOT NULL
        ),
        scoped_records AS (
            SELECT
                base_records.*,
                CASE
                    WHEN :time_aggregation = 'multi_year_average'
                        THEN base_records.total_funding_amount / COALESCE(scope_years.year_count, 1::numeric)
                    ELSE base_records.total_funding_amount
                END AS scoped_total_funding_amount
            FROM base_records
            CROSS JOIN scope_years
        )
        """,
        params,
    )


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _compute_bins(values: list[float]) -> list[dict[str, Any]]:
    if not values:
        return []
    minimum = min(values)
    maximum = max(values)
    if minimum == maximum:
        return [{"min": minimum, "max": maximum, "colorIndex": 0, "label": str(round(minimum, 2))}]
    step = (maximum - minimum) / 5
    bins: list[dict[str, Any]] = []
    current_min = minimum
    for index in range(5):
        current_max = maximum if index == 4 else minimum + step * (index + 1)
        bins.append({"min": current_min, "max": current_max, "colorIndex": index})
        current_min = current_max
    return bins


def _metric_value(
    metric: str,
    *,
    total_amount: float | None,
    population: float | None,
    national_total: float | None,
) -> float | None:
    if metric == "total_funding":
        return total_amount
    if metric == "funding_per_capita":
        if total_amount is None or population in (None, 0):
            return None
        return total_amount / population
    if metric == "funding_per_100k":
        if total_amount is None or population in (None, 0):
            return None
        return (total_amount / population) * 100000
    if metric == "share_national":
        if total_amount is None or national_total in (None, 0):
            return None
        return (total_amount / national_total) * 100
    return None


def _timeframe_label(
    *,
    fiscal_year: int | None,
    min_fiscal_year: int | None,
    max_fiscal_year: int | None,
    time_aggregation: str,
) -> str:
    if fiscal_year is not None:
        return f"FY{fiscal_year}"
    if min_fiscal_year is None or max_fiscal_year is None:
        return "All Years"
    if min_fiscal_year == max_fiscal_year:
        return f"FY{min_fiscal_year}"
    if time_aggregation == "multi_year_average":
        return f"FY{min_fiscal_year}-FY{max_fiscal_year} Multi-Year Average"
    return f"FY{min_fiscal_year}-FY{max_fiscal_year}"


def _legend_title(*, metric: str, timeframe_label: str) -> str:
    return f"{timeframe_label} {VALID_METRICS[metric]}"


def _included_categories(filters: CanonicalFilters) -> list[str]:
    categories = ["regular_discretionary"]
    if filters.include_mandatory:
        categories.append("mandatory")
    if filters.include_emergency:
        categories.append("emergency_supplemental")
    if filters.include_supplemental:
        categories.append("other_supplemental")
    if filters.include_pphf:
        categories.append("pphf")
    if filters.include_transfers:
        categories.append("transfer")
    return categories


def _excluded_categories(filters: CanonicalFilters) -> list[str]:
    all_categories = ["mandatory", "emergency_supplemental", "other_supplemental", "pphf", "transfer"]
    return [category for category in all_categories if category not in _included_categories(filters)]


def _filter_context(
    filters: CanonicalFilters,
    *,
    min_fiscal_year: int | None,
    max_fiscal_year: int | None,
    total_included_rows: int,
) -> dict[str, Any]:
    timeframe_label = _timeframe_label(
        fiscal_year=filters.fiscal_year,
        min_fiscal_year=min_fiscal_year,
        max_fiscal_year=max_fiscal_year,
        time_aggregation=filters.time_aggregation,
    )
    return {
        "metric": filters.metric,
        "metric_label": VALID_METRICS[filters.metric],
        "funding_type": filters.funding_type,
        "funding_type_label": FUNDING_TYPE_LABELS.get(filters.funding_type, filters.funding_type),
        "funding_model": FUNDING_MODEL_KEY,
        "funding_model_label": FUNDING_MODEL_LABEL,
        "time_aggregation": filters.time_aggregation,
        "timeframe_label": timeframe_label,
        "legend_title": _legend_title(metric=filters.metric, timeframe_label=timeframe_label),
        "review_mode": filters.review_mode,
        "include_mandatory": filters.include_mandatory,
        "include_emergency": filters.include_emergency,
        "include_supplemental": filters.include_supplemental,
        "include_pphf": filters.include_pphf,
        "include_transfers": filters.include_transfers,
        "included_categories": _included_categories(filters),
        "excluded_categories": _excluded_categories(filters),
        "total_included_rows": total_included_rows,
        "model_version": MODEL_VERSION,
    }


def _funding_profile_payload(
    *,
    metric: str,
    total_amount: float | None,
    row_count: int,
    population: float | None,
    national_total: float | None,
    geography_type: str,
    geography_id: str,
    geography_name: str,
    state_code: str | None,
    timeframe_label: str,
) -> dict[str, Any]:
    metric_value = _metric_value(
        metric,
        total_amount=total_amount,
        population=population,
        national_total=national_total,
    )
    return {
        "geography_type": geography_type,
        "geography_id": geography_id,
        "geography_name": geography_name,
        "state_code": state_code,
        "state_name": geography_name if geography_type == "state" else None,
        "funding_mode_requested": FUNDING_MODEL_KEY,
        "funding_mode_effective": FUNDING_MODEL_KEY,
        "funding_mode_label": FUNDING_MODEL_LABEL,
        "total_funding": total_amount,
        "award_count": row_count,
        "population": population,
        "funding_per_capita": _metric_value(
            "funding_per_capita",
            total_amount=total_amount,
            population=population,
            national_total=national_total,
        ),
        "funding_per_100k": _metric_value(
            "funding_per_100k",
            total_amount=total_amount,
            population=population,
            national_total=national_total,
        ),
        "national_share": _metric_value(
            "share_national",
            total_amount=total_amount,
            population=population,
            national_total=national_total,
        ),
        "metric_value": metric_value,
        "timeframe_label": timeframe_label,
        "normalization_note": (
            "Canonical CDC funding uses budget-grounded rows when available and provisional profile-scope "
            "normalized rows for remaining coverage."
        ),
        "funding_model_version": MODEL_VERSION,
    }


def fetch_national_summary(
    db: Session,
    *,
    fiscal_year: int | None = None,
    metric: str | None = None,
    funding_type: str | None = None,
    time_aggregation: str | None = None,
    include_mandatory: bool | None = None,
    include_emergency: bool | None = None,
    include_supplemental: bool | None = None,
    include_pphf: bool | None = None,
    include_transfers: bool | None = None,
    review_mode: str | None = None,
) -> dict[str, Any]:
    _ensure_required_views(db)
    filters = _normalize_filters(
        fiscal_year=fiscal_year,
        metric=metric,
        funding_type=funding_type,
        geography_level="national",
        time_aggregation=time_aggregation,
        include_mandatory=include_mandatory,
        include_emergency=include_emergency,
        include_supplemental=include_supplemental,
        include_pphf=include_pphf,
        include_transfers=include_transfers,
        review_mode=review_mode,
    )
    cte_sql, params = _scoped_records_cte(filters)
    row = db.execute(
        text(
            f"""
            {cte_sql}
            SELECT
                COALESCE(SUM(scoped_total_funding_amount), 0)::numeric AS total_amount,
                COUNT(*)::integer AS row_count,
                MIN(fiscal_year) AS min_fiscal_year,
                MAX(fiscal_year) AS max_fiscal_year,
                pop.population::numeric AS population
            FROM scoped_records
            LEFT JOIN {POPULATION_VIEW_TABLE} AS pop
              ON pop.geography_type = 'national'
             AND pop.geography_id = 'US'
            GROUP BY pop.population
            """
        ),
        params,
    ).mappings().one_or_none()
    total_amount = _to_float(row.get("total_amount")) if row else 0.0
    population = _to_float(row.get("population")) if row else None
    row_count = int(row.get("row_count") or 0) if row else 0
    min_fiscal_year = int(row["min_fiscal_year"]) if row and row.get("min_fiscal_year") is not None else None
    max_fiscal_year = int(row["max_fiscal_year"]) if row and row.get("max_fiscal_year") is not None else None
    timeframe_label = _timeframe_label(
        fiscal_year=filters.fiscal_year,
        min_fiscal_year=min_fiscal_year,
        max_fiscal_year=max_fiscal_year,
        time_aggregation=filters.time_aggregation,
    )
    profile = _funding_profile_payload(
        metric=filters.metric,
        total_amount=total_amount,
        row_count=row_count,
        population=population,
        national_total=total_amount,
        geography_type="national",
        geography_id="US",
        geography_name="United States",
        state_code=None,
        timeframe_label=timeframe_label,
    )
    return {
        "funding_profile": profile,
        "funding_mode_requested": FUNDING_MODEL_KEY,
        "funding_mode_effective": FUNDING_MODEL_KEY,
        "funding_mode_label": FUNDING_MODEL_LABEL,
        "total_funding_amount": total_amount,
        "funding_per_capita": profile["funding_per_capita"],
        "funding_per_100k": profile["funding_per_100k"],
        "share_national_pct": profile["national_share"],
        "population": population,
        "metadata": _filter_context(
            filters,
            min_fiscal_year=min_fiscal_year,
            max_fiscal_year=max_fiscal_year,
            total_included_rows=row_count,
        )
        | {
            "min_fiscal_year": min_fiscal_year,
            "max_fiscal_year": max_fiscal_year,
        },
    }


def _build_meta(
    db: Session,
    filters: CanonicalFilters,
    *,
    min_fiscal_year: int | None,
    max_fiscal_year: int | None,
    total_included_rows: int,
    geography_level: str,
) -> dict[str, Any]:
    national_summary = fetch_national_summary(
        db,
        fiscal_year=filters.fiscal_year,
        metric=filters.metric,
        funding_type=filters.funding_type,
        time_aggregation=filters.time_aggregation,
        include_mandatory=filters.include_mandatory,
        include_emergency=filters.include_emergency,
        include_supplemental=filters.include_supplemental,
        include_pphf=filters.include_pphf,
        include_transfers=filters.include_transfers,
        review_mode=filters.review_mode,
    )
    return {
        "note": (
            "Canonical CDC funding unifies budget-grounded rows with provisional profile-scope "
            "rows and excludes non-canonical rows before aggregation."
        ),
        "legend_title": _legend_title(
            metric=filters.metric,
            timeframe_label=_timeframe_label(
                fiscal_year=filters.fiscal_year,
                min_fiscal_year=min_fiscal_year,
                max_fiscal_year=max_fiscal_year,
                time_aggregation=filters.time_aggregation,
            ),
        ),
        "filter_context": _filter_context(
            filters,
            min_fiscal_year=min_fiscal_year,
            max_fiscal_year=max_fiscal_year,
            total_included_rows=total_included_rows,
        ),
        "funding_mode_requested": FUNDING_MODEL_KEY,
        "funding_mode_requested_label": FUNDING_MODEL_LABEL,
        "funding_mode_effective": FUNDING_MODEL_KEY,
        "funding_mode_label": FUNDING_MODEL_LABEL,
        "national_summary": national_summary,
        "geography_level": geography_level,
    }


def _build_note(*notes: str | None) -> str:
    filtered = [str(note).strip() for note in notes if str(note or "").strip()]
    return " ".join(filtered)


def _row_metric_value(filters: CanonicalFilters, row: dict[str, Any]) -> float | None:
    return _metric_value(
        filters.metric,
        total_amount=_to_float(row.get("total_amount")),
        population=_to_float(row.get("population")),
        national_total=_to_float(row.get("national_total")),
    )


def _fetch_national_feature(
    db: Session,
    filters: CanonicalFilters,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    summary = fetch_national_summary(
        db,
        fiscal_year=filters.fiscal_year,
        metric=filters.metric,
        funding_type=filters.funding_type,
        time_aggregation=filters.time_aggregation,
        include_mandatory=filters.include_mandatory,
        include_emergency=filters.include_emergency,
        include_supplemental=filters.include_supplemental,
        include_pphf=filters.include_pphf,
        include_transfers=filters.include_transfers,
        review_mode=filters.review_mode,
    )
    profile = summary["funding_profile"]
    row = db.execute(
        text(
            f"""
            SELECT
                ST_AsGeoJSON(
                    ST_SimplifyPreserveTopology(
                        ST_UnaryUnion(ST_Collect(geom)),
                        :simplify_degrees
                    ),
                    6
                )::json AS geometry
            FROM {STATE_BOUNDARY_TABLE}
            WHERE geom IS NOT NULL
            """
        ),
        {"simplify_degrees": STATE_SIMPLIFY_DEGREES},
    ).mappings().one()
    total_amount = _to_float(summary.get("total_funding_amount"))
    feature = {
        "type": "Feature",
        "geometry": row.get("geometry"),
        "properties": {
            "id": "US",
            "name": "United States",
            "state_code": None,
            "state_abbr": None,
            "state_name": None,
            "geo_level": "national",
            "metric": filters.metric,
            "metric_label": VALID_METRICS[filters.metric],
            "value": profile.get("metric_value"),
            "total_funding_amount": total_amount,
            "funding_per_capita": profile.get("funding_per_capita"),
            "funding_per_100k": profile.get("funding_per_100k"),
            "share_national_pct": profile.get("national_share"),
            "population": _to_float(summary.get("population")),
            "funding_mode_effective": FUNDING_MODEL_KEY,
            "funding_mode_label": FUNDING_MODEL_LABEL,
            "funding_profile": profile,
            "metric_context": summary.get("metadata", {}),
        },
    }
    summary_metadata = summary.get("metadata", {})
    meta_context = {
        "min_fiscal_year": (
            int(summary_metadata["min_fiscal_year"])
            if summary_metadata.get("min_fiscal_year") is not None
            else None
        ),
        "max_fiscal_year": (
            int(summary_metadata["max_fiscal_year"])
            if summary_metadata.get("max_fiscal_year") is not None
            else None
        ),
        "total_included_rows": int(summary_metadata.get("total_included_rows") or 0),
    }
    return [feature], meta_context


def _fetch_geography_rows(
    db: Session,
    filters: CanonicalFilters,
    *,
    bbox: str | None,
    limit: int,
    include_geometry: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any], NormalizedBbox]:
    bbox_ctx = _normalize_bbox(bbox, geography_level=filters.geography_level)
    cte_sql, params = _scoped_records_cte(filters)
    if filters.geography_level == "state":
        geometry_sql = (
            "ST_AsGeoJSON(ST_SimplifyPreserveTopology(sb.geom, :simplify_degrees), 6)::json AS geometry"
            if include_geometry
            else "NULL::json AS geometry"
        )
        bbox_clause = (
            " AND sb.geom && ST_MakeEnvelope(:bbox_west, :bbox_south, :bbox_east, :bbox_north, 4326)"
            if bbox_ctx.applied
            else ""
        )
        rows = db.execute(
            text(
                f"""
                {cte_sql},
                national_total AS (
                    SELECT COALESCE(SUM(scoped_total_funding_amount), 0)::numeric AS national_total
                    FROM scoped_records
                ),
                aggregated AS (
                    SELECT
                        state_abbr AS state_code,
                        MAX(state_name) AS state_name,
                        COALESCE(SUM(scoped_total_funding_amount), 0)::numeric AS total_amount,
                        COUNT(*)::integer AS row_count
                    FROM scoped_records
                    WHERE state_abbr IS NOT NULL
                    GROUP BY state_abbr
                ),
                overall AS (
                    SELECT
                        COUNT(*)::integer AS total_included_rows,
                        MIN(fiscal_year) AS min_fiscal_year,
                        MAX(fiscal_year) AS max_fiscal_year
                    FROM scoped_records
                )
                SELECT
                    sb.state_abbr AS geography_id,
                    sb.state_name AS geography_name,
                    sb.state_abbr AS state_code,
                    sb.state_name AS state_name,
                    aggregated.total_amount,
                    aggregated.row_count,
                    pop.population::numeric AS population,
                    national_total.national_total,
                    overall.total_included_rows,
                    overall.min_fiscal_year,
                    overall.max_fiscal_year,
                    {geometry_sql}
                FROM {STATE_BOUNDARY_TABLE} AS sb
                LEFT JOIN aggregated
                  ON aggregated.state_code = sb.state_abbr
                LEFT JOIN {POPULATION_VIEW_TABLE} AS pop
                  ON pop.geography_type = 'state'
                 AND pop.geography_id = sb.state_abbr
                CROSS JOIN national_total
                CROSS JOIN overall
                WHERE sb.geom IS NOT NULL{bbox_clause}
                ORDER BY sb.state_abbr
                LIMIT :limit
                """
            ),
            params
            | {
                "limit": limit,
                "simplify_degrees": STATE_SIMPLIFY_DEGREES,
            }
            | (
                {
                    "bbox_west": bbox_ctx.west,
                    "bbox_south": bbox_ctx.south,
                    "bbox_east": bbox_ctx.east,
                    "bbox_north": bbox_ctx.north,
                }
                if bbox_ctx.applied
                else {}
            ),
        ).mappings().all()
        meta_context = {
            "min_fiscal_year": int(rows[0]["min_fiscal_year"]) if rows and rows[0].get("min_fiscal_year") is not None else None,
            "max_fiscal_year": int(rows[0]["max_fiscal_year"]) if rows and rows[0].get("max_fiscal_year") is not None else None,
            "total_included_rows": int(rows[0].get("total_included_rows") or 0) if rows else 0,
        }
        return rows, meta_context, bbox_ctx

    geometry_sql = (
        "ST_AsGeoJSON(ST_SimplifyPreserveTopology(boundary.geom, :simplify_degrees), 6)::json AS geometry"
        if include_geometry
        else "NULL::json AS geometry"
    )
    bbox_clause = (
        " AND boundary.geom && ST_MakeEnvelope(:bbox_west, :bbox_south, :bbox_east, :bbox_north, 4326)"
        if bbox_ctx.applied
        else ""
    )
    rows = db.execute(
        text(
            f"""
            {cte_sql},
            county_records AS (
                SELECT *
                FROM scoped_records
                WHERE geography_type = 'county'
                  AND county_fips IS NOT NULL
            ),
            national_total AS (
                SELECT COALESCE(SUM(scoped_total_funding_amount), 0)::numeric AS national_total
                FROM county_records
            ),
            aggregated AS (
                SELECT
                    county_fips AS county_fips,
                    state_abbr AS state_code,
                    MAX(county_name) AS county_name,
                    COALESCE(SUM(scoped_total_funding_amount), 0)::numeric AS total_amount,
                    COUNT(*)::integer AS row_count
                FROM county_records
                GROUP BY county_fips, state_abbr
            ),
            overall AS (
                SELECT
                    COUNT(*)::integer AS total_included_rows,
                    MIN(fiscal_year) AS min_fiscal_year,
                    MAX(fiscal_year) AS max_fiscal_year
                FROM county_records
            )
            SELECT
                boundary.geoid AS geography_id,
                COALESCE(county.county_name, boundary.name) AS geography_name,
                county.state_abbr AS state_code,
                county.state_desc AS state_name,
                aggregated.total_amount,
                aggregated.row_count,
                pop.population::numeric AS population,
                national_total.national_total,
                overall.total_included_rows,
                overall.min_fiscal_year,
                overall.max_fiscal_year,
                {geometry_sql}
            FROM {COUNTY_BOUNDARY_TABLE} AS boundary
            LEFT JOIN {COUNTY_DIM_TABLE} AS county
              ON county.location_id = boundary.location_id
            LEFT JOIN aggregated
              ON aggregated.county_fips = boundary.geoid
            LEFT JOIN {POPULATION_VIEW_TABLE} AS pop
              ON pop.geography_type = 'county'
             AND pop.geography_id = boundary.geoid
            CROSS JOIN national_total
            CROSS JOIN overall
            WHERE boundary.geom IS NOT NULL{bbox_clause}
            ORDER BY boundary.geoid
            LIMIT :limit
            """
        ),
        params
        | {
            "limit": limit,
            "simplify_degrees": COUNTY_SIMPLIFY_DEGREES,
        }
        | (
            {
                "bbox_west": bbox_ctx.west,
                "bbox_south": bbox_ctx.south,
                "bbox_east": bbox_ctx.east,
                "bbox_north": bbox_ctx.north,
            }
            if bbox_ctx.applied
            else {}
        ),
    ).mappings().all()
    meta_context = {
        "min_fiscal_year": int(rows[0]["min_fiscal_year"]) if rows and rows[0].get("min_fiscal_year") is not None else None,
        "max_fiscal_year": int(rows[0]["max_fiscal_year"]) if rows and rows[0].get("max_fiscal_year") is not None else None,
        "total_included_rows": int(rows[0].get("total_included_rows") or 0) if rows else 0,
    }
    return rows, meta_context, bbox_ctx


def fetch_map_geojson(
    db: Session,
    *,
    fiscal_year: int | None = None,
    metric: str | None = None,
    funding_type: str | None = None,
    geography_level: str | None = None,
    time_aggregation: str | None = None,
    include_mandatory: bool | None = None,
    include_emergency: bool | None = None,
    include_supplemental: bool | None = None,
    include_pphf: bool | None = None,
    include_transfers: bool | None = None,
    review_mode: str | None = None,
    bbox: str | None = None,
    limit: int = 6000,
) -> dict[str, Any]:
    _ensure_required_views(db)
    filters = _normalize_filters(
        fiscal_year=fiscal_year,
        metric=metric,
        funding_type=funding_type,
        geography_level=geography_level,
        time_aggregation=time_aggregation,
        include_mandatory=include_mandatory,
        include_emergency=include_emergency,
        include_supplemental=include_supplemental,
        include_pphf=include_pphf,
        include_transfers=include_transfers,
        review_mode=review_mode,
    )
    bbox_ctx = _normalize_bbox(bbox, geography_level=filters.geography_level)
    if filters.geography_level == "national":
        features, meta_context = _fetch_national_feature(db, filters)
        mapped_geographies = sum(1 for feature in features if feature.get("properties", {}).get("value") is not None)
        meta = _build_meta(
            db,
            filters,
            min_fiscal_year=meta_context["min_fiscal_year"],
            max_fiscal_year=meta_context["max_fiscal_year"],
            total_included_rows=meta_context["total_included_rows"],
            geography_level="national",
        )
        meta["note"] = _build_note(meta.get("note"), bbox_ctx.ignored_reason)
        return {
            "type": "FeatureCollection",
            "features": features,
            "meta": meta
            | {
                "mapped_geographies": mapped_geographies,
                "no_data_count": max(len(features) - mapped_geographies, 0),
            },
        }
    rows, meta_context, bbox_ctx = _fetch_geography_rows(
        db,
        filters,
        bbox=bbox,
        limit=limit,
        include_geometry=True,
    )

    features: list[dict[str, Any]] = []
    for row in rows:
        total_amount = _to_float(row.get("total_amount"))
        population = _to_float(row.get("population"))
        national_total = _to_float(row.get("national_total"))
        timeframe_label = _timeframe_label(
            fiscal_year=filters.fiscal_year,
            min_fiscal_year=meta_context["min_fiscal_year"],
            max_fiscal_year=meta_context["max_fiscal_year"],
            time_aggregation=filters.time_aggregation,
        )
        profile = _funding_profile_payload(
            metric=filters.metric,
            total_amount=total_amount,
            row_count=int(row.get("row_count") or 0),
            population=population,
            national_total=national_total,
            geography_type=filters.geography_level,
            geography_id=str(row.get("geography_id") or ""),
            geography_name=str(row.get("geography_name") or ""),
            state_code=str(row.get("state_code") or "").strip() or None,
            timeframe_label=timeframe_label,
        )
        features.append(
            {
                "type": "Feature",
                "geometry": row.get("geometry"),
                "properties": {
                    "id": row.get("geography_id"),
                    "name": row.get("geography_name"),
                    "state_code": row.get("state_code"),
                    "state_abbr": row.get("state_code"),
                    "state_name": row.get("state_name"),
                    "geo_level": filters.geography_level,
                    "metric": filters.metric,
                    "metric_label": VALID_METRICS[filters.metric],
                    "value": profile["metric_value"],
                    "total_funding_amount": total_amount,
                    "funding_per_capita": profile["funding_per_capita"],
                    "funding_per_100k": profile["funding_per_100k"],
                    "share_national_pct": profile["national_share"],
                    "population": population,
                    "funding_mode_effective": FUNDING_MODEL_KEY,
                    "funding_mode_label": FUNDING_MODEL_LABEL,
                    "funding_profile": profile,
                    "metric_context": _filter_context(
                        filters,
                        min_fiscal_year=meta_context["min_fiscal_year"],
                        max_fiscal_year=meta_context["max_fiscal_year"],
                        total_included_rows=meta_context["total_included_rows"],
                    ),
                },
            }
        )
    mapped_geographies = sum(1 for feature in features if feature.get("properties", {}).get("value") is not None)
    meta = _build_meta(
        db,
        filters,
        min_fiscal_year=meta_context["min_fiscal_year"],
        max_fiscal_year=meta_context["max_fiscal_year"],
        total_included_rows=meta_context["total_included_rows"],
        geography_level=filters.geography_level,
    )
    meta["note"] = _build_note(meta.get("note"), bbox_ctx.ignored_reason)
    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": meta
        | {
            "mapped_geographies": mapped_geographies,
            "no_data_count": max(len(features) - mapped_geographies, 0),
        },
    }


def fetch_legend_stats(
    db: Session,
    *,
    fiscal_year: int | None = None,
    metric: str | None = None,
    funding_type: str | None = None,
    geography_level: str | None = None,
    time_aggregation: str | None = None,
    include_mandatory: bool | None = None,
    include_emergency: bool | None = None,
    include_supplemental: bool | None = None,
    include_pphf: bool | None = None,
    include_transfers: bool | None = None,
    review_mode: str | None = None,
    bbox: str | None = None,
) -> dict[str, Any]:
    _ensure_required_views(db)
    filters = _normalize_filters(
        fiscal_year=fiscal_year,
        metric=metric,
        funding_type=funding_type,
        geography_level=geography_level,
        time_aggregation=time_aggregation,
        include_mandatory=include_mandatory,
        include_emergency=include_emergency,
        include_supplemental=include_supplemental,
        include_pphf=include_pphf,
        include_transfers=include_transfers,
        review_mode=review_mode,
    )
    bbox_ctx = _normalize_bbox(bbox, geography_level=filters.geography_level)
    values: list[float] = []
    row_count = 0
    if filters.geography_level == "national":
        summary = fetch_national_summary(
            db,
            fiscal_year=filters.fiscal_year,
            metric=filters.metric,
            funding_type=filters.funding_type,
            time_aggregation=filters.time_aggregation,
            include_mandatory=filters.include_mandatory,
            include_emergency=filters.include_emergency,
            include_supplemental=filters.include_supplemental,
            include_pphf=filters.include_pphf,
            include_transfers=filters.include_transfers,
            review_mode=filters.review_mode,
        )
        profile = summary.get("funding_profile", {})
        metric_value = profile.get("metric_value")
        if metric_value is not None and math.isfinite(float(metric_value)):
            values.append(float(metric_value))
        metadata = summary.get("metadata", {})
        meta_context = {
            "min_fiscal_year": (
                int(metadata["min_fiscal_year"])
                if metadata.get("min_fiscal_year") is not None
                else None
            ),
            "max_fiscal_year": (
                int(metadata["max_fiscal_year"])
                if metadata.get("max_fiscal_year") is not None
                else None
            ),
            "total_included_rows": int(metadata.get("total_included_rows") or 0),
        }
        row_count = 1
    else:
        rows, meta_context, bbox_ctx = _fetch_geography_rows(
            db,
            filters,
            bbox=bbox,
            limit=7000,
            include_geometry=False,
        )
        row_count = len(rows)
        for row in rows:
            metric_value = _row_metric_value(filters, row)
            if metric_value is not None and math.isfinite(float(metric_value)):
                values.append(float(metric_value))
    meta = _build_meta(
        db,
        filters,
        min_fiscal_year=meta_context["min_fiscal_year"],
        max_fiscal_year=meta_context["max_fiscal_year"],
        total_included_rows=meta_context["total_included_rows"],
        geography_level=filters.geography_level,
    )
    note = _build_note(meta.get("note"), bbox_ctx.ignored_reason)
    return {
        "metric": filters.metric,
        "metric_label": VALID_METRICS[filters.metric],
        "funding_mode_requested": FUNDING_MODEL_KEY,
        "funding_mode_requested_label": FUNDING_MODEL_LABEL,
        "funding_mode_effective": FUNDING_MODEL_KEY,
        "funding_mode_label": FUNDING_MODEL_LABEL,
        "geography_level": filters.geography_level,
        "time_aggregation": filters.time_aggregation,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "bins": _compute_bins(values),
        "mapped_geographies": len(values),
        "n": len(values),
        "noDataCount": max(row_count - len(values), 0),
        "legend_title": meta["legend_title"],
        "filter_context": meta["filter_context"],
        "note": note,
        "national_summary": meta["national_summary"],
    }


def fetch_state_profile_overview(
    db: Session,
    *,
    state: str,
    fiscal_year: int | None = None,
    metric: str | None = None,
    funding_type: str | None = None,
    time_aggregation: str | None = None,
    include_mandatory: bool | None = None,
    include_emergency: bool | None = None,
    include_supplemental: bool | None = None,
    include_pphf: bool | None = None,
    include_transfers: bool | None = None,
    review_mode: str | None = None,
) -> dict[str, Any]:
    _ensure_required_views(db)
    state_code = str(state or "").strip().upper()
    if len(state_code) != 2:
        raise HTTPException(status_code=400, detail="state must be a valid 2-letter state code")
    filters = _normalize_filters(
        fiscal_year=fiscal_year,
        metric=metric,
        funding_type=funding_type,
        geography_level="state",
        time_aggregation=time_aggregation,
        include_mandatory=include_mandatory,
        include_emergency=include_emergency,
        include_supplemental=include_supplemental,
        include_pphf=include_pphf,
        include_transfers=include_transfers,
        review_mode=review_mode,
    )
    cte_sql, params = _scoped_records_cte(filters, state=state_code)
    totals_row = db.execute(
        text(
            f"""
            {cte_sql},
            national_total AS (
                SELECT COALESCE(SUM(scoped_total_funding_amount), 0)::numeric AS national_total
                FROM scoped_records
            )
            SELECT
                COALESCE(SUM(scoped_total_funding_amount), 0)::numeric AS total_amount,
                COUNT(*)::integer AS row_count,
                MAX(state_name) AS state_name,
                MIN(fiscal_year) AS min_fiscal_year,
                MAX(fiscal_year) AS max_fiscal_year,
                pop.population::numeric AS population,
                national_total.national_total
            FROM scoped_records
            LEFT JOIN {POPULATION_VIEW_TABLE} AS pop
              ON pop.geography_type = 'state'
             AND pop.geography_id = :state_code
            CROSS JOIN national_total
            GROUP BY pop.population, national_total.national_total
            """
        ),
        params | {"state_code": state_code},
    ).mappings().one_or_none()
    total_amount = _to_float(totals_row.get("total_amount")) if totals_row else 0.0
    row_count = int(totals_row.get("row_count") or 0) if totals_row else 0
    state_name = str(totals_row.get("state_name") or state_code) if totals_row else state_code
    population = _to_float(totals_row.get("population")) if totals_row else None
    national_total = _to_float(totals_row.get("national_total")) if totals_row else None
    min_fiscal_year = int(totals_row["min_fiscal_year"]) if totals_row and totals_row.get("min_fiscal_year") is not None else None
    max_fiscal_year = int(totals_row["max_fiscal_year"]) if totals_row and totals_row.get("max_fiscal_year") is not None else None
    timeframe_label = _timeframe_label(
        fiscal_year=filters.fiscal_year,
        min_fiscal_year=min_fiscal_year,
        max_fiscal_year=max_fiscal_year,
        time_aggregation=filters.time_aggregation,
    )
    profile = _funding_profile_payload(
        metric=filters.metric,
        total_amount=total_amount,
        row_count=row_count,
        population=population,
        national_total=national_total,
        geography_type="state",
        geography_id=state_code,
        geography_name=state_name,
        state_code=state_code,
        timeframe_label=timeframe_label,
    )
    categories = db.execute(
        text(
            f"""
            {cte_sql},
            totals AS (
                SELECT COALESCE(SUM(scoped_total_funding_amount), 0)::numeric AS total_amount
                FROM scoped_records
            )
            SELECT
                COALESCE(NULLIF(category_label, ''), 'Unclassified') AS category,
                COALESCE(SUM(scoped_total_funding_amount), 0)::numeric AS amount,
                COUNT(*)::integer AS row_count,
                COUNT(DISTINCT COALESCE(NULLIF(subcategory_label, ''), 'Unclassified'))::integer AS subcategory_count,
                CASE
                    WHEN totals.total_amount = 0 THEN NULL
                    ELSE (SUM(scoped_total_funding_amount) / totals.total_amount) * 100
                END AS share_pct
            FROM scoped_records
            CROSS JOIN totals
            GROUP BY COALESCE(NULLIF(category_label, ''), 'Unclassified'), totals.total_amount
            ORDER BY amount DESC, category ASC
            """
        ),
        params,
    ).mappings().all()
    subcategories = db.execute(
        text(
            f"""
            {cte_sql},
            state_totals AS (
                SELECT COALESCE(SUM(scoped_total_funding_amount), 0)::numeric AS state_total
                FROM scoped_records
            ),
            category_totals AS (
                SELECT
                    COALESCE(NULLIF(category_label, ''), 'Unclassified') AS category,
                    COALESCE(SUM(scoped_total_funding_amount), 0)::numeric AS category_total
                FROM scoped_records
                GROUP BY COALESCE(NULLIF(category_label, ''), 'Unclassified')
            )
            SELECT
                category_totals.category AS category,
                COALESCE(NULLIF(scoped_records.subcategory_label, ''), 'Unclassified') AS subcategory,
                COALESCE(SUM(scoped_records.scoped_total_funding_amount), 0)::numeric AS amount,
                COUNT(*)::integer AS row_count,
                CASE
                    WHEN state_totals.state_total = 0 THEN NULL
                    ELSE (SUM(scoped_records.scoped_total_funding_amount) / state_totals.state_total) * 100
                END AS share_total_pct,
                CASE
                    WHEN category_totals.category_total = 0 THEN NULL
                    ELSE (SUM(scoped_records.scoped_total_funding_amount) / category_totals.category_total) * 100
                END AS share_category_pct
            FROM scoped_records
            CROSS JOIN state_totals
            INNER JOIN category_totals
              ON category_totals.category = COALESCE(NULLIF(scoped_records.category_label, ''), 'Unclassified')
            GROUP BY category_totals.category, COALESCE(NULLIF(scoped_records.subcategory_label, ''), 'Unclassified'), state_totals.state_total, category_totals.category_total
            ORDER BY amount DESC, category ASC, subcategory ASC
            """
        ),
        params,
    ).mappings().all()
    filter_context = _filter_context(
        filters,
        min_fiscal_year=min_fiscal_year,
        max_fiscal_year=max_fiscal_year,
        total_included_rows=row_count,
    )
    summary = {
        "state_code": state_code,
        "state_name": state_name,
        "total_funding": total_amount,
        "population": population,
        "funding_per_capita": profile["funding_per_capita"],
        "award_count": row_count,
        "contract_award_count": 0,
        "timeframe_label": timeframe_label,
        "selected_metric": filters.metric,
        "selected_metric_label": VALID_METRICS[filters.metric],
        "selected_metric_value": profile["metric_value"],
        "legend_title": filter_context["legend_title"],
        "funding_mode_effective": FUNDING_MODEL_KEY,
        "funding_mode_label": FUNDING_MODEL_LABEL,
        "normalization_note": (
            "Canonical totals use budget-grounded rows when available and provisional profile-scope "
            "rows elsewhere under the same filter state."
        ),
        "filter_context": filter_context,
        "grouping": {
            "category_label": "Appropriation Category",
            "subcategory_label": "Budget / Program",
            "count_label": "Canonical funding rows",
            "subcategory_count_label": "Subcategories",
            "category_method": "Categories come from canonical appropriation buckets shared across budget-grounded and provisional rows.",
            "subcategory_method": "Subcategories use budget-program labels when grounded and provisional funding-scope labels otherwise.",
        },
        "methodology_notes": [
            "Budget-grounded rows remain authoritative where accepted scope anchors exist.",
            "Provisional profile-scope normalized rows backfill years and awards without budget-grounded coverage.",
            "The canonical layer excludes non-canonical rows before aggregation so the frontend never deduplicates.",
        ],
        "profile": profile | {"metadata": {"metric_context": filter_context}},
        "metadata": filter_context,
    }
    return {
        "summary": summary,
        "categories": {
            "rows": [
                {
                    **row,
                    "amount": _to_float(row.get("amount")),
                    "share_pct": _to_float(row.get("share_pct")),
                }
                for row in categories
            ],
            "grouping": summary["grouping"],
            "profile": profile | {"metadata": {"metric_context": filter_context}},
            "metadata": filter_context,
        },
        "subcategories": {
            "rows": [
                {
                    **row,
                    "amount": _to_float(row.get("amount")),
                    "share_total_pct": _to_float(row.get("share_total_pct")),
                    "share_category_pct": _to_float(row.get("share_category_pct")),
                }
                for row in subcategories
            ],
            "grouping": summary["grouping"],
            "profile": profile | {"metadata": {"metric_context": filter_context}},
            "metadata": filter_context,
        },
    }


def fetch_state_profile_details(
    db: Session,
    *,
    state: str,
    fiscal_year: int | None = None,
    funding_type: str | None = None,
    time_aggregation: str | None = None,
    include_mandatory: bool | None = None,
    include_emergency: bool | None = None,
    include_supplemental: bool | None = None,
    include_pphf: bool | None = None,
    include_transfers: bool | None = None,
    review_mode: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "amount",
    sort_dir: str = "desc",
) -> dict[str, Any]:
    _ensure_required_views(db)
    state_code = str(state or "").strip().upper()
    if len(state_code) != 2:
        raise HTTPException(status_code=400, detail="state must be a valid 2-letter state code")
    filters = _normalize_filters(
        fiscal_year=fiscal_year,
        metric="total_funding",
        funding_type=funding_type,
        geography_level="state",
        time_aggregation=time_aggregation,
        include_mandatory=include_mandatory,
        include_emergency=include_emergency,
        include_supplemental=include_supplemental,
        include_pphf=include_pphf,
        include_transfers=include_transfers,
        review_mode=review_mode,
    )
    safe_sort_by = {
        "category": "category_label",
        "subcategory": "subcategory_label",
        "grantee_name": "recipient_name",
        "amount": "scoped_total_funding_amount",
        "latest_action_date": "latest_action_date",
    }.get(str(sort_by or "amount").strip().lower(), "scoped_total_funding_amount")
    safe_sort_dir = "asc" if str(sort_dir or "desc").strip().lower() == "asc" else "desc"
    offset = max(int(page) - 1, 0) * int(page_size)
    cte_sql, params = _scoped_records_cte(filters, state=state_code)
    query_token = str(q or "").strip().lower()
    where_sql = ""
    if query_token:
        params["q"] = f"%{query_token}%"
        where_sql = (
            "WHERE ("
            "LOWER(COALESCE(category_label, '')) LIKE :q OR "
            "LOWER(COALESCE(subcategory_label, '')) LIKE :q OR "
            "LOWER(COALESCE(project_title, '')) LIKE :q OR "
            "LOWER(COALESCE(recipient_name, '')) LIKE :q OR "
            "LOWER(COALESCE(source_record_id, '')) LIKE :q OR "
            "LOWER(COALESCE(budget_anchor_id, '')) LIKE :q"
            ")"
        )
    rows = db.execute(
        text(
            f"""
            {cte_sql}
            SELECT
                canonical_row_id AS record_id,
                record_type,
                source_parent_record_id AS fain,
                COALESCE(NULLIF(category_label, ''), 'Unclassified') AS category,
                COALESCE(NULLIF(subcategory_label, ''), 'Unclassified') AS subcategory,
                project_title,
                recipient_name AS grantee_name,
                NULL::text AS city,
                county_name AS county,
                scoped_total_funding_amount::numeric AS amount,
                fiscal_year AS min_fiscal_year,
                fiscal_year AS max_fiscal_year,
                latest_action_date,
                state_name,
                state_abbr AS state_code,
                usaspending_permalink,
                budget_anchor_id,
                appropriation_category,
                source_system AS system_name,
                source_record_id,
                analyst_reviewed,
                trusted_auto_seed_flag,
                classification_basis
            FROM scoped_records
            {where_sql}
            ORDER BY {safe_sort_by} {safe_sort_dir.upper()} NULLS LAST, canonical_row_id ASC
            LIMIT :limit
            OFFSET :offset
            """
        ),
        params | {"limit": page_size, "offset": offset},
    ).mappings().all()
    totals_row = db.execute(
        text(
            f"""
            {cte_sql}
            SELECT
                COUNT(*)::integer AS total_rows,
                MIN(fiscal_year) AS min_fiscal_year,
                MAX(fiscal_year) AS max_fiscal_year
            FROM scoped_records
            {where_sql}
            """
        ),
        params,
    ).mappings().one()
    total_rows = int(totals_row.get("total_rows") or 0)
    min_fiscal_year = int(totals_row["min_fiscal_year"]) if totals_row.get("min_fiscal_year") is not None else None
    max_fiscal_year = int(totals_row["max_fiscal_year"]) if totals_row.get("max_fiscal_year") is not None else None
    return {
        "basis": "canonical",
        "state_code": state_code,
        "funding_geography_mode": "recipient_location",
        "q": query_token or None,
        "page": int(page),
        "page_size": int(page_size),
        "sort_by": safe_sort_by,
        "sort_dir": safe_sort_dir,
        "total_rows": total_rows,
        "funding_mode_label": FUNDING_MODEL_LABEL,
        "funding_mode_effective": FUNDING_MODEL_KEY,
        "metadata": _filter_context(
            filters,
            min_fiscal_year=min_fiscal_year,
            max_fiscal_year=max_fiscal_year,
            total_included_rows=total_rows,
        ),
        "rows": [
            {
                "line_number": offset + index,
                "record_id": row.get("record_id"),
                "record_type": row.get("record_type"),
                "fain": row.get("fain"),
                "category": row.get("category"),
                "subcategory": row.get("subcategory"),
                "project_title": row.get("project_title"),
                "grantee_name": row.get("grantee_name"),
                "city": row.get("city"),
                "county": row.get("county"),
                "amount": _to_float(row.get("amount")),
                "min_fiscal_year": row.get("min_fiscal_year"),
                "max_fiscal_year": row.get("max_fiscal_year"),
                "latest_action_date": row.get("latest_action_date"),
                "state_name": row.get("state_name"),
                "state_code": row.get("state_code"),
                "usaspending_permalink": row.get("usaspending_permalink"),
                "budget_anchor_id": row.get("budget_anchor_id"),
                "appropriation_category": row.get("appropriation_category"),
                "system_name": row.get("system_name"),
                "source_record_id": row.get("source_record_id"),
                "analyst_reviewed": row.get("analyst_reviewed"),
                "trusted_auto_seed_flag": row.get("trusted_auto_seed_flag"),
                "classification_basis": row.get("classification_basis"),
            }
            for index, row in enumerate(rows, start=1)
        ],
    }
