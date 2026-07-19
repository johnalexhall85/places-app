#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import compare_usaspending_profiles_disaster_filters as single_year


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent

DEFAULT_USASPENDING_ROOT = REPO_ROOT / "data" / "usaspending" / "chipfunding"
DEFAULT_FUNDING_PROFILES_DIR = REPO_ROOT / "data"
DEFAULT_FISCAL_YEARS = tuple(range(2019, 2027))
DEFAULT_OUTPUT_PATH = (
    BACKEND_ROOT
    / "data_profiles"
    / "usaspending_profiles_disaster_filter_comparison_all_years.json"
)
DEFAULT_SUMMARY_CSV_PATH = (
    BACKEND_ROOT
    / "data_profiles"
    / "usaspending_profiles_disaster_filter_comparison_all_years_summary.csv"
)

GRANT_ASSISTANCE_TYPE_CODES = {"02", "03", "04", "05"}
PROFILE_YEAR_RE = re.compile(r"(?:FY\s*)?(20\d{2})", re.IGNORECASE)
PROFILE_STRONG_CATEGORY_SUBCATEGORY_PATTERNS = (
    "PHSSEF COVID-19 Activities",
    "American Rescue Plan Act",
    "Coronavirus Aid, Relief, and Economic Security Act",
    "Coronavirus Preparedness and Response Supplemental",
    "Hurricane Supplemental",
    "COVID",
    "CARES",
    "Supplemental",
)
PROFILE_ARP_RE = re.compile(r"\bARP\b", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare USAspending CDC-funded assistance transactions against CDC "
            "Funding Profiles across all available fiscal years."
        )
    )
    parser.add_argument("--usaspending-root", type=Path, default=DEFAULT_USASPENDING_ROOT)
    parser.add_argument("--funding-profiles-dir", type=Path, default=DEFAULT_FUNDING_PROFILES_DIR)
    parser.add_argument(
        "--fiscal-years",
        default=",".join(str(year) for year in DEFAULT_FISCAL_YEARS),
        help="Comma-separated fiscal years to process.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--summary-csv", type=Path, default=DEFAULT_SUMMARY_CSV_PATH)
    parser.add_argument(
        "--profile-file",
        action="append",
        default=[],
        metavar="FY=PATH",
        help="Explicit Funding Profiles CSV mapping, repeatable; e.g. 2020=/path/2020.csv",
    )
    return parser.parse_args()


def parse_fiscal_years(value: str) -> list[int]:
    years: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        years.append(int(part))
    return years


def parse_profile_file_mappings(values: list[str]) -> dict[int, Path]:
    mappings: dict[int, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"--profile-file must be FY=path, got: {value}")
        year_text, path_text = value.split("=", 1)
        year = int(year_text.strip().removeprefix("FY").removeprefix("fy"))
        mappings[year] = Path(path_text.strip()).expanduser().resolve()
    return mappings


def fiscal_year_from_profile_filename(path: Path) -> int | None:
    match = PROFILE_YEAR_RE.search(path.name)
    return int(match.group(1)) if match else None


def detect_funding_profile_files(
    funding_profiles_dir: Path,
    explicit_mappings: dict[int, Path],
) -> tuple[dict[int, Path], dict[str, Any]]:
    candidates: dict[int, list[Path]] = defaultdict(list)
    for path in sorted(funding_profiles_dir.glob("*.csv")):
        year = fiscal_year_from_profile_filename(path)
        if year is not None:
            candidates[year].append(path.resolve())

    detected: dict[int, Path] = {}
    ambiguous: dict[int, list[str]] = {}
    for year, paths in sorted(candidates.items()):
        if year in explicit_mappings:
            continue
        if len(paths) == 1:
            detected[year] = paths[0]
        else:
            ambiguous[year] = [str(path) for path in paths]

    detected.update(explicit_mappings)
    return detected, {
        "auto_candidates": {
            year: [str(path) for path in paths]
            for year, paths in sorted(candidates.items())
        },
        "explicit_mappings": {
            year: str(path)
            for year, path in sorted(explicit_mappings.items())
        },
        "ambiguous_auto_detected_years": ambiguous,
    }


def find_usaspending_assistance_prime_file(root: Path, fiscal_year: int) -> Path | None:
    fy_dir = root / f"fy{fiscal_year % 100:02d}"
    matches = sorted(fy_dir.glob("All_Assistance_PrimeTransactions*.csv"))
    return matches[0].resolve() if matches else None


