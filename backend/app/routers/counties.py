from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app import models

router = APIRouter(tags=["counties"])

# curl "http://localhost:8000/counties?state_abbr=CA&q=los&limit=25&offset=0"
@router.get("/counties")
def list_counties(
    state_abbr: str | None = Query(default=None, min_length=2, max_length=2),
    q: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(models.DimCounty)
    if state_abbr:
        query = query.filter(models.DimCounty.state_abbr == state_abbr.upper())
    if q:
        query = query.filter(models.DimCounty.county_name.ilike(f"%{q}%"))

    rows = (
        query.order_by(models.DimCounty.state_abbr, models.DimCounty.county_name)
        .limit(limit)
        .offset(offset)
        .all()
    )

    return [
        {
            "location_id": row.location_id,
            "state_abbr": row.state_abbr,
            "state_desc": row.state_desc,
            "county_name": row.county_name,
            "total_population": row.total_population,
            "total_pop_18_plus": row.total_pop_18_plus,
        }
        for row in rows
    ]
