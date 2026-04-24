from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import uuid

import pytest

from app.budget import bridge_analyst_actions, bridge_resolution


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


def _normalized_action(**overrides):
    row = bridge_analyst_actions.apply_action_defaults(
        {
            "bridge_id": 1,
            "budget_anchor_id": "1",
            "analyst_action": "accept_full",
            "allocation_pct": None,
            "scope_include_flag": None,
            "action_reason_code": "exact_program_match_confirmed",
            "action_explanation": "Analyst confirmed this as the best match.",
            "action_priority": None,
            "action_is_final": None,
            "reviewer_name": "Analyst",
            "reviewer_email": "analyst@example.org",
            "reviewer_team": "CHIP",
            "reviewed_at": datetime(2026, 4, 6, tzinfo=timezone.utc),
            "review_notes": None,
            "import_source": "csv_import",
            "anchor_review_group": None,
        }
    )
    row.update(overrides)
    return bridge_analyst_actions.apply_action_defaults(row)


def test_apply_accept_full_action_maps_to_analyst_reviewed_resolution() -> None:
    candidate = _candidate()
    action = _normalized_action()

    action_row = bridge_analyst_actions.build_analyst_action_row(
        candidate=candidate,
        normalized_action=action,
        action_version=bridge_analyst_actions.DEFAULT_ACTION_VERSION,
        resolution_version=bridge_analyst_actions.DEFAULT_RESOLUTION_VERSION,
        bridge_version=candidate["bridge_version"],
        action_batch_id=uuid.uuid4(),
    )
    resolution_row = bridge_analyst_actions.build_analyst_resolution_row(
        candidate=candidate,
        analyst_action_row=action_row,
        resolution_version=bridge_analyst_actions.DEFAULT_RESOLUTION_VERSION,
        resolution_batch_id=uuid.uuid4(),
    )

    assert action_row["analyst_action"] == "accept_full"
    assert action_row["allocation_pct"] == Decimal("1.000000")
    assert resolution_row["resolution_status"] == "accepted"
    assert resolution_row["allocation_pct"] == Decimal("1.000000")
    assert resolution_row["analyst_reviewed"] is True
    assert resolution_row["auto_seeded"] is False


def test_apply_reject_action_maps_to_rejected_resolution() -> None:
    candidate = _candidate()
    action = _normalized_action(
        analyst_action="reject",
        allocation_pct=None,
        scope_include_flag=False,
        action_reason_code="better_candidate_exists",
        action_explanation="A stronger candidate was selected for this anchor.",
    )
    bridge_analyst_actions.validate_action_reason(action)
    bridge_analyst_actions.validate_action_semantics(action)

    action_row = bridge_analyst_actions.build_analyst_action_row(
        candidate=candidate,
        normalized_action=action,
        action_version=bridge_analyst_actions.DEFAULT_ACTION_VERSION,
        resolution_version=bridge_analyst_actions.DEFAULT_RESOLUTION_VERSION,
        bridge_version=candidate["bridge_version"],
        action_batch_id=uuid.uuid4(),
    )
    resolution_row = bridge_analyst_actions.build_analyst_resolution_row(
        candidate=candidate,
        analyst_action_row=action_row,
        resolution_version=bridge_analyst_actions.DEFAULT_RESOLUTION_VERSION,
        resolution_batch_id=uuid.uuid4(),
    )

    assert resolution_row["resolution_status"] == "rejected"
    assert resolution_row["scope_include_flag"] is False
    assert resolution_row["allocation_pct"] is None


def test_two_accept_partial_actions_summing_to_one_validate_cleanly() -> None:
    actions_by_anchor = {
        "1": [
            _normalized_action(
                analyst_action="accept_partial",
                bridge_id=1,
                allocation_pct=Decimal("0.600000"),
                scope_include_flag=True,
                action_reason_code="split_across_multiple_records",
            ),
            _normalized_action(
                analyst_action="accept_partial",
                bridge_id=2,
                allocation_pct=Decimal("0.400000"),
                scope_include_flag=True,
                action_reason_code="split_across_multiple_records",
            ),
        ]
    }

    bridge_analyst_actions.validate_anchor_action_groups(actions_by_anchor, strict_allocation=True)