def profile_emergency_reasons(category: str, subcategory: str) -> list[str]:
    category_norm = single_year.normalize_text(category)
    haystack = f"{category} {subcategory}"
    haystack_norm = single_year.normalize_text(haystack)
    reasons: list[str] = []

    if category_norm == single_year.normalize_text(single_year.PROFILE_EMERGENCY_CATEGORY):
        reasons.append("category_public_health_social_services_emergency_fund")

    for pattern in PROFILE_STRONG_CATEGORY_SUBCATEGORY_PATTERNS:
        if single_year.normalize_text(pattern) in haystack_norm:
            reasons.append(f"category_or_subcategory_contains_{re.sub(r'[^a-z0-9]+', '_', pattern.lower()).strip('_')}")

    if PROFILE_ARP_RE.search(haystack):
        reasons.append("category_or_subcategory_contains_arp")

    return sorted(set(reasons))


def funding_profiles_summary(path: Path, fiscal_year: int) -> dict[str, Any]:
    total = Decimal("0")
    vfc_total = Decimal("0")
    obvious_emergency_total = Decimal("0")
    non_vfc_non_obvious_emergency_total = Decimal("0")
    category_totals: dict[str, Decimal] = defaultdict(Decimal)
    category_subcategory_totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    emergency_reason_totals: dict[str, Decimal] = defaultdict(Decimal)
    row_count = 0
    included_row_count = 0

    for row in single_year.csv_rows(path):
        row_count += 1
        row_fiscal_year = single_year.clean_text(row.get("Fiscal Year"))
        if row_fiscal_year and row_fiscal_year != str(fiscal_year):
            continue

        included_row_count += 1
        amount = single_year.money(row.get("Amount"))
        category = single_year.clean_text(row.get("Category")) or "(blank)"
        subcategory = single_year.clean_text(row.get("Sub-Category")) or "(blank)"
        is_vfc = single_year.is_profile_vfc(category)
        emergency_reasons = profile_emergency_reasons(category, subcategory)
        is_obvious_emergency = bool(emergency_reasons)

        total += amount
        category_totals[category] += amount
        category_subcategory_totals[(category, subcategory)] += amount
        if is_vfc:
            vfc_total += amount
        if is_obvious_emergency:
            obvious_emergency_total += amount
            for reason in emergency_reasons:
                emergency_reason_totals[reason] += amount
        if not is_vfc and not is_obvious_emergency:
            non_vfc_non_obvious_emergency_total += amount

    targets = {
        "funding_profiles_total": total,
        "funding_profiles_minus_vfc": total - vfc_total,
        "funding_profiles_minus_obvious_emergency_supplemental": total - obvious_emergency_total,
        "funding_profiles_minus_vfc_minus_obvious_emergency_supplemental": (
            non_vfc_non_obvious_emergency_total
        ),
    }

    return {
        "input_path": path,
        "fiscal_year": fiscal_year,
        "source_row_count": row_count,
        "included_row_count": included_row_count,
        "total_amount": total,
        "vfc_total": vfc_total,
        "obvious_emergency_supplemental_total": obvious_emergency_total,
        "non_vfc_non_obvious_emergency_supplemental_total": non_vfc_non_obvious_emergency_total,
        "targets": targets,
        "total_by_category": [
            {"category": category, "amount": amount}
            for category, amount in sorted(
                category_totals.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        ],
        "total_by_category_subcategory": [
            {"category": category, "subcategory": subcategory, "amount": amount}
            for (category, subcategory), amount in sorted(
                category_subcategory_totals.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        ],
        "obvious_emergency_supplemental_reason_totals": [
            {"reason": reason, "amount": amount}
            for reason, amount in sorted(
                emergency_reason_totals.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        ],
        "emergency_exception": {
            "not_excluded_by_emergency_word_alone": single_year.PROFILE_PHEP_REGULAR_SUBCATEGORY,
        },
    }


def has_us_state_signal(row: dict[str, str]) -> bool:
    fields = (
        "prime_award_transaction_place_of_performance_state_fips_code",
        "primary_place_of_performance_state_code",
        "primary_place_of_performance_state_name",
        "prime_award_transaction_recipient_state_fips_code",
        "recipient_state_code",
        "recipient_state_name",
    )
    return any(single_year.clean_text(row.get(field)) for field in fields)


def is_foreign_or_global_unmapped(row: dict[str, str], state_identifiable: bool) -> bool:
    if state_identifiable:
        return False
    country_values = [
        single_year.clean_text(row.get("primary_place_of_performance_country_code")).upper(),
        single_year.clean_text(row.get("primary_place_of_performance_country_name")).casefold(),
        single_year.clean_text(row.get("recipient_country_code")).upper(),
        single_year.clean_text(row.get("recipient_country_name")).casefold(),
    ]
    country_blob = " ".join(country_values)
    if any(value and value not in {"USA", "US", "UNITED STATES", "UNITED STATES OF AMERICA"} for value in country_values):
        return True
    if any(term in country_blob for term in ("foreign", "world", "global", "international")):
        return True

    description_blob = " ".join(
        single_year.clean_text(row.get(field)).casefold()
        for field in (
            "transaction_description",
            "prime_award_base_transaction_description",
            "primary_place_of_performance_foreign_location",
        )
    )
    return any(term in description_blob for term in ("global", "world health", "international", "foreign"))


def is_grants_or_cooperative_assistance(row: dict[str, str]) -> bool:
    code = single_year.clean_text(row.get("assistance_type_code"))
    return not code or code in GRANT_ASSISTANCE_TYPE_CODES


def is_cdc_funded_positive_grant_fy(row: dict[str, str], fiscal_year: int) -> bool:
    return single_year.is_cdc_funded_positive_fy(row, fiscal_year) and is_grants_or_cooperative_assistance(row)


def make_record(row: dict[str, str]) -> dict[str, Any]:
    record = single_year.make_usaspending_record(row)
    state_identifiable = has_us_state_signal(row)
    has_supplemental_history = (
        record["has_defc_non_q"]
        or record["scenario_exclusion_flags"]["B_current_overall_award_covid_iija_amount"]
    )
    record.update(
        {
            "state_identifiable": state_identifiable,
            "foreign_global_unmapped": is_foreign_or_global_unmapped(row, state_identifiable),
            "has_supplemental_or_defc_history": has_supplemental_history,
        }
    )
    return record


def read_year_records(path: Path, fiscal_year: int) -> dict[str, Any]:
    source_row_count = 0
    included_records: list[dict[str, Any]] = []

    for row in single_year.csv_rows(path):
        source_row_count += 1
        if is_cdc_funded_positive_grant_fy(row, fiscal_year):
            included_records.append(make_record(row))

    return {
        "input_path": path,
        "source_row_count": source_row_count,
        "included_row_count": len(included_records),
        "records": included_records,
    }


def add_record(metrics: dict[str, Any], record: dict[str, Any]) -> None:
    amount = record["amount"]
    metrics["total_obligations"] += amount
    metrics["transaction_count"] += 1
    if record.get("award_key"):
        metrics["award_keys"].add(record["award_key"])
    if record.get("recipient_key"):
        metrics["recipient_keys"].add(record["recipient_key"])
    if record["is_likely_vfc"]:
        metrics["vfc_amount"] += amount
    else:
        metrics["non_vfc_total_obligations"] += amount
    if record["state_identifiable"]:
        metrics["state_identifiable_total"] += amount
    else:
        metrics["state_unmapped_total"] += amount
    if record["foreign_global_unmapped"]:
        metrics["foreign_global_unmapped_total"] += amount
    if record["has_supplemental_or_defc_history"]:
        metrics["amount_from_awards_with_supplemental_defc_history"] += amount
    else:
        metrics["amount_from_awards_without_supplemental_defc_history"] += amount


def empty_metrics() -> dict[str, Any]:
    return {
        "total_obligations": Decimal("0"),
        "non_vfc_total_obligations": Decimal("0"),
        "vfc_amount": Decimal("0"),
        "transaction_count": 0,
        "award_keys": set(),
        "recipient_keys": set(),
        "state_identifiable_total": Decimal("0"),
        "state_unmapped_total": Decimal("0"),
        "foreign_global_unmapped_total": Decimal("0"),
        "amount_from_awards_with_supplemental_defc_history": Decimal("0"),
        "amount_from_awards_without_supplemental_defc_history": Decimal("0"),
    }


def finalize_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    finalized = dict(metrics)
    finalized["award_count"] = len(metrics["award_keys"])
    finalized["recipient_count"] = len(metrics["recipient_keys"])
    del finalized["award_keys"]
    del finalized["recipient_keys"]
    return finalized


def metrics_for_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    metrics = empty_metrics()
    for record in records:
        add_record(metrics, record)
    return finalize_metrics(metrics)


def included_records_for_scenario(
    records: list[dict[str, Any]],
    scenario_definition: dict[str, str | None],
) -> list[dict[str, Any]]:
    flag = scenario_definition["flag"]
    if flag is None:
        return list(records)
    return [
        record
        for record in records
        if not record["scenario_exclusion_flags"].get(flag, False)
    ]


def scenario_summaries(
    records: list[dict[str, Any]],
    funding_profile_targets: dict[str, Decimal] | None,
) -> dict[str, Any]:
    scenarios: dict[str, Any] = {}
    baseline_total = metrics_for_records(records)["total_obligations"]

    for scenario_key, definition in single_year.scenario_definitions().items():
        included = included_records_for_scenario(records, definition)
        metrics = metrics_for_records(included)
        scenario = {
            "label": definition["label"],
            "exclusion_flag": definition["flag"],
            **metrics,
            "removed_from_no_exclusion_baseline": baseline_total - metrics["total_obligations"],
        }
        if funding_profile_targets is not None:
            scenario["target_comparisons"] = {
                target_key: {
                    **single_year.compare_to_target(metrics["total_obligations"], target),
                    "absolute_difference": abs(metrics["total_obligations"] - target),
                }
                for target_key, target in funding_profile_targets.items()
            }
            scenario["non_vfc_target_comparisons"] = {
                target_key: {
                    **single_year.compare_to_target(metrics["non_vfc_total_obligations"], target),
                    "absolute_difference": abs(metrics["non_vfc_total_obligations"] - target),
                }
                for target_key, target in funding_profile_targets.items()
            }
        scenarios[scenario_key] = scenario

    return scenarios


def closest_scenarios_by_target(
    scenarios: dict[str, Any],
    targets: dict[str, Decimal] | None,
) -> dict[str, Any]:
    if not targets:
        return {}
    closest: dict[str, Any] = {}
    for target_key, target in targets.items():
        rows = []
        for scenario_key, scenario in scenarios.items():
            total = scenario["non_vfc_total_obligations"]
            rows.append(
                {
                    "target": target_key,
                    "scenario": scenario_key,
                    "label": scenario["label"],
                    "non_vfc_total_obligations": total,
                    "difference": total - target,
                    "absolute_difference": abs(total - target),
                    "percent_difference": single_year.pct(total - target, target),
                }
            )
        closest[target_key] = min(rows, key=lambda row: row["absolute_difference"])
    return closest


def top_group_rows(
    records: list[dict[str, Any]],
    *,
    group_key,
    labeler,
    limit: int = 15,
) -> list[dict[str, Any]]:
    groups: dict[Any, single_year.Metrics] = defaultdict(single_year.Metrics)
    for record in records:
        single_year.add_record(groups[group_key(record)], record)
    return single_year.sorted_metric_rows(groups, labeler, limit=limit)


def top_listing_and_account_tables(records: list[dict[str, Any]]) -> dict[str, Any]:
    scenario_keys = {
        "no_exclusion": "A_no_emergency_supplemental_exclusion",
        "current_overall_award_exclusion": "B_current_overall_award_covid_iija_amount_exclusion",
        "profile_aligned_exclusion": "F_profile_aligned_text_category_defc_exclusion",
    }
    definitions = single_year.scenario_definitions()
    tables: dict[str, Any] = {}
    for alias, scenario_key in scenario_keys.items():
        included = included_records_for_scenario(records, definitions[scenario_key])
        tables[alias] = {
            "top_assistance_listings": top_group_rows(
                included,
                group_key=lambda record: (
                    record["cfda_number"] or "(blank)",
                    record["cfda_title"] or "(blank)",
                ),
                labeler=lambda key: {
                    "assistance_listing_number": key[0],
                    "assistance_listing_title": key[1],
                },
            ),
            "top_federal_accounts": top_group_rows(
                included,
                group_key=lambda record: record["federal_accounts_funding_this_award"] or "(blank)",
                labeler=lambda key: {"federal_accounts_funding_this_award": key},
            ),
        }
    return tables


def defc_tables(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_classification: dict[str, single_year.Metrics] = defaultdict(single_year.Metrics)
    by_code: dict[str, single_year.Metrics] = defaultdict(single_year.Metrics)
    for record in records:
        single_year.add_record(by_classification[record["defc_classification"]], record)
        if not record["defc_codes"]:
            single_year.add_record(by_code["(blank)"], record)
        for code in record["defc_codes"]:
            single_year.add_record(by_code[code], record)
    return {
        "by_defc_classification": single_year.sorted_metric_rows(
            by_classification,
            lambda key: {"defc_classification": key},
        ),
        "by_individual_defc_code": single_year.sorted_metric_rows(
            by_code,
            lambda key: {"defc_code": key},
        ),
        "note": (
            "The individual DEFC code table is not additive when an award-history field "
            "contains multiple codes; the same transaction contributes to each observed code."
        ),
    }


def process_year(
    fiscal_year: int,
    *,
    usaspending_root: Path,
    profile_files: dict[int, Path],
) -> dict[str, Any]:
    usaspending_file = find_usaspending_assistance_prime_file(usaspending_root, fiscal_year)
    if usaspending_file is None:
        return {
            "fiscal_year": fiscal_year,
            "status": "missing_usaspending_file",
            "usaspending_file": None,
        }

    usaspending = read_year_records(usaspending_file, fiscal_year)
    records = usaspending["records"]
    profiles = (
        funding_profiles_summary(profile_files[fiscal_year], fiscal_year)
        if fiscal_year in profile_files
        else None
    )
    targets = profiles["targets"] if profiles is not None else None
    scenarios = scenario_summaries(records, targets)

    return {
        "fiscal_year": fiscal_year,
        "status": "ok",
        "usaspending_file": usaspending_file,
        "funding_profiles_file": profile_files.get(fiscal_year),
        "usaspending_summary": {
            "source_row_count": usaspending["source_row_count"],
            "included_cdc_funded_positive_grant_assistance_row_count": usaspending["included_row_count"],
            "filter": {
                "action_date_fiscal_year": fiscal_year,
                "funding_agency_name": single_year.CDC_FUNDING_AGENCY_NAME,
                "funding_sub_agency_name": single_year.CDC_FUNDING_SUB_AGENCY_NAME,
                "federal_action_obligation": "> 0",
                "assistance_type_code": sorted(GRANT_ASSISTANCE_TYPE_CODES),
            },
        },
        "cdc_funding_profiles_summary": profiles,
        "usaspending_filter_scenarios": scenarios,
        "closest_scenarios_by_funding_profiles_target": closest_scenarios_by_target(scenarios, targets),
        "top_crosswalks": top_listing_and_account_tables(records),
        "defc_distribution": defc_tables(records),
    }


def target_for_year(year_report: dict[str, Any]) -> Decimal | None:
    profiles = year_report.get("cdc_funding_profiles_summary")
    if not profiles:
        return None
    return profiles["targets"]["funding_profiles_minus_vfc_minus_obvious_emergency_supplemental"]


def scenario_value(year_report: dict[str, Any], scenario_key: str, field: str) -> Decimal:
    return year_report["usaspending_filter_scenarios"][scenario_key][field]


def year_summary_row(year_report: dict[str, Any]) -> dict[str, Any]:
    fiscal_year = year_report["fiscal_year"]
    if year_report.get("status") != "ok":
        return {
            "fiscal_year": fiscal_year,
            "status": year_report.get("status"),
        }

    target = target_for_year(year_report)
    closest = None
    if target is not None:
        closest = year_report["closest_scenarios_by_funding_profiles_target"].get(
            "funding_profiles_minus_vfc_minus_obvious_emergency_supplemental"
        )

    return {
        "fiscal_year": fiscal_year,
        "status": "ok",
        "funding_profiles_target_non_vfc_non_emergency": target,
        "no_exclusion_non_vfc_total": scenario_value(
            year_report,
            "A_no_emergency_supplemental_exclusion",
            "non_vfc_total_obligations",
        ),
        "current_overall_award_exclusion_non_vfc_total": scenario_value(
            year_report,
            "B_current_overall_award_covid_iija_amount_exclusion",
            "non_vfc_total_obligations",
        ),
        "profile_aligned_non_vfc_total": scenario_value(
            year_report,
            "F_profile_aligned_text_category_defc_exclusion",
            "non_vfc_total_obligations",
        ),
        "closest_scenario_to_target": closest["label"] if closest else None,
        "closest_scenario_key_to_target": closest["scenario"] if closest else None,
        "closest_difference_from_target": closest["difference"] if closest else None,
        "closest_absolute_difference_from_target": closest["absolute_difference"] if closest else None,
    }


def compact_scenario_tables(year_reports: dict[int, dict[str, Any]]) -> dict[str, Any]:
    scenario_keys = list(single_year.scenario_definitions().keys())
    usa_totals: list[dict[str, Any]] = []
    usa_non_vfc_totals: list[dict[str, Any]] = []
    differences_from_baseline: list[dict[str, Any]] = []
    removed_by_rule: list[dict[str, Any]] = []
    funding_profile_targets: list[dict[str, Any]] = []

    for fiscal_year, report in sorted(year_reports.items()):
        if report.get("status") != "ok":
            continue
        total_row = {"fiscal_year": fiscal_year}
        non_vfc_row = {"fiscal_year": fiscal_year}
        diff_row = {"fiscal_year": fiscal_year}
        removed_row = {"fiscal_year": fiscal_year}
        for scenario_key in scenario_keys:
            scenario = report["usaspending_filter_scenarios"][scenario_key]
            total_row[scenario_key] = scenario["total_obligations"]
            non_vfc_row[scenario_key] = scenario["non_vfc_total_obligations"]
            diff_row[scenario_key] = scenario["removed_from_no_exclusion_baseline"]
        removed_row["current_overall_award_covid_iija_amount"] = diff_row[
            "B_current_overall_award_covid_iija_amount_exclusion"
        ]
        removed_row["broad_non_q_defc"] = diff_row["C_broad_defc_award_history_exclusion"]
        removed_row["profile_aligned"] = diff_row["F_profile_aligned_text_category_defc_exclusion"]
        usa_totals.append(total_row)
        usa_non_vfc_totals.append(non_vfc_row)
        differences_from_baseline.append(diff_row)
        removed_by_rule.append(removed_row)

        profiles = report.get("cdc_funding_profiles_summary")
        if profiles:
            funding_profile_targets.append(
                {
                    "fiscal_year": fiscal_year,
                    **profiles["targets"],
                    "funding_profiles_vfc_total": profiles["vfc_total"],
                    "funding_profiles_obvious_emergency_supplemental_total": profiles[
                        "obvious_emergency_supplemental_total"
                    ],
                }
            )

    return {
        "year_by_year_usaspending_scenario_totals": usa_totals,
        "year_by_year_usaspending_non_vfc_scenario_totals": usa_non_vfc_totals,
        "year_by_year_funding_profiles_targets": funding_profile_targets,
        "scenario_differences_compared_with_no_exclusion_baseline": differences_from_baseline,
        "amount_removed_by_rule": removed_by_rule,
    }


def recommendations(year_reports: dict[int, dict[str, Any]]) -> dict[str, Any]:
    ok_reports = [
        report
        for report in year_reports.values()
        if report.get("status") == "ok"
    ]
    profile_years = [
        report
        for report in ok_reports
        if report.get("cdc_funding_profiles_summary")
    ]

    current_removed = [
        scenario_value(report, "B_current_overall_award_covid_iija_amount_exclusion", "removed_from_no_exclusion_baseline")
        for report in ok_reports
    ]
    broad_removed = [
        scenario_value(report, "C_broad_defc_award_history_exclusion", "removed_from_no_exclusion_baseline")
        for report in ok_reports
    ]
    profile_removed = [
        scenario_value(report, "F_profile_aligned_text_category_defc_exclusion", "removed_from_no_exclusion_baseline")
        for report in ok_reports
    ]

    def range_text(values: list[Decimal]) -> str:
        if not values:
            return "not available"
        return f"{single_year.format_money(min(values))} to {single_year.format_money(max(values))}"

    fy2023 = year_reports.get(2023)
    prior_profile_years = [
        report
        for year, report in year_reports.items()
        if year in {2020, 2021, 2022} and report.get("cdc_funding_profiles_summary")
    ]

    closest_keys = {
        report["fiscal_year"]: report["closest_scenarios_by_funding_profiles_target"]
        .get("funding_profiles_minus_vfc_minus_obvious_emergency_supplemental", {})
        .get("scenario")
        for report in profile_years
    }
    closest_differences = {
        report["fiscal_year"]: report["closest_scenarios_by_funding_profiles_target"]
        .get("funding_profiles_minus_vfc_minus_obvious_emergency_supplemental", {})
        .get("difference")
        for report in profile_years
    }
    prior_differences = [
        difference
        for year, difference in closest_differences.items()
        if year in {2020, 2021, 2022} and difference is not None
    ]
    fy2023_difference = closest_differences.get(2023)
    fy2023_consistency = (
        fy2023 is not None
        and prior_profile_years
        and closest_keys.get(2023) == "B_current_overall_award_covid_iija_amount_exclusion"
        and all(
            closest_keys.get(year) == "B_current_overall_award_covid_iija_amount_exclusion"
            for year in {2020, 2021, 2022}
            if year in closest_keys
        )
        and fy2023_difference is not None
        and prior_differences
        and min(prior_differences) <= fy2023_difference <= max(prior_differences)
    )

    return {
        "findings": [
            (
                "The current overall-award COVID/IIJA exclusion is not a stable default "
                f"transaction filter across years; removed amounts range from {range_text(current_removed)}."
            ),
            (
                "Broad non-Q DEFC exclusion continues to over-exclude mixed award-history "
                f"transactions; removed amounts range from {range_text(broad_removed)}."
            ),
            (
                "The profile-aligned exclusion is more conservative than broad DEFC, but it "
                "does not land close to Funding Profiles non-VFC/non-emergency targets in "
                f"FY2020-FY2023; removed amounts range from {range_text(profile_removed)}."
            ),
            (
                "FY2023 is consistent with FY2020-FY2022 on closest-scenario behavior: all "
                "available Funding Profiles years are closest to the current overall-award "
                "COVID/IIJA exclusion, and FY2023's residual difference falls within the "
                "FY2020-FY2022 range."
            )
            if fy2023_consistency
            else "FY2023 consistency with FY2020-FY2022 could not be fully assessed from available profiles.",
            (
                "FY2021 is the strangest year: no-exclusion and profile-aligned totals are "
                "much higher than the Funding Profiles non-VFC/non-emergency target because "
                "a very large share of obligations sits on awards with supplemental/DEFC history."
            ),
            "Keep VFC exclusion separate from emergency/supplemental exclusion.",
        ],
        "closest_scenario_keys_by_profile_year": closest_keys,
        "closest_scenario_differences_by_profile_year": closest_differences,
        "recommended_next_production_fields": [
            "has_overall_award_supplemental_history",
            "defc_classification",
            "is_profile_aligned_emergency_supplemental",
            "is_likely_vfc",
            "funding_profiles_comparison_excluded",
            "funding_profiles_exclusion_reason",
        ],
        "recommended_next_methodology_update": (
            "Add supplemental-history and profile-aligned exclusion fields first, keep the "
            "map default mixed-award tolerant, and expose Funding Profiles comparison mode "
            "as a separate diagnostic/calibration view before changing public map defaults."
        ),
    }


def build_report(
    *,
    usaspending_root: Path,
    funding_profiles_dir: Path,
    fiscal_years: list[int],
    profile_file_mappings: dict[int, Path],
    output_path: Path,
    summary_csv_path: Path,
) -> dict[str, Any]:
    detected_profile_files, detection = detect_funding_profile_files(
        funding_profiles_dir,
        profile_file_mappings,
    )
    year_reports = {
        fiscal_year: process_year(
            fiscal_year,
            usaspending_root=usaspending_root,
            profile_files=detected_profile_files,
        )
        for fiscal_year in fiscal_years
    }

    year_summary = [
        year_summary_row(report)
        for _, report in sorted(year_reports.items())
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "usaspending_root": usaspending_root,
            "funding_profiles_dir": funding_profiles_dir,
            "fiscal_years": fiscal_years,
            "output_path": output_path,
            "summary_csv_path": summary_csv_path,
        },
        "funding_profiles_detection": {
            "detected_files_by_fiscal_year": {
                year: path
                for year, path in sorted(detected_profile_files.items())
            },
            **detection,
        },
        "years": year_reports,
        "cross_year_summary": {
            "terminal_summary_rows": year_summary,
            **compact_scenario_tables(year_reports),
        },
        "recommendations": recommendations(year_reports),
    }


def write_json_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(single_year.json_ready(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_summary_csv(report: dict[str, Any], summary_csv_path: Path) -> None:
    rows: list[dict[str, Any]] = []
    scenario_keys = list(single_year.scenario_definitions().keys())
    for fiscal_year, year_report in sorted(report["years"].items()):
        if year_report.get("status") != "ok":
            rows.append({"fiscal_year": fiscal_year, "status": year_report.get("status")})
            continue
        profiles = year_report.get("cdc_funding_profiles_summary") or {}
        targets = profiles.get("targets") or {}
        closest = year_report["closest_scenarios_by_funding_profiles_target"].get(
            "funding_profiles_minus_vfc_minus_obvious_emergency_supplemental",
            {},
        )
        for scenario_key in scenario_keys:
            scenario = year_report["usaspending_filter_scenarios"][scenario_key]
            target_comparison = scenario.get("non_vfc_target_comparisons", {}).get(
                "funding_profiles_minus_vfc_minus_obvious_emergency_supplemental",
                {},
            )
            rows.append(
                {
                    "fiscal_year": fiscal_year,
                    "status": "ok",
                    "funding_profiles_file": year_report.get("funding_profiles_file"),
                    "scenario_key": scenario_key,
                    "scenario_label": scenario["label"],
                    "total_obligations": scenario["total_obligations"],
                    "non_vfc_total_obligations": scenario["non_vfc_total_obligations"],
                    "vfc_amount": scenario["vfc_amount"],
                    "transaction_count": scenario["transaction_count"],
                    "award_count": scenario["award_count"],
                    "recipient_count": scenario["recipient_count"],
                    "state_identifiable_total": scenario["state_identifiable_total"],
                    "state_unmapped_total": scenario["state_unmapped_total"],
                    "foreign_global_unmapped_total": scenario["foreign_global_unmapped_total"],
                    "amount_from_awards_with_supplemental_defc_history": scenario[
                        "amount_from_awards_with_supplemental_defc_history"
                    ],
                    "amount_from_awards_without_supplemental_defc_history": scenario[
                        "amount_from_awards_without_supplemental_defc_history"
                    ],
                    "removed_from_no_exclusion_baseline": scenario[
                        "removed_from_no_exclusion_baseline"
                    ],
                    "funding_profiles_total": targets.get("funding_profiles_total"),
                    "funding_profiles_minus_vfc": targets.get("funding_profiles_minus_vfc"),
                    "funding_profiles_minus_obvious_emergency_supplemental": targets.get(
                        "funding_profiles_minus_obvious_emergency_supplemental"
                    ),
                    "funding_profiles_minus_vfc_minus_obvious_emergency_supplemental": targets.get(
                        "funding_profiles_minus_vfc_minus_obvious_emergency_supplemental"
                    ),
                    "difference_from_non_vfc_non_emergency_target": target_comparison.get("difference"),
                    "absolute_difference_from_non_vfc_non_emergency_target": target_comparison.get(
                        "absolute_difference"
                    ),
                    "percent_difference_from_non_vfc_non_emergency_target": target_comparison.get(
                        "percent_difference"
                    ),
                    "closest_scenario_to_non_vfc_non_emergency_target": closest.get("scenario"),
                }
            )

    fieldnames = sorted({key for row in rows for key in row})
    preferred = [
        "fiscal_year",
        "status",
        "scenario_key",
        "scenario_label",
        "total_obligations",
        "non_vfc_total_obligations",
        "vfc_amount",
        "funding_profiles_minus_vfc_minus_obvious_emergency_supplemental",
        "difference_from_non_vfc_non_emergency_target",
        "absolute_difference_from_non_vfc_non_emergency_target",
        "percent_difference_from_non_vfc_non_emergency_target",
        "closest_scenario_to_non_vfc_non_emergency_target",
    ]
    fieldnames = preferred + [field for field in fieldnames if field not in preferred]
    summary_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(single_year.json_ready(row))


def print_summary(report: dict[str, Any]) -> None:
    print("USAspending vs CDC Funding Profiles disaster filter comparison, all years")
    print(f"Output JSON: {report['inputs']['output_path']}")
    print(f"Summary CSV: {report['inputs']['summary_csv_path']}")
    print()
    print("Detected Funding Profiles files")
    for year, path in report["funding_profiles_detection"]["detected_files_by_fiscal_year"].items():
        print(f"  FY{year}: {path}")
    print()
    print(
        "FY | FP target | no-excl non-VFC | current non-VFC | profile-aligned non-VFC | closest | diff"
    )
    for row in report["cross_year_summary"]["terminal_summary_rows"]:
        if row.get("status") != "ok":
            print(f"{row['fiscal_year']} | {row.get('status')} |")
            continue
        target = row.get("funding_profiles_target_non_vfc_non_emergency")
        closest = row.get("closest_scenario_to_target") or "(no FP target)"
        diff = row.get("closest_difference_from_target")
        print(
            f"{row['fiscal_year']} | "
            f"{single_year.format_money(target) if target is not None else 'n/a'} | "
            f"{single_year.format_money(row['no_exclusion_non_vfc_total'])} | "
            f"{single_year.format_money(row['current_overall_award_exclusion_non_vfc_total'])} | "
            f"{single_year.format_money(row['profile_aligned_non_vfc_total'])} | "
            f"{closest} | "
            f"{single_year.format_money(diff) if diff is not None else 'n/a'}"
        )


def main() -> int:
    args = parse_args()
    fiscal_years = parse_fiscal_years(args.fiscal_years)
    profile_file_mappings = parse_profile_file_mappings(args.profile_file)
    report = build_report(
        usaspending_root=args.usaspending_root.expanduser().resolve(),
        funding_profiles_dir=args.funding_profiles_dir.expanduser().resolve(),
        fiscal_years=fiscal_years,
        profile_file_mappings=profile_file_mappings,
        output_path=args.output.expanduser().resolve(),
        summary_csv_path=args.summary_csv.expanduser().resolve(),
    )
    write_json_report(report, args.output.expanduser().resolve())
    write_summary_csv(report, args.summary_csv.expanduser().resolve())
    print_summary(single_year.json_ready(report))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        sys.exit(1)
