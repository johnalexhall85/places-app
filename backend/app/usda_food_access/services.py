from __future__ import annotations

import math
import re
from decimal import Decimal
from numbers import Real
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Float, bindparam, func, or_, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from app.db_fqtn import places_table, usda_food_access_table
from app.usda_food_access import models

DATASET_KEY = "food_access_atlas"
DATASET_NOTES = (
    "USDA Food Access Research Atlas (tract-level). "
    "Values indicate proximity-based food access and low-income designations."
)
TRACT_ZOOM_THRESHOLD = 10
HEAT_LIMIT_DEFAULT = 2000
HEAT_LIMIT_MAX = 5000
HEAT_GRID_COARSE_KM = 50
HEAT_GRID_MEDIUM_KM = 20

RECOMMENDED_FIELDS = [
    "LA1and10",
    "LowIncomeTracts",
    "PovertyRate",
    "MedianFamilyIncome",
    "LAhalfand10",
    "LA1and20",
    "LILATracts_1And10",
    "LILATracts_halfAnd10",
    "LILATracts_1And20",
    "LILATracts_Vehicle",
    "LAPOP1_10",
    "LAPOP05_10",
    "LAPOP1_20",
    "LALOWI1_10",
    "LALOWI05_10",
    "LALOWI1_20",
]

CURATED_FIELD_TO_COLUMN = {
    "LowIncomeTracts": "low_income_tracts",
    "PovertyRate": "poverty_rate",
    "MedianFamilyIncome": "median_family_income",
    "LA1and10": "la1and10",
    "LAhalfand10": "lahalfand10",
    "LA1and20": "la1and20",
    "LILATracts_1And10": "lilatracts_1and10",
    "LILATracts_halfAnd10": "lilatracts_halfand10",
    "LILATracts_1And20": "lilatracts_1and20",
    "LILATracts_Vehicle": "lilatracts_vehicle",
    "LAPOP1_10": "lapop1_10",
    "LAPOP05_10": "lapop05_10",
    "LAPOP1_20": "lapop1_20",
    "LALOWI1_10": "lalowi1_10",
    "LALOWI05_10": "lalowi05_10",
    "LALOWI1_20": "lalowi1_20",
}

CURATED_COLUMN_TO_FIELD = {column: field for field, column in CURATED_FIELD_TO_COLUMN.items()}
FLAG_LIKE_FIELDS = {
    "lowincometracts",
    "la1and10",
    "lahalfand10",
    "la1and20",
}
FLAG_LIKE_PREFIXES = ("lila",)
FLAG_LIKE_SUBSTRINGS = ("tracts",)

TRACT_ATLAS_TABLE = usda_food_access_table("tract_atlas")
TRACT_SHAPES_TABLE = places_table("tract_shapes")
VARIABLE_LOOKUP_TABLE = usda_food_access_table("variable_lookup")


def _ensure_required_tables(db: Session, *table_names: str) -> None:
    for table_name in table_names:
        row = db.execute(
            text("SELECT to_regclass(:name) AS exists"),
            {"name": table_name},
        ).mappings().one()
        if row["exists"] is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Required table {table_name} is missing. "
                    "Run migrations and ingest USDA Food Access data."
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


def normalize_geoid(value: str | None) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"[^0-9]", "", str(value).strip())
    if not digits or len(digits) > 11:
        return None
    normalized = digits.zfill(11)
    if not re.fullmatch(r"\d{11}", normalized):
        return None
    return normalized


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


def _normalize_mode(mode: str | None) -> str:
    normalized = str(mode or "auto").strip().lower()
    if normalized not in {"auto", "raw", "curated"}:
        raise HTTPException(status_code=400, detail="mode must be auto, raw, or curated")
    return normalized


def _recommended_rank(field: str) -> tuple[int, int]:
    lowered = str(field or "").strip().lower()
    for idx, recommended_field in enumerate(RECOMMENDED_FIELDS):
        if lowered == recommended_field.lower():
            return (0, idx)
    return (1, 9999)


