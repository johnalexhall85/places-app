from __future__ import annotations

import csv
from decimal import Decimal

from app.recon import federal_accounts


def _contract_row(**overrides):
    row = {
        "source_system": federal_accounts.SOURCE_CONTRACTS,
        "federal_account_symbol": "075-0943",
        "fiscal_year": 2024,
        "obligation_amount": Decimal("100.00"),
        "treasury_account_symbol": "075-2020/2022-0943-000",
        "awarding_agency_name": "Centers for Disease Control and Prevention",
        "funding_agency_name": "Centers for Disease Control and Prevention",
        "psc_or_aln": "6505",
        "psc_or_aln_description": "Biologicals and vaccines",
        "award_description": "Vaccines for Children vaccine procurement",
        "transaction_description": None,
        "prime_award_base_transaction_description": None,
        "naics_description": None,
        "appropriation_type": None,
        "appropriation_subtype": None,
        "raw_emergency_code": None,
        "program_activity_name": None,
    }
    row.update(overrides)
    return row


def _assistance_row(**overrides):
    row = {
        "source_system": federal_accounts.SOURCE_ASSISTANCE,
        "federal_account_symbol": "075-0950",
        "fiscal_year": 2023,
        "obligation_amount": Decimal("250.00"),
        "treasury_account_symbol": None,
        "awarding_agency_name": "Centers for Disease Control and Prevention",
        "funding_agency_name": "Centers for Disease Control and Prevention",
        "psc_or_aln": "93.323",
        "psc_or_aln_description": "Epidemiology and Laboratory Capacity",
        "award_description": None,
        "transaction_description": "CDC cooperative agreement",
        "prime_award_base_transaction_description": None,
        "naics_description": None,
        "appropriation_type": "regular",
        "appropriation_subtype": None,
        "raw_emergency_code": None,
        "program_activity_name": "Epidemiology and Laboratory Capacity",
    }
    row.update(overrides)
    return row


def test_build_lookup_rows_seeds_distinct_observed_symbols() -> None:
    observed_rows = [
        _contract_row(federal_account_symbol="075-0943;075-4553"),
        _assistance_row(federal_account_symbol="019-1030;075-0950"),
    ]

    rows = federal_accounts.build_lookup_rows(observed_rows)

    assert [row["federal_account_symbol"] for row in rows] == [
        "019-1030",
        "075-0943",
        "075-0950",
        "075-4553",
    ]
    assert rows[1]["observed_in_contracts"] is True
    assert rows[1]["observed_in_assistance"] is False
    assert rows[2]["observed_in_assistance"] is True
    assert rows[1]["agency_identifier"] == "075"
    assert rows[1]["main_account_code"] == "0943"


def test_build_observation_rows_rolls_up_source_year_hints() -> None:
    observed_rows = [
        _contract_row(
            federal_account_symbol="075-0943",
            obligation_amount=Decimal("100.00"),
            award_description="Vaccines for Children vaccine procurement",
        ),
        _contract_row(
            federal_account_symbol="075-0943",
            obligation_amount=Decimal("50.00"),
            award_description="Vaccines for Children ancillary logistics",
        ),
        _assistance_row(
            federal_account_symbol="075-0950",
            obligation_amount=Decimal("250.00"),
            psc_or_aln="93.323",
        ),
    ]

    rows = federal_accounts.build_observation_rows(observed_rows)

    assert rows == [
        {
            "federal_account_symbol": "075-0943",
            "source_system": "contracts",
            "fiscal_year": 2024,
            "transaction_count": 2,
            "total_obligations": Decimal("150.00"),
            "awarding_agency_name": "Centers for Disease Control and Prevention",
            "funding_agency_name": "Centers for Disease Control and Prevention",
            "top_psc_or_aln": "6505",
            "top_description_hint": "Vaccines for Children vaccine procurement",
        },
        {
            "federal_account_symbol": "075-0950",
            "source_system": "assistance",
            "fiscal_year": 2023,
            "transaction_count": 1,
            "total_obligations": Decimal("250.00"),
            "awarding_agency_name": "Centers for Disease Control and Prevention",
            "funding_agency_name": "Centers for Disease Control and Prevention",
            "top_psc_or_aln": "93.323",
            "top_description_hint": "CDC cooperative agreement",
        },
    ]


