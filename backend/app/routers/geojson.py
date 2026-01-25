from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(tags=["geojson"])

# curl "http://localhost:8000/counties/geojson?year=2021&measure_id=ACCESS2&data_value_type_id=CrdPrv&state_abbr=CA&limit=5000&offset=0"
@router.get("/counties/geojson")
def counties_geojson(
    year: int = Query(...),
    measure_id: str = Query(...),
    data_value_type_id: str = Query(default="CrdPrv"),
    state_abbr: str | None = Query(default=None, min_length=2, max_length=2),
    limit: int = Query(default=5000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    state_abbr_value = state_abbr.upper() if state_abbr else None
    params = {
        "year": year,
        "measure_id": measure_id,
        "data_value_type_id": data_value_type_id,
        "limit": limit,
        "offset": offset,
    }

    state_filter = ""
    if state_abbr_value:
        state_filter = "AND dim_county.state_abbr = :state_abbr"
        params["state_abbr"] = state_abbr_value

    query = text(
        f"""
        SELECT
            dim_county.location_id,
            dim_county.state_abbr,
            dim_county.state_desc,
            dim_county.county_name,
            dim_county.total_population,
            dim_county.total_pop_18_plus,
            fact_estimate_county.year,
            dim_measure.measure_id,
            dim_measure.data_value_type_id,
            fact_estimate_county.data_value,
            fact_estimate_county.low_confidence_limit,
            fact_estimate_county.high_confidence_limit,
            ST_AsGeoJSON(dim_county.geom)::json AS geometry
        FROM fact_estimate_county
        JOIN dim_measure
            ON fact_estimate_county.measure_dim_id = dim_measure.id
        JOIN dim_county
            ON fact_estimate_county.location_id = dim_county.location_id
        WHERE fact_estimate_county.year = :year
            AND dim_measure.measure_id = :measure_id
            AND dim_measure.data_value_type_id = :data_value_type_id
            AND dim_county.geom IS NOT NULL
            {state_filter}
        ORDER BY dim_county.state_abbr, dim_county.county_name
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