def _resolve_variable_metadata(
    db: Session,
    variable: str,
    *,
    unknown_status_code: int = 404,
) -> dict[str, Any]:
    cleaned = str(variable or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="variable is required")

    row = db.execute(
        select(
            models.UsdaFoodAccessVariableLookup.field,
            models.UsdaFoodAccessVariableLookup.long_name,
            models.UsdaFoodAccessVariableLookup.description,
        ).where(func.lower(models.UsdaFoodAccessVariableLookup.field) == cleaned.lower())
    ).mappings().one_or_none()

    if row:
        return {
            "field": row["field"],
            "long_name": row["long_name"] or row["field"],
            "description": row["description"],
        }

    for curated_field in CURATED_FIELD_TO_COLUMN:
        if curated_field.lower() == cleaned.lower():
            return {
                "field": curated_field,
                "long_name": curated_field,
                "description": None,
            }

    raise HTTPException(
        status_code=unknown_status_code,
        detail=(
            f"Unknown USDA Food Access variable: {cleaned}. "
            "Use /api/usda/food-access/variables to list supported fields."
        ),
    )


def resolve_variable_label(db: Session, variable: str) -> str:
    variable_meta = _resolve_variable_metadata(db, variable, unknown_status_code=400)
    return str(variable_meta.get("long_name") or variable_meta["field"])


def resolve_variable_description(db: Session, variable: str) -> str | None:
    variable_meta = _resolve_variable_metadata(db, variable, unknown_status_code=400)
    description = variable_meta.get("description")
    if description is None:
        return None
    return str(description)


def _is_flag_like_field(variable_field: str) -> bool:
    lowered = str(variable_field or "").strip().lower()
    if not lowered:
        return False
    if lowered in FLAG_LIKE_FIELDS:
        return True
    if any(lowered.startswith(prefix) for prefix in FLAG_LIKE_PREFIXES):
        return True
    if any(token in lowered for token in FLAG_LIKE_SUBSTRINGS):
        return True
    return False


def _normalize_heat_agg(agg: str | None) -> str:
    normalized = str(agg or "auto").strip().lower()
    if normalized not in {"auto", "median", "mean", "pct_flagged"}:
        raise HTTPException(status_code=400, detail="agg must be auto, median, mean, or pct_flagged")
    return normalized


def _resolve_heat_aggregation(variable_field: str, agg: str | None) -> str:
    requested = _normalize_heat_agg(agg)
    if requested != "auto":
        return requested
    return "pct_flagged" if _is_flag_like_field(variable_field) else "median"


def _heat_cell_km_for_zoom(zoom: int) -> int:
    if zoom <= 6:
        return HEAT_GRID_COARSE_KM
    return HEAT_GRID_MEDIUM_KM


def _grid_step_degrees(*, cell_km: float, center_lat: float) -> tuple[float, float]:
    cell_deg_lat = max(0.01, float(cell_km) / 111.0)
    cos_lat = math.cos(math.radians(center_lat))
    safe_cos = max(0.2, abs(cos_lat))
    cell_deg_lon = max(0.01, cell_deg_lat / safe_cos)
    return (cell_deg_lat, cell_deg_lon)


def _value_expression_sql(*, variable_field: str, mode: str) -> tuple[str, dict[str, Any], str]:
    normalized_mode = _normalize_mode(mode)
    curated_column = CURATED_FIELD_TO_COLUMN.get(variable_field)

    if normalized_mode in {"auto", "curated"} and curated_column:
        return (f"a.{curated_column}", {}, "curated")

    if normalized_mode == "curated" and not curated_column:
        raise HTTPException(
            status_code=400,
            detail=(
                "Requested variable is not available as a curated typed column. "
                "Use mode=raw or mode=auto."
            ),
        )

    value_sql = (
        "CASE "
        "WHEN NULLIF(TRIM(a.raw ->> :raw_field), '') IS NULL THEN NULL "
        "WHEN (a.raw ->> :raw_field) ~ '^[-+]?[0-9]*\\.?[0-9]+([eE][-+]?[0-9]+)?$' "
        "THEN (a.raw ->> :raw_field)::double precision "
        "ELSE NULL END"
    )
    return (value_sql, {"raw_field": variable_field}, "raw")


