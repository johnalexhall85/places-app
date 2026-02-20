from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(tags=["meta"])

YEARS_QUERY_BY_GEOGRAPHY = {
    "county": """
        SELECT DISTINCT year
        FROM fact_estimate_county
        WHERE year IS NOT NULL
        ORDER BY year DESC
    """,
    "tract": """
        SELECT DISTINCT year
        FROM tract_estimates
        WHERE year IS NOT NULL
        ORDER BY year DESC
    """,
}


# Quick check:
# curl -s "http://localhost:8000/meta/years?geography=county"
@router.get("/meta/years")
def available_years(
    geography: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    normalized_geography = geography.strip().lower()
    if normalized_geography not in YEARS_QUERY_BY_GEOGRAPHY:
        raise HTTPException(
            status_code=400,
            detail="Unsupported geography. Supported values: county, tract",
        )

    years = db.execute(
        text(YEARS_QUERY_BY_GEOGRAPHY[normalized_geography])
    ).scalars().all()

    return {
        "geography": normalized_geography,
        "years": [int(year) for year in years],
    }
