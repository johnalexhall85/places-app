#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.usaspending_fed_account.ingest import DEFAULT_DB_URL, fetch_reconciliation_rows  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify that the USAspending federal account reconciliation view returns rows."
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or local development DSN).",
    )
    parser.add_argument(
        "--years",
        nargs="*",
        type=int,
        default=[2020, 2021, 2022, 2023, 2024, 2025, 2026],
        help="Fiscal years to query.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    engine = create_engine(args.db_url, pool_pre_ping=True)
    try:
        rows = fetch_reconciliation_rows(engine, years=args.years)
    finally:
        engine.dispose()
    if not rows:
        raise SystemExit("No reconciliation rows returned. Run the migration and ingest first.")
    print(f"Reconciliation view returned {len(rows)} account-year row(s).")
    for row in rows[:5]:
        print(
            "FY{fiscal_year} {normalized_account_key}: balance={balance_obligations} "
            "awards={award_obligations_total} pa_oc={pa_oc_obligations_total}".format(**row)
        )


if __name__ == "__main__":
    main()

