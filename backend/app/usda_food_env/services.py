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

from app.db_fqtn import places_table, usda_food_env_table
from app.usda_food_env import models

DATASET_KEY = "food_environment_atlas_2025"
DATASET_NOTES = (
    "USDA Food Environment Atlas (July 2025). "
    "Missing/suppressed values are handled as null when Value is N/A, blank, -9999, or -8888."
)
BINS_DEFAULT = 5

MISSING_TOKENS = {"", "na", "n/a", "-9999", "-8888"}

COUNTY_VALUES_TABLE = usda_food_env_table("county_values")
STATE_VALUES_TABLE = usda_food_env_table("state_values")
VARIABLE_LOOKUP_TABLE = usda_food_env_table("variable_lookup")
COUNTY_BOUNDARY_TABLE = places_table("dim_county_boundary")
STATE_BOUNDARY_TABLE = places_table("dim_state_boundary")
COUNTY_DIM_TABLE = places_table("dim_county")

COUNTY_DEFAULT_CANDIDATES = [
    "PCT_LACCESS_POP19",
    "PCT_LACCESS_POP20",
    "PCT_LACCESS_POP22",
    "PCT_LACCESS_POP23",
    "PCT_LACCESS_POP24",
    "PCT_LACCESS_POP15",
    "LACCESS_POP19",
    "LACCESS_POP15",
]
STATE_DEFAULT_CANDIDATES = [
    "FOODINSEC_21_23",
    "PCT_SNAP22",
    "PCT_OBESE_ADULTS22",
]

CONUS_MIN_LON = -125.0
CONUS_MIN_LAT = 24.0
CONUS_MAX_LON = -66.0
CONUS_MAX_LAT = 50.0

DEFAULT_VARIABLE_LEVEL = "county"
CURRENT_DATASET_YEAR = 2025
MAP_GEOJSON_PRECISION = 6

RECOMMENDED_PREFIXES = (
    "PCT_LACCESS_POP",
    "PCT_LACCESS_LOWI",
    "GROCPTH",
    "SUPERCPTH",
    "CONVSPTH",
    "SNAPSPTH",
    "WICSPTH",
    "FOODINSEC",
    "FMRKTPTH",
)


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
                detail=f"Required table {table_name} is missing. Run migrations and ingest USDA Food Environment data.",
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


def normalize_state_fips(value: str | None) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"[^0-9]", "", str(value).strip())
    if not digits or len(digits) > 2:
        return None
    normalized = digits.zfill(2)
    if not re.fullmatch(r"\d{2}", normalized):
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


def _clamp_bbox_to_conus(bbox: dict[str, float]) -> dict[str, float] | None:
    minx = max(float(bbox["minx"]), CONUS_MIN_LON)
    miny = max(float(bbox["miny"]), CONUS_MIN_LAT)
    maxx = min(float(bbox["maxx"]), CONUS_MAX_LON)
    maxy = min(float(bbox["maxy"]), CONUS_MAX_LAT)

    if minx >= maxx or miny >= maxy:
        return None

    return {
        "minx": minx,
        "miny": miny,
        "maxx": maxx,
        "maxy": maxy,
    }


def _normalize_level(value: str | None, *, allow_auto: bool = True) -> str:
    normalized = str(value or ("auto" if allow_auto else "all")).strip().lower()
    allowed = {"county", "state", "all"}
    if allow_auto:
        allowed.add("auto")
    if normalized not in allowed:
        if allow_auto:
            raise HTTPException(status_code=400, detail="level must be auto, county, state, or all")
        raise HTTPException(status_code=400, detail="level must be county, state, or all")
    return normalized


def choose_level(*, variable_level: str, zoom: int, requested_level: str) -> str:
    normalized_variable_level = str(variable_level or "county").strip().lower()
    normalized_requested_level = _normalize_level(requested_level, allow_auto=True)
    normalized_zoom = max(0, int(zoom))

    if normalized_requested_level != "auto":
        return normalized_requested_level
    if normalized_zoom <= 5:
        return "state"
    return "state" if normalized_variable_level == "state" else "county"


def simplify_tolerance_degrees(zoom: int) -> float:
    normalized_zoom = max(0, int(zoom))
    if normalized_zoom <= 5:
        return 0.04
    if normalized_zoom == 6:
        return 0.03
    if normalized_zoom == 7:
        return 0.02
    if normalized_zoom == 8:
        return 0.015
    if normalized_zoom == 9:
        return 0.01
    return 0.005