def test_apply_classification_rows_uses_rule_table_metrics() -> None:
    observed_rows = [
        _contract_row(
            federal_account_symbol="075-0943",
            obligation_amount=Decimal("125.00"),
            award_description="Vaccines for Children vaccine procurement",
        ),
        _contract_row(
            federal_account_symbol="075-0943",
            obligation_amount=Decimal("25.00"),
            award_description="Vaccines for Children cold-chain support",
        ),
    ]
    lookup_rows = federal_accounts.build_lookup_rows(observed_rows)
    rules = federal_accounts.load_classification_rule_rows()

    classified_rows = federal_accounts.apply_classification_rows(lookup_rows, observed_rows, rules)

    assert classified_rows[0]["funding_stream_guess"] == federal_accounts.FUNDING_STREAM_REGULAR
    assert classified_rows[0]["funding_scope_guess"] == federal_accounts.FUNDING_SCOPE_CORE_PUBLIC_HEALTH
    assert classified_rows[0]["appropriations_scope_guess"] == federal_accounts.SCOPE_CORE_CDC
    assert classified_rows[0]["likely_profile_relevant"] is True
    assert classified_rows[0]["likely_core_public_health"] is True
    assert classified_rows[0]["effective_funding_scope"] == federal_accounts.FUNDING_SCOPE_CORE_PUBLIC_HEALTH
    assert classified_rows[0]["classification_method"].startswith(
        "verified_csv:federal_account_symbol:exact:075-0943"
    )


def test_apply_classification_rows_sets_emergency_and_medicaid_scopes() -> None:
    observed_rows = [
        _assistance_row(
            federal_account_symbol="075-0140",
            award_description=None,
            transaction_description="Emergency response agreement",
        ),
        _assistance_row(
            federal_account_symbol="075-0512",
            transaction_description="Medicaid transfer support",
        ),
        _assistance_row(
            federal_account_symbol="075-0951",
            transaction_description="Medicaid grants support",
        ),
    ]

    lookup_rows = federal_accounts.build_lookup_rows(observed_rows)
    rules = federal_accounts.load_classification_rule_rows()
    classified_rows = federal_accounts.apply_classification_rows(lookup_rows, observed_rows, rules)
    rows_by_symbol = {row["federal_account_symbol"]: row for row in classified_rows}

    assert rows_by_symbol["075-0140"]["effective_funding_scope"] == federal_accounts.FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH
    assert rows_by_symbol["075-0140"]["effective_profile_relevant"] is None
    assert rows_by_symbol["075-0512"]["effective_funding_scope"] == federal_accounts.FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER
    assert rows_by_symbol["075-0512"]["effective_profile_relevant"] is False
    assert rows_by_symbol["075-0951"]["effective_funding_scope"] == federal_accounts.FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER
    assert rows_by_symbol["075-0951"]["effective_profile_relevant"] is False


def test_apply_classification_rows_sets_biomedical_and_international_scopes() -> None:
    observed_rows = [
        _assistance_row(
            federal_account_symbol="075-0849",
            awarding_agency_name="National Institutes of Health",
            funding_agency_name="National Institutes of Health",
            transaction_description="Cancer research grant",
        ),
        _assistance_row(
            federal_account_symbol="019-1031",
            awarding_agency_name="Department of State",
            funding_agency_name="Department of State",
            transaction_description="Global health programs assistance",
        ),
    ]

    lookup_rows = federal_accounts.build_lookup_rows(observed_rows)
    rules = federal_accounts.load_classification_rule_rows()
    classified_rows = federal_accounts.apply_classification_rows(lookup_rows, observed_rows, rules)
    rows_by_symbol = {row["federal_account_symbol"]: row for row in classified_rows}

    assert rows_by_symbol["075-0849"]["effective_funding_scope"] == federal_accounts.FUNDING_SCOPE_BIOMEDICAL_RESEARCH
    assert rows_by_symbol["075-0849"]["effective_profile_relevant"] is False
    assert rows_by_symbol["075-0849"]["likely_biomedical_research"] is True
    assert rows_by_symbol["019-1031"]["effective_funding_scope"] == federal_accounts.FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE
    assert rows_by_symbol["019-1031"]["effective_profile_relevant"] is False
    assert rows_by_symbol["019-1031"]["likely_international_health_assistance"] is True


