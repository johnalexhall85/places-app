from __future__ import annotations

from decimal import Decimal
import uuid

from app.budget import bridge


def _anchor(**overrides):
    row = {
        "budget_anchor_id": "1",
        "classification_id": 1,
        "raw_budget_id": 1,
        "unique_id": "CDC-BRIDGE-0001",
        "fiscal_year": 2026,
        "agency": "HHS",
        "sub_agency": "CDC",
        "program": "HIV/AIDS, Viral Hepatitis, Sexually Transmitted Diseases, and Tuberculosis Prevention",
        "sub_program": "Tuberculosis",
        "sub_program_2": None,
        "sub_program_3": None,
        "norm_program": "hiv aids viral hepatitis sexually transmitted diseases and tuberculosis prevention",
        "norm_sub_program": "tuberculosis",
        "norm_sub_program_2": None,
        "norm_sub_program_3": None,
        "norm_program_path": "hiv aids viral hepatitis sexually transmitted diseases and tuberculosis prevention > tuberculosis",
        "budget_program_key": "hiv aids viral hepatitis sexually transmitted diseases and tuberculosis prevention > tuberculosis",
        "appropriation_category": "REGULAR",
        "appropriation_subtype": "annual_discretionary",
        "is_regular_appropriation": True,
        "classification_confidence": Decimal("0.950"),
        "primary_rule_code": "REGULAR_001",
    }
    row.update(overrides)
    return row


def _usaspending_row(**overrides):
    row = {
        "system_name": "usaspending",
        "source_table": "cdc_funding.prime_awards",
        "source_record_id": "award-1",
        "source_parent_record_id": "F-1",
        "source_fiscal_year": 2026,
        "awarding_sub_agency_name": "Centers for Disease Control and Prevention",
        "funding_sub_agency_name": "Centers for Disease Control and Prevention",
        "cfda_program_num": "93.116",
        "cfda_program_title": "PROJECT GRANTS AND COOPERATIVE AGREEMENTS FOR TUBERCULOSIS CONTROL PROGRAMS",
        "prime_award_base_transaction_description": "Tuberculosis activities",
        "appropriation_type": "regular",
        "federal_account_symbols": ["075-0950"],
        "account_titles": ["HIV/AIDS, Viral Hepatitis, Sexually Transmitted Diseases, and Tuberculosis Prevention"],
        "assistance_listing_numbers": ["93.116"],
        "assistance_listing_titles": ["PROJECT GRANTS AND COOPERATIVE AGREEMENTS FOR TUBERCULOSIS CONTROL PROGRAMS"],
        "program_activity_names": ["Tuberculosis Control"],
        "normalized_alns": ["93116"],
        "normalized_account_titles": ["hiv aids viral hepatitis sexually transmitted diseases and tuberculosis prevention"],
        "source_text_values": [
            "project grants and cooperative agreements for tuberculosis control programs",
            "tuberculosis activities",
        ],
        "search_text": "project grants and cooperative agreements for tuberculosis control programs tuberculosis activities",
        "has_regular_signal": True,
        "has_transfer_signal": False,
        "has_emergency_signal": False,
        "has_mandatory_signal": False,
        "total_obligated_amount": Decimal("100.00"),
    }
    row.update(overrides)
    return row


def _taggs_row(**overrides):
    row = {
        "system_name": "taggs",
        "source_table": "taggs.award_funding_summary",
        "source_record_id": "2001",
        "source_parent_record_id": "NU58AA000001",
        "source_fiscal_year": 2026,
        "opdiv": "CDC",
        "program_office": "NCCDPHP",
        "aln": "93.898",
        "can_code": "9213161",
        "assistance_listing_title": "CANCER PREVENTION AND CONTROL PROGRAMS",
        "award_title": "Cancer Prevention and Control Programs",
        "award_description": "Supports state cancer prevention and control activities.",
        "effective_program_name": "Cancer Prevention and Control Programs",
        "funding_stream": "Cancer Prevention and Control - PPHF",
        "appropriation_type": "",
        "is_regular_appropriation": False,
        "is_supplemental": False,
        "is_covid_related": False,
        "is_arpa_related": False,
        "total_sum_of_actions": Decimal("250.00"),
        "normalized_aln": "93898",
        "source_text_values": [
            "cancer prevention and control pphf",
            "cancer prevention and control programs",
            "supports state cancer prevention and control activities",
        ],
        "search_text": "cancer prevention and control pphf cancer prevention and control programs supports state cancer prevention and control activities",
        "has_regular_signal": False,
        "has_transfer_signal": False,
        "has_emergency_signal": False,
        "has_mandatory_signal": False,
    }
    row.update(overrides)
    return row


def test_build_budget_program_key_normalizes_and_joins_program_path() -> None:
    key = bridge.build_budget_program_key(
        "  Chronic Disease Prevention and Health Promotion ",
        "Cancer Prevention and Control",
    )
    assert key == "chronic disease prevention and health promotion > cancer prevention and control"


def test_confidence_band_assignment_matches_explicit_thresholds() -> None:
    assert bridge.confidence_band(Decimal("0.9500")) == "HIGH"
    assert bridge.confidence_band(Decimal("0.8200")) == "MEDIUM"
    assert bridge.confidence_band(Decimal("0.6200")) == "LOW"