def _guard_limit_for_performance(*, level: str, zoom: int, requested_limit: int) -> tuple[int, str | None]:
    normalized_level = str(level or "county").strip().lower()
    normalized_zoom = max(0, int(zoom))
    limit_value = max(1, int(requested_limit))
    warning: str | None = None

    if normalized_level == "state" and normalized_zoom <= 5:
        max_limit = 60
    elif normalized_level == "county":
        if normalized_zoom <= 5:
            max_limit = 1000
        elif normalized_zoom == 6:
            max_limit = 5000
        elif normalized_zoom == 7:
            max_limit = 2000
        else:
            max_limit = 5000
    else:
        max_limit = 5000

    if limit_value > max_limit:
        limit_value = max_limit
        warning = "Result limited for performance; zoom in for more detail."

    return limit_value, warning


def _value_sql(alias: str = "v") -> str:
    return (
        "CASE "
        f"WHEN NULLIF(TRIM({alias}.raw ->> :raw_field), '') IS NULL THEN NULL "
        f"WHEN LOWER(TRIM({alias}.raw ->> :raw_field)) IN ('na', 'n/a') THEN NULL "
        f"WHEN TRIM({alias}.raw ->> :raw_field) IN ('-9999', '-8888') THEN NULL "
        f"WHEN ({alias}.raw ->> :raw_field) ~ '^[-+]?[0-9]*\\.?[0-9]+([eE][-+]?[0-9]+)?$' "
        f"THEN ({alias}.raw ->> :raw_field)::double precision "
        "ELSE NULL END"
    )


def _resolve_variable_metadata(db: Session, variable: str) -> dict[str, Any]:
    cleaned = str(variable or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="variable is required")

    row = db.execute(
        select(
            models.UsdaFoodEnvVariableLookup.var_name,
            models.UsdaFoodEnvVariableLookup.display_name,
            models.UsdaFoodEnvVariableLookup.description,
            models.UsdaFoodEnvVariableLookup.category,
            models.UsdaFoodEnvVariableLookup.unit,
            models.UsdaFoodEnvVariableLookup.level,
        ).where(func.lower(models.UsdaFoodEnvVariableLookup.var_name) == cleaned.lower())
    ).mappings().one_or_none()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unknown USDA Food Environment variable: {cleaned}. "
                "Use /api/usda/food-environment/variables to list supported variables."
            ),
        )

    return {
        "var_name": row["var_name"],
        "display_name": row["display_name"] or row["var_name"],
        "description": row["description"],
        "category": row["category"],
        "unit": row["unit"],
        "level": row["level"],
    }


def _resolve_effective_level(
    *,
    variable_level: str,
    requested_level: str,
) -> str:
    if requested_level == "auto":
        return variable_level
    return requested_level


def _pick_default_var(variables: list[dict[str, Any]], *, level: str, candidates: list[str]) -> str | None:
    by_name = {
        str(item.get("var_name") or "").strip().upper(): str(item.get("var_name") or "").strip()
        for item in variables
        if str(item.get("level") or "").strip().lower() == level
    }

    for candidate in candidates:
        found = by_name.get(candidate.upper())
        if found:
            return found

    for item in variables:
        if str(item.get("level") or "").strip().lower() == level:
            value = str(item.get("var_name") or "").strip()
            if value:
                return value
    return None


def _coerce_two_digit_year(value: str | int | None) -> int | None:
    if value is None:
        return None
    token = str(value).strip()
    if not re.fullmatch(r"\d{2}", token):
        return None
    year_int = int(token)
    return (2000 + year_int) if year_int <= 30 else (1900 + year_int)


def _extract_years_from_text(value: str | None) -> list[int]:
    text_value = str(value or "").strip()
    if not text_value:
        return []
    matches = re.findall(r"\b(19\d{2}|20\d{2})\b", text_value)
    return [int(match) for match in matches]


