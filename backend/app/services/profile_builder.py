from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, UTC
import math
import re
from statistics import mean
from typing import Any

from sqlalchemy import String, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from app.db_fqtn import acs_table, places_table
from app.services.profile_narrative import build_profile_narrative
from app.services.hpsa_summary import (
    build_hpsa_response,
    fetch_county_hpsa_row,
    normalize_county_fips,
)

FINITE_FLOAT_SQL = (
    "NOT IN ('NaN'::double precision, 'Infinity'::double precision, '-Infinity'::double precision)"
)
YEAR_WINDOW_PATTERN = re.compile(r"^(\d{4})\s*-\s*(\d{4})$")
MAX_ACS_CANDIDATE_MEASURES = 20
MAX_ACS_LOCATION_MEASURES = 12
MAX_TOP_CORRELATES = 5
MAX_SCATTER_POINTS = 50000
CORRELATION_MIN_PAIRS = 30


class ProfileBuildError(ValueError):
    pass


@dataclass(slots=True)
class ProfileBuildResult:
    profile_json: dict[str, Any]
    chart_inputs: dict[str, Any]


def _table_for_geography(geography: str) -> str:
    normalized = str(geography or "").strip().lower()
    if normalized == "county":
        return "acs_nmf_county_estimates"
    if normalized == "tract":
        return "acs_nmf_tract_estimates"
    raise ProfileBuildError("geography must be either 'county' or 'tract'.")


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
        return int(value)
    except (TypeError, ValueError):
        return None