def test_make_candidate_row_uses_rule_defaults_for_deterministic_scores() -> None:
    candidate = bridge.make_candidate_row(
        anchor=_anchor(),
        source_row=_usaspending_row(),
        bridge_version=bridge.DEFAULT_BRIDGE_VERSION,
        bridge_batch_id=uuid.uuid4(),
        review_status="unreviewed",
        rule_code="BRIDGE_USA_A001",
        matched_fields=("budget_program", "account_title"),
        matched_label="hiv aids viral hepatitis sexually transmitted diseases and tuberculosis prevention",
        explanation="Exact verified federal-account title match.",
    )

    assert candidate["match_score"] == Decimal("0.9700")
    assert candidate["match_confidence"] == Decimal("0.9650")
    assert candidate["confidence_band"] == "HIGH"


def test_deduplicate_candidates_merges_duplicate_unique_bridge_rows() -> None:
    candidate_a = bridge.make_candidate_row(
        anchor=_anchor(),
        source_row=_usaspending_row(),
        bridge_version=bridge.DEFAULT_BRIDGE_VERSION,
        bridge_batch_id=uuid.uuid4(),
        review_status="unreviewed",
        rule_code="BRIDGE_USA_B001",
        matched_fields=("cfda_program_title",),
        matched_label="tuberculosis",
        explanation="First explanation.",
        match_score=Decimal("0.8000"),
        match_confidence=Decimal("0.7900"),
    )
    candidate_b = bridge.make_candidate_row(
        anchor=_anchor(),
        source_row=_usaspending_row(),
        bridge_version=bridge.DEFAULT_BRIDGE_VERSION,
        bridge_batch_id=uuid.uuid4(),
        review_status="unreviewed",
        rule_code="BRIDGE_USA_B001",
        matched_fields=("program_activity_names",),
        matched_label="tuberculosis",
        explanation="Second explanation.",
        match_score=Decimal("0.8400"),
        match_confidence=Decimal("0.8100"),
    )

    deduped = bridge.deduplicate_candidates([candidate_a, candidate_b])

    assert len(deduped) == 1
    assert deduped[0]["match_score"] == Decimal("0.8400")
    assert set(deduped[0]["matched_on_fields"]) == {"cfda_program_title", "program_activity_names"}


def test_build_bridge_rows_emits_tier_a_manual_seeded_candidate() -> None:
    rows = bridge.build_bridge_rows(
        anchors=[_anchor()],
        usaspending_rows=[_usaspending_row()],
        taggs_rows=[],
        bridge_version=bridge.DEFAULT_BRIDGE_VERSION,
        review_status="unreviewed",
    )

    rule_codes = {row["match_rule_code"] for row in rows}
    assert "BRIDGE_USA_A003" in rule_codes


def test_build_bridge_rows_emits_tier_b_structured_taggs_candidate() -> None:
    anchor = _anchor(
        program="Chronic Disease Prevention and Health Promotion",
        sub_program="Cancer Prevention and Control",
        norm_program="chronic disease prevention and health promotion",
        norm_sub_program="cancer prevention and control",
        norm_program_path="chronic disease prevention and health promotion > cancer prevention and control",
        budget_program_key="chronic disease prevention and health promotion > cancer prevention and control",
        appropriation_category="PPHF",
        appropriation_subtype="prevention_fund",
        is_regular_appropriation=False,
        primary_rule_code="PPHF_001",
    )

    rows = bridge.build_bridge_rows(
        anchors=[anchor],
        usaspending_rows=[],
        taggs_rows=[_taggs_row()],
        bridge_version=bridge.DEFAULT_BRIDGE_VERSION,
        review_status="unreviewed",
    )

    rule_codes = {row["match_rule_code"] for row in rows}
    assert "BRIDGE_TAGGS_B001" in rule_codes


def test_generate_fuzzy_candidates_emits_low_confidence_tier_c_candidate() -> None:
    anchor = _anchor(
        program="Global Health",
        sub_program="Global Public Health Protection",
        norm_program="global health",
        norm_sub_program="global public health protection",
        norm_program_path="global health > global public health protection",
        budget_program_key="global health > global public health protection",
    )
    taggs_row = _taggs_row(
        program_office="COGH",
        aln="93.318",
        normalized_aln="93318",
        can_code="9390NMV",
        assistance_listing_title="PROTECTING AND IMPROVING HEALTH GLOBALLY: BUILDING AND STRENGTHENING PUBLIC HEALTH IMPACT, SYSTEMS, CAPACITY AND SECURITY",
        award_title="Global Health Security Partnerships",
        award_description="Expanding and improving public health laboratory strategies and systems.",
        effective_program_name="Global Health Security Partnerships",
        funding_stream="Global Public Health Protection Partnerships",
        search_text="global health security partnerships expanding and improving public health laboratory strategies and systems global public health protection partnerships",
        source_text_values=[
            "global health security partnerships",
            "global public health protection partnerships",
            "expanding and improving public health laboratory strategies and systems",
        ],
        has_regular_signal=True,
    )
    by_year_rows = {2026: [taggs_row]}
    token_index = bridge.build_token_index([taggs_row])

    candidates = bridge.generate_fuzzy_candidates(
        anchor=anchor,
        by_year_rows=by_year_rows,
        token_index=token_index,
        bridge_version=bridge.DEFAULT_BRIDGE_VERSION,
        bridge_batch_id=uuid.uuid4(),
        review_status="unreviewed",
        system_name="taggs",
        existing_count=0,
    )

    assert len(candidates) == 1
    assert candidates[0]["match_rule_code"] == "BRIDGE_TAGGS_C001"
    assert candidates[0]["confidence_band"] == "LOW"
