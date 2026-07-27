from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.cdc_funding_api import repository
from app.cdc_funding_api.schemas import (
    CdcFundingAccount,
    CdcFundingAccountBreakdown,
    CdcFundingAccountsResponse,
    CdcFundingCategoriesResponse,
    CdcFundingCategory,
    CdcFundingCategoryBreakdown,
    CdcFundingFiscalYear,
    CdcFundingFiscalYearsResponse,
    CdcFundingOverviewClassification,
    CdcFundingOverviewResponse,
    CdcFundingOverviewTotals,
    CdcFundingReconciliation,
    CdcFundingScope,
)

logger = logging.getLogger(__name__)

ZERO_MONEY = Decimal("0.00")
MONEY_QUANT = Decimal("0.01")
PERCENT_QUANT = Decimal("0.0001")

API_COMBINATIONS = [
    ("Emergency", "Grant", "emergency", "grant", "Emergency Grants"),
    ("Emergency", "Contract", "emergency", "contract", "Emergency Contracts"),
    ("NonEmergency", "Grant", "nonemergency", "grant", "Nonemergency Grants"),
    ("NonEmergency", "Contract", "nonemergency", "contract", "Nonemergency Contracts"),
]


class CdcFundingApiError(RuntimeError):
    pass


def _money(value: Decimal | int | None) -> Decimal:
    if value is None:
        return ZERO_MONEY
    if isinstance(value, Decimal):
        return value.quantize(MONEY_QUANT)
    return Decimal(value).quantize(MONEY_QUANT)


def _money_string(value: Decimal | int | None) -> str:
    return f"{_money(value):.2f}"


def _percent_string(numerator: Decimal, denominator: Decimal) -> str:
    if denominator == ZERO_MONEY:
        return "0.0000"
    value = (numerator / denominator * Decimal("100")).quantize(PERCENT_QUANT, rounding=ROUND_HALF_UP)
    return f"{value:.4f}"


def _optional_percent_string(numerator: Decimal, denominator: Decimal) -> str | None:
    if denominator == ZERO_MONEY:
        return None
    return _percent_string(numerator, denominator)


def _not_found(fiscal_year: int) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "cdc_funding_fiscal_year_not_found",
            "message": f"CDC funding data are not available for fiscal year {fiscal_year}.",
        },
    )


def _no_years_available() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "cdc_funding_no_fiscal_years_available",
            "message": "No completed CDC funding datasets are available.",
        },
    )


def _internal_error(message: str) -> HTTPException:
    return HTTPException(
        status_code=500,
        detail={
            "code": "cdc_funding_internal_reconciliation_error",
            "message": message,
        },
    )


def _scope_validation_error(message: str) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "code": "cdc_funding_scope_not_supported",
            "message": message,
        },
    )


def list_fiscal_years(
    db: Session,
    scope: CdcFundingScope = CdcFundingScope.all_accounts,
) -> CdcFundingFiscalYearsResponse:
    years = repository.list_completed_fiscal_years(db, scope=scope)
    latest = years[0] if years else None
    return CdcFundingFiscalYearsResponse(
        scope=scope,
        fiscal_years=[
            CdcFundingFiscalYear(fiscal_year=year, is_latest=(year == latest))
            for year in years
        ],
        latest_fiscal_year=latest,
    )


def resolve_fiscal_year(
    db: Session,
    fiscal_year: int | None,
    scope: CdcFundingScope = CdcFundingScope.all_accounts,
) -> int:
    years = repository.list_completed_fiscal_years(db, scope=scope)
    if fiscal_year is None:
        if not years:
            raise _no_years_available()
        return years[0]
    if fiscal_year not in years:
        raise _not_found(fiscal_year)
    return fiscal_year


