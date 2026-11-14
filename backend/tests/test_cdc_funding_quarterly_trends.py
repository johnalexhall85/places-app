from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.cdc_funding_api import repository, router, service
from app.db import get_db
from app.cdc_funding_api.schemas import (
    CdcFundingScope,
    CdcFundingTrendMeasure,
    CdcFundingTrendPeriod,
    CdcFundingTrendView,
)


def _install_rows(
    monkeypatch: pytest.MonkeyPatch,
    *,
    quarterly_amounts: list[str],
    annual_amount: str,
    quarters: int = 4,
) -> None:
    monkeypatch.setattr(
        repository,
        "fetch_trend_quarter_coverage",
        lambda db: [
            {"fiscal_year": 2026, "fiscal_quarter": f"Q{quarter}"}
            for quarter in range(1, quarters + 1)
        ],
    )
    monkeypatch.setattr(
        repository,
        "fetch_quarterly_trend_rows",
        lambda db, **kwargs: [
            {
                "fiscal_year": 2026,
                "fiscal_quarter": f"Q{quarter}",
                "matched_row_count": 1,
                "numeric_amount_rows": 1,
                "amount": Decimal(amount),
            }
            for quarter, amount in enumerate(quarterly_amounts, start=1)
        ],
    )
    monkeypatch.setattr(
        repository,
        "fetch_annual_trend_rows",
        lambda db, **kwargs: [
            {
                "fiscal_year": 2026,
                "matched_row_count": 1,
                "numeric_amount_rows": 1,
                "amount": Decimal(annual_amount),
            }
        ],
    )
    monkeypatch.setattr(repository, "trend_account_exists", lambda db, symbol: symbol == "075-0943")


def test_obligations_default_and_cumulative_activity(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_rows(
        monkeypatch,
        quarterly_amounts=["100.00", "25.00", "-10.00", "5.00"],
        annual_amount="120.00",
    )

    payload = service.get_quarterly_trends(object())

    assert payload.scope == CdcFundingScope.all_accounts
    assert payload.measure == CdcFundingTrendMeasure.obligations
    assert payload.view == CdcFundingTrendView.total
    assert payload.available_fiscal_years == [2026]
    assert [point.quarter_amount for point in payload.series[0].points] == [
        "100.00",
        "25.00",
        "-10.00",
        "5.00",
    ]
    assert [point.cumulative_amount for point in payload.series[0].points] == [
        "100.00",
        "125.00",
        "115.00",
        "120.00",
    ]
    assert payload.series[0].reconciliation.difference == "0.00"


def test_outlays_use_snapshots_and_difference_activity(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_rows(
        monkeypatch,
        quarterly_amounts=["100.00", "160.00", "140.00", "220.00"],
        annual_amount="220.00",
    )

    payload = service.get_quarterly_trends(object(), measure=CdcFundingTrendMeasure.outlays)

    assert [point.cumulative_amount for point in payload.series[0].points] == [
        "100.00",
        "160.00",
        "140.00",
        "220.00",
    ]
    assert [point.quarter_amount for point in payload.series[0].points] == [
        "100.00",
        "60.00",
        "-20.00",
        "80.00",
    ]


def test_partial_year_returns_unavailable_null_quarters(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_rows(
        monkeypatch,
        quarterly_amounts=["10.00", "20.00"],
        annual_amount="30.00",
        quarters=2,
    )

    series = service.get_quarterly_trends(object()).series[0]

    assert series.available_through_quarter == "Q2"
    assert series.latest_submission_period == "FY2026P06"
    assert series.is_complete is False
    assert [point.available for point in series.points] == [True, True, False, False]
    assert series.points[2].quarter_amount is None
    assert series.points[2].cumulative_amount is None


def test_null_source_rows_fail_instead_of_coalescing_to_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_rows(monkeypatch, quarterly_amounts=["10.00"], annual_amount="10.00", quarters=1)
    monkeypatch.setattr(
        repository,
        "fetch_quarterly_trend_rows",
        lambda db, **kwargs: [
            {
                "fiscal_year": 2026,
                "fiscal_quarter": "Q1",
                "matched_row_count": 2,
                "numeric_amount_rows": 1,
                "amount": Decimal("10.00"),
            }
        ],
    )

    with pytest.raises(HTTPException) as exc_info:
        service.get_quarterly_trends(object(), measure=CdcFundingTrendMeasure.outlays)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail["code"] == "cdc_funding_internal_reconciliation_error"


def test_federal_account_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_rows(monkeypatch, quarterly_amounts=["10.00"], annual_amount="10.00", quarters=1)

    with pytest.raises(HTTPException) as missing:
        service.get_quarterly_trends(object(), view=CdcFundingTrendView.federal_account)
    assert missing.value.status_code == 422

    with pytest.raises(HTTPException) as unknown:
        service.get_quarterly_trends(
            object(),
            view=CdcFundingTrendView.federal_account,
            federal_account_symbol="075-UNKNOWN",
        )
    assert unknown.value.status_code == 404

    with pytest.raises(HTTPException) as total_symbol:
        service.get_quarterly_trends(object(), federal_account_symbol="075-0943")
    assert total_symbol.value.status_code == 422


def test_mapped_scope_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(HTTPException) as exc_info:
        service.get_quarterly_trends(object(), scope=CdcFundingScope.cdc_funding_profiles)

    assert exc_info.value.status_code == 422


def test_trend_accounts_keep_symbol_identity_and_latest_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        repository,
        "fetch_trend_account_options",
        lambda db: [
            {
                "federal_account_symbol": "075-0943",
                "federal_account_name": "Most recent name",
                "first_fiscal_year": 2021,
                "last_fiscal_year": 2026,
            },
            {
                "federal_account_symbol": "075-UNMAPPED",
                "federal_account_name": None,
                "first_fiscal_year": 2022,
                "last_fiscal_year": 2024,
            },
        ],
    )

    payload = service.get_trend_accounts(object())

    assert [account.federal_account_symbol for account in payload.accounts] == [
        "075-0943",
        "075-UNMAPPED",
    ]
    assert payload.accounts[0].federal_account_name == "Most recent name"
    assert payload.accounts[1].last_fiscal_year == 2024


@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        ("measure", "spending"),
        ("view", "category"),
        ("emergency_status", "sometimes"),
        ("award_type", "cooperative_agreement"),
    ],
)
def test_router_rejects_invalid_trend_enums(parameter: str, value: str) -> None:
    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides[get_db] = lambda: object()

    response = TestClient(app).get(f"/api/cdc-funding/v1/quarterly-trends?{parameter}={value}")

    assert response.status_code == 422


