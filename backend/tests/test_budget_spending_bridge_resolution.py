from __future__ import annotations

from decimal import Decimal
import uuid

from app.budget import bridge_resolution


def _candidate(**overrides):
    row = {
        "id": 1,
        "bridge_version": "v1_budget_spending_bridge",
        "budget_anchor_id": "1",
        "classification_id": 10,
        "raw_budget_id": 100,
        "unique_id": "CDC-BRIDGE-ANCHOR-1",
        "system_name": "usaspending",
        "source_record_id": "award-1",
        "match_tier": "TIER_A_DETERMINISTIC",
        "match_type": "federal_account_exact",
        "match_score": Decimal("0.9700"),
        "match_confidence": Decimal("0.9650"),
        "confidence_band": "HIGH",
        "fiscal_year": 2026,
        "budget_agency": "HHS",
        "budget_sub_agency": "CDC",
        "budget_program": "Tuberculosis",
        "budget_sub_program": None,
        "budget_sub_program_2": None,
        "budget_sub_program_3": None,
        "budget_program_key": "tuberculosis",
        "appropriation_category": "REGULAR",
        "appropriation_subtype": "annual_discretionary",
        "is_regular_appropriation": True,
        "classification_confidence": Decimal("0.950"),
        "primary_rule_code": "REGULAR_001",
        "is_excluded": False,
    }
    row.update(overrides)
    return row


def _current_row_from_candidate(candidate, **overrides):
    row = bridge_resolution.accepted_row_for_candidate(
        candidate=candidate,
        resolution_version=bridge_resolution.DEFAULT_RESOLUTION_VERSION,
        resolution_batch_id=uuid.uuid4(),
        rule_code="RESOLVE_AUTO_001",
    )
    row.update(
        {
            "id": 900,
            "supersedes_resolution_id": None,
            "is_current": True,
        }
    )
    row.update(overrides)
    return row


def test_auto_accepts_single_high_confidence_deterministic_candidate() -> None:
    rows = bridge_resolution.seed_anchor_resolution_rows(
        candidates=[_candidate()],
        resolution_version=bridge_resolution.DEFAULT_RESOLUTION_VERSION,
        resolution_batch_id=uuid.uuid4(),
    )

    assert len(rows) == 1
    assert rows[0]["resolution_rule_code"] == "RESOLVE_AUTO_001"
    assert rows[0]["resolution_status"] == "accepted"
    assert rows[0]["allocation_pct"] == Decimal("1.000000")
    assert rows[0]["allocation_method"] == "auto_single_high_confidence"


def test_unique_strongest_high_confidence_candidate_wins_when_others_are_weaker() -> None:
    winner = _candidate()
    weaker = _candidate(
        id=2,
        source_record_id="award-2",
        match_tier="TIER_B_STRUCTURED",
        match_type="program_name_exact",
        match_score=Decimal("0.8200"),
        match_confidence=Decimal("0.8000"),
        confidence_band="MEDIUM",
    )

    rows = bridge_resolution.seed_anchor_resolution_rows(
        candidates=[winner, weaker],
        resolution_version=bridge_resolution.DEFAULT_RESOLUTION_VERSION,
        resolution_batch_id=uuid.uuid4(),
    )

    status_by_bridge_id = {row["bridge_id"]: row["resolution_status"] for row in rows}
    rule_by_bridge_id = {row["bridge_id"]: row["resolution_rule_code"] for row in rows}

    assert status_by_bridge_id[1] == "accepted"
    assert rule_by_bridge_id[1] == "RESOLVE_AUTO_002"
    assert status_by_bridge_id[2] == "unresolved"


def test_ambiguous_candidate_set_becomes_unresolved() -> None:
    candidate_a = _candidate(
        id=1,
        match_tier="TIER_B_STRUCTURED",
        match_type="program_name_exact",
        match_score=Decimal("0.8300"),
        match_confidence=Decimal("0.8100"),
        confidence_band="MEDIUM",
    )
    candidate_b = _candidate(
        id=2,
        source_record_id="award-2",
        match_tier="TIER_B_STRUCTURED",
        match_type="account_to_program_bridge",
        match_score=Decimal("0.8500"),
        match_confidence=Decimal("0.8200"),
        confidence_band="MEDIUM",
    )

    rows = bridge_resolution.seed_anchor_resolution_rows(
        candidates=[candidate_a, candidate_b],
        resolution_version=bridge_resolution.DEFAULT_RESOLUTION_VERSION,
        resolution_batch_id=uuid.uuid4(),
    )

    assert {row["resolution_status"] for row in rows} == {"unresolved"}
    assert {row["resolution_rule_code"] for row in rows} == {"RESOLVE_SEED_003"}


