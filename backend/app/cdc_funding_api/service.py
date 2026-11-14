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
    CdcFundingObligationTrendPoint,
    CdcFundingObligationTrendSeries,
    CdcFundingObligationTrendsResponse,
    CdcFundingQuarterlyTrendsResponse,
    CdcFundingReconciliation,
    CdcFundingScope,
    CdcFundingTrendAccountOption,
    CdcFundingTrendAccountsResponse,
    CdcFundingTrendAwardType,
    CdcFundingTrendEmergencyStatus,
    CdcFundingTrendFilters,
    CdcFundingTrendMeasure,
    CdcFundingTrendPeriod,
    CdcFundingTrendPoint,
    CdcFundingTrendReconciliation,
    CdcFundingTrendSeries,
    CdcFundingTrendView,
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

FISCAL_MONTHS = (
    "Oct",
    "Nov",
    "Dec",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
)
SOURCE_PERIOD_MONTH_NUMBERS = {
    "October-November (combined P01/P02 submission)": 2,
    "December": 3,
    "January": 4,
    "February": 5,
    "March": 6,
    "April": 7,
    "May": 8,
    "June": 9,
    "July": 10,
    "August": 11,
    "September": 12,
}


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


def _trend_validation_error(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": code, "message": message})


def _trend_account_not_found(symbol: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "cdc_funding_account_not_found",
            "message": f'Federal account symbol "{symbol}" is not available in CDC funding trend data.',
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


def get_quarterly_trends(
    db: Session,
    *,
    scope: CdcFundingScope = CdcFundingScope.all_accounts,
    measure: CdcFundingTrendMeasure = CdcFundingTrendMeasure.obligations,
    view: CdcFundingTrendView = CdcFundingTrendView.total,
    federal_account_symbol: str | None = None,
    emergency_status: CdcFundingTrendEmergencyStatus = CdcFundingTrendEmergencyStatus.all,
    award_type: CdcFundingTrendAwardType = CdcFundingTrendAwardType.all,
) -> CdcFundingQuarterlyTrendsResponse:
    if scope != CdcFundingScope.all_accounts:
        raise _scope_validation_error("Quarterly trends support only scope=all_accounts.")
    symbol = (federal_account_symbol or "").strip() or None
    if view == CdcFundingTrendView.federal_account and symbol is None:
        raise _trend_validation_error(
            "cdc_funding_account_required",
            "federal_account_symbol is required when view=federal_account.",
        )
    if view == CdcFundingTrendView.total and symbol is not None:
        raise _trend_validation_error(
            "cdc_funding_account_not_allowed",
            "federal_account_symbol is not accepted when view=total.",
        )
    if symbol is not None and not repository.trend_account_exists(db, symbol):
        raise _trend_account_not_found(symbol)

    coverage_rows = repository.fetch_trend_quarter_coverage(db)
    coverage: dict[int, set[str]] = {}
    for row in coverage_rows:
        coverage.setdefault(int(row["fiscal_year"]), set()).add(str(row["fiscal_quarter"]))
    years = sorted(coverage)
    quarterly_rows = repository.fetch_quarterly_trend_rows(
        db,
        measure=measure.value,
        federal_account_symbol=symbol,
        emergency_status=emergency_status.value,
        award_type=award_type.value,
    )
    annual_rows = repository.fetch_annual_trend_rows(
        db,
        measure=measure.value,
        federal_account_symbol=symbol,
        emergency_status=emergency_status.value,
        award_type=award_type.value,
    )
    quarterly = {
        (int(row["fiscal_year"]), str(row["fiscal_quarter"])): row
        for row in quarterly_rows
    }
    annual = {int(row["fiscal_year"]): row for row in annual_rows}
    quarter_labels = ("Q1", "Q2", "Q3", "Q4")
    series: list[CdcFundingTrendSeries] = []

    for year in years:
        available_quarters = coverage[year]
        latest_number = max(
            (index for index, quarter in enumerate(quarter_labels, start=1) if quarter in available_quarters),
            default=0,
        )
        cumulative = ZERO_MONEY
        prior_outlay = ZERO_MONEY
        has_activity = False
        points: list[CdcFundingTrendPoint] = []
        for quarter_number, quarter in enumerate(quarter_labels, start=1):
            if quarter not in available_quarters:
                points.append(
                    CdcFundingTrendPoint(
                        quarter=quarter,
                        quarter_number=quarter_number,
                        available=False,
                        quarter_amount=None,
                        cumulative_amount=None,
                    )
                )
                continue
            row = quarterly.get((year, quarter))
            if row and int(row.get("matched_row_count") or 0) != int(row.get("numeric_amount_rows") or 0):
                logger.error(
                    "CDC funding trend source completeness failed fiscal_year=%s quarter=%s measure=%s "
                    "view=%s account=%s emergency=%s award_type=%s matched_rows=%s numeric_rows=%s",
                    year,
                    quarter,
                    measure.value,
                    view.value,
                    symbol,
                    emergency_status.value,
                    award_type.value,
                    row.get("matched_row_count"),
                    row.get("numeric_amount_rows"),
                )
                raise _internal_error("CDC funding trend source values are incomplete.")
            amount = _money(row.get("amount") if row else None)
            if measure == CdcFundingTrendMeasure.obligations:
                quarter_amount = amount
                cumulative = (cumulative + quarter_amount).quantize(MONEY_QUANT)
            else:
                cumulative = amount
                quarter_amount = (cumulative - prior_outlay).quantize(MONEY_QUANT)
                prior_outlay = cumulative
            has_activity = has_activity or quarter_amount != ZERO_MONEY or cumulative != ZERO_MONEY
            points.append(
                CdcFundingTrendPoint(
                    quarter=quarter,
                    quarter_number=quarter_number,
                    available=True,
                    quarter_amount=_money_string(quarter_amount),
                    cumulative_amount=_money_string(cumulative),
                )
            )

        annual_row = annual.get(year)
        if annual_row and int(annual_row.get("matched_row_count") or 0) != int(
            annual_row.get("numeric_amount_rows") or 0
        ):
            raise _internal_error("CDC funding annual trend source values are incomplete.")
        expected = _money(annual_row.get("amount") if annual_row else None)
        difference = (cumulative - expected).quantize(MONEY_QUANT)
        if difference != ZERO_MONEY:
            logger.error(
                "CDC funding trend reconciliation failed fiscal_year=%s measure=%s view=%s account=%s "
                "emergency=%s award_type=%s expected=%s actual=%s difference=%s",
                year,
                measure.value,
                view.value,
                symbol,
                emergency_status.value,
                award_type.value,
                expected,
                cumulative,
                difference,
            )
            raise _internal_error("CDC funding quarterly trend reconciliation failed.")
        latest_quarter = quarter_labels[latest_number - 1] if latest_number else None
        series.append(
            CdcFundingTrendSeries(
                fiscal_year=year,
                available_through_quarter=latest_quarter,
                is_complete=latest_number == 4,
                latest_submission_period=f"FY{year}P{latest_number * 3:02d}" if latest_number else None,
                has_activity=has_activity,
                points=points,
                reconciliation=CdcFundingTrendReconciliation(
                    latest_available_cumulative=_money_string(cumulative),
                    annual_or_current_ytd_total=_money_string(expected),
                    difference=_money_string(difference),
                ),
            )
        )

    return CdcFundingQuarterlyTrendsResponse(
        scope=scope,
        measure=measure,
        view=view,
        filters=CdcFundingTrendFilters(
            federal_account_symbol=symbol,
            emergency_status=emergency_status,
            award_type=award_type,
        ),
        available_fiscal_years=years,
        series=series,
    )


def get_trend_accounts(
    db: Session,
    *,
    scope: CdcFundingScope = CdcFundingScope.all_accounts,
) -> CdcFundingTrendAccountsResponse:
    if scope != CdcFundingScope.all_accounts:
        raise _scope_validation_error("Quarterly trend accounts support only scope=all_accounts.")
    return CdcFundingTrendAccountsResponse(
        scope=scope,
        accounts=[
            CdcFundingTrendAccountOption(
                federal_account_symbol=str(row["federal_account_symbol"]),
                federal_account_name=row.get("federal_account_name"),
                first_fiscal_year=int(row["first_fiscal_year"]),
                last_fiscal_year=int(row["last_fiscal_year"]),
            )
            for row in repository.fetch_trend_account_options(db)
        ],
    )


def _monthly_coverage(
    rows: list[dict[str, Any]],
) -> dict[int, dict[int, dict[str, Any]]]:
    coverage: dict[int, dict[int, dict[str, Any]]] = {}
    for row in rows:
        year = int(row["fiscal_year"])
        period_label = str(row.get("period_label") or "").strip()
        month_number = SOURCE_PERIOD_MONTH_NUMBERS.get(period_label)
        submission_period = str(row.get("submission_period") or "").strip()
        fiscal_quarter = str(row.get("fiscal_quarter") or "").strip()
        expected_submission = (
            f"FY{year}P{month_number:02d}" if month_number is not None else None
        )
        expected_quarter = (
            f"Q{((month_number - 1) // 3) + 1}"
            if month_number is not None
            else None
        )
        if (
            month_number is None
            or submission_period != expected_submission
            or fiscal_quarter != expected_quarter
        ):
            logger.error(
                "CDC funding monthly period mapping failed fiscal_year=%s submission_period=%s "
                "period_label=%s fiscal_quarter=%s",
                year,
                submission_period,
                period_label,
                fiscal_quarter,
            )
            raise _internal_error("CDC funding monthly period mapping is inconsistent.")
        if month_number in coverage.setdefault(year, {}):
            raise _internal_error("CDC funding monthly period coverage contains duplicates.")
        coverage[year][month_number] = dict(row)
    return coverage


def get_obligation_trends(
    db: Session,
    *,
    scope: CdcFundingScope = CdcFundingScope.all_accounts,
    period: CdcFundingTrendPeriod = CdcFundingTrendPeriod.month,
    view: CdcFundingTrendView = CdcFundingTrendView.total,
    federal_account_symbol: str | None = None,
    emergency_status: CdcFundingTrendEmergencyStatus = CdcFundingTrendEmergencyStatus.all,
    award_type: CdcFundingTrendAwardType = CdcFundingTrendAwardType.all,
    exclude_deobligations: bool = False,
    measure: CdcFundingTrendMeasure = CdcFundingTrendMeasure.obligations,
) -> CdcFundingObligationTrendsResponse:
    if isinstance(measure, str):
        try:
            measure = CdcFundingTrendMeasure(measure)
        except ValueError as exc:
            raise _trend_validation_error(
                "cdc_funding_measure_not_supported",
                "Funding measure must be obligations or outlays.",
            ) from exc
    if measure == CdcFundingTrendMeasure.outlays and exclude_deobligations:
        raise _trend_validation_error(
            "cdc_funding_deobligations_not_supported_for_outlays",
            "Deobligation filtering applies to obligations only.",
        )
    if scope != CdcFundingScope.all_accounts:
        raise _scope_validation_error("Obligation trends support only scope=all_accounts.")
    symbol = (federal_account_symbol or "").strip() or None
    if view == CdcFundingTrendView.federal_account and symbol is None:
        raise _trend_validation_error(
            "cdc_funding_account_required",
            "federal_account_symbol is required when view=federal_account.",
        )
    if view == CdcFundingTrendView.total and symbol is not None:
        raise _trend_validation_error(
            "cdc_funding_account_not_allowed",
            "federal_account_symbol is not accepted when view=total.",
        )
    if symbol is not None and not repository.trend_account_exists(db, symbol):
        raise _trend_account_not_found(symbol)

    monthly_coverage = _monthly_coverage(repository.fetch_trend_month_coverage(db))
    years = sorted(monthly_coverage)
    if period == CdcFundingTrendPeriod.month:
        period_labels = FISCAL_MONTHS
        coverage = {
            year: set(year_coverage)
            for year, year_coverage in monthly_coverage.items()
        }
        if exclude_deobligations:
            source_rows = repository.fetch_positive_obligation_trend_rows(
                db,
                period=period.value,
                federal_account_symbol=symbol,
                emergency_status=emergency_status.value,
                award_type=award_type.value,
            )
        elif measure == CdcFundingTrendMeasure.obligations:
            source_rows = repository.fetch_monthly_obligation_trend_rows(
                db,
                federal_account_symbol=symbol,
                emergency_status=emergency_status.value,
                award_type=award_type.value,
            )
        else:
            source_rows = repository.fetch_monthly_trend_rows(
                db,
                measure=measure.value,
                federal_account_symbol=symbol,
                emergency_status=emergency_status.value,
                award_type=award_type.value,
            )
        source_by_period: dict[tuple[int, int], dict[str, Any]] = {}
        for row in source_rows:
            source_label = str(row.get("period_label") or "").strip()
            month_number = SOURCE_PERIOD_MONTH_NUMBERS.get(source_label)
            if month_number is None:
                raise _internal_error("CDC funding monthly period mapping is inconsistent.")
            source_by_period[(int(row["fiscal_year"]), month_number)] = row
    else:
        period_labels = ("Q1", "Q2", "Q3", "Q4")
        quarter_rows = repository.fetch_trend_quarter_coverage(db)
        coverage: dict[int, set[int]] = {year: set() for year in years}
        for row in quarter_rows:
            quarter = str(row["fiscal_quarter"])
            if quarter not in period_labels:
                raise _internal_error("CDC funding quarterly period mapping is inconsistent.")
            coverage.setdefault(int(row["fiscal_year"]), set()).add(period_labels.index(quarter) + 1)
        if exclude_deobligations:
            source_rows = repository.fetch_positive_obligation_trend_rows(
                db,
                period=period.value,
                federal_account_symbol=symbol,
                emergency_status=emergency_status.value,
                award_type=award_type.value,
            )
        else:
            source_rows = repository.fetch_quarterly_trend_rows(
                db,
                measure=measure.value,
                federal_account_symbol=symbol,
                emergency_status=emergency_status.value,
                award_type=award_type.value,
            )
        source_by_period = {
            (
                int(row["fiscal_year"]),
                period_labels.index(str(row["fiscal_quarter"])) + 1,
            ): row
            for row in source_rows
        }

    if exclude_deobligations:
        annual_rows = repository.fetch_positive_annual_obligation_trend_rows(
            db,
            federal_account_symbol=symbol,
            emergency_status=emergency_status.value,
            award_type=award_type.value,
        )
    else:
        annual_rows = repository.fetch_annual_trend_rows(
            db,
            measure=measure.value,
            federal_account_symbol=symbol,
            emergency_status=emergency_status.value,
            award_type=award_type.value,
        )
    annual = {int(row["fiscal_year"]): row for row in annual_rows}
    series: list[CdcFundingObligationTrendSeries] = []
    for year in years:
        available_periods = coverage.get(year, set())
        latest_number = max(available_periods, default=0)
        cumulative = ZERO_MONEY
        prior_outlay = ZERO_MONEY
        has_activity = False
        points: list[CdcFundingObligationTrendPoint] = []
        for period_number, period_label in enumerate(period_labels, start=1):
            if period_number not in available_periods:
                points.append(
                    CdcFundingObligationTrendPoint(
                        period=period_label,
                        period_type=period,
                        period_number=period_number,
                        available=False,
                        period_amount=None,
                        cumulative_amount=None,
                    )
                )
                continue
            row = source_by_period.get((year, period_number))
            if row and int(row.get("matched_row_count") or 0) != int(
                row.get("numeric_amount_rows") or 0
            ):
                raise _internal_error("CDC funding trend source values are incomplete.")
            source_amount = _money(row.get("amount") if row else None)
            if measure == CdcFundingTrendMeasure.obligations:
                period_amount = source_amount
                cumulative = (cumulative + period_amount).quantize(MONEY_QUANT)
            else:
                cumulative = source_amount
                period_amount = (cumulative - prior_outlay).quantize(MONEY_QUANT)
                prior_outlay = cumulative
            has_activity = has_activity or period_amount != ZERO_MONEY
            coverage_row = (
                monthly_coverage[year].get(period_number)
                if period == CdcFundingTrendPeriod.month
                else None
            )
            points.append(
                CdcFundingObligationTrendPoint(
                    period=period_label,
                    period_type=period,
                    period_number=period_number,
                    available=True,
                    period_amount=_money_string(period_amount),
                    cumulative_amount=_money_string(cumulative),
                    submission_period=coverage_row.get("submission_period") if coverage_row else None,
                    source_period_label=coverage_row.get("period_label") if coverage_row else None,
                )
            )

        annual_row = annual.get(year)
        if annual_row and int(annual_row.get("matched_row_count") or 0) != int(
            annual_row.get("numeric_amount_rows") or 0
        ):
            raise _internal_error("CDC funding annual trend source values are incomplete.")
        expected = _money(annual_row.get("amount") if annual_row else None)
        difference = (cumulative - expected).quantize(MONEY_QUANT)
        if difference != ZERO_MONEY:
            logger.error(
                "CDC funding trend reconciliation failed fiscal_year=%s period=%s measure=%s view=%s "
                "account=%s emergency=%s award_type=%s expected=%s actual=%s difference=%s",
                year,
                period.value,
                measure.value,
                view.value,
                symbol,
                emergency_status.value,
                award_type.value,
                expected,
                cumulative,
                difference,
            )
            raise _internal_error("CDC funding trend reconciliation failed.")
        latest_month_row = monthly_coverage[year].get(max(monthly_coverage[year], default=0))
        latest_submission = (
            latest_month_row.get("submission_period")
            if period == CdcFundingTrendPeriod.month and latest_month_row
            else f"FY{year}P{latest_number * 3:02d}"
            if latest_number
            else None
        )
        latest_label = period_labels[latest_number - 1] if latest_number else None
        series.append(
            CdcFundingObligationTrendSeries(
                fiscal_year=year,
                available_through_period=latest_label,
                available_through_month=(
                    FISCAL_MONTHS[max(monthly_coverage[year]) - 1]
                    if period == CdcFundingTrendPeriod.month
                    else None
                ),
                available_through_quarter=(
                    latest_label if period == CdcFundingTrendPeriod.quarter else None
                ),
                is_complete=latest_number == len(period_labels),
                latest_submission_period=latest_submission,
                has_activity=has_activity,
                points=points,
                reconciliation=CdcFundingTrendReconciliation(
                    latest_available_cumulative=_money_string(cumulative),
                    annual_or_current_ytd_total=_money_string(expected),
                    difference=_money_string(difference),
                ),
            )
        )

    return CdcFundingObligationTrendsResponse(
        scope=scope,
        measure=measure,
        period=period,
        view=view,
        filters=CdcFundingTrendFilters(
            federal_account_symbol=symbol,
            emergency_status=emergency_status,
            award_type=award_type,
            exclude_deobligations=exclude_deobligations,
        ),
        available_fiscal_years=years,
        series=series,
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