MONTHLY_PERIODS = [
    ("FY2026P02", "October-November (combined P01/P02 submission)", "Q1"),
    ("FY2026P03", "December", "Q1"),
    ("FY2026P04", "January", "Q2"),
    ("FY2026P05", "February", "Q2"),
    ("FY2026P06", "March", "Q2"),
    ("FY2026P07", "April", "Q3"),
    ("FY2026P08", "May", "Q3"),
    ("FY2026P09", "June", "Q3"),
    ("FY2026P10", "July", "Q4"),
    ("FY2026P11", "August", "Q4"),
    ("FY2026P12", "September", "Q4"),
]


def _install_obligation_rows(
    monkeypatch: pytest.MonkeyPatch,
    *,
    monthly_amounts: list[str],
    quarterly_amounts: list[str] | None = None,
    annual_amount: str | None = None,
) -> None:
    periods = MONTHLY_PERIODS[: len(monthly_amounts)]
    monkeypatch.setattr(
        repository,
        "fetch_trend_month_coverage",
        lambda db: [
            {
                "fiscal_year": 2026,
                "submission_period": submission,
                "period_label": label,
                "fiscal_quarter": quarter,
            }
            for submission, label, quarter in periods
        ],
    )
    monkeypatch.setattr(
        repository,
        "fetch_monthly_obligation_trend_rows",
        lambda db, **kwargs: [
            {
                "fiscal_year": 2026,
                "submission_period": submission,
                "period_label": label,
                "fiscal_quarter": quarter,
                "matched_row_count": 1,
                "numeric_amount_rows": 1,
                "amount": Decimal(amount),
            }
            for (submission, label, quarter), amount in zip(
                periods, monthly_amounts, strict=True
            )
        ],
    )
    monkeypatch.setattr(
        repository,
        "fetch_monthly_trend_rows",
        lambda db, **kwargs: [
            {
                "fiscal_year": 2026,
                "submission_period": submission,
                "period_label": label,
                "fiscal_quarter": quarter,
                "matched_row_count": 1,
                "numeric_amount_rows": 1,
                "amount": Decimal(amount),
            }
            for (submission, label, quarter), amount in zip(
                periods, monthly_amounts, strict=True
            )
        ],
    )
    quarter_values = quarterly_amounts or []
    monkeypatch.setattr(
        repository,
        "fetch_trend_quarter_coverage",
        lambda db: [
            {"fiscal_year": 2026, "fiscal_quarter": f"Q{number}"}
            for number in range(1, len(quarter_values) + 1)
        ],
    )
    monkeypatch.setattr(
        repository,
        "fetch_quarterly_trend_rows",
        lambda db, **kwargs: [
            {
                "fiscal_year": 2026,
                "fiscal_quarter": f"Q{number}",
                "matched_row_count": 1,
                "numeric_amount_rows": 1,
                "amount": Decimal(amount),
            }
            for number, amount in enumerate(quarter_values, start=1)
        ],
    )
    expected = annual_amount or str(sum((Decimal(value) for value in monthly_amounts), Decimal("0")))
    monkeypatch.setattr(
        repository,
        "fetch_annual_trend_rows",
        lambda db, **kwargs: [
            {
                "fiscal_year": 2026,
                "matched_row_count": 1,
                "numeric_amount_rows": 1,
                "amount": Decimal(expected),
            }
        ],
    )
    monkeypatch.setattr(
        repository,
        "trend_account_exists",
        lambda db, symbol: symbol in {"075-0943", "075-0120"},
    )