def test_strict_allocation_validation_rejects_bad_split_totals() -> None:
    actions_by_anchor = {
        "1": [
            _normalized_action(
                analyst_action="accept_partial",
                bridge_id=1,
                allocation_pct=Decimal("0.600000"),
                scope_include_flag=True,
                action_reason_code="split_across_multiple_records",
            ),
            _normalized_action(
                analyst_action="accept_partial",
                bridge_id=2,
                allocation_pct=Decimal("0.300000"),
                scope_include_flag=True,
                action_reason_code="split_across_multiple_records",
            ),
        ]
    }

    with pytest.raises(ValueError, match="strict allocation validation"):
        bridge_analyst_actions.validate_anchor_action_groups(actions_by_anchor, strict_allocation=True)


def test_analyst_action_supersedes_auto_seeded_current_resolution_row() -> None:
    candidate = _candidate()
    current_auto = bridge_resolution.accepted_row_for_candidate(
        candidate=candidate,
        resolution_version=bridge_resolution.DEFAULT_RESOLUTION_VERSION,
        resolution_batch_id=uuid.uuid4(),
        rule_code="RESOLVE_AUTO_001",
    )
    current_auto["id"] = 701
    current_auto["is_current"] = True

    action_row = bridge_analyst_actions.build_analyst_action_row(
        candidate=candidate,
        normalized_action=_normalized_action(),
        action_version=bridge_analyst_actions.DEFAULT_ACTION_VERSION,
        resolution_version=bridge_analyst_actions.DEFAULT_RESOLUTION_VERSION,
        bridge_version=candidate["bridge_version"],
        action_batch_id=uuid.uuid4(),
    )
    desired_resolution = bridge_analyst_actions.build_analyst_resolution_row(
        candidate=candidate,
        analyst_action_row=action_row,
        resolution_version=bridge_analyst_actions.DEFAULT_RESOLUTION_VERSION,
        resolution_batch_id=uuid.uuid4(),
    )

    plan = bridge_resolution.plan_resolution_writes(
        desired_rows=[desired_resolution],
        current_rows_by_bridge_id={1: current_auto},
        protect_existing_analyst_rows=False,
    )

    assert plan.superseded_resolution_ids == [701]
    assert len(plan.insert_rows) == 1
    assert plan.insert_rows[0]["supersedes_resolution_id"] == 701
    assert plan.insert_rows[0]["analyst_reviewed"] is True


def test_rerunning_same_analyst_file_is_idempotent() -> None:
    candidate = _candidate()
    action_row = bridge_analyst_actions.build_analyst_action_row(
        candidate=candidate,
        normalized_action=_normalized_action(),
        action_version=bridge_analyst_actions.DEFAULT_ACTION_VERSION,
        resolution_version=bridge_analyst_actions.DEFAULT_RESOLUTION_VERSION,
        bridge_version=candidate["bridge_version"],
        action_batch_id=uuid.uuid4(),
    )
    current_action = dict(action_row)
    current_action["id"] = 801
    current_action["is_current"] = True

    action_plan = bridge_analyst_actions.plan_action_writes(
        desired_rows=[action_row],
        current_rows_by_bridge_id={1: current_action},
    )
    assert action_plan.insert_rows == []
    assert action_plan.superseded_action_ids == []

    resolution_row = bridge_analyst_actions.build_analyst_resolution_row(
        candidate=candidate,
        analyst_action_row=current_action,
        resolution_version=bridge_analyst_actions.DEFAULT_RESOLUTION_VERSION,
        resolution_batch_id=uuid.uuid4(),
    )
    current_resolution = dict(resolution_row)
    current_resolution["id"] = 802
    current_resolution["is_current"] = True

    resolution_plan = bridge_resolution.plan_resolution_writes(
        desired_rows=[resolution_row],
        current_rows_by_bridge_id={1: current_resolution},
        protect_existing_analyst_rows=False,
    )
    assert resolution_plan.insert_rows == []
    assert resolution_plan.superseded_resolution_ids == []


