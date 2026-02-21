from __future__ import annotations

import re
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

ADJACENCY_TABLE_CANDIDATES: tuple[tuple[str, str, str], ...] = (
    ("county_adjacency", "county_fips", "neighbor_county_fips"),
    ("dim_county_adjacency", "location_id", "neighbor_location_id"),
    ("county_neighbors", "county_fips", "neighbor_county_fips"),
    ("county_neighbors", "location_id", "neighbor_location_id"),
)

STATE_ABBR_PATTERN = re.compile(r"(?:,|\s)([A-Za-z]{2})\s*$")
COUNTY_SUFFIX_PATTERN = re.compile(r"\bcounty\b", flags=re.IGNORECASE)
NON_ALNUM_PATTERN = re.compile(r"[^a-z0-9]+")
COUNTY_FRAGMENT_PATTERN = re.compile(
    r"([A-Za-z][A-Za-z .'-]*\sCounty(?:,\s*[A-Za-z]{2}|\s+[A-Za-z]{2})?)",
    flags=re.IGNORECASE,
)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:  # NaN check without extra imports
        return None
    return parsed


def _to_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(
        text("SELECT to_regclass(:table_name) AS regclass_name"),
        {"table_name": f"public.{table_name}"},
    ).mappings().one()
    return row["regclass_name"] is not None


def _clean_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def _normalize_county_name(value: str) -> str:
    stripped = COUNTY_SUFFIX_PATTERN.sub(" ", value or "")
    stripped = NON_ALNUM_PATTERN.sub(" ", stripped.lower()).strip()
    return " ".join(stripped.split())


def _extract_state_abbr_hint(query: str) -> str | None:
    normalized = re.sub(r"[^A-Za-z0-9,\s]", " ", query or "").strip()
    match = STATE_ABBR_PATTERN.search(normalized)
    if not match:
        return None
    token = match.group(1).upper()
    if len(token) == 2 and token.isalpha():
        return token
    return None


def _county_geom_clauses(db: Session, alias: str = "c") -> tuple[str, str]:
    if _table_exists(db, "dim_county_boundary"):
        join_clause = (
            f"LEFT JOIN dim_county_boundary AS b_{alias} "
            f"ON b_{alias}.location_id = {alias}.location_id"
        )
        geom_expr = f"COALESCE(b_{alias}.geom, {alias}.geom)"
        return join_clause, geom_expr
    return "", f"{alias}.geom"


def _measure_dim_id(
    db: Session,
    *,
    measure_id: str,
    data_value_type_id: str,
) -> int | None:
    row = db.execute(
        text(
            """
            SELECT id
            FROM dim_measure
            WHERE measure_id = :measure_id
              AND data_value_type_id = :data_value_type_id
            LIMIT 1
            """
        ),
        {
            "measure_id": measure_id,
            "data_value_type_id": data_value_type_id,
        },
    ).mappings().one_or_none()
    if row is None:
        return None
    return int(row["id"])


