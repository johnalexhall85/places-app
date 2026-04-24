from __future__ import annotations

import argparse
import csv
import json
import os
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from app.budget.bridge import DEFAULT_BRIDGE_VERSION, parse_category_filter, quantize_score
from app.budget.bridge_resolution import (
    DEFAULT_RESOLUTION_VERSION,
    allocation_rules_valid,
    plan_resolution_writes,
    quantize_allocation,
    serialize_compare_value,
)
from app.budget.models import (
    CdcBudgetSpendingBridgeAnalystActionV1,
    CdcBudgetSpendingBridgeAnalystReasonRegistry,
    CdcBudgetSpendingBridgeResolutionV1,
)
from app.db import DEFAULT_DB_URL
from app.db_fqtn import budget_table

DEFAULT_ACTION_VERSION = "v1_analyst_bridge_actions"
DEFAULT_BATCH_SIZE = 500
ALLOCATION_TOLERANCE = Decimal("0.000001")

ANALYST_ACTION_TABLE = CdcBudgetSpendingBridgeAnalystActionV1.__table__
ANALYST_REASON_TABLE = CdcBudgetSpendingBridgeAnalystReasonRegistry.__table__
RESOLUTION_TABLE = CdcBudgetSpendingBridgeResolutionV1.__table__

BRIDGE_TABLE_FQTN = budget_table("cdc_budget_spending_bridge_v1")
CURRENT_RESOLUTION_TABLE_FQTN = budget_table("cdc_budget_spending_bridge_resolution_v1")
ACTION_TABLE_FQTN = budget_table("cdc_budget_spending_bridge_analyst_action_v1")
ACTION_REASON_TABLE_FQTN = budget_table("cdc_budget_spending_bridge_analyst_reason_registry")

ALLOWED_ANALYST_ACTIONS = {
    "accept_full",
    "accept_partial",
    "reject",
    "leave_unresolved",
    "supersede_prior",
    "mark_needs_followup",
}

TRUTHY = {"1", "true", "t", "yes", "y"}
FALSY = {"0", "false", "f", "no", "n"}

ACTION_COMPARE_IGNORE_FIELDS = {
    "id",
    "created_at",
    "updated_at",
    "action_batch_id",
    "reviewed_at",
    "supersedes_action_id",
    "is_current",
}


@dataclass(frozen=True)
class AnalystReasonDefinition:
    reason_code: str
    analyst_action: str
    description: str
    requires_allocation: bool
    scope_include_default: bool | None


@dataclass
class ActionWritePlan:
    insert_rows: list[dict[str, Any]]
    superseded_action_ids: list[int]
    preserved_current_rows: list[dict[str, Any]]
    current_scope_rows: list[dict[str, Any]]


@dataclass(frozen=True)
class AnchorReviewSummary:
    budget_anchor_id: str
    total_candidate_count: int
    current_accepted_count: int
    current_accepted_partial_count: int
    current_rejected_count: int
    current_unresolved_count: int
    accepted_allocation_sum: Decimal
    allocation_balance_status: str
    analyst_review_state: str
    has_analyst_review: bool
    has_auto_seed_only: bool
    highest_current_confidence: Decimal
    systems_represented: tuple[str, ...]
    last_reviewed_at: datetime | None
    last_reviewer_name: str | None


REASON_DEFINITIONS = (
    AnalystReasonDefinition(
        reason_code="exact_program_match_confirmed",
        analyst_action="accept_full",
        description="Analyst confirmed the candidate is the exact downstream program match.",
        requires_allocation=False,
        scope_include_default=True,
    ),
    AnalystReasonDefinition(
        reason_code="account_match_confirmed",
        analyst_action="accept_full",
        description="Analyst confirmed the bridge via federal-account or TAS lineage.",
        requires_allocation=False,
        scope_include_default=True,
    ),
    AnalystReasonDefinition(
        reason_code="can_match_confirmed",
        analyst_action="accept_full",
        description="Analyst confirmed the candidate via CAN linkage or TAGGS program structure.",
        requires_allocation=False,
        scope_include_default=True,
    ),
    AnalystReasonDefinition(
        reason_code="duplicate_candidate_rejected",
        analyst_action="reject",
        description="Candidate is duplicative or redundant once a better candidate is accepted.",
        requires_allocation=False,
        scope_include_default=False,
    ),
    AnalystReasonDefinition(
        reason_code="better_candidate_exists",
        analyst_action="reject",
        description="Another candidate for the same anchor is a stronger analyst-selected match.",
        requires_allocation=False,
        scope_include_default=False,
    ),
    AnalystReasonDefinition(
        reason_code="split_across_multiple_records",
        analyst_action="accept_partial",
        description="Anchor should be split explicitly across multiple downstream records.",
        requires_allocation=True,
        scope_include_default=True,
    ),
    AnalystReasonDefinition(
        reason_code="ambiguous_keep_unresolved",
        analyst_action="leave_unresolved",
        description="Analyst reviewed the row but is leaving it unresolved pending more evidence.",
        requires_allocation=False,
        scope_include_default=False,
    ),
    AnalystReasonDefinition(
        reason_code="not_same_program_after_review",
        analyst_action="reject",
        description="Analyst determined the candidate does not represent the same budget program after review.",
        requires_allocation=False,
        scope_include_default=False,
    ),
    AnalystReasonDefinition(
        reason_code="emergency_or_supplemental_excluded",
        analyst_action="reject",
        description="Candidate indicates emergency, supplemental, or otherwise excluded funding after review.",
        requires_allocation=False,
        scope_include_default=False,
    ),
    AnalystReasonDefinition(
        reason_code="pphf_confirmed",
        analyst_action="accept_full",
        description="Analyst confirmed the candidate as the correct PPHF-linked downstream record.",
        requires_allocation=False,
        scope_include_default=True,
    ),
    AnalystReasonDefinition(
        reason_code="transfer_confirmed",
        analyst_action="accept_full",
        description="Analyst confirmed the candidate as the correct structural transfer-linked record.",
        requires_allocation=False,
        scope_include_default=True,
    ),
    AnalystReasonDefinition(
        reason_code="needs_more_research",
        analyst_action="mark_needs_followup",
        description="Analyst reviewed the row and flagged it for additional research or follow-up.",
        requires_allocation=False,
        scope_include_default=False,
    ),
)
REASONS_BY_CODE = {reason.reason_code: reason for reason in REASON_DEFINITIONS}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply analyst bridge decisions into the analyst action and resolution layers.",
    )
    parser.add_argument(
        "--action-version",
        default=DEFAULT_ACTION_VERSION,
        help=f"Analyst action version label stored in {ACTION_TABLE_FQTN}.",
    )
    parser.add_argument(
        "--resolution-version",
        default=DEFAULT_RESOLUTION_VERSION,
        help=f"Resolution version to write analyst-reviewed rows into {budget_table('cdc_budget_spending_bridge_resolution_v1')}.",
    )
    parser.add_argument(
        "--bridge-version",
        default=DEFAULT_BRIDGE_VERSION,
        help=f"Bridge version to validate against in {BRIDGE_TABLE_FQTN}.",
    )
    parser.add_argument("--input-file", required=True, help="CSV or JSON file containing analyst actions.")
    parser.add_argument(
        "--input-format",
        default="csv",
        choices=("csv", "json"),
        help="Input file format.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate and plan writes without mutating the database.")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate the action file and print the summary without inserting or superseding rows.",
    )
    parser.add_argument("--reviewer-name", default=None, help="Fallback reviewer name when missing in the input file.")
    parser.add_argument("--reviewer-email", default=None, help="Fallback reviewer email when missing in the input file.")
    parser.add_argument(
        "--reviewer-team",
        default=None,
        help="Fallback reviewer team when missing in the input file.",
    )
    parser.add_argument(
        "--finalize-anchor-single-winner",
        action="store_true",
        help="When an anchor has one accept_full action, generate analyst reject rows for remaining candidates without current analyst actions.",
    )
    parser.add_argument(
        "--strict-allocation",
        dest="strict_allocation",
        action="store_true",
        default=True,
        help="Require accepted allocations within each touched anchor to sum to 1.0.",
    )
    parser.add_argument(
        "--no-strict-allocation",
        dest="strict_allocation",
        action="store_false",
        help="Allow analyst-reviewed anchors to remain temporarily under- or over-allocated.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or the local development DSN).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Insert batch size (default: {DEFAULT_BATCH_SIZE}).",
    )
    return parser.parse_args()


