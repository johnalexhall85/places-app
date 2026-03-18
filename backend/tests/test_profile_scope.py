from __future__ import annotations

from decimal import Decimal

from app.recon import assistance_accounts
from app.recon import profile_scope


RULES = profile_scope.load_rule_seed_rows(profile_scope.DEFAULT_RULES_CSV_PATH)


def _assistance_source_row(**overrides):
    row = {
        "source_transaction_id": "assist-1",
        "source_system": profile_scope.SOURCE_ASSISTANCE,
        "fiscal_year": 2023,
        "state_code": "GA",
        "recipient_name": "Georgia Department of Public Health",
        "recipient_country_name": "UNITED STATES",
        "awarding_agency_name": "Centers for Disease Control and Prevention",
        "funding_agency_name": "Centers for Disease Control and Prevention",
        "assistance_listing_number": "93.323",
        "assistance_listing_title": "Epidemiology and Laboratory Capacity",
        "program_activity_name": "Core Public Health",
        "raw_federal_account_symbol": "075-0950",
        "raw_treasury_account_symbol": "075-2023/2023-0950-000",
        "appropriation_type": "regular",
        "disaster_emergency_fund_code": None,
        "transaction_obligated_amount": Decimal("125.00"),
    }
    row.update(overrides)
    return row


def _contract_source_row(**overrides):
    row = {
        "source_transaction_id": "contract-1",
        "source_system": profile_scope.SOURCE_CONTRACTS,
        "fiscal_year": 2024,
        "state_code": "TX",
        "recipient_name": "ACME Pharma",
        "recipient_country_name": "UNITED STATES",
        "awarding_agency_name": "Centers for Disease Control and Prevention",
        "funding_agency_name": "Centers for Disease Control and Prevention",
        "raw_federal_account_symbol": "075-0943",
        "raw_treasury_account_symbol": "075-2024/2024-0943-000",
        "appropriation_type": "regular",
        "disaster_emergency_fund_code": None,
        "award_description": "Vaccines for Children vaccine procurement",
        "product_or_service_code": "6505",
        "product_or_service_code_description": "Biologicals and vaccines",
        "naics_code": None,
        "naics_description": None,
        "contract_award_type": None,
        "contract_transaction_type": None,
        "transaction_obligated_amount": Decimal("80.00"),
    }
    row.update(overrides)
    return row


def _account_row(**overrides):
    row = {
        "source_transaction_id": "unused",
        "federal_account_symbol": "075-0950",
        "treasury_account_symbol": "075-2023/2023-0950-000",
        "effective_funding_stream": profile_scope.STREAM_REGULAR,
        "effective_funding_scope": profile_scope.FUNDING_SCOPE_CORE_PUBLIC_HEALTH,
        "effective_scope_guess": profile_scope.SCOPE_CORE,
        "effective_profile_relevant": True,
        "likely_core_public_health": True,
        "likely_emergency_public_health": False,
        "likely_federal_health_transfer": False,
        "likely_procurement_support": False,
        "likely_other_public_health": False,
        "likely_biomedical_research": False,
        "likely_international_health_assistance": False,
        "likely_vfc_related": False,
        "likely_emergency_related": False,
        "likely_arpa_related": False,
        "likely_regular_appropriation": True,
    }
    row.update(overrides)
    return row


