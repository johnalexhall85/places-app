from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.cdc_funding_api import service
from app.cdc_funding_api.schemas import (
    CdcFundingAccountsResponse,
    CdcFundingCategoriesResponse,
    CdcFundingFiscalYearsResponse,
    CdcFundingOverviewResponse,
    CdcFundingObligationTrendsResponse,
    CdcFundingQuarterlyTrendsResponse,
    CdcFundingScope,
    CdcFundingTrendAccountsResponse,
    CdcFundingTrendAwardType,
    CdcFundingTrendEmergencyStatus,
    CdcFundingTrendMeasure,
    CdcFundingTrendPeriod,
    CdcFundingTrendView,
)
from app.db import get_db

router = APIRouter(prefix="/api/cdc-funding/v1", tags=["cdc-funding-v1"])


@router.get(
    "/fiscal-years",
    response_model=CdcFundingFiscalYearsResponse,
    summary="List available CDC funding fiscal years",
    description=(
        "Returns fiscal years with a completed import run and current annual account-summary rows. "
        "Data are sourced only from the ingested CDC funding import-run and annual account tables."
    ),
)
def get_fiscal_years(
    scope: CdcFundingScope = Query(default=CdcFundingScope.all_accounts),
    db: Session = Depends(get_db),
) -> CdcFundingFiscalYearsResponse:
    return service.list_fiscal_years(db, scope=scope)


@router.get(
    "/overview",
    response_model=CdcFundingOverviewResponse,
    response_model_exclude_none=True,
    summary="Summarize CDC funding obligations by annual classification",
    description=(
        "Returns emergency/nonemergency and grant/contract annual obligations. "
        "When fiscal_year is omitted, the latest completed fiscal year is used. "
        "Money and percentages are returned as fixed-precision decimal strings. "
        "Negative obligations are retained. Monthly, quarterly, category, geography, and award-level "
        "drilldowns are outside this API version."
    ),
)
def get_overview(
    fiscal_year: int | None = Query(default=None),
    scope: CdcFundingScope = Query(default=CdcFundingScope.all_accounts),
    db: Session = Depends(get_db),
) -> CdcFundingOverviewResponse:
    return service.get_overview(db, fiscal_year=fiscal_year, scope=scope)


@router.get(
    "/accounts",
    response_model=CdcFundingAccountsResponse,
    response_model_exclude_none=True,
    summary="List CDC funding obligations by federal account",
    description=(
        "Returns one annual row per federal account symbol, with emergency/nonemergency and "
        "grant/contract breakdowns from the ingested annual account-summary table only. "
        "Account identity is based on federal account symbol. Existing CDC Funding Map data are not used."
    ),
)
def get_accounts(
    fiscal_year: int | None = Query(default=None),
    scope: CdcFundingScope = Query(default=CdcFundingScope.all_accounts),
    db: Session = Depends(get_db),
) -> CdcFundingAccountsResponse:
    return service.get_accounts(db, fiscal_year=fiscal_year, scope=scope)


@router.get(
    "/obligation-trends",
    response_model=CdcFundingObligationTrendsResponse,
    response_model_exclude_none=True,
    summary="Compare monthly or quarterly CDC obligations or outlays",
    description=(
        "Obligations use stored fiscal reporting-period activity. Outlays use stored fiscal-year-beginning-"
        "to-period-end snapshots and derive period activity by differencing consecutive snapshots. "
        "Set exclude_deobligations=true only for obligations."
    ),
)
def get_obligation_trends(
    scope: CdcFundingScope = Query(default=CdcFundingScope.all_accounts),
    period: CdcFundingTrendPeriod = Query(default=CdcFundingTrendPeriod.month),
    view: CdcFundingTrendView = Query(default=CdcFundingTrendView.total),
    federal_account_symbol: str | None = Query(default=None),
    emergency_status: CdcFundingTrendEmergencyStatus = Query(default=CdcFundingTrendEmergencyStatus.all),
    award_type: CdcFundingTrendAwardType = Query(default=CdcFundingTrendAwardType.all),
    exclude_deobligations: bool = Query(default=False),
    measure: CdcFundingTrendMeasure = Query(default=CdcFundingTrendMeasure.obligations),
    db: Session = Depends(get_db),
) -> CdcFundingObligationTrendsResponse:
    return service.get_obligation_trends(
        db,
        scope=scope,
        period=period,
        view=view,
        federal_account_symbol=federal_account_symbol,
        emergency_status=emergency_status,
        award_type=award_type,
        exclude_deobligations=exclude_deobligations,
        measure=measure,
    )


@router.get(
    "/quarterly-trends",
    response_model=CdcFundingQuarterlyTrendsResponse,
    response_model_exclude_none=True,
    summary="Compare cumulative quarterly CDC funding across fiscal years",
    description=(
        "Uses all-account quarterly summaries. Obligations accumulate quarterly activity; outlays use each "
        "stored fiscal-year-beginning-to-period-end snapshot and derive activity by differencing snapshots."
    ),
)
def get_quarterly_trends(
    scope: CdcFundingScope = Query(default=CdcFundingScope.all_accounts),
    measure: CdcFundingTrendMeasure = Query(default=CdcFundingTrendMeasure.obligations),
    view: CdcFundingTrendView = Query(default=CdcFundingTrendView.total),
    federal_account_symbol: str | None = Query(default=None),
    emergency_status: CdcFundingTrendEmergencyStatus = Query(default=CdcFundingTrendEmergencyStatus.all),
    award_type: CdcFundingTrendAwardType = Query(default=CdcFundingTrendAwardType.all),
    db: Session = Depends(get_db),
) -> CdcFundingQuarterlyTrendsResponse:
    return service.get_quarterly_trends(
        db,
        scope=scope,
        measure=measure,
        view=view,
        federal_account_symbol=federal_account_symbol,
        emergency_status=emergency_status,
        award_type=award_type,
    )


@router.get(
    "/quarterly-trends/accounts",
    response_model=CdcFundingTrendAccountsResponse,
    response_model_exclude_none=True,
    summary="List cross-year federal account options for quarterly trends",
)
def get_quarterly_trend_accounts(
    scope: CdcFundingScope = Query(default=CdcFundingScope.all_accounts),
    db: Session = Depends(get_db),
) -> CdcFundingTrendAccountsResponse:
    return service.get_trend_accounts(db, scope=scope)


@router.get(
    "/categories",
    response_model=CdcFundingCategoriesResponse,
    response_model_exclude_none=True,
    summary="List CDC funding obligations by CDC Funding Profile category",
    description=(
        "Returns one annual row per CDC Funding Profile budget category. "
        "Rows are aggregated from mapped account-summary classification combinations only, using "
        "fiscal year, federal account symbol, emergency status, and grant/contract type as the mapping key. "
        "The endpoint supports only scope=cdc_funding_profiles."
    ),
)
def get_categories(
    fiscal_year: int | None = Query(default=None),
    scope: CdcFundingScope = Query(default=CdcFundingScope.cdc_funding_profiles),
    db: Session = Depends(get_db),
) -> CdcFundingCategoriesResponse:
    return service.get_categories(db, fiscal_year=fiscal_year, scope=scope)
