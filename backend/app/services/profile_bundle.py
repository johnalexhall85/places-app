from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import math
import re
from statistics import mean
from typing import Any, Literal

from sqlalchemy import String, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from app.services.hpsa_summary import (
    build_hpsa_county_domain_detail,
    build_hpsa_response,
    fetch_county_hpsa_row,
    fetch_hpsa_domain_quartiles,
    fetch_hpsa_domain_ratio_fields,
)
from app.services.profile_builder import _sanitize_for_json

ProfileGeography = Literal["county", "tract"]

_YEAR_WINDOW_PATTERN = re.compile(r"^(\d{4})\s*-\s*(\d{4})$")
_FINITE_FLOAT_SQL = (
    "NOT IN ('NaN'::double precision, 'Infinity'::double precision, '-Infinity'::double precision)"
)

_HPSA_DOMAIN_LABELS = {
    "pc": "Primary Care",
    "mh": "Mental Health",
    "dh": "Dental",
}

_HPSA_TIER_LABELS = {
    1: "Tier 1 (lower shortage severity among designated counties)",
    2: "Tier 2",
    3: "Tier 3",
    4: "Tier 4 (highest shortage severity quartile)",
}


class ProfileBundleError(ValueError):
    pass


@dataclass(slots=True)
class _ResolvedGeo:
    geography: ProfileGeography
    location_id: str
    county_fips: str
    tract_geoid: str | None
    name: str
    county_name: str | None
    state_abbr: str | None
    state_name: str | None
    state_fips: str | None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _format_number(value: float | None, unit: str | None, precision: int = 1) -> str:
    if value is None:
        return "Not available"
    normalized_unit = str(unit or "").strip()
    if normalized_unit in {"%", "percent", "Percent", "percentage", "pct"}:
        return f"{value:.{precision}f}%"
    if normalized_unit:
        return f"{value:.{precision}f} {normalized_unit}"
    return f"{value:.{precision}f}"


def _year_window_sort_key(value: str) -> tuple[int, int, str]:
    matched = _YEAR_WINDOW_PATTERN.match(str(value or "").strip())
    if not matched:
        return (-1, -1, str(value or ""))
    start = int(matched.group(1))
    end = int(matched.group(2))
    return (end, start, str(value))


def _normalize_county_fips(value: Any) -> str | None:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    if not digits:
        return None
    if len(digits) == 5:
        return digits
    if len(digits) < 5:
        return digits.zfill(5)
    return None


def _normalize_tract_geoid(value: Any) -> str | None:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    if not digits:
        return None
    if len(digits) == 11:
        return digits
    if len(digits) > 11:
        return digits[-11:]
    return None


def _coalesce_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text_value = str(value).strip()
        if text_value:
            return text_value
    return None


def _resolve_county_geo(db: Session, county_fips: str) -> _ResolvedGeo:
    normalized_fips = _normalize_county_fips(county_fips)
    if normalized_fips is None:
        raise ProfileBundleError("county_fips must be a valid 5-digit county FIPS.")

    row = db.execute(
        text(
            """
            SELECT
                location_id,
                county_name,
                state_abbr,
                state_desc
            FROM dim_county
            WHERE location_id = :location_id
            LIMIT 1
            """
        ),
        {"location_id": normalized_fips},
    ).mappings().one_or_none()
    if row is None:
        raise ProfileBundleError(f"County {normalized_fips} was not found.")

    county_name = _coalesce_text(row.get("county_name"), normalized_fips)
    state_abbr = _coalesce_text(row.get("state_abbr"))
    state_name = _coalesce_text(row.get("state_desc"))
    state_fips = normalized_fips[:2]
    return _ResolvedGeo(
        geography="county",
        location_id=normalized_fips,
        county_fips=normalized_fips,
        tract_geoid=None,
        name=county_name or normalized_fips,
        county_name=county_name,
        state_abbr=state_abbr,
        state_name=state_name,
        state_fips=state_fips,
    )


def _resolve_tract_geo(db: Session, tract_geoid: str) -> _ResolvedGeo:
    normalized_geoid = _normalize_tract_geoid(tract_geoid)
    if normalized_geoid is None:
        raise ProfileBundleError("tract_geoid must be a valid 11-digit tract GEOID.")

    row = db.execute(
        text(
            """
            WITH tract_meta AS (
                SELECT
                    locationid AS tract_geoid,
                    county_fips,
                    county_name,
                    state_abbr,
                    state_desc,
                    location_name,
                    year
                FROM tract_estimates
                WHERE locationid = :tract_geoid
                ORDER BY year DESC
                LIMIT 1
            )
            SELECT
                tract_geoid,
                county_fips,
                county_name,
                state_abbr,
                state_desc,
                location_name
            FROM tract_meta
            """
        ),
        {"tract_geoid": normalized_geoid},
    ).mappings().one_or_none()

    if row is None:
        row = db.execute(
            text(
                """
                SELECT
                    location_id AS tract_geoid,
                    substring(location_id from 1 for 5) AS county_fips,
                    NULL::text AS county_name,
                    state_abbr,
                    NULL::text AS state_desc,
                    location_name
                FROM acs_nmf_tract_estimates
                WHERE location_id = :tract_geoid
                ORDER BY year_window DESC
                LIMIT 1
                """
            ),
            {"tract_geoid": normalized_geoid},
        ).mappings().one_or_none()

    if row is None:
        raise ProfileBundleError(f"Tract {normalized_geoid} was not found.")

    county_fips = _normalize_county_fips(row.get("county_fips") or normalized_geoid[:5])
    if county_fips is None:
        county_fips = normalized_geoid[:5]
    county_name = _coalesce_text(row.get("county_name"))
    state_abbr = _coalesce_text(row.get("state_abbr"))
    state_name = _coalesce_text(row.get("state_desc"))
    tract_name = _coalesce_text(row.get("location_name"), f"Census Tract {normalized_geoid}")

    return _ResolvedGeo(
        geography="tract",
        location_id=normalized_geoid,
        county_fips=county_fips,
        tract_geoid=normalized_geoid,
        name=tract_name or normalized_geoid,
        county_name=county_name,
        state_abbr=state_abbr,
        state_name=state_name,
        state_fips=county_fips[:2] if county_fips else normalized_geoid[:2],
    )


