#!/usr/bin/env python3
"""Build a CDC funding fiscal-year source bundle from a USAspending federal account download.

The bundle is the 15-file folder that ``scripts/ingest_cdc_funding_source.py`` loads
(``data/chipfunding/FY####``). It reproduces the method of the original Windows pipeline
(pipeline_version 1) recorded in each bundle's ``FY####_pipeline_audit.json``:

* Assistance award rows are "Grant"; Contracts award rows are "Contract"; Unlinked rows are excluded.
* Only rows whose ``awarding_subagency_name`` is the Centers for Disease Control and Prevention are kept,
  and only HHS federal accounts (``075-``), the scope of the earlier agency-075 downloads.
* ``Emergency`` is NonEmergency when ``disaster_emergency_fund_name`` is blank or contains
  "nonemergency" (case-insensitive), and Emergency otherwise.
* Amounts are summed from ``transaction_obligated_amount`` and the cumulative
  ``gross_outlay_amount_FYB_to_period_end``; negative values are retained; source values are copied
  unchanged into the clean award file.
* CDC Funding Profile categories come from a reviewed crosswalk (the previous bundle's
  ``FY####_category_mapping_detail.csv``), carried forward unchanged.

The three validation JSON files are produced by re-reading the written CSVs and recomputing their
controls independently of the in-memory aggregation; any failed check sets ``passed: false``, which
makes the importer refuse the bundle.

Standard library only. Usage (from backend/):

    ./.venv/bin/python scripts/build_cdc_funding_bundle.py --fiscal-year 2026 \
        --assistance SRC/FY2026P01-P12_All_FA_Assistance_AccountBreakdownByAward_..._01.csv \
                     SRC/FY2026P01-P12_All_FA_Assistance_AccountBreakdownByAward_..._02.csv \
        --contracts  SRC/FY2026P01-P12_All_FA_Contracts_AccountBreakdownByAward_..._01.csv \
        --crosswalk  ../data/chipfunding/FY2026/FY2026_category_mapping_detail.csv \
        --output-dir ../data/chipfunding/FY2026_P12_candidate
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

PIPELINE_VERSION = 1
CDC_SUBAGENCY = "CENTERS FOR DISEASE CONTROL AND PREVENTION"
DEFAULT_ACCOUNT_PREFIX = "075-"
CENT = Decimal("0.01")
ZERO = Decimal("0")
UNMAPPED_REASON = "Account/source/emergency combination is not assigned to a funding category"
REFERENCE_STATUS = "No CDC Funding Profile available; USAspending-only forward estimate"
CROSSWALK_BASIS = "Reviewed FY2023 CDC Funding Profile crosswalk carried forward unchanged"

csv.field_size_limit(sys.maxsize)

SOURCE_COLUMNS = (
    "owning_agency_name,reporting_agency_name,submission_period,federal_account_symbol,federal_account_name,"
    "program_activity_reporting_key,agency_identifier_name,budget_function,budget_subfunction,program_activity_code,"
    "program_activity_name,object_class_code,object_class_name,direct_or_reimbursable_funding_source,"
    "disaster_emergency_fund_code,disaster_emergency_fund_name,transaction_obligated_amount,"
    "gross_outlay_amount_FYB_to_period_end,USSGL487200_downward_adj_prior_year_prepaid_undeliv_order_oblig,"
    "USSGL497200_downward_adj_of_prior_year_paid_deliv_orders_oblig,award_unique_key,award_id_piid,"
    "parent_award_id_piid,award_id_fain,award_id_uri,award_base_action_date,award_base_action_date_fiscal_year,"
    "award_latest_action_date,award_latest_action_date_fiscal_year,period_of_performance_start_date,"
    "period_of_performance_current_end_date,ordering_period_end_date,award_type_code,award_type,idv_type_code,"
    "idv_type,prime_award_base_transaction_description,awarding_agency_code,awarding_agency_name,"
    "awarding_subagency_code,awarding_subagency_name,awarding_office_code,awarding_office_name,funding_agency_code,"
    "funding_agency_name,funding_sub_agency_code,funding_sub_agency_name,funding_office_code,funding_office_name,"
    "recipient_uei,recipient_duns,recipient_name,recipient_name_raw,recipient_parent_uei,recipient_parent_duns,"
    "recipient_parent_name,recipient_parent_name_raw,recipient_country,recipient_state,recipient_county,"
    "recipient_city,prime_award_summary_recipient_cd_original,prime_award_summary_recipient_cd_current,"
    "recipient_zip_code,primary_place_of_performance_country,primary_place_of_performance_state,"
    "primary_place_of_performance_county,prime_award_summary_place_of_performance_cd_original,"
    "prime_award_summary_place_of_performance_cd_current,primary_place_of_performance_zip_code,cfda_number,"
    "cfda_title,product_or_service_code,product_or_service_code_description,naics_code,naics_description,"
    "national_interest_action_code,national_interest_action,usaspending_permalink,last_modified_date"
).split(",")
AWARD_COLUMNS = ["Grant or Contract", *SOURCE_COLUMNS, "Emergency"]

ANNUAL_COLUMNS = [
    "fiscal_year", "grant_or_contract", "emergency", "federal_account_symbol", "federal_account_name",
    "row_count", "numeric_obligation_rows", "transaction_obligated_amount", "gross_outlay_amount_FYB_to_period_end",
]
MONTHLY_COLUMNS = [
    "fiscal_year", "submission_period", "fiscal_quarter", "period_label", "grant_or_contract", "emergency",
    "federal_account_symbol", "federal_account_name", "row_count", "numeric_obligation_rows",
    "transaction_obligated_amount", "numeric_outlay_rows", "gross_outlay_amount_FYB_to_period_end",
]
QUARTERLY_COLUMNS = [
    "fiscal_year", "fiscal_quarter", "grant_or_contract", "emergency", "federal_account_symbol",
    "federal_account_name", "row_count", "numeric_obligation_rows", "transaction_obligated_amount",
    "numeric_outlay_rows", "gross_outlay_amount_FYB_to_period_end",
]
CATEGORY_MONTHLY_COLUMNS = [
    "fiscal_year", "submission_period", "fiscal_quarter", "period_label", "category", "row_count",
    "numeric_obligation_rows", "transaction_obligated_amount", "numeric_outlay_rows",
    "gross_outlay_amount_FYB_to_period_end",
]
CATEGORY_QUARTERLY_COLUMNS = [
    "fiscal_year", "fiscal_quarter", "category", "row_count", "numeric_obligation_rows",
    "transaction_obligated_amount", "numeric_outlay_rows", "gross_outlay_amount_FYB_to_period_end",
]
CATEGORY_SUMMARY_COLUMNS = [
    "fiscal_year", "data_status", "as_of_period", "category", "mapping_status", "mapped_account_rows",
    "usaspending_obligations", "usaspending_outlays", "methodology_note",
]
MAPPING_COLUMNS = [
    "fiscal_year", "category", "mapping_status", "grant_or_contract", "emergency", "federal_account_symbol",
    "expected_account_name", "actual_account_name", "account_name_match", "transaction_obligated_amount", "notes",
]
UNMAPPED_COLUMNS = [
    "fiscal_year", "grant_or_contract", "emergency", "federal_account_symbol", "federal_account_name",
    "row_count", "numeric_obligation_rows", "transaction_obligated_amount", "gross_outlay_amount_FYB_to_period_end",
    "reason",
]

MONTH_NAMES = {
    1: "October", 2: "November", 3: "December", 4: "January", 5: "February", 6: "March",
    7: "April", 8: "May", 9: "June", 10: "July", 11: "August", 12: "September",
}


def period_number(submission_period: str) -> int:
    return int(submission_period.rsplit("P", 1)[1])


def quarter_for(number: int) -> str:
    return f"Q{(number - 1) // 3 + 1}"


def period_label(number: int) -> str:
    if number == 2:
        return "October-November (combined P01/P02 submission)"
    return MONTH_NAMES[number]


def money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return str(value.quantize(CENT))


def parse_amount(text: str) -> Decimal | None:
    text = text.strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:  # pragma: no cover - source contract violation
        raise SystemExit(f"Non-numeric amount {text!r}") from exc


def emergency_for(def_name: str) -> str:
    name = def_name.strip()
    return "NonEmergency" if not name or "nonemergency" in name.lower() else "Emergency"


@dataclass
class Totals:
    row_count: int = 0
    numeric_obligation_rows: int = 0
    obligations: Decimal = ZERO
    numeric_outlay_rows: int = 0
    outlays: Decimal = ZERO

    def add(self, obligation: Decimal | None, outlay: Decimal | None) -> None:
        self.row_count += 1
        if obligation is not None:
            self.numeric_obligation_rows += 1
            self.obligations += obligation
        if outlay is not None:
            self.numeric_outlay_rows += 1
            self.outlays += outlay

    def merge(self, other: "Totals") -> None:
        self.row_count += other.row_count
        self.numeric_obligation_rows += other.numeric_obligation_rows
        self.obligations += other.obligations
        self.numeric_outlay_rows += other.numeric_outlay_rows
        self.outlays += other.outlays


@dataclass
class SourceStats:
    file: str
    source_type: str
    rows_scanned: int = 0
    rows_retained: int = 0
    repeated_header_rows_skipped: int = 0
    blank_obligation_rows: int = 0
    numeric_obligation_rows: int = 0
    obligation_total: Decimal = ZERO
    cdc_rows_outside_account_prefix: int = 0
    cdc_obligations_outside_account_prefix: Decimal = ZERO
    cdc_rows_after_max_period: int = 0


@dataclass
class Aggregates:
    names: dict = field(default_factory=dict)  # (gc, em, sym) -> account name
    first_seen: dict = field(default_factory=dict)  # (gc, em, sym) -> order
    annual: dict = field(default_factory=dict)  # key -> Totals
    monthly: dict = field(default_factory=dict)  # (period, key) -> Totals
    quarterly: dict = field(default_factory=dict)  # (quarter, key) -> Totals
    periods: set = field(default_factory=set)
    def_counts: Counter = field(default_factory=Counter)
    by_emergency_source: dict = field(default_factory=dict)
    name_conflicts: set = field(default_factory=set)


def scan_sources(
    sources: list[tuple[Path, str]],
    awards_path: Path,
    fiscal_year: int,
    account_prefix: str,
    max_period: int | None,
) -> tuple[list[SourceStats], Aggregates]:
    agg = Aggregates()
    stats_list: list[SourceStats] = []
    idx = {name: i for i, name in enumerate(SOURCE_COLUMNS)}
    i_sub = idx["awarding_subagency_name"]
    i_sym = idx["federal_account_symbol"]
    i_name = idx["federal_account_name"]
    i_period = idx["submission_period"]
    i_def = idx["disaster_emergency_fund_name"]
    i_obl = idx["transaction_obligated_amount"]
    i_out = idx["gross_outlay_amount_FYB_to_period_end"]
    expected_prefix = f"FY{fiscal_year}P"

    with awards_path.open("w", encoding="utf-8-sig", newline="") as out_handle:
        writer = csv.writer(out_handle, lineterminator="\n")
        writer.writerow(AWARD_COLUMNS)
        for path, source_type in sources:
            stats = SourceStats(file=path.name, source_type=source_type)
            stats_list.append(stats)
            started = time.monotonic()
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                header = next(reader)
                if header != SOURCE_COLUMNS:
                    missing = [c for c in SOURCE_COLUMNS if c not in header]
                    extra = [c for c in header if c not in SOURCE_COLUMNS]
                    raise SystemExit(f"{path.name}: header differs from contract; missing={missing} extra={extra}")
                for row in reader:
                    if row == header:
                        stats.repeated_header_rows_skipped += 1
                        continue
                    stats.rows_scanned += 1
                    if len(row) != len(SOURCE_COLUMNS):
                        raise SystemExit(f"{path.name}: row {stats.rows_scanned} has {len(row)} columns")
                    if row[i_sub].strip().upper() != CDC_SUBAGENCY:
                        continue
                    obligation = parse_amount(row[i_obl])
                    symbol = row[i_sym]
                    if not symbol.startswith(account_prefix):
                        stats.cdc_rows_outside_account_prefix += 1
                        if obligation is not None:
                            stats.cdc_obligations_outside_account_prefix += obligation
                        continue
                    submission_period = row[i_period]
                    if not submission_period.startswith(expected_prefix):
                        raise SystemExit(f"{path.name}: unexpected submission_period {submission_period!r}")
                    number = period_number(submission_period)
                    if max_period is not None and number > max_period:
                        stats.cdc_rows_after_max_period += 1
                        continue
                    outlay = parse_amount(row[i_out])
                    emergency = emergency_for(row[i_def])
                    writer.writerow([source_type, *row, emergency])

                    stats.rows_retained += 1
                    if obligation is None:
                        stats.blank_obligation_rows += 1
                    else:
                        stats.numeric_obligation_rows += 1
                        stats.obligation_total += obligation

                    key = (source_type, emergency, symbol)
                    name = row[i_name]
                    if key not in agg.annual:
                        agg.annual[key] = Totals()
                        agg.names[key] = name
                        agg.first_seen[key] = len(agg.first_seen)
                    elif agg.names[key] != name:
                        agg.name_conflicts.add((key, name))
                    agg.annual[key].add(obligation, outlay)
                    agg.monthly.setdefault((submission_period, key), Totals()).add(obligation, outlay)
                    agg.quarterly.setdefault((quarter_for(number), key), Totals()).add(obligation, outlay)
                    agg.periods.add(submission_period)
                    agg.def_counts[(emergency, row[i_def])] += 1
                    pair = (emergency, source_type)
                    entry = agg.by_emergency_source.setdefault(pair, [0, ZERO])
                    entry[0] += 1
                    if obligation is not None:
                        entry[1] += obligation
            print(
                f"  {path.name}: scanned {stats.rows_scanned:,}, retained {stats.rows_retained:,} "
                f"({time.monotonic() - started:.0f}s)",
                file=sys.stderr,
            )
    if agg.name_conflicts:
        raise SystemExit(f"Account names differ within a key: {sorted(agg.name_conflicts)[:5]}")
    return stats_list, agg


def read_crosswalk(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {"category", "mapping_status", "grant_or_contract", "emergency", "federal_account_symbol",
                "expected_account_name", "notes"}
    if not rows or not required.issubset(rows[0]):
        raise SystemExit(f"{path}: crosswalk needs columns {sorted(required)}")
    return rows


def write_csv(path: Path, columns: list[str], rows: list[list]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def dsum(rows: list[dict], column: str) -> Decimal:
    return sum((Decimal(r[column]) for r in rows if r[column] != ""), ZERO)


class Checks:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, path: str, expected, actual, tolerance: Decimal | None = None) -> None:
        if tolerance is not None:
            expected_d, actual_d = Decimal(str(expected)), Decimal(str(actual))
            difference = (actual_d - expected_d).quantize(CENT)
            passed = abs(difference) <= tolerance
            self.items.append({"path": path, "expected": money(expected_d), "actual": money(actual_d),
                               "tolerance": money(tolerance), "difference": money(difference), "passed": passed})
        else:
            self.items.append({"path": path, "expected": expected, "actual": actual, "tolerance": None,
                               "difference": None, "passed": expected == actual})

    def payload(self, reference_name: str) -> dict:
        return {"reference_name": reference_name, "passed": all(c["passed"] for c in self.items),
                "checks": self.items}


def build(args: argparse.Namespace) -> int:
    started = time.monotonic()
    fy = args.fiscal_year
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()) and not args.overwrite:
        raise SystemExit(f"{out} is not empty; pass --overwrite to replace its files")
    crosswalk = read_crosswalk(args.crosswalk)

    sources = [(p.resolve(), "Grant") for p in args.assistance] + [(p.resolve(), "Contract") for p in args.contracts]
    p = lambda name: out / f"FY{fy}_{name}"  # noqa: E731
    awards_path = p("CDC_awards_clean.csv")
    print(f"Scanning {len(sources)} source files", file=sys.stderr)
    stats_list, agg = scan_sources(sources, awards_path, fy, args.account_prefix, args.max_period)

    periods = sorted(agg.periods, key=period_number)
    last_number = period_number(periods[-1])
    as_of_period = f"FY{fy}P{last_number:02d}"
    data_status = (
        "Full fiscal year" if last_number == 12
        else f"Partial fiscal year through {MONTH_NAMES[last_number]} (P{last_number:02d})"
    )

    def key_order(key):
        return (key[0], key[1], agg.first_seen[key])

    keys = sorted(agg.annual, key=key_order)
    name = agg.names

    # Account summaries.
    annual_rows = [[fy, *k, name[k], t.row_count, t.numeric_obligation_rows, money(t.obligations), money(t.outlays)]
                   for k in keys for t in [agg.annual[k]]]
    monthly_rows = []
    for sp in periods:
        n = period_number(sp)
        for k in keys:
            t = agg.monthly.get((sp, k))
            if t:
                monthly_rows.append([fy, sp, quarter_for(n), period_label(n), *k, name[k], t.row_count,
                                     t.numeric_obligation_rows, money(t.obligations), t.numeric_outlay_rows,
                                     money(t.outlays)])
    quarters = sorted({quarter_for(period_number(sp)) for sp in periods})
    quarterly_rows = []
    for q in quarters:
        for k in sorted(keys, key=lambda k: (k[0], k[1], k[2])):
            t = agg.quarterly.get((q, k))
            if t:
                quarterly_rows.append([fy, q, *k, name[k], t.row_count, t.numeric_obligation_rows,
                                       money(t.obligations), t.numeric_outlay_rows, money(t.outlays)])
    write_csv(p("CDC_account_summary.csv"), ANNUAL_COLUMNS, annual_rows)
    write_csv(p("CDC_monthly_account_summary.csv"), MONTHLY_COLUMNS, monthly_rows)
    write_csv(p("CDC_quarterly_account_summary.csv"), QUARTERLY_COLUMNS, quarterly_rows)

    # Category crosswalk.
    categories: OrderedDict[str, list[dict]] = OrderedDict()
    for row in crosswalk:
        categories.setdefault(row["category"], []).append(row)
    mapped_keys: dict[tuple, str] = {}
    mapping_rows, mismatches, matched = [], 0, 0
    for row in crosswalk:
        if row["mapping_status"] != "Mapped":
            mapping_rows.append([fy, row["category"], row["mapping_status"], "", "", "", "", "", "", "", row["notes"]])
            continue
        key = (row["grant_or_contract"], row["emergency"], row["federal_account_symbol"])
        if key in mapped_keys:
            raise SystemExit(f"Crosswalk maps {key} to both {mapped_keys[key]!r} and {row['category']!r}")
        mapped_keys[key] = row["category"]
        actual = name.get(key, "")
        match = actual == row["expected_account_name"]
        mismatches += 0 if match else 1
        matched += 1 if key in agg.annual else 0
        amount = money(agg.annual[key].obligations) if key in agg.annual else ""
        mapping_rows.append([fy, row["category"], "Mapped", *key, row["expected_account_name"], actual,
                             str(match), amount, row["notes"]])
    write_csv(p("category_mapping_detail.csv"), MAPPING_COLUMNS, mapping_rows)

    def category_keys(category: str) -> list[tuple]:
        return [(r["grant_or_contract"], r["emergency"], r["federal_account_symbol"])
                for r in categories[category] if r["mapping_status"] == "Mapped"]

    summary_rows, mapped_obl, mapped_out, mapped_categories = [], ZERO, ZERO, 0
    for category, rows in categories.items():
        ckeys = [k for k in category_keys(category) if k in agg.annual]
        note = " | ".join(r["notes"] for r in rows)
        if not category_keys(category):
            summary_rows.append([fy, data_status, as_of_period, category, "No match", 0, "", "", note])
            continue
        mapped_categories += 1
        obl = sum((agg.annual[k].obligations for k in ckeys), ZERO)
        outl = sum((agg.annual[k].outlays for k in ckeys), ZERO)
        mapped_obl += obl
        mapped_out += outl
        summary_rows.append([fy, data_status, as_of_period, category, "Mapped", len(ckeys), money(obl), money(outl),
                             note])
    write_csv(p("category_summary.csv"), CATEGORY_SUMMARY_COLUMNS, summary_rows)

    unmapped_keys = [k for k in keys if k not in mapped_keys]
    unmapped_rows = [[fy, *k, name[k], t.row_count, t.numeric_obligation_rows, money(t.obligations),
                      money(t.outlays), UNMAPPED_REASON] for k in unmapped_keys for t in [agg.annual[k]]]
    write_csv(p("category_unmapped_accounts.csv"), UNMAPPED_COLUMNS, unmapped_rows)

    cat_monthly_rows, cat_quarterly_rows = [], []
    for sp in periods:
        n = period_number(sp)
        for category in categories:
            parts = [agg.monthly[(sp, k)] for k in category_keys(category) if (sp, k) in agg.monthly]
            if parts:
                t = Totals()
                for part in parts:
                    t.merge(part)
                cat_monthly_rows.append([fy, sp, quarter_for(n), period_label(n), category, t.row_count,
                                         t.numeric_obligation_rows, money(t.obligations), t.numeric_outlay_rows,
                                         money(t.outlays)])
    for q in quarters:
        for category in categories:
            parts = [agg.quarterly[(q, k)] for k in category_keys(category) if (q, k) in agg.quarterly]
            if parts:
                t = Totals()
                for part in parts:
                    t.merge(part)
                cat_quarterly_rows.append([fy, q, category, t.row_count, t.numeric_obligation_rows,
                                           money(t.obligations), t.numeric_outlay_rows, money(t.outlays)])
    write_csv(p("CFP_category_monthly.csv"), CATEGORY_MONTHLY_COLUMNS, cat_monthly_rows)
    write_csv(p("CFP_category_quarterly.csv"), CATEGORY_QUARTERLY_COLUMNS, cat_quarterly_rows)

    # Audit JSON files.
    annual_obl = sum((t.obligations for t in agg.annual.values()), ZERO)
    annual_out = sum((t.outlays for t in agg.annual.values()), ZERO)
    by_source = {}
    for source_type in ("Grant", "Contract"):
        group = [s for s in stats_list if s.source_type == source_type]
        by_source[source_type] = {
            "rows_retained": sum(s.rows_retained for s in group),
            "numeric_obligation_rows": sum(s.numeric_obligation_rows for s in group),
            "blank_obligation_rows": sum(s.blank_obligation_rows for s in group),
            "obligation_total": money(sum((s.obligation_total for s in group), ZERO)),
        }
    pipeline_audit = {
        "pipeline_version": PIPELINE_VERSION,
        "builder": "backend/scripts/build_cdc_funding_bundle.py",
        "fiscal_year": fy,
        "as_of_period": as_of_period,
        "input_directory": str(sources[0][0].parent),
        "output_directory": str(out),
        "awarding_subagency_filter": CDC_SUBAGENCY,
        "federal_account_prefix_filter": args.account_prefix,
        "max_period_filter": args.max_period,
        "methodology": {
            "assistance_classification": "Grant",
            "contracts_classification": "Contract",
            "unlinked_awards": "Excluded",
            "emergency_rule": "Blank/missing or containing 'nonemergency' is NonEmergency; all other values are Emergency.",
            "amount_field": "transaction_obligated_amount",
            "negative_amounts": "Retained",
            "account_scope": f"Only federal accounts whose symbol starts with {args.account_prefix!r} (HHS), "
                             "matching the earlier agency-075 downloads.",
        },
        "source_files": [
            {
                "file": s.file, "source_type": s.source_type, "rows_scanned": s.rows_scanned,
                "rows_retained": s.rows_retained, "repeated_header_rows_skipped": s.repeated_header_rows_skipped,
                "blank_obligation_rows": s.blank_obligation_rows,
                "numeric_obligation_rows": s.numeric_obligation_rows, "obligation_total": money(s.obligation_total),
                "cdc_rows_outside_account_prefix": s.cdc_rows_outside_account_prefix,
                "cdc_obligations_outside_account_prefix": money(s.cdc_obligations_outside_account_prefix),
                "cdc_rows_after_max_period": s.cdc_rows_after_max_period,
            }
            for s in stats_list
        ],
        "combined": {
            "rows_retained": sum(s.rows_retained for s in stats_list),
            "obligation_total": money(annual_obl),
            "by_source": by_source,
            "by_emergency_and_source": [
                {"emergency": em, "grant_or_contract": gc, "row_count": v[0], "obligation_total": money(v[1])}
                for (em, gc), v in sorted(agg.by_emergency_source.items())
            ],
        },
        "disaster_emergency_fund_counts": [
            {"emergency": em, "disaster_emergency_fund_name": dn, "row_count": c}
            for (em, dn), c in sorted(agg.def_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "outputs": {
            "clean_awards_csv": str(awards_path),
            "account_summary_csv": str(p("CDC_account_summary.csv")),
            "audit_json": str(p("pipeline_audit.json")),
        },
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    write_json(p("pipeline_audit.json"), pipeline_audit)

    category_audit = {
        "fiscal_year": fy,
        "data_status": data_status,
        "as_of_period": as_of_period,
        "reference_status": REFERENCE_STATUS,
        "crosswalk_basis": CROSSWALK_BASIS,
        "account_summary": str(p("CDC_account_summary.csv")),
        "mapping_file": str(args.crosswalk.resolve()),
        "mapping": {
            "mapping_rows": len(crosswalk),
            "mapped_keys": len(mapped_keys),
            "matched_summary_rows": matched,
            "unmapped_summary_rows": len(unmapped_keys),
            "account_name_mismatches": mismatches,
        },
        "categories": {"defined": len(categories), "mapped": mapped_categories,
                       "no_match": len(categories) - mapped_categories},
        "totals": {
            "mapped_usaspending_accounts": money(mapped_obl),
            "all_usaspending_summary": money(annual_obl),
            "unmapped_usaspending_accounts": money(annual_obl - mapped_obl),
            "mapping_reconciliation": money(mapped_obl + (annual_obl - mapped_obl) - annual_obl),
            "mapped_usaspending_outlays": money(mapped_out),
            "all_usaspending_summary_outlays": money(annual_out),
            "unmapped_usaspending_outlays": money(annual_out - mapped_out),
            "outlay_mapping_reconciliation": money(mapped_out + (annual_out - mapped_out) - annual_out),
        },
        "outputs": {
            "category_summary": str(p("category_summary.csv")),
            "mapping_detail": str(p("category_mapping_detail.csv")),
            "unmapped_accounts": str(p("category_unmapped_accounts.csv")),
            "audit": str(p("category_summary_audit.json")),
        },
    }
    write_json(p("category_summary_audit.json"), category_audit)

    def period_totals(groups: dict, label_for) -> list[dict]:
        result = []
        for unit in label_for:
            obl = sum((t.obligations for (u, _), t in groups.items() if u == unit), ZERO)
            outl = sum((t.outlays for (u, _), t in groups.items() if u == unit), ZERO)
            result.append((unit, obl, outl))
        return result

    monthly_totals = period_totals(agg.monthly, periods)
    quarterly_totals = period_totals(agg.quarterly, quarters)
    cm_obl = sum((Decimal(r[7]) for r in cat_monthly_rows), ZERO)
    cq_obl = sum((Decimal(r[5]) for r in cat_quarterly_rows), ZERO)
    cm_out = sum((Decimal(r[9]) for r in cat_monthly_rows), ZERO)
    cq_out = sum((Decimal(r[7]) for r in cat_quarterly_rows), ZERO)
    m_obl = sum((x[1] for x in monthly_totals), ZERO)
    q_obl = sum((x[1] for x in quarterly_totals), ZERO)
    m_out = sum((x[2] for x in monthly_totals), ZERO)
    q_out = sum((x[2] for x in quarterly_totals), ZERO)
    period_audit = {
        "fiscal_year": fy,
        "clean_awards": str(awards_path),
        "mapping": str(args.crosswalk.resolve()),
        "rows": sum(t.row_count for t in agg.annual.values()),
        "numeric_obligation_rows": sum(t.numeric_obligation_rows for t in agg.annual.values()),
        "numeric_outlay_rows": sum(t.numeric_outlay_rows for t in agg.annual.values()),
        "annual_obligation_total": money(annual_obl),
        "annual_outlay_total": money(annual_out),
        "mapped_category_obligation_total": money(mapped_obl),
        "mapped_category_outlay_total": money(mapped_out),
        "monthly_totals": [
            {"submission_period": sp, "fiscal_quarter": quarter_for(period_number(sp)),
             "period_label": period_label(period_number(sp)), "transaction_obligated_amount": money(o),
             "gross_outlay_amount_FYB_to_period_end": money(u)}
            for sp, o, u in monthly_totals
        ],
        "quarterly_totals": [
            {"fiscal_quarter": q, "transaction_obligated_amount": money(o),
             "gross_outlay_amount_FYB_to_period_end": money(u)}
            for q, o, u in quarterly_totals
        ],
        "reconciliation": {
            "monthly_minus_annual": money(m_obl - annual_obl),
            "quarterly_minus_annual": money(q_obl - annual_obl),
            "category_monthly_minus_category_quarterly": money(cm_obl - cq_obl),
            "monthly_obligations_minus_annual": money(m_obl - annual_obl),
            "quarterly_obligations_minus_annual": money(q_obl - annual_obl),
            "monthly_outlays_minus_annual": money(m_out - annual_out),
            "quarterly_outlays_minus_annual": money(q_out - annual_out),
            "category_monthly_obligations_minus_category_quarterly": money(cm_obl - cq_obl),
            "category_monthly_outlays_minus_category_quarterly": money(cm_out - cq_out),
        },
        "outputs": {
            "monthly_account_summary": str(p("CDC_monthly_account_summary.csv")),
            "quarterly_account_summary": str(p("CDC_quarterly_account_summary.csv")),
            "monthly_category_summary": str(p("CFP_category_monthly.csv")),
            "quarterly_category_summary": str(p("CFP_category_quarterly.csv")),
            "audit": str(p("period_summary_audit.json")),
        },
    }
    write_json(p("period_summary_audit.json"), period_audit)

    write_validations(out, fy, as_of_period, data_status, pipeline_audit, category_audit, period_audit,
                      mapped_keys, len(categories), mapped_categories)
    print(json.dumps({"output_directory": str(out), "as_of_period": as_of_period, "data_status": data_status,
                      "rows": period_audit["rows"], "annual_obligation_total": money(annual_obl),
                      "annual_outlay_total": money(annual_out),
                      "quarterly_obligations": {q: money(o) for q, o, _ in quarterly_totals},
                      "cdc_rows_outside_account_prefix": sum(s.cdc_rows_outside_account_prefix for s in stats_list),
                      "elapsed_seconds": round(time.monotonic() - started, 1)}, indent=2))
    return 0


def write_validations(out: Path, fy: int, as_of_period: str, data_status: str, pipeline_audit: dict,
                      category_audit: dict, period_audit: dict, mapped_keys: dict, defined: int,
                      mapped_categories: int) -> None:
    """Recompute controls by re-reading the written CSVs; compare with the audit figures."""
    p = lambda name: out / f"FY{fy}_{name}"  # noqa: E731
    tol = CENT
    label = f"FY{fy} {as_of_period.removeprefix(f'FY{fy}')} USAspending"

    # 1. Source baseline: re-read the clean award file.
    rows = Counter()
    obl = {}
    by_pair = {}
    with p("CDC_awards_clean.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        for r in csv.DictReader(handle):
            gc, em = r["Grant or Contract"], r["Emergency"]
            rows[gc] += 1
            amount = Decimal(r["transaction_obligated_amount"]) if r["transaction_obligated_amount"] else ZERO
            obl[gc] = obl.get(gc, ZERO) + amount
            pair = by_pair.setdefault((em, gc), [0, ZERO])
            pair[0] += 1
            pair[1] += amount
    combined = pipeline_audit["combined"]
    c = Checks()
    for i, s in enumerate(pipeline_audit["source_files"]):
        c.add(f"source_files.{i}.file", s["file"], s["file"])
    c.add("combined.rows_retained", combined["rows_retained"], sum(rows.values()))
    for gc in ("Grant", "Contract"):
        c.add(f"combined.by_source.{gc}.rows_retained", combined["by_source"][gc]["rows_retained"], rows[gc])
    for gc in ("Grant", "Contract"):
        c.add(f"combined.by_source.{gc}.obligation_total", combined["by_source"][gc]["obligation_total"],
              obl.get(gc, ZERO), tol)
    c.add("combined.obligation_total", combined["obligation_total"], sum(obl.values(), ZERO), tol)
    for i, item in enumerate(combined["by_emergency_and_source"]):
        actual = by_pair.get((item["emergency"], item["grant_or_contract"]), [0, ZERO])
        c.add(f"combined.by_emergency_and_source.{i}.row_count", item["row_count"], actual[0])
        c.add(f"combined.by_emergency_and_source.{i}.obligation_total", item["obligation_total"], actual[1], tol)
    write_json(p("reference_validation.json"), c.payload(f"{label} source baseline (re-read of clean awards)"))

    # 2. Category crosswalk: re-read summary, mapping, and unmapped files.
    annual = read_rows(p("CDC_account_summary.csv"))
    mapping = read_rows(p("category_mapping_detail.csv"))
    summary = read_rows(p("category_summary.csv"))
    unmapped = read_rows(p("category_unmapped_accounts.csv"))
    annual_keys = {(r["grant_or_contract"], r["emergency"], r["federal_account_symbol"]) for r in annual}
    mapped_rows = [r for r in mapping if r["mapping_status"] == "Mapped"]
    m = category_audit["mapping"]
    t = category_audit["totals"]
    c = Checks()
    c.add("data_status", data_status, {r["data_status"] for r in summary} == {data_status} and data_status)
    c.add("as_of_period", as_of_period, {r["as_of_period"] for r in summary} == {as_of_period} and as_of_period)
    c.add("mapping.mapping_rows", m["mapping_rows"], len(mapping))
    c.add("mapping.mapped_keys", m["mapped_keys"], len(mapped_rows))
    c.add("mapping.matched_summary_rows", m["matched_summary_rows"],
          sum(1 for r in mapped_rows if (r["grant_or_contract"], r["emergency"], r["federal_account_symbol"])
              in annual_keys))
    c.add("mapping.unmapped_summary_rows", m["unmapped_summary_rows"], len(unmapped))
    c.add("mapping.unmapped_plus_matched_equals_summary", len(annual),
          len(unmapped) + m["matched_summary_rows"])
    c.add("mapping.account_name_mismatches", m["account_name_mismatches"],
          sum(1 for r in mapped_rows if r["account_name_match"] != "True"))
    c.add("categories.defined", defined, len(summary))
    c.add("categories.mapped", mapped_categories, sum(1 for r in summary if r["mapping_status"] == "Mapped"))
    c.add("categories.no_match", defined - mapped_categories,
          sum(1 for r in summary if r["mapping_status"] != "Mapped"))
    c.add("totals.mapped_usaspending_accounts", t["mapped_usaspending_accounts"], dsum(summary, "usaspending_obligations"), tol)
    c.add("totals.mapping_detail_equals_category_summary", t["mapped_usaspending_accounts"],
          dsum(mapped_rows, "transaction_obligated_amount"), tol)
    c.add("totals.all_usaspending_summary", t["all_usaspending_summary"], dsum(annual, "transaction_obligated_amount"), tol)
    c.add("totals.unmapped_usaspending_accounts", t["unmapped_usaspending_accounts"],
          dsum(unmapped, "transaction_obligated_amount"), tol)
    c.add("totals.mapping_reconciliation", "0.00",
          dsum(summary, "usaspending_obligations") + dsum(unmapped, "transaction_obligated_amount")
          - dsum(annual, "transaction_obligated_amount"), tol)
    c.add("totals.mapped_usaspending_outlays", t["mapped_usaspending_outlays"], dsum(summary, "usaspending_outlays"), tol)
    c.add("totals.all_usaspending_summary_outlays", t["all_usaspending_summary_outlays"],
          dsum(annual, "gross_outlay_amount_FYB_to_period_end"), tol)
    c.add("totals.unmapped_usaspending_outlays", t["unmapped_usaspending_outlays"],
          dsum(unmapped, "gross_outlay_amount_FYB_to_period_end"), tol)
    c.add("totals.outlay_mapping_reconciliation", "0.00",
          dsum(summary, "usaspending_outlays") + dsum(unmapped, "gross_outlay_amount_FYB_to_period_end")
          - dsum(annual, "gross_outlay_amount_FYB_to_period_end"), tol)
    write_json(p("category_reference_validation.json"), c.payload(f"{label} forward category-crosswalk baseline"))

    # 3. Period summaries: re-read monthly and quarterly files.
    monthly = read_rows(p("CDC_monthly_account_summary.csv"))
    quarterly = read_rows(p("CDC_quarterly_account_summary.csv"))
    cat_m = read_rows(p("CFP_category_monthly.csv"))
    cat_q = read_rows(p("CFP_category_quarterly.csv"))
    a = period_audit
    c = Checks()
    c.add("rows", a["rows"], sum(int(r["row_count"]) for r in annual))
    c.add("numeric_obligation_rows", a["numeric_obligation_rows"], sum(int(r["numeric_obligation_rows"]) for r in annual))
    c.add("annual_obligation_total", a["annual_obligation_total"], dsum(annual, "transaction_obligated_amount"), tol)
    c.add("mapped_category_obligation_total", a["mapped_category_obligation_total"],
          dsum(summary, "usaspending_obligations"), tol)
    c.add("annual_outlay_total", a["annual_outlay_total"], dsum(annual, "gross_outlay_amount_FYB_to_period_end"), tol)
    c.add("mapped_category_outlay_total", a["mapped_category_outlay_total"], dsum(summary, "usaspending_outlays"), tol)
    for i, qt in enumerate(a["quarterly_totals"]):
        rows_q = [r for r in quarterly if r["fiscal_quarter"] == qt["fiscal_quarter"]]
        rows_m = [r for r in monthly if r["fiscal_quarter"] == qt["fiscal_quarter"]]
        c.add(f"quarterly_totals.{i}.transaction_obligated_amount", qt["transaction_obligated_amount"],
              dsum(rows_q, "transaction_obligated_amount"), tol)
        c.add(f"quarterly_totals.{i}.monthly_rollup", qt["transaction_obligated_amount"],
              dsum(rows_m, "transaction_obligated_amount"), tol)
    annual_obl = dsum(annual, "transaction_obligated_amount")
    annual_out = dsum(annual, "gross_outlay_amount_FYB_to_period_end")
    c.add("reconciliation.monthly_obligations_minus_annual", "0.00",
          dsum(monthly, "transaction_obligated_amount") - annual_obl, tol)
    c.add("reconciliation.quarterly_obligations_minus_annual", "0.00",
          dsum(quarterly, "transaction_obligated_amount") - annual_obl, tol)
    c.add("reconciliation.monthly_outlays_minus_annual", "0.00",
          dsum(monthly, "gross_outlay_amount_FYB_to_period_end") - annual_out, tol)
    c.add("reconciliation.quarterly_outlays_minus_annual", "0.00",
          dsum(quarterly, "gross_outlay_amount_FYB_to_period_end") - annual_out, tol)
    c.add("reconciliation.category_monthly_obligations_minus_category_quarterly", "0.00",
          dsum(cat_m, "transaction_obligated_amount") - dsum(cat_q, "transaction_obligated_amount"), tol)
    c.add("reconciliation.category_monthly_outlays_minus_category_quarterly", "0.00",
          dsum(cat_m, "gross_outlay_amount_FYB_to_period_end") - dsum(cat_q, "gross_outlay_amount_FYB_to_period_end"), tol)
    c.add("reconciliation.category_quarterly_obligations_minus_mapped", "0.00",
          dsum(cat_q, "transaction_obligated_amount") - dsum(summary, "usaspending_obligations"), tol)
    write_json(p("period_reference_validation.json"),
               c.payload(f"{label} monthly and quarterly period-summary baseline"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--fiscal-year", type=int, required=True)
    parser.add_argument("--assistance", type=Path, nargs="+", required=True,
                        help="Assistance_AccountBreakdownByAward CSV files (in order)")
    parser.add_argument("--contracts", type=Path, nargs="+", required=True,
                        help="Contracts_AccountBreakdownByAward CSV files (in order)")
    parser.add_argument("--crosswalk", type=Path, required=True,
                        help="Reviewed category crosswalk, e.g. the previous FY####_category_mapping_detail.csv")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--account-prefix", default=DEFAULT_ACCOUNT_PREFIX,
                        help="Keep only federal accounts with this symbol prefix (default 075-, HHS)")
    parser.add_argument("--max-period", type=int, default=None,
                        help="Drop submission periods after this number (for comparing with an earlier bundle)")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    for path in [*args.assistance, *args.contracts, args.crosswalk]:
        if not path.is_file():
            parser.error(f"not a file: {path}")
    return build(args)


if __name__ == "__main__":
    os.umask(0o002)
    raise SystemExit(main())
