from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.cdc_funding import services
from app.db import get_db

router = APIRouter(prefix="/api/cdc/funding", tags=["cdc-funding"])


@router.get("/map")
def get_cdc_funding_map(
    basis: Literal["prime", "subaward"] = Query(default="prime"),
    geography: Literal["state", "county"] = Query(default="county"),
    metric: str = Query(default="total_funding"),
    assistance_type: str | None = Query(default=None),
    fiscal_year: int | None = Query(default=None),
    awarding_office: str | None = Query(default=None),
    funding_office: str | None = Query(default=None),
    office: str | None = Query(default=None),
    center: str | None = Query(default=None),
    state: str | None = Query(default=None),
    bbox: str | None = Query(default=None),
    zoom: int = Query(default=6),
    limit: int = Query(default=6000, ge=1, le=50000),
    db: Session = Depends(get_db),
):
    office_value = str(office or "").strip() or None
    awarding_office_value = str(awarding_office or "").strip() or office_value
    funding_office_value = str(funding_office or "").strip() or office_value
    return services.fetch_map_geojson(
        db,
        basis=basis,
        geography=geography,
        metric=metric,
        assistance_type=assistance_type,
        fiscal_year=fiscal_year,
        awarding_office=awarding_office_value,
        funding_office=funding_office_value,
        center=center,
        state=state,
        bbox=bbox,
        zoom=zoom,
        limit=limit,
    )


@router.get("/legend")
def get_cdc_funding_legend(
    basis: Literal["prime", "subaward"] = Query(default="prime"),
    geography: Literal["state", "county"] = Query(default="county"),
    metric: str = Query(default="total_funding"),
    assistance_type: str | None = Query(default=None),
    fiscal_year: int | None = Query(default=None),
    awarding_office: str | None = Query(default=None),
    funding_office: str | None = Query(default=None),
    office: str | None = Query(default=None),
    center: str | None = Query(default=None),
    state: str | None = Query(default=None),
    bbox: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    office_value = str(office or "").strip() or None
    awarding_office_value = str(awarding_office or "").strip() or office_value
    funding_office_value = str(funding_office or "").strip() or office_value
    return services.fetch_legend_stats(
        db,
        basis=basis,
        geography=geography,
        metric=metric,
        assistance_type=assistance_type,
        fiscal_year=fiscal_year,
        awarding_office=awarding_office_value,
        funding_office=funding_office_value,
        center=center,
        state=state,
        bbox=bbox,
    )


@router.get("/filters")
def get_cdc_funding_filters(
    basis: Literal["all", "prime", "subaward"] = Query(default="all"),
    db: Session = Depends(get_db),
):
    return services.list_filter_options(db, basis=basis)


@router.get("/search")
def search_cdc_funding(
    q: str | None = Query(default=None),
    basis: Literal["all", "prime", "subaward"] = Query(default="all"),
    assistance_type: str | None = Query(default=None),
    fiscal_year: int | None = Query(default=None),
    state: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return services.search_awards(
        db,
        q=q,
        basis=basis,
        assistance_type=assistance_type,
        fiscal_year=fiscal_year,
        state=state,
        page=page,
        page_size=page_size,
    )


@router.get("/detail")
def get_cdc_funding_detail(
    prime_unique_key: str | None = Query(default=None),
    subaward_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    payload = services.fetch_detail(
        db,
        prime_unique_key=prime_unique_key,
        subaward_id=subaward_id,
    )
    if payload is None:
        if prime_unique_key:
            raise HTTPException(status_code=404, detail=f"No CDC prime award for unique_key={prime_unique_key}")
        raise HTTPException(status_code=404, detail=f"No CDC subaward for id={subaward_id}")
    return payload


@router.get("/top")
def get_cdc_funding_top(
    basis: Literal["prime", "subaward"] = Query(default="prime"),
    geography: Literal["state", "county"] = Query(default="county"),
    geography_id: str = Query(..., min_length=1),
    metric: str = Query(default="total_funding"),
    assistance_type: str | None = Query(default=None),
    fiscal_year: int | None = Query(default=None),
    awarding_office: str | None = Query(default=None),
    funding_office: str | None = Query(default=None),
    office: str | None = Query(default=None),
    center: str | None = Query(default=None),
    limit: int = Query(default=5, ge=1, le=50),
    db: Session = Depends(get_db),
):
    office_value = str(office or "").strip() or None
    awarding_office_value = str(awarding_office or "").strip() or office_value
    funding_office_value = str(funding_office or "").strip() or office_value
    return services.fetch_top_awards(
        db,
        basis=basis,
        geography=geography,
        geography_id=geography_id,
        metric=metric,
        assistance_type=assistance_type,
        fiscal_year=fiscal_year,
        awarding_office=awarding_office_value,
        funding_office=funding_office_value,
        center=center,
        limit=limit,
    )
