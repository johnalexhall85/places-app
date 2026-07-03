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
    parser = argparse.ArgumentParser(description="Validate CHIP v1 CDC funding map totals.")
    parser.add_argument(
        "--classification-version",
        default=chip_v1.CLASSIFICATION_VERSION_DEFAULT,
        help="Classification version to validate.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL. Defaults to DATABASE_URL or the local development DSN.",
    )
    parser.add_argument("--start-fy", type=int, default=2020)
    parser.add_argument("--end-fy", type=int, default=2026)
    return parser.parse_args()


def money(value: object) -> str:
    if value is None:
        return "$0"
    return f"${Decimal(str(value)):,.2f}"


def fetch_one(connection, sql: str, params: dict) -> dict:
    return dict(connection.execute(text(sql), params).mappings().one())


def fetch_all(connection, sql: str, params: dict) -> list[dict]:
    return [dict(row) for row in connection.execute(text(sql), params).mappings().all()]


def print_top_accounts(connection, *, fiscal_year: int, classification_version: str, needs_review_only: bool) -> None:
    title = "top 20 needs-review accounts" if needs_review_only else "top 20 included accounts"
    review_clause = "AND review_status = 'needs_review'" if needs_review_only else ""
    rows = fetch_all(
        connection,
        f"""
        {chip_v1._classified_award_source_sql()}
        SELECT
            normalized_account_key,
            MAX(federal_account_name) AS federal_account_name,
            MAX(review_status) AS review_status,
            COALESCE(SUM(obligation_amount), 0)::numeric AS obligations,
            COUNT(DISTINCT award_key)::bigint AS award_count
        FROM classified_awards
        WHERE classification_version = :classification_version
          AND fiscal_year = :fiscal_year
          {review_clause}
        GROUP BY normalized_account_key
        ORDER BY obligations DESC NULLS LAST
        LIMIT 20
        """,
        {"classification_version": classification_version, "fiscal_year": fiscal_year},
    )
    print(f"  {title}:")
    if not rows:
        print("    none")
        return
    for row in rows:
        account_name = str(row.get("federal_account_name") or "").strip() or "Unnamed account"
        print(
            "    {key}: {amount} ({awards:,} awards, {status}) - {name}".format(
                key=row["normalized_account_key"],
                amount=money(row["obligations"]),
                awards=int(row["award_count"] or 0),
                status=row.get("review_status") or "n/a",
                name=account_name[:120],
            )
        )


def validate_year(connection, *, fiscal_year: int, classification_version: str) -> None:
    params = {"classification_version": classification_version, "fiscal_year": fiscal_year}
    state = fetch_one(
        connection,
        f"""
        SELECT
            COALESCE(SUM(total_obligations), 0)::numeric AS total_obligations,
            COALESCE(SUM(needs_review_obligations), 0)::numeric AS needs_review_obligations,
            COALESCE(SUM(included_account_count), 0)::bigint AS included_account_count_geography_sum,
            COALESCE(SUM(needs_review_account_count), 0)::bigint AS needs_review_account_count_geography_sum
        FROM {chip_v1.STATE_MV}
        WHERE classification_version = :classification_version
          AND fiscal_year = :fiscal_year
        """,
        params,
    )
    county = fetch_one(
        connection,
        f"""
        SELECT
            COALESCE(SUM(total_obligations), 0)::numeric AS total_obligations,
            COALESCE(SUM(needs_review_obligations), 0)::numeric AS needs_review_obligations
        FROM {chip_v1.COUNTY_MV}
        WHERE classification_version = :classification_version
          AND fiscal_year = :fiscal_year
        """,
        params,
    )
    source = fetch_one(
        connection,
        f"""
        {chip_v1._classified_award_source_sql()}
        SELECT
            COALESCE(SUM(obligation_amount), 0)::numeric AS classified_award_obligations,
            COALESCE(SUM(obligation_amount) FILTER (WHERE state_code IS NOT NULL AND state_code <> ''), 0)::numeric
                AS state_mappable_obligations,
            COALESCE(SUM(obligation_amount) FILTER (WHERE county_fips ~ '^[0-9]{{5}}$'), 0)::numeric
                AS county_mappable_obligations,
            COALESCE(SUM(obligation_amount) FILTER (WHERE review_status = 'needs_review'), 0)::numeric
                AS pending_review_obligations,
            COUNT(DISTINCT normalized_account_key)::integer AS included_account_count,
            COUNT(DISTINCT normalized_account_key) FILTER (WHERE review_status = 'needs_review')::integer
                AS needs_review_account_count
        FROM classified_awards
        WHERE classification_version = :classification_version
          AND fiscal_year = :fiscal_year
        """,
        params,
    )
    unmapped = fetch_one(
        connection,
        f"""
        SELECT
            COALESCE(SUM(unmapped_award_total) FILTER (WHERE geography_level = 'state'), 0)::numeric
                AS state_unmapped_obligations,
            COALESCE(SUM(unmapped_award_total) FILTER (WHERE geography_level = 'county'), 0)::numeric
                AS county_unmapped_obligations
        FROM {chip_v1.UNMAPPED_MV}
        WHERE classification_version = :classification_version
          AND fiscal_year = :fiscal_year
        """,
        params,
    )
    state_delta = Decimal(str(source["state_mappable_obligations"])) - Decimal(str(state["total_obligations"]))
    county_delta = Decimal(str(source["county_mappable_obligations"])) - Decimal(str(county["total_obligations"]))
    print(f"\nFY{fiscal_year}")
    print(f"  total mapped state obligations: {money(state['total_obligations'])}")
    print(f"  total mapped county obligations: {money(county['total_obligations'])}")
    print(f"  pending-review mapped obligations: {money(state['needs_review_obligations'])}")
    print(f"  number of included accounts: {int(source['included_account_count'] or 0):,}")
    print(f"  number of needs-review accounts: {int(source['needs_review_account_count'] or 0):,}")
    print(f"  unmapped award obligations (state): {money(unmapped['state_unmapped_obligations'])}")
    print(f"  unmapped award obligations (county): {money(unmapped['county_unmapped_obligations'])}")
    print("  source vs materialized comparisons:")
    print(
        f"    classified baseline/public-map award obligations: {money(source['classified_award_obligations'])}"
    )
    print(
        f"    state-mappable source vs state MV delta: {money(state_delta)} "
        "(should be $0.00; state-unmapped awards are reported separately)"
    )
    print(
        f"    county-mappable source vs county MV delta: {money(county_delta)} "
        "(should be $0.00; county-unmapped awards are reported separately)"
    )
    print_top_accounts(
        connection,
        fiscal_year=fiscal_year,
        classification_version=classification_version,
        needs_review_only=False,
    )
    print_top_accounts(
        connection,
        fiscal_year=fiscal_year,
        classification_version=classification_version,
        needs_review_only=True,
    )


def main() -> None:
    args = parse_args()
    engine = create_engine(args.db_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            for fiscal_year in range(args.start_fy, args.end_fy + 1):
                validate_year(
                    connection,
                    fiscal_year=fiscal_year,
                    classification_version=args.classification_version,
                )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
