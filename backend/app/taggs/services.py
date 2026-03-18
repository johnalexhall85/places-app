from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass
from decimal import Decimal
from numbers import Real
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db_fqtn import places_table, taggs_table
from app.recon.normalization import (
    build_normalization_note,
    fetch_state_normalization_lookup,
    taggs_normalization_compatibility,
)
from app.recon.profile_calibration import METHODOLOGY_VERSION as PROFILE_CALIBRATION_METHODOLOGY_VERSION

AWARD_SUMMARY_TABLE = taggs_table("award_funding_summary")
STATE_SUMMARY_TABLE = taggs_table("state_funding_summary")
CAN_CLASSIFICATION_TABLE = taggs_table("can_classification")
STATE_BOUNDARY_TABLE = places_table("dim_state_boundary")
POPULATION_VIEW_TABLE = places_table("v_geography_population")

VALID_METRICS = {
    "total_funding",
    "funding_per_capita",
    "award_count",
    "unique_recipient_count",
}

METRIC_OPTIONS = [
    {"value": "total_funding", "label": "Total funding"},
    {"value": "funding_per_capita", "label": "Funding per capita"},
    {"value": "award_count", "label": "Award count"},
    {"value": "unique_recipient_count", "label": "Unique recipient count"},
]

METRIC_LABELS = {
    "total_funding": "Total TAGGS funding actions",
    "funding_per_capita": "TAGGS funding actions per capita",
    "award_count": "Distinct TAGGS awards",
    "unique_recipient_count": "Unique TAGGS recipients",
}

METRIC_LEGEND_TEXT = {
    "total_funding": "Total TAGGS funding actions recorded for this state",
    "funding_per_capita": "TAGGS funding actions per resident for this state",
    "award_count": "Distinct awards recorded for this state",
    "unique_recipient_count": "Unique recipients recorded for this state",
}

VALID_DETAIL_SORT_FIELDS = {
    "line_number": "award_number",
    "amount": "amount",
    "category": "category",
    "subcategory": "subcategory",
    "award_title": "award_title",
    "recipient_name": "recipient_name",
    "award_number": "award_number",
    "aln": "aln",
    "can_code": "can_code",
    "funding_stream": "funding_stream",
}

VALID_SORT_DIRECTIONS = {"asc", "desc"}

UNKNOWN_COUNTY_LABEL = "Undefined / Unspecified county"
UNKNOWN_CATEGORY_LABEL = "Unspecified Category"
UNKNOWN_SUBCATEGORY_LABEL = "Unspecified Sub-Category"
UNKNOWN_RECIPIENT_LABEL = "Unspecified Recipient"
UNKNOWN_FUNDING_STREAM_LABEL = "Unknown Funding Stream"
UNKNOWN_APPROPRIATION_LABEL = "Unknown Appropriation Type"
UNKNOWN_MAPPING_DISPLAY_LABEL = "Unknown / Unclassified"
MULTI_COUNTY_LABEL = "Multiple counties"
MULTI_CITY_LABEL = "Multiple cities"

UNKNOWN_COUNTY_TOKENS = {
    "",
    "UNKNOWN",
    "UNK",
    "N/A",
    "NA",
    "UNSPECIFIED",
    "UNDEFINED",
    "NOT REPORTED",
}

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


@dataclass(frozen=True)
class TaggsFilters:
    state: str | None
    fiscal_year: int
    program_office: str | None
    aln: str | None
    can_code: str | None
    funding_stream: str | None
    domestic_only: bool


@dataclass(frozen=True)
class TaggsQueryContext:
    summary_has_effective_program_name: bool
    summary_has_effective_category: bool
    summary_has_effective_subcategory: bool
    summary_has_effective_mapping_method: bool
    summary_has_funding_stream: bool
    summary_has_appropriation_type: bool
    summary_has_profile_assisted_mapping: bool
    summary_has_fallback_inference: bool
    summary_has_can_mapping_version: bool
    classification_has_effective_program_name: bool
    classification_has_effective_category: bool
    classification_has_effective_subcategory: bool
    classification_has_effective_mapping_method: bool
    classification_has_can_mapping_version: bool


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


def _strip_optional(value: str | None) -> str | None:
    token = str(value or "").strip()
    return token or None


def _normalize_metric(metric: str | None) -> str:
    normalized = str(metric or "total_funding").strip().lower()
    if normalized not in VALID_METRICS:
        raise HTTPException(
            status_code=400,
            detail=(
                "metric must be one of total_funding, funding_per_capita, "
                "award_count, unique_recipient_count"
            ),
        )
    return normalized


def _normalize_state_code(state: str | None) -> str:
    token = str(state or "").strip().upper()
    if not STATE_CODE_RE.fullmatch(token):
        raise HTTPException(status_code=400, detail="state must be a valid 2-letter state code")
    return token


def _normalize_sort_field(sort_by: str | None) -> str:
    token = str(sort_by or "amount").strip().lower()
    if token not in VALID_DETAIL_SORT_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=(
                "sort_by must be one of line_number, amount, category, subcategory, "
                "award_title, recipient_name, award_number, aln, can_code, funding_stream"
            ),
        )
    return token


def _normalize_sort_dir(sort_dir: str | None) -> str:
    token = str(sort_dir or "desc").strip().lower()
    if token not in VALID_SORT_DIRECTIONS:
        raise HTTPException(status_code=400, detail="sort_dir must be asc or desc")
    return token


def _normalize_domestic_only(value: bool | None) -> bool:
    return True if value is None else bool(value)


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


def _ensure_required_tables(db: Session, *, for_map: bool = False) -> None:
    required_tables = [AWARD_SUMMARY_TABLE, CAN_CLASSIFICATION_TABLE, POPULATION_VIEW_TABLE]
    if for_map:
        required_tables.append(STATE_BOUNDARY_TABLE)
    missing_tables = [table_name for table_name in required_tables if not _table_exists(db, table_name)]
    if missing_tables:
        missing = ", ".join(missing_tables)
        raise HTTPException(
            status_code=503,
            detail=f"Required TAGGS/report tables are missing: {missing}. Run migrations and TAGGS ingestion.",
        )


def _latest_fiscal_year(db: Session) -> int:
    row = db.execute(
        text(f"SELECT MAX(funding_fiscal_year) AS max_fy FROM {AWARD_SUMMARY_TABLE}"),
    ).mappings().one()
    max_fy = row.get("max_fy")
    if max_fy is None:
        raise HTTPException(
            status_code=503,
            detail="TAGGS summary tables are empty. Run TAGGS ingestion before requesting TAGGS funding data.",
        )
    return int(max_fy)


def _resolve_fiscal_year(db: Session, fiscal_year: int | None) -> int:
    return _latest_fiscal_year(db) if fiscal_year is None else int(fiscal_year)


def _resolve_filters(
    db: Session,
    *,
    state: str | None,
    fiscal_year: int | None,
    program_office: str | None,
    aln: str | None,
    can_code: str | None,
    funding_stream: str | None,
    domestic_only: bool | None,
    for_map: bool = False,
) -> TaggsFilters:
    _ensure_required_tables(db, for_map=for_map)
    return TaggsFilters(
        state=_normalize_state_code(state) if state is not None else None,
        fiscal_year=_resolve_fiscal_year(db, fiscal_year),
        program_office=_strip_optional(program_office),
        aln=_strip_optional(aln),
        can_code=_strip_optional(can_code),
        funding_stream=_strip_optional(funding_stream),
        domestic_only=_normalize_domestic_only(domestic_only),
    )


def _build_query_context(db: Session) -> TaggsQueryContext:
    return TaggsQueryContext(
        summary_has_effective_program_name=_column_exists(db, AWARD_SUMMARY_TABLE, "effective_program_name"),
        summary_has_effective_category=_column_exists(db, AWARD_SUMMARY_TABLE, "effective_category"),
        summary_has_effective_subcategory=_column_exists(db, AWARD_SUMMARY_TABLE, "effective_subcategory"),
        summary_has_effective_mapping_method=_column_exists(db, AWARD_SUMMARY_TABLE, "effective_mapping_method"),
        summary_has_funding_stream=_column_exists(db, AWARD_SUMMARY_TABLE, "funding_stream"),
        summary_has_appropriation_type=_column_exists(db, AWARD_SUMMARY_TABLE, "appropriation_type"),
        summary_has_profile_assisted_mapping=_column_exists(db, AWARD_SUMMARY_TABLE, "has_profile_assisted_mapping"),
        summary_has_fallback_inference=_column_exists(db, AWARD_SUMMARY_TABLE, "has_fallback_inference"),
        summary_has_can_mapping_version=_column_exists(db, AWARD_SUMMARY_TABLE, "can_mapping_version"),
        classification_has_effective_program_name=_column_exists(
            db, CAN_CLASSIFICATION_TABLE, "effective_program_name"
        ),
        classification_has_effective_category=_column_exists(db, CAN_CLASSIFICATION_TABLE, "effective_category"),
        classification_has_effective_subcategory=_column_exists(
            db, CAN_CLASSIFICATION_TABLE, "effective_subcategory"
        ),
        classification_has_effective_mapping_method=_column_exists(
            db, CAN_CLASSIFICATION_TABLE, "effective_mapping_method"
        ),
        classification_has_can_mapping_version=_column_exists(db, CAN_CLASSIFICATION_TABLE, "can_mapping_version"),
    )


