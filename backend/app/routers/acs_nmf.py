import math
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Float, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from app.db import get_db
from app.db_fqtn import acs_table

router = APIRouter(tags=["acs-nmf"])

YEAR_WINDOW_RE = re.compile(r"^(\d{4})\s*-\s*(\d{4})$")
COUNTY_TABLE = "acs_nmf_county_estimates"
TRACT_TABLE = "acs_nmf_tract_estimates"

STATE_ABBR_TO_FIPS = {
    "AL": "01",
    "AK": "02",
    "AZ": "04",
    "AR": "05",
    "CA": "06",
    "CO": "08",
    "CT": "09",
    "DE": "10",
    "DC": "11",
    "FL": "12",
    "GA": "13",
    "HI": "15",
    "ID": "16",
    "IL": "17",
    "IN": "18",
    "IA": "19",
    "KS": "20",
    "KY": "21",
    "LA": "22",
    "ME": "23",
    "MD": "24",
    "MA": "25",
    "MI": "26",
    "MN": "27",
    "MS": "28",
    "MO": "29",
    "MT": "30",
    "NE": "31",
    "NV": "32",
    "NH": "33",
    "NJ": "34",
    "NM": "35",
    "NY": "36",
    "NC": "37",
    "ND": "38",
    "OH": "39",
    "OK": "40",
    "OR": "41",
    "PA": "42",
    "RI": "44",
    "SC": "45",
    "SD": "46",
    "TN": "47",
    "TX": "48",
    "UT": "49",
    "VT": "50",
    "VA": "51",
    "WA": "53",
    "WV": "54",
    "WI": "55",
    "WY": "56",
    "PR": "72",
}
STATE_FIPS_TO_ABBR = {value: key for key, value in STATE_ABBR_TO_FIPS.items()}


def json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def deep_json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {key: deep_json_safe(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [deep_json_safe(value) for value in obj]
    return json_safe(obj)


def _finite_float_sql(column_sql: str) -> str:
    return (
        f"{column_sql} NOT IN ("
        "'NaN'::double precision, "
        "'Infinity'::double precision, "
        "'-Infinity'::double precision"
        ")"
    )


def _ensure_required_tables(db: Session, *table_names: str) -> None:
    for table_name in table_names:
        row = db.execute(
            text("SELECT to_regclass(:name) AS exists"),
            {"name": acs_table(table_name)},
        ).mappings().one()
        if row["exists"] is None:
            raise HTTPException(
                status_code=503,
                detail=f"{table_name} is missing. Run migrations and load required data.",
            )


def _year_window_sort_key(value: str) -> tuple[int, int, str]:
    match = YEAR_WINDOW_RE.match(str(value or "").strip())
    if not match:
        return (-1, -1, str(value or ""))
    start = int(match.group(1))
    end = int(match.group(2))
    return (end, start, str(value))


def _resolve_year_window(
    db: Session,
    table_name: str,
    requested_year_window: str | None,
) -> str:
    if requested_year_window:
        year_window = requested_year_window.strip()
        exists = db.execute(
            text(
                f"""
                SELECT EXISTS (
                    SELECT 1
                    FROM {table_name}
                    WHERE year_window = :year_window
                ) AS exists
                """
            ),
            {"year_window": year_window},
        ).mappings().one()
        if not exists["exists"]:
            raise HTTPException(
                status_code=404,
                detail=f"No ACS NMF rows found for year_window={year_window}",
            )
        return year_window

    row = db.execute(
        text(
            f"""
            SELECT year_window
            FROM {table_name}
            ORDER BY
                CASE
                    WHEN year_window ~ '^[0-9]{{4}}-[0-9]{{4}}$'
                    THEN split_part(year_window, '-', 2)::int
                    ELSE NULL
                END DESC NULLS LAST,
                year_window DESC
            LIMIT 1
            """
        )
    ).mappings().one_or_none()

    if row is None or row["year_window"] is None:
        raise HTTPException(status_code=404, detail="ACS NMF table is empty")

    return str(row["year_window"])


def _resolve_data_value_type_id(
    db: Session,
    table_name: str,
    year_window: str,
    measure_id: str,
    requested_data_value_type_id: str | None,
) -> str:
    requested = (
        str(requested_data_value_type_id).strip()
        if requested_data_value_type_id is not None
        else None
    )

    rows = db.execute(
        text(
            f"""
            SELECT DISTINCT data_value_type_id
            FROM {table_name}
            WHERE year_window = :year_window
              AND measure_id = :measure_id
            ORDER BY data_value_type_id
            """
        ),
        {"year_window": year_window, "measure_id": measure_id},
    ).scalars().all()
    available = [str(value) for value in rows if value is not None]

    if not available:
        raise HTTPException(
            status_code=404,
            detail=(
                "No ACS NMF rows found for "
                f"measure_id={measure_id} and year_window={year_window}"
            ),
        )

    if requested:
        if requested not in available:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"data_value_type_id={requested} is unavailable for "
                    f"measure_id={measure_id} and year_window={year_window}"
                ),
            )
        return requested

    if "Percent" in available:
        return "Percent"

    return available[0]