def test_obligation_trends_default_to_month_and_preserve_source_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_obligation_rows(
        monkeypatch,
        monthly_amounts=["100.00", "25.00", "-10.00", "0.00", "5.00"],
    )

    payload = service.get_obligation_trends(object())
    series = payload.series[0]

    assert payload.measure == "obligations"
    assert payload.period == CdcFundingTrendPeriod.month
    assert payload.available_fiscal_years == [2026]
    assert [point.period for point in series.points] == [
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
    ]
    assert series.points[0].available is False
    assert series.points[0].period_amount is None
    assert series.points[1].period_amount == "100.00"
    assert (
        series.points[1].source_period_label
        == "October-November (combined P01/P02 submission)"
    )
    assert [point.cumulative_amount for point in series.points[1:6]] == [
        "100.00",
        "125.00",
        "115.00",
        "115.00",
        "120.00",
    ]
    assert series.available_through_month == "Mar"
    assert series.latest_submission_period == "FY2026P06"
    assert series.is_complete is False
    assert series.points[6].available is False
    assert series.points[6].cumulative_amount is None
    assert series.reconciliation.difference == "0.00"


def test_obligation_trends_quarter_mode_uses_activity_and_preserves_declines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_obligation_rows(
        monkeypatch,
        monthly_amounts=["70.00", "30.00", "25.00", "0.00", "-10.00"],
        quarterly_amounts=["100.00", "15.00"],
        annual_amount="115.00",
    )
    quarterly_stub = repository.fetch_quarterly_trend_rows
    requested_measure: list[str] = []

    def fetch_quarterly(db: object, **kwargs: object) -> list[dict[str, object]]:
        requested_measure.append(str(kwargs["measure"]))
        return quarterly_stub(db, **kwargs)

    monkeypatch.setattr(repository, "fetch_quarterly_trend_rows", fetch_quarterly)

    series = service.get_obligation_trends(
        object(), period=CdcFundingTrendPeriod.quarter
    ).series[0]

    assert requested_measure == ["obligations"]
    assert [point.period for point in series.points] == ["Q1", "Q2", "Q3", "Q4"]
    assert [point.period_amount for point in series.points] == [
        "100.00",
        "15.00",
        None,
        None,
    ]
    assert [point.cumulative_amount for point in series.points] == [
        "100.00",
        "115.00",
        None,
        None,
    ]
    assert series.available_through_quarter == "Q2"
    assert series.latest_submission_period == "FY2026P06"


def test_obligation_trends_exclude_deobligations_before_aggregation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The same source period contains +100.00 and -40.00 activity. Its stored
    # net is 60.00, so clamping the net could never recover the positive 100.00.
    _install_obligation_rows(
        monkeypatch,
        monthly_amounts=["60.00", "-10.00"],
        quarterly_amounts=["50.00"],
        annual_amount="50.00",
    )

    def fetch_positive(
        db: object, *, period: str, **kwargs: object
    ) -> list[dict[str, object]]:
        if period == "quarter":
            return [
                {
                    "fiscal_year": 2026,
                    "fiscal_quarter": "Q1",
                    "matched_row_count": 4,
                    "numeric_amount_rows": 4,
                    "amount": Decimal("125.00"),
                }
            ]
        return [
            {
                "fiscal_year": 2026,
                "submission_period": "FY2026P02",
                "period_label": "October-November (combined P01/P02 submission)",
                "fiscal_quarter": "Q1",
                "matched_row_count": 2,
                "numeric_amount_rows": 2,
                "amount": Decimal("100.00"),
            },
            {
                "fiscal_year": 2026,
                "submission_period": "FY2026P03",
                "period_label": "December",
                "fiscal_quarter": "Q1",
                "matched_row_count": 2,
                "numeric_amount_rows": 2,
                "amount": Decimal("25.00"),
            },
        ]

    monkeypatch.setattr(
        repository, "fetch_positive_obligation_trend_rows", fetch_positive
    )
    monkeypatch.setattr(
        repository,
        "fetch_positive_annual_obligation_trend_rows",
        lambda db, **kwargs: [
            {
                "fiscal_year": 2026,
                "matched_row_count": 4,
                "numeric_amount_rows": 4,
                "amount": Decimal("125.00"),
            }
        ],
    )

    normal = service.get_obligation_trends(object())
    positive_monthly = service.get_obligation_trends(
        object(), exclude_deobligations=True
    )
    positive_quarterly = service.get_obligation_trends(
        object(),
        period=CdcFundingTrendPeriod.quarter,
        exclude_deobligations=True,
    )

    assert normal.series[0].points[1].period_amount == "60.00"
    assert [point.period_amount for point in positive_monthly.series[0].points[1:3]] == [
        "100.00",
        "25.00",
    ]
    assert [
        point.cumulative_amount for point in positive_monthly.series[0].points[1:3]
    ] == ["100.00", "125.00"]
    assert positive_quarterly.series[0].points[0].period_amount == "125.00"
    assert positive_quarterly.series[0].points[0].cumulative_amount == "125.00"
    assert positive_monthly.filters.exclude_deobligations is True
    assert positive_monthly.series[0].reconciliation.difference == "0.00"