def test_apply_classification_rows_populates_verified_account_titles() -> None:
    observed_rows = [_assistance_row(federal_account_symbol="075-0943")]

    lookup_rows = federal_accounts.build_lookup_rows(observed_rows)
    rules = federal_accounts.load_classification_rule_rows()
    classified_rows = federal_accounts.apply_classification_rows(lookup_rows, observed_rows, rules)

    assert classified_rows[0]["account_title"] == "CDC Wide Activities and Program Support"
    assert classified_rows[0]["classification_method"].startswith("verified_csv:")
    assert classified_rows[0]["funding_scope_method"] == federal_accounts.VERIFIED_EFFECTIVE_METHOD


def test_apply_classification_rows_uses_verified_csv_for_newly_verified_support_accounts() -> None:
    observed_rows = [
        _contract_row(
            federal_account_symbol="075-0120",
            awarding_agency_name="Centers for Disease Control and Prevention",
            funding_agency_name="Centers for Disease Control and Prevention",
            award_description="Departmental management support contract",
        ),
        _contract_row(
            federal_account_symbol="075-4553",
            award_description="CDC working capital support services",
        ),
        _contract_row(
            federal_account_symbol="075-0960",
            award_description="CDC facilities maintenance",
        ),
        _contract_row(
            federal_account_symbol="075-0954",
            award_description="Special compensation program support",
        ),
        _contract_row(
            federal_account_symbol="075-5146",
            award_description="Cooperative research and development agreement support",
        ),
    ]

    lookup_rows = federal_accounts.build_lookup_rows(observed_rows)
    rules = federal_accounts.load_classification_rule_rows()
    classified_rows = federal_accounts.apply_classification_rows(lookup_rows, observed_rows, rules)
    rows_by_symbol = {row["federal_account_symbol"]: row for row in classified_rows}

    assert rows_by_symbol["075-0120"]["effective_funding_scope"] == federal_accounts.FUNDING_SCOPE_PROCUREMENT_SUPPORT
    assert rows_by_symbol["075-0120"]["funding_scope_method"] == federal_accounts.VERIFIED_EFFECTIVE_METHOD
    assert rows_by_symbol["075-0120"]["classification_method"].startswith("verified_csv:")
    assert rows_by_symbol["075-4553"]["effective_funding_scope"] == federal_accounts.FUNDING_SCOPE_PROCUREMENT_SUPPORT
    assert rows_by_symbol["075-4553"]["funding_scope_method"] == federal_accounts.VERIFIED_EFFECTIVE_METHOD
    assert rows_by_symbol["075-0960"]["effective_funding_scope"] == federal_accounts.FUNDING_SCOPE_PROCUREMENT_SUPPORT
    assert rows_by_symbol["075-0954"]["effective_funding_scope"] == federal_accounts.FUNDING_SCOPE_SPECIAL_TRANSFER
    assert rows_by_symbol["075-0954"]["effective_profile_relevant"] is None
    assert rows_by_symbol["075-5146"]["effective_funding_scope"] == federal_accounts.FUNDING_SCOPE_PROCUREMENT_SUPPORT


