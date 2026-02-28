from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

router = APIRouter(tags=["svi"])

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

SVI_MEASURE_ORDER = {
    "RPL_THEMES": 0,
    "RPL_THEME1": 1,
    "RPL_THEME2": 2,
    "RPL_THEME3": 3,
    "RPL_THEME4": 4,
}


def _ensure_required_tables(db: Session, *table_names: str) -> None:
    for table_name in table_names:
        row = db.execute(
            text("SELECT to_regclass(:name) AS exists"),
            {"name": f"public.{table_name}"},
        ).mappings().one()
        if row["exists"] is None:
            raise HTTPException(
                status_code=503,
                detail=f"{table_name} is missing. Run migrations and ingest required data.",
            )


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


@router.get("/svi/measures")
def svi_measures(
    geography_level: Literal["county", "tract"] | None = Query(default=None),
    year: int = Query(default=2022),
    db: Session = Depends(get_db),
):
    _ensure_required_tables(db, "svi_measures")

    query = db.query(models.SviMeasure).filter(models.SviMeasure.year == year)
    if geography_level:
        query = query.filter(models.SviMeasure.geography_level == geography_level)

    rows = query.all()

    def sort_key(row: models.SviMeasure) -> tuple[int, str, int, str]:
        measure_id = str(row.measure_id or "").upper()
        geo_rank = 0 if str(row.geography_level or "").lower() == "county" else 1
        custom_rank = SVI_MEASURE_ORDER.get(measure_id)
        if custom_rank is not None:
            return (custom_rank, measure_id, geo_rank, str(row.name or "").lower())
        return (100, measure_id, geo_rank, str(row.name or "").lower())

    rows = sorted(rows, key=sort_key)

    return [
        {
            "measure_id": row.measure_id,
            "name": row.name,
            "measure": row.name,
            "description": row.description,
            "theme": row.theme,
            "value_type": row.value_type,
            "year": row.year,
            "geography_level": row.geography_level,
        }
        for row in rows
    ]


@router.get("/svi/counties")
def svi_counties_geojson(
    measure_id: str = Query(..., min_length=1),
    year: int = Query(default=2022),
    bbox: str | None = Query(default=None),
    simplify: float | None = Query(default=0.02, gt=0, le=0.5),
    limit: int = Query(default=5000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    _ensure_required_tables(
        db,
        "svi_estimates_county",
        "svi_measures",
        "dim_county_boundary",
    )

    safe_measure_id = measure_id.strip()
    if not safe_measure_id:
        raise HTTPException(status_code=400, detail="measure_id is required")

    bbox_params, bbox_cte, bbox_join, bbox_filter = _parse_bbox(bbox, geom_alias="b")
    params: dict[str, object] = {
        "measure_id": safe_measure_id,
        "year": year,
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
        """
        selected_measure AS (
            SELECT
                measure_id,
                name,
                description,
                theme,
                value_type
            FROM svi_measures
            WHERE measure_id = :measure_id
                AND year = :year
                AND geography_level = 'county'
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
                c.state_abbr,
                c.state_desc,
                c.county_name,
                c.total_population,
                c.total_pop_18_plus,
                e.value,
                COALESCE(sm.measure_id, :measure_id) AS measure_id,
                sm.name AS measure_name,
                sm.description AS measure_description,
                sm.theme AS measure_theme,
                sm.value_type AS value_type,
                {geometry_expr} AS geometry
            FROM dim_county_boundary AS b
            {bbox_join}
            LEFT JOIN dim_county AS c
                ON c.location_id = b.location_id
            LEFT JOIN selected_measure AS sm ON TRUE
            LEFT JOIN svi_estimates_county AS e
                ON e.geoid = b.geoid
                AND e.measure_id = :measure_id
                AND e.year = :year
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
                "county_fips": f"{row['statefp']}{row['countyfp']}",
                "state_abbr": row["state_abbr"],
                "state_desc": row["state_desc"],
                "county_name": row["county_name"],
                "location_name": row["county_name"] or row["name"],
                "total_population": row["total_population"],
                "total_pop_18_plus": row["total_pop_18_plus"],
                "population": (
                    row["total_pop_18_plus"]
                    if row["total_pop_18_plus"] is not None
                    else row["total_population"]
                ),
                "year": year,
                "measure_id": row["measure_id"],
                "measure": row["measure_name"],
                "measure_name": row["measure_name"],
                "description": row["measure_description"],
                "theme": row["measure_theme"],
                "value_type": row["value_type"],
                "value": row["value"],
                "data_value": row["value"],
                "dataset": "svi",
                "geo_level": "county",
            },
        }
        for row in rows
    ]

    return {"type": "FeatureCollection", "features": features}


@router.get("/svi/tracts")
def svi_tracts_geojson(
    measure_id: str = Query(..., min_length=1),
    year: int = Query(default=2022),
    bbox: str | None = Query(default=None, description="west,south,east,north"),
    simplify: float | None = Query(default=0.001, gt=0, le=0.1),
    limit: int = Query(default=25000, ge=1, le=50000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    _ensure_required_tables(
        db,
        "svi_estimates_tract",
        "svi_measures",
        "tract_shapes",
    )

    safe_measure_id = measure_id.strip()
    if not safe_measure_id:
        raise HTTPException(status_code=400, detail="measure_id is required")

    bbox_params, bbox_cte, bbox_join, bbox_filter = _parse_bbox(bbox, geom_alias="s")
    params: dict[str, object] = {
        "measure_id": safe_measure_id,
        "year": year,
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
        """
        selected_measure AS (
            SELECT
                measure_id,
                name,
                description,
                theme,
                value_type
            FROM svi_measures
            WHERE measure_id = :measure_id
                AND year = :year
                AND geography_level = 'tract'
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
                s.geoid11 AS geoid,
                s.name AS tract_name,
                s.statefp,
                s.countyfp,
                e.value,
                COALESCE(sm.measure_id, :measure_id) AS measure_id,
                sm.name AS measure_name,
                sm.description AS measure_description,
                sm.theme AS measure_theme,
                sm.value_type AS value_type,
                {geometry_expr} AS geometry
            FROM tract_shapes AS s
            {bbox_join}
            LEFT JOIN selected_measure AS sm ON TRUE
            LEFT JOIN svi_estimates_tract AS e
                ON e.geoid = s.geoid11
                AND e.measure_id = :measure_id
                AND e.year = :year
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
        state_abbr = STATE_FIPS_TO_ABBR.get(row["statefp"])
        features.append(
            {
                "type": "Feature",
                "geometry": row["geometry"],
                "properties": {
                    "location_id": row["geoid"],
                    "locationid": row["geoid"],
                    "geoid": row["geoid"],
                    "name": row["tract_name"],
                    "location_name": row["tract_name"] or row["geoid"],
                    "statefp": row["statefp"],
                    "countyfp": row["countyfp"],
                    "county_fips": f"{row['statefp']}{row['countyfp']}",
                    "state_abbr": state_abbr,
                    "year": year,
                    "measure_id": row["measure_id"],
                    "measure": row["measure_name"],
                    "measure_name": row["measure_name"],
                    "description": row["measure_description"],
                    "theme": row["measure_theme"],
                    "value_type": row["value_type"],
                    "value": row["value"],
                    "data_value": row["value"],
                    "dataset": "svi",
                    "geo_level": "tract",
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}