def _clean_label_expr(column_expr: str, fallback_literal: str) -> str:
    safe_fallback = fallback_literal.replace("'", "''")
    return f"COALESCE(NULLIF(TRIM({column_expr}), ''), '{safe_fallback}')"


def _clean_county_expr(column_expr: str) -> str:
    return (
        "CASE "
        f"WHEN NULLIF(TRIM({column_expr}), '') IS NULL THEN '{UNKNOWN_COUNTY_LABEL}' "
        f"WHEN UPPER(TRIM({column_expr})) IN ('UNKNOWN','UNK','N/A','NA','UNSPECIFIED','UNDEFINED','NOT REPORTED') "
        f"THEN '{UNKNOWN_COUNTY_LABEL}' "
        f"ELSE TRIM({column_expr}) END"
    )


def _state_expr(alias: str) -> str:
    return f"UPPER(NULLIF(TRIM({alias}.legal_entity_state_normalized), ''))"


def _category_expr(context: TaggsQueryContext, summary_alias: str = "s", can_alias: str = "c") -> str:
    summary_expr = (
        f"NULLIF(TRIM({summary_alias}.effective_category), '')"
        if context.summary_has_effective_category
        else "NULL"
    )
    classification_expr = (
        f"NULLIF(TRIM({can_alias}.effective_category), '')"
        if context.classification_has_effective_category
        else f"NULLIF(TRIM({can_alias}.category_override), '')"
    )
    return (
        f"COALESCE({summary_expr}, "
        f"{classification_expr}, "
        f"NULLIF(TRIM({summary_alias}.program_office), ''), "
        f"'{UNKNOWN_CATEGORY_LABEL}')"
    )


def _optional_category_expr(context: TaggsQueryContext, summary_alias: str = "s", can_alias: str = "c") -> str:
    summary_expr = (
        f"NULLIF(TRIM({summary_alias}.effective_category), '')"
        if context.summary_has_effective_category
        else "NULL"
    )
    classification_expr = (
        f"NULLIF(TRIM({can_alias}.effective_category), '')"
        if context.classification_has_effective_category
        else f"NULLIF(TRIM({can_alias}.category_override), '')"
    )
    return (
        f"COALESCE({summary_expr}, "
        f"{classification_expr}, "
        f"NULLIF(TRIM({summary_alias}.program_office), ''))"
    )


def _subcategory_expr(context: TaggsQueryContext, summary_alias: str = "s", can_alias: str = "c") -> str:
    summary_expr = (
        f"NULLIF(TRIM({summary_alias}.effective_subcategory), '')"
        if context.summary_has_effective_subcategory
        else "NULL"
    )
    classification_expr = (
        f"NULLIF(TRIM({can_alias}.effective_subcategory), '')"
        if context.classification_has_effective_subcategory
        else f"NULLIF(TRIM({can_alias}.subcategory_override), '')"
    )
    return (
        f"COALESCE({summary_expr}, "
        f"{classification_expr}, "
        f"NULLIF(TRIM({summary_alias}.assistance_listing_title), ''), "
        f"'{UNKNOWN_SUBCATEGORY_LABEL}')"
    )


def _optional_subcategory_expr(context: TaggsQueryContext, summary_alias: str = "s", can_alias: str = "c") -> str:
    summary_expr = (
        f"NULLIF(TRIM({summary_alias}.effective_subcategory), '')"
        if context.summary_has_effective_subcategory
        else "NULL"
    )
    classification_expr = (
        f"NULLIF(TRIM({can_alias}.effective_subcategory), '')"
        if context.classification_has_effective_subcategory
        else f"NULLIF(TRIM({can_alias}.subcategory_override), '')"
    )
    return (
        f"COALESCE({summary_expr}, "
        f"{classification_expr}, "
        f"NULLIF(TRIM({summary_alias}.assistance_listing_title), ''))"
    )


def _program_name_expr(context: TaggsQueryContext, summary_alias: str = "s", can_alias: str = "c") -> str:
    summary_expr = (
        f"NULLIF(TRIM({summary_alias}.effective_program_name), '')"
        if context.summary_has_effective_program_name
        else "NULL"
    )
    classification_expr = (
        f"NULLIF(TRIM({can_alias}.effective_program_name), '')"
        if context.classification_has_effective_program_name
        else "NULL"
    )
    return f"COALESCE({summary_expr}, {classification_expr})"


def _optional_funding_stream_expr(
    context: TaggsQueryContext,
    summary_alias: str = "s",
    can_alias: str = "c",
) -> str:
    stream_expr = (
        f"{summary_alias}.funding_stream"
        if context.summary_has_funding_stream
        else f"{can_alias}.funding_stream"
    )
    return f"NULLIF(TRIM({stream_expr}), '')"


def _funding_stream_expr(context: TaggsQueryContext, summary_alias: str = "s", can_alias: str = "c") -> str:
    return f"COALESCE({_optional_funding_stream_expr(context, summary_alias, can_alias)}, '{UNKNOWN_FUNDING_STREAM_LABEL}')"


def _appropriation_type_expr(context: TaggsQueryContext, summary_alias: str = "s", can_alias: str = "c") -> str:
    appropriation_expr = (
        f"{summary_alias}.appropriation_type"
        if context.summary_has_appropriation_type
        else f"{can_alias}.appropriation_type"
    )
    return _clean_label_expr(appropriation_expr, UNKNOWN_APPROPRIATION_LABEL)


def _mapping_method_expr(context: TaggsQueryContext, summary_alias: str = "s", can_alias: str = "c") -> str:
    summary_expr = (
        f"NULLIF(TRIM({summary_alias}.effective_mapping_method), '')"
        if context.summary_has_effective_mapping_method
        else "NULL"
    )
    classification_expr = (
        f"NULLIF(TRIM({can_alias}.effective_mapping_method), '')"
        if context.classification_has_effective_mapping_method
        else "NULL"
    )
    return f"COALESCE({summary_expr}, {classification_expr}, 'unknown')"


def _mapping_version_expr(context: TaggsQueryContext, summary_alias: str = "s", can_alias: str = "c") -> str:
    summary_expr = (
        f"NULLIF(TRIM({summary_alias}.can_mapping_version), '')"
        if context.summary_has_can_mapping_version
        else "NULL"
    )
    classification_expr = (
        f"NULLIF(TRIM({can_alias}.can_mapping_version), '')"
        if context.classification_has_can_mapping_version
        else "NULL"
    )
    return f"COALESCE({summary_expr}, {classification_expr})"


def _display_label_expr(context: TaggsQueryContext, summary_alias: str = "s", can_alias: str = "c") -> str:
    return (
        "COALESCE("
        f"{_program_name_expr(context, summary_alias, can_alias)}, "
        f"{_optional_funding_stream_expr(context, summary_alias, can_alias)}, "
        f"{_optional_subcategory_expr(context, summary_alias, can_alias)}, "
        f"{_optional_category_expr(context, summary_alias, can_alias)}, "
        f"'{UNKNOWN_MAPPING_DISPLAY_LABEL}')"
    )


def _display_label_from_row(row: dict[str, Any]) -> str:
    for key in ("effective_program_name", "funding_stream", "effective_subcategory", "effective_category"):
        value = _strip_optional(row.get(key))
        if value and value not in {
            UNKNOWN_FUNDING_STREAM_LABEL,
            UNKNOWN_CATEGORY_LABEL,
            UNKNOWN_SUBCATEGORY_LABEL,
        }:
            return value
    return UNKNOWN_MAPPING_DISPLAY_LABEL


def _mapping_status_from_row(row: dict[str, Any]) -> str:
    return "mapped" if _display_label_from_row(row) != UNKNOWN_MAPPING_DISPLAY_LABEL else "unresolved"


def _build_where_sql(
    filters: TaggsFilters,
    *,
    context: TaggsQueryContext,
    alias: str = "s",
    can_alias: str = "s",
    include_state: bool,
) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = [f"{alias}.funding_fiscal_year = :fiscal_year"]
    params: dict[str, Any] = {"fiscal_year": int(filters.fiscal_year)}

    if include_state and filters.state:
        clauses.append(f"{_state_expr(alias)} = :state")
        params["state"] = filters.state
    if filters.program_office:
        clauses.append(f"{alias}.program_office = :program_office")
        params["program_office"] = filters.program_office
    if filters.aln:
        clauses.append(f"{alias}.aln = :aln")
        params["aln"] = filters.aln
    if filters.can_code:
        clauses.append(f"{alias}.can_code = :can_code")
        params["can_code"] = filters.can_code
    if filters.funding_stream:
        clauses.append(f"{_funding_stream_expr(context, alias, can_alias)} = :funding_stream")
        params["funding_stream"] = filters.funding_stream
    if filters.domestic_only:
        clauses.append(f"{alias}.is_domestic_scope IS TRUE")

    return "WHERE " + " AND ".join(clauses), params


def _base_from_clause() -> str:
    return (
        f"FROM {AWARD_SUMMARY_TABLE} AS s "
        f"LEFT JOIN {CAN_CLASSIFICATION_TABLE} AS c ON c.can_code = s.can_code"
    )


def _build_grouping_metadata() -> dict[str, Any]:
    return {
        "category_field": "award_funding_summary.effective_category",
        "fallback_category_field": "award_funding_summary.program_office",
        "subcategory_field": "award_funding_summary.effective_subcategory",
        "fallback_subcategory_field": "award_funding_summary.assistance_listing_title",
        "program_name_field": "award_funding_summary.effective_program_name",
        "category_label": "Effective CAN category",
        "subcategory_label": "Effective CAN sub-category",
        "program_name_label": "Effective CAN program",
        "effective_category_method": "effective_category from CDC-profile-assisted CAN mapping, fallback CAN inference, or Program Office when unresolved",
        "effective_subcategory_method": (
            "effective_subcategory from CDC-profile-assisted CAN mapping, fallback CAN inference, or Assistance Listing Title when unresolved"
        ),
    }