def _derive_year(*, var_name: str, display_name: str | None, description: str | None, year_end: Any) -> int | None:
    if year_end is not None:
        try:
            return int(year_end)
        except (TypeError, ValueError):
            pass

    for candidate in (display_name, description):
        years = _extract_years_from_text(candidate)
        if years:
            return max(years)

    upper_var = str(var_name or "").strip().upper()
    if not upper_var:
        return None

    range_4 = re.search(r"_(19\d{2})_(19\d{2}|20\d{2})$", upper_var)
    if range_4:
        return max(int(range_4.group(1)), int(range_4.group(2)))

    range_2 = re.search(r"_(\d{2})_(\d{2})$", upper_var)
    if range_2:
        years = [_coerce_two_digit_year(range_2.group(1)), _coerce_two_digit_year(range_2.group(2))]
        numeric = [year for year in years if year is not None]
        if numeric:
            return max(numeric)

    suffix_4 = re.search(r"(19\d{2}|20\d{2})$", upper_var)
    if suffix_4:
        return int(suffix_4.group(1))

    suffix_2 = re.search(r"(\d{2})$", upper_var)
    if suffix_2:
        return _coerce_two_digit_year(suffix_2.group(1))

    return None


def _canonical_series_key(*, var_name: str, year: int | None) -> str:
    upper_var = str(var_name or "").strip().upper()
    if not upper_var or year is None:
        return upper_var

    base = upper_var
    changed = True
    while changed:
        changed = False
        next_base = re.sub(r"(?:[_-])?(19\d{2}|20\d{2})$", "", base)
        if next_base != base:
            base = next_base.rstrip("_-")
            changed = True
            continue
        next_base = re.sub(r"(?:[_-])?(\d{2})$", "", base)
        if next_base != base:
            base = next_base.rstrip("_-")
            changed = True

    return base or upper_var


def _parse_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    token = str(value).strip().lower()
    if not token:
        return None
    if token in {"1", "true", "yes", "y"}:
        return True
    if token in {"0", "false", "no", "n"}:
        return False
    return None


def _explicit_archival_flag(raw: Any) -> bool | None:
    if not isinstance(raw, dict):
        return None
    for key, value in raw.items():
        key_token = re.sub(r"[^a-z0-9]+", "", str(key or "").strip().lower())
        if not key_token:
            continue
        if "archiv" in key_token:
            parsed = _parse_optional_bool(value)
            if parsed is not None:
                return parsed
        if key_token in {"deprecated", "isdeprecated"}:
            parsed = _parse_optional_bool(value)
            if parsed is not None:
                return parsed
    return None


def _is_recommended(var_name: str) -> bool:
    upper_name = str(var_name or "").strip().upper()
    if not upper_name:
        return False
    return any(upper_name.startswith(prefix) for prefix in RECOMMENDED_PREFIXES)


def _enrich_variable_row(row: dict[str, Any]) -> dict[str, Any]:
    var_name = str(row.get("var_name") or "").strip()
    display_name = str(row.get("display_name") or var_name).strip() or var_name
    description = row.get("description")
    category = str(row.get("category") or "Other").strip() or "Other"
    level = str(row.get("level") or "county").strip().lower()
    level = "state" if level == "state" else "county"

    year_value = _derive_year(
        var_name=var_name,
        display_name=display_name,
        description=str(description or "").strip() or None,
        year_end=row.get("year_end"),
    )
    series_key = _canonical_series_key(var_name=var_name, year=year_value)
    recommended = _is_recommended(var_name)

    return {
        "var_name": var_name,
        "display_name": display_name,
        "description": description,
        "category": category,
        "unit": row.get("unit"),
        "level": level,
        "sort_order": row.get("sort_order"),
        "raw": row.get("raw") if isinstance(row.get("raw"), dict) else {},
        "year": year_value,
        "series_key": series_key,
        "recommended": recommended,
    }


def _sort_variables(variables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        variables,
        key=lambda item: (
            1_000_000 if item.get("sort_order") is None else int(item["sort_order"]),
            str(item.get("category") or "~").lower(),
            str(item.get("display_name") or item.get("var_name") or "").lower(),
        ),
    )


