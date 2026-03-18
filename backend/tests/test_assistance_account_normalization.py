from __future__ import annotations

from decimal import Decimal

from app.recon import assistance_accounts


def _source_row(**overrides):
    row = {
        "source_row_id": 101,
        "source_transaction_id": "assist-1",
        "award_key": "award-1",
        "fiscal_year": 2023,
        "state_code": "GA",
        "recipient_name": "Georgia Department of Public Health",
        "recipient_country_name": "UNITED STATES",
        "awarding_agency_name": "Centers for Disease Control and Prevention",
        "funding_agency_name": "Centers for Disease Control and Prevention",
        "assistance_listing_number": "93.323",
        "assistance_listing_title": "Epidemiology and Laboratory Capacity",
        "program_activity_name": "Core Public Health",
        "raw_federal_account_symbol": "075-0140; 075-0943; ; 075-0950",
        "raw_treasury_account_symbol": "075-2023/2023-0950-000",
        "appropriation_type": "regular",
        "appropriation_subtype": None,
        "raw_emergency_code": None,
        "transaction_description": "CDC cooperative agreement",
        "prime_award_base_transaction_description": None,
        "transaction_obligated_amount": Decimal("125.00"),
    }
    row.update(overrides)
    return row


def test_split_assistance_federal_account_symbols_preserves_order_and_discards_empty_values() -> None:
    assert assistance_accounts.split_assistance_federal_account_symbols("075-0140; 075-0943; ; 075-0950") == [
        "075-0140",
        "075-0943",
        "075-0950",
    ]


def test_build_assistance_transaction_account_rows_creates_bridge_rows() -> None:
    rows = assistance_accounts.build_assistance_transaction_account_rows([_source_row()])

    assert rows == [
        {
            "source_transaction_id": "assist-1",
            "federal_account_symbol": "075-0140",
            "account_position": 1,
            "source_row_id": 101,
            "award_key": "award-1",
            "fiscal_year": 2023,
            "state_code": "GA",
            "transaction_obligated_amount": Decimal("125.00"),
            "awarding_agency_name": "Centers for Disease Control and Prevention",
            "funding_agency_name": "Centers for Disease Control and Prevention",
            "treasury_account_symbol": "075-2023/2023-0950-000",
            "appropriation_type": "regular",
            "appropriation_subtype": None,
            "raw_emergency_code": None,
            "psc_or_aln": "93.323",
            "psc_or_aln_description": "Epidemiology and Laboratory Capacity",
            "award_description": None,
            "transaction_description": "CDC cooperative agreement",
            "prime_award_base_transaction_description": None,
            "naics_description": None,
            "program_activity_name": "Core Public Health",
            "raw_federal_account_symbol": "075-0140; 075-0943; ; 075-0950",
            "created_at": rows[0]["created_at"],
        },
        {
            "source_transaction_id": "assist-1",
            "federal_account_symbol": "075-0943",
            "account_position": 2,
            "source_row_id": 101,
            "award_key": "award-1",
            "fiscal_year": 2023,
            "state_code": "GA",
            "transaction_obligated_amount": Decimal("125.00"),
            "awarding_agency_name": "Centers for Disease Control and Prevention",
            "funding_agency_name": "Centers for Disease Control and Prevention",
            "treasury_account_symbol": "075-2023/2023-0950-000",
            "appropriation_type": "regular",
            "appropriation_subtype": None,
            "raw_emergency_code": None,
            "psc_or_aln": "93.323",
            "psc_or_aln_description": "Epidemiology and Laboratory Capacity",
            "award_description": None,
            "transaction_description": "CDC cooperative agreement",
            "prime_award_base_transaction_description": None,
            "naics_description": None,
            "program_activity_name": "Core Public Health",
            "raw_federal_account_symbol": "075-0140; 075-0943; ; 075-0950",
            "created_at": rows[1]["created_at"],
        },
        {
            "source_transaction_id": "assist-1",
            "federal_account_symbol": "075-0950",
            "account_position": 3,
            "source_row_id": 101,
            "award_key": "award-1",
            "fiscal_year": 2023,
            "state_code": "GA",
            "transaction_obligated_amount": Decimal("125.00"),
            "awarding_agency_name": "Centers for Disease Control and Prevention",
            "funding_agency_name": "Centers for Disease Control and Prevention",
            "treasury_account_symbol": "075-2023/2023-0950-000",
            "appropriation_type": "regular",
            "appropriation_subtype": None,
            "raw_emergency_code": None,
            "psc_or_aln": "93.323",
            "psc_or_aln_description": "Epidemiology and Laboratory Capacity",
            "award_description": None,
            "transaction_description": "CDC cooperative agreement",
            "prime_award_base_transaction_description": None,
            "naics_description": None,
            "program_activity_name": "Core Public Health",
            "raw_federal_account_symbol": "075-0140; 075-0943; ; 075-0950",
            "created_at": rows[2]["created_at"],
        },
    ]