def resolve_county(db: Session, *, query: str) -> dict[str, Any]:
    cleaned_query = _clean_text(query)
    if not cleaned_query:
        return {
            "found": False,
            "match": None,
            "alternatives": [],
            "reason": "County query is empty.",
        }

    county_fragment_match = COUNTY_FRAGMENT_PATTERN.search(cleaned_query)
    if county_fragment_match:
        cleaned_query = _clean_text(county_fragment_match.group(1))

    if re.fullmatch(r"\d{5}", cleaned_query):
        geom_join, geom_expr = _county_geom_clauses(db, alias="c")
        row = db.execute(
            text(
                f"""
                SELECT
                    c.location_id AS county_fips,
                    c.county_name,
                    c.state_abbr,
                    ST_Y(ST_PointOnSurface({geom_expr})) AS lat,
                    ST_X(ST_PointOnSurface({geom_expr})) AS lng
                FROM dim_county AS c
                {geom_join}
                WHERE c.location_id = :county_fips
                LIMIT 1
                """
            ),
            {"county_fips": cleaned_query},
        ).mappings().one_or_none()

        if row is None:
            return {
                "found": False,
                "match": None,
                "alternatives": [],
                "reason": "County FIPS not found.",
            }
        return {
            "found": True,
            "match": {
                "county_fips": row["county_fips"],
                "county_name": row["county_name"],
                "state_abbr": row["state_abbr"],
                "lat": _safe_float(row["lat"]),
                "lng": _safe_float(row["lng"]),
            },
            "alternatives": [],
            "reason": None,
        }

    state_hint = _extract_state_abbr_hint(cleaned_query)
    query_without_state = cleaned_query
    if state_hint:
        query_without_state = re.sub(
            rf"(?:,|\s){state_hint}\s*$",
            "",
            cleaned_query,
            flags=re.IGNORECASE,
        ).strip(", ")

    base_county_name = _normalize_county_name(query_without_state or cleaned_query)
    contains_query = f"%{cleaned_query}%"
    token_pattern = "%" + "%".join(base_county_name.split()) + "%" if base_county_name else "%"
    prefix_pattern = f"{base_county_name}%" if base_county_name else "%"
    base_name_with_county = f"{base_county_name} county".strip()

    geom_join, geom_expr = _county_geom_clauses(db, alias="c")
    state_filter = "AND c.state_abbr = :state_abbr" if state_hint else ""
    params: dict[str, Any] = {
        "contains_query": contains_query,
        "token_pattern": token_pattern,
        "base_county_name": base_county_name,
        "base_name_with_county": base_name_with_county,
        "prefix_pattern": prefix_pattern,
        "limit": 10,
    }
    if state_hint:
        params["state_abbr"] = state_hint

    rows = db.execute(
        text(
            f"""
            SELECT
                c.location_id AS county_fips,
                c.county_name,
                c.state_abbr,
                ST_Y(ST_PointOnSurface({geom_expr})) AS lat,
                ST_X(ST_PointOnSurface({geom_expr})) AS lng
            FROM dim_county AS c
            {geom_join}
            WHERE {geom_expr} IS NOT NULL
              AND (
                c.county_name ILIKE :contains_query
                OR (c.county_name || ' county') ILIKE :contains_query
                OR (c.county_name || ', ' || c.state_abbr) ILIKE :contains_query
                OR lower(
                    trim(
                        concat_ws(' ', c.county_name, 'county', c.state_abbr, c.state_desc)
                    )
                ) LIKE :token_pattern
              )
              {state_filter}
            ORDER BY
                CASE
                    WHEN lower(c.county_name) = :base_county_name THEN 0
                    WHEN lower(c.county_name || ' county') = :base_name_with_county THEN 1
                    WHEN lower(c.county_name) LIKE :prefix_pattern THEN 2
                    ELSE 10
                END,
                c.state_abbr,
                c.county_name
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()

    if not rows:
        return {
            "found": False,
            "match": None,
            "alternatives": [],
            "reason": "No matching county found.",
        }

    candidates = [
        {
            "county_fips": row["county_fips"],
            "county_name": row["county_name"],
            "state_abbr": row["state_abbr"],
            "lat": _safe_float(row["lat"]),
            "lng": _safe_float(row["lng"]),
        }
        for row in rows
    ]

    normalized_query_name = _normalize_county_name(base_county_name)
    exact_name_candidates = [
        item
        for item in candidates
        if _normalize_county_name(item["county_name"]) == normalized_query_name
    ]

    selected: dict[str, Any] | None = None
    selection_reason: str | None = None
    if len(candidates) == 1:
        selected = candidates[0]
    elif len(exact_name_candidates) == 1:
        selected = exact_name_candidates[0]
        selection_reason = "Selected exact county-name match from multiple candidates."
    else:
        # Fallback to the top-ranked candidate from the SQL ORDER BY ranking.
        selected = candidates[0]
        selection_reason = "Selected best-guess county from multiple candidates."

    alternatives = [
        {
            "county_fips": item["county_fips"],
            "county_name": item["county_name"],
            "state_abbr": item["state_abbr"],
        }
        for item in candidates
        if selected is None or item["county_fips"] != selected["county_fips"]
    ][:5]

    if selected is None:
        return {
            "found": False,
            "match": None,
            "alternatives": alternatives,
            "reason": "No matching county found.",
        }

    return {
        "found": True,
        "match": {
            "county_fips": selected["county_fips"],
            "county_name": selected["county_name"],
            "state_abbr": selected["state_abbr"],
            "lat": selected["lat"],
            "lng": selected["lng"],
        },
        "alternatives": alternatives,
        "reason": selection_reason,
    }


def get_estimate_county(
    db: Session,
    *,
    county_fips: str,
    measure_id: str,
    year: int,
    data_value_type_id: str,
) -> dict[str, Any]:
    county_fips_value = str(county_fips or "").strip()
    measure_id_value = str(measure_id or "").strip()
    data_type_value = str(data_value_type_id or "").strip()
    year_value = _to_int(year, 0)

    measure_dim_id = _measure_dim_id(
        db,
        measure_id=measure_id_value,
        data_value_type_id=data_type_value,
    )
    if measure_dim_id is None:
        return {
            "found": False,
            "county_fips": county_fips_value,
            "county_name": None,
            "state_abbr": None,
            "measure_id": measure_id_value,
            "year": year_value,
            "data_value_type_id": data_type_value,
            "value": None,
            "ci_low": None,
            "ci_high": None,
            "unit": "%",
            "reason": "Measure/type combination not found.",
        }

    row = db.execute(
        text(
            """
            SELECT
                c.location_id AS county_fips,
                c.county_name,
                c.state_abbr,
                f.data_value AS value,
                f.low_confidence_limit AS ci_low,
                f.high_confidence_limit AS ci_high
            FROM dim_county AS c
            LEFT JOIN fact_estimate_county AS f
              ON f.location_id = c.location_id
             AND f.measure_dim_id = :measure_dim_id
             AND f.year = :year
            WHERE c.location_id = :county_fips
            LIMIT 1
            """
        ),
        {
            "county_fips": county_fips_value,
            "measure_dim_id": measure_dim_id,
            "year": year_value,
        },
    ).mappings().one_or_none()

    if row is None:
        return {
            "found": False,
            "county_fips": county_fips_value,
            "county_name": None,
            "state_abbr": None,
            "measure_id": measure_id_value,
            "year": year_value,
            "data_value_type_id": data_type_value,
            "value": None,
            "ci_low": None,
            "ci_high": None,
            "unit": "%",
            "reason": "County not found.",
        }

    value = _safe_float(row["value"])
    ci_low = _safe_float(row["ci_low"])
    ci_high = _safe_float(row["ci_high"])
    return {
        "found": value is not None,
        "county_fips": row["county_fips"],
        "county_name": row["county_name"],
        "state_abbr": row["state_abbr"],
        "measure_id": measure_id_value,
        "year": year_value,
        "data_value_type_id": data_type_value,
        "value": value,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "unit": "%",
        "reason": None if value is not None else "Estimate not found for county.",
    }


def _try_state_rollup_query(
    db: Session,
    *,
    state_abbr: str,
    measure_id: str,
    year: int,
    data_value_type_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    queries: list[tuple[str, str]] = [
        (
            "fact_estimate_state",
            """
            SELECT
                state_abbr,
                data_value AS value,
                low_confidence_limit AS ci_low,
                high_confidence_limit AS ci_high
            FROM fact_estimate_state
            WHERE upper(state_abbr) = :state_abbr
              AND measure_id = :measure_id
              AND year = :year
              AND data_value_type_id = :data_value_type_id
            LIMIT 1
            """,
        ),
        (
            "state_estimates",
            """
            SELECT
                state_abbr,
                data_value AS value,
                low_confidence_limit AS ci_low,
                high_confidence_limit AS ci_high
            FROM state_estimates
            WHERE upper(state_abbr) = :state_abbr
              AND measure_id = :measure_id
              AND year = :year
              AND data_value_type_id = :data_value_type_id
            LIMIT 1
            """,
        ),
        (
            "fact_state_estimate",
            """
            SELECT
                state_abbr,
                data_value AS value,
                low_confidence_limit AS ci_low,
                high_confidence_limit AS ci_high
            FROM fact_state_estimate
            WHERE upper(state_abbr) = :state_abbr
              AND measure_id = :measure_id
              AND year = :year
              AND data_value_type_id = :data_value_type_id
            LIMIT 1
            """,
        ),
    ]

    params = {
        "state_abbr": state_abbr.upper(),
        "measure_id": measure_id,
        "year": year,
        "data_value_type_id": data_value_type_id,
    }

    for table_name, query_sql in queries:
        if not _table_exists(db, table_name):
            continue
        try:
            row = db.execute(text(query_sql), params).mappings().one_or_none()
        except Exception:
            continue
        return (dict(row) if row is not None else None, table_name)
    return None, None


def get_estimate_state(
    db: Session,
    *,
    state_abbr: str,
    measure_id: str,
    year: int,
    data_value_type_id: str,
) -> dict[str, Any]:
    state_value = str(state_abbr or "").strip().upper()
    measure_id_value = str(measure_id or "").strip()
    data_type_value = str(data_value_type_id or "").strip()
    year_value = _to_int(year, 0)

    row, source_table = _try_state_rollup_query(
        db,
        state_abbr=state_value,
        measure_id=measure_id_value,
        year=year_value,
        data_value_type_id=data_type_value,
    )

    if source_table is None:
        return {
            "found": False,
            "state_abbr": state_value,
            "measure_id": measure_id_value,
            "year": year_value,
            "data_value_type_id": data_type_value,
            "value": None,
            "ci_low": None,
            "ci_high": None,
            "unit": "%",
            "reason": "State estimate table is unavailable.",
        }

    if row is None:
        return {
            "found": False,
            "state_abbr": state_value,
            "measure_id": measure_id_value,
            "year": year_value,
            "data_value_type_id": data_type_value,
            "value": None,
            "ci_low": None,
            "ci_high": None,
            "unit": "%",
            "reason": "State estimate not found.",
            "source_table": source_table,
        }

    value = _safe_float(row.get("value"))
    ci_low = _safe_float(row.get("ci_low"))
    ci_high = _safe_float(row.get("ci_high"))
    return {
        "found": value is not None,
        "state_abbr": str(row.get("state_abbr") or state_value).upper(),
        "measure_id": measure_id_value,
        "year": year_value,
        "data_value_type_id": data_type_value,
        "value": value,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "unit": "%",
        "reason": None if value is not None else "State estimate value is missing.",
        "source_table": source_table,
    }


def _try_nation_rollup_query(
    db: Session,
    *,
    measure_id: str,
    year: int,
    data_value_type_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    queries: list[tuple[str, str]] = [
        (
            "fact_estimate_nation",
            """
            SELECT
                data_value AS value,
                low_confidence_limit AS ci_low,
                high_confidence_limit AS ci_high
            FROM fact_estimate_nation
            WHERE measure_id = :measure_id
              AND year = :year
              AND data_value_type_id = :data_value_type_id
            LIMIT 1
            """,
        ),
        (
            "nation_estimates",
            """
            SELECT
                data_value AS value,
                low_confidence_limit AS ci_low,
                high_confidence_limit AS ci_high
            FROM nation_estimates
            WHERE measure_id = :measure_id
              AND year = :year
              AND data_value_type_id = :data_value_type_id
            LIMIT 1
            """,
        ),
        (
            "national_estimates",
            """
            SELECT
                data_value AS value,
                low_confidence_limit AS ci_low,
                high_confidence_limit AS ci_high
            FROM national_estimates
            WHERE measure_id = :measure_id
              AND year = :year
              AND data_value_type_id = :data_value_type_id
            LIMIT 1
            """,
        ),
        (
            "fact_nation_estimate",
            """
            SELECT
                data_value AS value,
                low_confidence_limit AS ci_low,
                high_confidence_limit AS ci_high
            FROM fact_nation_estimate
            WHERE measure_id = :measure_id
              AND year = :year
              AND data_value_type_id = :data_value_type_id
            LIMIT 1
            """,
        ),
    ]
    params = {
        "measure_id": measure_id,
        "year": year,
        "data_value_type_id": data_value_type_id,
    }
    for table_name, query_sql in queries:
        if not _table_exists(db, table_name):
            continue
        try:
            row = db.execute(text(query_sql), params).mappings().one_or_none()
        except Exception:
            continue
        return (dict(row) if row is not None else None, table_name)
    return None, None


def get_estimate_nation(
    db: Session,
    *,
    measure_id: str,
    year: int,
    data_value_type_id: str,
) -> dict[str, Any]:
    measure_id_value = str(measure_id or "").strip()
    data_type_value = str(data_value_type_id or "").strip()
    year_value = _to_int(year, 0)

    row, source_table = _try_nation_rollup_query(
        db,
        measure_id=measure_id_value,
        year=year_value,
        data_value_type_id=data_type_value,
    )

    if source_table is None:
        return {
            "found": False,
            "scope": "US",
            "measure_id": measure_id_value,
            "year": year_value,
            "data_value_type_id": data_type_value,
            "value": None,
            "ci_low": None,
            "ci_high": None,
            "unit": "%",
            "reason": "National estimate table is unavailable.",
        }

    if row is None:
        return {
            "found": False,
            "scope": "US",
            "measure_id": measure_id_value,
            "year": year_value,
            "data_value_type_id": data_type_value,
            "value": None,
            "ci_low": None,
            "ci_high": None,
            "unit": "%",
            "reason": "National estimate not found.",
            "source_table": source_table,
        }

    value = _safe_float(row.get("value"))
    ci_low = _safe_float(row.get("ci_low"))
    ci_high = _safe_float(row.get("ci_high"))
    return {
        "found": value is not None,
        "scope": "US",
        "measure_id": measure_id_value,
        "year": year_value,
        "data_value_type_id": data_type_value,
        "value": value,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "unit": "%",
        "reason": None if value is not None else "National estimate value is missing.",
        "source_table": source_table,
    }


def _adjacent_neighbor_rows(
    db: Session,
    *,
    county_fips: str,
    k: int,
) -> tuple[list[dict[str, Any]], str | None]:
    for table_name, source_column, neighbor_column in ADJACENCY_TABLE_CANDIDATES:
        if not _table_exists(db, table_name):
            continue
        try:
            rows = db.execute(
                text(
                    f"""
                    SELECT
                        n.location_id AS county_fips,
                        n.county_name,
                        n.state_abbr,
                        ST_Y(ST_PointOnSurface(n.geom)) AS lat,
                        ST_X(ST_PointOnSurface(n.geom)) AS lng
                    FROM {table_name} AS a
                    JOIN dim_county AS n
                      ON n.location_id = a.{neighbor_column}
                    WHERE a.{source_column} = :county_fips
                    UNION
                    SELECT
                        n.location_id AS county_fips,
                        n.county_name,
                        n.state_abbr,
                        ST_Y(ST_PointOnSurface(n.geom)) AS lat,
                        ST_X(ST_PointOnSurface(n.geom)) AS lng
                    FROM {table_name} AS a
                    JOIN dim_county AS n
                      ON n.location_id = a.{source_column}
                    WHERE a.{neighbor_column} = :county_fips
                    ORDER BY county_fips
                    LIMIT :k
                    """
                ),
                {"county_fips": county_fips, "k": k},
            ).mappings().all()
        except Exception:
            continue

        if rows:
            return [
                {
                    "county_fips": row["county_fips"],
                    "county_name": row["county_name"],
                    "state_abbr": row["state_abbr"],
                    "lat": _safe_float(row["lat"]),
                    "lng": _safe_float(row["lng"]),
                }
                for row in rows
            ], f"adjacency:{table_name}"

    return [], None


def _distance_neighbor_rows(
    db: Session,
    *,
    county_fips: str,
    k: int,
) -> list[dict[str, Any]]:
    if _table_exists(db, "dim_county_boundary"):
        target_join = "LEFT JOIN dim_county_boundary AS b ON b.location_id = c.location_id"
        target_geom = "COALESCE(b.geom, c.geom)"
        neighbor_join = (
            "LEFT JOIN dim_county_boundary AS b2 ON b2.location_id = c2.location_id"
        )
        neighbor_geom = "COALESCE(b2.geom, c2.geom)"
    else:
        target_join = ""
        target_geom = "c.geom"
        neighbor_join = ""
        neighbor_geom = "c2.geom"

    rows = db.execute(
        text(
            f"""
            WITH target AS (
                SELECT ST_PointOnSurface({target_geom}) AS geom
                FROM dim_county AS c
                {target_join}
                WHERE c.location_id = :county_fips
                  AND {target_geom} IS NOT NULL
                LIMIT 1
            )
            SELECT
                c2.location_id AS county_fips,
                c2.county_name,
                c2.state_abbr,
                ST_Y(ST_PointOnSurface({neighbor_geom})) AS lat,
                ST_X(ST_PointOnSurface({neighbor_geom})) AS lng
            FROM dim_county AS c2
            {neighbor_join}
            CROSS JOIN target
            WHERE c2.location_id <> :county_fips
              AND {neighbor_geom} IS NOT NULL
            ORDER BY ST_DistanceSphere(ST_PointOnSurface({neighbor_geom}), target.geom)
            LIMIT :k
            """
        ),
        {"county_fips": county_fips, "k": k},
    ).mappings().all()

    return [
        {
            "county_fips": row["county_fips"],
            "county_name": row["county_name"],
            "state_abbr": row["state_abbr"],
            "lat": _safe_float(row["lat"]),
            "lng": _safe_float(row["lng"]),
        }
        for row in rows
    ]


def get_neighbor_counties(
    db: Session,
    *,
    county_fips: str,
    k: int = 5,
) -> dict[str, Any]:
    county_fips_value = str(county_fips or "").strip()
    k_value = max(1, min(_to_int(k, 5), 10))

    if not county_fips_value:
        return {
            "found": False,
            "county_fips": county_fips_value,
            "neighbors": [],
            "method": "none",
            "reason": "county_fips is required.",
        }

    adjacency_neighbors, method = _adjacent_neighbor_rows(
        db,
        county_fips=county_fips_value,
        k=k_value,
    )
    if adjacency_neighbors:
        return {
            "found": True,
            "county_fips": county_fips_value,
            "neighbors": adjacency_neighbors,
            "method": method,
            "reason": None,
        }

    distance_neighbors = _distance_neighbor_rows(
        db,
        county_fips=county_fips_value,
        k=k_value,
    )
    return {
        "found": len(distance_neighbors) > 0,
        "county_fips": county_fips_value,
        "neighbors": distance_neighbors,
        "method": "centroid_distance_fallback",
        "reason": None if distance_neighbors else "No neighboring counties found.",
    }


def get_estimates_for_counties(
    db: Session,
    *,
    county_fips_list: list[str],
    measure_id: str,
    year: int,
    data_value_type_id: str,
) -> dict[str, Any]:
    cleaned_fips: list[str] = []
    seen: set[str] = set()
    for raw in county_fips_list:
        county_fips = str(raw or "").strip()
        if not county_fips or county_fips in seen:
            continue
        seen.add(county_fips)
        cleaned_fips.append(county_fips)

    if not cleaned_fips:
        return {
            "found": False,
            "counties": [],
            "reason": "county_fips_list is empty.",
        }

    measure_id_value = str(measure_id or "").strip()
    data_type_value = str(data_value_type_id or "").strip()
    year_value = _to_int(year, 0)

    measure_dim_id = _measure_dim_id(
        db,
        measure_id=measure_id_value,
        data_value_type_id=data_type_value,
    )
    if measure_dim_id is None:
        return {
            "found": False,
            "counties": [
                {
                    "county_fips": county_fips,
                    "county_name": None,
                    "state_abbr": None,
                    "found": False,
                    "value": None,
                    "ci_low": None,
                    "ci_high": None,
                    "unit": "%",
                    "reason": "Measure/type combination not found.",
                }
                for county_fips in cleaned_fips
            ],
            "reason": "Measure/type combination not found.",
        }

    query = (
        text(
            """
            SELECT
                c.location_id AS county_fips,
                c.county_name,
                c.state_abbr,
                f.data_value AS value,
                f.low_confidence_limit AS ci_low,
                f.high_confidence_limit AS ci_high
            FROM dim_county AS c
            LEFT JOIN fact_estimate_county AS f
              ON f.location_id = c.location_id
             AND f.measure_dim_id = :measure_dim_id
             AND f.year = :year
            WHERE c.location_id IN :county_fips_list
            """
        )
        .bindparams(bindparam("county_fips_list", expanding=True))
    )
    rows = db.execute(
        query,
        {
            "county_fips_list": cleaned_fips,
            "measure_dim_id": measure_dim_id,
            "year": year_value,
        },
    ).mappings().all()

    by_fips = {
        row["county_fips"]: {
            "county_fips": row["county_fips"],
            "county_name": row["county_name"],
            "state_abbr": row["state_abbr"],
            "value": _safe_float(row["value"]),
            "ci_low": _safe_float(row["ci_low"]),
            "ci_high": _safe_float(row["ci_high"]),
        }
        for row in rows
    }

    counties: list[dict[str, Any]] = []
    for county_fips in cleaned_fips:
        row = by_fips.get(county_fips)
        if row is None:
            counties.append(
                {
                    "county_fips": county_fips,
                    "county_name": None,
                    "state_abbr": None,
                    "found": False,
                    "value": None,
                    "ci_low": None,
                    "ci_high": None,
                    "unit": "%",
                    "reason": "County not found.",
                }
            )
            continue
        value = row["value"]
        counties.append(
            {
                "county_fips": row["county_fips"],
                "county_name": row["county_name"],
                "state_abbr": row["state_abbr"],
                "found": value is not None,
                "value": value,
                "ci_low": row["ci_low"],
                "ci_high": row["ci_high"],
                "unit": "%",
                "reason": None if value is not None else "Estimate not found for county.",
            }
        )

    return {
        "found": any(item["found"] for item in counties),
        "counties": counties,
        "reason": None,
    }
