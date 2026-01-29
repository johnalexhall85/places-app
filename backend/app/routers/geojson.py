from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(tags=["geojson"])

# curl "http://localhost:8000/counties/geojson"
# curl "http://localhost:8000/counties/geojson?measure_id=CASTHMA&year=2023&data_value_type_id=CrdPrv"
@router.get("/counties/geojson")
def counties_geojson(
    year: int | None = Query(default=None),
    measure_id: str | None = Query(default=None),
    data_value_type_id: str | None = Query(default=None),
    state_abbr: str | None = Query(default=None, min_length=2, max_length=2),
    limit: int = Query(default=5000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if (year is None) != (measure_id is None):
        raise HTTPException(
            status_code=400, detail="measure_id and year must be provided together"
        )

    state_abbr_value = state_abbr.upper() if state_abbr else None

    state_filter = ""
    if state_abbr_value:
        state_filter = "AND c.state_abbr = %(state_abbr)s"

    if year is None and measure_id is None:
        params = {"limit": limit, "offset": offset}
        if state_abbr_value:
            params["state_abbr"] = state_abbr_value

        query = text(
            f"""
            SELECT
                c.location_id,
                c.state_abbr,
                c.state_desc,
                c.county_name,
                c.total_population,
                c.total_pop_18_plus,
                ST_AsGeoJSON(c.geom)::json AS geometry
            FROM dim_county AS c
            WHERE c.geom IS NOT NULL
                {state_filter}
            ORDER BY c.state_abbr, c.county_name
            LIMIT %(limit)s
            OFFSET %(offset)s
            """
        )

        rows = db.execute(query, params).mappings().all()

        features = [
            {
                "type": "Feature",
                "geometry": row["geometry"],
                "properties": {
                    "location_id": row["location_id"],
                    "state_abbr": row["state_abbr"],
                    "state_desc": row["state_desc"],
                    "county_name": row["county_name"],
                    "total_population": row["total_population"],
                    "total_pop_18_plus": row["total_pop_18_plus"],
                },
            }
            for row in rows
        ]
    else:
        params = {
            "year": year,
            "measure_id": measure_id,
            "limit": limit,
            "offset": offset,
        }
        params["data_value_type_id"] = data_value_type_id or "CrdPrv"
        if state_abbr_value:
            params["state_abbr"] = state_abbr_value

        query = text(
            f"""
            WITH selected_measure AS (
                SELECT
                    id,
                    measure_id,
                    data_value_type_id
                FROM dim_measure
                WHERE measure_id = %(measure_id)s
                    AND data_value_type_id = %(data_value_type_id)s
                LIMIT 1
            )
            SELECT
                c.location_id,
                c.state_abbr,
                c.state_desc,
                c.county_name,
                c.total_population,
                c.total_pop_18_plus,
                CASE WHEN sm.id IS NULL THEN NULL ELSE f.year END AS year,
                sm.measure_id,
                sm.data_value_type_id,
                CASE WHEN sm.id IS NULL THEN NULL ELSE f.data_value END AS data_value,
                CASE WHEN sm.id IS NULL THEN NULL ELSE f.low_confidence_limit END
                    AS low_confidence_limit,
                CASE WHEN sm.id IS NULL THEN NULL ELSE f.high_confidence_limit END
                    AS high_confidence_limit,
                ST_AsGeoJSON(c.geom)::json AS geometry
            FROM dim_county AS c
            LEFT JOIN selected_measure AS sm ON TRUE
            LEFT JOIN fact_estimate_county AS f
                ON f.location_id = c.location_id
                AND f.year = %(year)s
                AND f.measure_dim_id = sm.id
            WHERE c.geom IS NOT NULL
                {state_filter}
            ORDER BY c.state_abbr, c.county_name
            LIMIT %(limit)s
            OFFSET %(offset)s
            """
        )

        rows = db.execute(query, params).mappings().all()

        features = [
            {
                "type": "Feature",
                "geometry": row["geometry"],
                "properties": {
                    "location_id": row["location_id"],
                    "state_abbr": row["state_abbr"],
                    "state_desc": row["state_desc"],
                    "county_name": row["county_name"],
                    "total_population": row["total_population"],
                    "total_pop_18_plus": row["total_pop_18_plus"],
                    "year": row["year"],
                    "measure_id": row["measure_id"],
                    "data_value_type_id": row["data_value_type_id"],
                    "data_value": row["data_value"],
                    "low_confidence_limit": row["low_confidence_limit"],
                    "high_confidence_limit": row["high_confidence_limit"],
                },
            }
            for row in rows
        ]

    return {"type": "FeatureCollection", "features": features}


@router.get("/geojson/states")
def states_geojson(
    measure_id: str | None = Query(default=None),
    year: int | None = Query(default=None),
    data_value_type_id: str | None = Query(default="CrdPrv"),
    simplify: float | None = Query(default=0.05, gt=0, le=0.5),
    db: Session = Depends(get_db),
):
    if (year is None) != (measure_id is None):
        raise HTTPException(
            status_code=400, detail="measure_id and year must be provided together"
        )

    boundary_table_exists = db.execute(
        text("SELECT to_regclass('public.dim_county_boundary') AS exists")
    ).mappings().one()
    if boundary_table_exists["exists"] is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "County boundaries not loaded. Run the boundary loader script to create "
                "dim_county_boundary."
            ),
        )

    geometry_expr = "ST_AsGeoJSON(state_geom.geom)::json"
    if simplify is not None:
        geometry_expr = (
            "ST_AsGeoJSON(ST_SimplifyPreserveTopology(state_geom.geom, %(simplify)s))::json"
        )

    if year is None and measure_id is None:
        params = {}
        if simplify is not None:
            params["simplify"] = simplify

        query = text(
            f"""
            WITH state_geom AS (
                SELECT
                    c.state_abbr,
                    c.state_desc,
                    ST_Union(b.geom) AS geom
                FROM dim_county_boundary AS b
                JOIN dim_county AS c
                    ON c.location_id = b.location_id
                WHERE b.geom IS NOT NULL
                GROUP BY c.state_abbr, c.state_desc
            )
            SELECT
                state_geom.state_abbr,
                state_geom.state_desc,
                {geometry_expr} AS geometry
            FROM state_geom
            ORDER BY state_geom.state_abbr
            """
        )

        rows = db.execute(query, params).mappings().all()

        features = [
            {
                "type": "Feature",
                "geometry": row["geometry"],
                "properties": {
                    "state_abbr": row["state_abbr"],
                    "state_desc": row["state_desc"],
                },
            }
            for row in rows
        ]
    else:
        params = {
            "year": year,
            "measure_id": measure_id,
            "data_value_type_id": data_value_type_id or "CrdPrv",
        }
        if simplify is not None:
            params["simplify"] = simplify

        query = text(
            f"""
            WITH selected_measure AS (
                SELECT
                    id,
                    measure_id,
                    data_value_type_id
                FROM dim_measure
                WHERE measure_id = %(measure_id)s
                    AND data_value_type_id = %(data_value_type_id)s
                LIMIT 1
            ),
            state_geom AS (
                SELECT
                    c.state_abbr,
                    c.state_desc,
                    ST_Union(b.geom) AS geom
                FROM dim_county_boundary AS b
                JOIN dim_county AS c
                    ON c.location_id = b.location_id
                WHERE b.geom IS NOT NULL
                GROUP BY c.state_abbr, c.state_desc
            ),
            state_values AS (
                SELECT
                    c.state_abbr,
                    CASE WHEN sm.id IS NULL THEN NULL ELSE MAX(f.year) END AS year,
                    sm.measure_id,
                    sm.data_value_type_id,
                    CASE WHEN sm.id IS NULL THEN NULL ELSE AVG(f.data_value) END
                        AS data_value,
                    CASE WHEN sm.id IS NULL THEN NULL ELSE AVG(f.low_confidence_limit) END
                        AS low_confidence_limit,
                    CASE WHEN sm.id IS NULL THEN NULL ELSE AVG(f.high_confidence_limit) END
                        AS high_confidence_limit
                FROM dim_county AS c
                LEFT JOIN selected_measure AS sm ON TRUE
                LEFT JOIN fact_estimate_county AS f
                    ON f.location_id = c.location_id
                    AND f.year = %(year)s
                    AND f.measure_dim_id = sm.id
                GROUP BY c.state_abbr, sm.id, sm.measure_id, sm.data_value_type_id
            )
            SELECT
                state_geom.state_abbr,
                state_geom.state_desc,
                state_values.year,
                state_values.measure_id,
                state_values.data_value_type_id,
                state_values.data_value,
                state_values.low_confidence_limit,
                state_values.high_confidence_limit,
                {geometry_expr} AS geometry
            FROM state_geom
            LEFT JOIN state_values
                ON state_values.state_abbr = state_geom.state_abbr
            ORDER BY state_geom.state_abbr
            """
        )

        rows = db.execute(query, params).mappings().all()

        features = [
            {
                "type": "Feature",
                "geometry": row["geometry"],
                "properties": {
                    "state_abbr": row["state_abbr"],
                    "state_desc": row["state_desc"],
                    "year": row["year"],
                    "measure_id": row["measure_id"],
                    "data_value_type_id": row["data_value_type_id"],
                    "data_value": row["data_value"],
                    "low_confidence_limit": row["low_confidence_limit"],
                    "high_confidence_limit": row["high_confidence_limit"],
                },
            }
            for row in rows
        ]

    return {"type": "FeatureCollection", "features": features}