def list_variables(
    db: Session,
    *,
    q: str | None = None,
    include_raw_only: bool = False,
) -> dict[str, Any]:
    _ensure_required_tables(db, VARIABLE_LOOKUP_TABLE)

    query = select(
        models.UsdaFoodAccessVariableLookup.field,
        models.UsdaFoodAccessVariableLookup.long_name,
        models.UsdaFoodAccessVariableLookup.description,
    )

    cleaned_q = str(q or "").strip()
    if cleaned_q:
        pattern = f"%{cleaned_q.lower()}%"
        query = query.where(
            or_(
                func.lower(models.UsdaFoodAccessVariableLookup.field).like(pattern),
                func.lower(func.coalesce(models.UsdaFoodAccessVariableLookup.long_name, "")).like(
                    pattern
                ),
                func.lower(
                    func.coalesce(models.UsdaFoodAccessVariableLookup.description, "")
                ).like(pattern),
            )
        )

    rows = db.execute(query).mappings().all()
    variables = [
        {
            "field": row["field"],
            "long_name": row["long_name"] or row["field"],
            "description": row["description"],
            "recommended": row["field"] in CURATED_FIELD_TO_COLUMN,
        }
        for row in rows
        if row["field"]
    ]

    if include_raw_only:
        variables.sort(
            key=lambda item: (
                str(item.get("long_name") or item.get("field") or "").lower(),
                str(item.get("field") or "").lower(),
            )
        )
    else:
        variables.sort(
            key=lambda item: (
                *_recommended_rank(str(item.get("field") or "")),
                str(item.get("long_name") or item.get("field") or "").lower(),
            )
        )

    recommended_fields = [
        field
        for field in RECOMMENDED_FIELDS
        if any(field.lower() == str(item.get("field") or "").lower() for item in variables)
    ]

    return {
        "variables": variables,
        "recommended_fields": recommended_fields,
        "notes": DATASET_NOTES,
    }


def fetch_tract_detail(db: Session, *, geoid: str) -> dict[str, Any] | None:
    _ensure_required_tables(db, TRACT_ATLAS_TABLE)

    normalized_geoid = normalize_geoid(geoid)
    if normalized_geoid is None:
        raise HTTPException(status_code=400, detail="geoid must be an 11-digit census tract code")

    row = db.execute(
        select(models.UsdaFoodAccessTractAtlas).where(
            models.UsdaFoodAccessTractAtlas.geoid == normalized_geoid
        )
    ).scalar_one_or_none()
    if row is None:
        return None

    payload = {
        "geoid": row.geoid,
        "state": row.state,
        "county": row.county,
        "urban": row.urban,
        "pop2010": row.pop2010,
    }
    for column, field in CURATED_COLUMN_TO_FIELD.items():
        payload[field] = _json_number(getattr(row, column))
    payload["raw"] = row.raw or {}
    return payload


