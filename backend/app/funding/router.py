from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.funding import services

router = APIRouter(prefix="/funding", tags=["funding"])
FundingViewMode = Literal["standard_usaspending", "funding_profiles_comparable"]
SupplementalHistoryFilter = Literal[
    "all",
    "only_awards_with_supplemental_history",
    "exclude_awards_with_supplemental_history",
]


@router.get("/filters")
def get_funding_filters(db: Session = Depends(get_db)):
    return services.fetch_filters(db)


@router.get("/map/state")
def get_state_funding_map(
    fiscal_year: str | None = Query(default=None),
    funding_mechanism: Literal["grants_cooperative_agreements", "contracts", "all"] = Query(
        default="grants_cooperative_agreements"
    ),
    include_supplemental: bool = Query(default=False),
    funding_view_mode: FundingViewMode = Query(default="standard_usaspending"),
    supplemental_history_filter: SupplementalHistoryFilter = Query(default="all"),
    state: str | None = Query(default=None),
    assistance_listing_number: str | None = Query(default=None),
    metric: Literal["total_obligations"] = Query(default="total_obligations"),
    db: Session = Depends(get_db),
):
    return services.fetch_state_map(
        db,
        fiscal_year=fiscal_year,
        funding_mechanism=funding_mechanism,
        include_supplemental=include_supplemental,
        funding_view_mode=funding_view_mode,
        supplemental_history_filter=supplemental_history_filter,
        state=state,
        assistance_listing_number=assistance_listing_number,
        metric=metric,
    )


@router.get("/summary")
def get_funding_summary(
    fiscal_year: str | None = Query(default=None),
    funding_mechanism: Literal["grants_cooperative_agreements", "contracts", "all"] = Query(
        default="grants_cooperative_agreements"
    ),
    include_supplemental: bool = Query(default=False),
    funding_view_mode: FundingViewMode = Query(default="standard_usaspending"),
    supplemental_history_filter: SupplementalHistoryFilter = Query(default="all"),
    state: str | None = Query(default=None),
    assistance_listing_number: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return services.fetch_summary(
        db,
        fiscal_year=fiscal_year,
        funding_mechanism=funding_mechanism,
        include_supplemental=include_supplemental,
        funding_view_mode=funding_view_mode,
        supplemental_history_filter=supplemental_history_filter,
        state=state,
        assistance_listing_number=assistance_listing_number,
    )


@router.get("/state/{state}/awards")
def get_state_awards(
    state: str,
    fiscal_year: str | None = Query(default=None),
    funding_mechanism: Literal["grants_cooperative_agreements", "contracts", "all"] = Query(
        default="grants_cooperative_agreements"
    ),
    include_supplemental: bool = Query(default=False),
    funding_view_mode: FundingViewMode = Query(default="standard_usaspending"),
    supplemental_history_filter: SupplementalHistoryFilter = Query(default="all"),
    assistance_listing_number: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return services.fetch_state_awards(
        db,
        state,
        fiscal_year=fiscal_year,
        funding_mechanism=funding_mechanism,
        include_supplemental=include_supplemental,
        funding_view_mode=funding_view_mode,
        supplemental_history_filter=supplemental_history_filter,
        assistance_listing_number=assistance_listing_number,
        limit=limit,
        offset=offset,
    )


@router.get("/validation")
def get_funding_validation(db: Session = Depends(get_db)):
    return services.fetch_validation(db)
