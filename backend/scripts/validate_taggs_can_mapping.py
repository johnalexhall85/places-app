from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import DEFAULT_DB_URL
from app.taggs.services import fetch_can_mapping_status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate that TAGGS derived tables contain interpreted CAN mappings.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or the local development DSN).",
    )
    parser.add_argument(
        "--min-mapped-ratio",
        type=float,
        default=0.60,
        help="Minimum acceptable mapped_can_count / can_count ratio (default: 0.60).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    engine = create_engine(args.db_url, future=True)
    with Session(engine) as session:
        status = fetch_can_mapping_status(session)

    can_count = int(status.get("can_count") or 0)
    mapped_count = int(status.get("mapped_can_count") or 0)
    mapped_ratio = (mapped_count / can_count) if can_count > 0 else 0.0

    print(f"status={status.get('status')}")
    print(f"can_mapping_version={status.get('can_mapping_version')}")
    print(f"can_count={can_count}")
    print(f"mapped_can_count={mapped_count}")
    print(f"profile_assisted_can_count={int(status.get('profile_assisted_can_count') or 0)}")
    print(f"fallback_inferred_can_count={int(status.get('fallback_inferred_can_count') or 0)}")
    print(f"unresolved_can_count={int(status.get('unresolved_can_count') or 0)}")
    print(f"mapped_ratio={mapped_ratio:.3f}")
    print(f"summary_has_effective_columns={bool(status.get('summary_has_effective_columns'))}")

    if not status.get("summary_has_effective_columns"):
        print("FAIL: taggs.award_funding_summary does not contain rebuilt interpreted CAN columns.", file=sys.stderr)
        return 1
    if can_count == 0:
        print("FAIL: no CANs found in TAGGS derived summaries.", file=sys.stderr)
        return 1
    if mapped_ratio < float(args.min_mapped_ratio):
        print(
            f"FAIL: mapped CAN ratio {mapped_ratio:.3f} is below threshold {float(args.min_mapped_ratio):.3f}.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