def _build_methodology_notes(*, domestic_only: bool) -> list[str]:
    notes = [
        "Data source: state-based HHS TAGGS CSV exports ingested into CHIP.",
        "Amounts represent TAGGS funding or award actions, not audited final expenditures.",
        "Raw TAGGS rows are not altered. CHIP rebuilds derived summaries after applying the current CAN mapping dictionary in taggs.can_classification.",
        "CDC Funding Profiles FY2020-FY2023 are the primary reference dataset for CAN mapping. TAGGS FY2021-FY2023 rows are matched deterministically to profile rows using fiscal year, state, grantee, title, amount, and related metadata.",
        "FY2024-FY2026 TAGGS classifications reuse learned CAN mappings when possible. New or unresolved CANs use deterministic fallback inference from Program Office, ALN, Assistance Listing Title, and award text.",
        "When Normalize Data is on, CHIP maps TAGGS CANs into the same funding-stream framework used for USA Spending, then applies explicit profile-scope inclusion and exclusion rules instead of a flat statewide scaling factor.",
        "Category, sub-category, and program totals use effective CAN mapping fields. Low-confidence CANs remain in unknown or unclassified buckets instead of being forced into a program bucket.",
    ]
    if domestic_only:
        notes.append(
            "Domestic profile filter is enabled. It excludes foreign recipient geography and records flagged by a conservative international-activity keyword heuristic."
        )
    else:
        notes.append("Domestic profile filter is disabled. Profile totals include all ingested rows that match the selected filters.")
    notes.append(
        "FY2024-FY2026 values in CHIP are profile-informed estimates, not official CDC Funding Profile totals or official CDC profile PDFs."
    )
    return notes


def _state_name_from_code(db: Session, state_code: str) -> str:
    row = db.execute(
        text(
            f"""
            SELECT COALESCE(state_name, state_abbr) AS state_name
            FROM {STATE_BOUNDARY_TABLE}
            WHERE state_abbr = :state
            LIMIT 1
            """
        ),
        {"state": state_code},
    ).mappings().one_or_none()
    if row and row.get("state_name"):
        return str(row["state_name"])
    return state_code


def _fetch_population_for_state(db: Session, state_code: str) -> tuple[float | None, str | None]:
    row = db.execute(
        text(
            f"""
            SELECT population, source_label
            FROM {POPULATION_VIEW_TABLE}
            WHERE geography_type = 'state'
              AND UPPER(state_abbr) = :state
            LIMIT 1
            """
        ),
        {"state": state_code},
    ).mappings().one_or_none()
    if not row:
        return None, None
    population = _json_number(row.get("population"))
    return (float(population) if population is not None else None, _strip_optional(row.get("source_label")))


def _metric_value_from_row(row: dict[str, Any], metric: str) -> float | None:
    if metric == "total_funding":
        return _json_number(row.get("total_funding"))
    if metric == "funding_per_capita":
        return _json_number(row.get("funding_per_capita"))
    if metric == "award_count":
        value = row.get("award_count")
        return float(value) if value is not None else None
    if metric == "unique_recipient_count":
        value = row.get("unique_recipient_count")
        return float(value) if value is not None else None
    return None


def _compute_bins(values: list[float], bins: int = 5) -> list[dict[str, Any]]:
    if not values:
        return []
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        value = sorted_values[0]
        return [{"min": value, "max": value, "label": f"{value:,.2f}", "colorIndex": 0}]

    quantiles: list[float] = []
    for index in range(1, bins):
        raw_position = (len(sorted_values) - 1) * (index / bins)
        lower_idx = int(math.floor(raw_position))
        upper_idx = int(math.ceil(raw_position))
        lower = sorted_values[lower_idx]
        upper = sorted_values[upper_idx]
        if lower_idx == upper_idx:
            quantile = lower
        else:
            ratio = raw_position - lower_idx
            quantile = lower + (upper - lower) * ratio
        quantiles.append(float(quantile))

    points = [sorted_values[0], *quantiles, sorted_values[-1]]
    deduped: list[float] = []
    for point in points:
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
                "label": f"{lower:,.2f} - {upper:,.2f}",
                "colorIndex": index,
            }
        )
    return output


def _fetch_mapping_metadata(
    db: Session,
    *,
    filters: TaggsFilters | None = None,
) -> dict[str, Any]:
    context = _build_query_context(db)
    if filters is None:
        where_sql = "WHERE NULLIF(TRIM(s.can_code), '') IS NOT NULL"
        params: dict[str, Any] = {}
    else:
        where_sql, params = _build_where_sql(
            filters,
            context=context,
            include_state=bool(filters.state),
        )
        where_sql = f"{where_sql} AND NULLIF(TRIM(s.can_code), '') IS NOT NULL"

    row = db.execute(
        text(
            f"""
            SELECT
                COUNT(DISTINCT s.can_code)::integer AS can_count,
                COUNT(DISTINCT s.can_code) FILTER (
                    WHERE {_mapping_method_expr(context)} <> 'unknown'
                )::integer AS mapped_can_count,
                COUNT(DISTINCT s.can_code) FILTER (
                    WHERE {_mapping_method_expr(context)} = 'cdc_profile_match'
                )::integer AS profile_assisted_can_count,
                COUNT(DISTINCT s.can_code) FILTER (
                    WHERE {_mapping_method_expr(context)} = 'fallback_inference'
                )::integer AS fallback_inferred_can_count,
                COUNT(DISTINCT s.can_code) FILTER (
                    WHERE {_mapping_method_expr(context)} = 'unknown'
                )::integer AS unresolved_can_count,
                MAX({_mapping_version_expr(context)}) AS can_mapping_version
            {_base_from_clause()}
            {where_sql}
            """
        ),
        params,
    ).mappings().one()
    return {
        "can_count": int(row.get("can_count") or 0),
        "mapped_can_count": int(row.get("mapped_can_count") or 0),
        "profile_assisted_can_count": int(row.get("profile_assisted_can_count") or 0),
        "fallback_inferred_can_count": int(row.get("fallback_inferred_can_count") or 0),
        "unresolved_can_count": int(row.get("unresolved_can_count") or 0),
        "can_mapping_version": row.get("can_mapping_version"),
        "methodology_version": PROFILE_CALIBRATION_METHODOLOGY_VERSION,
        "summary_has_effective_columns": (
            context.summary_has_effective_program_name
            and context.summary_has_effective_category
            and context.summary_has_effective_subcategory
            and context.summary_has_funding_stream
            and context.summary_has_effective_mapping_method
            and context.summary_has_can_mapping_version
        ),
        "classification_has_effective_columns": (
            context.classification_has_effective_program_name
            and context.classification_has_effective_category
            and context.classification_has_effective_subcategory
            and context.classification_has_effective_mapping_method
            and context.classification_has_can_mapping_version
        ),
        "has_profile_assisted_mapping": int(row.get("profile_assisted_can_count") or 0) > 0,
        "has_fallback_inference": int(row.get("fallback_inferred_can_count") or 0) > 0,
        "has_interpreted_can_labels": int(row.get("mapped_can_count") or 0) > 0,
    }


def fetch_can_mapping_status(db: Session) -> dict[str, Any]:
    _ensure_required_tables(db, for_map=False)
    metadata = _fetch_mapping_metadata(db)
    return {
        **metadata,
        "status": (
            "ready"
            if metadata.get("summary_has_effective_columns") and metadata.get("has_interpreted_can_labels")
            else "needs_rebuild"
        ),
        "validation_note": (
            "Derived TAGGS summaries include interpreted CAN labels."
            if metadata.get("summary_has_effective_columns") and metadata.get("has_interpreted_can_labels")
            else "TAGGS CAN mapping is present in schema, but derived summaries appear stale or unresolved. Rebuild downstream TAGGS layers."
        ),
    }


