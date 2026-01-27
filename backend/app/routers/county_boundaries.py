from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(tags=["county-boundaries"])


@router.get("/counties/boundaries/geojson")
def counties_boundary_geojson(
    state_abbr: str | None = Query(default=None, min_length=2, max_length=2),
    bbox: str | None = Query(default=None),
    simplify: float | None = Query(default=0.02, gt=0, le=0.5),
    limit: int = Query(default=5000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    state_abbr_value = state_abbr.upper() if state_abbr else None

    state_filter = ""
    if state_abbr_value:
        state_filter = "AND c.state_abbr = :state_abbr"

    bbox_filter = ""
    if bbox:
        try:
            minx, miny, maxx, maxy = (float(value) for value in bbox.split(","))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid bbox format") from exc
        if minx >= maxx or miny >= maxy:
            raise HTTPException(status_code=400, detail="Invalid bbox bounds")
        bbox_filter = "AND b.geom && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326)"

    params = {"limit": limit, "offset": offset}
    if state_abbr_value:
        params["state_abbr"] = state_abbr_value
    if bbox:
        params.update({"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy})

    geometry_expr = "ST_AsGeoJSON(b.geom)::json"
    if simplify is not None:
        geometry_expr = (
            "ST_AsGeoJSON(ST_SimplifyPreserveTopology(b.geom, :simplify))::json"
        )
        params["simplify"] = simplify

    query = text(
        f"""
        SELECT
            b.location_id,
            b.geoid,
            b.name,
            b.statefp,
            b.countyfp,
            c.state_abbr,
            c.state_desc,
            {geometry_expr} AS geometry
        FROM dim_county_boundary AS b
        LEFT JOIN dim_county AS c
            ON c.location_id = b.location_id
        WHERE b.geom IS NOT NULL
            {state_filter}
            {bbox_filter}
        ORDER BY b.location_id
        LIMIT :limit
        OFFSET :offset
        """
    )

    rows = db.execute(query, params).mappings().all()

    features = [
        {
            "type": "Feature",
            "geometry": row["geometry"],
            "properties": {
                "location_id": row["location_id"],
                "geoid": row["geoid"],
                "name": row["name"],
                "statefp": row["statefp"],
                "countyfp": row["countyfp"],
                "state_abbr": row["state_abbr"],
                "state_desc": row["state_desc"],
            },
        }
        for row in rows
    ]

    return {"type": "FeatureCollection", "features": features}


@router.get("/counties/boundaries/geojson/estimates")
def counties_boundary_geojson_estimates(
    measure_id: str = Query(...),
    year: int = Query(...),
    data_value_type_id: str | None = Query(default="CrdPrv"),
    state_abbr: str | None = Query(default=None, min_length=2, max_length=2),
    bbox: str | None = Query(default=None),
    simplify: float | None = Query(default=0.02, gt=0, le=0.5),
    limit: int = Query(default=5000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if not measure_id:
        raise HTTPException(status_code=400, detail="measure_id is required")

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

    state_abbr_value = state_abbr.upper() if state_abbr else None

    state_filter = ""
    if state_abbr_value:
        state_filter = "AND c.state_abbr = :state_abbr"

    bbox_filter = ""
    if bbox:
        try:
            minx, miny, maxx, maxy = (float(value) for value in bbox.split(","))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid bbox format") from exc
        if minx >= maxx or miny >= maxy:
            raise HTTPException(status_code=400, detail="Invalid bbox bounds")
        bbox_filter = "AND b.geom && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326)"

    params = {
        "measure_id": measure_id,
        "year": year,
        "data_value_type_id": data_value_type_id or "CrdPrv",
        "limit": limit,
        "offset": offset,
    }
    if state_abbr_value:
        params["state_abbr"] = state_abbr_value
    if bbox:
        params.update({"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy})

    geometry_expr = "ST_AsGeoJSON(b.geom)::json"
    if simplify is not None:
        geometry_expr = (
            "ST_AsGeoJSON(ST_SimplifyPreserveTopology(b.geom, :simplify))::json"
        )
        params["simplify"] = simplify

    query = text(
        f"""
        WITH selected_measure AS (
            SELECT
                id,
                measure_id,
                data_value_type_id
            FROM dim_measure
            WHERE measure_id = :measure_id
                AND data_value_type_id = :data_value_type_id
            LIMIT 1
        )
        SELECT
            b.location_id,
            b.geoid,
            b.name,
            b.statefp,
            b.countyfp,
            c.state_abbr,
            c.state_desc,
            CASE WHEN sm.id IS NULL THEN NULL ELSE f.year END AS year,
            sm.measure_id,
            sm.data_value_type_id,
            CASE WHEN sm.id IS NULL THEN NULL ELSE f.data_value END AS data_value,
            CASE WHEN sm.id IS NULL THEN NULL ELSE f.low_confidence_limit END
                AS low_confidence_limit,
            CASE WHEN sm.id IS NULL THEN NULL ELSE f.high_confidence_limit END
                AS high_confidence_limit,
            {geometry_expr} AS geometry
        FROM dim_county_boundary AS b
        LEFT JOIN selected_measure AS sm ON TRUE
        LEFT JOIN fact_estimate_county AS f
            ON f.location_id = b.location_id
            AND f.year = :year
            AND f.measure_dim_id = sm.id
        LEFT JOIN dim_county AS c
            ON c.location_id = b.location_id
        WHERE b.geom IS NOT NULL
            {state_filter}
            {bbox_filter}
        ORDER BY b.location_id
        LIMIT :limit
        OFFSET :offset
        """
    )

    rows = db.execute(query, params).mappings().all()

    features = [
        {
            "type": "Feature",
            "geometry": row["geometry"],
            "properties": {
                "location_id": row["location_id"],
                "geoid": row["geoid"],
                "name": row["name"],
                "statefp": row["statefp"],
                "countyfp": row["countyfp"],
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