def list_variables(
    db: Session,
    *,
    q: str | None = None,
    level: str = DEFAULT_VARIABLE_LEVEL,
    include_archival: bool = False,
    year: int | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    _ensure_required_tables(db, VARIABLE_LOOKUP_TABLE)

    normalized_level = _normalize_level(level, allow_auto=False)
    normalized_year: int | None = None
    if year is not None:
        try:
            normalized_year = int(year)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="year must be an integer") from exc

    query = select(
        models.UsdaFoodEnvVariableLookup.var_name,
        models.UsdaFoodEnvVariableLookup.display_name,
        models.UsdaFoodEnvVariableLookup.description,
        models.UsdaFoodEnvVariableLookup.category,
        models.UsdaFoodEnvVariableLookup.unit,
        models.UsdaFoodEnvVariableLookup.level,
        models.UsdaFoodEnvVariableLookup.year_end,
        models.UsdaFoodEnvVariableLookup.sort_order,
        models.UsdaFoodEnvVariableLookup.raw,
    )

    if normalized_level != "all":
        query = query.where(models.UsdaFoodEnvVariableLookup.level == normalized_level)

    cleaned_category = str(category or "").strip()

    cleaned_q = str(q or "").strip()
    if cleaned_q:
        pattern = f"%{cleaned_q.lower()}%"
        query = query.where(
            or_(
                func.lower(models.UsdaFoodEnvVariableLookup.var_name).like(pattern),
                func.lower(func.coalesce(models.UsdaFoodEnvVariableLookup.display_name, "")).like(pattern),
                func.lower(func.coalesce(models.UsdaFoodEnvVariableLookup.description, "")).like(pattern),
                func.lower(func.coalesce(models.UsdaFoodEnvVariableLookup.category, "")).like(pattern),
            )
        )

    rows = db.execute(query).mappings().all()
    enriched_variables = [_enrich_variable_row(dict(row)) for row in rows if row.get("var_name")]
    enriched_variables = _sort_variables(enriched_variables)

    latest_year_by_series: dict[tuple[str, str], int] = {}
    for item in enriched_variables:
        item_year = item.get("year")
        if item_year is None:
            continue
        key = (
            str(item.get("level") or "county").strip().lower(),
            str(item.get("series_key") or item.get("var_name") or "").upper(),
        )
        existing = latest_year_by_series.get(key)
        if existing is None or int(item_year) > existing:
            latest_year_by_series[key] = int(item_year)

    filtered_variables: list[dict[str, Any]] = []
    for item in enriched_variables:
        item_level = str(item.get("level") or "county").strip().lower()
        if normalized_level != "all" and item_level != normalized_level:
            continue

        key = (
            item_level,
            str(item.get("series_key") or item.get("var_name") or "").upper(),
        )
        year_value = item.get("year")
        latest_year = latest_year_by_series.get(key)
        explicit_archival = _explicit_archival_flag(item.get("raw"))

        if explicit_archival is None:
            inferred_archival = bool(
                year_value is not None
                and latest_year is not None
                and int(year_value) < int(latest_year)
            )
        else:
            inferred_archival = explicit_archival

        is_default = bool(
            year_value is None
            or latest_year is None
            or int(year_value) >= int(latest_year)
        )

        if not include_archival and inferred_archival:
            continue
        if normalized_year is not None and year_value != normalized_year:
            continue
        if cleaned_category:
            item_category = str(item.get("category") or "Other").strip() or "Other"
            if item_category.lower() != cleaned_category.lower():
                continue

        filtered_variables.append(
            {
                "var_name": item["var_name"],
                "display_name": item["display_name"],
                "description": item.get("description"),
                "category": item.get("category") or "Other",
                "unit": item.get("unit"),
                "level": item_level,
                "year": year_value,
                "is_archival": inferred_archival,
                "is_default": is_default,
                "recommended": bool(item.get("recommended")),
                "sort_order": item.get("sort_order"),
            }
        )

    filtered_variables = _sort_variables(filtered_variables)
    categories = sorted(
        {str(item.get("category") or "Other").strip() or "Other" for item in filtered_variables},
        key=lambda value: value.lower(),
    )
    recommended_var_names = [
        str(item["var_name"])
        for item in filtered_variables
        if bool(item.get("recommended"))
    ][:20]

    defaults = {
        "county": _pick_default_var(filtered_variables, level="county", candidates=COUNTY_DEFAULT_CANDIDATES),
        "state": _pick_default_var(filtered_variables, level="state", candidates=STATE_DEFAULT_CANDIDATES),
    }

    if defaults["county"] is None:
        defaults["county"] = _pick_default_var(enriched_variables, level="county", candidates=COUNTY_DEFAULT_CANDIDATES)
    if defaults["state"] is None:
        defaults["state"] = _pick_default_var(enriched_variables, level="state", candidates=STATE_DEFAULT_CANDIDATES)

    return {
        "variables": filtered_variables,
        "recommended": recommended_var_names,
        "categories": categories,
        "defaults": defaults,
        "recommended_defaults": defaults,
        "notes": DATASET_NOTES,
        "dataset_year": CURRENT_DATASET_YEAR,
    }


