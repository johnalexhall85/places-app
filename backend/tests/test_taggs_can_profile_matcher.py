from __future__ import annotations

from decimal import Decimal

from app.taggs import can_profile_matcher
from app.taggs import rebuild as taggs_rebuild


def test_score_profile_to_taggs_prefers_exact_identifier_match() -> None:
    profile_row = can_profile_matcher.ProfileReferenceRow(
        id=1,
        fiscal_year=2023,
        state_code="AL",
        category="Immunization",
        subcategory="Vaccines for Children",
        grantee_name="Alabama Department of Public Health",
        city="Montgomery",
        county="Montgomery",
        amount=Decimal("100000"),
        project_number="NU58IP000123",
        reference_number="5 NU58IP000123-02-00",
        nofo_number="CDC-TEST",
        nofo_title="Vaccines for Children Program",
        funding_opportunity_title="Vaccines for Children Program",
    )
    taggs_row = can_profile_matcher.TaggsAwardAggregate(
        representative_raw_award_id=99,
        award_number="NU58IP000123",
        funding_fiscal_year=2023,
        can_code="93VFC01",
        legal_entity_state_normalized="AL",
        legal_entity_county_normalized="MONTGOMERY",
        legal_entity_country_normalized="UNITED STATES",
        program_office="NCIRD",
        aln="93.268",
        assistance_listing_title="Immunization Cooperative Agreements",
        award_title="Vaccines for Children Program",
        award_description="Supports vaccines for children activities.",
        legal_entity_name="ALABAMA DEPARTMENT OF PUBLIC HEALTH",
        legal_entity_city="Montgomery",
        total_sum_of_actions=Decimal("100000"),
        raw_row_count=1,
        is_domestic_scope=True,
    )

    match = can_profile_matcher.score_profile_to_taggs(profile_row, taggs_row)

    assert match.match_method == "award_identifier_exact"
    assert match.match_strength == "strong_match"
    assert match.match_score >= Decimal("0.85")


def test_aggregate_profile_matches_by_can_builds_confident_dictionary_row() -> None:
    profile_rows = {
        1: can_profile_matcher.ProfileReferenceRow(
            id=1,
            fiscal_year=2022,
            state_code="AL",
            category="Immunization",
            subcategory="Vaccines for Children",
            grantee_name="Alabama Department of Health",
            city="Montgomery",
            county="Montgomery",
            amount=Decimal("100"),
            project_number="NU58AA000001",
            reference_number=None,
            nofo_number=None,
            nofo_title="Vaccines for Children",
            funding_opportunity_title="Vaccines for Children Program",
        ),
        2: can_profile_matcher.ProfileReferenceRow(
            id=2,
            fiscal_year=2023,
            state_code="GA",
            category="Immunization",
            subcategory="Vaccines for Children",
            grantee_name="Georgia Department of Health",
            city="Atlanta",
            county="Fulton",
            amount=Decimal("120"),
            project_number="NU58AA000002",
            reference_number=None,
            nofo_number=None,
            nofo_title="Vaccines for Children",
            funding_opportunity_title="Vaccines for Children Program",
        ),
    }
    matches = [
        can_profile_matcher.MatchCandidate(
            can_code="93VFC01",
            fiscal_year=2022,
            state_code="AL",
            matched_profile_row_id=1,
            matched_taggs_row_id=10,
            match_score=Decimal("0.92"),
            match_strength="strong_match",
            match_method="award_identifier_exact",
            evidence_json={},
        ),
        can_profile_matcher.MatchCandidate(
            can_code="93VFC01",
            fiscal_year=2023,
            state_code="GA",
            matched_profile_row_id=2,
            matched_taggs_row_id=11,
            match_score=Decimal("0.88"),
            match_strength="probable_match",
            match_method="scored_candidate",
            evidence_json={},
        ),
    ]

    rows = can_profile_matcher.aggregate_profile_matches_by_can(matches, profile_rows)

    assert rows["93VFC01"]["profile_inferred_category"] == "Immunization"
    assert rows["93VFC01"]["profile_inferred_subcategory"] == "Vaccines for Children"
    assert rows["93VFC01"]["profile_match_count"] == 2
    assert rows["93VFC01"]["profile_match_confidence"] >= Decimal("80.00")