def test_summary_classifies_mixed_core_and_emergency_accounts_conservatively() -> None:
    source_row = _source_row(raw_federal_account_symbol="075-0140; 075-0943")
    account_rows = assistance_accounts.build_assistance_transaction_account_rows([source_row])
    lookup = {
        "075-0140": {
            "effective_funding_stream": assistance_accounts.STREAM_OTHER_EMERGENCY,
            "effective_funding_scope": assistance_accounts.FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH,
            "funding_scope_method": "verified_csv",
            "effective_scope_guess": assistance_accounts.SCOPE_EMERGENCY,
            "effective_profile_relevant": None,
        },
        "075-0943": {
            "effective_funding_stream": assistance_accounts.STREAM_REGULAR,
            "effective_funding_scope": assistance_accounts.FUNDING_SCOPE_CORE_PUBLIC_HEALTH,
            "funding_scope_method": "verified_csv",
            "effective_scope_guess": assistance_accounts.SCOPE_CORE,
            "effective_profile_relevant": True,
        },
    }

    summary = assistance_accounts.derive_assistance_transaction_account_summary(
        source_row=source_row,
        account_rows=account_rows,
        lookup_by_symbol=lookup,
    )

    assert summary["account_count"] == 2
    assert summary["distinct_account_count"] == 2
    assert summary["effective_funding_stream"] == assistance_accounts.STREAM_OTHER_EMERGENCY
    assert summary["effective_funding_scope"] == assistance_accounts.FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH
    assert summary["effective_scope_guess"] == assistance_accounts.SCOPE_MIXED
    assert summary["effective_profile_relevant"] is None
    assert summary["effective_classification_method"] == assistance_accounts.METHOD_MIXED_CORE_EMERGENCY_CONSERVATIVE
    assert summary["account_structure_type"] == "multi_account_mixed_scope"
    assert summary["multi_account_interpretation"] == "mixed_core_emergency"
    assert summary["federal_account_combination_key"] == "075-0140|075-0943"


def test_summary_keeps_same_scope_multi_account_rows_in_scope() -> None:
    source_row = _source_row(raw_federal_account_symbol="075-0943; 075-0950")
    account_rows = assistance_accounts.build_assistance_transaction_account_rows([source_row])
    lookup = {
        "075-0943": {
            "effective_funding_stream": assistance_accounts.STREAM_REGULAR,
            "effective_funding_scope": assistance_accounts.FUNDING_SCOPE_CORE_PUBLIC_HEALTH,
            "funding_scope_method": "verified_csv",
            "effective_scope_guess": assistance_accounts.SCOPE_CORE,
            "effective_profile_relevant": True,
        },
        "075-0950": {
            "effective_funding_stream": assistance_accounts.STREAM_REGULAR,
            "effective_funding_scope": assistance_accounts.FUNDING_SCOPE_CORE_PUBLIC_HEALTH,
            "funding_scope_method": "verified_csv",
            "effective_scope_guess": assistance_accounts.SCOPE_CORE,
            "effective_profile_relevant": True,
        },
    }

    summary = assistance_accounts.derive_assistance_transaction_account_summary(
        source_row=source_row,
        account_rows=account_rows,
        lookup_by_symbol=lookup,
    )

    assert summary["account_structure_type"] == "multi_account_same_scope"
    assert summary["has_mixed_scopes"] is False
    assert summary["effective_funding_scope"] == assistance_accounts.FUNDING_SCOPE_CORE_PUBLIC_HEALTH
    assert summary["effective_profile_relevant"] is True
    assert summary["federal_account_combination_key"] == "075-0943|075-0950"


def test_summary_keeps_unknown_multi_account_rows_uncertain() -> None:
    source_row = _source_row(
        source_transaction_id="assist-unknown",
        raw_federal_account_symbol="072-1037; 019-1031",
        appropriation_type="unknown",
    )
    account_rows = assistance_accounts.build_assistance_transaction_account_rows([source_row])

    summary = assistance_accounts.derive_assistance_transaction_account_summary(
        source_row=source_row,
        account_rows=account_rows,
        lookup_by_symbol={},
    )

    assert summary["has_unknown_account"] is True
    assert summary["effective_funding_stream"] == assistance_accounts.STREAM_UNKNOWN
    assert summary["effective_profile_relevant"] is None
    assert summary["effective_classification_method"] == assistance_accounts.METHOD_ALL_UNKNOWN
    assert summary["manual_review_recommended"] is True
    assert summary["multi_account_interpretation"] == "unknown_mixed"


def test_build_multi_account_diagnostics_counts_single_multi_and_missing_rows() -> None:
    diagnostics = assistance_accounts.build_multi_account_diagnostics(
        [
            _source_row(
                source_transaction_id="assist-single",
                raw_federal_account_symbol="075-0950",
                transaction_obligated_amount=Decimal("50.00"),
            ),
            _source_row(
                source_transaction_id="assist-multi",
                raw_federal_account_symbol="075-0140; 075-0943",
                transaction_obligated_amount=Decimal("125.00"),
            ),
            _source_row(
                source_transaction_id="assist-missing",
                raw_federal_account_symbol=None,
                transaction_obligated_amount=Decimal("10.00"),
            ),
        ]
    )

    assert diagnostics["single_account_rows"] == 1
    assert diagnostics["multi_account_rows"] == 1
    assert diagnostics["missing_account_rows"] == 1
    assert diagnostics["single_account_amount"] == Decimal("50.00")
    assert diagnostics["multi_account_amount"] == Decimal("125.00")
    assert diagnostics["missing_account_amount"] == Decimal("10.00")
    assert diagnostics["top_multi_account_combinations"][0]["account_symbols"] == "075-0140|075-0943"
    assert diagnostics["top_individual_account_symbols_from_multi_account_rows"][0]["federal_account_symbol"] in {
        "075-0140",
        "075-0943",
    }