def test_apply_classification_rows_uses_verified_csv_for_former_fallback_accounts() -> None:
    observed_rows = [
        _contract_row(
            federal_account_symbol="075-0125",
            award_description="Departmental transfer support",
        ),
        _assistance_row(
            federal_account_symbol="075-0961",
            awarding_agency_name="Centers for Disease Control and Prevention",
            funding_agency_name="Centers for Disease Control and Prevention",
            transaction_description="Other public health program support",
        ),
        _assistance_row(
            federal_account_symbol="075-0844",
            awarding_agency_name="National Institutes of Health",
            funding_agency_name="National Institutes of Health",
            transaction_description="Biomedical research support",
        ),
        _contract_row(
            federal_account_symbol="075-8514",
            award_description="Support services procurement",
        ),
        _assistance_row(
            federal_account_symbol="075-0131",
            transaction_description="Special transfer support",
        ),
        _assistance_row(
            federal_account_symbol="075-1362",
            awarding_agency_name="Substance Abuse and Mental Health Services Administration",
            funding_agency_name="Substance Abuse and Mental Health Services Administration",
            transaction_description="Behavioral health public health support",
        ),
        _assistance_row(
            federal_account_symbol="075-0843",
            awarding_agency_name="National Institutes of Health",
            funding_agency_name="National Institutes of Health",
            transaction_description="NIH research support",
        ),
    ]

    lookup_rows = federal_accounts.build_lookup_rows(observed_rows)
    rules = federal_accounts.load_classification_rule_rows()
    classified_rows = federal_accounts.apply_classification_rows(lookup_rows, observed_rows, rules)
    rows_by_symbol = {row["federal_account_symbol"]: row for row in classified_rows}

    assert rows_by_symbol["075-0125"]["effective_funding_scope"] == federal_accounts.FUNDING_SCOPE_SPECIAL_TRANSFER
    assert rows_by_symbol["075-0961"]["effective_funding_scope"] == federal_accounts.FUNDING_SCOPE_OTHER_PUBLIC_HEALTH
    assert rows_by_symbol["075-0844"]["effective_funding_scope"] == federal_accounts.FUNDING_SCOPE_BIOMEDICAL_RESEARCH
    assert rows_by_symbol["075-8514"]["effective_funding_scope"] == federal_accounts.FUNDING_SCOPE_PROCUREMENT_SUPPORT
    assert rows_by_symbol["075-0131"]["effective_funding_scope"] == federal_accounts.FUNDING_SCOPE_SPECIAL_TRANSFER
    assert rows_by_symbol["075-1362"]["effective_funding_scope"] == federal_accounts.FUNDING_SCOPE_OTHER_PUBLIC_HEALTH
    assert rows_by_symbol["075-0843"]["effective_funding_scope"] == federal_accounts.FUNDING_SCOPE_BIOMEDICAL_RESEARCH
    for symbol in (
        "075-0125",
        "075-0961",
        "075-0844",
        "075-8514",
        "075-0131",
        "075-1362",
        "075-0843",
    ):
        assert rows_by_symbol[symbol]["funding_scope_method"] == federal_accounts.VERIFIED_EFFECTIVE_METHOD
        assert rows_by_symbol[symbol]["classification_method"].startswith("verified_csv:")


def test_apply_classification_rows_leaves_unmapped_accounts_on_fallback_logic() -> None:
    observed_rows = [
        _assistance_row(
            federal_account_symbol="075-7777",
            awarding_agency_name="Centers for Disease Control and Prevention",
            funding_agency_name="Centers for Disease Control and Prevention",
            transaction_description="Regular CDC cooperative agreement",
            program_activity_name="CDC preparedness work",
        )
    ]

    lookup_rows = federal_accounts.build_lookup_rows(observed_rows)
    rules = federal_accounts.load_classification_rule_rows()
    classified_rows = federal_accounts.apply_classification_rows(lookup_rows, observed_rows, rules)

    assert classified_rows[0]["classification_method"].startswith("rule:")
    assert classified_rows[0]["funding_scope_method"] != federal_accounts.VERIFIED_EFFECTIVE_METHOD
    assert classified_rows[0]["effective_funding_scope"] in {
        federal_accounts.FUNDING_SCOPE_CORE_PUBLIC_HEALTH,
        federal_accounts.FUNDING_SCOPE_UNKNOWN,
    }


def test_apply_effective_classification_prefers_manual_overrides() -> None:
    row = {
        "funding_stream_guess": federal_accounts.FUNDING_STREAM_REGULAR,
        "funding_scope_guess": federal_accounts.FUNDING_SCOPE_CORE_PUBLIC_HEALTH,
        "appropriations_scope_guess": federal_accounts.SCOPE_CORE_CDC,
        "likely_profile_relevant": True,
        "manual_funding_stream": federal_accounts.FUNDING_STREAM_TRANSFER_SPECIAL,
        "manual_funding_scope": federal_accounts.FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER,
        "manual_scope_guess": federal_accounts.SCOPE_SPECIAL_TRANSFER,
        "manual_profile_relevant": False,
        "is_manually_verified": True,
        "classification_method": "rule:regular_obligation_ratio:ge:0.60",
    }

    effective = federal_accounts.apply_effective_classification(row)

    assert effective["effective_funding_stream"] == federal_accounts.FUNDING_STREAM_TRANSFER_SPECIAL
    assert effective["effective_funding_scope"] == federal_accounts.FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER
    assert effective["effective_scope_guess"] == federal_accounts.SCOPE_SPECIAL_TRANSFER
    assert effective["effective_profile_relevant"] is False
    assert effective["effective_classification_method"] == "manual_override"
    assert effective["funding_scope_method"] == "manual_override"


