from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, ConfigDict


class CdcFundingScope(str, Enum):
    all_accounts = "all_accounts"
    cdc_funding_profiles = "cdc_funding_profiles"


class CdcFundingTrendMeasure(str, Enum):
    obligations = "obligations"
    outlays = "outlays"


class CdcFundingTrendPeriod(str, Enum):
    month = "month"
    quarter = "quarter"


class CdcFundingTrendView(str, Enum):
    total = "total"
    federal_account = "federal_account"


class CdcFundingTrendEmergencyStatus(str, Enum):
    all = "all"
    emergency = "emergency"
    nonemergency = "nonemergency"


class CdcFundingTrendAwardType(str, Enum):
    all = "all"
    grant = "grant"
    contract = "contract"


class CdcFundingFiscalYear(BaseModel):
    fiscal_year: int
    is_latest: bool


class CdcFundingFiscalYearsResponse(BaseModel):
    scope: CdcFundingScope
    fiscal_years: list[CdcFundingFiscalYear]
    latest_fiscal_year: int | None


class CdcFundingOverviewClassification(BaseModel):
    emergency_status: str
    award_type: str
    label: str
    obligations: str
    percent_of_total: str


class CdcFundingOverviewTotals(BaseModel):
    emergency: str
    nonemergency: str
    grants: str
    contracts: str


class CdcFundingReconciliation(BaseModel):
    classification_sum: str | None = None
    account_total: str | None = None
    category_total: str | None = None
    overview_total: str | None = None
    difference: str

    model_config = ConfigDict(exclude_none=True)


class CdcFundingOverviewResponse(BaseModel):
    fiscal_year: int
    scope: CdcFundingScope
    total_obligations: str
    classifications: list[CdcFundingOverviewClassification]
    totals: CdcFundingOverviewTotals
    reconciliation: CdcFundingReconciliation


class CdcFundingAccountBreakdown(BaseModel):
    emergency_grants: str
    emergency_contracts: str
    nonemergency_grants: str
    nonemergency_contracts: str


class CdcFundingAccount(BaseModel):
    federal_account_symbol: str
    federal_account_name: str | None
    total_obligations: str
    emergency_obligations: str
    nonemergency_obligations: str
    emergency_share: str | None
    breakdown: CdcFundingAccountBreakdown


class CdcFundingAccountsResponse(BaseModel):
    fiscal_year: int
    scope: CdcFundingScope
    total_accounts: int
    accounts: list[CdcFundingAccount]
    reconciliation: CdcFundingReconciliation


class CdcFundingCategoryBreakdown(BaseModel):
    emergency_grants: str
    emergency_contracts: str
    nonemergency_grants: str
    nonemergency_contracts: str


class CdcFundingCategory(BaseModel):
    category: str
    total_obligations: str
    emergency_obligations: str
    nonemergency_obligations: str
    grant_obligations: str
    contract_obligations: str
    emergency_share: str | None
    mapped_account_combination_count: int | None = None
    breakdown: CdcFundingCategoryBreakdown

    model_config = ConfigDict(exclude_none=True)


class CdcFundingCategoriesResponse(BaseModel):
    fiscal_year: int
    scope: CdcFundingScope
    total_categories: int
    categories: list[CdcFundingCategory]
    reconciliation: CdcFundingReconciliation


class CdcFundingTrendFilters(BaseModel):
    federal_account_symbol: str | None
    emergency_status: CdcFundingTrendEmergencyStatus
    award_type: CdcFundingTrendAwardType
    exclude_deobligations: bool = False


class CdcFundingTrendPoint(BaseModel):
    quarter: str
    quarter_number: int
    available: bool
    quarter_amount: str | None
    cumulative_amount: str | None


class CdcFundingTrendReconciliation(BaseModel):
    latest_available_cumulative: str
    annual_or_current_ytd_total: str
    difference: str


class CdcFundingTrendSeries(BaseModel):
    fiscal_year: int
    available_through_quarter: str | None
    is_complete: bool
    latest_submission_period: str | None = None
    has_activity: bool
    points: list[CdcFundingTrendPoint]
    reconciliation: CdcFundingTrendReconciliation


class CdcFundingQuarterlyTrendsResponse(BaseModel):
    scope: CdcFundingScope
    measure: CdcFundingTrendMeasure
    view: CdcFundingTrendView
    calculation: str = "cumulative_fiscal_year_to_date"
    filters: CdcFundingTrendFilters
    available_fiscal_years: list[int]
    series: list[CdcFundingTrendSeries]


class CdcFundingTrendAccountOption(BaseModel):
    federal_account_symbol: str
    federal_account_name: str | None
    first_fiscal_year: int
    last_fiscal_year: int


class CdcFundingTrendAccountsResponse(BaseModel):
    scope: CdcFundingScope
    accounts: list[CdcFundingTrendAccountOption]


class CdcFundingObligationTrendPoint(BaseModel):
    period: str
    period_type: CdcFundingTrendPeriod
    period_number: int
    available: bool
    period_amount: str | None
    cumulative_amount: str | None
    submission_period: str | None = None
    source_period_label: str | None = None

    model_config = ConfigDict(exclude_none=True)


class CdcFundingObligationTrendSeries(BaseModel):
    fiscal_year: int
    available_through_period: str | None
    available_through_month: str | None = None
    available_through_quarter: str | None = None
    is_complete: bool
    latest_submission_period: str | None = None
    has_activity: bool
    points: list[CdcFundingObligationTrendPoint]
    reconciliation: CdcFundingTrendReconciliation

    model_config = ConfigDict(exclude_none=True)


class CdcFundingObligationTrendsResponse(BaseModel):
    scope: CdcFundingScope
    measure: CdcFundingTrendMeasure = CdcFundingTrendMeasure.obligations
    period: CdcFundingTrendPeriod
    view: CdcFundingTrendView
    calculation: str = "cumulative_fiscal_year_to_date"
    filters: CdcFundingTrendFilters
    available_fiscal_years: list[int]
    series: list[CdcFundingObligationTrendSeries]
