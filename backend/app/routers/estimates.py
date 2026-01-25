from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

router = APIRouter(tags=["estimates"])

# curl "http://localhost:8000/estimates?state_abbr=CA&measure_id=CASTHMA&limit=25&offset=0"
@router.get("/estimates")
def list_estimates(
    year: int | None = Query(default=None),
    location_id: str | None = Query(default=None),
    state_abbr: str | None = Query(default=None, min_length=2, max_length=2),
    measure_id: str | None = Query(default=None),
    data_value_type_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if not (location_id or state_abbr or measure_id):
        raise HTTPException(
            status_code=400,
            detail="At least one of location_id, state_abbr, or measure_id is required.",
        )

    query = db.query(models.FactEstimateCounty, models.DimMeasure).join(
        models.DimMeasure,
        models.FactEstimateCounty.measure_dim_id == models.DimMeasure.id,
    )

    if state_abbr:
        query = query.join(
            models.DimCounty,
            models.FactEstimateCounty.location_id == models.DimCounty.location_id,
        ).filter(models.DimCounty.state_abbr == state_abbr.upper())

    if year is not None:
        query = query.filter(models.FactEstimateCounty.year == year)
    if location_id:
        query = query.filter(models.FactEstimateCounty.location_id == location_id)
    if measure_id:
        query = query.filter(models.DimMeasure.measure_id == measure_id)
    if data_value_type_id:
        query = query.filter(models.DimMeasure.data_value_type_id == data_value_type_id)

    rows = (
        query.order_by(
            models.FactEstimateCounty.year.desc(),
            models.FactEstimateCounty.location_id,
        )
        .limit(limit)
        .offset(offset)
        .all()
    )

    return [
        {
            "year": estimate.year,
            "location_id": estimate.location_id,
            "measure_id": measure.measure_id,
            "data_value_type_id": measure.data_value_type_id,
            "data_value": estimate.data_value,
            "low_confidence_limit": estimate.low_confidence_limit,
            "high_confidence_limit": estimate.high_confidence_limit,
            "footnote_symbol": estimate.footnote_symbol,
            "footnote": estimate.footnote,
        }
        for estimate, measure in rows
    ]