def _resolve_places_snapshot(
    db: Session,
    *,
    geography: ProfileGeography,
    location_id: str,
) -> tuple[int, str]:
    if geography == "county":
        year_row = db.execute(
            text(
                """
                SELECT MAX(year) AS places_year
                FROM fact_estimate_county
                WHERE location_id = :location_id
                """
            ),
            {"location_id": location_id},
        ).mappings().one()
        places_year = _safe_int(year_row.get("places_year"))
        if places_year is None:
            raise ProfileBundleError(f"No PLACES county rows were found for county {location_id}.")
        rows = db.execute(
            text(
                """
                SELECT DISTINCT dm.data_value_type_id
                FROM fact_estimate_county AS f
                INNER JOIN dim_measure AS dm ON dm.id = f.measure_dim_id
                WHERE f.location_id = :location_id
                  AND f.year = :year
                  AND dm.data_value_type_id IS NOT NULL
                """
            ),
            {"location_id": location_id, "year": places_year},
        ).scalars().all()
    else:
        year_row = db.execute(
            text(
                """
                SELECT MAX(year) AS places_year
                FROM tract_estimates
                WHERE locationid = :location_id
                """
            ),
            {"location_id": location_id},
        ).mappings().one()
        places_year = _safe_int(year_row.get("places_year"))
        if places_year is None:
            raise ProfileBundleError(f"No PLACES tract rows were found for tract {location_id}.")
        rows = db.execute(
            text(
                """
                SELECT DISTINCT data_value_type_id
                FROM tract_estimates
                WHERE locationid = :location_id
                  AND year = :year
                  AND data_value_type_id IS NOT NULL
                """
            ),
            {"location_id": location_id, "year": places_year},
        ).scalars().all()

    available_types = sorted(str(value) for value in rows if value is not None)
    if "CrdPrv" in available_types:
        return places_year, "CrdPrv"
    if "AgeAdjPrv" in available_types:
        return places_year, "AgeAdjPrv"
    if available_types:
        return places_year, available_types[0]
    return places_year, "CrdPrv"


def _resolve_acs_snapshot(
    db: Session,
    *,
    geography: ProfileGeography,
    location_id: str,
) -> tuple[str | None, str | None]:
    table_name = "acs_nmf_county_estimates" if geography == "county" else "acs_nmf_tract_estimates"
    year_rows = db.execute(
        text(
            f"""
            SELECT DISTINCT year_window
            FROM {table_name}
            WHERE location_id = :location_id
              AND year_window IS NOT NULL
            """
        ),
        {"location_id": location_id},
    ).scalars().all()
    year_windows = sorted((str(value) for value in year_rows if value is not None), key=_year_window_sort_key, reverse=True)
    if not year_windows:
        return None, None
    year_window = year_windows[0]

    dtype_rows = db.execute(
        text(
            f"""
            SELECT DISTINCT data_value_type_id
            FROM {table_name}
            WHERE location_id = :location_id
              AND year_window = :year_window
              AND data_value_type_id IS NOT NULL
            """
        ),
        {"location_id": location_id, "year_window": year_window},
    ).scalars().all()
    available_types = sorted(str(value) for value in dtype_rows if value is not None)
    if "Percent" in available_types:
        return year_window, "Percent"
    if available_types:
        return year_window, available_types[0]
    return year_window, None


def _resolve_svi_snapshot(
    db: Session,
    *,
    geography: ProfileGeography,
    location_id: str,
) -> int | None:
    table_name = "svi_estimates_county" if geography == "county" else "svi_estimates_tract"
    year_row = db.execute(
        text(
            f"""
            SELECT MAX(year) AS svi_year
            FROM {table_name}
            WHERE geoid = :location_id
            """
        ),
        {"location_id": location_id},
    ).mappings().one()
    return _safe_int(year_row.get("svi_year"))


