from __future__ import annotations

import math
import re
from decimal import Decimal
from numbers import Real
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Float, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from app.db_fqtn import fema_nri_table
from app.fema_nri import catalog

COUNTY_TABLE = fema_nri_table("nri_county")
TRACT_TABLE = fema_nri_table("nri_tract")
DATASET_META_TABLE = fema_nri_table("dataset_meta")

FEMA_TRACT_ZOOM_THRESHOLD = 10
BINS_DEFAULT = 5
MAP_GEOJSON_PRECISION = 6
MISSING_TOKENS = {"", "na", "n/a", "null", "none", "-9999", "-8888"}

RATING_COLOR_ORDER = [
    "Very Low",
    "Low",
    "Moderate",
    "High",
    "Very High",
]
RATING_NORMALIZATION = {
    "VERYLOW": "Very Low",
    "VERY LOW": "Very Low",
    "VLOW": "Very Low",
    "LOW": "Low",
    "MODERATE": "Moderate",
    "MOD": "Moderate",
    "HIGH": "High",
    "VERYHIGH": "Very High",
    "VERY HIGH": "Very High",
    "VHIGH": "Very High",
}

NUMERIC_RE = re.compile(r"^[-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?$")


def _table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(
        text("SELECT to_regclass(:name) AS exists"),
        {"name": table_name},
    ).mappings().one()
    return row["exists"] is not None


def _ensure_required_tables(db: Session, *table_names: str) -> None:
    for table_name in table_names:
        if not _table_exists(db, table_name):
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Required table {table_name} is missing. "
                    "Run migrations and ingest FEMA NRI data."
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


def _parse_numeric(value: Any) -> float | None:
    token = str(value or "").strip()
    if not token:
        return None
    if token.lower() in MISSING_TOKENS:
        return None
    if not NUMERIC_RE.fullmatch(token):
        return None
    try:
        parsed = float(token)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def normalize_county_geoid(value: str | None) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"[^0-9]", "", str(value).strip())
    if not digits or len(digits) > 5:
        return None
    normalized = digits.zfill(5)
    if not re.fullmatch(r"\d{5}", normalized):
        return None
    return normalized


def normalize_tract_geoid(value: str | None) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"[^0-9]", "", str(value).strip())
    if not digits or len(digits) > 11:
        return None
    normalized = digits.zfill(11)
    if not re.fullmatch(r"\d{11}", normalized):
        return None
    return normalized


def _normalize_level(value: str | None, *, allow_auto: bool = True) -> str:
    normalized = str(value or ("auto" if allow_auto else "county")).strip().lower()
    allowed = {"county", "tract"}
    if allow_auto:
        allowed.add("auto")
    if normalized not in allowed:
        if allow_auto:
            raise HTTPException(status_code=400, detail="level must be auto, county, or tract")
        raise HTTPException(status_code=400, detail="level must be county or tract")
    return normalized


def choose_level(*, zoom: int, requested_level: str) -> str:
    normalized_zoom = max(0, int(zoom))
    normalized_requested_level = _normalize_level(requested_level, allow_auto=True)
    if normalized_requested_level != "auto":
        return normalized_requested_level
    if normalized_zoom >= FEMA_TRACT_ZOOM_THRESHOLD:
        return "tract"
    return "county"


def simplify_tolerance_degrees(zoom: int) -> float:
    normalized_zoom = max(0, int(zoom))
    if normalized_zoom <= 5:
        return 0.04
    if normalized_zoom == 6:
        return 0.03
    if normalized_zoom == 7:
        return 0.02
    if normalized_zoom == 8:
        return 0.012
    if normalized_zoom == 9:
        return 0.006
    if normalized_zoom == 10:
        return 0.003
    return 0.0015


def _guard_limit_for_performance(*, level: str, zoom: int, requested_limit: int) -> tuple[int, str | None]:
    normalized_level = str(level or "county").strip().lower()
    normalized_zoom = max(0, int(zoom))
    value = max(1, int(requested_limit))

    if normalized_level == "county":
        max_limit = 5000 if normalized_zoom <= 7 else 8000
    else:
        if normalized_zoom <= 10:
            max_limit = 7000
        elif normalized_zoom <= 12:
            max_limit = 12000
        else:
            max_limit = 18000

    if value > max_limit:
        return max_limit, "Result limited for performance; zoom in for more detail."
    return value, None


def _parse_bbox(bbox: str) -> dict[str, float]:
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