def test_apply_effective_classification_prefers_verified_mapping_over_manual_override() -> None:
    row = {
        "funding_stream_guess": federal_accounts.FUNDING_STREAM_REGULAR,
        "funding_scope_guess": federal_accounts.FUNDING_SCOPE_CORE_PUBLIC_HEALTH,
        "appropriations_scope_guess": federal_accounts.SCOPE_CORE_CDC,
        "likely_profile_relevant": True,
        "manual_funding_stream": federal_accounts.FUNDING_STREAM_TRANSFER_SPECIAL,
        "manual_funding_scope": federal_accounts.FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER,
        "manual_scope_guess": federal_accounts.SCOPE_SPECIAL_TRANSFER,
        "manual_profile_relevant": False,
        "is_manually_verified": True,
        "classification_method": "verified_csv:federal_account_symbol:exact:075-0943",
    }

    effective = federal_accounts.apply_effective_classification(row)

    assert effective["effective_funding_stream"] == federal_accounts.FUNDING_STREAM_REGULAR
    assert effective["effective_funding_scope"] == federal_accounts.FUNDING_SCOPE_CORE_PUBLIC_HEALTH
    assert effective["effective_scope_guess"] == federal_accounts.SCOPE_CORE_CDC
    assert effective["effective_profile_relevant"] is True
    assert effective["effective_classification_method"] == federal_accounts.VERIFIED_EFFECTIVE_METHOD


def test_build_verified_account_mapping_summary_payload_marks_verified_and_fallback_accounts() -> None:
    payload = federal_accounts.build_verified_account_mapping_summary_payload(
        lookup_rows=[
            {
                "federal_account_symbol": "075-0120",
                "account_title": "General Departmental Management",
                "effective_funding_scope": federal_accounts.FUNDING_SCOPE_PROCUREMENT_SUPPORT,
                "effective_profile_relevant": False,
                "funding_scope_method": federal_accounts.VERIFIED_EFFECTIVE_METHOD,
                "observed_total_obligations": Decimal("10.00"),
            },
            {
                "federal_account_symbol": "075-7777",
                "account_title": None,
                "effective_funding_scope": federal_accounts.FUNDING_SCOPE_UNKNOWN,
                "effective_profile_relevant": None,
                "funding_scope_method": "rule:descriptor_blob:contains:cdc",
                "observed_total_obligations": Decimal("5.00"),
            },
        ],
        verified_rule_rows=[
            {
                "match_value": "075-0120",
                "assigned_account_title": "General Departmental Management",
                "verified_agency": "Departmental Management, Health and Human Services",
                "assigned_funding_scope": federal_accounts.FUNDING_SCOPE_PROCUREMENT_SUPPORT,
                "verified_rationale": "Verified manually.",
            }
        ],
    )

    assert payload["loaded_account_count"] == 1
    assert payload["loaded_accounts"][0]["account_code"] == "075-0120"
    assert payload["loaded_accounts"][0]["funding_scope_method"] == federal_accounts.VERIFIED_EFFECTIVE_METHOD
    assert payload["fallback_account_count"] == 1
    assert payload["fallback_accounts"][0]["federal_account_symbol"] == "075-7777"


