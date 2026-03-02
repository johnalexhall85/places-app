from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.db_fqtn import places_table

router = APIRouter(tags=["county-boundaries"])


@router.get("/counties/boundaries/geojson")
def counties_boundary_geojson(
    state_abbr: str | None = Query(default=None, min_length=2, max_length=2),
    bbox: str | None = Query(default=None),
    boundaries_only: bool = Query(default=False),
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
    bbox_cte = ""
    bbox_join = ""
    if bbox:
        try:
            minx, miny, maxx, maxy = (float(value) for value in bbox.split(","))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid bbox format") from exc
        if minx >= maxx or miny >= maxy:
            raise HTTPException(status_code=400, detail="Invalid bbox bounds")
        bbox_filter = (
            "AND b.geom && bbox.geom "
            "AND ST_Intersects(b.geom, bbox.geom)"
        )
        bbox_cte = (
            "WITH bbox AS ("
            "SELECT ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) AS geom"
            ")"
        )
        bbox_join = "CROSS JOIN bbox"

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

    if boundaries_only:
        query = text(
            f"""
            {bbox_cte}
            SELECT
                b.location_id,
                b.statefp,
                b.countyfp,
                c.state_abbr,
                {geometry_expr} AS geometry
            FROM dim_county_boundary AS b
            {bbox_join}
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
    else:
        query = text(
            f"""
            {bbox_cte}
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
            {bbox_join}
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

    if boundaries_only:
        features = [
            {
                "type": "Feature",
                "geometry": row["geometry"],
                "properties": {
                    "location_id": row["location_id"],
                    "statefp": row["statefp"],
                    "countyfp": row["countyfp"],
                    "county_fips": f"{row['statefp']}{row['countyfp']}",
                    "state_abbr": row["state_abbr"],
                },
            }
            for row in rows
        ]
    else:
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
        text("SELECT to_regclass(:table_name) AS exists"),
        {"table_name": places_table("dim_county_boundary")},
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
    bbox_cte = ""
    bbox_join = ""
    if bbox:
        try:
            minx, miny, maxx, maxy = (float(value) for value in bbox.split(","))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid bbox format") from exc
        if minx >= maxx or miny >= maxy:
            raise HTTPException(status_code=400, detail="Invalid bbox bounds")
        bbox_filter = (
            "AND b.geom && bbox.geom "
            "AND ST_Intersects(b.geom, bbox.geom)"
        )
        bbox_cte = (
            "bbox AS ("
            "SELECT ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) AS geom"
            ")"
        )
        bbox_join = "CROSS JOIN bbox"

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

    with_parts = []
    if bbox_cte:
        with_parts.append(bbox_cte)
    with_parts.append(
        """
        selected_measure AS (
            SELECT
                id,
                measure_id,
                data_value_type_id,
                measure,
                short_question_text
            FROM dim_measure
            WHERE measure_id = :measure_id
                AND data_value_type_id = :data_value_type_id
            LIMIT 1
        ),
        selected_measure_crude AS (
            SELECT
                id,
                measure_id,
                data_value_type_id,
                measure,
                short_question_text
            FROM dim_measure
            WHERE measure_id = :measure_id
                AND data_value_type_id = 'CrdPrv'
            LIMIT 1
        ),
        selected_measure_age_adjusted AS (
            SELECT
                id,
                measure_id,
                data_value_type_id,
                measure,
                short_question_text
            FROM dim_measure
            WHERE measure_id = :measure_id
                AND data_value_type_id = 'AgeAdjPrv'
            LIMIT 1
        )
        """
    )
    with_clause = ", ".join(with_parts)

    query = text(
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
            COALESCE(f.year, f_crude.year, f_age.year, :year) AS year,
            COALESCE(sm.measure_id, sm_crude.measure_id, sm_age.measure_id, :measure_id)
                AS measure_id,
            COALESCE(sm.data_value_type_id, :data_value_type_id) AS data_value_type_id,
            COALESCE(
                sm_crude.short_question_text,
                sm.short_question_text,
                sm_age.short_question_text,
                sm_crude.measure,
                sm.measure,
                sm_age.measure
            ) AS measure_name,
            CASE WHEN sm.id IS NULL THEN NULL ELSE f.data_value END AS value,
            CASE WHEN sm.id IS NULL THEN NULL ELSE f.low_confidence_limit END AS low,
            CASE WHEN sm.id IS NULL THEN NULL ELSE f.high_confidence_limit END AS high,
            CASE WHEN sm_crude.id IS NULL THEN NULL ELSE f_crude.data_value END AS data_value,
            CASE WHEN sm_crude.id IS NULL THEN NULL ELSE f_crude.low_confidence_limit END
                AS low_confidence_limit,
            CASE WHEN sm_crude.id IS NULL THEN NULL ELSE f_crude.high_confidence_limit END
                AS high_confidence_limit,
            CASE WHEN sm_age.id IS NULL THEN NULL ELSE f_age.data_value END
                AS age_adjusted_data_value,
            CASE WHEN sm_age.id IS NULL THEN NULL ELSE f_age.low_confidence_limit END
                AS age_adjusted_low_confidence_limit,
            CASE WHEN sm_age.id IS NULL THEN NULL ELSE f_age.high_confidence_limit END
                AS age_adjusted_high_confidence_limit,
            {geometry_expr} AS geometry
        FROM dim_county_boundary AS b
        {bbox_join}
        LEFT JOIN selected_measure AS sm ON TRUE
        LEFT JOIN selected_measure_crude AS sm_crude ON TRUE
        LEFT JOIN selected_measure_age_adjusted AS sm_age ON TRUE
        LEFT JOIN fact_estimate_county AS f
            ON f.location_id = b.location_id
            AND f.year = :year
            AND f.measure_dim_id = sm.id
        LEFT JOIN fact_estimate_county AS f_crude
            ON f_crude.location_id = b.location_id
            AND f_crude.year = :year
            AND f_crude.measure_dim_id = sm_crude.id
        LEFT JOIN fact_estimate_county AS f_age
            ON f_age.location_id = b.location_id
            AND f_age.year = :year
            AND f_age.measure_dim_id = sm_age.id
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
                "county_name": row["county_name"],
                "total_population": row["total_population"],
                "total_pop_18_plus": row["total_pop_18_plus"],
                "year": row["year"],
                "measure_id": row["measure_id"],
                "data_value_type_id": row["data_value_type_id"],
                "measure_name": row["measure_name"],
                "value": row["value"],
                "low": row["low"],
                "high": row["high"],
                "data_value": row["data_value"],
                "low_confidence_limit": row["low_confidence_limit"],
                "high_confidence_limit": row["high_confidence_limit"],
                "age_adjusted_data_value": row["age_adjusted_data_value"],
                "age_adjusted_low_confidence_limit": row[
                    "age_adjusted_low_confidence_limit"
                ],
                "age_adjusted_high_confidence_limit": row[
                    "age_adjusted_high_confidence_limit"
                ],
                "population": (
                    row["total_pop_18_plus"]
                    if row["total_pop_18_plus"] is not None
                    else row["total_population"]
                ),
                "location_name": row["county_name"] or row["name"],
                "geo_level": "county",
            },
        }
        for row in rows
    ]

    return {"type": "FeatureCollection", "features": features}