def list_filter_options(db: Session) -> dict[str, Any]:
    _ensure_required_tables(db, for_map=True)
    context = _build_query_context(db)

    fiscal_year_rows = db.execute(
        text(
            f"""
            SELECT DISTINCT funding_fiscal_year
            FROM {AWARD_SUMMARY_TABLE}
            WHERE funding_fiscal_year IS NOT NULL
            ORDER BY funding_fiscal_year DESC
            """
        )
    ).mappings().all()
    office_rows = db.execute(
        text(
            f"""
            SELECT DISTINCT program_office
            FROM {AWARD_SUMMARY_TABLE}
            WHERE NULLIF(TRIM(program_office), '') IS NOT NULL
            ORDER BY program_office
            LIMIT 500
            """
        )
    ).mappings().all()
    aln_rows = db.execute(
        text(
            f"""
            SELECT DISTINCT aln
            FROM {AWARD_SUMMARY_TABLE}
            WHERE NULLIF(TRIM(aln), '') IS NOT NULL
            ORDER BY aln
            LIMIT 800
            """
        )
    ).mappings().all()
    can_rows = db.execute(
        text(
            f"""
            SELECT DISTINCT can_code
            FROM {AWARD_SUMMARY_TABLE}
            WHERE NULLIF(TRIM(can_code), '') IS NOT NULL
            ORDER BY can_code
            LIMIT 2000
            """
        )
    ).mappings().all()
    funding_stream_rows = db.execute(
        text(
            f"""
            SELECT DISTINCT NULLIF(TRIM({_funding_stream_expr(context)}), '') AS funding_stream
            {_base_from_clause()}
            WHERE NULLIF(TRIM({_funding_stream_expr(context)}), '') IS NOT NULL
            ORDER BY funding_stream
            """
        )
    ).mappings().all()
    refreshed_row = db.execute(
        text(
            f"""
            SELECT GREATEST(
                COALESCE(MAX(s.refreshed_at), TIMESTAMPTZ 'epoch'),
                COALESCE((SELECT MAX(updated_at) FROM {CAN_CLASSIFICATION_TABLE}), TIMESTAMPTZ 'epoch')
            ) AS refreshed_at
            FROM {AWARD_SUMMARY_TABLE} AS s
            """
        )
    ).mappings().one()
    mapping_metadata = _fetch_mapping_metadata(db)

    fiscal_years = [int(row["funding_fiscal_year"]) for row in fiscal_year_rows if row.get("funding_fiscal_year") is not None]
    latest_fy = fiscal_years[0] if fiscal_years else None

    return {
        "metric_options": METRIC_OPTIONS,
        "fiscal_years": fiscal_years,
        "default_fiscal_year": latest_fy,
        "program_offices": [str(row["program_office"]).strip() for row in office_rows if row.get("program_office")],
        "alns": [str(row["aln"]).strip() for row in aln_rows if row.get("aln")],
        "can_codes": [str(row["can_code"]).strip() for row in can_rows if row.get("can_code")],
        "funding_streams": [
            str(row["funding_stream"]).strip() for row in funding_stream_rows if row.get("funding_stream")
        ],
        "grouping": _build_grouping_metadata(),
        "profile_default_domestic_only": True,
        "data_source": "HHS TAGGS",
        "normalization": {
            "available": True,
            "help_text": "Reconstructed to CDC Funding Profiles scope and benchmarked against observed profile years",
            "supported_metrics": ["total_funding", "funding_per_capita"],
            "training_years": [2020, 2021, 2022, 2023],
            "estimated_years": [2024, 2025, 2026],
            "methodology_version": PROFILE_CALIBRATION_METHODOLOGY_VERSION,
        },
        "mapping_metadata": mapping_metadata,
        "last_refreshed_at": (
            refreshed_row.get("refreshed_at").isoformat() if refreshed_row.get("refreshed_at") else None
        ),
        "methodology_notes": _build_methodology_notes(domestic_only=True),
    }


