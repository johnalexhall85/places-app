from __future__ import annotations

import argparse
import json
import os
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Sequence

from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from app.budget.bridge import DEFAULT_BRIDGE_VERSION, parse_category_filter, quantize_score
from app.budget.models import (
    CdcBudgetSpendingBridgeResolutionRuleRegistry,
    CdcBudgetSpendingBridgeResolutionV1,
)
from app.db import DEFAULT_DB_URL
from app.db_fqtn import budget_table

DEFAULT_RESOLUTION_VERSION = "v1_bridge_resolution"
DEFAULT_BATCH_SIZE = 500
ALLOCATION_QUANTIZER = Decimal("0.000001")
DOMINANT_CONFIDENCE_GAP = Decimal("0.0500")

TIER_PRIORITY = {
    "TIER_A_DETERMINISTIC": 3,
    "TIER_B_STRUCTURED": 2,
    "TIER_C_FUZZY_CANDIDATE": 1,
}

RESOLUTION_TABLE = CdcBudgetSpendingBridgeResolutionV1.__table__
RULE_REGISTRY_TABLE = CdcBudgetSpendingBridgeResolutionRuleRegistry.__table__
BRIDGE_TABLE_FQTN = budget_table("cdc_budget_spending_bridge_v1")
RESOLUTION_TABLE_FQTN = budget_table("cdc_budget_spending_bridge_resolution_v1")
RULE_REGISTRY_TABLE_FQTN = budget_table("cdc_budget_spending_bridge_resolution_rule_registry")

COMPARE_IGNORE_FIELDS = {
    "id",
    "created_at",
    "updated_at",
    "resolution_batch_id",
    "supersedes_resolution_id",
    "is_current",
}


@dataclass(frozen=True)
class ResolutionRuleDefinition:
    rule_code: str
    rule_group: str
    description: str
    resolution_status_output: str
    scope_include_output: bool
    default_allocation_pct: Decimal | None
    resolution_method_output: str
    priority: int


@dataclass
class ResolutionWritePlan:
    insert_rows: list[dict[str, Any]]
    superseded_resolution_ids: list[int]
    protected_resolution_ids: list[int]
    preserved_current_rows: list[dict[str, Any]]
    current_scope_rows: list[dict[str, Any]]


