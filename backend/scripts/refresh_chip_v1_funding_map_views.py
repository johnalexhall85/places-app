#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.cdc_funding import chip_v1  # noqa: E402
from app.db import DEFAULT_DB_URL  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh CHIP v1 CDC funding map materialized views.")
    parser.add_argument(
        "--classification-version",
        default=chip_v1.CLASSIFICATION_VERSION_DEFAULT,
        help="Classification version to report after refreshing all materialized views.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL. Defaults to DATABASE_URL or the local development DSN.",
    )
    return parser.parse_args()


def money(value: object) -> str:
    if value is None:
        return "$0"
    numeric = Decimal(str(value))
    return f"${numeric:,.2f}"


def refresh_views(connection) -> None:
    for view_name in (chip_v1.STATE_MV, chip_v1.COUNTY_MV, chip_v1.UNMAPPED_MV):
        print(f"Refreshing {view_name}...")
        connection.execute(text(f"REFRESH MATERIALIZED VIEW {view_name}"))


def print_counts(connection, *, classification_version: str) -> None:
    for label, view_name in (
        ("state rows", chip_v1.STATE_MV),
        ("county rows", chip_v1.COUNTY_MV),
        ("unmapped rows", chip_v1.UNMAPPED_MV),
    ):
        row = connection.execute(
            text(
                f"""
                SELECT COUNT(*)::integer AS row_count
                FROM {view_name}
                WHERE classification_version = :classification_version
                """
            ),
            {"classification_version": classification_version},
        ).mappings().one()
        print(f"{label}: {row['row_count']:,}")


def print_totals_by_year_state(connection, *, classification_version: str) -> None:
    rows = connection.execute(
        text(
            f"""
            SELECT
                fiscal_year,
                state_code,
                total_obligations,
                needs_review_obligations,
                award_count,
                included_account_count
            FROM {chip_v1.STATE_MV}
            WHERE classification_version = :classification_version
            ORDER BY fiscal_year DESC, state_code ASC
            """
        ),
        {"classification_version": classification_version},
    ).mappings().all()
    print("\nState mapped totals by year/state:")
    if not rows:
        print("  No state rows found.")
        return
    for row in rows:
        print(
            "  FY{fy} {state}: total={total} pending_review={pending} awards={awards:,} accounts={accounts:,}".format(
                fy=row["fiscal_year"],
                state=row["state_code"],
                total=money(row["total_obligations"]),
                pending=money(row["needs_review_obligations"]),
                awards=int(row["award_count"] or 0),
                accounts=int(row["included_account_count"] or 0),
            )
        )


def print_needs_review_by_year(connection, *, classification_version: str) -> None:
    rows = connection.execute(
        text(
            f"""
            SELECT
                fiscal_year,
                COALESCE(SUM(total_obligations), 0)::numeric AS total_obligations,
                COALESCE(SUM(needs_review_obligations), 0)::numeric AS needs_review_obligations,
                COALESCE(SUM(needs_review_award_count), 0)::bigint AS needs_review_award_count,
                COALESCE(SUM(needs_review_account_count), 0)::bigint AS needs_review_account_count
            FROM {chip_v1.STATE_MV}
            WHERE classification_version = :classification_version
            GROUP BY fiscal_year
            ORDER BY fiscal_year
            """
        ),
        {"classification_version": classification_version},
    ).mappings().all()
    print("\nNeeds-review totals by year:")
    if not rows:
        print("  No needs-review totals found.")
        return
    for row in rows:
        print(
            "  FY{fy}: pending_review={pending} of total={total}; awards={awards:,}; account-geography rows={accounts:,}".format(
                fy=row["fiscal_year"],
                pending=money(row["needs_review_obligations"]),
                total=money(row["total_obligations"]),
                awards=int(row["needs_review_award_count"] or 0),
                accounts=int(row["needs_review_account_count"] or 0),
            )
        )


def main() -> None:
    args = parse_args()
    engine = create_engine(args.db_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            refresh_views(connection)
            print_counts(connection, classification_version=args.classification_version)
            print_needs_review_by_year(connection, classification_version=args.classification_version)
            print_totals_by_year_state(connection, classification_version=args.classification_version)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