def _account_summary(**overrides):
    row = {
        "source_transaction_id": "assist-1",
        "account_count": 1,
        "distinct_account_count": 1,
        "joined_account_symbols": "075-0950",
        "has_regular_account": True,
        "has_emergency_account": False,
        "has_arpa_account": False,
        "has_core_public_health_account": True,
        "has_emergency_public_health_account": False,
        "has_federal_health_transfer_account": False,
        "has_special_transfer_account": False,
        "has_procurement_support_account": False,
        "has_other_public_health_account": False,
        "has_biomedical_research_account": False,
        "has_international_health_assistance_account": False,
        "has_profile_relevant_account": True,
        "has_unknown_account": False,
        "has_transfer_or_special_account": False,
        "has_procurement_account": False,
        "has_non_profile_relevant_account": False,
        "effective_funding_stream": profile_scope.STREAM_REGULAR,
        "effective_funding_scope": profile_scope.FUNDING_SCOPE_CORE_PUBLIC_HEALTH,
        "effective_scope_guess": profile_scope.SCOPE_CORE,
        "effective_profile_relevant": True,
        "effective_classification_method": assistance_accounts.METHOD_REGULAR_PROFILE_RELEVANT,
        "funding_scope_method": "verified_csv",
        "federal_account_count": 1,
        "federal_account_combination_key": "075-0950",
        "federal_account_titles_combined": "HIV/AIDS, Viral Hepatitis, Sexually Transmitted Diseases, and Tuberculosis Prevention",
        "component_account_scopes": [
            {
                "federal_account_symbol": "075-0950",
                "account_title": "HIV/AIDS, Viral Hepatitis, Sexually Transmitted Diseases, and Tuberculosis Prevention",
                "effective_funding_scope": profile_scope.FUNDING_SCOPE_CORE_PUBLIC_HEALTH,
                "funding_scope_method": "verified_csv",
                "effective_profile_relevant": True,
            }
        ],
        "component_scope_count": 1,
        "has_mixed_scopes": False,
        "account_structure_type": "single_account",
        "multi_account_interpretation": "single_account",
        "conservative_inclusion_reason": None,
        "manual_review_recommended": False,
        "mixed_scope_contains_core": True,
        "mixed_scope_contains_emergency": False,
        "mixed_scope_contains_transfer": False,
        "mixed_scope_contains_procurement": False,
        "mixed_scope_contains_research": False,
        "mixed_scope_contains_international": False,
        "mixed_scope_contains_special_transfer": False,
        "mixed_scope_contains_unknown": False,
        "classification_notes": "At least one linked regular federal account is explicitly profile relevant.",
    }
    row.update(overrides)
    return row


def test_assistance_regular_domestic_row_is_included() -> None:
    enriched = profile_scope.classify_assistance_row(
        _assistance_source_row(),
        _account_summary(),
        rules=RULES,
    )

    assert enriched["effective_funding_stream"] == profile_scope.STREAM_REGULAR
    assert enriched["effective_funding_scope"] == profile_scope.FUNDING_SCOPE_CORE_PUBLIC_HEALTH
    assert enriched["federal_account_profile_relevant"] is True
    assert enriched["decision_context"] == "cdc_domestic_core_public_health"
    assert enriched["include_in_profile_scope"] is True
    assert enriched["inclusion_weight"] == Decimal("1.00")
    assert enriched["confidence_label"] == profile_scope.CONFIDENCE_HIGH


def test_assistance_unknown_stream_without_lookup_support_stays_uncertain() -> None:
    enriched = profile_scope.classify_assistance_row(
        _assistance_source_row(
            source_transaction_id="assist-unknown",
            raw_federal_account_symbol=None,
            raw_treasury_account_symbol=None,
            appropriation_type="unknown",
            disaster_emergency_fund_code=None,
        ),
        None,
        rules=RULES,
    )

    assert enriched["effective_funding_stream"] == profile_scope.STREAM_UNKNOWN
    assert enriched["effective_funding_scope"] == profile_scope.FUNDING_SCOPE_UNKNOWN
    assert enriched["federal_account_profile_relevant"] is None
    assert enriched["decision_context"] == "cdc_domestic_unknown_uncertain"
    assert enriched["include_in_profile_scope"] is None
    assert enriched["confidence_label"] == profile_scope.CONFIDENCE_LOW


def test_assistance_mixed_core_and_emergency_row_stays_conservative() -> None:
    enriched = profile_scope.classify_assistance_row(
        _assistance_source_row(
            source_transaction_id="assist-mixed",
            raw_federal_account_symbol="075-0140; 075-0943",
        ),
        _account_summary(
            source_transaction_id="assist-mixed",
            account_count=2,
            distinct_account_count=2,
            joined_account_symbols="075-0140; 075-0943",
            has_emergency_account=True,
            has_core_public_health_account=True,
            has_emergency_public_health_account=True,
            has_profile_relevant_account=True,
            has_unknown_account=False,
            effective_funding_stream=profile_scope.STREAM_OTHER_EMERGENCY,
            effective_funding_scope=profile_scope.FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH,
            effective_scope_guess=profile_scope.SCOPE_MIXED,
            effective_profile_relevant=None,
            effective_classification_method=assistance_accounts.METHOD_MIXED_CORE_EMERGENCY_CONSERVATIVE,
            federal_account_count=2,
            federal_account_combination_key="075-0140|075-0943",
            component_scope_count=2,
            has_mixed_scopes=True,
            account_structure_type="multi_account_mixed_scope",
            multi_account_interpretation="mixed_core_emergency",
            conservative_inclusion_reason="Mixed core and emergency without an exact split.",
            mixed_scope_contains_core=True,
            mixed_scope_contains_emergency=True,
            classification_notes="Mixed core public health and emergency public health accounts stay conservative.",
        ),
        rules=RULES,
    )

    assert enriched["decision_context"] == "cdc_domestic_mixed_core_emergency_conservative"
    assert enriched["include_in_profile_scope"] is None
    assert enriched["inclusion_weight"] is None
    assert enriched["account_structure_type"] == "multi_account_mixed_scope"
    assert enriched["federal_account_combination_key"] == "075-0140|075-0943"