def test_resolve_effective_mapping_respects_manual_then_profile_then_fallback() -> None:
    effective = can_profile_matcher.resolve_effective_mapping(
        manual_row={
            "manual_program_name": "Manual Program",
            "manual_category": "Manual Category",
            "manual_subcategory": "Manual Subcategory",
            "is_manually_verified": True,
        },
        profile_row={
            "profile_inferred_program_name": "Profile Program",
            "profile_inferred_category": "Profile Category",
            "profile_inferred_subcategory": "Profile Subcategory",
            "profile_match_confidence": Decimal("95.00"),
        },
        fallback_row={
            "fallback_inferred_program_name": "Fallback Program",
            "fallback_inferred_category": "Fallback Category",
            "fallback_inferred_subcategory": "Fallback Subcategory",
            "fallback_guess_confidence": Decimal("80.00"),
        },
    )
    assert effective["effective_mapping_method"] == can_profile_matcher.MANUAL_OVERRIDE_METHOD
    assert effective["effective_category"] == "Manual Category"

    effective = can_profile_matcher.resolve_effective_mapping(
        manual_row={},
        profile_row={
            "profile_inferred_program_name": "Profile Program",
            "profile_inferred_category": "Profile Category",
            "profile_inferred_subcategory": "Profile Subcategory",
            "profile_match_confidence": Decimal("95.00"),
        },
        fallback_row={
            "fallback_inferred_program_name": "Fallback Program",
            "fallback_inferred_category": "Fallback Category",
            "fallback_inferred_subcategory": "Fallback Subcategory",
            "fallback_guess_confidence": Decimal("80.00"),
        },
    )
    assert effective["effective_mapping_method"] == can_profile_matcher.PROFILE_MATCH_METHOD
    assert effective["effective_category"] == "Profile Category"

    effective = can_profile_matcher.resolve_effective_mapping(
        manual_row={},
        profile_row={},
        fallback_row={
            "fallback_inferred_program_name": "Fallback Program",
            "fallback_inferred_category": "Fallback Category",
            "fallback_inferred_subcategory": "Fallback Subcategory",
            "fallback_guess_confidence": Decimal("80.00"),
        },
    )
    assert effective["effective_mapping_method"] == can_profile_matcher.FALLBACK_METHOD
    assert effective["effective_category"] == "Fallback Category"


def test_build_classification_rows_handles_known_profile_can_and_new_later_year_can() -> None:
    can_observations = {
        "KNOWN1": {
            "observed_first_fy": 2021,
            "observed_last_fy": 2026,
            "observed_row_count": 10,
            "observed_total_funding": Decimal("500"),
            "dominant_program_office": "NCIRD",
            "dominant_aln": "93.268",
            "dominant_assistance_listing_title": "Immunization Cooperative Agreements",
            "fiscal_years": {2021, 2022, 2023, 2024, 2025, 2026},
        },
        "NEW26": {
            "observed_first_fy": 2026,
            "observed_last_fy": 2026,
            "observed_row_count": 2,
            "observed_total_funding": Decimal("100"),
            "dominant_program_office": "NCIPC",
            "dominant_aln": "93.276",
            "dominant_assistance_listing_title": "Drug-Free Communities Support Program",
            "dominant_award_title": "Drug Free Communities Support Program",
            "dominant_award_description": "Drug free communities support program",
            "fiscal_years": {2026},
        },
    }
    profile_mappings = {
        "KNOWN1": {
            "profile_inferred_program_name": "Vaccines for Children Program",
            "profile_inferred_category": "Immunization",
            "profile_inferred_subcategory": "Vaccines for Children",
            "profile_match_confidence": Decimal("90.00"),
            "profile_match_count": 5,
            "profile_match_evidence_json": {},
        }
    }
    fallback_mappings = {
        "NEW26": {
            "fallback_inferred_program_name": "Drug Free Communities Support Program",
            "fallback_inferred_category": "NCIPC",
            "fallback_inferred_subcategory": "Drug-Free Communities Support Program",
            "fallback_guess_confidence": Decimal("60.00"),
            "fallback_guess_evidence_json": {},
        }
    }

    rows = {
        row["can_code"]: row
        for row in can_profile_matcher.build_classification_rows(
            can_observations=can_observations,
            profile_mappings=profile_mappings,
            fallback_mappings=fallback_mappings,
            manual_overrides={},
        )
    }

    assert rows["KNOWN1"]["effective_mapping_method"] == can_profile_matcher.PROFILE_MATCH_METHOD
    assert rows["KNOWN1"]["effective_subcategory"] == "Vaccines for Children"
    assert rows["NEW26"]["effective_mapping_method"] == can_profile_matcher.FALLBACK_METHOD
    assert rows["NEW26"]["funding_stream"] == "Drug Free Communities"


