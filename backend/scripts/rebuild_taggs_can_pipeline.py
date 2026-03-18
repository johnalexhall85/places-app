#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import DEFAULT_DB_URL  # noqa: E402
from app.taggs.can_profile_matcher import (  # noqa: E402
    build_can_profile_mapping,
    _parse_csv_cans,
    _parse_csv_years,
)
from app.taggs.rebuild import rebuild_taggs_derived_layers  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the CDC-profile-assisted TAGGS CAN mapping pipeline.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or the local development DSN).",
    )
    parser.add_argument(
        "--use-cdc-profiles",
        action="store_true",
        help="Build the CDC-profile-assisted CAN mapping stage.",
    )
    parser.add_argument(
        "--rebuild-summaries",
        action="store_true",
        help="Rebuild taggs.award_funding_summary and taggs.state_funding_summary.",
    )
    parser.add_argument(
        "--rebuild-normalization",
        action="store_true",
        help="Rebuild recon.normalized_state_funding and related reconciliation outputs.",
    )
    parser.add_argument(
        "--rebuild-profiles",
        action="store_true",
        help="Alias for rebuilding TAGGS profile support tables/views (same summary rebuild stage).",
    )
    parser.add_argument(
        "--limit-years",
        default=None,
        help="Optional comma-separated fiscal years to target.",
    )
    parser.add_argument(
        "--limit-cans",
        default=None,
        help="Optional comma-separated CAN codes to target.",
    )
    parser.add_argument(
        "--only-unmapped",
        action="store_true",
        help="Only refresh currently unmapped CANs in the mapping stage.",
    )
    parser.add_argument(
        "--export-review-csv",
        action="store_true",
        help="Export data/taggs/review/can_profile_mapping_review.csv after the mapping stage.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build payloads without writing to the database.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress information while running.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    limit_years = _parse_csv_years(args.limit_years)
    limit_cans = _parse_csv_cans(args.limit_cans)
    review_path = (
        (BACKEND_ROOT.parent / "data" / "taggs" / "review" / "can_profile_mapping_review.csv").resolve()
        if args.export_review_csv
        else None
    )

    output: dict[str, object] = {}
    if args.use_cdc_profiles:
        output["can_mapping"] = build_can_profile_mapping(
            db_url=args.db_url,
            limit_years=limit_years,
            limit_cans=limit_cans,
            only_unmapped=bool(args.only_unmapped),
            export_review_csv_path=review_path,
            dry_run=bool(args.dry_run),
            verbose=bool(args.verbose),
        )

    if args.rebuild_summaries or args.rebuild_profiles or args.rebuild_normalization:
        output["taggs_rebuild"] = rebuild_taggs_derived_layers(
            db_url=args.db_url,
            limit_years=limit_years,
            limit_cans=limit_cans,
            rebuild_normalization=bool(args.rebuild_normalization),
            dry_run=bool(args.dry_run),
        )

    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