def test_build_fallback_account_verification_summary_payload_marks_former_fallbacks_as_verified() -> None:
    payload = federal_accounts.build_fallback_account_verification_summary_payload(
        current_verified_summary={
            "loaded_accounts": [
                {
                    "account_code": symbol,
                    "account_title": f"Title {symbol}",
                    "funding_scope": federal_accounts.FUNDING_SCOPE_PROCUREMENT_SUPPORT,
                    "effective_funding_scope": federal_accounts.FUNDING_SCOPE_PROCUREMENT_SUPPORT,
                    "funding_scope_method": federal_accounts.VERIFIED_EFFECTIVE_METHOD,
                    "effective_profile_relevant": False,
                    "observed_total_obligations": Decimal("1.00"),
                }
                for symbol in federal_accounts.KNOWN_FORMER_FALLBACK_ACCOUNTS
            ],
            "fallback_accounts": [],
        },
        previous_verified_summary={
            "fallback_accounts": [
                {
                    "federal_account_symbol": symbol,
                    "effective_funding_scope": federal_accounts.FUNDING_SCOPE_UNKNOWN,
                    "funding_scope_method": "rule:fallback",
                }
                for symbol in federal_accounts.KNOWN_FORMER_FALLBACK_ACCOUNTS
            ]
        },
    )

    assert payload["former_fallback_account_count"] == len(federal_accounts.KNOWN_FORMER_FALLBACK_ACCOUNTS)
    assert payload["remaining_fallback_account_count"] == 0
    assert payload["all_former_fallback_accounts_verified"] is True


def test_apply_effective_classification_populates_defaults_without_manual_override() -> None:
    row = {
        "funding_stream_guess": federal_accounts.FUNDING_STREAM_REGULAR,
        "funding_scope_guess": federal_accounts.FUNDING_SCOPE_CORE_PUBLIC_HEALTH,
        "appropriations_scope_guess": federal_accounts.SCOPE_CORE_CDC,
        "likely_profile_relevant": True,
        "manual_funding_stream": None,
        "manual_funding_scope": None,
        "manual_scope_guess": None,
        "manual_profile_relevant": None,
        "is_manually_verified": False,
        "classification_method": "rule:regular_obligation_ratio:ge:0.60",
    }

    effective = federal_accounts.apply_effective_classification(row)

    assert effective["effective_funding_stream"] == federal_accounts.FUNDING_STREAM_REGULAR
    assert effective["effective_funding_scope"] == federal_accounts.FUNDING_SCOPE_CORE_PUBLIC_HEALTH
    assert effective["effective_scope_guess"] == federal_accounts.SCOPE_CORE_CDC
    assert effective["effective_profile_relevant"] is True
    assert effective["effective_classification_method"] == "rule:regular_obligation_ratio:ge:0.60"


def test_write_review_csv_sorts_by_obligations_then_confidence(tmp_path) -> None:
    rows = [
        {
            "federal_account_symbol": "075-0950",
            "account_title": None,
            "observed_in_contracts": False,
            "observed_in_assistance": True,
            "first_fiscal_year": 2023,
            "last_fiscal_year": 2024,
            "observed_total_obligations": Decimal("100.00"),
            "funding_stream_guess": federal_accounts.FUNDING_STREAM_REGULAR,
            "appropriations_scope_guess": federal_accounts.SCOPE_CORE_CDC,
            "likely_profile_relevant": True,
            "likely_vfc_related": False,
            "likely_emergency_related": False,
            "likely_arpa_related": False,
            "likely_regular_appropriation": True,
            "classification_confidence": Decimal("0.80"),
            "classification_method": "rule:a",
            "is_manually_verified": False,
        },
        {
            "federal_account_symbol": "075-0943",
            "account_title": None,
            "observed_in_contracts": True,
            "observed_in_assistance": False,
            "first_fiscal_year": 2024,
            "last_fiscal_year": 2024,
            "observed_total_obligations": Decimal("100.00"),
            "funding_stream_guess": federal_accounts.FUNDING_STREAM_PROCUREMENT,
            "appropriations_scope_guess": federal_accounts.SCOPE_PROCUREMENT,
            "likely_profile_relevant": True,
            "likely_vfc_related": True,
            "likely_emergency_related": False,
            "likely_arpa_related": False,
            "likely_regular_appropriation": False,
            "classification_confidence": Decimal("0.30"),
            "classification_method": "rule:b",
            "is_manually_verified": False,
        },
    ]

    review_rows = federal_accounts.build_review_rows(rows)
    output_path = tmp_path / "federal_account_review.csv"
    federal_accounts.write_review_csv(output_path, review_rows)

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        written_rows = list(csv.DictReader(handle))

    assert [row["federal_account_symbol"] for row in written_rows] == ["075-0943", "075-0950"]
    assert written_rows[0]["classification_confidence"] == "0.30"
