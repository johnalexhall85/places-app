from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.hpsa import HPSASummaryResponseWithLegacy
from app.services.hpsa_summary import (
    build_hpsa_response,
    fetch_county_hpsa_row,
    normalize_county_fips,
)

router = APIRouter(tags=["hpsa"])


@router.get(
    "/hpsa/counties/{county_fips}",
    response_model=HPSASummaryResponseWithLegacy,
)
def get_county_hpsa_summary(
    county_fips: str,
    db: Session = Depends(get_db),
):
    normalized_fips = normalize_county_fips(county_fips)
    if normalized_fips is None:
        raise HTTPException(status_code=400, detail="county_fips must be a valid 5-digit FIPS")

    row = fetch_county_hpsa_row(db, normalized_fips)

    if row is None:
        raise HTTPException(status_code=404, detail=f"No HPSA summary found for county {normalized_fips}")
    return build_hpsa_response(row, include_legacy=True)