def test_excluded_candidate_seeds_rejected() -> None:
    rows = bridge_resolution.seed_anchor_resolution_rows(
        candidates=[_candidate(is_excluded=True)],
        resolution_version=bridge_resolution.DEFAULT_RESOLUTION_VERSION,
        resolution_batch_id=uuid.uuid4(),
    )

    assert len(rows) == 1
    assert rows[0]["resolution_rule_code"] == "RESOLVE_SEED_005"
    assert rows[0]["resolution_status"] == "rejected"
    assert rows[0]["scope_include_flag"] is False


def test_analyst_reviewed_current_row_is_not_overwritten() -> None:
    candidate = _candidate()
    desired_rows = bridge_resolution.seed_anchor_resolution_rows(
        candidates=[candidate],
        resolution_version=bridge_resolution.DEFAULT_RESOLUTION_VERSION,
        resolution_batch_id=uuid.uuid4(),
    )
    current = _current_row_from_candidate(
        candidate,
        analyst_reviewed=True,
        auto_seeded=False,
        resolution_method="analyst",
        reviewer_name="Analyst",
        reviewer_email="analyst@example.com",
    )

    plan = bridge_resolution.plan_resolution_writes(
        desired_rows=desired_rows,
        current_rows_by_bridge_id={1: current},
    )

    assert plan.insert_rows == []
    assert plan.superseded_resolution_ids == []
    assert plan.protected_resolution_ids == [900]
    assert plan.current_scope_rows[0]["analyst_reviewed"] is True
    assert plan.current_scope_rows[0]["resolution_method"] == "analyst"


def test_allocation_rules_helper_accepts_valid_status_shapes() -> None:
    accepted = _current_row_from_candidate(_candidate())
    accepted_partial = dict(accepted)
    accepted_partial["resolution_status"] = "accepted_partial"
    accepted_partial["allocation_pct"] = Decimal("0.250000")
    accepted_partial["scope_include_flag"] = True
    accepted_partial["allocation_method"] = "analyst_split"

    unresolved = dict(accepted)
    unresolved["resolution_status"] = "unresolved"
    unresolved["allocation_pct"] = None
    unresolved["scope_include_flag"] = False

    rejected = dict(unresolved)
    rejected["resolution_status"] = "rejected"

    assert bridge_resolution.allocation_rules_valid(accepted) is True
    assert bridge_resolution.allocation_rules_valid(accepted_partial) is True
    assert bridge_resolution.allocation_rules_valid(unresolved) is True
    assert bridge_resolution.allocation_rules_valid(rejected) is True


def test_supersede_plan_keeps_only_one_current_row_per_bridge() -> None:
    candidate = _candidate(
        match_tier="TIER_B_STRUCTURED",
        match_type="program_name_exact",
        match_score=Decimal("0.8300"),
        match_confidence=Decimal("0.8100"),
        confidence_band="MEDIUM",
    )
    desired_rows = bridge_resolution.seed_anchor_resolution_rows(
        candidates=[candidate],
        resolution_version=bridge_resolution.DEFAULT_RESOLUTION_VERSION,
        resolution_batch_id=uuid.uuid4(),
    )
    existing = _current_row_from_candidate(
        candidate,
        id=901,
        resolution_status="accepted",
        allocation_pct=Decimal("1.000000"),
        allocation_method="auto_single_high_confidence",
        resolution_rule_code="RESOLVE_AUTO_001",
    )

    plan = bridge_resolution.plan_resolution_writes(
        desired_rows=desired_rows,
        current_rows_by_bridge_id={1: existing},
    )

    assert plan.superseded_resolution_ids == [901]
    assert len(plan.insert_rows) == 1
    assert plan.insert_rows[0]["supersedes_resolution_id"] == 901
    assert len([row for row in plan.current_scope_rows if int(row["bridge_id"]) == 1]) == 1