RULE_DEFINITIONS = (
    ResolutionRuleDefinition(
        rule_code="RESOLVE_AUTO_001",
        rule_group="group_1_auto_accept",
        description="Auto-accept an anchor's only non-excluded HIGH-confidence Tier A deterministic candidate.",
        resolution_status_output="accepted",
        scope_include_output=True,
        default_allocation_pct=Decimal("1.000000"),
        resolution_method_output="auto_seed",
        priority=100,
    ),
    ResolutionRuleDefinition(
        rule_code="RESOLVE_AUTO_002",
        rule_group="group_1_auto_accept",
        description="Auto-accept a unique strongest HIGH-confidence Tier A deterministic candidate when all other candidates are lower-tier and clearly weaker.",
        resolution_status_output="accepted",
        scope_include_output=True,
        default_allocation_pct=Decimal("1.000000"),
        resolution_method_output="auto_seed",
        priority=110,
    ),
    ResolutionRuleDefinition(
        rule_code="RESOLVE_SEED_003",
        rule_group="group_2_unresolved",
        description="Seed viable candidates as unresolved when an anchor has multiple plausible candidates and no clean auto-accepted winner.",
        resolution_status_output="unresolved",
        scope_include_output=False,
        default_allocation_pct=None,
        resolution_method_output="auto_seed",
        priority=200,
    ),
    ResolutionRuleDefinition(
        rule_code="RESOLVE_SEED_004",
        rule_group="group_2_unresolved",
        description="Seed LOW-confidence fuzzy candidates as unresolved for analyst review instead of auto-accepting or auto-rejecting them.",
        resolution_status_output="unresolved",
        scope_include_output=False,
        default_allocation_pct=None,
        resolution_method_output="auto_seed",
        priority=210,
    ),
    ResolutionRuleDefinition(
        rule_code="RESOLVE_SEED_005",
        rule_group="group_3_rejected",
        description="Seed already-excluded bridge candidates as rejected and out of downstream scope.",
        resolution_status_output="rejected",
        scope_include_output=False,
        default_allocation_pct=None,
        resolution_method_output="auto_seed",
        priority=300,
    ),
)
RULES_BY_CODE = {rule.rule_code: rule for rule in RULE_DEFINITIONS}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the bridge review and resolution layer for CDC budget-to-spending bridge candidates.",
    )
    parser.add_argument(
        "--resolution-version",
        default=DEFAULT_RESOLUTION_VERSION,
        help=f"Resolution version label stored in {RESOLUTION_TABLE_FQTN}.",
    )
    parser.add_argument(
        "--bridge-version",
        default=DEFAULT_BRIDGE_VERSION,
        help=f"Candidate bridge version to resolve from {BRIDGE_TABLE_FQTN}.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Delete existing resolution rows for the selected scope before rebuilding.",
    )
    parser.add_argument(
        "--system-name",
        default="all",
        choices=("all", "usaspending", "taggs"),
        help="Optional downstream system filter.",
    )
    parser.add_argument(
        "--appropriation-category",
        default=None,
        help="Optional single category or comma-separated list of categories.",
    )
    parser.add_argument(
        "--only-regular",
        action="store_true",
        help="Limit candidate rows to regular-appropriation anchors.",
    )
    parser.add_argument(
        "--fiscal-year",
        type=int,
        default=None,
        help="Optional single fiscal year filter.",
    )
    parser.add_argument(
        "--limit-anchors",
        type=int,
        default=None,
        help="Optional anchor-row cap for debugging or validation slices.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute resolution rows and summaries without writing to the database.",
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


def quantize_allocation(value: Decimal | float | int | str | None) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    if value < 0:
        value = Decimal("0")
    if value > 1:
        value = Decimal("1")
    return value.quantize(ALLOCATION_QUANTIZER, rounding=ROUND_HALF_UP)


def allocation_rules_valid(row: Mapping[str, Any]) -> bool:
    status = str(row.get("resolution_status") or "")
    scope_include_flag = bool(row.get("scope_include_flag"))
    allocation_pct = quantize_allocation(row.get("allocation_pct"))
    if status == "accepted":
        return scope_include_flag and allocation_pct == Decimal("1.000000")
    if status == "accepted_partial":
        return (
            scope_include_flag
            and allocation_pct is not None
            and allocation_pct > Decimal("0")
            and allocation_pct < Decimal("1")
        )
    if status in {"rejected", "unresolved", "superseded"}:
        return (not scope_include_flag) and allocation_pct is None
    return False


def candidate_sort_key(row: Mapping[str, Any]) -> tuple[float, int, int, str]:
    return (
        -float(row.get("match_confidence") or 0),
        -TIER_PRIORITY.get(str(row.get("match_tier")), 0),
        -1 if str(row.get("confidence_band")) == "HIGH" else 0,
        str(row.get("source_record_id") or ""),
    )


def is_high_tier_a(row: Mapping[str, Any]) -> bool:
    return (
        str(row.get("confidence_band")) == "HIGH"
        and str(row.get("match_tier")) == "TIER_A_DETERMINISTIC"
        and not bool(row.get("is_excluded"))
    )


def is_low_fuzzy_candidate(row: Mapping[str, Any]) -> bool:
    return (
        str(row.get("match_tier")) == "TIER_C_FUZZY_CANDIDATE"
        and str(row.get("confidence_band")) == "LOW"
        and not bool(row.get("is_excluded"))
    )


def sortable_confidence(row: Mapping[str, Any], key: str = "match_confidence") -> Decimal:
    value = row.get(key)
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def strongest_candidate(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    if not rows:
        return None
    return sorted(rows, key=candidate_sort_key)[0]


def unique_dominant_high_candidate(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    viable = [row for row in rows if not bool(row.get("is_excluded"))]
    if len(viable) <= 1:
        return None
    high_tier_a = [row for row in viable if is_high_tier_a(row)]
    if len(high_tier_a) != 1:
        return None
    winner = high_tier_a[0]
    others = [row for row in viable if int(row["id"]) != int(winner["id"])]
    if any(str(row.get("match_tier")) == "TIER_A_DETERMINISTIC" for row in others):
        return None
    strongest_other = strongest_candidate(others)
    if strongest_other is None:
        return winner
    confidence_gap = sortable_confidence(winner) - sortable_confidence(strongest_other)
    if confidence_gap < DOMINANT_CONFIDENCE_GAP:
        return None
    return winner


def resolution_confidence_for_rule(rule_code: str, candidate: Mapping[str, Any]) -> Decimal:
    match_confidence = quantize_score(candidate.get("match_confidence"))
    if rule_code == "RESOLVE_AUTO_001":
        return match_confidence
    if rule_code == "RESOLVE_AUTO_002":
        return quantize_score(match_confidence - Decimal("0.0200"))
    if rule_code == "RESOLVE_SEED_003":
        return Decimal("0.8800")
    if rule_code == "RESOLVE_SEED_004":
        return Decimal("0.7800")
    if rule_code == "RESOLVE_SEED_005":
        return Decimal("0.9900")
    return match_confidence


def build_resolution_row(
    *,
    candidate: Mapping[str, Any],
    resolution_version: str,
    resolution_batch_id: uuid.UUID,
    rule_code: str,
    resolution_status: str,
    scope_include_flag: bool,
    allocation_pct: Decimal | None,
    allocation_method: str | None,
    resolution_method: str,
    resolution_reason_code: str,
    resolution_explanation: str,
    auto_seeded: bool,
    analyst_reviewed: bool,
    supersedes_resolution_id: int | None = None,
    reviewer_name: str | None = None,
    reviewer_email: str | None = None,
    reviewed_at: Any = None,
    review_notes: str | None = None,
) -> dict[str, Any]:
    rule = RULES_BY_CODE[rule_code]
    return {
        "resolution_batch_id": resolution_batch_id,
        "resolution_version": resolution_version,
        "bridge_id": int(candidate["id"]),
        "resolution_rule_code": rule.rule_code,
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
        "resolution_method": resolution_method,
        "resolution_confidence": resolution_confidence_for_rule(rule_code, candidate),
        "resolution_priority": rule.priority,
        "auto_seeded": auto_seeded,
        "analyst_reviewed": analyst_reviewed,
        "resolution_reason_code": resolution_reason_code,
        "resolution_explanation": resolution_explanation,
        "reviewer_name": reviewer_name,
        "reviewer_email": reviewer_email,
        "reviewed_at": reviewed_at,
        "review_notes": review_notes,
        "supersedes_resolution_id": supersedes_resolution_id,
        "is_current": True,
    }


def accepted_row_for_candidate(
    *,
    candidate: Mapping[str, Any],
    resolution_version: str,
    resolution_batch_id: uuid.UUID,
    rule_code: str,
) -> dict[str, Any]:
    if rule_code == "RESOLVE_AUTO_001":
        reason_code = "single_high_confidence_candidate"
        explanation = (
            "This anchor has exactly one non-excluded candidate and it is a HIGH-confidence Tier A deterministic match, "
            "so it is auto-accepted at 100 percent."
        )
        allocation_method = "auto_single_high_confidence"
    else:
        reason_code = "unique_strongest_high_confidence_candidate"
        explanation = (
            "This anchor has multiple candidates, but this row is the only HIGH-confidence Tier A deterministic match "
            "and it is clearly stronger than the lower-tier alternatives, so it is auto-accepted at 100 percent."
        )
        allocation_method = "auto_unique_high_confidence"
    return build_resolution_row(
        candidate=candidate,
        resolution_version=resolution_version,
        resolution_batch_id=resolution_batch_id,
        rule_code=rule_code,
        resolution_status="accepted",
        scope_include_flag=True,
        allocation_pct=Decimal("1.000000"),
        allocation_method=allocation_method,
        resolution_method="auto_seed",
        resolution_reason_code=reason_code,
        resolution_explanation=explanation,
        auto_seeded=True,
        analyst_reviewed=False,
    )


def unresolved_row_for_candidate(
    *,
    candidate: Mapping[str, Any],
    resolution_version: str,
    resolution_batch_id: uuid.UUID,
    analyst_anchor_locked: bool,
    viable_candidate_count: int,
) -> dict[str, Any]:
    rule_code = "RESOLVE_SEED_004" if is_low_fuzzy_candidate(candidate) else "RESOLVE_SEED_003"
    if analyst_anchor_locked:
        reason_code = "anchor_has_analyst_reviewed_resolution"
        explanation = (
            "This anchor already has at least one analyst-reviewed current resolution row, so this candidate is kept "
            "unresolved for analyst review rather than being auto-accepted."
        )
    elif rule_code == "RESOLVE_SEED_004":
        reason_code = "low_confidence_fuzzy_candidate"
        explanation = (
            "This candidate is a LOW-confidence fuzzy match, so it is left unresolved for analyst review instead of "
            "being auto-accepted or auto-rejected."
        )
    else:
        reason_code = "ambiguous_candidate_set"
        explanation = (
            f"This anchor has {viable_candidate_count} viable candidate rows and the auto-seeder did not find a single "
            "deterministic winner, so this row remains unresolved for analyst review."
        )
    return build_resolution_row(
        candidate=candidate,
        resolution_version=resolution_version,
        resolution_batch_id=resolution_batch_id,
        rule_code=rule_code,
        resolution_status="unresolved",
        scope_include_flag=False,
        allocation_pct=None,
        allocation_method=None,
        resolution_method="auto_seed",
        resolution_reason_code=reason_code,
        resolution_explanation=explanation,
        auto_seeded=True,
        analyst_reviewed=False,
    )


def rejected_row_for_candidate(
    *,
    candidate: Mapping[str, Any],
    resolution_version: str,
    resolution_batch_id: uuid.UUID,
) -> dict[str, Any]:
    explanation = (
        "This bridge candidate is already marked excluded in the candidate bridge table, so it is seeded as rejected "
        "and kept out of downstream scope."
    )
    return build_resolution_row(
        candidate=candidate,
        resolution_version=resolution_version,
        resolution_batch_id=resolution_batch_id,
        rule_code="RESOLVE_SEED_005",
        resolution_status="rejected",
        scope_include_flag=False,
        allocation_pct=None,
        allocation_method="seeded_default",
        resolution_method="auto_seed",
        resolution_reason_code="bridge_candidate_excluded",
        resolution_explanation=explanation,
        auto_seeded=True,
        analyst_reviewed=False,
    )


def seed_anchor_resolution_rows(
    *,
    candidates: Sequence[Mapping[str, Any]],
    resolution_version: str,
    resolution_batch_id: uuid.UUID,
    analyst_anchor_locked: bool = False,
) -> list[dict[str, Any]]:
    anchor_candidates = sorted((dict(row) for row in candidates), key=candidate_sort_key)
    if not anchor_candidates:
        return []
    viable = [row for row in anchor_candidates if not bool(row.get("is_excluded"))]
    accepted_bridge_id: int | None = None
    accepted_rule_code: str | None = None
    if not analyst_anchor_locked and len(viable) == 1 and is_high_tier_a(viable[0]):
        accepted_bridge_id = int(viable[0]["id"])
        accepted_rule_code = "RESOLVE_AUTO_001"
    elif not analyst_anchor_locked:
        dominant = unique_dominant_high_candidate(viable)
        if dominant is not None:
            accepted_bridge_id = int(dominant["id"])
            accepted_rule_code = "RESOLVE_AUTO_002"

    seeded_rows: list[dict[str, Any]] = []
    for candidate in anchor_candidates:
        if bool(candidate.get("is_excluded")):
            seeded_rows.append(
                rejected_row_for_candidate(
                    candidate=candidate,
                    resolution_version=resolution_version,
                    resolution_batch_id=resolution_batch_id,
                )
            )
            continue
        if accepted_bridge_id is not None and int(candidate["id"]) == accepted_bridge_id and accepted_rule_code:
            seeded_rows.append(
                accepted_row_for_candidate(
                    candidate=candidate,
                    resolution_version=resolution_version,
                    resolution_batch_id=resolution_batch_id,
                    rule_code=accepted_rule_code,
                )
            )
            continue
        seeded_rows.append(
            unresolved_row_for_candidate(
                candidate=candidate,
                resolution_version=resolution_version,
                resolution_batch_id=resolution_batch_id,
                analyst_anchor_locked=analyst_anchor_locked,
                viable_candidate_count=len(viable),
            )
        )
    return seeded_rows


def serialize_compare_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    if isinstance(value, list):
        return tuple(serialize_compare_value(item) for item in value)
    return value


def resolution_rows_equivalent(existing: Mapping[str, Any], desired: Mapping[str, Any]) -> bool:
    keys = (set(existing.keys()) | set(desired.keys())) - COMPARE_IGNORE_FIELDS
    for key in keys:
        if serialize_compare_value(existing.get(key)) != serialize_compare_value(desired.get(key)):
            return False
    return True


def plan_resolution_writes(
    *,
    desired_rows: Sequence[Mapping[str, Any]],
    current_rows_by_bridge_id: Mapping[int, Mapping[str, Any]],
    protect_existing_analyst_rows: bool = True,
) -> ResolutionWritePlan:
    insert_rows: list[dict[str, Any]] = []
    superseded_resolution_ids: list[int] = []
    protected_resolution_ids: list[int] = []
    preserved_current_rows: list[dict[str, Any]] = []
    processed_bridge_ids: set[int] = set()

    for desired in desired_rows:
        bridge_id = int(desired["bridge_id"])
        processed_bridge_ids.add(bridge_id)
        current = current_rows_by_bridge_id.get(bridge_id)
        if current is None:
            insert_rows.append(dict(desired))
            continue
        if resolution_rows_equivalent(current, desired):
            preserved_current_rows.append(dict(current))
            continue
        if protect_existing_analyst_rows and bool(current.get("analyst_reviewed")):
            protected_resolution_ids.append(int(current["id"]))
            preserved_current_rows.append(dict(current))
            continue
        new_row = dict(desired)
        new_row["supersedes_resolution_id"] = int(current["id"])
        insert_rows.append(new_row)
        superseded_resolution_ids.append(int(current["id"]))

    for bridge_id, current in current_rows_by_bridge_id.items():
        if bridge_id in processed_bridge_ids:
            continue
        preserved_current_rows.append(dict(current))
        if bool(current.get("analyst_reviewed")):
            protected_resolution_ids.append(int(current["id"]))

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
    return ResolutionWritePlan(
        insert_rows=insert_rows,
        superseded_resolution_ids=sorted(set(superseded_resolution_ids)),
        protected_resolution_ids=sorted(set(protected_resolution_ids)),
        preserved_current_rows=preserved_current_rows,
        current_scope_rows=current_scope_rows,
    )


def build_desired_resolution_rows(
    *,
    bridge_candidates: Sequence[Mapping[str, Any]],
    resolution_version: str,
    analyst_locked_anchor_ids: set[str],
) -> list[dict[str, Any]]:
    resolution_batch_id = uuid.uuid4()
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in bridge_candidates:
        grouped[str(row["budget_anchor_id"])].append(dict(row))

    desired_rows: list[dict[str, Any]] = []
    for budget_anchor_id in sorted(grouped):
        desired_rows.extend(
            seed_anchor_resolution_rows(
                candidates=grouped[budget_anchor_id],
                resolution_version=resolution_version,
                resolution_batch_id=resolution_batch_id,
                analyst_anchor_locked=budget_anchor_id in analyst_locked_anchor_ids,
            )
        )
    desired_rows.sort(
        key=lambda row: (
            row.get("fiscal_year") or 0,
            str(row.get("budget_anchor_id")),
            str(row.get("system_name")),
            -float(row.get("match_confidence") or 0),
            str(row.get("source_record_id")),
        )
    )
    return desired_rows


def resolution_scope_conditions(args: argparse.Namespace) -> tuple[list[str], dict[str, Any]]:
    conditions = ["bridge_version = :bridge_version"]
    params: dict[str, Any] = {"bridge_version": args.bridge_version}
    if args.system_name != "all":
        conditions.append("system_name = :system_name")
        params["system_name"] = args.system_name
    if args.fiscal_year is not None:
        conditions.append("fiscal_year = :fiscal_year")
        params["fiscal_year"] = args.fiscal_year
    categories = parse_category_filter(args.appropriation_category)
    if categories:
        conditions.append("appropriation_category = ANY(:appropriation_categories)")
        params["appropriation_categories"] = list(sorted(categories))
    if args.only_regular:
        conditions.append("is_regular_appropriation = TRUE")
    return conditions, params


def load_scope_anchor_ids(connection: Connection, args: argparse.Namespace) -> list[str]:
    conditions, params = resolution_scope_conditions(args)
    sql = (
        f"SELECT budget_anchor_id, MIN(fiscal_year) AS fiscal_year "
        f"FROM {BRIDGE_TABLE_FQTN} "
        f"WHERE {' AND '.join(conditions)} "
        "GROUP BY budget_anchor_id "
        "ORDER BY MIN(fiscal_year) NULLS LAST, budget_anchor_id"
    )
    if args.limit_anchors:
        sql = f"{sql} LIMIT :limit_anchors"
        params["limit_anchors"] = args.limit_anchors
    rows = connection.execute(text(sql), params).mappings().all()
    return [str(row["budget_anchor_id"]) for row in rows]


def load_bridge_candidates(
    connection: Connection,
    *,
    args: argparse.Namespace,
    anchor_ids: Sequence[str],
) -> list[dict[str, Any]]:
    if not anchor_ids:
        return []
    conditions, params = resolution_scope_conditions(args)
    conditions.append("budget_anchor_id = ANY(:anchor_ids)")
    params["anchor_ids"] = list(anchor_ids)
    sql = (
        f"SELECT * FROM {BRIDGE_TABLE_FQTN} "
        f"WHERE {' AND '.join(conditions)} "
        "ORDER BY fiscal_year NULLS LAST, budget_anchor_id, system_name, match_confidence DESC, source_record_id"
    )
    rows = connection.execute(text(sql), params).mappings().all()
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
        f"SELECT * FROM {RESOLUTION_TABLE_FQTN} "
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


def seed_rule_registry(
    connection: Connection,
    *,
    resolution_version: str,
    dry_run: bool,
) -> None:
    rows = [
        {
            "rule_code": rule.rule_code,
            "resolution_version": resolution_version,
            "rule_group": rule.rule_group,
            "description": rule.description,
            "resolution_status_output": rule.resolution_status_output,
            "scope_include_output": rule.scope_include_output,
            "default_allocation_pct": quantize_allocation(rule.default_allocation_pct),
            "resolution_method_output": rule.resolution_method_output,
            "priority": rule.priority,
            "is_active": True,
        }
        for rule in RULE_DEFINITIONS
    ]
    if dry_run:
        return
    insert_stmt = pg_insert(RULE_REGISTRY_TABLE).values(rows)
    connection.execute(
        insert_stmt.on_conflict_do_update(
            index_elements=[RULE_REGISTRY_TABLE.c.rule_code],
            set_={
                "resolution_version": insert_stmt.excluded.resolution_version,
                "rule_group": insert_stmt.excluded.rule_group,
                "description": insert_stmt.excluded.description,
                "resolution_status_output": insert_stmt.excluded.resolution_status_output,
                "scope_include_output": insert_stmt.excluded.scope_include_output,
                "default_allocation_pct": insert_stmt.excluded.default_allocation_pct,
                "resolution_method_output": insert_stmt.excluded.resolution_method_output,
                "priority": insert_stmt.excluded.priority,
                "is_active": insert_stmt.excluded.is_active,
            },
        )
    )


def delete_resolution_scope(
    connection: Connection,
    *,
    resolution_version: str,
    bridge_ids: Sequence[int],
    dry_run: bool,
) -> int:
    if dry_run or not bridge_ids:
        return 0
    sql = (
        f"DELETE FROM {RESOLUTION_TABLE_FQTN} "
        "WHERE resolution_version = :resolution_version "
        "AND bridge_id = ANY(:bridge_ids)"
    )
    result = connection.execute(
        text(sql),
        {
            "resolution_version": resolution_version,
            "bridge_ids": list(bridge_ids),
        },
    )
    return int(result.rowcount or 0)


def supersede_resolution_rows(
    connection: Connection,
    *,
    resolution_ids: Sequence[int],
    dry_run: bool,
) -> int:
    if dry_run or not resolution_ids:
        return 0
    sql = (
        f"UPDATE {RESOLUTION_TABLE_FQTN} "
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


def summarize_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Counter[Any]]:
    return {
        "by_status": Counter(str(row["resolution_status"]) for row in rows),
        "by_system_status": Counter((str(row["system_name"]), str(row["resolution_status"])) for row in rows),
        "by_category_status": Counter(
            (str(row["appropriation_category"]), str(row["resolution_status"])) for row in rows
        ),
        "by_seed_review": Counter((bool(row.get("auto_seeded")), bool(row.get("analyst_reviewed"))) for row in rows),
    }


def print_summary(
    *,
    bridge_candidates: Sequence[Mapping[str, Any]],
    plan: ResolutionWritePlan,
    resolution_version: str,
    truncated_rows: int,
    inserted_rows: int,
    superseded_rows: int,
    dry_run: bool,
) -> None:
    print(f"resolution_version={resolution_version}")
    print(f"bridge_candidate_count={len(bridge_candidates)}")
    print(f"current_resolution_row_count={len(plan.current_scope_rows)}")
    print(f"rows_deleted={truncated_rows}")
    print(f"rows_inserted={inserted_rows}")
    print(f"rows_superseded={superseded_rows}")
    print(f"protected_analyst_rows={len(plan.protected_resolution_ids)}")
    print(f"dry_run={dry_run}")

    summaries = summarize_rows(plan.current_scope_rows)
    if summaries["by_status"]:
        print("counts_by_resolution_status:")
        for status, count in sorted(summaries["by_status"].items()):
            print(f"  {status}={count}")
    if summaries["by_system_status"]:
        print("counts_by_system_and_status:")
        for (system_name, status), count in sorted(summaries["by_system_status"].items()):
            print(f"  {system_name} | {status}={count}")
    if summaries["by_category_status"]:
        print("counts_by_category_and_status:")
        for (category, status), count in sorted(summaries["by_category_status"].items()):
            print(f"  {category} | {status}={count}")
    if summaries["by_seed_review"]:
        print("counts_by_auto_seeded_and_analyst_reviewed:")
        for (auto_seeded, analyst_reviewed), count in sorted(summaries["by_seed_review"].items()):
            print(f"  auto_seeded={auto_seeded} | analyst_reviewed={analyst_reviewed}={count}")


def main() -> None:
    args = parse_args()
    engine = create_engine(args.db_url, future=True)
    with engine.begin() as connection:
        seed_rule_registry(connection, resolution_version=args.resolution_version, dry_run=args.dry_run)
        anchor_ids = load_scope_anchor_ids(connection, args)
        if not anchor_ids:
            print(f"resolution_version={args.resolution_version}")
            print("bridge_candidate_count=0")
            print("current_resolution_row_count=0")
            print("rows_deleted=0")
            print("rows_inserted=0")
            print("rows_superseded=0")
            print("protected_analyst_rows=0")
            print(f"dry_run={args.dry_run}")
            return

        bridge_candidates = load_bridge_candidates(connection, args=args, anchor_ids=anchor_ids)
        current_rows = load_current_resolution_rows(
            connection,
            resolution_version=args.resolution_version,
            anchor_ids=anchor_ids,
        )
        current_rows_by_bridge_id = {int(row["bridge_id"]): row for row in current_rows}
        analyst_locked_anchor_ids = {
            str(row["budget_anchor_id"])
            for row in current_rows
            if bool(row.get("analyst_reviewed"))
        }

        desired_rows = build_desired_resolution_rows(
            bridge_candidates=bridge_candidates,
            resolution_version=args.resolution_version,
            analyst_locked_anchor_ids=analyst_locked_anchor_ids,
        )
        plan = plan_resolution_writes(
            desired_rows=desired_rows,
            current_rows_by_bridge_id=current_rows_by_bridge_id,
        )

        bridge_ids = [int(row["id"]) for row in bridge_candidates]
        truncated_rows = 0
        superseded_rows = 0
        inserted_rows = 0
        if args.truncate:
            truncated_rows = delete_resolution_scope(
                connection,
                resolution_version=args.resolution_version,
                bridge_ids=bridge_ids,
                dry_run=args.dry_run,
            )
            inserted_rows = insert_resolution_rows(
                connection,
                rows=desired_rows,
                batch_size=args.batch_size,
                dry_run=args.dry_run,
            )
            plan = ResolutionWritePlan(
                insert_rows=list(desired_rows),
                superseded_resolution_ids=[],
                protected_resolution_ids=[],
                preserved_current_rows=[],
                current_scope_rows=list(desired_rows),
            )
        else:
            superseded_rows = supersede_resolution_rows(
                connection,
                resolution_ids=plan.superseded_resolution_ids,
                dry_run=args.dry_run,
            )
            inserted_rows = insert_resolution_rows(
                connection,
                rows=plan.insert_rows,
                batch_size=args.batch_size,
                dry_run=args.dry_run,
            )

        print_summary(
            bridge_candidates=bridge_candidates,
            plan=plan,
            resolution_version=args.resolution_version,
            truncated_rows=truncated_rows,
            inserted_rows=inserted_rows,
            superseded_rows=superseded_rows,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