def _query_county_places_rows(
    db: Session,
    *,
    county_fips: str,
    state_abbr: str | None,
    year: int,
    data_value_type_id: str,
) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            WITH state_agg AS (
                SELECT
                    f.measure_dim_id,
                    AVG(f.data_value) FILTER (
                        WHERE f.data_value IS NOT NULL
                          AND f.data_value {_FINITE_FLOAT_SQL}
                    ) AS state_value,
                    AVG(f.low_confidence_limit) FILTER (
                        WHERE f.low_confidence_limit IS NOT NULL
                          AND f.low_confidence_limit {_FINITE_FLOAT_SQL}
                    ) AS state_low,
                    AVG(f.high_confidence_limit) FILTER (
                        WHERE f.high_confidence_limit IS NOT NULL
                          AND f.high_confidence_limit {_FINITE_FLOAT_SQL}
                    ) AS state_high,
                    COUNT(*) FILTER (
                        WHERE f.data_value IS NOT NULL
                          AND f.data_value {_FINITE_FLOAT_SQL}
                    )::integer AS state_n
                FROM fact_estimate_county AS f
                INNER JOIN dim_county AS dc ON dc.location_id = f.location_id
                WHERE f.year = :year
                  AND dc.state_abbr = :state_abbr
                GROUP BY f.measure_dim_id
            ),
            us_agg AS (
                SELECT
                    f.measure_dim_id,
                    AVG(f.data_value) FILTER (
                        WHERE f.data_value IS NOT NULL
                          AND f.data_value {_FINITE_FLOAT_SQL}
                    ) AS us_value,
                    AVG(f.low_confidence_limit) FILTER (
                        WHERE f.low_confidence_limit IS NOT NULL
                          AND f.low_confidence_limit {_FINITE_FLOAT_SQL}
                    ) AS us_low,
                    AVG(f.high_confidence_limit) FILTER (
                        WHERE f.high_confidence_limit IS NOT NULL
                          AND f.high_confidence_limit {_FINITE_FLOAT_SQL}
                    ) AS us_high,
                    COUNT(*) FILTER (
                        WHERE f.data_value IS NOT NULL
                          AND f.data_value {_FINITE_FLOAT_SQL}
                    )::integer AS us_n
                FROM fact_estimate_county AS f
                WHERE f.year = :year
                GROUP BY f.measure_dim_id
            )
            SELECT
                dm.category_id,
                dm.category,
                dm.measure_id,
                dm.measure,
                dm.short_question_text,
                dm.unit,
                dm.data_value_type_id,
                dm.data_value_type,
                f.data_value AS local_value,
                f.low_confidence_limit AS local_low,
                f.high_confidence_limit AS local_high,
                sa.state_value,
                sa.state_low,
                sa.state_high,
                sa.state_n,
                ua.us_value,
                ua.us_low,
                ua.us_high,
                ua.us_n
            FROM dim_measure AS dm
            LEFT JOIN fact_estimate_county AS f
                ON f.measure_dim_id = dm.id
               AND f.location_id = :location_id
               AND f.year = :year
            LEFT JOIN state_agg AS sa
                ON sa.measure_dim_id = dm.id
            LEFT JOIN us_agg AS ua
                ON ua.measure_dim_id = dm.id
            WHERE dm.data_value_type_id = :data_value_type_id
            ORDER BY dm.category, dm.measure, dm.measure_id
            """
        ),
        {
            "location_id": county_fips,
            "state_abbr": state_abbr,
            "year": year,
            "data_value_type_id": data_value_type_id,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _query_tract_places_rows(
    db: Session,
    *,
    tract_geoid: str,
    state_abbr: str | None,
    year: int,
    data_value_type_id: str,
) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            WITH catalog AS (
                SELECT DISTINCT
                    t.category_id,
                    t.category,
                    t.measure_id,
                    t.measure,
                    t.short_question_text,
                    t.data_value_unit AS unit
                FROM tract_estimates AS t
                WHERE t.year = :year
                  AND t.data_value_type_id = :data_value_type_id
            ),
            local_rows AS (
                SELECT DISTINCT ON (t.measure_id)
                    t.measure_id,
                    t.data_value AS local_value,
                    t.low_confidence_limit AS local_low,
                    t.high_confidence_limit AS local_high
                FROM tract_estimates AS t
                WHERE t.locationid = :location_id
                  AND t.year = :year
                  AND t.data_value_type_id = :data_value_type_id
                ORDER BY t.measure_id
            ),
            state_agg AS (
                SELECT
                    t.measure_id,
                    AVG(t.data_value) FILTER (
                        WHERE t.data_value IS NOT NULL
                          AND t.data_value {_FINITE_FLOAT_SQL}
                    ) AS state_value,
                    AVG(t.low_confidence_limit) FILTER (
                        WHERE t.low_confidence_limit IS NOT NULL
                          AND t.low_confidence_limit {_FINITE_FLOAT_SQL}
                    ) AS state_low,
                    AVG(t.high_confidence_limit) FILTER (
                        WHERE t.high_confidence_limit IS NOT NULL
                          AND t.high_confidence_limit {_FINITE_FLOAT_SQL}
                    ) AS state_high,
                    COUNT(*) FILTER (
                        WHERE t.data_value IS NOT NULL
                          AND t.data_value {_FINITE_FLOAT_SQL}
                    )::integer AS state_n
                FROM tract_estimates AS t
                WHERE t.year = :year
                  AND t.data_value_type_id = :data_value_type_id
                  AND t.state_abbr = :state_abbr
                GROUP BY t.measure_id
            ),
            us_agg AS (
                SELECT
                    t.measure_id,
                    AVG(t.data_value) FILTER (
                        WHERE t.data_value IS NOT NULL
                          AND t.data_value {_FINITE_FLOAT_SQL}
                    ) AS us_value,
                    AVG(t.low_confidence_limit) FILTER (
                        WHERE t.low_confidence_limit IS NOT NULL
                          AND t.low_confidence_limit {_FINITE_FLOAT_SQL}
                    ) AS us_low,
                    AVG(t.high_confidence_limit) FILTER (
                        WHERE t.high_confidence_limit IS NOT NULL
                          AND t.high_confidence_limit {_FINITE_FLOAT_SQL}
                    ) AS us_high,
                    COUNT(*) FILTER (
                        WHERE t.data_value IS NOT NULL
                          AND t.data_value {_FINITE_FLOAT_SQL}
                    )::integer AS us_n
                FROM tract_estimates AS t
                WHERE t.year = :year
                  AND t.data_value_type_id = :data_value_type_id
                GROUP BY t.measure_id
            )
            SELECT
                c.category_id,
                c.category,
                c.measure_id,
                c.measure,
                c.short_question_text,
                c.unit,
                :data_value_type_id AS data_value_type_id,
                CASE
                    WHEN :data_value_type_id = 'CrdPrv' THEN 'Crude Prevalence'
                    WHEN :data_value_type_id = 'AgeAdjPrv' THEN 'Age-adjusted Prevalence'
                    ELSE :data_value_type_id
                END AS data_value_type,
                l.local_value,
                l.local_low,
                l.local_high,
                sa.state_value,
                sa.state_low,
                sa.state_high,
                sa.state_n,
                ua.us_value,
                ua.us_low,
                ua.us_high,
                ua.us_n
            FROM catalog AS c
            LEFT JOIN local_rows AS l ON l.measure_id = c.measure_id
            LEFT JOIN state_agg AS sa ON sa.measure_id = c.measure_id
            LEFT JOIN us_agg AS ua ON ua.measure_id = c.measure_id
            ORDER BY c.category, c.measure, c.measure_id
            """
        ),
        {
            "location_id": tract_geoid,
            "state_abbr": state_abbr,
            "year": year,
            "data_value_type_id": data_value_type_id,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _build_places_section(
    db: Session,
    *,
    geo: _ResolvedGeo,
    places_year: int,
    places_data_value_type_id: str,
) -> dict[str, Any]:
    if geo.geography == "county":
        raw_rows = _query_county_places_rows(
            db,
            county_fips=geo.county_fips,
            state_abbr=geo.state_abbr,
            year=places_year,
            data_value_type_id=places_data_value_type_id,
        )
    else:
        raw_rows = _query_tract_places_rows(
            db,
            tract_geoid=geo.location_id,
            state_abbr=geo.state_abbr,
            year=places_year,
            data_value_type_id=places_data_value_type_id,
        )

    measures: list[dict[str, Any]] = []
    for row in raw_rows:
        local_value = _safe_float(row.get("local_value"))
        state_value = _safe_float(row.get("state_value"))
        us_value = _safe_float(row.get("us_value"))
        measures.append(
            {
                "measure_id": _coalesce_text(row.get("measure_id")) or "",
                "measure": _coalesce_text(row.get("measure"), row.get("measure_id")) or "",
                "short_question_text": _coalesce_text(row.get("short_question_text")),
                "category_id": _coalesce_text(row.get("category_id")),
                "category": _coalesce_text(row.get("category")),
                "data_value_type_id": _coalesce_text(row.get("data_value_type_id")) or places_data_value_type_id,
                "data_value_type": _coalesce_text(row.get("data_value_type"), places_data_value_type_id),
                "unit": _coalesce_text(row.get("unit")),
                "local": {
                    "value": local_value,
                    "low_confidence_limit": _safe_float(row.get("local_low")),
                    "high_confidence_limit": _safe_float(row.get("local_high")),
                },
                "comparisons": {
                    "state": {
                        "value": state_value,
                        "low_confidence_limit": _safe_float(row.get("state_low")),
                        "high_confidence_limit": _safe_float(row.get("state_high")),
                        "available": state_value is not None,
                        "n": _safe_int(row.get("state_n")),
                        "method": "mean_aggregate",
                    },
                    "us": {
                        "value": us_value,
                        "low_confidence_limit": _safe_float(row.get("us_low")),
                        "high_confidence_limit": _safe_float(row.get("us_high")),
                        "available": us_value is not None,
                        "n": _safe_int(row.get("us_n")),
                        "method": "mean_aggregate",
                    },
                },
                "deltas": {
                    "vs_state": (local_value - state_value) if local_value is not None and state_value is not None else None,
                    "vs_us": (local_value - us_value) if local_value is not None and us_value is not None else None,
                },
            }
        )

    measures.sort(
        key=lambda item: (
            str(item.get("category") or "").lower(),
            str(item.get("measure") or "").lower(),
            str(item.get("measure_id") or "").lower(),
        )
    )

    top_concerns = [
        measure for measure in measures
        if _safe_float(measure.get("local", {}).get("value")) is not None
    ]
    top_concerns.sort(
        key=lambda item: float(item["local"]["value"]),  # type: ignore[index]
        reverse=True,
    )
    top_concerns = top_concerns[:8]

    grouped_categories: dict[str, dict[str, Any]] = {}
    for measure in measures:
        category = _coalesce_text(measure.get("category"), "Uncategorized") or "Uncategorized"
        if category not in grouped_categories:
            grouped_categories[category] = {
                "category": category,
                "category_id": _coalesce_text(measure.get("category_id")),
                "measure_ids": [],
                "measure_count": 0,
            }
        grouped_categories[category]["measure_ids"].append(measure.get("measure_id"))
        grouped_categories[category]["measure_count"] = int(grouped_categories[category]["measure_count"]) + 1

    has_state_comparison = any(
        bool(measure.get("comparisons", {}).get("state", {}).get("available"))
        for measure in measures
    )
    has_us_comparison = any(
        bool(measure.get("comparisons", {}).get("us", {}).get("available"))
        for measure in measures
    )

    return {
        "year": places_year,
        "data_value_type_id": places_data_value_type_id,
        "measure_count": len(measures),
        "comparison_availability": {
            "state": has_state_comparison,
            "us": has_us_comparison,
        },
        "top_concerns": top_concerns,
        "categories": sorted(grouped_categories.values(), key=lambda item: str(item["category"]).lower()),
        "measures": measures,
    }


def _build_acs_section(
    db: Session,
    *,
    geo: _ResolvedGeo,
    year_window: str | None,
    data_value_type_id: str | None,
) -> dict[str, Any]:
    if not year_window or not data_value_type_id:
        return {
            "year_window": year_window,
            "data_value_type_id": data_value_type_id,
            "factor_count": 0,
            "comparison_availability": {"state": False, "us": False},
            "factors": [],
            "top_context_tiles": [],
        }

    table_name = "acs_nmf_county_estimates" if geo.geography == "county" else "acs_nmf_tract_estimates"
    rows = db.execute(
        text(
            f"""
            WITH local_rows AS (
                SELECT
                    location_id,
                    measure_id,
                    measure,
                    category_id,
                    category,
                    data_value_type_id,
                    data_value_type,
                    data_value_unit,
                    data_value AS local_value,
                    moe AS local_moe
                FROM {table_name}
                WHERE location_id = :location_id
                  AND year_window = :year_window
                  AND data_value_type_id = :data_value_type_id
            ),
            state_agg AS (
                SELECT
                    measure_id,
                    AVG(data_value) FILTER (
                        WHERE data_value IS NOT NULL
                          AND data_value {_FINITE_FLOAT_SQL}
                    ) AS state_value,
                    COUNT(*) FILTER (
                        WHERE data_value IS NOT NULL
                          AND data_value {_FINITE_FLOAT_SQL}
                    )::integer AS state_n
                FROM {table_name}
                WHERE year_window = :year_window
                  AND data_value_type_id = :data_value_type_id
                  AND state_abbr = :state_abbr
                GROUP BY measure_id
            ),
            us_agg AS (
                SELECT
                    measure_id,
                    AVG(data_value) FILTER (
                        WHERE data_value IS NOT NULL
                          AND data_value {_FINITE_FLOAT_SQL}
                    ) AS us_value,
                    COUNT(*) FILTER (
                        WHERE data_value IS NOT NULL
                          AND data_value {_FINITE_FLOAT_SQL}
                    )::integer AS us_n
                FROM {table_name}
                WHERE year_window = :year_window
                  AND data_value_type_id = :data_value_type_id
                GROUP BY measure_id
            ),
            quintiles AS (
                SELECT
                    measure_id,
                    location_id,
                    ntile(5) OVER (
                        PARTITION BY measure_id
                        ORDER BY data_value
                    ) AS us_quintile
                FROM {table_name}
                WHERE year_window = :year_window
                  AND data_value_type_id = :data_value_type_id
                  AND data_value IS NOT NULL
                  AND data_value {_FINITE_FLOAT_SQL}
            )
            SELECT
                l.measure_id,
                l.measure,
                l.category_id,
                l.category,
                l.data_value_type_id,
                l.data_value_type,
                l.data_value_unit,
                l.local_value,
                l.local_moe,
                sa.state_value,
                sa.state_n,
                ua.us_value,
                ua.us_n,
                q.us_quintile
            FROM local_rows AS l
            LEFT JOIN state_agg AS sa ON sa.measure_id = l.measure_id
            LEFT JOIN us_agg AS ua ON ua.measure_id = l.measure_id
            LEFT JOIN quintiles AS q
                ON q.measure_id = l.measure_id
               AND q.location_id = l.location_id
            ORDER BY l.category, l.measure, l.measure_id
            """
        ),
        {
            "location_id": geo.location_id,
            "state_abbr": geo.state_abbr,
            "year_window": year_window,
            "data_value_type_id": data_value_type_id,
        },
    ).mappings().all()

    factors: list[dict[str, Any]] = []
    for row in rows:
        local_value = _safe_float(row.get("local_value"))
        state_value = _safe_float(row.get("state_value"))
        us_value = _safe_float(row.get("us_value"))
        factors.append(
            {
                "measure_id": _coalesce_text(row.get("measure_id")) or "",
                "measure": _coalesce_text(row.get("measure"), row.get("measure_id")) or "",
                "category_id": _coalesce_text(row.get("category_id")),
                "category": _coalesce_text(row.get("category")),
                "data_value_type_id": _coalesce_text(row.get("data_value_type_id")) or data_value_type_id,
                "data_value_type": _coalesce_text(row.get("data_value_type"), data_value_type_id),
                "unit": _coalesce_text(row.get("data_value_unit")),
                "local": {
                    "value": local_value,
                    "moe": _safe_float(row.get("local_moe")),
                },
                "comparisons": {
                    "state": {
                        "value": state_value,
                        "available": state_value is not None,
                        "n": _safe_int(row.get("state_n")),
                        "method": "mean_aggregate",
                    },
                    "us": {
                        "value": us_value,
                        "available": us_value is not None,
                        "n": _safe_int(row.get("us_n")),
                        "method": "mean_aggregate",
                    },
                },
                "us_quintile": _safe_int(row.get("us_quintile")),
                "deltas": {
                    "vs_state": (local_value - state_value) if local_value is not None and state_value is not None else None,
                    "vs_us": (local_value - us_value) if local_value is not None and us_value is not None else None,
                },
            }
        )

    factors.sort(
        key=lambda item: (
            str(item.get("category") or "").lower(),
            str(item.get("measure") or "").lower(),
        )
    )

    context_tiles = [
        factor for factor in factors
        if _safe_float(factor.get("local", {}).get("value")) is not None
    ]
    context_tiles.sort(
        key=lambda item: abs(
            _safe_float(item.get("deltas", {}).get("vs_us")) or _safe_float(item.get("deltas", {}).get("vs_state")) or 0.0
        ),
        reverse=True,
    )

    has_state = any(bool(factor.get("comparisons", {}).get("state", {}).get("available")) for factor in factors)
    has_us = any(bool(factor.get("comparisons", {}).get("us", {}).get("available")) for factor in factors)

    return {
        "year_window": year_window,
        "data_value_type_id": data_value_type_id,
        "factor_count": len(factors),
        "comparison_availability": {
            "state": has_state,
            "us": has_us,
        },
        "top_context_tiles": context_tiles[:6],
        "factors": factors,
    }


def _build_svi_section(
    db: Session,
    *,
    geo: _ResolvedGeo,
    svi_year: int | None,
) -> dict[str, Any]:
    if svi_year is None:
        return {
            "year": None,
            "available": False,
            "interpretation": "SVI percentile data were not available for this geography.",
            "overall": None,
            "themes": [],
            "state_comparison_available": False,
        }

    table_name = "svi_estimates_county" if geo.geography == "county" else "svi_estimates_tract"
    measure_ids = ["RPL_THEMES", "RPL_THEME1", "RPL_THEME2", "RPL_THEME3", "RPL_THEME4"]

    rows = db.execute(
        text(
            f"""
            WITH local AS (
                SELECT
                    e.measure_id,
                    e.value AS local_value
                FROM {table_name} AS e
                WHERE e.geoid = :location_id
                  AND e.year = :year
                  AND e.measure_id = ANY(:measure_ids)
            ),
            state_dist AS (
                SELECT
                    e.measure_id,
                    e.value
                FROM {table_name} AS e
                WHERE e.year = :year
                  AND e.measure_id = ANY(:measure_ids)
                  AND substring(e.geoid from 1 for 2) = :state_fips
                  AND e.value IS NOT NULL
                  AND e.value {_FINITE_FLOAT_SQL}
            ),
            state_stats AS (
                SELECT
                    measure_id,
                    AVG(value) AS state_avg,
                    COUNT(*)::integer AS state_n
                FROM state_dist
                GROUP BY measure_id
            ),
            us_stats AS (
                SELECT
                    e.measure_id,
                    AVG(e.value) FILTER (
                        WHERE e.value IS NOT NULL
                          AND e.value {_FINITE_FLOAT_SQL}
                    ) AS us_avg,
                    COUNT(*) FILTER (
                        WHERE e.value IS NOT NULL
                          AND e.value {_FINITE_FLOAT_SQL}
                    )::integer AS us_n
                FROM {table_name} AS e
                WHERE e.year = :year
                  AND e.measure_id = ANY(:measure_ids)
                GROUP BY e.measure_id
            ),
            state_percentiles AS (
                SELECT
                    l.measure_id,
                    CASE
                        WHEN l.local_value IS NULL THEN NULL
                        WHEN ss.state_n IS NULL OR ss.state_n = 0 THEN NULL
                        ELSE (
                            SELECT COUNT(*)::float / ss.state_n::float
                            FROM state_dist sd
                            WHERE sd.measure_id = l.measure_id
                              AND sd.value <= l.local_value
                        )
                    END AS state_percentile
                FROM local l
                LEFT JOIN state_stats ss ON ss.measure_id = l.measure_id
            )
            SELECT
                l.measure_id,
                COALESCE(sm.name, l.measure_id) AS measure_name,
                sm.theme,
                l.local_value,
                ss.state_avg,
                ss.state_n,
                sp.state_percentile,
                us.us_avg,
                us.us_n
            FROM local AS l
            LEFT JOIN svi_measures AS sm
                ON sm.measure_id = l.measure_id
               AND sm.year = :year
               AND sm.geography_level = :geography_level
            LEFT JOIN state_stats AS ss ON ss.measure_id = l.measure_id
            LEFT JOIN state_percentiles AS sp ON sp.measure_id = l.measure_id
            LEFT JOIN us_stats AS us ON us.measure_id = l.measure_id
            ORDER BY l.measure_id
            """
        ).bindparams(bindparam("measure_ids", type_=ARRAY(String))),
        {
            "location_id": geo.location_id,
            "measure_ids": measure_ids,
            "year": svi_year,
            "state_fips": geo.state_fips,
            "geography_level": geo.geography,
        },
    ).mappings().all()

    if not rows:
        return {
            "year": svi_year,
            "available": False,
            "interpretation": "SVI percentile data were not available for this geography and year.",
            "overall": None,
            "themes": [],
            "state_comparison_available": False,
        }

    items: dict[str, dict[str, Any]] = {}
    for row in rows:
        measure_id = _coalesce_text(row.get("measure_id")) or ""
        items[measure_id] = {
            "measure_id": measure_id,
            "measure_name": _coalesce_text(row.get("measure_name"), measure_id) or measure_id,
            "theme": _coalesce_text(row.get("theme")),
            "value": _safe_float(row.get("local_value")),
            "comparisons": {
                "state": {
                    "value": _safe_float(row.get("state_avg")),
                    "n": _safe_int(row.get("state_n")),
                    "state_percentile": _safe_float(row.get("state_percentile")),
                    "available": _safe_float(row.get("state_percentile")) is not None,
                    "method": "within_state_distribution",
                },
                "us": {
                    "value": _safe_float(row.get("us_avg")),
                    "n": _safe_int(row.get("us_n")),
                    "available": _safe_float(row.get("us_avg")) is not None,
                    "method": "national_distribution_mean",
                },
            },
            "interpretation": "Higher percentile indicates higher social vulnerability relative to other U.S. geographies.",
        }

    overall = items.get("RPL_THEMES")
    themes = [
        items[measure_id]
        for measure_id in ["RPL_THEME1", "RPL_THEME2", "RPL_THEME3", "RPL_THEME4"]
        if measure_id in items
    ]

    has_state = any(
        bool(item.get("comparisons", {}).get("state", {}).get("available"))
        for item in items.values()
    )

    return {
        "year": svi_year,
        "available": True,
        "interpretation": "SVI values are national percentiles; higher percentile = higher vulnerability.",
        "overall": overall,
        "themes": themes,
        "state_comparison_available": has_state,
    }


def _build_hpsa_section(
    db: Session,
    *,
    geo: _ResolvedGeo,
) -> dict[str, Any]:
    county_row = fetch_county_hpsa_row(db, geo.county_fips)
    if geo.geography == "tract":
        overlap_caveat: str | None = None
        if county_row is not None:
            summary = build_hpsa_response(county_row, include_legacy=False)
            methodology = summary.get("methodology") if isinstance(summary, dict) else {}
            caveats = methodology.get("caveats") if isinstance(methodology, dict) else None
            if isinstance(caveats, list) and caveats:
                overlap_caveat = str(caveats[0])
        return {
            "available": False,
            "not_available_message": (
                "HPSA designations are not available at the tract level in this report. "
                "County-level access metrics are shown in the county profile."
            ),
            "county_fips": geo.county_fips,
            "county_available": county_row is not None,
            "overlap_caveat": overlap_caveat,
            "domains": {},
            "methodology": None,
        }

    if county_row is None:
        return {
            "available": False,
            "not_available_message": "No county-level HPSA summary was found for this county.",
            "county_fips": geo.county_fips,
            "county_available": False,
            "overlap_caveat": None,
            "domains": {},
            "methodology": None,
        }

    summary_payload = build_hpsa_response(county_row, include_legacy=False)
    methodology = summary_payload.get("methodology") if isinstance(summary_payload, dict) else None

    domains: dict[str, dict[str, Any]] = {}
    for domain in ("pc", "mh", "dh"):
        quartile_row = fetch_hpsa_domain_quartiles(db, domain)  # type: ignore[arg-type]
        ratio_fields = fetch_hpsa_domain_ratio_fields(
            db,
            county_fips=geo.county_fips,
            domain=domain,  # type: ignore[arg-type]
        )
        detail = build_hpsa_county_domain_detail(
            row=county_row,
            domain=domain,  # type: ignore[arg-type]
            quartile_row=quartile_row,
            ratio_fields=ratio_fields,
        )
        tier_value = _safe_int(detail.get("tier"))
        domains[domain] = {
            "domain": domain,
            "domain_label": _HPSA_DOMAIN_LABELS.get(domain, domain.upper()),
            "designated": bool(detail.get("designated")),
            "score_max": _safe_float(detail.get("score_max")),
            "tier": tier_value,
            "tier_label": _HPSA_TIER_LABELS.get(tier_value),
            "hpsa_formal_ratio": _coalesce_text(detail.get("hpsa_formal_ratio")),
            "provider_ratio_goal": _coalesce_text(detail.get("provider_ratio_goal")),
            "fte": _safe_float(detail.get("fte")),
            "coverage_pct": _safe_float(detail.get("coverage_pct")),
            "population_covered": _safe_int(detail.get("population_covered")),
            "comparison_context": {
                "n_designated_counties": _safe_int(
                    quartile_row.get("n_counties") if quartile_row is not None else None
                ),
                "as_of_date": (
                    quartile_row.get("as_of_date") if quartile_row is not None else None
                ),
            },
        }

    overlap_caveat = None
    if isinstance(methodology, dict):
        caveats = methodology.get("caveats")
        if isinstance(caveats, list) and caveats:
            overlap_caveat = str(caveats[0])

    return {
        "available": True,
        "county_fips": geo.county_fips,
        "county_available": True,
        "domains": domains,
        "methodology": methodology,
        "overlap_caveat": overlap_caveat,
        "as_of_date": methodology.get("as_of_date") if isinstance(methodology, dict) else None,
    }


def _ranked_places_concerns(places_section: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for measure in places_section.get("measures", []):
        if not isinstance(measure, dict):
            continue
        local = _safe_float(measure.get("local", {}).get("value"))
        state = _safe_float(measure.get("comparisons", {}).get("state", {}).get("value"))
        us = _safe_float(measure.get("comparisons", {}).get("us", {}).get("value"))
        if local is None:
            continue
        unit = _coalesce_text(measure.get("unit"))
        delta_threshold = 1.0 if (unit in {"%", "percent", "Percent", "pct"}) else 0.5
        beats_state = state is not None and local > (state + delta_threshold)
        beats_us = us is not None and local > (us + delta_threshold)
        if beats_state and beats_us:
            combined_gap = (local - state) + (local - us)
            candidates.append(
                {
                    "measure_id": measure.get("measure_id"),
                    "measure_name": _coalesce_text(
                        measure.get("short_question_text"),
                        measure.get("measure"),
                        measure.get("measure_id"),
                    ),
                    "unit": unit,
                    "local": local,
                    "state": state,
                    "us": us,
                    "combined_gap": combined_gap,
                }
            )
    candidates.sort(key=lambda item: item["combined_gap"], reverse=True)
    return candidates


def _build_executive_summary(
    *,
    geo: _ResolvedGeo,
    places_section: dict[str, Any],
    acs_section: dict[str, Any],
    svi_section: dict[str, Any],
    hpsa_section: dict[str, Any],
) -> dict[str, Any]:
    bullets: list[str] = []
    top_places = _ranked_places_concerns(places_section)

    for item in top_places[:2]:
        bullets.append(
            (
                f"{item['measure_name']}: {_format_number(item['local'], item['unit'])} "
                f"(U.S. {_format_number(item['us'], item['unit'])}, "
                f"{geo.state_abbr or 'state'} {_format_number(item['state'], item['unit'])})."
            )
        )

    overall_svi = svi_section.get("overall") if isinstance(svi_section.get("overall"), dict) else None
    overall_svi_value = _safe_float(overall_svi.get("value")) if overall_svi else None
    if overall_svi_value is not None and overall_svi_value >= 0.8:
        bullets.append(
            (
                "Overall social vulnerability is elevated at "
                f"{overall_svi_value:.3f} (national percentile scale; higher indicates higher vulnerability)."
            )
        )

    high_themes: list[tuple[str, float]] = []
    for theme in svi_section.get("themes", []):
        if not isinstance(theme, dict):
            continue
        theme_value = _safe_float(theme.get("value"))
        if theme_value is None or theme_value < 0.8:
            continue
        theme_name = _coalesce_text(theme.get("measure_name"), theme.get("measure_id"), "SVI theme")
        high_themes.append((theme_name, theme_value))
    high_themes.sort(key=lambda item: item[1], reverse=True)
    if high_themes:
        theme_name, theme_value = high_themes[0]
        bullets.append(
            f"{theme_name} is high at {theme_value:.3f}, indicating concentrated vulnerability in this theme."
        )

    if hpsa_section.get("available"):
        domains = hpsa_section.get("domains")
        if isinstance(domains, dict):
            severe_domains: list[tuple[str, dict[str, Any]]] = []
            for domain in ("pc", "mh", "dh"):
                detail = domains.get(domain)
                if not isinstance(detail, dict):
                    continue
                tier = _safe_int(detail.get("tier"))
                coverage_pct = _safe_float(detail.get("coverage_pct"))
                if tier is not None and tier >= 4:
                    severe_domains.append((domain, detail))
                    continue
                if coverage_pct is not None and coverage_pct >= 50:
                    severe_domains.append((domain, detail))
            if severe_domains:
                _, detail = severe_domains[0]
                domain_label = _coalesce_text(detail.get("domain_label"), "HPSA")
                tier_label = _coalesce_text(detail.get("tier_label"))
                coverage_text = _format_number(_safe_float(detail.get("coverage_pct")), "%")
                bullet_parts = [f"{domain_label} HPSA designation is present"]
                if tier_label:
                    bullet_parts.append(f"({tier_label})")
                if coverage_text != "Not available":
                    bullet_parts.append(f"with {coverage_text} population coverage")
                bullets.append(" ".join(bullet_parts) + ".")

    acs_extremes: list[dict[str, Any]] = []
    for factor in acs_section.get("factors", []):
        if not isinstance(factor, dict):
            continue
        quintile = _safe_int(factor.get("us_quintile"))
        local_value = _safe_float(factor.get("local", {}).get("value"))
        if quintile not in {1, 5} or local_value is None:
            continue
        acs_extremes.append(
            {
                "measure_name": _coalesce_text(factor.get("measure"), factor.get("measure_id"), "ACS factor"),
                "quintile": quintile,
                "local_value": local_value,
                "unit": _coalesce_text(factor.get("unit")),
            }
        )
    acs_extremes.sort(key=lambda item: item["quintile"], reverse=True)
    if acs_extremes:
        item = acs_extremes[0]
        bullets.append(
            (
                f"{item['measure_name']} is in national quintile {item['quintile']} "
                f"for this ACS measure ({_format_number(item['local_value'], item['unit'])})."
            )
        )

    if len(bullets) < 3:
        for concern in places_section.get("top_concerns", []):
            if not isinstance(concern, dict):
                continue
            measure_name = _coalesce_text(
                concern.get("short_question_text"),
                concern.get("measure"),
                concern.get("measure_id"),
            )
            local_value = _safe_float(concern.get("local", {}).get("value"))
            if not measure_name or local_value is None:
                continue
            bullets.append(
                f"{measure_name} is {_format_number(local_value, _coalesce_text(concern.get('unit')))} in this geography."
            )
            if len(bullets) >= 3:
                break

    if not bullets:
        bullets.append("Insufficient data were available to derive ranked summary takeaways.")
    bullets = bullets[:6]

    connector_parts: list[str] = []
    if top_places:
        connector_parts.append(
            f"PLACES measures show elevated burden for {top_places[0]['measure_name']} relative to U.S. and state benchmarks."
        )
    if overall_svi_value is not None:
        connector_parts.append(
            f"SVI overall percentile ({overall_svi_value:.3f}) provides national-context vulnerability for this area."
        )
    if hpsa_section.get("available"):
        connector_parts.append(
            "HPSA tiering and coverage describe how provider shortage conditions align with population coverage."
        )
    if acs_extremes:
        connector_parts.append(
            f"ACS factor patterns, including {acs_extremes[0]['measure_name']}, add non-medical context for interpretation."
        )
    if not connector_parts:
        connector_parts.append(
            "Available PLACES, ACS, SVI, and HPSA sections should be interpreted together because each dataset reflects a different lens on community risk."
        )

    return {
        "key_takeaways": bullets,
        "how_factors_connect": " ".join(connector_parts),
    }


def _build_methodology_section(
    *,
    hpsa_section: dict[str, Any],
) -> dict[str, Any]:
    hpsa_methodology = hpsa_section.get("methodology") if isinstance(hpsa_section.get("methodology"), dict) else {}
    hpsa_source = _coalesce_text(hpsa_methodology.get("source"), "HRSA HPSA Data Mart")
    hpsa_as_of = _coalesce_text(hpsa_methodology.get("as_of_date"))
    hpsa_calc = _coalesce_text(
        hpsa_methodology.get("calculation"),
        "Tiering uses county score quartiles among designated counties.",
    )
    hpsa_lines = [
        f"Source: {hpsa_source}",
        f"As-of date: {hpsa_as_of}" if hpsa_as_of else "As-of date: Not available",
        hpsa_calc,
    ]

    return {
        "places": [
            "CDC PLACES values are model-based small-area estimates.",
            "This report defaults to the most recent available year and default data value type for the selected geography.",
            "U.S. and state comparisons are included only when computable from available data.",
        ],
        "acs": [
            "ACS factors use the selected ACS year-window and data value type available for this geography.",
            "ACS margins of error (MOE) are provided when available for local estimates.",
            "U.S. and state comparisons are aggregate benchmarks from available rows.",
        ],
        "svi": [
            "SVI values are percentiles (0 to 1) where higher percentile means higher relative vulnerability.",
            "SVI overall and theme percentiles are shown for the selected SVI year.",
            "Within-state percentile context is included only when state distribution rows are available.",
        ],
        "hpsa": hpsa_lines,
    }


def _build_data_notes(
    *,
    hpsa_section: dict[str, Any],
) -> list[str]:
    overlap_caveat = _coalesce_text(
        hpsa_section.get("overlap_caveat"),
        "HPSA designated populations may overlap across partial-county, population-group, and facility designations. "
        "Population covered is aggregated conservatively using MAX to reduce double counting; coverage_pct should be interpreted "
        "as an approximate upper-bound proxy for coverage within the county.",
    )
    return [
        "PLACES estimates are model-based and are not direct measurements of every local resident.",
        "Confidence intervals describe statistical uncertainty; overlapping intervals can indicate uncertainty in apparent differences.",
        "ACS margins of error (MOE) should be considered when interpreting differences across areas.",
        "SVI is a percentile/relative ranking and not a direct prevalence rate.",
        overlap_caveat,
    ]


def _build_snapshot_section(
    *,
    places_section: dict[str, Any],
    acs_section: dict[str, Any],
    svi_section: dict[str, Any],
    hpsa_section: dict[str, Any],
) -> dict[str, Any]:
    return {
        "places_top_concerns": places_section.get("top_concerns", []),
        "acs_top_context": acs_section.get("top_context_tiles", []),
        "svi": {
            "overall": svi_section.get("overall"),
            "themes": svi_section.get("themes", []),
        },
        "hpsa": {
            "available": bool(hpsa_section.get("available")),
            "domains": hpsa_section.get("domains", {}),
            "not_available_message": hpsa_section.get("not_available_message"),
        },
    }


def _derive_state_and_us_summary_values(section_rows: list[dict[str, Any]]) -> dict[str, Any]:
    local_values = [
        _safe_float(row.get("local", {}).get("value"))
        for row in section_rows
        if isinstance(row, dict)
    ]
    local_values = [value for value in local_values if value is not None]
    state_values = [
        _safe_float(row.get("comparisons", {}).get("state", {}).get("value"))
        for row in section_rows
        if isinstance(row, dict)
    ]
    state_values = [value for value in state_values if value is not None]
    us_values = [
        _safe_float(row.get("comparisons", {}).get("us", {}).get("value"))
        for row in section_rows
        if isinstance(row, dict)
    ]
    us_values = [value for value in us_values if value is not None]
    return {
        "local_mean": mean(local_values) if local_values else None,
        "state_mean": mean(state_values) if state_values else None,
        "us_mean": mean(us_values) if us_values else None,
    }


def build_profile_bundle(
    db: Session,
    *,
    geography: ProfileGeography,
    identifier: str,
) -> dict[str, Any]:
    normalized_geography = str(geography or "").strip().lower()
    if normalized_geography not in {"county", "tract"}:
        raise ProfileBundleError("geography must be either 'county' or 'tract'.")

    if normalized_geography == "county":
        geo = _resolve_county_geo(db, identifier)
    else:
        geo = _resolve_tract_geo(db, identifier)

    places_year, places_data_value_type_id = _resolve_places_snapshot(
        db,
        geography=geo.geography,
        location_id=geo.location_id,
    )
    acs_year_window, acs_data_value_type_id = _resolve_acs_snapshot(
        db,
        geography=geo.geography,
        location_id=geo.location_id,
    )
    svi_year = _resolve_svi_snapshot(
        db,
        geography=geo.geography,
        location_id=geo.location_id,
    )

    places_section = _build_places_section(
        db,
        geo=geo,
        places_year=places_year,
        places_data_value_type_id=places_data_value_type_id,
    )
    acs_section = _build_acs_section(
        db,
        geo=geo,
        year_window=acs_year_window,
        data_value_type_id=acs_data_value_type_id,
    )
    svi_section = _build_svi_section(
        db,
        geo=geo,
        svi_year=svi_year,
    )
    hpsa_section = _build_hpsa_section(
        db,
        geo=geo,
    )

    executive_summary = _build_executive_summary(
        geo=geo,
        places_section=places_section,
        acs_section=acs_section,
        svi_section=svi_section,
        hpsa_section=hpsa_section,
    )
    methodology_section = _build_methodology_section(hpsa_section=hpsa_section)
    data_notes = _build_data_notes(hpsa_section=hpsa_section)

    places_summary = _derive_state_and_us_summary_values(
        [row for row in places_section.get("measures", []) if isinstance(row, dict)]
    )
    acs_summary = _derive_state_and_us_summary_values(
        [row for row in acs_section.get("factors", []) if isinstance(row, dict)]
    )

    bundle = {
        "schema_version": "2.0",
        "geo": {
            "level": geo.geography,
            "id": geo.location_id,
            "county_fips": geo.county_fips,
            "tract_geoid": geo.tract_geoid,
            "name": geo.name,
            "county_name": geo.county_name,
            "state_abbr": geo.state_abbr,
            "state_name": geo.state_name,
            "state_fips": geo.state_fips,
        },
        "as_of": {
            "generated_at": datetime.now(UTC),
            "places_year": places_year,
            "places_data_value_type_id": places_data_value_type_id,
            "acs_year_window": acs_year_window,
            "acs_data_value_type_id": acs_data_value_type_id,
            "svi_year": svi_year,
            "hpsa_as_of_date": hpsa_section.get("as_of_date"),
        },
        "snapshot": _build_snapshot_section(
            places_section=places_section,
            acs_section=acs_section,
            svi_section=svi_section,
            hpsa_section=hpsa_section,
        ),
        "places": places_section,
        "acs": acs_section,
        "svi": svi_section,
        "hpsa": hpsa_section,
        "comparisons_summary": {
            "places": places_summary,
            "acs": acs_summary,
            "svi_overall_value": (
                _safe_float(svi_section.get("overall", {}).get("value"))
                if isinstance(svi_section.get("overall"), dict)
                else None
            ),
        },
        "narrative": {
            "executive_summary": executive_summary,
            "drivers": {
                "places_ranked_excess": _ranked_places_concerns(places_section)[:8],
            },
        },
        "methodology": methodology_section,
        "data_notes": data_notes,
    }

    return _sanitize_for_json(bundle)
