from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(tags=["meta"])


# Quick check:
# curl -s "http://localhost:8000/meta/years?geography=county"
@router.get("/meta/years")
def available_years(
    geography: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    normalized_geography = geography.strip().lower()
    if normalized_geography != "county":
        raise HTTPException(
            status_code=400,
            detail="Unsupported geography. Supported values: county",
        )

    years = db.execute(
        text(
            """
            SELECT DISTINCT year
            FROM fact_estimate_county
            WHERE year IS NOT NULL
            ORDER BY year DESC
            """
        )
    ).scalars().all()

    return {
        "geography": normalized_geography,
        "years": [int(year) for year in years],
    }