def _sanitize_for_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_json(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_for_json(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    return value


def _format_num(value: float | None, precision: int = 1, suffix: str = "") -> str:
    if value is None:
        return "data unavailable"
    return f"{value:.{precision}f}{suffix}"


def _quantile(sorted_values: list[float], q: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    clamped_q = min(1.0, max(0.0, q))
    position = (len(sorted_values) - 1) * clamped_q
    lower_index = int(math.floor(position))
    upper_index = min(len(sorted_values) - 1, lower_index + 1)
    lower = sorted_values[lower_index]
    upper = sorted_values[upper_index]
    fraction = position - lower_index
    return lower + (upper - lower) * fraction


def _compute_stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "p10": None,
            "p25": None,
            "p75": None,
            "p90": None,
            "min": None,
            "max": None,
        }
    sorted_values = sorted(values)
    return {
        "count": len(sorted_values),
        "mean": _safe_float(mean(sorted_values)),
        "median": _quantile(sorted_values, 0.5),
        "p10": _quantile(sorted_values, 0.10),
        "p25": _quantile(sorted_values, 0.25),
        "p75": _quantile(sorted_values, 0.75),
        "p90": _quantile(sorted_values, 0.90),
        "min": sorted_values[0],
        "max": sorted_values[-1],
    }


def _percentile(values: list[float], location_value: float | None) -> float | None:
    if not values or location_value is None:
        return None
    less_or_equal = sum(1 for value in values if value <= location_value)
    return (less_or_equal / len(values)) * 100.0


def _year_window_sort_key(value: str) -> tuple[int, int, str]:
    matched = YEAR_WINDOW_PATTERN.match(str(value or "").strip())
    if not matched:
        return (-1, -1, str(value or ""))
    start = int(matched.group(1))
    end = int(matched.group(2))
    return (end, start, str(value))


def _resolve_hpsa_county_fips(*, geography: str, location_id: str) -> str | None:
    normalized_geography = str(geography or "").strip().lower()
    normalized_location_id = str(location_id or "").strip()
    if not normalized_location_id:
        return None
    if normalized_geography == "county":
        return normalize_county_fips(normalized_location_id)
    if normalized_geography != "tract":
        return None
    digits = re.sub(r"[^0-9]", "", normalized_location_id)
    if len(digits) < 5:
        return None
    return normalize_county_fips(digits[:5])


def inject_hpsa_context(profile_json: dict[str, Any], hpsa_payload: dict[str, Any] | None) -> None:
    if not isinstance(profile_json, dict):
        return
    if not isinstance(hpsa_payload, dict):
        return

    profile_json["hpsa"] = {
        "county_fips": hpsa_payload.get("county_fips"),
        "state_fips": hpsa_payload.get("state_fips"),
        "primary_care": hpsa_payload.get("primary_care"),
        "mental_health": hpsa_payload.get("mental_health"),
        "dental": hpsa_payload.get("dental"),
    }

    methodology = (
        profile_json.get("methodology")
        if isinstance(profile_json.get("methodology"), dict)
        else {}
    )
    hpsa_methodology = hpsa_payload.get("methodology")
    if isinstance(hpsa_methodology, dict):
        methodology["hpsa"] = hpsa_methodology
        profile_json["methodology"] = methodology

        caveats = hpsa_methodology.get("caveats")
        first_caveat = caveats[0] if isinstance(caveats, list) and caveats else None
        if first_caveat:
            methods_caveats = (
                profile_json.get("methods_caveats")
                if isinstance(profile_json.get("methods_caveats"), list)
                else []
            )
            if first_caveat not in methods_caveats:
                methods_caveats.append(str(first_caveat))
            profile_json["methods_caveats"] = methods_caveats


def _table_exists(db: Session, table_name: str) -> bool:
    fq_table_name = (
        acs_table(table_name)
        if str(table_name).startswith("acs_nmf_")
        else places_table(table_name)
    )
    row = db.execute(
        text("SELECT to_regclass(:table_name) AS table_name"),
        {"table_name": fq_table_name},
    ).mappings().one()
    return row["table_name"] is not None


def _resolve_acs_year_window(
    db: Session,
    *,
    table_name: str,
    requested_year_window: str | None,
) -> str:
    if requested_year_window:
        requested = str(requested_year_window).strip()
        exists_row = db.execute(
            text(
                f"""
                SELECT EXISTS (
                    SELECT 1
                    FROM {table_name}
                    WHERE year_window = :year_window
                ) AS exists
                """
            ),
            {"year_window": requested},
        ).mappings().one()
        if exists_row["exists"]:
            return requested
        raise ProfileBuildError(
            f"No ACS NMF rows found for year_window={requested} in {table_name}."
        )

    rows = db.execute(
        text(
            f"""
            SELECT DISTINCT year_window
            FROM {table_name}
            """
        )
    ).scalars().all()
    year_windows = [str(value) for value in rows if value is not None]
    if not year_windows:
        raise ProfileBuildError(f"ACS table {table_name} is empty.")
    return sorted(year_windows, key=_year_window_sort_key, reverse=True)[0]


def _fetch_location_and_places_value(
    db: Session,
    *,
    geography: str,
    location_id: str,
    places_year: int,
    places_measure_id: str,
    places_data_value_type_id: str,
) -> dict[str, Any] | None:
    if geography == "county":
        row = db.execute(
            text(
                """
                WITH selected_measure AS (
                    SELECT id, measure_id, measure, short_question_text, data_value_type_id, unit
                    FROM dim_measure
                    WHERE measure_id = :measure_id
                      AND data_value_type_id = :data_value_type_id
                    LIMIT 1
                )
                SELECT
                    c.location_id,
                    c.county_name AS location_name,
                    c.state_abbr,
                    sm.measure_id,
                    sm.measure,
                    sm.short_question_text,
                    sm.data_value_type_id,
                    sm.unit,
                    f.data_value,
                    f.low_confidence_limit,
                    f.high_confidence_limit
                FROM dim_county AS c
                LEFT JOIN selected_measure AS sm ON TRUE
                LEFT JOIN fact_estimate_county AS f
                    ON f.location_id = c.location_id
                   AND f.year = :year
                   AND f.measure_dim_id = sm.id
                WHERE c.location_id = :location_id
                LIMIT 1
                """
            ),
            {
                "location_id": location_id,
                "year": places_year,
                "measure_id": places_measure_id,
                "data_value_type_id": places_data_value_type_id,
            },
        ).mappings().one_or_none()
        return dict(row) if row is not None else None

    row = db.execute(
        text(
            """
            WITH location_meta AS (
                SELECT
                    t.locationid AS location_id,
                    COALESCE(NULLIF(t.location_name, ''), t.locationid) AS location_name,
                    t.state_abbr
                FROM tract_estimates AS t
                WHERE t.locationid = :location_id
                ORDER BY t.year DESC
                LIMIT 1
            ),
            selected_measure AS (
                SELECT
                    t.locationid AS location_id,
                    t.measure_id,
                    t.measure,
                    t.short_question_text,
                    t.data_value_type_id,
                    t.data_value_unit AS unit,
                    t.data_value,
                    t.low_confidence_limit,
                    t.high_confidence_limit
                FROM tract_estimates AS t
                WHERE t.locationid = :location_id
                  AND t.year = :year
                  AND t.measure_id = :measure_id
                  AND t.data_value_type_id = :data_value_type_id
                LIMIT 1
            )
            SELECT
                l.location_id,
                l.location_name,
                l.state_abbr,
                s.measure_id,
                s.measure,
                s.short_question_text,
                s.data_value_type_id,
                s.unit,
                s.data_value,
                s.low_confidence_limit,
                s.high_confidence_limit
            FROM location_meta AS l
            LEFT JOIN selected_measure AS s
                ON s.location_id = l.location_id
            LIMIT 1
            """
        ),
        {
            "location_id": location_id,
            "year": places_year,
            "measure_id": places_measure_id,
            "data_value_type_id": places_data_value_type_id,
        },
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


def _fetch_places_distribution(
    db: Session,
    *,
    geography: str,
    places_year: int,
    places_measure_id: str,
    places_data_value_type_id: str,
    state_abbr: str | None = None,
) -> list[float]:
    if geography == "county":
        params: dict[str, Any] = {
            "year": places_year,
            "measure_id": places_measure_id,
            "data_value_type_id": places_data_value_type_id,
        }
        state_filter_sql = ""
        if state_abbr:
            state_filter_sql = "AND c.state_abbr = :state_abbr"
            params["state_abbr"] = state_abbr

        query = text(
            f"""
            SELECT f.data_value
            FROM fact_estimate_county AS f
            JOIN dim_measure AS dm
              ON dm.id = f.measure_dim_id
            JOIN dim_county AS c
              ON c.location_id = f.location_id
            WHERE f.year = :year
              AND dm.measure_id = :measure_id
              AND dm.data_value_type_id = :data_value_type_id
              AND f.data_value {FINITE_FLOAT_SQL}
              {state_filter_sql}
            """
        )
        rows = db.execute(query, params).scalars().all()
        return [_safe_float(value) for value in rows if _safe_float(value) is not None]

    params = {
        "year": places_year,
        "measure_id": places_measure_id,
        "data_value_type_id": places_data_value_type_id,
    }
    state_filter_sql = ""
    if state_abbr:
        state_filter_sql = "AND t.state_abbr = :state_abbr"
        params["state_abbr"] = state_abbr

    query = text(
        f"""
        SELECT t.data_value
        FROM tract_estimates AS t
        WHERE t.year = :year
          AND t.measure_id = :measure_id
          AND t.data_value_type_id = :data_value_type_id
          AND t.data_value {FINITE_FLOAT_SQL}
          {state_filter_sql}
        """
    )
    rows = db.execute(query, params).scalars().all()
    return [_safe_float(value) for value in rows if _safe_float(value) is not None]


def _fetch_acs_candidates(
    db: Session,
    *,
    table_name: str,
    acs_year_window: str,
    acs_data_value_type_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            SELECT
                measure_id,
                MAX(measure) AS measure,
                MAX(category_id) AS category_id,
                MAX(category) AS category,
                MAX(data_value_unit) AS data_value_unit,
                COUNT(*) FILTER (WHERE data_value {FINITE_FLOAT_SQL}) AS finite_count
            FROM {table_name}
            WHERE year_window = :year_window
              AND data_value_type_id = :data_value_type_id
            GROUP BY measure_id
            ORDER BY finite_count DESC, measure_id
            LIMIT :limit
            """
        ),
        {
            "year_window": acs_year_window,
            "data_value_type_id": acs_data_value_type_id,
            "limit": limit,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _fetch_acs_location_measures(
    db: Session,
    *,
    table_name: str,
    acs_year_window: str,
    acs_data_value_type_id: str,
    location_id: str,
    ordered_measure_ids: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    if not ordered_measure_ids:
        return []
    selected_ids = ordered_measure_ids[:limit]
    query = text(
        f"""
        SELECT
            measure_id,
            measure,
            category_id,
            category,
            data_value,
            moe,
            data_value_unit
        FROM {table_name}
        WHERE year_window = :year_window
          AND data_value_type_id = :data_value_type_id
          AND location_id = :location_id
          AND measure_id = ANY(:measure_ids)
        """
    ).bindparams(bindparam("measure_ids", type_=ARRAY(String())))
    rows = db.execute(
        query,
        {
            "year_window": acs_year_window,
            "data_value_type_id": acs_data_value_type_id,
            "location_id": location_id,
            "measure_ids": selected_ids,
        },
    ).mappings().all()

    order_map = {measure_id: index for index, measure_id in enumerate(selected_ids)}
    ordered_rows = sorted(
        (dict(row) for row in rows),
        key=lambda item: order_map.get(str(item.get("measure_id")), 1_000_000),
    )
    normalized: list[dict[str, Any]] = []
    for row in ordered_rows:
        normalized.append(
            {
                "measure_id": row.get("measure_id"),
                "measure": row.get("measure"),
                "category_id": row.get("category_id"),
                "category": row.get("category"),
                "value": _safe_float(row.get("data_value")),
                "moe": _safe_float(row.get("moe")),
                "unit": row.get("data_value_unit"),
            }
        )
    return normalized


def _correlate_places_with_acs(
    db: Session,
    *,
    geography: str,
    table_name: str,
    places_year: int,
    places_measure_id: str,
    places_data_value_type_id: str,
    acs_year_window: str,
    acs_data_value_type_id: str,
    candidate_measure_ids: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    if not candidate_measure_ids:
        return []

    if geography == "county":
        places_cte = f"""
        SELECT
            f.location_id,
            f.data_value AS places_value
        FROM fact_estimate_county AS f
        JOIN dim_measure AS dm
          ON dm.id = f.measure_dim_id
        WHERE f.year = :places_year
          AND dm.measure_id = :places_measure_id
          AND dm.data_value_type_id = :places_data_value_type_id
          AND f.data_value {FINITE_FLOAT_SQL}
        """
    else:
        places_cte = f"""
        SELECT
            t.locationid AS location_id,
            t.data_value AS places_value
        FROM tract_estimates AS t
        WHERE t.year = :places_year
          AND t.measure_id = :places_measure_id
          AND t.data_value_type_id = :places_data_value_type_id
          AND t.data_value {FINITE_FLOAT_SQL}
        """

    query = text(
        f"""
        WITH places AS (
            {places_cte}
        ),
        acs AS (
            SELECT
                measure_id,
                location_id,
                data_value AS acs_value
            FROM {table_name}
            WHERE year_window = :acs_year_window
              AND data_value_type_id = :acs_data_value_type_id
              AND measure_id = ANY(:measure_ids)
              AND data_value {FINITE_FLOAT_SQL}
        )
        SELECT
            a.measure_id,
            corr(a.acs_value, p.places_value) AS correlation,
            COUNT(*) AS n_pairs
        FROM acs AS a
        JOIN places AS p
          ON p.location_id = a.location_id
        GROUP BY a.measure_id
        HAVING COUNT(*) >= :min_pairs
        ORDER BY abs(corr(a.acs_value, p.places_value)) DESC NULLS LAST, a.measure_id
        LIMIT :limit
        """
    ).bindparams(bindparam("measure_ids", type_=ARRAY(String())))

    rows = db.execute(
        query,
        {
            "places_year": places_year,
            "places_measure_id": places_measure_id,
            "places_data_value_type_id": places_data_value_type_id,
            "acs_year_window": acs_year_window,
            "acs_data_value_type_id": acs_data_value_type_id,
            "measure_ids": candidate_measure_ids,
            "min_pairs": CORRELATION_MIN_PAIRS,
            "limit": limit,
        },
    ).mappings().all()

    return [
        {
            "measure_id": row.get("measure_id"),
            "correlation": _safe_float(row.get("correlation")),
            "n_pairs": _safe_int(row.get("n_pairs")),
        }
        for row in rows
        if _safe_float(row.get("correlation")) is not None
    ]


def _fetch_acs_comparison_stats(
    db: Session,
    *,
    table_name: str,
    measure_id: str,
    acs_year_window: str,
    acs_data_value_type_id: str,
    location_id: str,
    state_abbr: str | None,
) -> dict[str, Any]:
    location_row = db.execute(
        text(
            f"""
            SELECT data_value, moe, measure, data_value_unit
            FROM {table_name}
            WHERE year_window = :year_window
              AND data_value_type_id = :data_value_type_id
              AND measure_id = :measure_id
              AND location_id = :location_id
            LIMIT 1
            """
        ),
        {
            "year_window": acs_year_window,
            "data_value_type_id": acs_data_value_type_id,
            "measure_id": measure_id,
            "location_id": location_id,
        },
    ).mappings().one_or_none()

    state_params = {
        "year_window": acs_year_window,
        "data_value_type_id": acs_data_value_type_id,
        "measure_id": measure_id,
    }
    state_filter_sql = ""
    if state_abbr:
        state_filter_sql = "AND state_abbr = :state_abbr"
        state_params["state_abbr"] = state_abbr

    state_stats = db.execute(
        text(
            f"""
            SELECT
                COUNT(*) FILTER (WHERE data_value {FINITE_FLOAT_SQL}) AS count,
                AVG(data_value) FILTER (WHERE data_value {FINITE_FLOAT_SQL}) AS mean,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY data_value)
                    FILTER (WHERE data_value {FINITE_FLOAT_SQL}) AS median
            FROM {table_name}
            WHERE year_window = :year_window
              AND data_value_type_id = :data_value_type_id
              AND measure_id = :measure_id
              {state_filter_sql}
            """
        ),
        state_params,
    ).mappings().one()

    us_stats = db.execute(
        text(
            f"""
            SELECT
                COUNT(*) FILTER (WHERE data_value {FINITE_FLOAT_SQL}) AS count,
                AVG(data_value) FILTER (WHERE data_value {FINITE_FLOAT_SQL}) AS mean,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY data_value)
                    FILTER (WHERE data_value {FINITE_FLOAT_SQL}) AS median
            FROM {table_name}
            WHERE year_window = :year_window
              AND data_value_type_id = :data_value_type_id
              AND measure_id = :measure_id
            """
        ),
        {
            "year_window": acs_year_window,
            "data_value_type_id": acs_data_value_type_id,
            "measure_id": measure_id,
        },
    ).mappings().one()

    return {
        "measure": location_row.get("measure") if location_row else None,
        "unit": location_row.get("data_value_unit") if location_row else None,
        "location_value": _safe_float(location_row.get("data_value") if location_row else None),
        "location_moe": _safe_float(location_row.get("moe") if location_row else None),
        "state_mean": _safe_float(state_stats.get("mean")),
        "state_median": _safe_float(state_stats.get("median")),
        "state_count": _safe_int(state_stats.get("count")),
        "us_mean": _safe_float(us_stats.get("mean")),
        "us_median": _safe_float(us_stats.get("median")),
        "us_count": _safe_int(us_stats.get("count")),
    }


def _fetch_scatter_points(
    db: Session,
    *,
    geography: str,
    table_name: str,
    places_year: int,
    places_measure_id: str,
    places_data_value_type_id: str,
    acs_year_window: str,
    acs_data_value_type_id: str,
    acs_measure_id: str,
) -> list[dict[str, float | str]]:
    if geography == "county":
        places_cte = f"""
        SELECT
            f.location_id,
            f.data_value AS places_value
        FROM fact_estimate_county AS f
        JOIN dim_measure AS dm
          ON dm.id = f.measure_dim_id
        WHERE f.year = :places_year
          AND dm.measure_id = :places_measure_id
          AND dm.data_value_type_id = :places_data_value_type_id
          AND f.data_value {FINITE_FLOAT_SQL}
        """
    else:
        places_cte = f"""
        SELECT
            t.locationid AS location_id,
            t.data_value AS places_value
        FROM tract_estimates AS t
        WHERE t.year = :places_year
          AND t.measure_id = :places_measure_id
          AND t.data_value_type_id = :places_data_value_type_id
          AND t.data_value {FINITE_FLOAT_SQL}
        """

    rows = db.execute(
        text(
            f"""
            WITH places AS (
                {places_cte}
            ),
            acs AS (
                SELECT
                    location_id,
                    data_value AS acs_value
                FROM {table_name}
                WHERE year_window = :acs_year_window
                  AND data_value_type_id = :acs_data_value_type_id
                  AND measure_id = :acs_measure_id
                  AND data_value {FINITE_FLOAT_SQL}
            )
            SELECT
                p.location_id,
                a.acs_value,
                p.places_value
            FROM places AS p
            JOIN acs AS a
              ON a.location_id = p.location_id
            ORDER BY p.location_id
            """
        ),
        {
            "places_year": places_year,
            "places_measure_id": places_measure_id,
            "places_data_value_type_id": places_data_value_type_id,
            "acs_year_window": acs_year_window,
            "acs_data_value_type_id": acs_data_value_type_id,
            "acs_measure_id": acs_measure_id,
        },
    ).mappings().all()

    points = []
    for row in rows:
        x_value = _safe_float(row.get("acs_value"))
        y_value = _safe_float(row.get("places_value"))
        if x_value is None or y_value is None:
            continue
        points.append(
            {
                "location_id": str(row.get("location_id")),
                "x": x_value,
                "y": y_value,
            }
        )

    if len(points) <= MAX_SCATTER_POINTS:
        return points

    step = max(1, math.ceil(len(points) / MAX_SCATTER_POINTS))
    return points[::step]


def build_narrative(
    profile_json: dict[str, Any],
    *,
    include_full_narrative: bool,
) -> dict[str, Any]:
    return build_profile_narrative(
        profile_json=profile_json,
        include_full_narrative=include_full_narrative,
    )


def build_profile(
    db: Session,
    *,
    geography: str,
    location_id: str,
    places_year: int,
    places_measure_id: str,
    places_data_value_type_id: str,
    acs_year_window: str | None,
    acs_data_value_type_id: str,
    include_full_narrative: bool = True,
) -> ProfileBuildResult:
    normalized_geography = str(geography or "").strip().lower()
    if normalized_geography not in {"county", "tract"}:
        raise ProfileBuildError("Unsupported geography. Use 'county' or 'tract'.")

    normalized_location_id = str(location_id or "").strip()
    if not normalized_location_id:
        raise ProfileBuildError("location_id is required.")

    normalized_places_measure_id = str(places_measure_id or "").strip()
    normalized_places_type = str(places_data_value_type_id or "").strip()
    if not normalized_places_measure_id or not normalized_places_type:
        raise ProfileBuildError("PLACES measure_id and data_value_type_id are required.")

    normalized_acs_type = str(acs_data_value_type_id or "Percent").strip() or "Percent"
    acs_table_name = _table_for_geography(normalized_geography)
    required_tables = [acs_table_name]
    if normalized_geography == "county":
        required_tables.extend(["dim_measure", "dim_county", "fact_estimate_county"])
    else:
        required_tables.append("tract_estimates")
    missing_tables = [
        table_name for table_name in required_tables if not _table_exists(db, table_name)
    ]
    if missing_tables:
        missing_label = ", ".join(missing_tables)
        raise ProfileBuildError(f"Required tables are missing: {missing_label}.")

    resolved_acs_year_window = _resolve_acs_year_window(
        db,
        table_name=acs_table_name,
        requested_year_window=acs_year_window,
    )

    location_row = _fetch_location_and_places_value(
        db,
        geography=normalized_geography,
        location_id=normalized_location_id,
        places_year=places_year,
        places_measure_id=normalized_places_measure_id,
        places_data_value_type_id=normalized_places_type,
    )
    if not location_row:
        raise ProfileBuildError(
            f"Location {normalized_location_id} was not found for geography={normalized_geography}."
        )

    state_abbr = str(location_row.get("state_abbr") or "").strip() or None
    us_distribution = _fetch_places_distribution(
        db,
        geography=normalized_geography,
        places_year=places_year,
        places_measure_id=normalized_places_measure_id,
        places_data_value_type_id=normalized_places_type,
        state_abbr=None,
    )
    state_distribution = _fetch_places_distribution(
        db,
        geography=normalized_geography,
        places_year=places_year,
        places_measure_id=normalized_places_measure_id,
        places_data_value_type_id=normalized_places_type,
        state_abbr=state_abbr,
    )

    us_stats = _compute_stats(us_distribution)
    state_stats = _compute_stats(state_distribution)

    places_location_value = _safe_float(location_row.get("data_value"))
    us_percentile = _percentile(us_distribution, places_location_value)

    acs_candidates = _fetch_acs_candidates(
        db,
        table_name=acs_table_name,
        acs_year_window=resolved_acs_year_window,
        acs_data_value_type_id=normalized_acs_type,
        limit=MAX_ACS_CANDIDATE_MEASURES,
    )
    candidate_measure_ids = [
        str(item.get("measure_id"))
        for item in acs_candidates
        if item.get("measure_id") is not None
    ]
    candidate_by_id = {
        str(item.get("measure_id")): item
        for item in acs_candidates
        if item.get("measure_id") is not None
    }

    acs_location_measures = _fetch_acs_location_measures(
        db,
        table_name=acs_table_name,
        acs_year_window=resolved_acs_year_window,
        acs_data_value_type_id=normalized_acs_type,
        location_id=normalized_location_id,
        ordered_measure_ids=candidate_measure_ids,
        limit=MAX_ACS_LOCATION_MEASURES,
    )
    acs_location_by_id = {
        str(item.get("measure_id")): item for item in acs_location_measures if item.get("measure_id")
    }

    correlated = _correlate_places_with_acs(
        db,
        geography=normalized_geography,
        table_name=acs_table_name,
        places_year=places_year,
        places_measure_id=normalized_places_measure_id,
        places_data_value_type_id=normalized_places_type,
        acs_year_window=resolved_acs_year_window,
        acs_data_value_type_id=normalized_acs_type,
        candidate_measure_ids=candidate_measure_ids,
        limit=MAX_TOP_CORRELATES,
    )

    top_correlates: list[dict[str, Any]] = []
    for item in correlated:
        measure_id = str(item.get("measure_id"))
        candidate_meta = candidate_by_id.get(measure_id, {})
        location_measure = acs_location_by_id.get(measure_id, {})
        top_correlates.append(
            {
                "measure_id": measure_id,
                "measure": candidate_meta.get("measure") or location_measure.get("measure"),
                "category_id": candidate_meta.get("category_id") or location_measure.get("category_id"),
                "category": candidate_meta.get("category") or location_measure.get("category"),
                "correlation": _safe_float(item.get("correlation")),
                "n_pairs": _safe_int(item.get("n_pairs")),
                "location_value": _safe_float(location_measure.get("value")),
            }
        )

    primary_acs_measure_id = None
    if top_correlates:
        primary_acs_measure_id = str(top_correlates[0].get("measure_id"))
    elif acs_location_measures:
        primary_acs_measure_id = str(acs_location_measures[0].get("measure_id"))

    acs_primary_comparison = None
    scatter_payload = None
    if primary_acs_measure_id:
        acs_primary_comparison = _fetch_acs_comparison_stats(
            db,
            table_name=acs_table_name,
            measure_id=primary_acs_measure_id,
            acs_year_window=resolved_acs_year_window,
            acs_data_value_type_id=normalized_acs_type,
            location_id=normalized_location_id,
            state_abbr=state_abbr,
        )
        primary_meta = candidate_by_id.get(primary_acs_measure_id, {})
        if isinstance(acs_primary_comparison, dict):
            acs_primary_comparison["measure_id"] = primary_acs_measure_id
            acs_primary_comparison["category_id"] = primary_meta.get("category_id")
            acs_primary_comparison["category"] = primary_meta.get("category")

        scatter_points = _fetch_scatter_points(
            db,
            geography=normalized_geography,
            table_name=acs_table_name,
            places_year=places_year,
            places_measure_id=normalized_places_measure_id,
            places_data_value_type_id=normalized_places_type,
            acs_year_window=resolved_acs_year_window,
            acs_data_value_type_id=normalized_acs_type,
            acs_measure_id=primary_acs_measure_id,
        )
        scatter_payload = {
            "measure_id": primary_acs_measure_id,
            "measure": (
                acs_primary_comparison.get("measure")
                if isinstance(acs_primary_comparison, dict)
                else primary_meta.get("measure")
            ),
            "points": scatter_points,
            "location_id": normalized_location_id,
        }

    profile_json: dict[str, Any] = {
        "schema_version": "1.1",
        "generated_at": datetime.now(UTC).isoformat(),
        "geography": normalized_geography,
        "location": {
            "id": normalized_location_id,
            "name": location_row.get("location_name") or normalized_location_id,
            "state_abbr": state_abbr,
        },
        "selections": {
            "places": {
                "year": places_year,
                "measure_id": normalized_places_measure_id,
                "data_value_type_id": normalized_places_type,
            },
            "acs_nmf": {
                "year_window": resolved_acs_year_window,
                "data_value_type_id": normalized_acs_type,
            },
        },
        "places_measure": {
            "measure_id": location_row.get("measure_id") or normalized_places_measure_id,
            "measure": location_row.get("measure"),
            "short_question_text": location_row.get("short_question_text"),
            "data_value_type_id": location_row.get("data_value_type_id") or normalized_places_type,
            "year": places_year,
            "unit": location_row.get("unit") or "%",
            "location_value": places_location_value,
            "location_ci_low": _safe_float(location_row.get("low_confidence_limit")),
            "location_ci_high": _safe_float(location_row.get("high_confidence_limit")),
        },
        "reference_stats": {
            "state": state_stats,
            "us": us_stats,
            "us_percentile": us_percentile,
        },
        "comparisons": {
            "places": {
                "location_value": places_location_value,
                "state_mean": _safe_float(state_stats.get("mean")),
                "us_mean": _safe_float(us_stats.get("mean")),
            },
            "acs_primary": acs_primary_comparison,
        },
        "acs_nmf": {
            "year_window": resolved_acs_year_window,
            "data_value_type_id": normalized_acs_type,
            "candidate_measure_count": len(candidate_measure_ids),
            "location_measures": acs_location_measures,
            "top_correlates": top_correlates,
        },
        "charts": {},
        "methods_caveats": [
            "Analysis uses only local PLACES and ACS NMF tables from this application database.",
            "Correlations use a capped ACS candidate set and finite paired values only.",
            "State and US references are descriptive summaries of the selected geography distribution.",
            "Values can be missing due to source suppression or unavailable estimates.",
        ],
    }

    hpsa_county_fips = _resolve_hpsa_county_fips(
        geography=normalized_geography,
        location_id=normalized_location_id,
    )
    if hpsa_county_fips:
        hpsa_row = fetch_county_hpsa_row(db, hpsa_county_fips)
        if hpsa_row is not None:
            hpsa_payload = build_hpsa_response(hpsa_row, include_legacy=False)
            inject_hpsa_context(profile_json, hpsa_payload)

    narrative = build_narrative(
        profile_json,
        include_full_narrative=include_full_narrative,
    )
    profile_json["narrative"] = narrative

    chart_inputs = {
        "places_comparison": {
            "label": (
                profile_json["places_measure"].get("short_question_text")
                or profile_json["places_measure"].get("measure")
                or profile_json["places_measure"].get("measure_id")
            ),
            "unit": "%",
            "location_value": places_location_value,
            "state_mean": _safe_float(state_stats.get("mean")),
            "us_mean": _safe_float(us_stats.get("mean")),
        },
        "acs_primary_comparison": acs_primary_comparison,
        "us_distribution": {
            "values": us_distribution,
            "location_value": places_location_value,
            "label": (
                profile_json["places_measure"].get("short_question_text")
                or profile_json["places_measure"].get("measure")
                or profile_json["places_measure"].get("measure_id")
            ),
            "unit": "%",
        },
        "scatter": scatter_payload,
    }

    return ProfileBuildResult(
        profile_json=_sanitize_for_json(profile_json),
        chart_inputs=_sanitize_for_json(chart_inputs),
    )
