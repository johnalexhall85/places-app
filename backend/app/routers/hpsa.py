from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.hpsa import HPSAChoroplethCountiesResponse
from app.services.hpsa_summary import (
    build_hpsa_choropleth_response,
    build_hpsa_county_domain_detail,
    build_hpsa_response,
    fetch_county_hpsa_row,
    fetch_hpsa_county_rows_for_domain,
    fetch_hpsa_domain_quartiles,
    fetch_hpsa_domain_ratio_fields,
    normalize_county_fips,
    normalize_hpsa_domain,
)

router = APIRouter(tags=["hpsa"])


@router.get(
    "/hpsa/choropleth/counties",
    response_model=HPSAChoroplethCountiesResponse,
)
def get_hpsa_choropleth_counties(
    domain: Literal["pc", "mh", "dh"] = Query(default="pc"),
    db: Session = Depends(get_db),
):
    normalized_domain = normalize_hpsa_domain(domain, default="pc")
    if normalized_domain is None:
        raise HTTPException(status_code=400, detail="domain must be one of pc, mh, dh")

    quartile_row = fetch_hpsa_domain_quartiles(db, normalized_domain)
    county_rows = fetch_hpsa_county_rows_for_domain(db, normalized_domain)
    return build_hpsa_choropleth_response(
        domain=normalized_domain,
        quartile_row=quartile_row,
        county_rows=county_rows,
    )


@router.get(
    "/hpsa/counties/{county_fips}",
)
def get_county_hpsa_summary(
    county_fips: str,
    domain: Literal["pc", "mh", "dh"] | None = Query(default=None),
    db: Session = Depends(get_db),
):
    normalized_fips = normalize_county_fips(county_fips)
    if normalized_fips is None:
        raise HTTPException(status_code=400, detail="county_fips must be a valid 5-digit FIPS")

    row = fetch_county_hpsa_row(db, normalized_fips)

    if row is None:
        raise HTTPException(status_code=404, detail=f"No HPSA summary found for county {normalized_fips}")
    normalized_domain = normalize_hpsa_domain(domain)
    if normalized_domain is None:
        return build_hpsa_response(row, include_legacy=True)

    quartile_row = fetch_hpsa_domain_quartiles(db, normalized_domain)
    ratio_fields = fetch_hpsa_domain_ratio_fields(
        db,
        county_fips=normalized_fips,
        domain=normalized_domain,
    )
    return build_hpsa_county_domain_detail(
        row=row,
        domain=normalized_domain,
        quartile_row=quartile_row,
        ratio_fields=ratio_fields,
    )
