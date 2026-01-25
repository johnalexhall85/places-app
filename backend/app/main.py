from fastapi import FastAPI, Depends, Query
from app.routers.health import router as health_router
from sqlalchemy.orm import Session
from sqlalchemy import text
from .db import get_db
from . import models

app = FastAPI(title="PLACES (independent) API", version="0.1.0")

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/measures")
def list_measures(db: Session = Depends(get_db)):
    rows = db.query(models.DimMeasure).order_by(models.DimMeasure.category, models.DimMeasure.measure).all()
    return [
        {
            "id": r.id,
            "category_id": r.category_id,
            "category": r.category,
            "measure_id": r.measure_id,
            "measure": r.measure,
            "data_value_type_id": r.data_value_type_id,
            "data_value_type": r.data_value_type,
            "unit": r.unit,
            "short_question_text": r.short_question_text,
        }
        for r in rows
    ]

@app.get("/county-points")
def county_points(
    measure_dim_id: int = Query(..., description="DimMeasure.id"),
    year: int = Query(...),
    db: Session = Depends(get_db),
):
    """
    Returns county centroids + value for rendering a dot map.
    GeoJSON output (FeatureCollection).
    """
    sql = text("""
        SELECT
            c.location_id,
            c.state_abbr,
            c.state_desc,
            c.county_name,
            c.total_population,
            e.data_value,
            e.low_confidence_limit,
            e.high_confidence_limit,
            ST_AsGeoJSON(c.geom)::json AS geom
        FROM fact_estimate_county e
        JOIN dim_county c ON c.location_id = e.location_id
        WHERE e.measure_dim_id = :measure_dim_id
          AND e.year = :year
          AND c.geom IS NOT NULL
    """)
    rows = db.execute(sql, {"measure_dim_id": measure_dim_id, "year": year}).mappings().all()

    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "geometry": r["geom"],
            "properties": {
                "location_id": r["location_id"],
                "state_abbr": r["state_abbr"],
                "state_desc": r["state_desc"],
                "county_name": r["county_name"],
                "total_population": r["total_population"],
                "data_value": r["data_value"],
                "low_confidence_limit": r["low_confidence_limit"],
                "high_confidence_limit": r["high_confidence_limit"],
            }
        })

    return {"type": "FeatureCollection", "features": features}

app.include_router(health_router)