def _parse_bbox(
    bbox: str | None,
    geom_alias: str,
) -> tuple[dict[str, float], str, str, str]:
    if not bbox:
        return ({}, "", "", "")

    try:
        minx, miny, maxx, maxy = (float(value) for value in bbox.split(","))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid bbox format") from exc

    if minx >= maxx or miny >= maxy:
        raise HTTPException(status_code=400, detail="Invalid bbox bounds")

    return (
        {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy},
        "bbox AS (SELECT ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) AS geom)",
        "CROSS JOIN bbox",
        (
            f"AND {geom_alias}.geom && bbox.geom "
            f"AND ST_Intersects({geom_alias}.geom, bbox.geom)"
        ),
    )


def _list_measures(db: Session, table_name: str) -> list[dict[str, object]]:
    rows = db.execute(
        text(
            f"""
            SELECT
                category_id,
                category,
                measure_id,
                measure,
                year_window,
                data_value_type_id,
                data_value_type
            FROM {table_name}
            ORDER BY category, measure, measure_id
            """
        )
    ).mappings().all()

    grouped: dict[tuple[str, str, str, str], dict[str, object]] = {}
    for row in rows:
        group_key = (
            str(row["category_id"]),
            str(row["category"]),
            str(row["measure_id"]),
            str(row["measure"]),
        )
        if group_key not in grouped:
            grouped[group_key] = {
                "category_id": group_key[0],
                "category": group_key[1],
                "measure_id": group_key[2],
                "measure": group_key[3],
                "year_windows": set(),
                "data_value_type_ids": set(),
                "data_value_types": {},
            }

        grouped[group_key]["year_windows"].add(str(row["year_window"]))
        dtype_id = str(row["data_value_type_id"])
        grouped[group_key]["data_value_type_ids"].add(dtype_id)
        if row["data_value_type"] is not None:
            grouped[group_key]["data_value_types"][dtype_id] = str(row["data_value_type"])

    measures = []
    for item in grouped.values():
        sorted_year_windows = sorted(
            item["year_windows"],
            key=_year_window_sort_key,
            reverse=True,
        )
        sorted_type_ids = sorted(item["data_value_type_ids"])
        default_data_value_type_id = (
            "Percent" if "Percent" in sorted_type_ids else sorted_type_ids[0]
        )

        measures.append(
            {
                "category_id": item["category_id"],
                "category": item["category"],
                "measure_id": item["measure_id"],
                "measure": item["measure"],
                "year_windows": sorted_year_windows,
                "data_value_type_ids": sorted_type_ids,
                "data_value_types": item["data_value_types"],
                "default_data_value_type_id": default_data_value_type_id,
            }
        )

    measures.sort(
        key=lambda row: ((row.get("category") or "").lower(), (row.get("measure") or "").lower())
    )
    return measures


def _build_acs_legend_payload(
    *,
    measure_id: str,
    year_window: str,
    data_value_type_id: str,
    n: int,
    no_data_count: int,
    raw_quantiles: list[Any],
    min_value: Any,
    max_value: Any,
) -> dict[str, Any]:
    values = [min_value, *(raw_quantiles or []), max_value]
    values = [
        float(value)
        for value in values
        if value is not None and isinstance(value, (int, float)) and math.isfinite(float(value))
    ]

    if not values:
        payload = {
            "measure_id": measure_id,
            "year_window": year_window,
            "data_value_type_id": data_value_type_id,
            "bins": [],
            "min": None,
            "max": None,
            "noDataCount": int(no_data_count),
            "n": 0,
        }
        return deep_json_safe(payload)

    breaks = [values[0]]
    for value in values[1:]:
        if value > breaks[-1]:
            breaks.append(value)

    if len(breaks) < 2:
        breaks.append(breaks[0])

    bins_payload = []
    for index, start in enumerate(breaks[:-1]):
        end = breaks[index + 1]
        bins_payload.append(
            {
                "min": float(start),
                "max": float(end),
                "label": f"{float(start):.1f} - {float(end):.1f}",
                "colorIndex": index,
            }
        )

    payload = {
        "measure_id": measure_id,
        "year_window": year_window,
        "data_value_type_id": data_value_type_id,
        "bins": bins_payload,
        "min": float(breaks[0]),
        "max": float(breaks[-1]),
        "noDataCount": int(no_data_count),
        "n": int(n),
    }
    return deep_json_safe(payload)


