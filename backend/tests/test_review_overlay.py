from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.recon import profile_calibration
from app.recon import review_overlay


def _profile_scope_summary() -> dict[str, object]:
    return {
        "row_count_by_account_structure_type": [
            {"account_structure_type": "single_account", "row_count": 10},
            {"account_structure_type": "multi_account_same_scope", "row_count": 4},
            {"account_structure_type": "multi_account_mixed_scope", "row_count": 6},
        ]
    }


def _review_payload() -> dict[str, object]:
    return {
        "summary_by_program_family": [
            {
                "program_family_label": "immunization",
                "row_count": 11,
                "raw_amount": Decimal("725.00"),
                "residual_contribution_estimate": Decimal("700.00"),
            },
            {
                "program_family_label": "ELC",
                "row_count": 5,
                "raw_amount": Decimal("200.00"),
                "residual_contribution_estimate": Decimal("150.00"),
            },
        ],
        "national_top_rows": [
            {
                "award_identifier": "wa-elc-1",
                "aln_or_code": "93.323",
                "program_family_label": "ELC",
                "state_code": "WA",
                "state_name": "Washington",
                "state": "Washington",
                "award_title": "Epidemiology and Laboratory Capacity",
                "federal_account_combination_key": "075-0140|075-0511|075-0512|075-0943",
                "current_inclusion_treatment": "conditional",
                "multi_account_interpretation": "mixed_program_transfer",
                "residual_contribution_estimate": Decimal("150.00"),
                "raw_amount": Decimal("200.00"),
                "normalized_amount": Decimal("0.00"),
            },
            {
                "award_identifier": "ca-imm-1",
                "aln_or_code": "93.268",
                "program_family_label": "immunization",
                "state_code": "CA",
                "state_name": "California",
                "state": "California",
                "award_title": "Immunization Cooperative Agreements",
                "federal_account_combination_key": "075-0512|075-0943|075-0951",
                "current_inclusion_treatment": "conditional",
                "multi_account_interpretation": "mixed_program_transfer",
                "residual_contribution_estimate": Decimal("500.00"),
                "raw_amount": Decimal("500.00"),
                "normalized_amount": Decimal("0.00"),
            },
        ],
        "washington_rows": [
            {
                "award_identifier": "wa-elc-1",
                "aln_or_code": "93.323",
                "program_family_label": "ELC",
                "state_code": "WA",
                "state_name": "Washington",
                "state": "Washington",
                "award_title": "Epidemiology and Laboratory Capacity",
                "federal_account_combination_key": "075-0140|075-0511|075-0512|075-0943",
                "current_inclusion_treatment": "conditional",
                "multi_account_interpretation": "mixed_program_transfer",
                "residual_contribution_estimate": Decimal("150.00"),
                "raw_amount": Decimal("200.00"),
                "normalized_amount": Decimal("0.00"),
            }
        ],
    }


def _recommendations_payload() -> dict[str, object]:
    return {
        "candidate_recommendations": [
            {
                "status": "manual_review_only",
                "program_family_label": "ELC",
                "reason_not_auto_applied": "No defensible split.",
                "proposed_conditions": {
                    "fiscal_year": 2021,
                    "award_type": "assistance",
                    "alns": ["93.323"],
                    "program_family_label": "ELC",
                    "federal_account_combination_keys": ["075-0140|075-0511|075-0512|075-0943"],
                },
            },
            {
                "status": "manual_review_only",
                "program_family_label": "immunization",
                "reason_not_auto_applied": "No defensible split.",
                "proposed_conditions": {
                    "fiscal_year": 2021,
                    "award_type": "assistance",
                    "alns": ["93.268", "93.185", "D318"],
                    "program_family_label": "immunization",
                    "federal_account_combination_keys": [
                        "075-0140|075-0512|075-0943|075-0951",
                        "075-0512|075-0943|075-0951",
                    ],
                },
            },
        ],
        "production_change_recommended": False,
    }


