from __future__ import annotations

from decimal import Decimal

from app.recon import assistance_multi_account_fix


def test_build_state_improvements_orders_biggest_positive_residual_reductions_first() -> None:
    rows = assistance_multi_account_fix.build_state_improvements(
        {
            "GA": Decimal("0.120000"),
            "TX": Decimal("0.080000"),
            "AL": Decimal("0.050000"),
        },
        {
            "GA": Decimal("0.040000"),
            "TX": Decimal("0.060000"),
            "AL": Decimal("0.060000"),
        },
    )

    assert rows == [
        {
            "state_code": "GA",
            "avg_abs_residual_pct_before": Decimal("0.120000"),
            "avg_abs_residual_pct_after": Decimal("0.040000"),
            "improvement_pct_points": Decimal("0.080000"),
        },
        {
            "state_code": "TX",
            "avg_abs_residual_pct_before": Decimal("0.080000"),
            "avg_abs_residual_pct_after": Decimal("0.060000"),
            "improvement_pct_points": Decimal("0.020000"),
        },
    ]


def test_build_account_improvements_allocates_transaction_gain_across_linked_accounts() -> None:
    rows = assistance_multi_account_fix.build_account_improvements(
        before_transaction_amounts={
            "assist-1": Decimal("0.00"),
            "assist-2": Decimal("20.00"),
        },
        after_transaction_amounts={
            "assist-1": Decimal("100.00"),
            "assist-2": Decimal("70.00"),
        },
        account_rows=[
            {"source_transaction_id": "assist-1", "federal_account_symbol": "075-0140"},
            {"source_transaction_id": "assist-1", "federal_account_symbol": "075-0943"},
            {"source_transaction_id": "assist-2", "federal_account_symbol": "075-0140"},
        ],
    )

    assert rows == [
        {
            "federal_account_symbol": "075-0140",
            "allocated_improvement_amount": Decimal("100.00"),
        },
        {
            "federal_account_symbol": "075-0943",
            "allocated_improvement_amount": Decimal("50.00"),
        },
    ]


def test_build_fix_summary_payload_surfaces_before_after_improvement_metrics() -> None:
    payload = assistance_multi_account_fix.build_fix_summary_payload(
        before_metrics={
            "included_assistance_amount": Decimal("23.26"),
            "avg_abs_residual_pct": Decimal("0.990000"),
            "state_residuals": {"GA": Decimal("0.120000")},
            "assistance_transaction_amounts": {},
        },
        after_metrics={
            "included_assistance_amount": Decimal("72.25"),
            "avg_abs_residual_pct": Decimal("0.180000"),
            "state_residuals": {"GA": Decimal("0.040000")},
            "assistance_transaction_amounts": {},
        },
        lookup_summary={
            "assistance_account_bridge": {
                "single_account_rows": 10,
                "multi_account_rows": 20,
                "missing_account_rows": 2,
                "top_individual_account_symbols_from_multi_account_rows": [
                    {"federal_account_symbol": "075-0140", "transaction_obligated_amount": Decimal("50.00")}
                ],
                "top_multi_account_combinations": [
                    {"account_symbols": "075-0140; 075-0943", "transaction_obligated_amount": Decimal("60.00")}
                ],
            }
        },
        profile_scope_summary={"included_assistance_total": Decimal("72.25")},
        calibration_summary={"summary_rows_written": 4},
        top_account_improvements=[
            {"federal_account_symbol": "075-0140", "allocated_improvement_amount": Decimal("35.00")}
        ],
    )

    assert payload["included_assistance_amount_before"] == Decimal("23.26")
    assert payload["included_assistance_amount_after"] == Decimal("72.25")
    assert payload["avg_abs_residual_pct_before"] == Decimal("0.990000")
    assert payload["avg_abs_residual_pct_after"] == Decimal("0.180000")
    assert payload["states_with_biggest_improvement"][0]["state_code"] == "GA"
    assert payload["top_individual_accounts_driving_improvement"][0]["federal_account_symbol"] == "075-0140"