def test_finalize_anchor_single_winner_rejects_other_candidates() -> None:
    candidate_a = _candidate(id=1, source_record_id="award-1")
    candidate_b = _candidate(id=2, source_record_id="award-2", match_confidence=Decimal("0.7000"), confidence_band="MEDIUM")
    expanded = bridge_analyst_actions.expand_finalize_single_winner_actions(
        normalized_actions=[_normalized_action(bridge_id=1)],
        bridge_rows_by_anchor={"1": [candidate_a, candidate_b]},
        current_action_rows_by_bridge_id={},
        default_import_source="csv_import",
    )

    assert len(expanded) == 2
    reject_rows = [row for row in expanded if row["analyst_action"] == "reject"]
    assert len(reject_rows) == 1
    assert reject_rows[0]["bridge_id"] == 2
    assert reject_rows[0]["action_reason_code"] == "better_candidate_exists"


def test_anchor_summary_helper_marks_balanced_split_as_fully_reviewed_split() -> None:
    candidate_a = _candidate(id=1)
    candidate_b = _candidate(id=2, source_record_id="award-2", match_confidence=Decimal("0.8100"), confidence_band="MEDIUM")
    action_a = bridge_analyst_actions.build_analyst_action_row(
        candidate=candidate_a,
        normalized_action=_normalized_action(
            bridge_id=1,
            analyst_action="accept_partial",
            allocation_pct=Decimal("0.600000"),
            scope_include_flag=True,
            action_reason_code="split_across_multiple_records",
        ),
        action_version=bridge_analyst_actions.DEFAULT_ACTION_VERSION,
        resolution_version=bridge_analyst_actions.DEFAULT_RESOLUTION_VERSION,
        bridge_version=candidate_a["bridge_version"],
        action_batch_id=uuid.uuid4(),
    )
    action_b = bridge_analyst_actions.build_analyst_action_row(
        candidate=candidate_b,
        normalized_action=_normalized_action(
            bridge_id=2,
            analyst_action="accept_partial",
            allocation_pct=Decimal("0.400000"),
            scope_include_flag=True,
            action_reason_code="split_across_multiple_records",
        ),
        action_version=bridge_analyst_actions.DEFAULT_ACTION_VERSION,
        resolution_version=bridge_analyst_actions.DEFAULT_RESOLUTION_VERSION,
        bridge_version=candidate_b["bridge_version"],
        action_batch_id=uuid.uuid4(),
    )
    resolution_rows = [
        bridge_analyst_actions.build_analyst_resolution_row(
            candidate=candidate_a,
            analyst_action_row=action_a,
            resolution_version=bridge_analyst_actions.DEFAULT_RESOLUTION_VERSION,
            resolution_batch_id=uuid.uuid4(),
        ),
        bridge_analyst_actions.build_analyst_resolution_row(
            candidate=candidate_b,
            analyst_action_row=action_b,
            resolution_version=bridge_analyst_actions.DEFAULT_RESOLUTION_VERSION,
            resolution_batch_id=uuid.uuid4(),
        ),
    ]

    summary = bridge_analyst_actions.summarize_anchor_review_state(
        budget_anchor_id="1",
        resolution_rows=resolution_rows,
        analyst_action_rows=[action_a, action_b],
    )

    assert summary.accepted_allocation_sum == Decimal("1.000000")
    assert summary.allocation_balance_status == "balanced"
    assert summary.analyst_review_state == "fully_reviewed_split"