def parse_boolish(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    token = str(value).strip().lower()
    if token == "":
        return None
    if token in TRUTHY:
        return True
    if token in FALSY:
        return False
    raise ValueError(f"Could not interpret boolean value: {value!r}")


def input_import_source(input_format: str) -> str:
    return "csv_import" if input_format == "csv" else "json_import"


def load_input_actions(input_file: str, input_format: str) -> list[dict[str, Any]]:
    path = Path(input_file)
    if input_format == "csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("actions") or payload.get("rows") or []
    if not isinstance(payload, list):
        raise ValueError("JSON analyst action input must be a list or an object containing an 'actions' list.")
    return [dict(row) for row in payload]


def normalize_input_action(
    raw_row: Mapping[str, Any],
    *,
    fallback_reviewer_name: str | None,
    fallback_reviewer_email: str | None,
    fallback_reviewer_team: str | None,
    default_import_source: str,
) -> dict[str, Any]:
    bridge_id = raw_row.get("bridge_id")
    budget_anchor_id = raw_row.get("budget_anchor_id")
    if bridge_id in (None, ""):
        raise ValueError("Each analyst action row must include bridge_id.")
    if budget_anchor_id in (None, ""):
        raise ValueError("Each analyst action row must include budget_anchor_id.")

    analyst_action = str(raw_row.get("analyst_action") or "").strip().lower()
    if analyst_action not in ALLOWED_ANALYST_ACTIONS:
        raise ValueError(f"Unsupported analyst_action {analyst_action!r} for bridge_id={bridge_id}.")

    reviewer_name = str(raw_row.get("reviewer_name") or fallback_reviewer_name or "").strip()
    if not reviewer_name:
        raise ValueError(f"bridge_id={bridge_id} is missing reviewer_name and no fallback reviewer name was provided.")

    reviewer_email = str(raw_row.get("reviewer_email") or fallback_reviewer_email or "").strip() or None
    reviewer_team = str(raw_row.get("reviewer_team") or fallback_reviewer_team or "").strip() or None
    action_reason_code = str(raw_row.get("action_reason_code") or "").strip()
    action_explanation = str(raw_row.get("action_explanation") or "").strip()
    if not action_reason_code:
        raise ValueError(f"bridge_id={bridge_id} is missing action_reason_code.")
    if not action_explanation:
        raise ValueError(f"bridge_id={bridge_id} is missing action_explanation.")

    allocation_raw = raw_row.get("allocation_pct")
    allocation_pct = quantize_allocation(allocation_raw) if allocation_raw not in (None, "") else None
    scope_include_flag = parse_boolish(raw_row.get("scope_include_flag"))
    action_priority = raw_row.get("action_priority")
    reviewed_at_raw = raw_row.get("reviewed_at")
    reviewed_at = None
    if reviewed_at_raw not in (None, ""):
        if isinstance(reviewed_at_raw, datetime):
            reviewed_at = reviewed_at_raw
        else:
            reviewed_at = datetime.fromisoformat(str(reviewed_at_raw).replace("Z", "+00:00"))
    review_notes = str(raw_row.get("review_notes") or "").strip() or None
    anchor_review_group = str(raw_row.get("anchor_review_group") or "").strip() or None
    import_source = str(raw_row.get("import_source") or default_import_source).strip() or default_import_source
    action_is_final = parse_boolish(raw_row.get("action_is_final"))

    normalized = {
        "bridge_id": int(str(bridge_id).strip()),
        "budget_anchor_id": str(budget_anchor_id).strip(),
        "analyst_action": analyst_action,
        "allocation_pct": allocation_pct,
        "scope_include_flag": scope_include_flag,
        "action_reason_code": action_reason_code,
        "action_explanation": action_explanation,
        "action_priority": int(action_priority) if action_priority not in (None, "") else None,
        "action_is_final": action_is_final,
        "reviewer_name": reviewer_name,
        "reviewer_email": reviewer_email,
        "reviewer_team": reviewer_team,
        "reviewed_at": reviewed_at or datetime.now(timezone.utc),
        "review_notes": review_notes,
        "import_source": import_source,
        "anchor_review_group": anchor_review_group,
    }
    return apply_action_defaults(normalized)


def apply_action_defaults(action_row: Mapping[str, Any]) -> dict[str, Any]:
    action = str(action_row["analyst_action"])
    normalized = dict(action_row)
    if action == "accept_full":
        normalized["allocation_pct"] = Decimal("1.000000") if normalized.get("allocation_pct") is None else quantize_allocation(normalized["allocation_pct"])
        normalized["scope_include_flag"] = True if normalized.get("scope_include_flag") is None else bool(normalized["scope_include_flag"])
        normalized["action_is_final"] = True
    elif action == "accept_partial":
        normalized["allocation_pct"] = quantize_allocation(normalized.get("allocation_pct"))
        normalized["scope_include_flag"] = True if normalized.get("scope_include_flag") is None else bool(normalized["scope_include_flag"])
        normalized["action_is_final"] = True
    elif action in {"reject", "leave_unresolved", "mark_needs_followup", "supersede_prior"}:
        normalized["allocation_pct"] = None
        normalized["scope_include_flag"] = False if normalized.get("scope_include_flag") is None else bool(normalized["scope_include_flag"])
        if normalized.get("action_is_final") is None:
            normalized["action_is_final"] = action == "reject"
    if normalized.get("action_is_final") is None:
        normalized["action_is_final"] = True
    return normalized


def validate_action_reason(normalized_action: Mapping[str, Any]) -> None:
    reason_code = str(normalized_action["action_reason_code"])
    reason = REASONS_BY_CODE.get(reason_code)
    if reason is None:
        raise ValueError(f"Unknown action_reason_code {reason_code!r}.")
    if reason.analyst_action != normalized_action["analyst_action"]:
        raise ValueError(
            f"reason_code={reason_code!r} is registered for analyst_action={reason.analyst_action!r}, "
            f"not {normalized_action['analyst_action']!r}."
        )
    if reason.requires_allocation and normalized_action.get("allocation_pct") is None:
        raise ValueError(f"reason_code={reason_code!r} requires a non-null allocation_pct.")


def validate_action_semantics(normalized_action: Mapping[str, Any]) -> None:
    action = str(normalized_action["analyst_action"])
    allocation_pct = quantize_allocation(normalized_action.get("allocation_pct"))
    scope_include_flag = normalized_action.get("scope_include_flag")
    if action == "accept_full":
        if allocation_pct != Decimal("1.000000"):
            raise ValueError("accept_full requires allocation_pct = 1.000000.")
        if scope_include_flag is not True:
            raise ValueError("accept_full requires scope_include_flag = true.")
    elif action == "accept_partial":
        if allocation_pct is None or allocation_pct <= Decimal("0") or allocation_pct >= Decimal("1"):
            raise ValueError("accept_partial requires 0 < allocation_pct < 1.")
        if scope_include_flag is not True:
            raise ValueError("accept_partial requires scope_include_flag = true.")
    elif action in {"reject", "leave_unresolved", "mark_needs_followup", "supersede_prior"}:
        if allocation_pct is not None:
            raise ValueError(f"{action} does not allow allocation_pct.")
        if scope_include_flag not in {False, None}:
            raise ValueError(f"{action} requires scope_include_flag to be false or null.")


def validate_duplicate_input_bridge_ids(actions: Sequence[Mapping[str, Any]]) -> None:
    seen: set[int] = set()
    duplicates: set[int] = set()
    for row in actions:
        bridge_id = int(row["bridge_id"])
        if bridge_id in seen:
            duplicates.add(bridge_id)
        seen.add(bridge_id)
    if duplicates:
        duplicate_text = ", ".join(str(value) for value in sorted(duplicates))
        raise ValueError(f"Input contains duplicate bridge_id values: {duplicate_text}")


def validate_anchor_action_groups(
    actions_by_anchor: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    strict_allocation: bool,
) -> None:
    for budget_anchor_id, rows in actions_by_anchor.items():
        accept_full_count = sum(1 for row in rows if row["analyst_action"] == "accept_full")
        accept_partial_rows = [row for row in rows if row["analyst_action"] == "accept_partial"]
        if accept_full_count > 1:
            raise ValueError(f"budget_anchor_id={budget_anchor_id} has more than one accept_full action.")
        if accept_full_count and accept_partial_rows:
            raise ValueError(f"budget_anchor_id={budget_anchor_id} mixes accept_full with accept_partial actions.")
        if not strict_allocation:
            continue
        accepted_total = Decimal("0")
        for row in rows:
            if row["analyst_action"] == "accept_full":
                accepted_total += Decimal("1.000000")
            elif row["analyst_action"] == "accept_partial":
                accepted_total += quantize_allocation(row["allocation_pct"]) or Decimal("0")
        if accepted_total == Decimal("0"):
            continue
        if abs(accepted_total - Decimal("1.000000")) > ALLOCATION_TOLERANCE:
            raise ValueError(
                f"budget_anchor_id={budget_anchor_id} has accepted allocation total {accepted_total}, "
                "which fails strict allocation validation."
            )


def load_bridge_rows_by_ids(
    connection: Connection,
    *,
    bridge_ids: Sequence[int],
    bridge_version: str,
) -> list[dict[str, Any]]:
    if not bridge_ids:
        return []
    sql = (
        f"SELECT * FROM {BRIDGE_TABLE_FQTN} "
        "WHERE bridge_version = :bridge_version "
        "AND id = ANY(:bridge_ids)"
    )
    rows = connection.execute(
        text(sql),
        {
            "bridge_version": bridge_version,
            "bridge_ids": list(sorted(set(int(value) for value in bridge_ids))),
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def load_bridge_rows_by_anchor_ids(
    connection: Connection,
    *,
    anchor_ids: Sequence[str],
    bridge_version: str,
) -> list[dict[str, Any]]:
    if not anchor_ids:
        return []
    sql = (
        f"SELECT * FROM {BRIDGE_TABLE_FQTN} "
        "WHERE bridge_version = :bridge_version "
        "AND budget_anchor_id = ANY(:anchor_ids) "
        "ORDER BY fiscal_year NULLS LAST, budget_anchor_id, system_name, match_confidence DESC, source_record_id"
    )
    rows = connection.execute(
        text(sql),
        {
            "bridge_version": bridge_version,
            "anchor_ids": list(anchor_ids),
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def load_current_action_rows(
    connection: Connection,
    *,
    action_version: str,
    anchor_ids: Sequence[str],
) -> list[dict[str, Any]]:
    if not anchor_ids:
        return []
    sql = (
        f"SELECT * FROM {ACTION_TABLE_FQTN} "
        "WHERE action_version = :action_version "
        "AND is_current = TRUE "
        "AND budget_anchor_id = ANY(:anchor_ids)"
    )
    rows = connection.execute(
        text(sql),
        {
            "action_version": action_version,
            "anchor_ids": list(anchor_ids),
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def load_current_resolution_rows(
    connection: Connection,
    *,
    resolution_version: str,
    anchor_ids: Sequence[str],
) -> list[dict[str, Any]]:
    if not anchor_ids:
        return []
    sql = (
        f"SELECT * FROM {CURRENT_RESOLUTION_TABLE_FQTN} "
        "WHERE resolution_version = :resolution_version "
        "AND is_current = TRUE "
        "AND budget_anchor_id = ANY(:anchor_ids)"
    )
    rows = connection.execute(
        text(sql),
        {
            "resolution_version": resolution_version,
            "anchor_ids": list(anchor_ids),
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def validate_bridge_alignment(
    *,
    normalized_actions: Sequence[Mapping[str, Any]],
    bridge_rows_by_id: Mapping[int, Mapping[str, Any]],
) -> None:
    missing_bridge_ids = sorted({int(row["bridge_id"]) for row in normalized_actions} - set(bridge_rows_by_id))
    if missing_bridge_ids:
        missing_text = ", ".join(str(value) for value in missing_bridge_ids)
        raise ValueError(f"These bridge_id values were not found in the candidate bridge table: {missing_text}")
    for row in normalized_actions:
        bridge_row = bridge_rows_by_id[int(row["bridge_id"])]
        if str(bridge_row["budget_anchor_id"]) != str(row["budget_anchor_id"]):
            raise ValueError(
                f"bridge_id={row['bridge_id']} belongs to budget_anchor_id={bridge_row['budget_anchor_id']}, "
                f"not {row['budget_anchor_id']}."
            )


def build_analyst_action_row(
    *,
    candidate: Mapping[str, Any],
    normalized_action: Mapping[str, Any],
    action_version: str,
    resolution_version: str,
    bridge_version: str,
    action_batch_id: uuid.UUID,
    supersedes_action_id: int | None = None,
) -> dict[str, Any]:
    return {
        "action_batch_id": action_batch_id,
        "action_version": action_version,
        "bridge_id": int(candidate["id"]),
        "resolution_version": resolution_version,
        "bridge_version": bridge_version,
        "budget_anchor_id": str(candidate["budget_anchor_id"]),
        "classification_id": candidate["classification_id"],
        "raw_budget_id": candidate["raw_budget_id"],
        "unique_id": candidate["unique_id"],
        "system_name": candidate["system_name"],
        "source_record_id": str(candidate["source_record_id"]),
        "fiscal_year": candidate.get("fiscal_year"),
        "budget_program": candidate.get("budget_program"),
        "budget_sub_program": candidate.get("budget_sub_program"),
        "budget_program_key": candidate.get("budget_program_key"),
        "appropriation_category": candidate["appropriation_category"],
        "is_regular_appropriation": bool(candidate.get("is_regular_appropriation")),
        "match_tier": candidate["match_tier"],
        "match_type": candidate["match_type"],
        "match_confidence": quantize_score(candidate["match_confidence"]),
        "confidence_band": candidate["confidence_band"],
        "analyst_action": normalized_action["analyst_action"],
        "allocation_pct": quantize_allocation(normalized_action.get("allocation_pct")),
        "scope_include_flag": normalized_action.get("scope_include_flag"),
        "action_reason_code": normalized_action["action_reason_code"],
        "action_explanation": normalized_action["action_explanation"],
        "action_priority": normalized_action.get("action_priority"),
        "action_is_final": bool(normalized_action.get("action_is_final", True)),
        "reviewer_name": normalized_action["reviewer_name"],
        "reviewer_email": normalized_action.get("reviewer_email"),
        "reviewer_team": normalized_action.get("reviewer_team"),
        "reviewed_at": normalized_action["reviewed_at"],
        "review_notes": normalized_action.get("review_notes"),
        "import_source": normalized_action.get("import_source"),
        "anchor_review_group": normalized_action.get("anchor_review_group"),
        "is_current": True,
        "supersedes_action_id": supersedes_action_id,
    }


def analyst_resolution_fields(action_row: Mapping[str, Any]) -> tuple[str, bool, Decimal | None, str]:
    action = str(action_row["analyst_action"])
    if action == "accept_full":
        return "accepted", True, Decimal("1.000000"), "analyst_full_accept"
    if action == "accept_partial":
        return "accepted_partial", True, quantize_allocation(action_row.get("allocation_pct")), "analyst_split"
    if action == "reject":
        return "rejected", False, None, "analyst_reject"
    if action == "mark_needs_followup":
        return "unresolved", False, None, "analyst_manual"
    if action == "supersede_prior":
        return "unresolved", False, None, "analyst_manual"
    return "unresolved", False, None, "analyst_manual"


def build_analyst_resolution_row(
    *,
    candidate: Mapping[str, Any],
    analyst_action_row: Mapping[str, Any],
    resolution_version: str,
    resolution_batch_id: uuid.UUID,
    supersedes_resolution_id: int | None = None,
) -> dict[str, Any]:
    resolution_status, scope_include_flag, allocation_pct, allocation_method = analyst_resolution_fields(analyst_action_row)
    resolution_row = {
        "resolution_batch_id": resolution_batch_id,
        "resolution_version": resolution_version,
        "bridge_id": int(candidate["id"]),
        "resolution_rule_code": None,
        "bridge_version": candidate["bridge_version"],
        "budget_anchor_id": str(candidate["budget_anchor_id"]),
        "classification_id": candidate["classification_id"],
        "raw_budget_id": candidate["raw_budget_id"],
        "unique_id": candidate["unique_id"],
        "system_name": candidate["system_name"],
        "source_record_id": str(candidate["source_record_id"]),
        "match_tier": candidate["match_tier"],
        "match_type": candidate["match_type"],
        "match_score": quantize_score(candidate["match_score"]),
        "match_confidence": quantize_score(candidate["match_confidence"]),
        "confidence_band": candidate["confidence_band"],
        "fiscal_year": candidate.get("fiscal_year"),
        "budget_agency": candidate.get("budget_agency"),
        "budget_sub_agency": candidate.get("budget_sub_agency"),
        "budget_program": candidate.get("budget_program"),
        "budget_sub_program": candidate.get("budget_sub_program"),
        "budget_sub_program_2": candidate.get("budget_sub_program_2"),
        "budget_sub_program_3": candidate.get("budget_sub_program_3"),
        "budget_program_key": candidate.get("budget_program_key"),
        "appropriation_category": candidate["appropriation_category"],
        "appropriation_subtype": candidate.get("appropriation_subtype"),
        "is_regular_appropriation": bool(candidate.get("is_regular_appropriation")),
        "classification_confidence": candidate["classification_confidence"],
        "primary_rule_code": candidate.get("primary_rule_code"),
        "resolution_status": resolution_status,
        "scope_include_flag": scope_include_flag,
        "allocation_pct": quantize_allocation(allocation_pct),
        "allocation_method": allocation_method,
        "resolution_method": "analyst",
        "resolution_confidence": quantize_score(candidate["match_confidence"]),
        "resolution_priority": analyst_action_row.get("action_priority"),
        "auto_seeded": False,
        "analyst_reviewed": True,
        "resolution_reason_code": analyst_action_row["action_reason_code"],
        "resolution_explanation": analyst_action_row["action_explanation"],
        "reviewer_name": analyst_action_row["reviewer_name"],
        "reviewer_email": analyst_action_row.get("reviewer_email"),
        "reviewed_at": analyst_action_row["reviewed_at"],
        "review_notes": analyst_action_row.get("review_notes"),
        "supersedes_resolution_id": supersedes_resolution_id,
        "is_current": True,
    }
    if not allocation_rules_valid(resolution_row):
        raise ValueError(
            f"Analyst action for bridge_id={candidate['id']} produced an invalid resolution shape: {resolution_row['resolution_status']}"
        )
    return resolution_row


def action_rows_equivalent(existing: Mapping[str, Any], desired: Mapping[str, Any]) -> bool:
    keys = (set(existing.keys()) | set(desired.keys())) - ACTION_COMPARE_IGNORE_FIELDS
    for key in keys:
        if serialize_compare_value(existing.get(key)) != serialize_compare_value(desired.get(key)):
            return False
    return True


def plan_action_writes(
    *,
    desired_rows: Sequence[Mapping[str, Any]],
    current_rows_by_bridge_id: Mapping[int, Mapping[str, Any]],
) -> ActionWritePlan:
    insert_rows: list[dict[str, Any]] = []
    superseded_action_ids: list[int] = []
    preserved_current_rows: list[dict[str, Any]] = []
    processed_bridge_ids: set[int] = set()

    for desired in desired_rows:
        bridge_id = int(desired["bridge_id"])
        processed_bridge_ids.add(bridge_id)
        current = current_rows_by_bridge_id.get(bridge_id)
        if current is None:
            insert_rows.append(dict(desired))
            continue
        if action_rows_equivalent(current, desired):
            preserved_current_rows.append(dict(current))
            continue
        new_row = dict(desired)
        new_row["supersedes_action_id"] = int(current["id"])
        insert_rows.append(new_row)
        superseded_action_ids.append(int(current["id"]))

    for bridge_id, current in current_rows_by_bridge_id.items():
        if bridge_id in processed_bridge_ids:
            continue
        preserved_current_rows.append(dict(current))

    current_scope_rows = [*preserved_current_rows, *insert_rows]
    current_scope_rows.sort(
        key=lambda row: (
            row.get("fiscal_year") or 0,
            str(row.get("budget_anchor_id")),
            str(row.get("system_name")),
            -float(row.get("match_confidence") or 0),
            str(row.get("source_record_id")),
        )
    )
    return ActionWritePlan(
        insert_rows=insert_rows,
        superseded_action_ids=sorted(set(superseded_action_ids)),
        preserved_current_rows=preserved_current_rows,
        current_scope_rows=current_scope_rows,
    )


def summarize_anchor_review_state(
    *,
    budget_anchor_id: str,
    resolution_rows: Sequence[Mapping[str, Any]],
    analyst_action_rows: Sequence[Mapping[str, Any]],
) -> AnchorReviewSummary:
    accepted_rows = [row for row in resolution_rows if row["resolution_status"] == "accepted" and row["scope_include_flag"]]
    accepted_partial_rows = [row for row in resolution_rows if row["resolution_status"] == "accepted_partial" and row["scope_include_flag"]]
    rejected_rows = [row for row in resolution_rows if row["resolution_status"] == "rejected"]
    unresolved_rows = [row for row in resolution_rows if row["resolution_status"] == "unresolved"]
    accepted_allocation_sum = sum(
        (quantize_allocation(row.get("allocation_pct")) or Decimal("0"))
        for row in [*accepted_rows, *accepted_partial_rows]
    )
    if accepted_allocation_sum == Decimal("0"):
        allocation_balance_status = "no_allocations"
    elif accepted_allocation_sum > Decimal("1.000000") + ALLOCATION_TOLERANCE:
        allocation_balance_status = "over_allocated"
    elif accepted_allocation_sum < Decimal("1.000000") - ALLOCATION_TOLERANCE:
        allocation_balance_status = "under_allocated"
    else:
        allocation_balance_status = "balanced"

    systems_represented = tuple(sorted({str(row["system_name"]) for row in resolution_rows}))
    highest_current_confidence = max(
        (quantize_score(row.get("match_confidence")) for row in resolution_rows),
        default=Decimal("0.0000"),
    )
    has_analyst_review = any(bool(row.get("analyst_reviewed")) for row in resolution_rows) or bool(analyst_action_rows)
    has_auto_seed_only = (not has_analyst_review) and any(bool(row.get("auto_seeded")) for row in resolution_rows)
    latest_action = None
    if analyst_action_rows:
        latest_action = sorted(
            analyst_action_rows,
            key=lambda row: (row.get("reviewed_at"), row.get("id") or 0),
        )[-1]

    needs_followup = any(str(row["analyst_action"]) == "mark_needs_followup" for row in analyst_action_rows)
    accepted_full_count = len(accepted_rows)
    accepted_partial_count = len(accepted_partial_rows)
    unresolved_count = len(unresolved_rows)

    if not has_analyst_review:
        analyst_review_state = "unreviewed"
    elif needs_followup:
        analyst_review_state = "needs_followup"
    elif allocation_balance_status == "over_allocated" or accepted_full_count > 1:
        analyst_review_state = "conflicting"
    elif (
        accepted_full_count == 1
        and accepted_partial_count == 0
        and unresolved_count == 0
        and allocation_balance_status == "balanced"
    ):
        analyst_review_state = "fully_reviewed_single_winner"
    elif (
        accepted_partial_count > 0
        and unresolved_count == 0
        and allocation_balance_status == "balanced"
    ):
        analyst_review_state = "fully_reviewed_split"
    else:
        analyst_review_state = "partially_reviewed"

    return AnchorReviewSummary(
        budget_anchor_id=budget_anchor_id,
        total_candidate_count=len(resolution_rows),
        current_accepted_count=accepted_full_count,
        current_accepted_partial_count=accepted_partial_count,
        current_rejected_count=len(rejected_rows),
        current_unresolved_count=unresolved_count,
        accepted_allocation_sum=accepted_allocation_sum.quantize(Decimal("0.000001")),
        allocation_balance_status=allocation_balance_status,
        analyst_review_state=analyst_review_state,
        has_analyst_review=has_analyst_review,
        has_auto_seed_only=has_auto_seed_only,
        highest_current_confidence=highest_current_confidence,
        systems_represented=systems_represented,
        last_reviewed_at=latest_action.get("reviewed_at") if latest_action else None,
        last_reviewer_name=latest_action.get("reviewer_name") if latest_action else None,
    )


def build_anchor_review_summaries(
    resolution_rows: Sequence[Mapping[str, Any]],
    analyst_action_rows: Sequence[Mapping[str, Any]],
) -> dict[str, AnchorReviewSummary]:
    resolution_by_anchor: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in resolution_rows:
        resolution_by_anchor[str(row["budget_anchor_id"])].append(dict(row))
    actions_by_anchor: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in analyst_action_rows:
        actions_by_anchor[str(row["budget_anchor_id"])].append(dict(row))
    summaries: dict[str, AnchorReviewSummary] = {}
    for budget_anchor_id in sorted(set(resolution_by_anchor) | set(actions_by_anchor)):
        summaries[budget_anchor_id] = summarize_anchor_review_state(
            budget_anchor_id=budget_anchor_id,
            resolution_rows=resolution_by_anchor.get(budget_anchor_id, []),
            analyst_action_rows=actions_by_anchor.get(budget_anchor_id, []),
        )
    return summaries


def expand_finalize_single_winner_actions(
    *,
    normalized_actions: Sequence[Mapping[str, Any]],
    bridge_rows_by_anchor: Mapping[str, Sequence[Mapping[str, Any]]],
    current_action_rows_by_bridge_id: Mapping[int, Mapping[str, Any]],
    default_import_source: str,
) -> list[dict[str, Any]]:
    expanded = [dict(row) for row in normalized_actions]
    actions_by_anchor: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in expanded:
        actions_by_anchor[str(row["budget_anchor_id"])].append(row)

    for budget_anchor_id, rows in list(actions_by_anchor.items()):
        accept_full_rows = [row for row in rows if row["analyst_action"] == "accept_full"]
        if len(accept_full_rows) != 1:
            continue
        winner = accept_full_rows[0]
        existing_input_bridge_ids = {int(row["bridge_id"]) for row in rows}
        for candidate in bridge_rows_by_anchor.get(budget_anchor_id, []):
            bridge_id = int(candidate["id"])
            if bridge_id == int(winner["bridge_id"]):
                continue
            if bridge_id in existing_input_bridge_ids:
                continue
            if bridge_id in current_action_rows_by_bridge_id:
                continue
            expanded.append(
                apply_action_defaults(
                    {
                        "bridge_id": bridge_id,
                        "budget_anchor_id": budget_anchor_id,
                        "analyst_action": "reject",
                        "allocation_pct": None,
                        "scope_include_flag": False,
                        "action_reason_code": "better_candidate_exists",
                        "action_explanation": (
                            f"Single-winner finalize mode rejected this remaining candidate after bridge_id={winner['bridge_id']} "
                            "was accepted as the analyst-selected full match for the anchor."
                        ),
                        "action_priority": None,
                        "action_is_final": True,
                        "reviewer_name": winner["reviewer_name"],
                        "reviewer_email": winner.get("reviewer_email"),
                        "reviewer_team": winner.get("reviewer_team"),
                        "reviewed_at": winner["reviewed_at"],
                        "review_notes": winner.get("review_notes"),
                        "import_source": "script_generated",
                        "anchor_review_group": winner.get("anchor_review_group"),
                    }
                )
            )
    return expanded


def seed_reason_registry(
    connection: Connection,
    *,
    action_version: str,
    dry_run: bool,
) -> None:
    rows = [
        {
            "reason_code": definition.reason_code,
            "action_version": action_version,
            "analyst_action": definition.analyst_action,
            "description": definition.description,
            "requires_allocation": definition.requires_allocation,
            "scope_include_default": definition.scope_include_default,
            "is_active": True,
        }
        for definition in REASON_DEFINITIONS
    ]
    if dry_run:
        return
    insert_stmt = pg_insert(ANALYST_REASON_TABLE).values(rows)
    connection.execute(
        insert_stmt.on_conflict_do_update(
            index_elements=[ANALYST_REASON_TABLE.c.reason_code],
            set_={
                "action_version": insert_stmt.excluded.action_version,
                "analyst_action": insert_stmt.excluded.analyst_action,
                "description": insert_stmt.excluded.description,
                "requires_allocation": insert_stmt.excluded.requires_allocation,
                "scope_include_default": insert_stmt.excluded.scope_include_default,
                "is_active": insert_stmt.excluded.is_active,
            },
        )
    )


def supersede_action_rows(
    connection: Connection,
    *,
    action_ids: Sequence[int],
    dry_run: bool,
) -> int:
    if dry_run or not action_ids:
        return 0
    sql = (
        f"UPDATE {ACTION_TABLE_FQTN} "
        "SET is_current = FALSE, updated_at = now() "
        "WHERE id = ANY(:action_ids)"
    )
    result = connection.execute(text(sql), {"action_ids": list(action_ids)})
    return int(result.rowcount or 0)


def insert_action_rows(
    connection: Connection,
    *,
    rows: Sequence[Mapping[str, Any]],
    batch_size: int,
    dry_run: bool,
) -> int:
    if dry_run or not rows:
        return 0
    written = 0
    for offset in range(0, len(rows), batch_size):
        batch = [dict(row) for row in rows[offset : offset + batch_size]]
        connection.execute(pg_insert(ANALYST_ACTION_TABLE).values(batch))
        written += len(batch)
    return written


def supersede_resolution_rows(
    connection: Connection,
    *,
    resolution_ids: Sequence[int],
    dry_run: bool,
) -> int:
    if dry_run or not resolution_ids:
        return 0
    sql = (
        f"UPDATE {budget_table('cdc_budget_spending_bridge_resolution_v1')} "
        "SET is_current = FALSE, updated_at = now() "
        "WHERE id = ANY(:resolution_ids)"
    )
    result = connection.execute(text(sql), {"resolution_ids": list(resolution_ids)})
    return int(result.rowcount or 0)


def insert_resolution_rows(
    connection: Connection,
    *,
    rows: Sequence[Mapping[str, Any]],
    batch_size: int,
    dry_run: bool,
) -> int:
    if dry_run or not rows:
        return 0
    written = 0
    for offset in range(0, len(rows), batch_size):
        batch = [dict(row) for row in rows[offset : offset + batch_size]]
        connection.execute(pg_insert(RESOLUTION_TABLE).values(batch))
        written += len(batch)
    return written


def print_summary(
    *,
    desired_action_rows: Sequence[Mapping[str, Any]],
    action_plan: ActionWritePlan,
    resolution_current_rows: Sequence[Mapping[str, Any]],
    action_current_rows: Sequence[Mapping[str, Any]],
    validate_only: bool,
    dry_run: bool,
    inserted_action_rows: int,
    superseded_action_rows: int,
    inserted_resolution_rows: int,
    superseded_resolution_rows: int,
) -> None:
    action_counter = Counter(str(row["analyst_action"]) for row in desired_action_rows)
    summaries = build_anchor_review_summaries(resolution_current_rows, action_current_rows)
    anchors_touched = sorted(summaries)
    fully_allocated = sum(1 for summary in summaries.values() if summary.allocation_balance_status == "balanced")
    under_allocated = sum(1 for summary in summaries.values() if summary.allocation_balance_status == "under_allocated")
    over_allocated = sum(1 for summary in summaries.values() if summary.allocation_balance_status == "over_allocated")

    print(f"actions_loaded={len(desired_action_rows)}")
    print(f"accepted_full={action_counter.get('accept_full', 0)}")
    print(f"accepted_partial={action_counter.get('accept_partial', 0)}")
    print(f"rejected={action_counter.get('reject', 0)}")
    print(f"unresolved={action_counter.get('leave_unresolved', 0) + action_counter.get('supersede_prior', 0)}")
    print(f"needs_followup={action_counter.get('mark_needs_followup', 0)}")
    print(f"anchors_touched={len(anchors_touched)}")
    print(f"anchors_fully_allocated={fully_allocated}")
    print(f"anchors_under_allocated={under_allocated}")
    print(f"anchors_over_allocated={over_allocated}")
    print(f"action_rows_inserted={inserted_action_rows}")
    print(f"action_rows_superseded={superseded_action_rows}")
    print(f"resolution_rows_inserted={inserted_resolution_rows}")
    print(f"resolution_rows_superseded={superseded_resolution_rows}")
    print(f"validate_only={validate_only}")
    print(f"dry_run={dry_run}")

    by_review_state = Counter(summary.analyst_review_state for summary in summaries.values())
    if by_review_state:
        print("anchor_review_state_counts:")
        for state, count in sorted(by_review_state.items()):
            print(f"  {state}={count}")


def main() -> None:
    args = parse_args()
    default_import_source = input_import_source(args.input_format)
    raw_actions = load_input_actions(args.input_file, args.input_format)
    normalized_actions = [
        normalize_input_action(
            raw_row,
            fallback_reviewer_name=args.reviewer_name,
            fallback_reviewer_email=args.reviewer_email,
            fallback_reviewer_team=args.reviewer_team,
            default_import_source=default_import_source,
        )
        for raw_row in raw_actions
    ]
    validate_duplicate_input_bridge_ids(normalized_actions)
    for row in normalized_actions:
        validate_action_reason(row)
        validate_action_semantics(row)

    engine = create_engine(args.db_url, future=True)
    with engine.begin() as connection:
        seed_reason_registry(connection, action_version=args.action_version, dry_run=(args.dry_run or args.validate_only))
        bridge_rows = load_bridge_rows_by_ids(
            connection,
            bridge_ids=[int(row["bridge_id"]) for row in normalized_actions],
            bridge_version=args.bridge_version,
        )
        bridge_rows_by_id = {int(row["id"]): row for row in bridge_rows}
        validate_bridge_alignment(normalized_actions=normalized_actions, bridge_rows_by_id=bridge_rows_by_id)

        touched_anchor_ids = sorted({str(row["budget_anchor_id"]) for row in normalized_actions})
        bridge_rows_for_anchors = load_bridge_rows_by_anchor_ids(
            connection,
            anchor_ids=touched_anchor_ids,
            bridge_version=args.bridge_version,
        )
        bridge_rows_by_anchor: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in bridge_rows_for_anchors:
            bridge_rows_by_anchor[str(row["budget_anchor_id"])].append(dict(row))
            bridge_rows_by_id[int(row["id"])] = dict(row)

        current_action_rows = load_current_action_rows(
            connection,
            action_version=args.action_version,
            anchor_ids=touched_anchor_ids,
        )
        current_action_rows_by_bridge_id = {int(row["bridge_id"]): row for row in current_action_rows}

        if args.finalize_anchor_single_winner:
            normalized_actions = expand_finalize_single_winner_actions(
                normalized_actions=normalized_actions,
                bridge_rows_by_anchor=bridge_rows_by_anchor,
                current_action_rows_by_bridge_id=current_action_rows_by_bridge_id,
                default_import_source=default_import_source,
            )
            validate_duplicate_input_bridge_ids(normalized_actions)
            for row in normalized_actions:
                validate_action_reason(row)
                validate_action_semantics(row)

        actions_by_anchor: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in normalized_actions:
            actions_by_anchor[str(row["budget_anchor_id"])].append(dict(row))
        validate_anchor_action_groups(actions_by_anchor, strict_allocation=args.strict_allocation)

        action_batch_id = uuid.uuid4()
        desired_action_rows = [
            build_analyst_action_row(
                candidate=bridge_rows_by_id[int(action["bridge_id"])],
                normalized_action=action,
                action_version=args.action_version,
                resolution_version=args.resolution_version,
                bridge_version=args.bridge_version,
                action_batch_id=action_batch_id,
            )
            for action in normalized_actions
        ]

        action_plan = plan_action_writes(
            desired_rows=desired_action_rows,
            current_rows_by_bridge_id=current_action_rows_by_bridge_id,
        )

        effective_action_rows = action_plan.current_scope_rows
        current_resolution_rows = load_current_resolution_rows(
            connection,
            resolution_version=args.resolution_version,
            anchor_ids=touched_anchor_ids,
        )
        current_resolution_rows_by_bridge_id = {int(row["bridge_id"]): row for row in current_resolution_rows}

        resolution_batch_id = uuid.uuid4()
        desired_resolution_rows = [
            build_analyst_resolution_row(
                candidate=bridge_rows_by_id[int(action_row["bridge_id"])],
                analyst_action_row=action_row,
                resolution_version=args.resolution_version,
                resolution_batch_id=resolution_batch_id,
            )
            for action_row in effective_action_rows
        ]

        resolution_plan = plan_resolution_writes(
            desired_rows=desired_resolution_rows,
            current_rows_by_bridge_id=current_resolution_rows_by_bridge_id,
            protect_existing_analyst_rows=False,
        )

        action_inserted = 0
        action_superseded = 0
        resolution_inserted = 0
        resolution_superseded = 0
        perform_writes = not args.dry_run and not args.validate_only
        if perform_writes:
            action_superseded = supersede_action_rows(
                connection,
                action_ids=action_plan.superseded_action_ids,
                dry_run=False,
            )
            action_inserted = insert_action_rows(
                connection,
                rows=action_plan.insert_rows,
                batch_size=args.batch_size,
                dry_run=False,
            )
            resolution_superseded = supersede_resolution_rows(
                connection,
                resolution_ids=resolution_plan.superseded_resolution_ids,
                dry_run=False,
            )
            resolution_inserted = insert_resolution_rows(
                connection,
                rows=resolution_plan.insert_rows,
                batch_size=args.batch_size,
                dry_run=False,
            )

        print_summary(
            desired_action_rows=desired_action_rows,
            action_plan=action_plan,
            resolution_current_rows=resolution_plan.current_scope_rows,
            action_current_rows=action_plan.current_scope_rows,
            validate_only=args.validate_only,
            dry_run=args.dry_run,
            inserted_action_rows=action_inserted,
            superseded_action_rows=action_superseded,
            inserted_resolution_rows=resolution_inserted,
            superseded_resolution_rows=resolution_superseded,
        )


if __name__ == "__main__":
    main()