def get_overview(
    db: Session,
    fiscal_year: int | None = None,
    scope: CdcFundingScope = CdcFundingScope.all_accounts,
) -> CdcFundingOverviewResponse:
    year = resolve_fiscal_year(db, fiscal_year, scope=scope)
    rows = repository.fetch_overview_rows(db, year, scope=scope)
    amounts = {
        (str(row.get("emergency") or ""), str(row.get("grant_or_contract") or "")): _money(row.get("obligations"))
        for row in rows
    }
    total = sum(amounts.values(), ZERO_MONEY).quantize(MONEY_QUANT)
    classifications: list[CdcFundingOverviewClassification] = []
    for source_emergency, source_type, api_emergency, api_type, label in API_COMBINATIONS:
        obligations = amounts.get((source_emergency, source_type), ZERO_MONEY)
        classifications.append(
            CdcFundingOverviewClassification(
                emergency_status=api_emergency,
                award_type=api_type,
                label=label,
                obligations=_money_string(obligations),
                percent_of_total=_percent_string(obligations, total),
            )
        )

    emergency_total = amounts.get(("Emergency", "Grant"), ZERO_MONEY) + amounts.get(("Emergency", "Contract"), ZERO_MONEY)
    nonemergency_total = amounts.get(("NonEmergency", "Grant"), ZERO_MONEY) + amounts.get(
        ("NonEmergency", "Contract"),
        ZERO_MONEY,
    )
    grant_total = amounts.get(("Emergency", "Grant"), ZERO_MONEY) + amounts.get(("NonEmergency", "Grant"), ZERO_MONEY)
    contract_total = amounts.get(("Emergency", "Contract"), ZERO_MONEY) + amounts.get(
        ("NonEmergency", "Contract"),
        ZERO_MONEY,
    )
    classification_sum = emergency_total + nonemergency_total
    difference = (classification_sum - total).quantize(MONEY_QUANT)
    if difference != ZERO_MONEY:
        logger.error(
            "CDC funding overview reconciliation failed fiscal_year=%s total=%s classification_sum=%s difference=%s",
            year,
            total,
            classification_sum,
            difference,
        )
        raise _internal_error("CDC funding overview reconciliation failed.")

    return CdcFundingOverviewResponse(
        fiscal_year=year,
        scope=scope,
        total_obligations=_money_string(total),
        classifications=classifications,
        totals=CdcFundingOverviewTotals(
            emergency=_money_string(emergency_total),
            nonemergency=_money_string(nonemergency_total),
            grants=_money_string(grant_total),
            contracts=_money_string(contract_total),
        ),
        reconciliation=CdcFundingReconciliation(
            classification_sum=_money_string(classification_sum),
            difference=_money_string(difference),
        ),
    )


def _raise_for_name_conflicts(conflicts: list[dict[str, Any]], fiscal_year: int) -> None:
    if not conflicts:
        return
    for conflict in conflicts:
        logger.error(
            "CDC funding account name conflict fiscal_year=%s federal_account_symbol=%s names=%s",
            fiscal_year,
            conflict.get("federal_account_symbol"),
            conflict.get("account_names"),
        )
    raise _internal_error("CDC funding account name consistency check failed.")


def _raise_for_category_mapping_conflicts(conflicts: list[dict[str, Any]], fiscal_year: int) -> None:
    if not conflicts:
        return
    for conflict in conflicts:
        logger.error(
            "CDC funding category mapping conflict fiscal_year=%s federal_account_symbol=%s "
            "grant_or_contract=%s emergency=%s categories=%s",
            fiscal_year,
            conflict.get("federal_account_symbol"),
            conflict.get("grant_or_contract"),
            conflict.get("emergency"),
            conflict.get("categories"),
        )
    raise _internal_error("CDC funding category mapping consistency check failed.")


def _raise_for_blank_category_mappings(rows: list[dict[str, Any]], fiscal_year: int) -> None:
    if not rows:
        return
    for row in rows:
        logger.error(
            "CDC funding blank category mapping fiscal_year=%s federal_account_symbol=%s "
            "grant_or_contract=%s emergency=%s",
            fiscal_year,
            row.get("federal_account_symbol"),
            row.get("grant_or_contract"),
            row.get("emergency"),
        )
    raise _internal_error("CDC funding category mapping label check failed.")


def get_accounts(
    db: Session,
    fiscal_year: int | None = None,
    scope: CdcFundingScope = CdcFundingScope.all_accounts,
) -> CdcFundingAccountsResponse:
    year = resolve_fiscal_year(db, fiscal_year, scope=scope)
    _raise_for_name_conflicts(repository.fetch_account_name_conflicts(db, year, scope=scope), year)
    rows = repository.fetch_account_rows(db, year, scope=scope)
    overview = get_overview(db, year, scope=scope)
    overview_total = _money(overview.total_obligations)

    accounts: list[CdcFundingAccount] = []
    account_total = ZERO_MONEY
    for row in rows:
        total = _money(row.get("total_obligations"))
        emergency = _money(row.get("emergency_obligations"))
        nonemergency = _money(row.get("nonemergency_obligations"))
        account_total += total
        accounts.append(
            CdcFundingAccount(
                federal_account_symbol=str(row.get("federal_account_symbol") or ""),
                federal_account_name=row.get("federal_account_name"),
                total_obligations=_money_string(total),
                emergency_obligations=_money_string(emergency),
                nonemergency_obligations=_money_string(nonemergency),
                emergency_share=_optional_percent_string(emergency, total),
                breakdown=CdcFundingAccountBreakdown(
                    emergency_grants=_money_string(row.get("emergency_grants")),
                    emergency_contracts=_money_string(row.get("emergency_contracts")),
                    nonemergency_grants=_money_string(row.get("nonemergency_grants")),
                    nonemergency_contracts=_money_string(row.get("nonemergency_contracts")),
                ),
            )
        )

    account_total = account_total.quantize(MONEY_QUANT)
    difference = (account_total - overview_total).quantize(MONEY_QUANT)
    if difference != ZERO_MONEY:
        logger.error(
            "CDC funding account reconciliation failed fiscal_year=%s overview_total=%s account_total=%s difference=%s",
            year,
            overview_total,
            account_total,
            difference,
        )
        raise _internal_error("CDC funding account reconciliation failed.")

    return CdcFundingAccountsResponse(
        fiscal_year=year,
        scope=scope,
        total_accounts=len(accounts),
        accounts=accounts,
        reconciliation=CdcFundingReconciliation(
            account_total=_money_string(account_total),
            overview_total=_money_string(overview_total),
            difference=_money_string(difference),
        ),
    )


