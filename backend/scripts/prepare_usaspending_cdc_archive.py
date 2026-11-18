#!/usr/bin/env python3
"""Prepare a CDC award-level prime-transaction file from a USAspending Award Data Archive file.

Why: on 2026-11-18 USAspending's search and bulk-download index served no FY2026 HHS assistance
transactions, and the FY2026 HHS archive (FY2026_075_Assistance_Full_20261106) has the transactions
through 2026-09-30 but a blank funding_opportunity_number on almost every row. CHIP links awards
to NOFOs through that field, so this script restores it from values USAspending published earlier:

  1. same assistance_transaction_unique_key in an earlier CHIP download (--previous CSV) -> "previous_transaction"
  2. otherwise, the award's single FON in earlier CHIP raw rows (database, any fiscal year) -> "award_history"
     (awards with more than one historical FON are left blank; the funding_report builder still links them)

Rows that already carry a FON keep it ("usaspending"). The column chip_fon_backfill records which rule
applied. Only rows whose awarding sub-agency is CDC are written. Output columns: the archive's columns
plus chip_fon_backfill. Nothing is ingested.

    python scripts/prepare_usaspending_cdc_archive.py \
        --archive ../data/usaspending/chipfunding/fy26_archive_20261106/FY2026_075_Assistance_Full_20261108_1.csv \
        --previous ../data/usaspending/chipfunding/fy26/All_Assistance_PrimeTransactions_2026-07-02_H18M17S30_1.csv \
        --out ../data/usaspending/chipfunding/fy26_archive_20261106/CDC_Assistance_PrimeTransactions_FY2026_archive_20261106.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

import psycopg

CDC = "Centers for Disease Control and Prevention"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--db-url", default=os.getenv("DATABASE_URL", "postgresql://places:places@localhost:5432/places")
                        .replace("postgresql+psycopg://", "postgresql://"))
    args = parser.parse_args()
    csv.field_size_limit(10**9)

    previous = {}
    with open(args.previous, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("funding_opportunity_number"):
                previous[row["assistance_transaction_unique_key"]] = row["funding_opportunity_number"]

    history: dict[str, set[str]] = defaultdict(set)
    with psycopg.connect(args.db_url) as conn:
        for key, fon in conn.execute(
            "SELECT DISTINCT raw_record->>'assistance_award_unique_key', raw_record->>'funding_opportunity_number' "
            "FROM cdc_funding.raw_usaspending_assistance_prime_transactions "
            "WHERE COALESCE(raw_record->>'funding_opportunity_number', '') <> ''"
        ):
            history[key].add(fon)

    stats: Counter = Counter()
    with open(args.archive, encoding="utf-8-sig", newline="") as src, \
            open(args.out, "w", encoding="utf-8", newline="") as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=[*reader.fieldnames, "chip_fon_backfill"])
        writer.writeheader()
        for row in reader:
            stats["archive_rows"] += 1
            if row.get("awarding_sub_agency_name") != CDC:
                continue
            stats["cdc_rows"] += 1
            rule = ""
            if row.get("funding_opportunity_number"):
                rule = "usaspending"
            elif row["assistance_transaction_unique_key"] in previous:
                row["funding_opportunity_number"] = previous[row["assistance_transaction_unique_key"]]
                rule = "previous_transaction"
            elif len(history.get(row["assistance_award_unique_key"], ())) == 1:
                row["funding_opportunity_number"] = next(iter(history[row["assistance_award_unique_key"]]))
                rule = "award_history"
            row["chip_fon_backfill"] = rule
            stats[f"fon_{rule or 'blank'}"] += 1
            stats["max_action_date"] = max(stats.get("max_action_date") or "", row.get("action_date") or "")
            writer.writerow(row)
    summary = {"archive": str(args.archive), "previous": str(args.previous), "out": str(args.out), **stats}
    args.out.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
