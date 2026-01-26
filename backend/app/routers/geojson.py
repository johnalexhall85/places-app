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
        state_filter = "AND c.state_abbr = :state_abbr"

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
        data_value_type_filter = ""
        params = {
            "year": year,
            "measure_id": measure_id,
            "limit": limit,
            "offset": offset,
        }
        if data_value_type_id:
            data_value_type_filter = "AND m.data_value_type_id = :data_value_type_id"
            params["data_value_type_id"] = data_value_type_id
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
                CASE WHEN m.id IS NULL THEN NULL ELSE f.year END AS year,
                m.measure_id,
                m.data_value_type_id,
                CASE WHEN m.id IS NULL THEN NULL ELSE f.data_value END AS data_value,
                CASE WHEN m.id IS NULL THEN NULL ELSE f.low_confidence_limit END
                    AS low_confidence_limit,
                CASE WHEN m.id IS NULL THEN NULL ELSE f.high_confidence_limit END
                    AS high_confidence_limit,
                ST_AsGeoJSON(c.geom)::json AS geometry
            FROM dim_county AS c
            LEFT JOIN fact_estimate_county AS f
                ON f.location_id = c.location_id
                AND f.year = :year
            LEFT JOIN dim_measure AS m
                ON f.measure_dim_id = m.id
                AND m.measure_id = :measure_id
                {data_value_type_filter}
            WHERE c.geom IS NOT NULL
                {state_filter}
            ORDER BY c.state_abbr, c.county_name
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