def fetch_county_detail(db: Session, *, geoid: str) -> dict[str, Any] | None:
    _ensure_required_tables(db, COUNTY_VALUES_TABLE)

    normalized_geoid = normalize_county_geoid(geoid)
    if normalized_geoid is None:
        raise HTTPException(status_code=400, detail="geoid must be a valid 5-digit county FIPS")

    row = db.execute(
        select(models.UsdaFoodEnvCountyValues).where(models.UsdaFoodEnvCountyValues.geoid == normalized_geoid)
    ).scalar_one_or_none()
    if row is None:
        return None

    return {
        "geoid": row.geoid,
        "state_fips": row.state_fips,
        "county_fips": row.county_fips,
        "state_abbr": row.state_abbr,
        "state_name": row.state_name,
        "county_name": row.county_name,
        "raw": row.raw or {},
    }


def fetch_state_detail(db: Session, *, state_fips: str) -> dict[str, Any] | None:
    _ensure_required_tables(db, STATE_VALUES_TABLE)

    normalized_fips = normalize_state_fips(state_fips)
    if normalized_fips is None:
        raise HTTPException(status_code=400, detail="state_fips must be a valid 2-digit FIPS code")

    row = db.execute(
        select(models.UsdaFoodEnvStateValues).where(models.UsdaFoodEnvStateValues.state_fips == normalized_fips)
    ).scalar_one_or_none()
    if row is None:
        return None

    return {
        "state_fips": row.state_fips,
        "state_abbr": row.state_abbr,
        "state_name": row.state_name,
        "raw": row.raw or {},
    }