def _support_row(**overrides):
    row = {
        "source_system": "usaspending",
        "fiscal_year": 2021,
        "state_code": "WA",
        "raw_reconstructed_amount": Decimal("120.00"),
        "reconstructed_profile_scope_amount": Decimal("100.00"),
        "regular_appropriation_amount": Decimal("80.00"),
        "covid_emergency_amount": Decimal("0.00"),
        "arpa_amount": Decimal("0.00"),
        "other_emergency_or_disaster_amount": Decimal("0.00"),
        "non_covid_supplemental_amount": Decimal("0.00"),
        "transfer_or_special_amount": Decimal("0.00"),
        "procurement_support_amount": Decimal("0.00"),
        "unknown_stream_amount": Decimal("0.00"),
        "unknown_stream_included_amount": Decimal("0.00"),
        "unknown_stream_excluded_amount": Decimal("0.00"),
        "unknown_stream_uncertain_amount": Decimal("0.00"),
        "core_public_health_amount": Decimal("80.00"),
        "core_public_health_excluded_amount": Decimal("0.00"),
        "core_public_health_uncertain_amount": Decimal("0.00"),
        "emergency_public_health_amount": Decimal("0.00"),
        "emergency_public_health_excluded_amount": Decimal("0.00"),
        "emergency_public_health_uncertain_amount": Decimal("0.00"),
        "federal_health_transfer_amount": Decimal("0.00"),
        "federal_health_transfer_excluded_amount": Decimal("0.00"),
        "federal_health_transfer_uncertain_amount": Decimal("0.00"),
        "procurement_support_scope_amount": Decimal("0.00"),
        "procurement_support_scope_excluded_amount": Decimal("0.00"),
        "procurement_support_scope_uncertain_amount": Decimal("0.00"),
        "special_transfer_amount": Decimal("0.00"),
        "special_transfer_excluded_amount": Decimal("0.00"),
        "special_transfer_uncertain_amount": Decimal("0.00"),
        "other_public_health_amount": Decimal("0.00"),
        "other_public_health_excluded_amount": Decimal("0.00"),
        "other_public_health_uncertain_amount": Decimal("0.00"),
        "biomedical_research_amount": Decimal("0.00"),
        "biomedical_research_excluded_amount": Decimal("0.00"),
        "biomedical_research_uncertain_amount": Decimal("0.00"),
        "international_health_assistance_amount": Decimal("0.00"),
        "international_health_assistance_excluded_amount": Decimal("0.00"),
        "international_health_assistance_uncertain_amount": Decimal("0.00"),
        "unknown_funding_scope_amount": Decimal("0.00"),
        "unknown_funding_scope_excluded_amount": Decimal("0.00"),
        "unknown_funding_scope_uncertain_amount": Decimal("0.00"),
        "transaction_count": 1,
        "included_transaction_count": 1,
        "excluded_transaction_count": 0,
        "uncertain_transaction_count": 0,
        "uncertain_amount": Decimal("0.00"),
        "excluded_non_domestic_amount": Decimal("0.00"),
        "excluded_contract_amount": Decimal("0.00"),
        "methodology_version": "profile_scope_v5_verified_csv_multi_account_fy2021_diagnostics",
        "refreshed_at": datetime(2026, 3, 16, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def test_build_methodology_display_summary_payload_produces_frontend_ready_counts() -> None:
    payload = review_overlay.build_methodology_display_summary_payload(
        methodology_version=profile_calibration.METHODOLOGY_VERSION,
        verified_summary={"loaded_account_count": 29, "fallback_account_count": 0},
        profile_scope_summary=_profile_scope_summary(),
        review_payload=_review_payload(),
        recommendations_payload=_recommendations_payload(),
    )

    assert payload["current_frozen_version"] == profile_calibration.METHODOLOGY_VERSION
    assert payload["verified_account_count"] == 29
    assert payload["fallback_account_count"] == 0
    assert payload["total_multi_account_mixed_scope_rows"] == 6
    assert payload["top_fy2021_review_families"][0]["award_family"] == "immunization"
    assert payload["manual_review_exceptions_applied_in_production"] is False


def test_build_manual_review_exception_candidate_rows_generates_seed_rows() -> None:
    rows = review_overlay.build_manual_review_exception_candidate_rows(
        methodology_version=profile_calibration.METHODOLOGY_VERSION,
        review_payload=_review_payload(),
        recommendations_payload=_recommendations_payload(),
    )

    assert len(rows) == 7
    assert all(row["apply_in_production"] is False for row in rows)
    assert all(row["assistance_only"] is True for row in rows)
    assert rows[0]["recommended_review_disposition"] == "manual_review_only"


def test_build_manual_review_crosswalk_payload_matches_candidate_rows() -> None:
    candidate_rows = review_overlay.build_manual_review_exception_candidate_rows(
        methodology_version=profile_calibration.METHODOLOGY_VERSION,
        review_payload=_review_payload(),
        recommendations_payload=_recommendations_payload(),
    )

    payload = review_overlay.build_manual_review_crosswalk_payload(
        review_payload=_review_payload(),
        candidate_rows=candidate_rows,
    )

    assert payload["row_count"] == 2
    assert payload["rows"][0]["award_family"] == "immunization"
    assert payload["rows"][1]["state_code"] == "WA"


def test_manual_review_overlay_candidates_do_not_change_production_calculations() -> None:
    support_map = profile_calibration.build_support_map([_support_row()])
    reference_map = profile_calibration.build_cdc_profile_reference_map(
        [
            {
                "fiscal_year": 2021,
                "state_code": "WA",
                "state_name": "Washington",
                "cdc_profile_amount": Decimal("110.00"),
                "row_count": 1,
            }
        ]
    )

    baseline_rows = profile_calibration.build_normalized_state_funding_rows(
        source_system="usaspending",
        fiscal_years=[2021],
        cdc_reference_map=reference_map,
        support_map=support_map,
    )
    candidate_rows = review_overlay.build_manual_review_exception_candidate_rows(
        methodology_version=profile_calibration.METHODOLOGY_VERSION,
        review_payload=_review_payload(),
        recommendations_payload=_recommendations_payload(),
    )
    after_rows = profile_calibration.build_normalized_state_funding_rows(
        source_system="usaspending",
        fiscal_years=[2021],
        cdc_reference_map=reference_map,
        support_map=support_map,
    )

    assert candidate_rows
    assert all(row["apply_in_production"] is False for row in candidate_rows)
    assert [
        {key: value for key, value in row.items() if key not in {"refreshed_at", "created_at", "updated_at"}}
        for row in after_rows
    ] == [
        {key: value for key, value in row.items() if key not in {"refreshed_at", "created_at", "updated_at"}}
        for row in baseline_rows
    ]