def _raise_for_category_reconciliation(
    *,
    fiscal_year: int,
    label: str,
    expected: Decimal,
    actual: Decimal,
) -> None:
    difference = (actual - expected).quantize(MONEY_QUANT)
    if difference == ZERO_MONEY:
        return
    logger.error(
        "CDC funding category reconciliation failed fiscal_year=%s label=%s expected=%s actual=%s difference=%s",
        fiscal_year,
        label,
        expected,
        actual,
        difference,
    )
    raise _internal_error("CDC funding category reconciliation failed.")


def get_categories(
    db: Session,
    fiscal_year: int | None = None,
    scope: CdcFundingScope = CdcFundingScope.cdc_funding_profiles,
) -> CdcFundingCategoriesResponse:
    if scope != CdcFundingScope.cdc_funding_profiles:
        raise _scope_validation_error(
            "The CDC funding categories endpoint supports only scope=cdc_funding_profiles."
        )

    year = resolve_fiscal_year(db, fiscal_year, scope=CdcFundingScope.cdc_funding_profiles)
    _raise_for_category_mapping_conflicts(repository.fetch_category_mapping_conflicts(db, year), year)
    _raise_for_blank_category_mappings(repository.fetch_blank_category_mappings(db, year), year)

    rows = repository.fetch_category_rows(db, year)
    overview = get_overview(db, year, scope=CdcFundingScope.cdc_funding_profiles)
    overview_total = _money(overview.total_obligations)
    overview_emergency = _money(overview.totals.emergency)
    overview_nonemergency = _money(overview.totals.nonemergency)
    overview_grants = _money(overview.totals.grants)
    overview_contracts = _money(overview.totals.contracts)

    categories: list[CdcFundingCategory] = []
    category_total = ZERO_MONEY
    category_emergency = ZERO_MONEY
    category_nonemergency = ZERO_MONEY
    category_grants = ZERO_MONEY
    category_contracts = ZERO_MONEY

    for row in rows:
        category = str(row.get("category") or "")
        total = _money(row.get("total_obligations"))
        emergency = _money(row.get("emergency_obligations"))
        nonemergency = _money(row.get("nonemergency_obligations"))
        grants = _money(row.get("grant_obligations"))
        contracts = _money(row.get("contract_obligations"))
        category_total += total
        category_emergency += emergency
        category_nonemergency += nonemergency
        category_grants += grants
        category_contracts += contracts
        categories.append(
            CdcFundingCategory(
                category=category,
                total_obligations=_money_string(total),
                emergency_obligations=_money_string(emergency),
                nonemergency_obligations=_money_string(nonemergency),
                grant_obligations=_money_string(grants),
                contract_obligations=_money_string(contracts),
                emergency_share=_optional_percent_string(emergency, total),
                mapped_account_combination_count=int(row.get("mapped_account_combination_count") or 0),
                breakdown=CdcFundingCategoryBreakdown(
                    emergency_grants=_money_string(row.get("emergency_grants")),
                    emergency_contracts=_money_string(row.get("emergency_contracts")),
                    nonemergency_grants=_money_string(row.get("nonemergency_grants")),
                    nonemergency_contracts=_money_string(row.get("nonemergency_contracts")),
                ),
            )
        )

    category_total = category_total.quantize(MONEY_QUANT)
    category_emergency = category_emergency.quantize(MONEY_QUANT)
    category_nonemergency = category_nonemergency.quantize(MONEY_QUANT)
    category_grants = category_grants.quantize(MONEY_QUANT)
    category_contracts = category_contracts.quantize(MONEY_QUANT)

    _raise_for_category_reconciliation(
        fiscal_year=year,
        label="total",
        expected=overview_total,
        actual=category_total,
    )
    _raise_for_category_reconciliation(
        fiscal_year=year,
        label="emergency",
        expected=overview_emergency,
        actual=category_emergency,
    )
    _raise_for_category_reconciliation(
        fiscal_year=year,
        label="nonemergency",
        expected=overview_nonemergency,
        actual=category_nonemergency,
    )
    _raise_for_category_reconciliation(
        fiscal_year=year,
        label="grants",
        expected=overview_grants,
        actual=category_grants,
    )
    _raise_for_category_reconciliation(
        fiscal_year=year,
        label="contracts",
        expected=overview_contracts,
        actual=category_contracts,
    )

    difference = (category_total - overview_total).quantize(MONEY_QUANT)
    return CdcFundingCategoriesResponse(
        fiscal_year=year,
        scope=CdcFundingScope.cdc_funding_profiles,
        total_categories=len(categories),
        categories=categories,
        reconciliation=CdcFundingReconciliation(
            category_total=_money_string(category_total),
            overview_total=_money_string(overview_total),
            difference=_money_string(difference),
        ),
    )
