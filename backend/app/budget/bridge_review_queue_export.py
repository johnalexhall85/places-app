from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from app.db import DEFAULT_DB_URL
from app.db_fqtn import budget_table

DEFAULT_BRIDGE_VERSION = "v1_budget_spending_bridge"
DEFAULT_RESOLUTION_VERSION = "v1_bridge_resolution"

CURRENT_RESOLUTION_VIEW_FQTN = budget_table("v_cdc_budget_spending_bridge_resolution_current_v1")
ANCHOR_REVIEW_STATE_VIEW_FQTN = budget_table("v_cdc_budget_spending_anchor_review_state_v1")
UNRESOLVED_QUEUE_VIEW_FQTN = budget_table("v_cdc_budget_spending_review_queue_unresolved_v1")
HIGH_PRIORITY_REGULAR_VIEW_FQTN = budget_table("v_cdc_budget_spending_review_queue_high_priority_regular_v1")
RESOLUTION_REVIEW_QUEUE_VIEW_FQTN = budget_table("v_cdc_budget_spending_bridge_resolution_review_queue_v1")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export analyst-friendly bridge review queue rows to CSV.",
    )
    parser.add_argument("--output-file", required=True, help="Destination CSV path.")
    parser.add_argument("--resolution-version", default=DEFAULT_RESOLUTION_VERSION)
    parser.add_argument("--bridge-version", default=DEFAULT_BRIDGE_VERSION)
    parser.add_argument("--appropriation-category", default=None)
    parser.add_argument("--only-regular", action="store_true")
    parser.add_argument("--fiscal-year", type=int, default=None)
    parser.add_argument("--system-name", default=None, choices=("usaspending", "taggs"))
    parser.add_argument("--limit-anchors", type=int, default=None)
    parser.add_argument(
        "--queue-type",
        default="review_queue",
        choices=("review_queue", "unresolved", "high_confidence_ambiguous"),
    )
    parser.add_argument("--db-url", default=os.getenv("DATABASE_URL", DEFAULT_DB_URL))
    return parser.parse_args()


def anchor_source_view(queue_type: str) -> str:
    if queue_type == "high_confidence_ambiguous":
        return RESOLUTION_REVIEW_QUEUE_VIEW_FQTN
    return UNRESOLVED_QUEUE_VIEW_FQTN


def build_anchor_filters(args: argparse.Namespace) -> tuple[list[str], dict[str, Any]]:
    filters = ["1=1"]
    params: dict[str, Any] = {}
    if args.appropriation_category:
        filters.append("appropriation_category = ANY(:appropriation_categories)")
        params["appropriation_categories"] = [part.strip().upper() for part in args.appropriation_category.split(",") if part.strip()]
    if args.only_regular:
        filters.append("is_regular_appropriation = TRUE")
    if args.fiscal_year is not None:
        filters.append("fiscal_year = :fiscal_year")
        params["fiscal_year"] = args.fiscal_year
    return filters, params


def export_rows(connection: Connection, args: argparse.Namespace) -> list[dict[str, Any]]:
    anchor_view = anchor_source_view(args.queue_type)
    anchor_filters, params = build_anchor_filters(args)
    order_by = (
        "CASE WHEN is_regular_appropriation THEN 0 ELSE 1 END, "
        "highest_current_confidence DESC NULLS LAST, fiscal_year NULLS LAST, budget_anchor_id"
    )
    anchor_sql = (
        f"SELECT budget_anchor_id FROM {anchor_view} "
        f"WHERE {' AND '.join(anchor_filters)} "
        f"ORDER BY {order_by}"
    )
    if args.limit_anchors is not None:
        anchor_sql = f"{anchor_sql} LIMIT :limit_anchors"
        params["limit_anchors"] = args.limit_anchors

    resolution_filters = ["r.resolution_version = :resolution_version", "r.bridge_version = :bridge_version"]
    params["resolution_version"] = args.resolution_version
    params["bridge_version"] = args.bridge_version
    if args.system_name:
        resolution_filters.append("r.system_name = :system_name")
        params["system_name"] = args.system_name

    sql = f"""
        WITH anchor_set AS (
            {anchor_sql}
        )
        SELECT
            r.budget_anchor_id,
            r.unique_id,
            r.fiscal_year,
            r.appropriation_category,
            r.budget_program,
            r.budget_sub_program,
            r.system_name,
            r.bridge_id,
            r.source_record_id,
            r.match_tier,
            r.match_type,
            r.match_confidence,
            r.match_explanation,
            r.resolution_status AS current_resolution_status,
            s.total_candidate_count AS candidate_count_for_anchor,
            s.accepted_allocation_sum AS accepted_allocation_sum_for_anchor,
            ''::text AS analyst_action,
            ''::text AS allocation_pct,
            ''::text AS scope_include_flag,
            ''::text AS action_reason_code,
            ''::text AS action_explanation,
            ''::text AS reviewer_name,
            ''::text AS reviewer_email,
            ''::text AS review_notes
        FROM {CURRENT_RESOLUTION_VIEW_FQTN} AS r
        JOIN anchor_set AS a
          ON a.budget_anchor_id = r.budget_anchor_id
        LEFT JOIN {ANCHOR_REVIEW_STATE_VIEW_FQTN} AS s
          ON s.budget_anchor_id = r.budget_anchor_id
        WHERE {' AND '.join(resolution_filters)}
        ORDER BY
            CASE WHEN r.is_regular_appropriation THEN 0 ELSE 1 END,
            r.fiscal_year NULLS LAST,
            r.budget_anchor_id,
            r.system_name,
            r.match_confidence DESC,
            r.source_record_id
    """
    rows = connection.execute(text(sql), params).mappings().all()
    return [dict(row) for row in rows]


def write_csv(output_file: str, rows: list[dict[str, Any]]) -> None:
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "budget_anchor_id",
        "unique_id",
        "fiscal_year",
        "appropriation_category",
        "budget_program",
        "budget_sub_program",
        "system_name",
        "bridge_id",
        "source_record_id",
        "match_tier",
        "match_type",
        "match_confidence",
        "match_explanation",
        "current_resolution_status",
        "candidate_count_for_anchor",
        "accepted_allocation_sum_for_anchor",
        "analyst_action",
        "allocation_pct",
        "scope_include_flag",
        "action_reason_code",
        "action_explanation",
        "reviewer_name",
        "reviewer_email",
        "review_notes",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def main() -> None:
    args = parse_args()
    engine = create_engine(args.db_url, future=True)
    with engine.begin() as connection:
        rows = export_rows(connection, args)
    write_csv(args.output_file, rows)
    print(f"rows_exported={len(rows)}")
    print(f"output_file={args.output_file}")


if __name__ == "__main__":
    main()