def fetch_map_geojson(
    db: Session,
    *,
    variable: str,
    bbox: str,
    zoom: int,
    level: str = "auto",
    limit: int = 5000,
) -> dict[str, Any]:
    _ensure_required_tables(db, COUNTY_VALUES_TABLE, STATE_VALUES_TABLE, VARIABLE_LOOKUP_TABLE, COUNTY_BOUNDARY_TABLE)

    if limit < 1 or limit > 50000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 50000")

    normalized_zoom = max(0, int(zoom))
    variable_meta = _resolve_variable_metadata(db, variable)
    requested_level = _normalize_level(level, allow_auto=True)
    variable_level = str(variable_meta.get("level") or "county").strip().lower()
    effective_level = choose_level(
        variable_level=variable_level,
        zoom=normalized_zoom,
        requested_level=requested_level,
    )
    parsed_bbox = _parse_bbox(bbox)
    clamped_bbox = _clamp_bbox_to_conus(parsed_bbox)

    label = variable_meta.get("display_name") or variable_meta["var_name"]
    unit = variable_meta.get("unit")
    simplify_degrees = simplify_tolerance_degrees(normalized_zoom)
    geojson_precision = MAP_GEOJSON_PRECISION
    effective_limit, warning = _guard_limit_for_performance(
        level=effective_level,
        zoom=normalized_zoom,
        requested_limit=limit,
    )

    if clamped_bbox is None:
        response: dict[str, Any] = {
            "type": "FeatureCollection",
            "features": [],
            "variable": variable_meta["var_name"],
            "label": label,
            "description": variable_meta.get("description"),
            "unit": unit,
            "level": effective_level,
            "zoom": normalized_zoom,
            "meta": {
                "simplify_tolerance_degrees": simplify_degrees,
                "geojson_precision": geojson_precision,
            },
        }
        if warning:
            response["meta"]["warning"] = warning
        return response

    params: dict[str, Any] = {
        **clamped_bbox,
        "raw_field": variable_meta["var_name"],
        "simplify_degrees": float(simplify_degrees),
        "limit": int(effective_limit),
    }
    state_boundaries_available = _table_exists(db, STATE_BOUNDARY_TABLE)

    if effective_level == "county":
        rows = db.execute(
            text(
                f"""
                WITH bbox AS (
                    SELECT ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) AS geom
                )
                SELECT
                    b.geoid AS id,
                    CASE
                        WHEN COALESCE(c.state_abbr, cv.state_abbr, b.statefp) IS NULL
                            THEN COALESCE(c.county_name, b.name)
                        ELSE COALESCE(c.county_name, b.name) || ', ' || COALESCE(c.state_abbr, cv.state_abbr, b.statefp)
                    END AS name,
                    {_value_sql('cv')} AS value,
                    ST_AsGeoJSON(
                        ST_SimplifyPreserveTopology(
                            b.geom,
                            :simplify_degrees
                        ),
                        {MAP_GEOJSON_PRECISION}
                    )::json AS geometry
                FROM {COUNTY_BOUNDARY_TABLE} AS b
                JOIN {COUNTY_VALUES_TABLE} AS cv
                  ON cv.geoid = b.geoid
                LEFT JOIN {COUNTY_DIM_TABLE} AS c
                  ON c.location_id = b.geoid
                CROSS JOIN bbox
                WHERE b.geom IS NOT NULL
                  AND b.geom && bbox.geom
                  AND ST_Intersects(b.geom, bbox.geom)
                ORDER BY b.geoid
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()

        features = [
            {
                "type": "Feature",
                "geometry": row["geometry"],
                "properties": {
                    "id": row["id"],
                    "name": row["name"],
                    "value": _json_number(row["value"]),
                    "label": label,
                    "unit": unit,
                },
            }
            for row in rows
        ]
    else:
        if variable_level == "state":
            value_select_sql = f"{_value_sql('sv')} AS value"
            value_join_sql = f"LEFT JOIN {STATE_VALUES_TABLE} AS sv ON sv.state_fips = s.state_fips"
        else:
            value_select_sql = "sm.value AS value"
            value_join_sql = (
                f"LEFT JOIN ("
                f"  SELECT cv.state_fips AS state_fips, AVG(({_value_sql('cv')})) AS value"
                f"  FROM {COUNTY_VALUES_TABLE} AS cv"
                f"  GROUP BY cv.state_fips"
                f") AS sm ON sm.state_fips = s.state_fips"
            )

        if state_boundaries_available:
            states_cte = f"""
                states AS (
                    SELECT
                        sb.state_fips AS state_fips,
                        COALESCE(sb.state_abbr, sb.state_fips) AS state_abbr,
                        COALESCE(sb.state_name, sb.state_fips) AS state_name,
                        sb.geom AS geom
                    FROM {STATE_BOUNDARY_TABLE} AS sb
                    WHERE sb.geom IS NOT NULL
                )
            """
        else:
            states_cte = f"""
                states AS (
                    SELECT
                        b.statefp AS state_fips,
                        COALESCE(c.state_abbr, b.statefp) AS state_abbr,
                        COALESCE(c.state_desc, b.statefp) AS state_name,
                        ST_UnaryUnion(ST_Collect(b.geom)) AS geom
                    FROM {COUNTY_BOUNDARY_TABLE} AS b
                    LEFT JOIN {COUNTY_DIM_TABLE} AS c
                      ON c.location_id = b.location_id
                    WHERE b.geom IS NOT NULL
                    GROUP BY
                        b.statefp,
                        COALESCE(c.state_abbr, b.statefp),
                        COALESCE(c.state_desc, b.statefp)
                )
            """

        rows = db.execute(
            text(
                f"""
                WITH bbox AS (
                    SELECT ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) AS geom
                ),
                {states_cte}
                SELECT
                    s.state_fips AS id,
                    s.state_name AS name,
                    {value_select_sql},
                    ST_AsGeoJSON(
                        ST_SimplifyPreserveTopology(
                            s.geom,
                            :simplify_degrees
                        ),
                        {MAP_GEOJSON_PRECISION}
                    )::json AS geometry
                FROM states AS s
                {value_join_sql}
                CROSS JOIN bbox
                WHERE s.geom IS NOT NULL
                  AND s.geom && bbox.geom
                  AND ST_Intersects(s.geom, bbox.geom)
                ORDER BY s.state_fips
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()

        features = [
            {
                "type": "Feature",
                "geometry": row["geometry"],
                "properties": {
                    "id": row["id"],
                    "name": row["name"],
                    "value": _json_number(row["value"]),
                    "label": label,
                    "unit": unit,
                },
            }
            for row in rows
        ]

    response = {
        "type": "FeatureCollection",
        "features": features,
        "variable": variable_meta["var_name"],
        "label": label,
        "description": variable_meta.get("description"),
        "unit": unit,
        "level": effective_level,
        "zoom": normalized_zoom,
        "meta": {
            "simplify_tolerance_degrees": simplify_degrees,
            "geojson_precision": geojson_precision,
            "state_boundaries_source": (
                "dim_state_boundary"
                if state_boundaries_available
                else "runtime_union"
            ),
        },
    }
    if warning:
        response["meta"]["warning"] = warning
    return response


def fetch_legend(
    db: Session,
    *,
    variable: str,
    bbox: str | None,
    level: str = "auto",
) -> dict[str, Any]:
    _ensure_required_tables(db, COUNTY_VALUES_TABLE, STATE_VALUES_TABLE, VARIABLE_LOOKUP_TABLE, COUNTY_BOUNDARY_TABLE)

    variable_meta = _resolve_variable_metadata(db, variable)
    requested_level = _normalize_level(level, allow_auto=True)
    effective_level = _resolve_effective_level(
        variable_level=str(variable_meta["level"]).strip().lower(),
        requested_level=requested_level,
    )

    quantile_fractions = [i / BINS_DEFAULT for i in range(1, BINS_DEFAULT)]
    params: dict[str, Any] = {
        "raw_field": variable_meta["var_name"],
        "quantiles": quantile_fractions,
    }
    is_state_variable = str(variable_meta.get("level") or "").strip().lower() == "state"

    if effective_level == "county":
        if bbox:
            params.update(_parse_bbox(bbox))
            sql = text(
                f"""
                WITH bbox AS (
                    SELECT ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) AS geom
                ),
                values AS (
                    SELECT {_value_sql('cv')} AS value
                    FROM {COUNTY_BOUNDARY_TABLE} AS b
                    JOIN {COUNTY_VALUES_TABLE} AS cv
                      ON cv.geoid = b.geoid
                    CROSS JOIN bbox
                    WHERE b.geom IS NOT NULL
                      AND b.geom && bbox.geom
                      AND ST_Intersects(b.geom, bbox.geom)
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
        else:
            sql = text(
                f"""
                WITH values AS (
                    SELECT {_value_sql('cv')} AS value
                    FROM {COUNTY_VALUES_TABLE} AS cv
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
    else:
        if bbox:
            params.update(_parse_bbox(bbox))
            state_boundaries_available = _table_exists(db, STATE_BOUNDARY_TABLE)

            if state_boundaries_available:
                states_cte = f"""
                    states AS (
                        SELECT sb.state_fips, sb.geom
                        FROM {STATE_BOUNDARY_TABLE} AS sb
                        WHERE sb.geom IS NOT NULL
                    )
                """
            else:
                states_cte = f"""
                    states AS (
                        SELECT
                            b.statefp AS state_fips,
                            ST_UnaryUnion(ST_Collect(b.geom)) AS geom
                        FROM {COUNTY_BOUNDARY_TABLE} AS b
                        WHERE b.geom IS NOT NULL
                        GROUP BY b.statefp
                    )
                """

            if is_state_variable:
                values_source_sql = (
                    f"SELECT sv.state_fips, {_value_sql('sv')} AS value "
                    f"FROM {STATE_VALUES_TABLE} AS sv"
                )
            else:
                values_source_sql = (
                    f"SELECT cv.state_fips AS state_fips, AVG(({_value_sql('cv')})) AS value "
                    f"FROM {COUNTY_VALUES_TABLE} AS cv "
                    "GROUP BY cv.state_fips"
                )

            sql = text(
                f"""
                WITH
                bbox AS (
                    SELECT ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) AS geom
                ),
                {states_cte},
                values AS (
                    SELECT v.value AS value
                    FROM ({values_source_sql}) AS v
                    JOIN states AS s
                      ON s.state_fips = v.state_fips
                    CROSS JOIN bbox
                    WHERE s.geom && bbox.geom
                      AND ST_Intersects(s.geom, bbox.geom)
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
        else:
            if is_state_variable:
                values_sql = f"SELECT {_value_sql('sv')} AS value FROM {STATE_VALUES_TABLE} AS sv"
            else:
                values_sql = (
                    f"SELECT AVG(({_value_sql('cv')})) AS value "
                    f"FROM {COUNTY_VALUES_TABLE} AS cv "
                    "GROUP BY cv.state_fips"
                )

            sql = text(
                f"""
                WITH values AS (
                    {values_sql}
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
        "variable": variable_meta["var_name"],
        "label": variable_meta.get("display_name") or variable_meta["var_name"],
        "description": variable_meta.get("description"),
        "unit": variable_meta.get("unit"),
        "level": effective_level,
        "bins": bins_payload,
        "missing_count": nulls,
        "total_count": n + nulls,
        "n": n,
        "noDataCount": nulls,
    }