def test_assistance_unknown_multi_account_row_stays_uncertain() -> None:
    enriched = profile_scope.classify_assistance_row(
        _assistance_source_row(
            source_transaction_id="assist-multi-unknown",
            raw_federal_account_symbol="072-1037; 019-1031",
        ),
        _account_summary(
            source_transaction_id="assist-multi-unknown",
            account_count=2,
            distinct_account_count=2,
            joined_account_symbols="072-1037; 019-1031",
            has_regular_account=False,
            has_profile_relevant_account=False,
            has_unknown_account=True,
            effective_funding_stream=profile_scope.STREAM_UNKNOWN,
            effective_funding_scope=profile_scope.FUNDING_SCOPE_UNKNOWN,
            effective_scope_guess=profile_scope.SCOPE_UNCERTAIN,
            effective_profile_relevant=None,
            effective_classification_method=assistance_accounts.METHOD_ALL_UNKNOWN,
            federal_account_count=2,
            federal_account_combination_key="019-1031|072-1037",
            component_scope_count=1,
            has_mixed_scopes=True,
            account_structure_type="multi_account_mixed_scope",
            multi_account_interpretation="unknown_mixed",
            manual_review_recommended=True,
            mixed_scope_contains_unknown=True,
            classification_notes="All linked accounts are currently unknown.",
        ),
        rules=RULES,
    )

    assert enriched["decision_context"] == "cdc_domestic_unknown_mixed_review"
    assert enriched["include_in_profile_scope"] is None
    assert enriched["confidence_label"] == profile_scope.CONFIDENCE_LOW
    assert enriched["manual_review_recommended"] is True


def test_assistance_federal_health_transfer_is_excluded() -> None:
    enriched = profile_scope.classify_assistance_row(
        _assistance_source_row(source_transaction_id="assist-medicaid", raw_federal_account_symbol="075-0512"),
        _account_summary(
            source_transaction_id="assist-medicaid",
            joined_account_symbols="075-0512",
            has_regular_account=False,
            has_core_public_health_account=False,
            has_federal_health_transfer_account=True,
            has_profile_relevant_account=False,
            has_non_profile_relevant_account=True,
            has_transfer_or_special_account=True,
            effective_funding_stream=profile_scope.STREAM_TRANSFER,
            effective_funding_scope=profile_scope.FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER,
            effective_scope_guess=profile_scope.SCOPE_SPECIAL,
            effective_profile_relevant=False,
            effective_classification_method=assistance_accounts.METHOD_FEDERAL_HEALTH_TRANSFER_EXCLUDED,
            classification_notes="Medicaid transfer accounts are excluded from the core model.",
        ),
        rules=RULES,
    )

    assert enriched["decision_context"] == "cdc_domestic_federal_health_transfer_excluded"
    assert enriched["include_in_profile_scope"] is False
    assert enriched["confidence_label"] == profile_scope.CONFIDENCE_HIGH


