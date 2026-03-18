from __future__ import annotations

import json
from decimal import Decimal

from app.recon import diagnostics


class _FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def one(self):
        if len(self._rows) != 1:
            raise AssertionError(f"Expected exactly one row, got {len(self._rows)}")
        return self._rows[0]


class _FakeConnection:
    def __init__(self, handlers):
        self._handlers = handlers

    def execute(self, statement, params=None):
        sql = str(statement)
        for needle, rows in self._handlers.items():
            if needle in sql:
                return _FakeResult(rows(params) if callable(rows) else rows)
        raise AssertionError(f"Unhandled SQL in test fake connection: {sql}")


def test_build_fy2021_residual_diagnostics_payload_highlights_mixed_multi_account_worsening(
    monkeypatch,
    tmp_path,
) -> None:
    before_snapshot_path = tmp_path / "before.json"
    before_snapshot_path.write_text(
        json.dumps(
            {
                "lookup_rows": [
                    {
                        "federal_account_symbol": "075-0943",
                        "funding_stream_guess": "regular_appropriation",
                        "effective_profile_relevant": True,
                    },
                    {
                        "federal_account_symbol": "075-0140",
                        "funding_stream_guess": "other_emergency_or_disaster",
                        "effective_profile_relevant": None,
                    },
                    {
                        "federal_account_symbol": "075-0512",
                        "funding_stream_guess": "transfer_or_special",
                        "effective_profile_relevant": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        diagnostics,
        "_fetch_fy2021_rows",
        lambda _connection, *, state_code_to_name: [
            {
                "award_type": "assistance",
                "source_system": "assistance",
                "source_transaction_id": "wa-mixed-transfer",
                "fiscal_year": 2021,
                "state_code": "WA",
                "state_name": state_code_to_name["WA"],
                "aln_or_code": "93.323",
                "listing_or_award_title": "Core public health with transfer contamination",
                "award_description": None,
                "effective_funding_stream": "transfer_or_special",
                "funding_scope_method": "mixed",
                "effective_funding_scope": "federal_health_transfer",
                "include_in_profile_scope": None,
                "inclusion_weight": None,
                "decision_context": "cdc_domestic_mixed_program_transfer_conservative",
                "transaction_obligated_amount": Decimal("60.00"),
                "federal_account_symbol": "075-0512; 075-0943",
                "federal_account_titles_combined": "Payments to Health Care Trust Funds | CDC Wide Activities and Program Support",
                "federal_account_count": 2,
                "federal_account_combination_key": "075-0512|075-0943",
                "component_account_scopes": [],
                "component_scope_count": 2,
                "has_mixed_scopes": True,
                "account_structure_type": "multi_account_mixed_scope",
                "multi_account_interpretation": "mixed_program_transfer",
                "manual_review_recommended": False,
                "emergency_related": False,
                "transfer_related": True,
                "procurement_related": False,
                "research_related": False,
                "international_related": False,
                "special_transfer_related": False,
                "unknown_related": False,
                "conservative_inclusion_reason": "Mixed core and transfer without an exact split.",
                "raw_amount": Decimal("60.00"),
                "normalized_amount": Decimal("0.00"),
            },
            {
                "award_type": "assistance",
                "source_system": "assistance",
                "source_transaction_id": "wa-mixed-emergency",
                "fiscal_year": 2021,
                "state_code": "WA",
                "state_name": state_code_to_name["WA"],
                "aln_or_code": "93.354",
                "listing_or_award_title": "Core public health with emergency scope mix",
                "award_description": None,
                "effective_funding_stream": "other_emergency_or_disaster",
                "funding_scope_method": "mixed",
                "effective_funding_scope": "emergency_public_health",
                "include_in_profile_scope": None,
                "inclusion_weight": None,
                "decision_context": "cdc_domestic_mixed_core_emergency_conservative",
                "transaction_obligated_amount": Decimal("50.00"),
                "federal_account_symbol": "075-0140; 075-0943",
                "federal_account_titles_combined": "Public Health and Social Services Emergency Fund | CDC Wide Activities and Program Support",
                "federal_account_count": 2,
                "federal_account_combination_key": "075-0140|075-0943",
                "component_account_scopes": [],
                "component_scope_count": 2,
                "has_mixed_scopes": True,
                "account_structure_type": "multi_account_mixed_scope",
                "multi_account_interpretation": "mixed_core_emergency",
                "manual_review_recommended": False,
                "emergency_related": True,
                "transfer_related": False,
                "procurement_related": False,
                "research_related": False,
                "international_related": False,
                "special_transfer_related": False,
                "unknown_related": False,
                "conservative_inclusion_reason": "Mixed core and emergency without an exact split.",
                "raw_amount": Decimal("50.00"),
                "normalized_amount": Decimal("0.00"),
            },
            {
                "award_type": "assistance",
                "source_system": "assistance",
                "source_transaction_id": "ga-single-core",
                "fiscal_year": 2021,
                "state_code": "GA",
                "state_name": state_code_to_name["GA"],
                "aln_or_code": "93.323",
                "listing_or_award_title": "Core public health",
                "award_description": None,
                "effective_funding_stream": "regular_appropriation",
                "funding_scope_method": "verified_csv",
                "effective_funding_scope": "core_public_health",
                "include_in_profile_scope": True,
                "inclusion_weight": Decimal("1.00"),
                "decision_context": "cdc_domestic_core_public_health",
                "transaction_obligated_amount": Decimal("40.00"),
                "federal_account_symbol": "075-0943",
                "federal_account_titles_combined": "CDC Wide Activities and Program Support",
                "federal_account_count": 1,
                "federal_account_combination_key": "075-0943",
                "component_account_scopes": [],
                "component_scope_count": 1,
                "has_mixed_scopes": False,
                "account_structure_type": "single_account",
                "multi_account_interpretation": "single_account",
                "manual_review_recommended": False,
                "emergency_related": False,
                "transfer_related": False,
                "procurement_related": False,
                "research_related": False,
                "international_related": False,
                "special_transfer_related": False,
                "unknown_related": False,
                "conservative_inclusion_reason": None,
                "raw_amount": Decimal("40.00"),
                "normalized_amount": Decimal("40.00"),
            },
        ],
    )

    payload = diagnostics.build_fy2021_residual_diagnostics_payload(
        connection=None,
        before_snapshot_path=before_snapshot_path,
        state_code_to_name={"WA": "Washington", "GA": "Georgia"},
    )

    structure_rows = {
        row["account_structure_type"]: row
        for row in payload["before_vs_after_fy2021_by_account_structure_type"]
    }
    assert payload["conclusion"]["primary_worsening_bucket"] == "mixed multi-account attribution"
    assert payload["top_100_fy2021_residual_contributor_rows_national"][0]["state_code"] == "WA"
    assert payload["fy2021_summary_by_account_structure_type"][0]["account_structure_type"] == "multi_account_mixed_scope"
    assert structure_rows["single_account"]["after_normalized_amount"] == Decimal("40.00")


def test_build_funding_scope_refinement_summary_payload_includes_examples_and_unknowns(tmp_path) -> None:
    before_snapshot_path = tmp_path / "before.json"
    profile_scope_summary_path = tmp_path / "profile_scope_build_summary.json"
    calibration_summary_path = tmp_path / "profile_calibration_summary.json"

    before_snapshot_path.write_text(
        json.dumps(
            {
                "profile_scope_build_summary": {
                    "methodology_version": "before-profile",
                    "included_assistance_total": "10.00",
                    "excluded_assistance_total": "0.00",
                    "uncertain_assistance_total": "5.00",
                    "included_contract_total": "2.00",
                    "excluded_contract_total": "1.00",
                    "uncertain_contract_total": "0.00",
                },
                "profile_calibration_summary": {
                    "methodology_version": "before-calibration",
                    "residual_stats_by_year": {
                        "2021": {"usaspending": {"avg_abs_residual_pct": "0.80"}}
                    },
                },
                "lookup_rows": [
                    {
                        "federal_account_symbol": "075-0943",
                        "funding_stream_guess": "other_emergency_or_disaster",
                        "effective_profile_relevant": False,
                    }
                ],
                "residual_rows": [
                    {
                        "source_system": "usaspending",
                        "fiscal_year": 2021,
                        "state_code": "WA",
                        "residual_pct": "0.90",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    profile_scope_summary_path.write_text(
        json.dumps(
            {
                "methodology_version": "after-profile",
                "included_assistance_total": "12.00",
                "excluded_assistance_total": "1.00",
                "uncertain_assistance_total": "3.00",
                "included_contract_total": "2.00",
                "excluded_contract_total": "2.00",
                "uncertain_contract_total": "1.00",
                "row_count_by_account_structure_type": {"single_account": 3},
                "raw_amount_by_account_structure_type": {"single_account": "15.00"},
                "row_count_by_multi_account_interpretation": {"single_account": 3},
                "manual_review_recommended_row_count": 0,
            }
        ),
        encoding="utf-8",
    )
    calibration_summary_path.write_text(
        json.dumps(
            {
                "methodology_version": "after-calibration",
                "residual_stats_by_year": {
                    "2021": {"usaspending": {"avg_abs_residual_pct": "0.40"}}
                },
                "funding_scope_component_totals_by_year": {
                    "2021": {"usaspending": {"core_public_health": "12.00"}}
                },
            }
        ),
        encoding="utf-8",
    )

    connection = _FakeConnection(
        {
            "WHERE effective_funding_scope = 'unknown'": [
                {
                    "federal_account_symbol": "075-9999",
                    "account_title": None,
                    "observed_total_obligations": Decimal("50.00"),
                    "effective_funding_stream": "unknown",
                    "effective_profile_relevant": None,
                    "funding_scope_method": "rule:unknown",
                }
            ],
            "FROM recon.federal_account_lookup": [
                {
                    "federal_account_symbol": "075-0943",
                    "account_title": "CDC Wide Activities and Program Support",
                    "effective_funding_scope": "core_public_health",
                    "funding_scope_guess": "core_public_health",
                    "funding_scope_method": "verified_csv",
                    "effective_profile_relevant": True,
                    "effective_funding_stream": "regular_appropriation",
                    "effective_scope_guess": "likely_core_cdc",
                    "effective_classification_method": "verified_csv",
                    "observed_total_obligations": Decimal("100.00"),
                },
            ],
            "FROM recon.profile_reconciliation_state_year": [
                {
                    "fiscal_year": 2021,
                    "state_code": "WA",
                    "source_system": "usaspending",
                    "residual_amount": Decimal("20.00"),
                    "residual_pct": Decimal("0.40"),
                    "abs_residual_amount": Decimal("20.00"),
                }
            ],
            "FROM recon.assistance_transactions_profile_enriched": lambda params: (
                [
                    {
                        "source_transaction_id": "assist-1",
                        "fiscal_year": 2021,
                        "state_code": "WA",
                        "assistance_listing_number": "93.323",
                        "assistance_listing_title": "Core public health",
                        "federal_account_symbol": "075-0943",
                        "effective_funding_scope": "core_public_health",
                        "decision_context": params["context"],
                        "include_in_profile_scope": True,
                        "transaction_obligated_amount": Decimal("12.00"),
                    }
                ]
                if params["context"] == "cdc_domestic_core_public_health"
                else []
            ),
        }
    )

    payload = diagnostics.build_funding_scope_refinement_summary_payload(
        connection,
        before_snapshot_path=before_snapshot_path,
        profile_scope_summary_path=profile_scope_summary_path,
        calibration_summary_path=calibration_summary_path,
    )

    assert payload["methodology_versions"]["profile_scope_after"] == "after-profile"
    assert payload["top_accounts_reclassified"][0]["federal_account_symbol"] == "075-0943"
    assert payload["before_vs_after_residual_stats_by_year"]["2021"]["after_avg_abs_residual_pct"] == "0.40"
    assert payload["example_assistance_rows"]["core_public_health_included"]["source_transaction_id"] == "assist-1"
    assert payload["still_unknown_high_dollar_accounts"][0]["federal_account_symbol"] == "075-9999"


def test_build_fy2021_mixed_program_transfer_review_payload_groups_wa_rows(monkeypatch, tmp_path) -> None:
    before_snapshot_path = tmp_path / "before.json"
    before_snapshot_path.write_text(
        json.dumps(
            {
                "lookup_rows": [
                    {
                        "federal_account_symbol": "075-0943",
                        "funding_stream_guess": "regular_appropriation",
                        "effective_profile_relevant": True,
                    },
                    {
                        "federal_account_symbol": "075-0512",
                        "funding_stream_guess": "transfer_or_special",
                        "effective_profile_relevant": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        diagnostics,
        "_fetch_fy2021_rows",
        lambda _connection, *, state_code_to_name: [
            {
                "award_type": "assistance",
                "source_system": "assistance",
                "source_transaction_id": "wa-elc",
                "fiscal_year": 2021,
                "state_code": "WA",
                "state_name": state_code_to_name["WA"],
                "aln_or_code": "93.323",
                "listing_or_award_title": "Epidemiology and Laboratory Capacity",
                "award_description": None,
                "effective_funding_stream": "transfer_or_special",
                "funding_scope_method": "mixed",
                "effective_funding_scope": "federal_health_transfer",
                "include_in_profile_scope": None,
                "inclusion_weight": None,
                "decision_context": "cdc_domestic_mixed_program_transfer_conservative",
                "transaction_obligated_amount": Decimal("60.00"),
                "federal_account_symbol": "075-0512; 075-0943",
                "federal_account_titles_combined": "Grants to States for Medicaid | CDC Wide Activities and Program Support",
                "federal_account_count": 2,
                "federal_account_combination_key": "075-0512|075-0943",
                "component_account_scopes": [
                    {
                        "federal_account_symbol": "075-0512",
                        "effective_funding_scope": "federal_health_transfer",
                    },
                    {
                        "federal_account_symbol": "075-0943",
                        "effective_funding_scope": "core_public_health",
                    },
                ],
                "component_scope_count": 2,
                "has_mixed_scopes": True,
                "account_structure_type": "multi_account_mixed_scope",
                "multi_account_interpretation": "mixed_program_transfer",
                "manual_review_recommended": False,
                "emergency_related": False,
                "transfer_related": True,
                "procurement_related": False,
                "research_related": False,
                "international_related": False,
                "special_transfer_related": False,
                "unknown_related": False,
                "conservative_inclusion_reason": "Mixed core and transfer without an exact split.",
                "raw_amount": Decimal("60.00"),
                "normalized_amount": Decimal("0.00"),
            },
            {
                "award_type": "assistance",
                "source_system": "assistance",
                "source_transaction_id": "or-immunization",
                "fiscal_year": 2021,
                "state_code": "OR",
                "state_name": "Oregon",
                "aln_or_code": "93.268",
                "listing_or_award_title": "Immunization Cooperative Agreements",
                "award_description": None,
                "effective_funding_stream": "transfer_or_special",
                "funding_scope_method": "mixed",
                "effective_funding_scope": "federal_health_transfer",
                "include_in_profile_scope": None,
                "inclusion_weight": None,
                "decision_context": "cdc_domestic_mixed_program_transfer_conservative",
                "transaction_obligated_amount": Decimal("40.00"),
                "federal_account_symbol": "075-0512; 075-0951; 075-0943",
                "federal_account_titles_combined": "Grants to States for Medicaid | Grants to States for Medicaid | CDC Wide Activities and Program Support",
                "federal_account_count": 3,
                "federal_account_combination_key": "075-0512|075-0943|075-0951",
                "component_account_scopes": [],
                "component_scope_count": 2,
                "has_mixed_scopes": True,
                "account_structure_type": "multi_account_mixed_scope",
                "multi_account_interpretation": "mixed_program_transfer",
                "manual_review_recommended": False,
                "emergency_related": False,
                "transfer_related": True,
                "procurement_related": False,
                "research_related": False,
                "international_related": False,
                "special_transfer_related": False,
                "unknown_related": False,
                "conservative_inclusion_reason": "Mixed core and transfer without an exact split.",
                "raw_amount": Decimal("40.00"),
                "normalized_amount": Decimal("0.00"),
            },
        ],
    )

    payload = diagnostics.build_fy2021_mixed_program_transfer_review_payload(
        connection=None,
        before_snapshot_path=before_snapshot_path,
        state_code_to_name={"WA": "Washington"},
    )

    assert payload["row_count"] == 2
    assert payload["national_top_rows"][0]["state"] == "Washington"
    assert payload["national_top_rows"][0]["program_family_heuristic_label"] == "ELC"
    assert payload["washington_rows"][0]["award_identifier"] == "wa-elc"
    assert payload["summary_by_program_family"][0]["program_family_label"] == "ELC"
    assert payload["summary_by_assistance_vs_contracts"][0]["award_type"] == "assistance"


def test_build_mixed_program_transfer_exception_recommendations_payload_stays_manual_review_only() -> None:
    review_payload = {
        "summary_by_program_family": [
            {
                "program_family_label": "ELC",
                "row_count": 10,
                "raw_amount": Decimal("100.00"),
                "normalized_amount": Decimal("0.00"),
                "residual_contribution_estimate": Decimal("100.00"),
            },
            {
                "program_family_label": "immunization",
                "row_count": 5,
                "raw_amount": Decimal("50.00"),
                "normalized_amount": Decimal("0.00"),
                "residual_contribution_estimate": Decimal("50.00"),
            },
        ],
        "summary_by_aln": [
            {
                "aln_or_code": "93.323",
                "listing_or_award_title": "Epidemiology and Laboratory Capacity",
            },
            {
                "aln_or_code": "93.268",
                "listing_or_award_title": "Immunization Cooperative Agreements",
            },
            {
                "aln_or_code": "93.185",
                "listing_or_award_title": "Immunization Research",
            },
            {
                "aln_or_code": "D318",
                "listing_or_award_title": "Other Functions Immunization Systems Maintenance and Service",
            },
            {
                "aln_or_code": "R604",
                "listing_or_award_title": "2017 Vaccine Distribution for Other Functions",
            },
        ],
        "summary_by_federal_account_combination_key": [
            {
                "federal_account_combination_key": "075-0512|075-0943",
            },
            {
                "federal_account_combination_key": "075-0512|075-0943|075-0951",
            },
        ],
        "washington_rows": [
            {
                "program_family_label": "ELC",
                "federal_account_combination_key": "075-0512|075-0943",
            }
        ],
    }

    payload = diagnostics.build_mixed_program_transfer_exception_recommendations_payload(review_payload)

    assert payload["production_change_recommended"] is False
    assert payload["production_methodology_should_remain_unchanged"] is True
    assert payload["candidate_recommendations"][0]["status"] == "manual_review_only"
    assert payload["candidate_recommendations"][1]["proposed_conditions"]["alns"] == ["93.268", "93.185", "D318"]


def test_program_family_label_treats_vaccine_distribution_as_immunization() -> None:
    assert (
        diagnostics._program_family_label(
            {
                "aln_or_code": "R604",
                "listing_or_award_title": "2017 Vaccine Distribution for Other Functions",
                "award_description": None,
            }
        )
        == "immunization"
    )