def test_obligation_trends_account_filters_and_zero_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_obligation_rows(
        monkeypatch,
        monthly_amounts=["10.00", "0.00"],
        annual_amount="10.00",
    )

    payload = service.get_obligation_trends(
        object(),
        view=CdcFundingTrendView.federal_account,
        federal_account_symbol="075-0120",
    )

    assert payload.filters.federal_account_symbol == "075-0120"
    assert payload.series[0].points[2].available is True
    assert payload.series[0].points[2].period_amount == "0.00"
    assert payload.series[0].points[2].cumulative_amount == "10.00"


def test_obligation_trends_reject_invalid_measure_and_reconciliation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_obligation_rows(
        monkeypatch,
        monthly_amounts=["10.00"],
        annual_amount="11.00",
    )

    with pytest.raises(HTTPException) as measure_error:
        service.get_obligation_trends(object(), measure="spending")
    assert measure_error.value.status_code == 422
    assert measure_error.value.detail["code"] == "cdc_funding_measure_not_supported"

    with pytest.raises(HTTPException) as reconciliation_error:
        service.get_obligation_trends(object())
    assert reconciliation_error.value.status_code == 500
    assert (
        reconciliation_error.value.detail["code"]
        == "cdc_funding_internal_reconciliation_error"
    )


def test_monthly_outlays_difference_stored_cumulative_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_obligation_rows(
        monkeypatch,
        monthly_amounts=["80.00", "125.00", "120.00"],
        annual_amount="120.00",
    )

    payload = service.get_obligation_trends(object(), measure="outlays")
    points = payload.series[0].points[1:4]

    assert payload.measure == "outlays"
    assert [point.period_amount for point in points] == ["80.00", "45.00", "-5.00"]
    assert [point.cumulative_amount for point in points] == ["80.00", "125.00", "120.00"]
    assert payload.series[0].reconciliation.difference == "0.00"

    with pytest.raises(HTTPException) as error:
        service.get_obligation_trends(
            object(), measure="outlays", exclude_deobligations=True
        )
    assert error.value.detail["code"] == "cdc_funding_deobligations_not_supported_for_outlays"


def test_obligation_trends_validate_scope_and_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(repository, "trend_account_exists", lambda db, symbol: False)

    with pytest.raises(HTTPException) as scope_error:
        service.get_obligation_trends(
            object(), scope=CdcFundingScope.cdc_funding_profiles
        )
    assert scope_error.value.status_code == 422

    with pytest.raises(HTTPException) as missing_account:
        service.get_obligation_trends(
            object(), view=CdcFundingTrendView.federal_account
        )
    assert missing_account.value.status_code == 422

    with pytest.raises(HTTPException) as unknown_account:
        service.get_obligation_trends(
            object(),
            view=CdcFundingTrendView.federal_account,
            federal_account_symbol="075-UNKNOWN",
        )
    assert unknown_account.value.status_code == 404

    with pytest.raises(HTTPException) as account_in_total_view:
        service.get_obligation_trends(
            object(), federal_account_symbol="075-0943"
        )
    assert account_in_total_view.value.status_code == 422


@pytest.mark.parametrize("period", ["week", "year"])
def test_obligation_trends_router_rejects_invalid_period(period: str) -> None:
    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides[get_db] = lambda: object()

    response = TestClient(app).get(
        f"/api/cdc-funding/v1/obligation-trends?period={period}"
    )

    assert response.status_code == 422