def test_assistance_emergency_public_health_stays_conditional() -> None:
    enriched = profile_scope.classify_assistance_row(
        _assistance_source_row(
            source_transaction_id="assist-emergency",
            raw_federal_account_symbol="075-0140",
            appropriation_type="other_emergency",
        ),
        _account_summary(
            source_transaction_id="assist-emergency",
            joined_account_symbols="075-0140",
            has_regular_account=False,
            has_core_public_health_account=False,
            has_emergency_account=True,
            has_emergency_public_health_account=True,
            effective_funding_stream=profile_scope.STREAM_OTHER_EMERGENCY,
            effective_funding_scope=profile_scope.FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH,
            effective_scope_guess=profile_scope.SCOPE_EMERGENCY,
            effective_profile_relevant=None,
            effective_classification_method=assistance_accounts.METHOD_EMERGENCY_PUBLIC_HEALTH_UNCERTAIN,
            classification_notes="Emergency public health funding remains conditional.",
        ),
        rules=RULES,
    )

    assert enriched["decision_context"] == "cdc_domestic_emergency_public_health_conditional"
    assert enriched["include_in_profile_scope"] is None


def test_assistance_other_public_health_is_excluded() -> None:
    enriched = profile_scope.classify_assistance_row(
        _assistance_source_row(
            source_transaction_id="assist-other-public-health",
            raw_federal_account_symbol="075-1363",
            awarding_agency_name="Substance Abuse and Mental Health Services Administration",
            funding_agency_name="Substance Abuse and Mental Health Services Administration",
        ),
        _account_summary(
            source_transaction_id="assist-other-public-health",
            joined_account_symbols="075-1363",
            has_regular_account=True,
            has_core_public_health_account=False,
            has_other_public_health_account=True,
            has_profile_relevant_account=False,
            has_non_profile_relevant_account=True,
            effective_funding_scope=profile_scope.FUNDING_SCOPE_OTHER_PUBLIC_HEALTH,
            effective_scope_guess=profile_scope.SCOPE_UNCERTAIN,
            effective_profile_relevant=False,
            effective_classification_method=assistance_accounts.METHOD_OTHER_PUBLIC_HEALTH_EXCLUDED,
            classification_notes="Other public health funding stays out of the CDC core model.",
        ),
        rules=RULES,
    )

    assert enriched["decision_context"] == "cdc_domestic_other_public_health_excluded"
    assert enriched["include_in_profile_scope"] is False


def test_assistance_international_health_assistance_is_excluded() -> None:
    enriched = profile_scope.classify_assistance_row(
        _assistance_source_row(
            source_transaction_id="assist-international",
            raw_federal_account_symbol="019-1031",
            awarding_agency_name="Department of State",
            funding_agency_name="Department of State",
            recipient_country_name="United States",
            state_code="NY",
        ),
        _account_summary(
            source_transaction_id="assist-international",
            joined_account_symbols="019-1031",
            has_regular_account=False,
            has_international_health_assistance_account=True,
            has_profile_relevant_account=False,
            has_non_profile_relevant_account=True,
            effective_funding_stream=profile_scope.STREAM_TRANSFER,
            effective_funding_scope=profile_scope.FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE,
            effective_scope_guess=profile_scope.SCOPE_UNCERTAIN,
            effective_profile_relevant=False,
            effective_classification_method=assistance_accounts.METHOD_INTERNATIONAL_HEALTH_ASSISTANCE_EXCLUDED,
            classification_notes="International health assistance stays out of the domestic CDC model.",
        ),
        rules=RULES,
    )

    assert enriched["decision_context"] == "international_health_assistance_excluded"
    assert enriched["include_in_profile_scope"] is False


def test_contract_vfc_row_is_included() -> None:
    enriched = profile_scope.classify_contract_row(
        _contract_source_row(),
        [
            _account_row(
                federal_account_symbol="075-0943",
                treasury_account_symbol="075-2024/2024-0943-000",
                effective_funding_stream=profile_scope.STREAM_REGULAR,
                effective_funding_scope=profile_scope.FUNDING_SCOPE_CORE_PUBLIC_HEALTH,
                effective_scope_guess=profile_scope.SCOPE_CORE,
                likely_core_public_health=True,
                likely_procurement_support=False,
                likely_vfc_related=True,
                likely_regular_appropriation=True,
            )
        ],
        rules=RULES,
    )

    assert enriched["contract_category_guess"] == "likely_vfc_vaccine_purchase"
    assert enriched["likely_vfc_related"] is True
    assert enriched["effective_funding_stream"] == profile_scope.STREAM_PROCUREMENT
    assert enriched["effective_funding_scope"] == profile_scope.FUNDING_SCOPE_PROCUREMENT_SUPPORT
    assert enriched["decision_context"] == "cdc_domestic_procurement_vfc_relevant"
    assert enriched["include_in_profile_scope"] is True
    assert enriched["confidence_label"] == profile_scope.CONFIDENCE_HIGH