def _numeric_value_sql(alias: str = "t") -> str:
    return (
        "CASE "
        f"WHEN NULLIF(TRIM({alias}.raw ->> :raw_field), '') IS NULL THEN NULL "
        f"WHEN LOWER(TRIM({alias}.raw ->> :raw_field)) IN ('na', 'n/a', 'null', 'none') THEN NULL "
        f"WHEN TRIM({alias}.raw ->> :raw_field) IN ('-9999', '-8888') THEN NULL "
        f"WHEN ({alias}.raw ->> :raw_field) ~ '^[-+]?[0-9]*\\.?[0-9]+([eE][-+]?[0-9]+)?$' "
        f"THEN ({alias}.raw ->> :raw_field)::double precision "
        "ELSE NULL END"
    )


def _text_value_sql(alias: str = "t") -> str:
    return (
        "CASE "
        f"WHEN NULLIF(TRIM({alias}.raw ->> :raw_field), '') IS NULL THEN NULL "
        f"WHEN LOWER(TRIM({alias}.raw ->> :raw_field)) IN ('na', 'n/a', 'null', 'none') THEN NULL "
        f"WHEN TRIM({alias}.raw ->> :raw_field) IN ('-9999', '-8888') THEN NULL "
        f"ELSE TRIM({alias}.raw ->> :raw_field) END"
    )


def _normalize_rating(value: Any) -> str | None:
    token = str(value or "").strip()
    if not token:
        return None
    direct = RATING_NORMALIZATION.get(token.upper())
    if direct:
        return direct
    squashed = re.sub(r"\s+", " ", token).strip().upper()
    direct = RATING_NORMALIZATION.get(squashed)
    if direct:
        return direct
    if token.lower() in MISSING_TOKENS:
        return None
    return token.title()


def _rating_sort_key(label: str) -> tuple[int, str]:
    try:
        return (RATING_COLOR_ORDER.index(label), label)
    except ValueError:
        return (999, label)


def _measure_note(measure: dict[str, Any]) -> str | None:
    value_type = str(measure.get("value_type") or "").strip().lower()
    if value_type == "rating":
        return "Ratings are ordered from Very Low to Very High."
    if value_type in {"continuous", "percentile"}:
        return "Higher scores indicate relatively greater risk compared with other areas at the same level."
    if value_type == "dollars":
        return "Values represent expected annual loss in dollars."
    if value_type in {"count", "frequency"}:
        return "Values represent annualized frequency or number of events."
    return None


def _resolve_measure(measure_id: str, *, level: str | None = None) -> dict[str, Any]:
    cleaned = str(measure_id or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="measure is required")

    measure = catalog.find_measure(cleaned)
    if measure is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unknown FEMA NRI measure: {cleaned}. "
                "Use /api/fema/nri/measures to list supported measures."
            ),
        )

    if level:
        supported_levels = {
            str(item).strip().lower()
            for item in (measure.get("supported_levels") or [])
            if str(item).strip()
        }
        if supported_levels and level not in supported_levels:
            raise HTTPException(
                status_code=400,
                detail=f"Measure {measure.get('measure_id')} is not supported at {level} level.",
            )

    return measure