@router.get("/acs-nmf/measures")
def acs_nmf_measures(db: Session = Depends(get_db)):
    _ensure_required_tables(db, COUNTY_TABLE)
    return _list_measures(db, COUNTY_TABLE)


@router.get("/acs-nmf/tracts/measures")
def acs_nmf_tract_measures(db: Session = Depends(get_db)):
    _ensure_required_tables(db, TRACT_TABLE)
    return _list_measures(db, TRACT_TABLE)


@router.get("/acs-nmf/counties")
def acs_nmf_counties_geojson(
    measure_id: str = Query(..., min_length=1),
    year_window: str | None = Query(default=None),
    data_value_type_id: str | None = Query(default=None),
    bbox: str | None = Query(default=None),
    simplify: float | None = Query(default=0.02, gt=0, le=0.5),
    limit: int = Query(default=5000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    _ensure_required_tables(db, COUNTY_TABLE, "dim_county_boundary")

    safe_measure_id = measure_id.strip()
    if not safe_measure_id:
        raise HTTPException(status_code=400, detail="measure_id is required")

    resolved_year_window = _resolve_year_window(db, COUNTY_TABLE, year_window)
    resolved_data_value_type_id = _resolve_data_value_type_id(
        db,
        COUNTY_TABLE,
        year_window=resolved_year_window,
        measure_id=safe_measure_id,
        requested_data_value_type_id=data_value_type_id,
    )

    bbox_params, bbox_cte, bbox_join, bbox_filter = _parse_bbox(bbox, geom_alias="b")

    params: dict[str, object] = {
        "measure_id": safe_measure_id,
        "year_window": resolved_year_window,
        "data_value_type_id": resolved_data_value_type_id,
        "limit": limit,
        "offset": offset,
    }
    params.update(bbox_params)

    geometry_expr = "ST_AsGeoJSON(b.geom)::json"
    if simplify is not None:
        geometry_expr = "ST_AsGeoJSON(ST_SimplifyPreserveTopology(b.geom, :simplify))::json"
        params["simplify"] = simplify

    with_parts = []
    if bbox_cte:
        with_parts.append(bbox_cte)
    with_parts.append(
        f"""
        selected_measure_meta AS (
            SELECT
                category_id,
                category,
                measure_id,
                measure
            FROM {COUNTY_TABLE}
            WHERE measure_id = :measure_id
              AND year_window = :year_window
            ORDER BY CASE WHEN data_value_type_id = :data_value_type_id THEN 0 ELSE 1 END,
                     location_id
            LIMIT 1
        )
        """
    )
    with_clause = ", ".join(with_parts)

    rows = db.execute(
        text(
            f"""
            WITH {with_clause}
            SELECT
                b.location_id,
                b.geoid,
                b.name,
                b.statefp,
                b.countyfp,
                COALESCE(a.state_abbr, c.state_abbr) AS state_abbr,
                COALESCE(a.location_name, c.county_name, b.name) AS location_name,
                COALESCE(a.year_window, :year_window) AS year_window,
                COALESCE(a.measure_id, sm.measure_id, :measure_id) AS measure_id,
                COALESCE(a.measure, sm.measure) AS measure,
                COALESCE(a.category, sm.category) AS category,
                COALESCE(a.category_id, sm.category_id) AS category_id,
                COALESCE(a.data_value_type_id, :data_value_type_id) AS data_value_type_id,
                a.data_value_type,
                a.data_value AS value,
                a.moe,
                a.total_population,
                {geometry_expr} AS geometry
            FROM dim_county_boundary AS b
            {bbox_join}
            LEFT JOIN dim_county AS c
                ON c.location_id = b.location_id
            LEFT JOIN selected_measure_meta AS sm ON TRUE
            LEFT JOIN {COUNTY_TABLE} AS a
                ON a.location_id = b.location_id
                AND a.year_window = :year_window
                AND a.measure_id = :measure_id
                AND a.data_value_type_id = :data_value_type_id
            WHERE b.geom IS NOT NULL
                {bbox_filter}
            ORDER BY b.location_id
            LIMIT :limit
            OFFSET :offset
            """
        ),
        params,
    ).mappings().all()

    features = [
        {
            "type": "Feature",
            "geometry": row["geometry"],
            "properties": {
                "location_id": row["location_id"],
                "locationid": row["location_id"],
                "geoid": row["geoid"],
                "name": row["name"],
                "statefp": row["statefp"],
                "countyfp": row["countyfp"],
                "state_abbr": row["state_abbr"],
                "location_name": row["location_name"],
                "year_window": row["year_window"],
                "measure_id": row["measure_id"],
                "measure": row["measure"],
                "category": row["category"],
                "category_id": row["category_id"],
                "data_value_type_id": row["data_value_type_id"],
                "data_value_type": row["data_value_type"],
                "value": row["value"],
                "data_value": row["value"],
                "moe": row["moe"],
                "total_population": row["total_population"],
                "population": row["total_population"],
                "geo_level": "county",
            },
        }
        for row in rows
    ]

    payload = {
        "type": "FeatureCollection",
        "features": features,
        "measure_id": safe_measure_id,
        "year_window": resolved_year_window,
        "data_value_type_id": resolved_data_value_type_id,
    }
    return deep_json_safe(payload)


@router.get("/acs-nmf/tracts")
def acs_nmf_tracts_geojson(
    measure_id: str = Query(..., min_length=1),
    year_window: str | None = Query(default=None),
    data_value_type_id: str | None = Query(default=None),
    bbox: str | None = Query(default=None),
    simplify: float | None = Query(default=0.001, gt=0, le=0.1),
    limit: int = Query(default=25000, ge=1, le=50000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    _ensure_required_tables(db, TRACT_TABLE, "tract_shapes")

    safe_measure_id = measure_id.strip()
    if not safe_measure_id:
        raise HTTPException(status_code=400, detail="measure_id is required")

    resolved_year_window = _resolve_year_window(db, TRACT_TABLE, year_window)
    resolved_data_value_type_id = _resolve_data_value_type_id(
        db,
        TRACT_TABLE,
        year_window=resolved_year_window,
        measure_id=safe_measure_id,
        requested_data_value_type_id=data_value_type_id,
    )

    bbox_params, bbox_cte, bbox_join, bbox_filter = _parse_bbox(bbox, geom_alias="s")

    params: dict[str, object] = {
        "measure_id": safe_measure_id,
        "year_window": resolved_year_window,
        "data_value_type_id": resolved_data_value_type_id,
        "limit": limit,
        "offset": offset,
    }
    params.update(bbox_params)

    geometry_expr = "ST_AsGeoJSON(s.geom)::json"
    if simplify is not None:
        geometry_expr = "ST_AsGeoJSON(ST_SimplifyPreserveTopology(s.geom, :simplify))::json"
        params["simplify"] = simplify

    with_parts = []
    if bbox_cte:
        with_parts.append(bbox_cte)
    with_parts.append(
        f"""
        selected_measure_meta AS (
            SELECT
                category_id,
                category,
                measure_id,
                measure
            FROM {TRACT_TABLE}
            WHERE measure_id = :measure_id
              AND year_window = :year_window
            ORDER BY CASE WHEN data_value_type_id = :data_value_type_id THEN 0 ELSE 1 END,
                     location_id
            LIMIT 1
        )
        """
    )
    with_clause = ", ".join(with_parts)

    rows = db.execute(
        text(
            f"""
            WITH {with_clause}
            SELECT
                s.geoid11 AS location_id,
                s.name AS tract_name,
                s.statefp,
                s.countyfp,
                COALESCE(a.state_abbr, '') AS state_abbr,
                COALESCE(a.location_name, s.name, s.geoid11) AS location_name,
                COALESCE(a.year_window, :year_window) AS year_window,
                COALESCE(a.measure_id, sm.measure_id, :measure_id) AS measure_id,
                COALESCE(a.measure, sm.measure) AS measure,
                COALESCE(a.category, sm.category) AS category,
                COALESCE(a.category_id, sm.category_id) AS category_id,
                COALESCE(a.data_value_type_id, :data_value_type_id) AS data_value_type_id,
                a.data_value_type,
                a.data_value AS value,
                a.moe,
                a.total_population,
                {geometry_expr} AS geometry
            FROM tract_shapes AS s
            {bbox_join}
            LEFT JOIN selected_measure_meta AS sm ON TRUE
            LEFT JOIN {TRACT_TABLE} AS a
                ON a.location_id = s.geoid11
                AND a.year_window = :year_window
                AND a.measure_id = :measure_id
                AND a.data_value_type_id = :data_value_type_id
            WHERE s.geom IS NOT NULL
                {bbox_filter}
            ORDER BY s.geoid11
            LIMIT :limit
            OFFSET :offset
            """
        ),
        params,
    ).mappings().all()

    features = []
    for row in rows:
        state_abbr_value = row["state_abbr"] or STATE_FIPS_TO_ABBR.get(row["statefp"])
        features.append(
            {
                "type": "Feature",
                "geometry": row["geometry"],
                "properties": {
                    "location_id": row["location_id"],
                    "locationid": row["location_id"],
                    "geoid": row["location_id"],
                    "name": row["tract_name"],
                    "statefp": row["statefp"],
                    "countyfp": row["countyfp"],
                    "county_fips": f"{row['statefp']}{row['countyfp']}",
                    "state_abbr": state_abbr_value,
                    "location_name": row["location_name"],
                    "year_window": row["year_window"],
                    "measure_id": row["measure_id"],
                    "measure": row["measure"],
                    "measure_name": row["measure"],
                    "category": row["category"],
                    "category_id": row["category_id"],
                    "data_value_type_id": row["data_value_type_id"],
                    "data_value_type": row["data_value_type"],
                    "value": row["value"],
                    "data_value": row["value"],
                    "moe": row["moe"],
                    "total_population": row["total_population"],
                    "population": row["total_population"],
                    "geo_level": "tract",
                },
            }
        )

    payload = {
        "type": "FeatureCollection",
        "features": features,
        "measure_id": safe_measure_id,
        "year_window": resolved_year_window,
        "data_value_type_id": resolved_data_value_type_id,
    }
    return deep_json_safe(payload)


@router.get("/acs-nmf/legend")
def acs_nmf_legend(
    measure_id: str = Query(..., min_length=1),
    year_window: str | None = Query(default=None),
    data_value_type_id: str | None = Query(default=None),
    bins: int = Query(default=5, ge=2, le=9),
    db: Session = Depends(get_db),
):
    _ensure_required_tables(db, COUNTY_TABLE, "dim_county_boundary")

    safe_measure_id = measure_id.strip()
    if not safe_measure_id:
        raise HTTPException(status_code=400, detail="measure_id is required")

    resolved_year_window = _resolve_year_window(db, COUNTY_TABLE, year_window)
    resolved_data_value_type_id = _resolve_data_value_type_id(
        db,
        COUNTY_TABLE,
        year_window=resolved_year_window,
        measure_id=safe_measure_id,
        requested_data_value_type_id=data_value_type_id,
    )

    quantile_fractions = [i / bins for i in range(1, bins)]
    finite_value_expr = _finite_float_sql("e.data_value")

    sql = text(
        f"""
        SELECT
            COUNT(*) FILTER (
                WHERE e.data_value IS NOT NULL
                  AND {finite_value_expr}
            ) AS n,
            COUNT(*) FILTER (
                WHERE e.data_value IS NULL
                  OR NOT ({finite_value_expr})
            ) AS nulls,
            MIN(e.data_value) FILTER (
                WHERE e.data_value IS NOT NULL
                  AND {finite_value_expr}
            ) AS min,
            MAX(e.data_value) FILTER (
                WHERE e.data_value IS NOT NULL
                  AND {finite_value_expr}
            ) AS max,
            COALESCE(
                percentile_cont(:quantiles)
                  WITHIN GROUP (ORDER BY e.data_value)
                  FILTER (
                      WHERE e.data_value IS NOT NULL
                        AND {finite_value_expr}
                  ),
                ARRAY[]::float8[]
            ) AS quantiles
        FROM dim_county_boundary AS b
        LEFT JOIN {COUNTY_TABLE} AS e
            ON e.location_id = b.location_id
            AND e.year_window = :year_window
            AND e.measure_id = :measure_id
            AND e.data_value_type_id = :data_value_type_id
        WHERE b.geom IS NOT NULL
        """
    ).bindparams(bindparam("quantiles", type_=ARRAY(Float)))

    row = db.execute(
        sql,
        {
            "year_window": resolved_year_window,
            "measure_id": safe_measure_id,
            "data_value_type_id": resolved_data_value_type_id,
            "quantiles": quantile_fractions,
        },
    ).mappings().one()

    n = int(row["n"] or 0)
    no_data_count = int(row["nulls"] or 0)
    payload = _build_acs_legend_payload(
        measure_id=safe_measure_id,
        year_window=resolved_year_window,
        data_value_type_id=resolved_data_value_type_id,
        n=n,
        no_data_count=no_data_count,
        raw_quantiles=list(row["quantiles"] or []),
        min_value=row["min"],
        max_value=row["max"],
    )
    return payload


@router.get("/acs-nmf/tracts/legend")
def acs_nmf_tract_legend(
    measure_id: str = Query(..., min_length=1),
    year_window: str | None = Query(default=None),
    data_value_type_id: str | None = Query(default=None),
    bbox: str | None = Query(default=None),
    bins: int = Query(default=5, ge=2, le=9),
    db: Session = Depends(get_db),
):
    _ensure_required_tables(db, TRACT_TABLE, "tract_shapes")

    safe_measure_id = measure_id.strip()
    if not safe_measure_id:
        raise HTTPException(status_code=400, detail="measure_id is required")

    resolved_year_window = _resolve_year_window(db, TRACT_TABLE, year_window)
    resolved_data_value_type_id = _resolve_data_value_type_id(
        db,
        TRACT_TABLE,
        year_window=resolved_year_window,
        measure_id=safe_measure_id,
        requested_data_value_type_id=data_value_type_id,
    )

    bbox_params, bbox_cte, bbox_join, bbox_filter = _parse_bbox(bbox, geom_alias="s")
    quantile_fractions = [i / bins for i in range(1, bins)]
    finite_value_expr = _finite_float_sql("e.data_value")

    params: dict[str, object] = {
        "year_window": resolved_year_window,
        "measure_id": safe_measure_id,
        "data_value_type_id": resolved_data_value_type_id,
        "quantiles": quantile_fractions,
    }
    params.update(bbox_params)

    with_clause = f"WITH {bbox_cte}" if bbox_cte else ""

    sql = text(
        f"""
        {with_clause}
        SELECT
            COUNT(*) FILTER (
                WHERE e.data_value IS NOT NULL
                  AND {finite_value_expr}
            ) AS n,
            COUNT(*) FILTER (
                WHERE e.data_value IS NULL
                  OR NOT ({finite_value_expr})
            ) AS nulls,
            MIN(e.data_value) FILTER (
                WHERE e.data_value IS NOT NULL
                  AND {finite_value_expr}
            ) AS min,
            MAX(e.data_value) FILTER (
                WHERE e.data_value IS NOT NULL
                  AND {finite_value_expr}
            ) AS max,
            COALESCE(
                percentile_cont(:quantiles)
                  WITHIN GROUP (ORDER BY e.data_value)
                  FILTER (
                      WHERE e.data_value IS NOT NULL
                        AND {finite_value_expr}
                  ),
                ARRAY[]::float8[]
            ) AS quantiles
        FROM tract_shapes AS s
        {bbox_join}
        LEFT JOIN {TRACT_TABLE} AS e
            ON e.location_id = s.geoid11
            AND e.year_window = :year_window
            AND e.measure_id = :measure_id
            AND e.data_value_type_id = :data_value_type_id
        WHERE s.geom IS NOT NULL
            {bbox_filter}
        """
    ).bindparams(bindparam("quantiles", type_=ARRAY(Float)))

    row = db.execute(sql, params).mappings().one()

    n = int(row["n"] or 0)
    no_data_count = int(row["nulls"] or 0)
    payload = _build_acs_legend_payload(
        measure_id=safe_measure_id,
        year_window=resolved_year_window,
        data_value_type_id=resolved_data_value_type_id,
        n=n,
        no_data_count=no_data_count,
        raw_quantiles=list(row["quantiles"] or []),
        min_value=row["min"],
        max_value=row["max"],
    )
    return payload