def fetch_state_map_geojson(
    db: Session,
    *,
    metric: str | None,
    fiscal_year: int | None,
    program_office: str | None,
    aln: str | None,
    can_code: str | None,
    funding_stream: str | None,
    bbox: str | None,
    zoom: int,
    limit: int,
    normalize: bool = False,
) -> dict[str, Any]:
    filters = _resolve_filters(
        db,
        state=None,
        fiscal_year=fiscal_year,
        program_office=program_office,
        aln=aln,
        can_code=can_code,
        funding_stream=funding_stream,
        domestic_only=False,
        for_map=True,
    )
    context = _build_query_context(db)
    normalized_metric = _normalize_metric(metric)
    normalization_requested = bool(normalize)
    normalization_supported, normalization_reason = taggs_normalization_compatibility(
        metric=normalized_metric,
        program_office=filters.program_office,
        aln=filters.aln,
        can_code=filters.can_code,
        funding_stream=filters.funding_stream,
    )
    normalization_lookup = (
        fetch_state_normalization_lookup(
            db,
            source_system="taggs",
            fiscal_year=filters.fiscal_year,
        )
        if normalization_requested and normalization_supported
        else {}
    )
    normalization_applied = normalization_requested and normalization_supported and bool(normalization_lookup)
    where_sql, params = _build_where_sql(filters, context=context, include_state=False)

    simplify_degrees = 0.03
    normalized_zoom = max(0, int(zoom))
    if normalized_zoom <= 4:
        simplify_degrees = 0.05
    elif normalized_zoom >= 8:
        simplify_degrees = 0.015

    bbox_filter_sql = ""
    params.update(
        {
            "simplify_degrees": simplify_degrees,
            "limit": max(1, min(int(limit), 200)),
        }
    )
    if bbox:
        try:
            minx, miny, maxx, maxy = [float(item) for item in str(bbox).split(",")]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="bbox must be minLon,minLat,maxLon,maxLat") from exc
        if minx >= maxx or miny >= maxy:
            raise HTTPException(status_code=400, detail="bbox bounds are invalid")
        params.update({"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy})
        bbox_filter_sql = (
            "AND sb.geom && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) "
            "AND ST_Intersects(sb.geom, ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326))"
        )

    rows = db.execute(
        text(
            f"""
            WITH state_rollup AS (
                SELECT
                    {_state_expr('s')} AS state_abbr,
                    SUM(COALESCE(s.total_sum_of_actions, 0))::numeric AS total_funding,
                    COUNT(DISTINCT s.award_number)::integer AS award_count,
                    COUNT(DISTINCT NULLIF(TRIM(s.legal_entity_name), ''))::integer AS unique_recipient_count
                {_base_from_clause()}
                {where_sql}
                GROUP BY {_state_expr('s')}
            ),
            enriched AS (
                SELECT
                    sr.state_abbr,
                    sr.total_funding,
                    sr.award_count,
                    sr.unique_recipient_count,
                    pop.population::numeric AS population,
                    CASE
                        WHEN pop.population IS NULL OR pop.population <= 0 THEN NULL
                        ELSE sr.total_funding / pop.population
                    END AS funding_per_capita
                FROM state_rollup AS sr
                LEFT JOIN {POPULATION_VIEW_TABLE} AS pop
                    ON pop.geography_type = 'state'
                   AND UPPER(pop.state_abbr) = sr.state_abbr
            )
            SELECT
                sb.state_abbr AS id,
                COALESCE(sb.state_name, sb.state_abbr) AS state_name,
                enriched.total_funding,
                enriched.award_count,
                enriched.unique_recipient_count,
                enriched.population,
                enriched.funding_per_capita,
                ST_AsGeoJSON(
                    ST_SimplifyPreserveTopology(sb.geom, :simplify_degrees),
                    6
                )::json AS geometry
            FROM {STATE_BOUNDARY_TABLE} AS sb
            LEFT JOIN enriched
              ON enriched.state_abbr = sb.state_abbr
            WHERE sb.geom IS NOT NULL
              {bbox_filter_sql}
            ORDER BY sb.state_abbr
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()

    features = []
    for row in rows:
        row_dict = dict(row)
        metric_value = _metric_value_from_row(row_dict, normalized_metric)
        raw_total_funding = _json_number(row.get("total_funding"))
        raw_funding_per_capita = _json_number(row.get("funding_per_capita"))
        normalization_row = normalization_lookup.get(str(row.get("id") or "").strip().upper())
        normalized_total_funding = None
        normalized_funding_per_capita = None
        normalization_factor = None
        normalized_amount_type = None
        normalization_status = None
        confidence_note = None
        normalization_method = None
        funding_stream_logic_version = None
        if normalization_applied and normalization_row:
            normalized_total_funding = _json_number(normalization_row.get("normalized_amount"))
            normalization_factor = _json_number(normalization_row.get("normalization_factor"))
            normalized_amount_type = normalization_row.get("normalized_amount_type")
            normalization_status = normalization_row.get("status_label")
            confidence_note = normalization_row.get("confidence_note")
            normalization_method = normalization_row.get("normalization_method")
            funding_stream_logic_version = normalization_row.get("funding_stream_logic_version")
            population = _json_number(row.get("population"))
            if normalized_total_funding is not None and population not in (None, 0):
                normalized_funding_per_capita = float(normalized_total_funding) / float(population)
            if normalized_metric == "total_funding":
                metric_value = normalized_total_funding
            elif normalized_metric == "funding_per_capita":
                metric_value = normalized_funding_per_capita
        features.append(
            {
                "type": "Feature",
                "geometry": row.get("geometry"),
                "properties": {
                    "id": row.get("id"),
                    "location_id": row.get("id"),
                    "name": row.get("state_name"),
                    "state_abbr": row.get("id"),
                    "state_name": row.get("state_name"),
                    "geo_level": "state",
                    "metric": normalized_metric,
                    "metric_label": METRIC_LABELS[normalized_metric],
                    "value": metric_value,
                    "fiscal_year": filters.fiscal_year,
                    "total_funding": normalized_total_funding if normalized_total_funding is not None else raw_total_funding,
                    "funding_per_capita": (
                        normalized_funding_per_capita
                        if normalized_funding_per_capita is not None
                        else raw_funding_per_capita
                    ),
                    "raw_total_funding": raw_total_funding,
                    "raw_funding_per_capita": raw_funding_per_capita,
                    "award_count": int(row.get("award_count") or 0),
                    "unique_recipient_count": int(row.get("unique_recipient_count") or 0),
                    "population": _json_number(row.get("population")),
                    "program_office_filter": filters.program_office,
                    "aln_filter": filters.aln,
                    "can_code_filter": filters.can_code,
                    "funding_stream_filter": filters.funding_stream,
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

    normalization_note = build_normalization_note(
        fiscal_year=filters.fiscal_year,
        normalization_applied=normalization_applied,
        reason=normalization_reason,
    )
    mapping_metadata = _fetch_mapping_metadata(db)
    return {
        "type": "FeatureCollection",
        "level": "state",
        "metric": normalized_metric,
        "metric_label": METRIC_LABELS[normalized_metric],
        "fiscal_year": filters.fiscal_year,
        "features": features,
        "meta": {
            "note": " ".join(
                part
                for part in [
                    (
                        "Values reflect TAGGS award funding actions by recipient location and can include international activities "
                        "with U.S.-based recipients unless the funding profile domestic filter is applied."
                    ),
                    normalization_note,
                ]
                if part
            ),
            "legend_label": (
                f"{METRIC_LEGEND_TEXT[normalized_metric]} in FY{filters.fiscal_year}."
                + (
                    f" {normalization_lookup[next(iter(normalization_lookup))]['status_label']}."
                    if normalization_applied and normalization_lookup
                    else ""
                )
            ),
            "geojson_precision": 6,
            "simplify_tolerance_degrees": simplify_degrees,
            "data_source": "HHS TAGGS",
            "normalization_requested": normalization_requested,
            "normalization_applied": normalization_applied,
            "normalization_status_label": (
                normalization_lookup[next(iter(normalization_lookup))]["status_label"]
                if normalization_applied and normalization_lookup
                else None
            ),
            "can_mapping_version": mapping_metadata.get("can_mapping_version"),
            "mapping_metadata": mapping_metadata,
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


def fetch_state_legend(
    db: Session,
    *,
    metric: str | None,
    fiscal_year: int | None,
    program_office: str | None,
    aln: str | None,
    can_code: str | None,
    funding_stream: str | None,
    normalize: bool = False,
) -> dict[str, Any]:
    filters = _resolve_filters(
        db,
        state=None,
        fiscal_year=fiscal_year,
        program_office=program_office,
        aln=aln,
        can_code=can_code,
        funding_stream=funding_stream,
        domestic_only=False,
        for_map=False,
    )
    context = _build_query_context(db)
    normalized_metric = _normalize_metric(metric)
    normalization_requested = bool(normalize)
    normalization_supported, normalization_reason = taggs_normalization_compatibility(
        metric=normalized_metric,
        program_office=filters.program_office,
        aln=filters.aln,
        can_code=filters.can_code,
        funding_stream=filters.funding_stream,
    )
    normalization_lookup = (
        fetch_state_normalization_lookup(
            db,
            source_system="taggs",
            fiscal_year=filters.fiscal_year,
        )
        if normalization_requested and normalization_supported
        else {}
    )
    normalization_applied = normalization_requested and normalization_supported and bool(normalization_lookup)
    where_sql, params = _build_where_sql(filters, context=context, include_state=False)

    rows = db.execute(
        text(
            f"""
            WITH state_rollup AS (
                SELECT
                    {_state_expr('s')} AS state_abbr,
                    SUM(COALESCE(s.total_sum_of_actions, 0))::numeric AS total_funding,
                    COUNT(DISTINCT s.award_number)::integer AS award_count,
                    COUNT(DISTINCT NULLIF(TRIM(s.legal_entity_name), ''))::integer AS unique_recipient_count
                {_base_from_clause()}
                {where_sql}
                GROUP BY {_state_expr('s')}
            )
            SELECT
                sr.state_abbr,
                sr.total_funding,
                sr.award_count,
                sr.unique_recipient_count,
                pop.population::numeric AS population,
                CASE
                    WHEN pop.population IS NULL OR pop.population <= 0 THEN NULL
                    ELSE sr.total_funding / pop.population
                END AS funding_per_capita
            FROM state_rollup AS sr
            LEFT JOIN {POPULATION_VIEW_TABLE} AS pop
              ON pop.geography_type = 'state'
             AND UPPER(pop.state_abbr) = sr.state_abbr
            """
        ),
        params,
    ).mappings().all()

    metric_values: list[float] = []
    for row in rows:
        row_dict = dict(row)
        state_code = str(row_dict.get("state_abbr") or "").strip().upper()
        value = _metric_value_from_row(row_dict, normalized_metric)
        if normalization_applied and state_code in normalization_lookup:
            normalized_total = _json_number(normalization_lookup[state_code].get("normalized_amount"))
            population = _json_number(row_dict.get("population"))
            if normalized_metric == "total_funding":
                value = normalized_total
            elif normalized_metric == "funding_per_capita":
                value = (
                    float(normalized_total) / float(population)
                    if normalized_total is not None and population not in (None, 0)
                    else None
                )
        if value is None:
            continue
        numeric = float(value)
        if math.isfinite(numeric):
            metric_values.append(numeric)

    if normalization_applied:
        total_funding = float(
            sum(
                float(_json_number(row.get("normalized_amount")) or 0)
                for row in normalization_lookup.values()
            )
        )
    else:
        total_funding = float(sum(float(_json_number(row.get("total_funding")) or 0) for row in rows))
    total_awards = int(sum(int(row.get("award_count") or 0) for row in rows))
    normalization_note = build_normalization_note(
        fiscal_year=filters.fiscal_year,
        normalization_applied=normalization_applied,
        reason=normalization_reason,
    )
    normalization_status = (
        normalization_lookup[next(iter(normalization_lookup))]["status_label"]
        if normalization_applied and normalization_lookup
        else None
    )
    mapping_metadata = _fetch_mapping_metadata(db)

    return {
        "metric": normalized_metric,
        "metric_label": METRIC_LABELS[normalized_metric],
        "fiscal_year": filters.fiscal_year,
        "n": len(metric_values),
        "noDataCount": 0,
        "min": min(metric_values) if metric_values else None,
        "max": max(metric_values) if metric_values else None,
        "bins": _compute_bins(metric_values, bins=5),
        "total_funding": total_funding,
        "total_awards": total_awards,
        "note": " ".join(
            part
            for part in [
                "Values reflect TAGGS funding actions and are intended for comparative context, not final audited expenditures.",
                normalization_note,
            ]
            if part
        ),
        "legend_label": (
            f"{METRIC_LEGEND_TEXT[normalized_metric]} in FY{filters.fiscal_year}."
            + (f" {normalization_status}." if normalization_status else "")
        ),
        "normalization_requested": normalization_requested,
        "normalization_applied": normalization_applied,
        "normalization_status_label": normalization_status,
        "can_mapping_version": mapping_metadata.get("can_mapping_version"),
        "mapping_metadata": mapping_metadata,
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


def _fetch_profile_overall_row(db: Session, filters: TaggsFilters) -> dict[str, Any]:
    context = _build_query_context(db)
    where_sql, params = _build_where_sql(filters, context=context, include_state=True)
    row = db.execute(
        text(
            f"""
            SELECT
                COALESCE(SUM(COALESCE(s.total_sum_of_actions, 0)), 0)::numeric AS total_funding,
                COUNT(DISTINCT s.award_number)::integer AS award_count,
                COUNT(DISTINCT NULLIF(TRIM(s.legal_entity_name), ''))::integer AS unique_recipients,
                COUNT(DISTINCT CASE
                    WHEN NULLIF(TRIM(s.legal_entity_county_normalized), '') IS NULL THEN NULL
                    WHEN UPPER(TRIM(s.legal_entity_county_normalized)) IN ('UNKNOWN','UNK','N/A','NA','UNSPECIFIED','UNDEFINED','NOT REPORTED') THEN NULL
                    ELSE UPPER(TRIM(s.legal_entity_county_normalized))
                END)::integer AS counties_represented,
                MAX(s.refreshed_at) AS refreshed_at
            {_base_from_clause()}
            {where_sql}
            """
        ),
        params,
    ).mappings().one()
    return dict(row)


def _fetch_top_group_row(
    db: Session,
    *,
    filters: TaggsFilters,
    label_expr: str,
) -> dict[str, Any] | None:
    context = _build_query_context(db)
    where_sql, params = _build_where_sql(filters, context=context, include_state=True)
    row = db.execute(
        text(
            f"""
            SELECT
                {label_expr} AS label,
                SUM(COALESCE(s.total_sum_of_actions, 0))::numeric AS amount,
                COUNT(DISTINCT s.award_number)::integer AS award_count
            {_base_from_clause()}
            {where_sql}
            GROUP BY {label_expr}
            ORDER BY amount DESC, label ASC
            LIMIT 1
            """
        ),
        params,
    ).mappings().one_or_none()
    return dict(row) if row else None


def _fetch_recipients_rows(
    db: Session,
    *,
    filters: TaggsFilters,
    limit: int,
    offset: int,
) -> tuple[int, list[dict[str, Any]]]:
    context = _build_query_context(db)
    where_sql, params = _build_where_sql(filters, context=context, include_state=True)
    params = {**params, "limit": limit, "offset": offset}

    count_row = db.execute(
        text(
            f"""
            WITH recipient_rollup AS (
                SELECT {_clean_label_expr('s.legal_entity_name', UNKNOWN_RECIPIENT_LABEL)} AS recipient_name
                {_base_from_clause()}
                {where_sql}
                GROUP BY {_clean_label_expr('s.legal_entity_name', UNKNOWN_RECIPIENT_LABEL)}
            )
            SELECT COUNT(*)::integer AS total_rows
            FROM recipient_rollup
            """
        ),
        params,
    ).mappings().one()

    rows = db.execute(
        text(
            f"""
            WITH recipient_rollup AS (
                SELECT
                    {_clean_label_expr('s.legal_entity_name', UNKNOWN_RECIPIENT_LABEL)} AS recipient_name,
                    {_clean_label_expr('s.legal_entity_city', '')} AS city_label,
                    {_clean_county_expr('s.legal_entity_county_normalized')} AS county_label,
                    SUM(COALESCE(s.total_sum_of_actions, 0))::numeric AS amount,
                    COUNT(DISTINCT s.award_number)::integer AS award_count
                {_base_from_clause()}
                {where_sql}
                GROUP BY
                    {_clean_label_expr('s.legal_entity_name', UNKNOWN_RECIPIENT_LABEL)},
                    {_clean_label_expr('s.legal_entity_city', '')},
                    {_clean_county_expr('s.legal_entity_county_normalized')}
            ),
            recipient_collapsed AS (
                SELECT
                    recipient_name,
                    CASE
                        WHEN COUNT(DISTINCT NULLIF(city_label, '')) = 1 THEN MIN(NULLIF(city_label, ''))
                        WHEN COUNT(DISTINCT NULLIF(city_label, '')) = 0 THEN NULL
                        ELSE :multi_city_label
                    END AS city,
                    CASE
                        WHEN COUNT(DISTINCT county_label) = 1 THEN MIN(county_label)
                        ELSE :multi_county_label
                    END AS county,
                    SUM(amount)::numeric AS total_funding,
                    SUM(award_count)::integer AS award_count
                FROM recipient_rollup
                GROUP BY recipient_name
            )
            SELECT
                recipient_name,
                city,
                county,
                total_funding,
                award_count
            FROM recipient_collapsed
            ORDER BY total_funding DESC, recipient_name ASC
            LIMIT :limit
            OFFSET :offset
            """
        ),
        {**params, "multi_city_label": MULTI_CITY_LABEL, "multi_county_label": MULTI_COUNTY_LABEL},
    ).mappings().all()

    return int(count_row.get("total_rows") or 0), [dict(row) for row in rows]


def fetch_profile_summary(
    db: Session,
    *,
    state: str,
    fiscal_year: int | None,
    program_office: str | None,
    aln: str | None,
    can_code: str | None,
    funding_stream: str | None,
    domestic_only: bool | None,
) -> dict[str, Any]:
    filters = _resolve_filters(
        db,
        state=state,
        fiscal_year=fiscal_year,
        program_office=program_office,
        aln=aln,
        can_code=can_code,
        funding_stream=funding_stream,
        domestic_only=domestic_only,
    )
    context = _build_query_context(db)

    overall = _fetch_profile_overall_row(db, filters)
    total_funding = float(_json_number(overall.get("total_funding")) or 0.0)
    award_count = int(overall.get("award_count") or 0)
    unique_recipients = int(overall.get("unique_recipients") or 0)
    counties_represented = int(overall.get("counties_represented") or 0)

    top_category = _fetch_top_group_row(
        db,
        filters=filters,
        label_expr=_category_expr(context),
    )
    top_subcategory = _fetch_top_group_row(
        db,
        filters=filters,
        label_expr=_subcategory_expr(context),
    )
    top_recipient = _fetch_top_group_row(
        db,
        filters=filters,
        label_expr=_clean_label_expr("s.legal_entity_name", UNKNOWN_RECIPIENT_LABEL),
    )

    recipient_total_count, top_recipients_rows = _fetch_recipients_rows(
        db,
        filters=filters,
        limit=5,
        offset=0,
    )
    top5_amount = float(sum(float(_json_number(row.get("total_funding")) or 0) for row in top_recipients_rows))
    top5_share = (top5_amount / total_funding * 100.0) if total_funding > 0 else None

    population, population_source = _fetch_population_for_state(db, filters.state or "")
    per_capita = (total_funding / population) if population and population > 0 else None
    state_name = _state_name_from_code(db, filters.state or "")
    mapping_metadata = _fetch_mapping_metadata(db, filters=filters)
    unresolved_count = int(mapping_metadata.get("unresolved_can_count") or 0)

    county_totals = fetch_profile_counties(
        db,
        state=filters.state or "",
        fiscal_year=filters.fiscal_year,
        program_office=filters.program_office,
        aln=filters.aln,
        can_code=filters.can_code,
        funding_stream=filters.funding_stream,
        domestic_only=filters.domestic_only,
        limit=5000,
    )
    can_breakdown = fetch_profile_can_breakdown(
        db,
        state=filters.state or "",
        fiscal_year=filters.fiscal_year,
        program_office=filters.program_office,
        aln=filters.aln,
        can_code=filters.can_code,
        funding_stream=filters.funding_stream,
        domestic_only=filters.domestic_only,
    )
    categories = fetch_profile_categories(
        db,
        state=filters.state or "",
        fiscal_year=filters.fiscal_year,
        program_office=filters.program_office,
        aln=filters.aln,
        can_code=filters.can_code,
        funding_stream=filters.funding_stream,
        domestic_only=filters.domestic_only,
    )
    subcategories = fetch_profile_subcategories(
        db,
        state=filters.state or "",
        fiscal_year=filters.fiscal_year,
        program_office=filters.program_office,
        aln=filters.aln,
        can_code=filters.can_code,
        funding_stream=filters.funding_stream,
        domestic_only=filters.domestic_only,
    )
    detail_rollup = fetch_profile_details(
        db,
        state=filters.state or "",
        fiscal_year=filters.fiscal_year,
        program_office=filters.program_office,
        aln=filters.aln,
        can_code=filters.can_code,
        funding_stream=filters.funding_stream,
        domestic_only=filters.domestic_only,
        page=1,
        page_size=1,
        sort_by="amount",
        sort_dir="desc",
    )

    undefined_county_amount = float(county_totals.get("undefined_county_amount") or 0)
    undefined_county_share = (undefined_county_amount / total_funding * 100.0) if total_funding > 0 else None

    executive_lines = [
        f"In fiscal year {filters.fiscal_year}, TAGGS recorded ${total_funding:,.2f} across {award_count:,} awards in {state_name}.",
    ]
    if filters.domestic_only:
        executive_lines.append("Domestic reporting scope is enabled for this profile.")
    if top_category and top_category.get("label"):
        executive_lines.append(
            f"Top category: {top_category['label']} (${float(_json_number(top_category.get('amount')) or 0):,.2f})."
        )
    if top_subcategory and top_subcategory.get("label"):
        executive_lines.append(
            f"Top sub-category: {top_subcategory['label']} (${float(_json_number(top_subcategory.get('amount')) or 0):,.2f})."
        )
    if top_recipient and top_recipient.get("label"):
        executive_lines.append(
            f"Top recipient: {top_recipient['label']} (${float(_json_number(top_recipient.get('amount')) or 0):,.2f})."
        )
    if top5_share is not None:
        executive_lines.append(f"The top 5 recipients accounted for {top5_share:.1f}% of filtered TAGGS funding.")
    if counties_represented > 0:
        executive_lines.append(f"Filtered awards were associated with {counties_represented:,} counties.")
    if undefined_county_share is not None:
        executive_lines.append(
            f"{undefined_county_share:.1f}% of funding is in the explicit undefined county bucket."
        )

    return {
        "state": filters.state,
        "state_name": state_name,
        "fiscal_year": filters.fiscal_year,
        "data_source": "HHS TAGGS",
        "total_funding": total_funding,
        "award_count": award_count,
        "funding_per_capita": per_capita,
        "population": population,
        "population_source": population_source,
        "recipient_count": unique_recipients,
        "county_count": counties_represented,
        "top_category": {
            "name": top_category.get("label") if top_category else None,
            "amount": _json_number(top_category.get("amount")) if top_category else None,
            "award_count": int(top_category.get("award_count") or 0) if top_category else None,
        },
        "top_subcategory": {
            "name": top_subcategory.get("label") if top_subcategory else None,
            "amount": _json_number(top_subcategory.get("amount")) if top_subcategory else None,
            "award_count": int(top_subcategory.get("award_count") or 0) if top_subcategory else None,
        },
        "top_recipient": {
            "name": top_recipient.get("label") if top_recipient else None,
            "amount": _json_number(top_recipient.get("amount")) if top_recipient else None,
            "award_count": int(top_recipient.get("award_count") or 0) if top_recipient else None,
        },
        "executive_summary": executive_lines,
        "active_filters": {
            "program_office": filters.program_office,
            "aln": filters.aln,
            "can_code": filters.can_code,
            "funding_stream": filters.funding_stream,
            "domestic_only": filters.domestic_only,
        },
        "grouping": _build_grouping_metadata(),
        "mapping_metadata": mapping_metadata,
        "mapping_notice": (
            f"{unresolved_count:,} CANs in this filtered view remain unresolved and are shown as Unknown / Unclassified."
            if unresolved_count > 0
            else "All CANs in this filtered view have an interpreted funding-stream or program label."
        ),
        "methodology_notes": _build_methodology_notes(domestic_only=filters.domestic_only),
        "last_refreshed_at": overall.get("refreshed_at").isoformat() if overall.get("refreshed_at") else None,
        "validation": {
            "summary_total": total_funding,
            "category_total": float(categories.get("total_funding") or 0),
            "subcategory_total": float(subcategories.get("total_funding") or 0),
            "detail_total": float(detail_rollup.get("total_funding") or 0),
            "county_total_including_undefined": float(county_totals.get("total_funding") or 0),
            "can_breakdown_total": float(can_breakdown.get("total_funding") or 0),
        },
        "can_breakdown_total_streams": int(can_breakdown.get("funding_stream_count") or 0),
        "executive_summary_inputs": {
            "top_5_recipient_share_pct": top5_share,
            "undefined_county_amount": undefined_county_amount,
            "undefined_county_share_pct": undefined_county_share,
            "recipient_total_count": recipient_total_count,
        },
    }


def fetch_profile_categories(
    db: Session,
    *,
    state: str,
    fiscal_year: int | None,
    program_office: str | None,
    aln: str | None,
    can_code: str | None,
    funding_stream: str | None,
    domestic_only: bool | None,
) -> dict[str, Any]:
    filters = _resolve_filters(
        db,
        state=state,
        fiscal_year=fiscal_year,
        program_office=program_office,
        aln=aln,
        can_code=can_code,
        funding_stream=funding_stream,
        domestic_only=domestic_only,
    )
    context = _build_query_context(db)
    where_sql, params = _build_where_sql(filters, context=context, include_state=True)

    rows = db.execute(
        text(
            f"""
            WITH grouped AS (
                SELECT
                    {_category_expr(context)} AS category,
                    SUM(COALESCE(s.total_sum_of_actions, 0))::numeric AS amount,
                    COUNT(DISTINCT s.award_number)::integer AS award_count
                {_base_from_clause()}
                {where_sql}
                GROUP BY {_category_expr(context)}
            )
            SELECT
                category,
                amount,
                award_count,
                SUM(amount) OVER ()::numeric AS total_amount
            FROM grouped
            ORDER BY amount DESC, category ASC
            """
        ),
        params,
    ).mappings().all()

    total_amount = float(_json_number(rows[0].get("total_amount")) or 0) if rows else 0.0
    payload_rows = []
    for row in rows:
        amount = float(_json_number(row.get("amount")) or 0)
        payload_rows.append(
            {
                "category": row.get("category"),
                "amount": amount,
                "share_pct": (amount / total_amount * 100.0) if total_amount > 0 else 0.0,
                "award_count": int(row.get("award_count") or 0),
            }
        )

    return {
        "state": filters.state,
        "fiscal_year": filters.fiscal_year,
        "total_funding": total_amount,
        "rows": payload_rows,
        "grouping": _build_grouping_metadata(),
    }


def fetch_profile_subcategories(
    db: Session,
    *,
    state: str,
    fiscal_year: int | None,
    program_office: str | None,
    aln: str | None,
    can_code: str | None,
    funding_stream: str | None,
    domestic_only: bool | None,
) -> dict[str, Any]:
    filters = _resolve_filters(
        db,
        state=state,
        fiscal_year=fiscal_year,
        program_office=program_office,
        aln=aln,
        can_code=can_code,
        funding_stream=funding_stream,
        domestic_only=domestic_only,
    )
    context = _build_query_context(db)
    where_sql, params = _build_where_sql(filters, context=context, include_state=True)

    rows = db.execute(
        text(
            f"""
            WITH grouped AS (
                SELECT
                    {_category_expr(context)} AS category,
                    {_subcategory_expr(context)} AS subcategory,
                    SUM(COALESCE(s.total_sum_of_actions, 0))::numeric AS amount,
                    COUNT(DISTINCT s.award_number)::integer AS award_count
                {_base_from_clause()}
                {where_sql}
                GROUP BY {_category_expr(context)}, {_subcategory_expr(context)}
            )
            SELECT
                category,
                subcategory,
                amount,
                award_count,
                SUM(amount) OVER ()::numeric AS total_amount,
                SUM(amount) OVER (PARTITION BY category)::numeric AS category_amount
            FROM grouped
            ORDER BY category_amount DESC, category ASC, amount DESC, subcategory ASC
            """
        ),
        params,
    ).mappings().all()

    total_amount = float(_json_number(rows[0].get("total_amount")) or 0) if rows else 0.0
    payload_rows = []
    for row in rows:
        amount = float(_json_number(row.get("amount")) or 0)
        category_amount = float(_json_number(row.get("category_amount")) or 0)
        payload_rows.append(
            {
                "category": row.get("category"),
                "subcategory": row.get("subcategory"),
                "amount": amount,
                "share_total_pct": (amount / total_amount * 100.0) if total_amount > 0 else 0.0,
                "share_category_pct": (amount / category_amount * 100.0) if category_amount > 0 else 0.0,
                "award_count": int(row.get("award_count") or 0),
                "category_total": category_amount,
            }
        )

    return {
        "state": filters.state,
        "fiscal_year": filters.fiscal_year,
        "total_funding": total_amount,
        "rows": payload_rows,
        "grouping": _build_grouping_metadata(),
    }


def fetch_profile_can_breakdown(
    db: Session,
    *,
    state: str,
    fiscal_year: int | None,
    program_office: str | None,
    aln: str | None,
    can_code: str | None,
    funding_stream: str | None,
    domestic_only: bool | None,
) -> dict[str, Any]:
    filters = _resolve_filters(
        db,
        state=state,
        fiscal_year=fiscal_year,
        program_office=program_office,
        aln=aln,
        can_code=can_code,
        funding_stream=funding_stream,
        domestic_only=domestic_only,
    )
    context = _build_query_context(db)
    where_sql, params = _build_where_sql(filters, context=context, include_state=True)

    rows = db.execute(
        text(
            f"""
            WITH grouped AS (
                SELECT
                    {_display_label_expr(context)} AS display_label,
                    {_funding_stream_expr(context)} AS funding_stream,
                    {_appropriation_type_expr(context)} AS appropriation_type,
                    {_clean_label_expr('s.can_code', 'Unknown CAN')} AS raw_can_code,
                    SUM(COALESCE(s.total_sum_of_actions, 0))::numeric AS amount,
                    COUNT(DISTINCT s.award_number)::integer AS award_count,
                    COUNT(DISTINCT NULLIF(TRIM(s.legal_entity_name), ''))::integer AS unique_recipient_count
                {_base_from_clause()}
                {where_sql}
                GROUP BY
                    {_display_label_expr(context)},
                    {_funding_stream_expr(context)},
                    {_appropriation_type_expr(context)},
                    {_clean_label_expr('s.can_code', 'Unknown CAN')}
            )
            SELECT
                display_label,
                funding_stream,
                appropriation_type,
                raw_can_code,
                amount,
                award_count,
                unique_recipient_count,
                SUM(amount) OVER ()::numeric AS total_amount,
                SUM(amount) OVER (PARTITION BY funding_stream)::numeric AS funding_stream_total
            FROM grouped
            ORDER BY funding_stream_total DESC, funding_stream ASC, amount DESC, raw_can_code ASC
            """
        ),
        params,
    ).mappings().all()

    total_amount = float(_json_number(rows[0].get("total_amount")) or 0) if rows else 0.0
    payload_rows = []
    streams = set()
    for row in rows:
        amount = float(_json_number(row.get("amount")) or 0)
        stream_total = float(_json_number(row.get("funding_stream_total")) or 0)
        if row.get("funding_stream"):
            streams.add(str(row["funding_stream"]))
        payload_rows.append(
            {
                "display_label": row.get("display_label"),
                "funding_stream": row.get("funding_stream"),
                "appropriation_type": row.get("appropriation_type"),
                "raw_can_code": row.get("raw_can_code"),
                "can_code": row.get("raw_can_code"),
                "mapping_status": (
                    "mapped"
                    if _strip_optional(row.get("display_label")) != UNKNOWN_MAPPING_DISPLAY_LABEL
                    else "unresolved"
                ),
                "amount": amount,
                "share_total_pct": (amount / total_amount * 100.0) if total_amount > 0 else 0.0,
                "share_stream_pct": (amount / stream_total * 100.0) if stream_total > 0 else 0.0,
                "award_count": int(row.get("award_count") or 0),
                "unique_recipient_count": int(row.get("unique_recipient_count") or 0),
            }
        )

    return {
        "state": filters.state,
        "fiscal_year": filters.fiscal_year,
        "total_funding": total_amount,
        "funding_stream_count": len(streams),
        "rows": payload_rows,
    }


def fetch_profile_recipients(
    db: Session,
    *,
    state: str,
    fiscal_year: int | None,
    program_office: str | None,
    aln: str | None,
    can_code: str | None,
    funding_stream: str | None,
    domestic_only: bool | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    filters = _resolve_filters(
        db,
        state=state,
        fiscal_year=fiscal_year,
        program_office=program_office,
        aln=aln,
        can_code=can_code,
        funding_stream=funding_stream,
        domestic_only=domestic_only,
    )
    normalized_page = max(1, int(page))
    normalized_page_size = max(1, min(int(page_size), 200))
    offset = (normalized_page - 1) * normalized_page_size

    total_count, rows = _fetch_recipients_rows(
        db,
        filters=filters,
        limit=normalized_page_size,
        offset=offset,
    )
    overall = _fetch_profile_overall_row(db, filters)
    total_funding = float(_json_number(overall.get("total_funding")) or 0)

    payload_rows = []
    for row in rows:
        amount = float(_json_number(row.get("total_funding")) or 0)
        payload_rows.append(
            {
                "recipient_name": row.get("recipient_name"),
                "city": row.get("city"),
                "county": row.get("county"),
                "total_funding": amount,
                "share_pct": (amount / total_funding * 100.0) if total_funding > 0 else 0.0,
                "award_count": int(row.get("award_count") or 0),
            }
        )

    return {
        "state": filters.state,
        "fiscal_year": filters.fiscal_year,
        "page": normalized_page,
        "page_size": normalized_page_size,
        "total_rows": total_count,
        "total_funding": total_funding,
        "rows": payload_rows,
    }


def fetch_profile_counties(
    db: Session,
    *,
    state: str,
    fiscal_year: int | None,
    program_office: str | None,
    aln: str | None,
    can_code: str | None,
    funding_stream: str | None,
    domestic_only: bool | None,
    limit: int,
) -> dict[str, Any]:
    filters = _resolve_filters(
        db,
        state=state,
        fiscal_year=fiscal_year,
        program_office=program_office,
        aln=aln,
        can_code=can_code,
        funding_stream=funding_stream,
        domestic_only=domestic_only,
    )
    normalized_limit = max(1, min(int(limit), 5000))
    context = _build_query_context(db)
    where_sql, params = _build_where_sql(filters, context=context, include_state=True)
    params = {**params, "limit": normalized_limit}

    rows = db.execute(
        text(
            f"""
            WITH grouped AS (
                SELECT
                    {_clean_county_expr('s.legal_entity_county_normalized')} AS county,
                    SUM(COALESCE(s.total_sum_of_actions, 0))::numeric AS amount,
                    COUNT(DISTINCT s.award_number)::integer AS award_count
                {_base_from_clause()}
                {where_sql}
                GROUP BY {_clean_county_expr('s.legal_entity_county_normalized')}
            )
            SELECT
                county,
                amount,
                award_count,
                SUM(amount) OVER ()::numeric AS total_amount
            FROM grouped
            ORDER BY amount DESC, county ASC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()

    total_amount = float(_json_number(rows[0].get("total_amount")) or 0) if rows else 0.0
    undefined_amount = 0.0
    payload_rows = []
    for row in rows:
        county_label = str(row.get("county") or UNKNOWN_COUNTY_LABEL)
        amount = float(_json_number(row.get("amount")) or 0)
        is_unknown = county_label.strip().upper() in UNKNOWN_COUNTY_TOKENS or county_label == UNKNOWN_COUNTY_LABEL
        if is_unknown:
            undefined_amount += amount
        payload_rows.append(
            {
                "county": county_label,
                "total_funding": amount,
                "share_pct": (amount / total_amount * 100.0) if total_amount > 0 else 0.0,
                "award_count": int(row.get("award_count") or 0),
                "is_unknown": is_unknown,
            }
        )

    return {
        "state": filters.state,
        "fiscal_year": filters.fiscal_year,
        "total_funding": total_amount,
        "undefined_county_amount": undefined_amount,
        "rows": payload_rows,
    }


def fetch_profile_details(
    db: Session,
    *,
    state: str,
    fiscal_year: int | None,
    program_office: str | None,
    aln: str | None,
    can_code: str | None,
    funding_stream: str | None,
    domestic_only: bool | None,
    page: int,
    page_size: int,
    sort_by: str,
    sort_dir: str,
) -> dict[str, Any]:
    filters = _resolve_filters(
        db,
        state=state,
        fiscal_year=fiscal_year,
        program_office=program_office,
        aln=aln,
        can_code=can_code,
        funding_stream=funding_stream,
        domestic_only=domestic_only,
    )
    context = _build_query_context(db)
    normalized_page = max(1, int(page))
    normalized_page_size = max(1, min(int(page_size), 200))
    offset = (normalized_page - 1) * normalized_page_size
    normalized_sort_by = _normalize_sort_field(sort_by)
    normalized_sort_dir = _normalize_sort_dir(sort_dir)
    sort_column = VALID_DETAIL_SORT_FIELDS[normalized_sort_by]
    where_sql, params = _build_where_sql(filters, context=context, include_state=True)

    count_row = db.execute(
        text(
            f"""
            SELECT
                COUNT(*)::integer AS total_rows,
                COALESCE(SUM(COALESCE(s.total_sum_of_actions, 0)), 0)::numeric AS total_amount
            {_base_from_clause()}
            {where_sql}
            """
        ),
        params,
    ).mappings().one()

    rows = db.execute(
        text(
            f"""
            WITH filtered AS (
                SELECT
                    {_category_expr(context)} AS category,
                    {_subcategory_expr(context)} AS subcategory,
                    {_display_label_expr(context)} AS display_label,
                    {_clean_label_expr('s.award_title', 'Unspecified award title')} AS award_title,
                    {_clean_label_expr('s.award_description', 'No description supplied')} AS award_description,
                    {_clean_label_expr('s.legal_entity_name', UNKNOWN_RECIPIENT_LABEL)} AS recipient_name,
                    NULLIF(TRIM(s.legal_entity_city), '') AS city,
                    {_clean_county_expr('s.legal_entity_county_normalized')} AS county,
                    NULLIF(TRIM(s.award_number), '') AS award_number,
                    NULLIF(TRIM(s.aln), '') AS aln,
                    NULLIF(TRIM(s.can_code), '') AS raw_can_code,
                    {_funding_stream_expr(context)} AS funding_stream,
                    {_appropriation_type_expr(context)} AS appropriation_type,
                    s.funding_fiscal_year,
                    COALESCE(s.total_sum_of_actions, 0)::numeric AS amount
                {_base_from_clause()}
                {where_sql}
            ),
            ordered AS (
                SELECT
                    ROW_NUMBER() OVER (ORDER BY {sort_column} {normalized_sort_dir}, award_number ASC NULLS LAST) AS line_number,
                    *
                FROM filtered
            )
            SELECT
                line_number,
                category,
                subcategory,
                award_title,
                award_description,
                recipient_name,
                city,
                county,
                award_number,
                aln,
                raw_can_code,
                display_label,
                funding_stream,
                appropriation_type,
                funding_fiscal_year,
                amount
            FROM ordered
            ORDER BY line_number
            LIMIT :limit
            OFFSET :offset
            """
        ),
        {**params, "limit": normalized_page_size, "offset": offset},
    ).mappings().all()

    payload_rows = []
    for row in rows:
        payload_rows.append(
            {
                "line_number": int(row.get("line_number") or 0),
                "category": row.get("category"),
                "subcategory": row.get("subcategory"),
                "award_title": row.get("award_title"),
                "award_description": row.get("award_description"),
                "recipient_name": row.get("recipient_name"),
                "city": row.get("city"),
                "county": row.get("county"),
                "award_number": row.get("award_number"),
                "aln": row.get("aln"),
                "raw_can_code": row.get("raw_can_code"),
                "can_code": row.get("raw_can_code"),
                "display_label": row.get("display_label"),
                "mapping_status": (
                    "mapped"
                    if _strip_optional(row.get("display_label")) != UNKNOWN_MAPPING_DISPLAY_LABEL
                    else "unresolved"
                ),
                "funding_stream": row.get("funding_stream"),
                "appropriation_type": row.get("appropriation_type"),
                "issue_fiscal_year": row.get("funding_fiscal_year"),
                "amount": float(_json_number(row.get("amount")) or 0),
            }
        )

    return {
        "state": filters.state,
        "fiscal_year": filters.fiscal_year,
        "page": normalized_page,
        "page_size": normalized_page_size,
        "sort_by": normalized_sort_by,
        "sort_dir": normalized_sort_dir,
        "total_rows": int(count_row.get("total_rows") or 0),
        "total_funding": float(_json_number(count_row.get("total_amount")) or 0),
        "rows": payload_rows,
    }


def export_profile_details_csv(
    db: Session,
    *,
    state: str,
    fiscal_year: int | None,
    program_office: str | None,
    aln: str | None,
    can_code: str | None,
    funding_stream: str | None,
    domestic_only: bool | None,
    sort_by: str,
    sort_dir: str,
) -> tuple[str, str]:
    detail_payload = fetch_profile_details(
        db,
        state=state,
        fiscal_year=fiscal_year,
        program_office=program_office,
        aln=aln,
        can_code=can_code,
        funding_stream=funding_stream,
        domestic_only=domestic_only,
        page=1,
        page_size=200,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )

    total_rows = int(detail_payload.get("total_rows") or 0)
    rows = list(detail_payload.get("rows") or [])
    while len(rows) < total_rows:
        next_page = (len(rows) // 200) + 1
        page_payload = fetch_profile_details(
            db,
            state=state,
            fiscal_year=fiscal_year,
            program_office=program_office,
            aln=aln,
            can_code=can_code,
            funding_stream=funding_stream,
            domestic_only=domestic_only,
            page=next_page,
            page_size=200,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        next_rows = list(page_payload.get("rows") or [])
        if not next_rows:
            break
        rows.extend(next_rows)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "line_number",
            "display_label",
            "category",
            "subcategory",
            "award_title",
            "award_description",
            "recipient_name",
            "city",
            "county",
            "award_number",
            "aln",
            "raw_can_code",
            "can_code",
            "funding_stream",
            "mapping_status",
            "appropriation_type",
            "issue_fiscal_year",
            "amount",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.get("line_number"),
                row.get("display_label"),
                row.get("category"),
                row.get("subcategory"),
                row.get("award_title"),
                row.get("award_description"),
                row.get("recipient_name"),
                row.get("city"),
                row.get("county"),
                row.get("award_number"),
                row.get("aln"),
                row.get("raw_can_code"),
                row.get("can_code"),
                row.get("funding_stream"),
                row.get("mapping_status"),
                row.get("appropriation_type"),
                row.get("issue_fiscal_year"),
                row.get("amount"),
            ]
        )

    scope_suffix = "domestic" if _normalize_domestic_only(domestic_only) else "all_scope"
    filename = f"taggs_funding_profile_{str(state).strip().upper()}_fy{detail_payload.get('fiscal_year')}_{scope_suffix}.csv"
    return filename, buffer.getvalue()