def _regroup_measures(measures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    for measure in measures:
        group_name = str(measure.get("group") or "Other").strip() or "Other"
        subgroup_name = str(measure.get("subgroup") or "General").strip() or "General"

        group_bucket = grouped.setdefault(group_name, {"group": group_name, "subgroups": {}})
        subgroup_bucket = group_bucket["subgroups"].setdefault(
            subgroup_name,
            {"subgroup": subgroup_name, "measures": []},
        )
        subgroup_bucket["measures"].append(measure)

    groups: list[dict[str, Any]] = []
    for group_name in sorted(grouped.keys(), key=str.lower):
        subgroup_map = grouped[group_name]["subgroups"]
        subgroups: list[dict[str, Any]] = []
        for subgroup_name in sorted(subgroup_map.keys(), key=str.lower):
            subgroups.append(subgroup_map[subgroup_name])
        groups.append({"group": group_name, "subgroups": subgroups})
    return groups


def list_measure_catalog(*, level: str = "all", include_hidden: bool = True) -> dict[str, Any]:
    payload = catalog.catalog_for_level(level)
    measures = payload.get("measures")
    if not isinstance(measures, list):
        measures = []

    if include_hidden:
        filtered = [item for item in measures if isinstance(item, dict)]
    else:
        filtered = [
            item for item in measures if isinstance(item, dict) and bool(item.get("visible_by_default"))
        ]

    sorted_measures = sorted(
        filtered,
        key=lambda item: (
            int(item.get("sort_order") or 1_000_000),
            str(item.get("display_label") or item.get("measure_id") or "").lower(),
        ),
    )

    return {
        **payload,
        "measure_count": len(sorted_measures),
        "groups": _regroup_measures(sorted_measures),
        "measures": sorted_measures,
    }


def fetch_map_geojson(
    db: Session,
    *,
    measure: str,
    bbox: str,
    zoom: int,
    level: str = "auto",
    limit: int = 5000,
) -> dict[str, Any]:
    _ensure_required_tables(db, COUNTY_TABLE, TRACT_TABLE)

    normalized_zoom = max(0, int(zoom))
    requested_level = _normalize_level(level, allow_auto=True)
    effective_level = choose_level(zoom=normalized_zoom, requested_level=requested_level)

    if limit < 1 or limit > 50000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 50000")

    measure_meta = _resolve_measure(measure, level=effective_level)
    parsed_bbox = _parse_bbox(bbox)
    simplify_degrees = simplify_tolerance_degrees(normalized_zoom)
    effective_limit, warning = _guard_limit_for_performance(
        level=effective_level,
        zoom=normalized_zoom,
        requested_limit=limit,
    )

    rating_field = str(measure_meta.get("companion_rating_field") or "").strip()
    rating_select_sql = "NULL::text AS rating_value"
    params: dict[str, Any] = {
        **parsed_bbox,
        "raw_field": str(measure_meta.get("raw_field") or measure_meta.get("measure_id")),
        "simplify_degrees": float(simplify_degrees),
        "limit": int(effective_limit),
    }
    if rating_field:
        rating_select_sql = "NULLIF(TRIM(t.raw ->> :rating_field), '') AS rating_value"
        params["rating_field"] = rating_field

    if effective_level == "county":
        rows = db.execute(
            text(
                f"""
                WITH bbox AS (
                    SELECT ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) AS geom
                )
                SELECT
                    t.county_geoid AS location_id,
                    CASE
                        WHEN COALESCE(t.state_abbr, t.state_fips) IS NULL THEN COALESCE(t.county_name, t.county_geoid)
                        ELSE COALESCE(t.county_name, t.county_geoid) || ', ' || COALESCE(t.state_abbr, t.state_fips)
                    END AS area_name,
                    {_numeric_value_sql('t')} AS value_numeric,
                    {_text_value_sql('t')} AS value_text,
                    {rating_select_sql},
                    t.state_fips,
                    t.county_fips,
                    t.state_abbr,
                    t.state_name,
                    t.county_name,
                    ST_AsGeoJSON(
                        ST_SimplifyPreserveTopology(t.geom, :simplify_degrees),
                        {MAP_GEOJSON_PRECISION}
                    )::json AS geometry
                FROM {COUNTY_TABLE} AS t
                CROSS JOIN bbox
                WHERE t.geom IS NOT NULL
                  AND t.geom && bbox.geom
                  AND ST_Intersects(t.geom, bbox.geom)
                ORDER BY t.county_geoid
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    else:
        rows = db.execute(
            text(
                f"""
                WITH bbox AS (
                    SELECT ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) AS geom
                )
                SELECT
                    t.tract_geoid AS location_id,
                    CASE
                        WHEN COALESCE(t.tract_name, t.tract_geoid) IS NULL THEN t.tract_geoid
                        WHEN COALESCE(t.county_name, t.state_abbr) IS NULL THEN COALESCE(t.tract_name, t.tract_geoid)
                        ELSE COALESCE(t.tract_name, t.tract_geoid) || ' • ' || COALESCE(t.county_name, t.county_geoid) || ', ' || COALESCE(t.state_abbr, t.state_fips)
                    END AS area_name,
                    {_numeric_value_sql('t')} AS value_numeric,
                    {_text_value_sql('t')} AS value_text,
                    {rating_select_sql},
                    t.state_fips,
                    t.county_fips,
                    t.county_geoid,
                    t.tract_geoid,
                    t.state_abbr,
                    t.state_name,
                    t.county_name,
                    t.tract_name,
                    ST_AsGeoJSON(
                        ST_SimplifyPreserveTopology(t.geom, :simplify_degrees),
                        {MAP_GEOJSON_PRECISION}
                    )::json AS geometry
                FROM {TRACT_TABLE} AS t
                CROSS JOIN bbox
                WHERE t.geom IS NOT NULL
                  AND t.geom && bbox.geom
                  AND ST_Intersects(t.geom, bbox.geom)
                ORDER BY t.tract_geoid
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()

    features = []
    for row in rows:
        numeric_value = _json_number(row.get("value_numeric"))
        value_text = row.get("value_text")
        if value_text is None and numeric_value is not None:
            value_text = str(numeric_value)
        rating_value = _normalize_rating(row.get("rating_value"))

        properties: dict[str, Any] = {
            "id": row.get("location_id"),
            "location_id": row.get("location_id"),
            "locationid": row.get("location_id"),
            "name": row.get("area_name"),
            "geo_level": effective_level,
            "level": effective_level,
            "measure_id": measure_meta.get("measure_id"),
            "measure": measure_meta.get("display_label") or measure_meta.get("measure_id"),
            "label": measure_meta.get("display_label") or measure_meta.get("measure_id"),
            "description": measure_meta.get("description"),
            "unit": measure_meta.get("unit"),
            "value": numeric_value,
            "data_value": numeric_value,
            "value_text": value_text,
            "rating": rating_value,
            "value_type": measure_meta.get("value_type"),
            "legend_mode": measure_meta.get("legend_mode"),
            "hazard_name": measure_meta.get("hazard_name"),
            "state_fips": row.get("state_fips"),
            "county_fips": row.get("county_fips"),
            "state_abbr": row.get("state_abbr"),
            "state_name": row.get("state_name"),
            "county_name": row.get("county_name"),
        }

        if effective_level == "county":
            properties["county_geoid"] = row.get("location_id")
        else:
            properties["county_geoid"] = row.get("county_geoid")
            properties["tract_geoid"] = row.get("tract_geoid")
            properties["tract_name"] = row.get("tract_name")

        features.append(
            {
                "type": "Feature",
                "geometry": row.get("geometry"),
                "properties": properties,
            }
        )

    response: dict[str, Any] = {
        "type": "FeatureCollection",
        "features": features,
        "dataset": "FEMA National Risk Index",
        "measure": measure_meta.get("measure_id"),
        "label": measure_meta.get("display_label") or measure_meta.get("measure_id"),
        "description": measure_meta.get("description"),
        "unit": measure_meta.get("unit"),
        "value_type": measure_meta.get("value_type"),
        "legend_mode": measure_meta.get("legend_mode"),
        "level": effective_level,
        "zoom": normalized_zoom,
        "meta": {
            "simplify_tolerance_degrees": simplify_degrees,
            "geojson_precision": MAP_GEOJSON_PRECISION,
            "note": _measure_note(measure_meta),
        },
    }

    if warning:
        response["meta"]["warning"] = warning

    return response


def fetch_legend(
    db: Session,
    *,
    measure: str,
    bbox: str | None,
    level: str = "auto",
) -> dict[str, Any]:
    _ensure_required_tables(db, COUNTY_TABLE, TRACT_TABLE)

    requested_level = _normalize_level(level, allow_auto=True)
    effective_level = "county" if requested_level == "auto" else requested_level

    measure_meta = _resolve_measure(measure, level=effective_level)
    table_name = COUNTY_TABLE if effective_level == "county" else TRACT_TABLE

    params: dict[str, Any] = {
        "raw_field": str(measure_meta.get("raw_field") or measure_meta.get("measure_id")),
    }

    bbox_clause = ""
    bbox_join = ""
    if bbox:
        parsed = _parse_bbox(bbox)
        params.update(parsed)
        bbox_join = "CROSS JOIN bbox"
        bbox_clause = "AND t.geom && bbox.geom AND ST_Intersects(t.geom, bbox.geom)"

    legend_mode = str(measure_meta.get("legend_mode") or "").strip().lower()
    value_type = str(measure_meta.get("value_type") or "").strip().lower()

    if legend_mode == "ordered_category" or value_type == "rating":
        bbox_cte = ""
        if bbox:
            bbox_cte = "WITH bbox AS (SELECT ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) AS geom)"

        rows = db.execute(
            text(
                f"""
                {bbox_cte}
                SELECT
                    COALESCE({_text_value_sql('t')}, '__NO_DATA__') AS bucket,
                    COUNT(*)::bigint AS n
                FROM {table_name} AS t
                {bbox_join}
                WHERE TRUE
                  {bbox_clause}
                GROUP BY COALESCE({_text_value_sql('t')}, '__NO_DATA__')
                """
            ),
            params,
        ).mappings().all()

        no_data_count = 0
        categories: list[dict[str, Any]] = []
        for row in rows:
            bucket = str(row.get("bucket") or "").strip()
            count = int(row.get("n") or 0)
            if bucket == "__NO_DATA__":
                no_data_count += count
                continue
            normalized = _normalize_rating(bucket) or bucket
            categories.append(
                {
                    "value": bucket,
                    "label": normalized,
                    "count": count,
                }
            )

        merged: dict[str, int] = {}
        for item in categories:
            key = str(item["label"])
            merged[key] = merged.get(key, 0) + int(item["count"])

        sorted_categories = [
            {
                "value": label,
                "label": label,
                "count": count,
            }
            for label, count in sorted(merged.items(), key=lambda pair: _rating_sort_key(pair[0]))
        ]

        total_count = no_data_count + sum(int(item["count"]) for item in sorted_categories)
        return {
            "measure": measure_meta.get("measure_id"),
            "label": measure_meta.get("display_label") or measure_meta.get("measure_id"),
            "description": measure_meta.get("description"),
            "unit": measure_meta.get("unit"),
            "value_type": measure_meta.get("value_type"),
            "legend_mode": measure_meta.get("legend_mode"),
            "level": effective_level,
            "categories": sorted_categories,
            "bins": [],
            "missing_count": no_data_count,
            "noDataCount": no_data_count,
            "n": total_count - no_data_count,
            "total_count": total_count,
            "note": (
                _measure_note(measure_meta)
                or "FEMA NRI is intended for planning and broad comparison, not local engineering-grade assessment."
            ),
        }

    quantile_fractions = [i / BINS_DEFAULT for i in range(1, BINS_DEFAULT)]
    params["quantiles"] = quantile_fractions

    bbox_cte = ""
    if bbox:
        bbox_cte = "bbox AS (SELECT ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) AS geom),"

    sql = text(
        f"""
        WITH
        {bbox_cte}
        values AS (
            SELECT {_numeric_value_sql('t')} AS value
            FROM {table_name} AS t
            {bbox_join}
            WHERE TRUE
              {bbox_clause}
        )
        SELECT
            COUNT(*) FILTER (WHERE value IS NOT NULL) AS n,
            COUNT(*) FILTER (WHERE value IS NULL) AS nulls,
            MIN(value) AS min,
            MAX(value) AS max,
            COALESCE(
                percentile_cont(:quantiles)
                WITHIN GROUP (ORDER BY value)
                FILTER (WHERE value IS NOT NULL),
                ARRAY[]::float8[]
            ) AS quantiles
        FROM values
        """
    ).bindparams(bindparam("quantiles", type_=ARRAY(Float)))

    row = db.execute(sql, params).mappings().one()

    n = int(row["n"] or 0)
    nulls = int(row["nulls"] or 0)
    min_value = _json_number(row["min"])
    max_value = _json_number(row["max"])

    bins_payload: list[dict[str, Any]] = []
    if n > 0 and min_value is not None and max_value is not None:
        raw_quantiles = [float(value) for value in (row["quantiles"] or []) if value is not None]
        points = [float(min_value), *raw_quantiles, float(max_value)]

        deduped_breaks = [points[0]]
        for value in points[1:]:
            if value > deduped_breaks[-1]:
                deduped_breaks.append(value)

        if len(deduped_breaks) == 1:
            deduped_breaks.append(deduped_breaks[0])

        bins_payload = [
            {
                "min": float(start),
                "max": float(end),
                "label": f"{float(start):.2f} - {float(end):.2f}",
            }
            for start, end in zip(deduped_breaks[:-1], deduped_breaks[1:], strict=False)
        ]

    return {
        "measure": measure_meta.get("measure_id"),
        "label": measure_meta.get("display_label") or measure_meta.get("measure_id"),
        "description": measure_meta.get("description"),
        "unit": measure_meta.get("unit"),
        "value_type": measure_meta.get("value_type"),
        "legend_mode": measure_meta.get("legend_mode"),
        "level": effective_level,
        "categories": [],
        "bins": bins_payload,
        "missing_count": nulls,
        "noDataCount": nulls,
        "n": n,
        "total_count": n + nulls,
        "note": (
            _measure_note(measure_meta)
            or "FEMA NRI is intended for planning and broad comparison, not local engineering-grade assessment."
        ),
    }


def fetch_detail(db: Session, *, level: str, geoid: str) -> dict[str, Any] | None:
    normalized_level = _normalize_level(level, allow_auto=False)
    table_name = COUNTY_TABLE if normalized_level == "county" else TRACT_TABLE
    _ensure_required_tables(db, table_name)

    if normalized_level == "county":
        normalized_geoid = normalize_county_geoid(geoid)
        if normalized_geoid is None:
            raise HTTPException(status_code=400, detail="geoid must be a valid 5-digit county GEOID")

        row = db.execute(
            text(
                f"""
                SELECT
                    county_geoid,
                    nri_id,
                    state_fips,
                    county_fips,
                    state_abbr,
                    state_name,
                    county_name,
                    raw
                FROM {COUNTY_TABLE}
                WHERE county_geoid = :geoid
                LIMIT 1
                """
            ),
            {"geoid": normalized_geoid},
        ).mappings().one_or_none()
    else:
        normalized_geoid = normalize_tract_geoid(geoid)
        if normalized_geoid is None:
            raise HTTPException(status_code=400, detail="geoid must be a valid 11-digit tract GEOID")

        row = db.execute(
            text(
                f"""
                SELECT
                    tract_geoid,
                    nri_id,
                    state_fips,
                    county_fips,
                    county_geoid,
                    tract_code,
                    state_abbr,
                    state_name,
                    county_name,
                    tract_name,
                    raw
                FROM {TRACT_TABLE}
                WHERE tract_geoid = :geoid
                LIMIT 1
                """
            ),
            {"geoid": normalized_geoid},
        ).mappings().one_or_none()

    if row is None:
        return None

    raw = row.get("raw")
    if not isinstance(raw, dict):
        raw = {}

    catalog_payload = catalog.catalog_for_level(normalized_level)
    measures = catalog_payload.get("measures")
    if not isinstance(measures, list):
        measures = []

    values: list[dict[str, Any]] = []
    for measure_meta in measures:
        if not isinstance(measure_meta, dict):
            continue
        raw_field = str(measure_meta.get("raw_field") or measure_meta.get("measure_id") or "").strip()
        if not raw_field:
            continue

        raw_value = raw.get(raw_field)
        numeric_value = _parse_numeric(raw_value)

        companion_field = str(measure_meta.get("companion_rating_field") or "").strip()
        rating_value = _normalize_rating(raw.get(companion_field)) if companion_field else None

        values.append(
            {
                "measure_id": measure_meta.get("measure_id"),
                "label": measure_meta.get("display_label") or measure_meta.get("measure_id"),
                "group": measure_meta.get("group"),
                "subgroup": measure_meta.get("subgroup"),
                "description": measure_meta.get("description"),
                "unit": measure_meta.get("unit"),
                "value_type": measure_meta.get("value_type"),
                "legend_mode": measure_meta.get("legend_mode"),
                "value": _json_number(numeric_value),
                "value_text": None if raw_value is None else str(raw_value),
                "rating": rating_value,
                "hazard_name": measure_meta.get("hazard_name"),
            }
        )

    base_payload: dict[str, Any] = {
        "level": normalized_level,
        "geoid": normalized_geoid,
        "dataset": "FEMA National Risk Index",
        "values": values,
    }

    if normalized_level == "county":
        base_payload.update(
            {
                "county_geoid": row.get("county_geoid"),
                "nri_id": row.get("nri_id"),
                "state_fips": row.get("state_fips"),
                "county_fips": row.get("county_fips"),
                "state_abbr": row.get("state_abbr"),
                "state_name": row.get("state_name"),
                "county_name": row.get("county_name"),
            }
        )
    else:
        base_payload.update(
            {
                "tract_geoid": row.get("tract_geoid"),
                "nri_id": row.get("nri_id"),
                "state_fips": row.get("state_fips"),
                "county_fips": row.get("county_fips"),
                "county_geoid": row.get("county_geoid"),
                "tract_code": row.get("tract_code"),
                "state_abbr": row.get("state_abbr"),
                "state_name": row.get("state_name"),
                "county_name": row.get("county_name"),
                "tract_name": row.get("tract_name"),
            }
        )

    return base_payload