def test_contract_admin_row_is_excluded() -> None:
    enriched = profile_scope.classify_contract_row(
        _contract_source_row(
            source_transaction_id="contract-admin",
            award_description="CDC janitorial and facilities support services",
            product_or_service_code_description="Facilities support",
        ),
        [],
        rules=RULES,
    )

    assert enriched["contract_category_guess"] == "likely_admin_or_operations"
    assert enriched["decision_context"] == "cdc_domestic_procurement_support_excluded"
    assert enriched["include_in_profile_scope"] is False
    assert enriched["confidence_label"] == profile_scope.CONFIDENCE_HIGH


def test_contract_mixed_program_transfer_row_stays_conservative() -> None:
    enriched = profile_scope.classify_contract_row(
        _contract_source_row(
            source_transaction_id="contract-mixed-transfer",
            raw_federal_account_symbol="075-0512; 075-0943",
            award_description="Mixed support and transfer contract",
        ),
        [
            _account_row(
                federal_account_symbol="075-0512",
                effective_funding_stream=profile_scope.STREAM_TRANSFER,
                effective_funding_scope=profile_scope.FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER,
                effective_profile_relevant=False,
                likely_core_public_health=False,
                likely_federal_health_transfer=True,
            ),
            _account_row(
                federal_account_symbol="075-0943",
                effective_funding_stream=profile_scope.STREAM_REGULAR,
                effective_funding_scope=profile_scope.FUNDING_SCOPE_CORE_PUBLIC_HEALTH,
                effective_profile_relevant=True,
            ),
        ],
        rules=RULES,
    )

    assert enriched["decision_context"] == "cdc_domestic_mixed_program_transfer_conservative"
    assert enriched["include_in_profile_scope"] is None
    assert enriched["account_structure_type"] == "multi_account_mixed_scope"
    assert enriched["multi_account_interpretation"] == "mixed_program_transfer"


def test_profile_scope_transaction_and_state_year_rollup() -> None:
    assistance = profile_scope.classify_assistance_row(
        _assistance_source_row(source_transaction_id="assist-rollup", transaction_obligated_amount=Decimal("100.00")),
        _account_summary(source_transaction_id="assist-rollup"),
        rules=RULES,
    )
    contract = profile_scope.classify_contract_row(
        _contract_source_row(
            source_transaction_id="contract-rollup",
            award_description="Administrative support contract",
            product_or_service_code_description="Administrative support",
            transaction_obligated_amount=Decimal("40.00"),
        ),
        [],
        rules=RULES,
    )

    combined = profile_scope.build_profile_scope_transaction_rows([assistance], [contract])
    summary_rows = profile_scope.build_state_year_summary_rows(combined)

    assistance_tx = next(row for row in combined if row["source_system"] == profile_scope.SOURCE_ASSISTANCE)
    assert assistance_tx["normalized_profile_scope_amount"] == Decimal("100.00")

    assistance_summary = next(row for row in summary_rows if row["source_system"] == profile_scope.SOURCE_ASSISTANCE)
    assert assistance_summary["raw_amount"] == Decimal("100.00")
    assert assistance_summary["profile_scope_amount"] == Decimal("100.00")
    assert assistance_summary["included_transaction_count"] == 1

    contract_summary = next(row for row in summary_rows if row["source_system"] == profile_scope.SOURCE_CONTRACTS)
    assert contract_summary["raw_amount"] == Decimal("40.00")
    assert contract_summary["profile_scope_amount"] == Decimal("0.00")
    assert contract_summary["included_transaction_count"] == 0


def test_rule_is_false_does_not_match_null_value() -> None:
    rule = {
        "rule_id": 999,
        "priority": 1,
        "source_system": profile_scope.SOURCE_ASSISTANCE,
        "match_field": "federal_account_profile_relevant",
        "match_type": "is_false",
        "match_value": "",
        "is_active": True,
    }

    assert profile_scope.rule_matches(
        {"source_system": profile_scope.SOURCE_ASSISTANCE, "federal_account_profile_relevant": None},
        rule,
    ) is False