def fetch_map_geojson(
    db: Session,
    *,
    variable: str,
    bbox: str,
    zoom: int,
    limit: int,
    mode: str = "auto",
) -> dict[str, Any]:
    _ensure_required_tables(db, TRACT_SHAPES_TABLE, TRACT_ATLAS_TABLE, VARIABLE_LOOKUP_TABLE)

    if int(zoom) < TRACT_ZOOM_THRESHOLD:
        return {
            "type": "FeatureCollection",
            "features": [],
            "message": "Zoom in to see tract-level food access.",
            "variable": str(variable or "").strip(),
        }

    if limit < 1 or limit > 50000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 50000")

    bbox_params = _parse_bbox(bbox)
    variable_meta = _resolve_variable_metadata(db, variable)
    value_sql, value_params, resolved_mode = _value_expression_sql(
        variable_field=variable_meta["field"],
        mode=mode,
    )

    params: dict[str, Any] = {
        **bbox_params,
        **value_params,
        "limit": int(limit),
    }

    rows = db.execute(
        text(
            f"""
            WITH bbox AS (
                SELECT ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) AS geom
            )
            SELECT
                s.geoid11 AS geoid,
                a.state,
                a.county,
                a.pop2010,
                {value_sql} AS value,
                ST_AsGeoJSON(s.geom)::json AS geometry
            FROM {TRACT_SHAPES_TABLE} AS s
            JOIN {TRACT_ATLAS_TABLE} AS a
              ON a.geoid = s.geoid11
            CROSS JOIN bbox
            WHERE s.geom IS NOT NULL
              AND s.geom && bbox.geom
              AND ST_Intersects(s.geom, bbox.geom)
            ORDER BY s.geoid11
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()

    label = variable_meta.get("long_name") or variable_meta["field"]
    features = [
        {
            "type": "Feature",
            "geometry": row["geometry"],
            "properties": {
                "geoid": row["geoid"],
                "locationid": row["geoid"],
                "location_id": row["geoid"],
                "value": _json_number(row["value"]),
                "data_value": _json_number(row["value"]),
                "label": label,
                "variable": variable_meta["field"],
                "state": row["state"],
                "county": row["county"],
                "pop2010": row["pop2010"],
                "geo_level": "tract",
            },
        }
        for row in rows
    ]

    return {
        "type": "FeatureCollection",
        "features": features,
        "variable": variable_meta["field"],
        "label": label,
        "description": variable_meta.get("description"),
        "mode": resolved_mode,
    }


def fetch_heat_points(
    db: Session,
    *,
    variable: str,
    bbox: str,
    zoom: int,
    limit: int = HEAT_LIMIT_DEFAULT,
    agg: str = "auto",
    mode: str = "auto",
) -> dict[str, Any]:
    _ = _normalize_mode(mode)
    normalized_zoom = max(0, int(zoom))
    requested_variable = str(variable or "").strip()
    if not requested_variable:
        raise HTTPException(status_code=400, detail="variable is required")

    if normalized_zoom >= TRACT_ZOOM_THRESHOLD:
        return {
            "mode": "heat",
            "variable": requested_variable,
            "variable_label": requested_variable,
            "variable_description": None,
            "agg": "auto",
            "cell_km": None,
            "points": [],
            "notes": "Heat disabled at tract zoom; use /map",
        }

    if limit < 1 or limit > HEAT_LIMIT_MAX:
        raise HTTPException(status_code=400, detail=f"limit must be between 1 and {HEAT_LIMIT_MAX}")

    _ensure_required_tables(db, TRACT_SHAPES_TABLE, TRACT_ATLAS_TABLE, VARIABLE_LOOKUP_TABLE)
    bbox_params = _parse_bbox(bbox)
    variable_meta = _resolve_variable_metadata(
        db,
        requested_variable,
        unknown_status_code=400,
    )
    variable_field = variable_meta["field"]
    variable_label = variable_meta.get("long_name") or variable_field
    variable_description = variable_meta.get("description")
    resolved_agg = _resolve_heat_aggregation(variable_field, agg)

    center_lat = (bbox_params["miny"] + bbox_params["maxy"]) / 2.0
    cell_km = _heat_cell_km_for_zoom(normalized_zoom)
    cell_deg_lat, cell_deg_lon = _grid_step_degrees(cell_km=cell_km, center_lat=center_lat)
    notes_parts = ["This view shows aggregated tract values in grid cells. Zoom in for tract-level detail."]

    value_sql, value_params, _resolved_mode = _value_expression_sql(
        variable_field=variable_field,
        mode="auto",
    )
    if resolved_agg == "pct_flagged":
        agg_sql = "100.0 * AVG(CASE WHEN bv.value = 1 OR bv.value > 0 THEN 1.0 ELSE 0.0 END)"
    elif resolved_agg == "mean":
        agg_sql = "AVG(bv.value)"
    else:
        agg_sql = "percentile_cont(0.5) WITHIN GROUP (ORDER BY bv.value)"

    params: dict[str, Any] = {
        **bbox_params,
        **value_params,
        "cell_deg_lat": cell_deg_lat,
        "cell_deg_lon": cell_deg_lon,
        "limit": int(limit),
    }

    rows = db.execute(
        text(
            f"""
            WITH bbox AS (
                SELECT ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) AS geom
            ),
            tract_values AS (
                SELECT
                    ST_X(ST_PointOnSurface(s.geom)) AS lon,
                    ST_Y(ST_PointOnSurface(s.geom)) AS lat,
                    {value_sql} AS value
                FROM {TRACT_SHAPES_TABLE} AS s
                JOIN {TRACT_ATLAS_TABLE} AS a
                  ON a.geoid = s.geoid11
                CROSS JOIN bbox
                WHERE s.geom IS NOT NULL
                  AND s.geom && bbox.geom
                  AND ST_Intersects(s.geom, bbox.geom)
            ),
            binned_values AS (
                SELECT
                    FLOOR((tv.lon - :minx) / :cell_deg_lon)::int AS cell_x,
                    FLOOR((tv.lat - :miny) / :cell_deg_lat)::int AS cell_y,
                    tv.value AS value
                FROM tract_values AS tv
                WHERE tv.value IS NOT NULL
            )
            SELECT
                (:miny + (bv.cell_y + 0.5) * :cell_deg_lat) AS lat,
                (:minx + (bv.cell_x + 0.5) * :cell_deg_lon) AS lon,
                {agg_sql} AS value,
                COUNT(*)::int AS n
            FROM binned_values AS bv
            GROUP BY bv.cell_x, bv.cell_y
            HAVING COUNT(*) > 0
            ORDER BY n DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()

    points = [
        {
            "cell_id": index + 1,
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "value": _json_number(row["value"]),
            "n": int(row["n"] or 0),
        }
        for index, row in enumerate(rows)
        if row["lat"] is not None and row["lon"] is not None
    ]

    return {
        "mode": "heat",
        "variable": variable_field,
        "variable_label": variable_label,
        "variable_description": variable_description,
        "agg": resolved_agg,
        "cell_km": cell_km,
        "points": points,
        "notes": " ".join(notes_parts),
    }


def fetch_legend(
    db: Session,
    *,
    variable: str,
    bins: int,
    bbox: str | None,
    mode: str,
) -> dict[str, Any]:
    _ensure_required_tables(db, TRACT_SHAPES_TABLE, TRACT_ATLAS_TABLE, VARIABLE_LOOKUP_TABLE)

    if bins < 2 or bins > 9:
        raise HTTPException(status_code=400, detail="bins must be between 2 and 9")

    variable_meta = _resolve_variable_metadata(db, variable)
    value_sql, value_params, resolved_mode = _value_expression_sql(
        variable_field=variable_meta["field"],
        mode=mode,
    )

    quantile_fractions = [i / bins for i in range(1, bins)]
    params: dict[str, Any] = {**value_params, "quantiles": quantile_fractions}

    bbox_cte = ""
    bbox_join = ""
    bbox_filter = ""
    if bbox:
        params.update(_parse_bbox(bbox))
        bbox_cte = "bbox AS (SELECT ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) AS geom),"
        bbox_join = "CROSS JOIN bbox"
        bbox_filter = (
            "AND s.geom && bbox.geom "
            "AND ST_Intersects(s.geom, bbox.geom)"
        )

    sql = text(
        f"""
        WITH
        {bbox_cte}
        values AS (
            SELECT {value_sql} AS value
            FROM {TRACT_SHAPES_TABLE} AS s
            JOIN {TRACT_ATLAS_TABLE} AS a
              ON a.geoid = s.geoid11
            {bbox_join}
            WHERE s.geom IS NOT NULL
            {bbox_filter}
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
    no_data_count = int(row["nulls"] or 0)
    min_value = _json_number(row["min"])
    max_value = _json_number(row["max"])

    bins_payload: list[dict[str, Any]] = []
    breaks: list[float] = []

    if n > 0 and min_value is not None and max_value is not None:
        raw_quantiles = [float(value) for value in (row["quantiles"] or []) if value is not None]
        points = [float(min_value), *raw_quantiles, float(max_value)]

        deduped_breaks = [points[0]]
        for value in points[1:]:
            if value > deduped_breaks[-1]:
                deduped_breaks.append(value)

        if len(deduped_breaks) == 1:
            deduped_breaks.append(deduped_breaks[0])

        breaks = deduped_breaks
        bins_payload = [
            {
                "min": float(start),
                "max": float(end),
                "label": f"{float(start):.2f} - {float(end):.2f}",
                "colorIndex": index,
            }
            for index, (start, end) in enumerate(zip(breaks[:-1], breaks[1:], strict=False))
        ]

    return {
        "variable": variable_meta["field"],
        "label": variable_meta.get("long_name") or variable_meta["field"],
        "description": variable_meta.get("description"),
        "legend_text": variable_meta.get("description") or "USDA Food Access indicator",
        "mode": resolved_mode,
        "bins": bins_payload,
        "n": n,
        "noDataCount": no_data_count,
        "min": float(min_value) if isinstance(min_value, (int, float)) else None,
        "max": float(max_value) if isinstance(max_value, (int, float)) else None,
        "breaks": breaks,
    }
