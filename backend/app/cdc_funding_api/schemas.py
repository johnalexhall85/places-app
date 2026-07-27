from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class CdcFundingScope(str, Enum):
    all_accounts = "all_accounts"
    cdc_funding_profiles = "cdc_funding_profiles"


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
