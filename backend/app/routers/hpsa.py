from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.hpsa import HPSAChoroplethCountiesResponse
from app.services.hpsa_summary import (
    build_hpsa_counties_geojson_response,
    build_hpsa_choropleth_response,
    build_hpsa_county_domain_detail,
    build_hpsa_response,
    fetch_county_hpsa_row,
    fetch_hpsa_county_geojson_rows,
    fetch_hpsa_county_rows_for_domain,
    fetch_hpsa_domain_quartiles,
    fetch_hpsa_domain_ratio_fields,
    normalize_county_fips,
    normalize_hpsa_domain,
)

router = APIRouter(tags=["hpsa"])


def _ensure_hpsa_county_geojson_tables(db: Session) -> None:
    required = {
        "dim_county_boundary": "County boundaries not loaded. Run boundary ingest first.",
        "county_hpsa_summary": "HPSA county summary table not loaded. Run HPSA summary ingest first.",
    }
    for table_name, detail in required.items():
        exists = db.execute(
            text("SELECT to_regclass(:table_name) AS exists"),
            {"table_name": f"public.{table_name}"},
        ).mappings().one()["exists"]
        if exists is None:
            raise HTTPException(status_code=503, detail=detail)


def _parse_bbox(bbox: str | None) -> tuple[float, float, float, float] | None:
    if bbox is None:
        return None
    if not isinstance(bbox, str):
        return None
    try:
        minx, miny, maxx, maxy = (float(value) for value in bbox.split(","))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid bbox format") from exc
    if minx >= maxx or miny >= maxy:
        raise HTTPException(status_code=400, detail="Invalid bbox bounds")
    return (minx, miny, maxx, maxy)


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


@router.get("/hpsa/counties")
def get_hpsa_counties_geojson(
    domain: Literal["pc", "mh", "dh"] = Query(default="pc"),
    bbox: str | None = Query(default=None),
    simplify: float | None = Query(default=0.02, gt=0, le=0.5),
    limit: int = Query(default=5000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    normalized_domain = normalize_hpsa_domain(domain, default="pc")
    if normalized_domain is None:
        raise HTTPException(status_code=400, detail="domain must be one of pc, mh, dh")

    bbox_bounds = _parse_bbox(bbox)
    _ensure_hpsa_county_geojson_tables(db)

    quartile_row = fetch_hpsa_domain_quartiles(db, normalized_domain)
    county_rows = fetch_hpsa_county_geojson_rows(
        db,
        domain=normalized_domain,
        bbox_bounds=bbox_bounds,
        simplify=simplify,
        limit=limit,
        offset=offset,
    )
    return build_hpsa_counties_geojson_response(
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
