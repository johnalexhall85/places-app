#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db_fqtn import cdc_funding_table  # noqa: E402
from app.funding.classification import classify_funding_row  # noqa: E402


DEFAULT_DB_URL = "postgresql+psycopg://places:places@localhost:5432/places"
DEFAULT_CHUNK_SIZE = 5_000
FACT_TABLE = cdc_funding_table("fact_cdc_funding_prime_transaction")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill CDC funding classification fields.")
    parser.add_argument("--db-url", default=os.getenv("DATABASE_URL", DEFAULT_DB_URL))
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--fiscal-year", action="append", type=int, default=[])
    parser.add_argument(
        "--refresh-aggregates",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Refresh funding materialized views after backfill (default: true).",
    )
    return parser.parse_args()


def merged_row(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("raw_record") or {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        **raw,
        "assistance_listing_number": row.get("assistance_listing_number"),
        "assistance_listing_title": row.get("assistance_listing_title"),
        "source_fiscal_year": row.get("source_fiscal_year"),
        "funding_mechanism": row.get("funding_mechanism"),
        "transaction_description": row.get("transaction_description"),
        "prime_award_base_transaction_description": row.get("prime_award_base_transaction_description"),
        "federal_accounts_funding_this_award": row.get("federal_accounts_funding_this_award"),
        "treasury_accounts_funding_this_award": row.get("treasury_accounts_funding_this_award"),
        "covid_supplemental_obligated_amount": row.get("covid_supplemental_obligated_amount"),
        "iija_supplemental_obligated_amount": row.get("iija_supplemental_obligated_amount"),
    }


def fetch_rows(connection: sa.Connection, *, last_id: int, chunk_size: int, fiscal_years: list[int]) -> list[dict[str, Any]]:
    clauses = ["id > :last_id"]
    params: dict[str, Any] = {"last_id": last_id, "limit": chunk_size}
    if fiscal_years:
        clauses.append("source_fiscal_year = ANY(:fiscal_years)")
        params["fiscal_years"] = fiscal_years
    return [
        dict(row._mapping)
        for row in connection.execute(
            text(
                f"""
                SELECT
                    id,
                    source_fiscal_year,
                    funding_mechanism,
                    raw_record,
                    assistance_listing_number,
                    assistance_listing_title,
                    transaction_description,
                    prime_award_base_transaction_description,
                    federal_accounts_funding_this_award,
                    treasury_accounts_funding_this_award,
                    covid_supplemental_obligated_amount,
                    iija_supplemental_obligated_amount
                FROM {FACT_TABLE}
                WHERE {" AND ".join(clauses)}
                ORDER BY id
                LIMIT :limit
                """
            ),
            params,
        )
    ]


def update_rows(connection: sa.Connection, rows: list[dict[str, Any]]) -> Counter:
    stats: Counter = Counter()
    for row in rows:
        classification = classify_funding_row(merged_row(row))
        connection.execute(
            text(
                f"""
                UPDATE {FACT_TABLE}
                SET
                    defc_codes = CAST(:defc_codes AS jsonb),
                    defc_classification = :defc_classification,
                    has_defc_q = :has_defc_q,
                    has_defc_non_q = :has_defc_non_q,
                    has_defc_covid = :has_defc_covid,
                    has_defc_arp = :has_defc_arp,
                    has_defc_other_emergency = :has_defc_other_emergency,
                    has_overall_award_supplemental_history = :has_overall_award_supplemental_history,
                    is_likely_vfc = :is_likely_vfc,
                    is_covid_era_immunization_response = :is_covid_era_immunization_response,
                    is_profile_aligned_emergency_supplemental = :is_profile_aligned_emergency_supplemental,
                    funding_profiles_comparison_excluded = :funding_profiles_comparison_excluded,
                    funding_profiles_exclusion_reason = :funding_profiles_exclusion_reason,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": row["id"], **{**classification, "defc_codes": json.dumps(classification["defc_codes"])}},
        )
        stats["rows"] += 1
        stats[f"defc_classification:{classification['defc_classification']}"] += 1
        for field in (
            "has_overall_award_supplemental_history",
            "is_likely_vfc",
            "is_covid_era_immunization_response",
            "is_profile_aligned_emergency_supplemental",
            "funding_profiles_comparison_excluded",
        ):
            stats[f"{field}:{classification[field]}"] += 1
        for reason in (classification["funding_profiles_exclusion_reason"] or "(none)").split(";"):
            stats[f"funding_profiles_exclusion_reason:{reason}"] += 1
    return stats


def refresh_aggregates(connection: sa.Connection) -> None:
    for view_name in (
        "mv_cdc_funding_map_county",
        "mv_cdc_funding_map_state_all_positive",
    ):
        connection.execute(text(f"REFRESH MATERIALIZED VIEW {cdc_funding_table(view_name)}"))


def print_counts(stats: Counter) -> None:
    print(f"Backfilled rows: {stats['rows']:,}")
    for prefix in (
        "defc_classification:",
        "has_overall_award_supplemental_history:",
        "is_likely_vfc:",
        "is_covid_era_immunization_response:",
        "is_profile_aligned_emergency_supplemental:",
        "funding_profiles_comparison_excluded:",
        "funding_profiles_exclusion_reason:",
    ):
        print(prefix.rstrip(":"))
        for key, count in sorted((item for item in stats.items() if item[0].startswith(prefix))):
            print(f"  {key.removeprefix(prefix)}: {count:,}")


def main() -> int:
    args = parse_args()
    engine = sa.create_engine(args.db_url, future=True)
    stats: Counter = Counter()
    fiscal_years = sorted(set(args.fiscal_year))
    with engine.begin() as connection:
        last_id = 0
        while True:
            rows = fetch_rows(
                connection,
                last_id=last_id,
                chunk_size=args.chunk_size,
                fiscal_years=fiscal_years,
            )
            if not rows:
                break
            stats.update(update_rows(connection, rows))
            last_id = int(rows[-1]["id"])
        if args.refresh_aggregates:
            refresh_aggregates(connection)
    print_counts(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