def test_rebuild_rows_propagate_effective_mapping_into_award_and_state_summaries() -> None:
    aggregated_awards = [
        can_profile_matcher.TaggsAwardAggregate(
            representative_raw_award_id=1,
            award_number="NU58AA000001",
            funding_fiscal_year=2025,
            can_code="KNOWN1",
            legal_entity_state_normalized="AL",
            legal_entity_county_normalized="MONTGOMERY",
            legal_entity_country_normalized="UNITED STATES",
            program_office="NCIRD",
            aln="93.268",
            assistance_listing_title="Immunization Cooperative Agreements",
            award_title="Vaccines for Children Program",
            award_description="VFC support",
            legal_entity_name="ALABAMA DEPARTMENT OF HEALTH",
            legal_entity_city="Montgomery",
            total_sum_of_actions=Decimal("250"),
            raw_row_count=1,
            is_domestic_scope=True,
        )
    ]
    classification_lookup = {
        "KNOWN1": {
            "effective_program_name": "Vaccines for Children Program",
            "effective_category": "Immunization",
            "effective_subcategory": "Vaccines for Children",
            "effective_mapping_method": can_profile_matcher.PROFILE_MATCH_METHOD,
            "funding_stream": "Vaccines for Children",
            "appropriation_type": "regular",
            "can_mapping_version": can_profile_matcher.CAN_MAPPING_VERSION,
        }
    }

    award_rows = taggs_rebuild.enrich_award_summary_rows(aggregated_awards, classification_lookup)
    state_rows = taggs_rebuild.build_state_funding_summary_rows(award_rows)

    assert award_rows[0]["effective_category"] == "Immunization"
    assert award_rows[0]["has_profile_assisted_mapping"] is True
    assert state_rows[0]["effective_subcategory"] == "Vaccines for Children"
    assert state_rows[0]["funding_stream"] == "Vaccines for Children"


def test_write_can_classification_rows_batches_large_upserts() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.executed: list[object] = []

        def execute(self, statement, params=None):
            self.executed.append((statement, params))
            return None

    rows = [
        {
            "can_code": f"CAN{i:04d}",
            "effective_mapping_method": can_profile_matcher.FALLBACK_METHOD,
            "can_mapping_version": can_profile_matcher.CAN_MAPPING_VERSION,
        }
        for i in range(501)
    ]
    audit_rows = [
        {
            "can_code": f"CAN{i:04d}",
            "fiscal_year": 2024,
            "state_code": "AL",
            "matched_profile_row_id": None,
            "matched_taggs_row_id": None,
            "match_score": Decimal("0.70"),
            "match_strength": "probable_match",
            "match_method": "scored_candidate",
            "evidence_json": {},
            "can_mapping_version": can_profile_matcher.CAN_MAPPING_VERSION,
        }
        for i in range(501)
    ]

    fake_connection = FakeConnection()
    can_profile_matcher.write_can_classification_rows(
        fake_connection,
        rows=rows,
        audit_rows=audit_rows,
        replace_all=False,
        target_can_codes=None,
    )

    assert len(fake_connection.executed) == 6
