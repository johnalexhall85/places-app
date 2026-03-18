from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.recon import profile_calibration


def _support_row(**overrides):
    row = {
        "source_system": "usaspending",
        "fiscal_year": 2023,
        "state_code": "ga",
        "raw_reconstructed_amount": Decimal("120.00"),
        "reconstructed_profile_scope_amount": Decimal("100.00"),
        "regular_appropriation_amount": Decimal("82.00"),
        "covid_emergency_amount": Decimal("5.00"),
        "arpa_amount": Decimal("0.00"),
        "other_emergency_or_disaster_amount": Decimal("0.00"),
        "non_covid_supplemental_amount": Decimal("0.00"),
        "transfer_or_special_amount": Decimal("3.00"),
        "procurement_support_amount": Decimal("10.00"),
        "unknown_stream_amount": Decimal("12.00"),
        "unknown_stream_included_amount": Decimal("0.00"),
        "unknown_stream_excluded_amount": Decimal("8.00"),
        "unknown_stream_uncertain_amount": Decimal("4.00"),
        "core_public_health_amount": Decimal("82.00"),
        "core_public_health_excluded_amount": Decimal("0.00"),
        "core_public_health_uncertain_amount": Decimal("0.00"),
        "emergency_public_health_amount": Decimal("5.00"),
        "emergency_public_health_excluded_amount": Decimal("0.00"),
        "emergency_public_health_uncertain_amount": Decimal("4.00"),
        "federal_health_transfer_amount": Decimal("0.00"),
        "federal_health_transfer_excluded_amount": Decimal("3.00"),
        "federal_health_transfer_uncertain_amount": Decimal("0.00"),
        "procurement_support_scope_amount": Decimal("10.00"),
        "procurement_support_scope_excluded_amount": Decimal("14.00"),
        "procurement_support_scope_uncertain_amount": Decimal("0.00"),
        "special_transfer_amount": Decimal("3.00"),
        "special_transfer_excluded_amount": Decimal("0.00"),
        "special_transfer_uncertain_amount": Decimal("0.00"),
        "other_public_health_amount": Decimal("0.00"),
        "other_public_health_excluded_amount": Decimal("9.00"),
        "other_public_health_uncertain_amount": Decimal("0.00"),
        "biomedical_research_amount": Decimal("0.00"),
        "biomedical_research_excluded_amount": Decimal("7.00"),
        "biomedical_research_uncertain_amount": Decimal("0.00"),
        "international_health_assistance_amount": Decimal("0.00"),
        "international_health_assistance_excluded_amount": Decimal("6.00"),
        "international_health_assistance_uncertain_amount": Decimal("0.00"),
        "unknown_funding_scope_amount": Decimal("0.00"),
        "unknown_funding_scope_excluded_amount": Decimal("8.00"),
        "unknown_funding_scope_uncertain_amount": Decimal("4.00"),
        "transaction_count": 10,
        "included_transaction_count": 7,
        "excluded_transaction_count": 2,
        "uncertain_transaction_count": 1,
        "uncertain_amount": Decimal("4.00"),
        "excluded_non_domestic_amount": Decimal("6.00"),
        "excluded_contract_amount": Decimal("14.00"),
        "methodology_version": "profile_scope_v1",
        "refreshed_at": datetime(2026, 3, 15, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def test_build_cdc_profile_reference_map_normalizes_keys() -> None:
    reference_map = profile_calibration.build_cdc_profile_reference_map(
        [
            {
                "fiscal_year": 2023,
                "state_code": "ga",
                "state_name": "Georgia",
                "cdc_profile_amount": Decimal("110.00"),
                "row_count": 5,
            }
        ]
    )

    assert reference_map[(2023, "GA")]["cdc_profile_amount"] == Decimal("110.00")
    assert reference_map[(2023, "GA")]["state_name"] == "Georgia"


def test_build_support_map_normalizes_full_state_names_to_postal_codes() -> None:
    support_map = profile_calibration.build_support_map(
        [
            _support_row(
                state_code="District of Columbia",
                fiscal_year=2022,
            )
        ]
    )

    assert (2022, "DC") in support_map
    assert support_map[(2022, "DC")]["raw_reconstructed_amount"] == Decimal("120.00")


def test_build_reconciliation_rows_calculates_residuals_and_flags() -> None:
    support_map = profile_calibration.build_support_map([_support_row()])
    reference_map = profile_calibration.build_cdc_profile_reference_map(
        [
            {
                "fiscal_year": 2023,
                "state_code": "GA",
                "state_name": "Georgia",
                "cdc_profile_amount": Decimal("103.00"),
                "row_count": 10,
            }
        ]
    )

    rows = profile_calibration.build_reconciliation_rows(
        source_system="usaspending",
        fiscal_years=[2023],
        cdc_reference_map=reference_map,
        support_map=support_map,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["state_code"] == "GA"
    assert row["residual_amount"] == Decimal("3.00")
    assert row["residual_pct"] == Decimal("0.029126")
    assert row["abs_residual_amount"] == Decimal("3.00")
    assert row["calibration_status"] == "calibrated"
    assert row["confidence_label"] == "medium"


def test_build_driver_breakdown_rows_preserves_status_buckets() -> None:
    support_map = profile_calibration.build_support_map([_support_row()])

    rows = profile_calibration.build_driver_breakdown_rows(
        source_system="usaspending",
        fiscal_years=[2023],
        support_map=support_map,
    )

    keyed_rows = {
        (row["driver_name"], row["inclusion_status"]): row["driver_amount"]
        for row in rows
    }
    assert keyed_rows[("regular_appropriation", "included")] == Decimal("82.00")
    assert keyed_rows[("procurement_support_stream", "included")] == Decimal("10.00")
    assert keyed_rows[("core_public_health", "included")] == Decimal("82.00")
    assert keyed_rows[("procurement_support", "included")] == Decimal("10.00")
    assert keyed_rows[("federal_health_transfer", "excluded")] == Decimal("3.00")
    assert keyed_rows[("other_public_health", "excluded")] == Decimal("9.00")
    assert keyed_rows[("biomedical_research", "excluded")] == Decimal("7.00")
    assert keyed_rows[("international_health_assistance", "excluded")] == Decimal("6.00")
    assert keyed_rows[("unknown_stream", "excluded")] == Decimal("8.00")
    assert keyed_rows[("unknown", "uncertain")] == Decimal("4.00")
    assert keyed_rows[("uncertain_rows", "uncertain")] == Decimal("4.00")
    assert keyed_rows[("excluded_contracts", "excluded")] == Decimal("14.00")


def test_build_normalized_state_funding_rows_preserves_reconstructed_amount() -> None:
    support_map = profile_calibration.build_support_map([_support_row()])
    reference_map = profile_calibration.build_cdc_profile_reference_map(
        [
            {
                "fiscal_year": 2023,
                "state_code": "GA",
                "state_name": "Georgia",
                "cdc_profile_amount": Decimal("103.00"),
                "row_count": 10,
            }
        ]
    )

    rows = profile_calibration.build_normalized_state_funding_rows(
        source_system="usaspending",
        fiscal_years=[2023, 2024],
        cdc_reference_map=reference_map,
        support_map=support_map,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["normalized_amount"] == Decimal("100.00")
    assert row["cdc_profile_reference_amount"] == Decimal("103.00")
    assert row["residual_amount"] == Decimal("3.00")
    assert row["normalized_amount_type"] == profile_calibration.NORMALIZED_AMOUNT_TYPE_OBSERVED
    assert row["core_public_health_amount"] == Decimal("82.00")
    assert row["funding_scope_components_json"]["special_transfer"] == "3.00"
    assert "not a copied CDC profile total" in str(row["confidence_note"])


def test_build_normalized_state_funding_rows_marks_later_years_as_estimated() -> None:
    support_map = profile_calibration.build_support_map(
        [
            _support_row(
                fiscal_year=2025,
                state_code="TX",
                raw_reconstructed_amount=Decimal("210.00"),
                reconstructed_profile_scope_amount=Decimal("160.00"),
            )
        ]
    )

    rows = profile_calibration.build_normalized_state_funding_rows(
        source_system="usaspending",
        fiscal_years=[2025],
        cdc_reference_map={},
        support_map=support_map,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["state_code"] == "TX"
    assert row["normalized_amount_type"] == profile_calibration.NORMALIZED_AMOUNT_TYPE_ESTIMATED
    assert row["cdc_profile_reference_amount"] is None
    assert "profile-aligned estimates" in str(row["calibration_basis"])


def test_build_reconciliation_summary_rows_aggregates_absolute_residuals() -> None:
    rows = [
        {
            "fiscal_year": 2023,
            "source_system": "usaspending",
            "state_code": "GA",
            "residual_pct": Decimal("0.020000"),
            "calibration_status": "exact_window",
            "unknown_stream_amount": Decimal("12.00"),
            "uncertain_amount": Decimal("4.00"),
        },
        {
            "fiscal_year": 2023,
            "source_system": "usaspending",
            "state_code": "AL",
            "residual_pct": Decimal("-0.100000"),
            "calibration_status": "calibrated",
            "unknown_stream_amount": Decimal("5.00"),
            "uncertain_amount": Decimal("2.00"),
        },
        {
            "fiscal_year": 2023,
            "source_system": "usaspending",
            "state_code": "TX",
            "residual_pct": Decimal("0.200000"),
            "calibration_status": "needs_review",
            "unknown_stream_amount": Decimal("8.00"),
            "uncertain_amount": Decimal("1.00"),
        },
    ]

    summary_rows = profile_calibration.build_reconciliation_summary_rows(rows)

    assert len(summary_rows) == 1
    row = summary_rows[0]
    assert row["avg_abs_residual_pct"] == Decimal("0.106667")
    assert row["median_abs_residual_pct"] == Decimal("0.100000")
    assert row["max_abs_residual_pct"] == Decimal("0.200000")
    assert row["exact_window_state_count"] == 1
    assert row["calibrated_state_count"] == 1
    assert row["needs_review_state_count"] == 1
    assert row["total_unknown_stream_amount"] == Decimal("25.00")
    assert row["total_uncertain_amount"] == Decimal("7.00")
