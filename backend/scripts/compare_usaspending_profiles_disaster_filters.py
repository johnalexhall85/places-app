#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


BACKEND_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_USASPENDING_CSV = Path("/mnt/data/All_Assistance_PrimeTransactions_2026-07-02_H17M58S45_1.csv")
DEFAULT_FUNDING_PROFILES_CSV = Path("/mnt/data/2023 CSV Data.csv")
DEFAULT_OUTPUT_PATH = (
    BACKEND_ROOT
    / "data_profiles"
    / "fy2023_usaspending_profiles_disaster_filter_comparison.json"
)
DEFAULT_FISCAL_YEAR = 2023
ENCODING_CANDIDATES = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

CDC_FUNDING_AGENCY_NAME = "Department of Health and Human Services"
CDC_FUNDING_SUB_AGENCY_NAME = "Centers for Disease Control and Prevention"

DEFC_Q = "Q"
DEFC_COVID_CODES = {"L", "N", "P", "U"}
DEFC_ARP_CODES = {"V"}
DEFC_OTHER_EMERGENCY_CODES = {"C", "E", "X", "6", "AAB"}
KNOWN_NON_Q_DEFC_CODES = DEFC_COVID_CODES | DEFC_ARP_CODES | DEFC_OTHER_EMERGENCY_CODES

PROFILE_EMERGENCY_CATEGORY = "Public Health Social Services Emergency Fund (PHSSEF)"
PROFILE_PHEP_REGULAR_SUBCATEGORY = "Public Health Emergency Preparedness Cooperative Agreement"
PROFILE_STRONG_SUBCATEGORY_PATTERNS = (
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

USASPENDING_STRONG_PROFILE_TEXT_RE = re.compile(
    r"\bPHSSEF\b|"
    r"\bCOVID(?:-19)?\b|"
    r"\bCoronavirus\b|"
    r"\bCARES\b|"
    r"\bAmerican Rescue Plan\b|"
    r"\bARP\b|"
    r"\bHurricane Supplemental\b|"
    r"\bsupplemental\b|"
    r"\bpublic health crisis response\b",
    re.IGNORECASE,
)
DEFC_CODE_RE = re.compile(r"(?:^|[;,|])\s*([A-Z0-9]{1,3})\s*:")


@dataclass
class Metrics:
    total_obligations: Decimal = Decimal("0")
    transaction_count: int = 0
    award_keys: set[str] = field(default_factory=set)
    recipient_keys: set[str] = field(default_factory=set)

    def add(
        self,
        amount: Decimal,
        *,
        award_key: str | None = None,
        recipient_key: str | None = None,
    ) -> None:
        self.total_obligations += amount
        self.transaction_count += 1
        if award_key:
            self.award_keys.add(award_key)
        if recipient_key:
            self.recipient_keys.add(recipient_key)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_obligations": self.total_obligations,
            "transaction_count": self.transaction_count,
            "award_count": len(self.award_keys),
            "recipient_count": len(self.recipient_keys),
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare USAspending FY CDC-funded assistance transactions against "
            "CDC Funding Profiles under alternate emergency/supplemental exclusions."
        )
    )
    parser.add_argument("--usaspending-csv", type=Path, default=DEFAULT_USASPENDING_CSV)
    parser.add_argument("--funding-profiles-csv", type=Path, default=DEFAULT_FUNDING_PROFILES_CSV)
    parser.add_argument("--fiscal-year", type=int, default=DEFAULT_FISCAL_YEAR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def detect_encoding(path: Path) -> str:
    last_error: UnicodeDecodeError | None = None
    for encoding in ENCODING_CANDIDATES:
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                for _ in handle:
                    pass
            return encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return ENCODING_CANDIDATES[0]


def csv_rows(path: Path) -> Iterable[dict[str, str]]:
    encoding = detect_encoding(path)
    with path.open("r", encoding=encoding, newline="") as handle:
        reader = csv.DictReader(handle)
        yield from reader


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", clean_text(value)).casefold()


def money(value: Any) -> Decimal:
    text = clean_text(value)
    if not text:
        return Decimal("0")
    text = text.replace("$", "").replace(",", "").strip()
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")


def json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    return value


def format_money(value: Decimal | float | int) -> str:
    amount = Decimal(str(value))
    return f"${amount:,.2f}"


def pct(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return None
    return numerator / denominator * Decimal("100")


def compare_to_target(total: Decimal, target: Decimal) -> dict[str, Any]:
    difference = total - target
    return {
        "target": target,
        "difference": difference,
        "percent_difference": pct(difference, target),
    }


def metric_row(label_fields: dict[str, Any], metrics: Metrics) -> dict[str, Any]:
    return {**label_fields, **metrics.as_dict()}


def sorted_metric_rows(
    groups: dict[Any, Metrics],
    labeler,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    rows = [
        metric_row(labeler(key), metrics)
        for key, metrics in groups.items()
    ]
    rows.sort(key=lambda row: row["total_obligations"], reverse=True)
    return rows if limit is None else rows[:limit]


def is_profile_vfc(category: str) -> bool:
    return normalize_text(category) == "vaccines for children"


def profile_emergency_reasons(category: str, subcategory: str) -> list[str]:
    category_norm = normalize_text(category)
    subcategory_norm = normalize_text(subcategory)
    reasons: list[str] = []

    if category_norm == normalize_text(PROFILE_EMERGENCY_CATEGORY):
        reasons.append("category_public_health_social_services_emergency_fund")

    for pattern in PROFILE_STRONG_SUBCATEGORY_PATTERNS:
        if normalize_text(pattern) in subcategory_norm:
            reasons.append(f"subcategory_contains_{re.sub(r'[^a-z0-9]+', '_', pattern.lower()).strip('_')}")

    if PROFILE_ARP_RE.search(subcategory):
        reasons.append("subcategory_contains_arp")

    is_regular_phep = normalize_text(PROFILE_PHEP_REGULAR_SUBCATEGORY) in subcategory_norm
    if "emergency" in subcategory_norm and not is_regular_phep:
        reasons.append("subcategory_contains_emergency")

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

    for row in csv_rows(path):
        row_count += 1
        row_fiscal_year = clean_text(row.get("Fiscal Year"))
        if row_fiscal_year and row_fiscal_year != str(fiscal_year):
            continue

        included_row_count += 1
        amount = money(row.get("Amount"))
        category = clean_text(row.get("Category")) or "(blank)"
        subcategory = clean_text(row.get("Sub-Category")) or "(blank)"
        is_vfc = is_profile_vfc(category)
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
        "non_vfc_non_obvious_emergency_supplemental_total": (
            non_vfc_non_obvious_emergency_total
        ),
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
            "not_excluded_by_emergency_word_alone": PROFILE_PHEP_REGULAR_SUBCATEGORY,
        },
    }


def parse_defc_codes(raw_value: str) -> list[str]:
    text = clean_text(raw_value)
    if not text:
        return []

    codes = [match.group(1).upper() for match in DEFC_CODE_RE.finditer(text)]
    if not codes and ":" in text:
        possible_code = text.split(":", 1)[0].strip().upper()
        if re.fullmatch(r"[A-Z0-9]{1,3}", possible_code):
            codes = [possible_code]
    if not codes:
        for token in re.split(r"[;,|\s]+", text):
            token = token.strip().upper()
            if token in ({DEFC_Q} | KNOWN_NON_Q_DEFC_CODES):
                codes.append(token)

    deduped: list[str] = []
    for code in codes:
        if code not in deduped:
            deduped.append(code)
    return deduped


def classify_defc(codes: list[str]) -> str:
    code_set = set(codes)
    has_q = DEFC_Q in code_set
    has_non_q = bool(code_set - {DEFC_Q})
    unknown_codes = code_set - ({DEFC_Q} | KNOWN_NON_Q_DEFC_CODES)

    if not code_set or code_set == {DEFC_Q}:
        return "regular_or_not_designated"
    if unknown_codes:
        return "unknown"
    if has_non_q and not has_q:
        return "clean_supplemental_award"
    if has_q and has_non_q:
        return "mixed_regular_and_supplemental_award"
    return "unknown"


def first_nonblank(row: dict[str, str], columns: tuple[str, ...]) -> str:
    for column in columns:
        value = clean_text(row.get(column))
        if value:
            return value
    return ""


def award_key(row: dict[str, str]) -> str:
    return first_nonblank(
        row,
        (
            "assistance_award_unique_key",
            "award_unique_key",
            "generated_unique_award_id",
            "award_id_fain",
            "award_id_uri",
            "award_id_piid",
        ),
    )


def recipient_key(row: dict[str, str]) -> str:
    return first_nonblank(
        row,
        (
            "recipient_uei",
            "recipient_duns",
            "recipient_name",
        ),
    )


def transaction_key(row: dict[str, str]) -> str:
    return first_nonblank(
        row,
        (
            "assistance_transaction_unique_key",
            "transaction_unique_key",
            "transaction_id",
        ),
    )


def is_cdc_funded_positive_fy(row: dict[str, str], fiscal_year: int) -> bool:
    return (
        clean_text(row.get("action_date_fiscal_year")) == str(fiscal_year)
        and clean_text(row.get("funding_agency_name")) == CDC_FUNDING_AGENCY_NAME
        and clean_text(row.get("funding_sub_agency_name")) == CDC_FUNDING_SUB_AGENCY_NAME
        and money(row.get("federal_action_obligation")) > 0
    )


def is_likely_vfc(row: dict[str, str]) -> bool:
    cfda_number = clean_text(row.get("cfda_number"))
    cfda_title = normalize_text(row.get("cfda_title"))
    transaction_description = normalize_text(row.get("transaction_description"))
    base_description = normalize_text(row.get("prime_award_base_transaction_description"))
    description_blob = f"{transaction_description} {base_description}"
    return (
        cfda_number == "93.268"
        or "immunization cooperative agreements" in cfda_title
        or "vaccines for children" in description_blob
        or re.search(r"\bVFC\b", clean_text(row.get("transaction_description")), re.IGNORECASE) is not None
        or re.search(
            r"\bVFC\b",
            clean_text(row.get("prime_award_base_transaction_description")),
            re.IGNORECASE,
        )
        is not None
    )


def strong_profile_text_matches(row: dict[str, str]) -> list[str]:
    fields = {
        "cfda_title": clean_text(row.get("cfda_title")),
        "assistance_listing_title": clean_text(row.get("assistance_listing_title")),
        "transaction_description": clean_text(row.get("transaction_description")),
        "prime_award_base_transaction_description": clean_text(
            row.get("prime_award_base_transaction_description")
        ),
        "federal_accounts_funding_this_award": clean_text(
            row.get("federal_accounts_funding_this_award")
        ),
        "treasury_accounts_funding_this_award": clean_text(
            row.get("treasury_accounts_funding_this_award")
        ),
    }
    matches = [
        field
        for field, value in fields.items()
        if value and USASPENDING_STRONG_PROFILE_TEXT_RE.search(value)
    ]
    return matches


def make_usaspending_record(row: dict[str, str]) -> dict[str, Any]:
    defc_codes = parse_defc_codes(row.get("disaster_emergency_fund_codes_for_overall_award", ""))
    defc_code_set = set(defc_codes)
    has_defc_q = DEFC_Q in defc_code_set
    has_defc_non_q = bool(defc_code_set - {DEFC_Q})
    defc_classification = classify_defc(defc_codes)
    strong_text_fields = strong_profile_text_matches(row)

    current_overall_award_amount_exclusion = (
        money(row.get("obligated_amount_from_COVID-19_supplementals_for_overall_award")) > 0
        or money(row.get("obligated_amount_from_IIJA_supplemental_for_overall_award")) > 0
    )
    clean_defc_exclusion = defc_classification == "clean_supplemental_award"
    profile_aligned_exclusion = clean_defc_exclusion or bool(strong_text_fields)

    return {
        "amount": money(row.get("federal_action_obligation")),
        "transaction_key": transaction_key(row),
        "award_key": award_key(row),
        "recipient_key": recipient_key(row),
        "cfda_number": clean_text(row.get("cfda_number")),
        "cfda_title": clean_text(row.get("cfda_title")),
        "federal_accounts_funding_this_award": clean_text(row.get("federal_accounts_funding_this_award")),
        "treasury_accounts_funding_this_award": clean_text(row.get("treasury_accounts_funding_this_award")),
        "defc_codes": defc_codes,
        "has_defc_q": has_defc_q,
        "has_defc_non_q": has_defc_non_q,
        "has_defc_covid": bool(defc_code_set & DEFC_COVID_CODES),
        "has_defc_arp": bool(defc_code_set & DEFC_ARP_CODES),
        "has_defc_other_emergency": bool(defc_code_set & DEFC_OTHER_EMERGENCY_CODES),
        "defc_classification": defc_classification,
        "is_likely_vfc": is_likely_vfc(row),
        "strong_profile_text_fields": strong_text_fields,
        "scenario_exclusion_flags": {
            "B_current_overall_award_covid_iija_amount": current_overall_award_amount_exclusion,
            "C_broad_defc_award_history": has_defc_non_q,
            "D_clean_defc_only": clean_defc_exclusion,
            "E_mixed_aware_defc": clean_defc_exclusion,
            "F_profile_aligned_text_category_defc": profile_aligned_exclusion,
        },
    }


def read_usaspending_records(path: Path, fiscal_year: int) -> dict[str, Any]:
    source_row_count = 0
    included_records: list[dict[str, Any]] = []

    for row in csv_rows(path):
        source_row_count += 1
        if is_cdc_funded_positive_fy(row, fiscal_year):
            included_records.append(make_usaspending_record(row))

    return {
        "source_row_count": source_row_count,
        "included_row_count": len(included_records),
        "records": included_records,
    }


def add_record(metrics: Metrics, record: dict[str, Any]) -> None:
    metrics.add(
        record["amount"],
        award_key=record.get("award_key"),
        recipient_key=record.get("recipient_key"),
    )


def metrics_for_records(records: Iterable[dict[str, Any]]) -> Metrics:
    metrics = Metrics()
    for record in records:
        add_record(metrics, record)
    return metrics


def scenario_definitions() -> dict[str, dict[str, str | None]]:
    return {
        "A_no_emergency_supplemental_exclusion": {
            "label": "A. No emergency/supplemental exclusion",
            "flag": None,
        },
        "B_current_overall_award_covid_iija_amount_exclusion": {
            "label": "B. Current overall-award COVID/IIJA amount exclusion",
            "flag": "B_current_overall_award_covid_iija_amount",
        },
        "C_broad_defc_award_history_exclusion": {
            "label": "C. Broad DEFC award-history exclusion",
            "flag": "C_broad_defc_award_history",
        },
        "D_clean_defc_only_exclusion": {
            "label": "D. Clean DEFC-only exclusion",
            "flag": "D_clean_defc_only",
        },
        "E_mixed_aware_defc_exclusion": {
            "label": "E. Mixed-aware DEFC exclusion",
            "flag": "E_mixed_aware_defc",
        },
        "F_profile_aligned_text_category_defc_exclusion": {
            "label": "F. Profile-aligned text/category/DEFC exclusion",
            "flag": "F_profile_aligned_text_category_defc",
        },
    }


def build_scenario_summary(
    records: list[dict[str, Any]],
    funding_profile_targets: dict[str, Decimal],
) -> dict[str, Any]:
    scenarios: dict[str, Any] = {}
    for scenario_key, definition in scenario_definitions().items():
        flag = definition["flag"]
        if flag is None:
            included = list(records)
            excluded = []
        else:
            included = [
                record
                for record in records
                if not record["scenario_exclusion_flags"].get(flag, False)
            ]
            excluded = [
                record
                for record in records
                if record["scenario_exclusion_flags"].get(flag, False)
            ]

        included_non_vfc = [
            record
            for record in included
            if not record["is_likely_vfc"]
        ]
        metrics = metrics_for_records(included)
        non_vfc_metrics = metrics_for_records(included_non_vfc)
        excluded_metrics = metrics_for_records(excluded)

        scenarios[scenario_key] = {
            "label": definition["label"],
            "exclusion_flag": flag,
            "included": {
                **metrics.as_dict(),
                "target_comparisons": {
                    target_key: compare_to_target(metrics.total_obligations, target)
                    for target_key, target in funding_profile_targets.items()
                },
            },
            "included_after_excluding_likely_vfc": {
                **non_vfc_metrics.as_dict(),
                "target_comparisons": {
                    target_key: compare_to_target(non_vfc_metrics.total_obligations, target)
                    for target_key, target in funding_profile_targets.items()
                },
            },
            "excluded_by_emergency_supplemental_rule": excluded_metrics.as_dict(),
        }

    comparison_target_key = "funding_profiles_minus_vfc_minus_obvious_emergency_supplemental"
    comparison_target = funding_profile_targets[comparison_target_key]
    closest = min(
        (
            {
                "scenario": scenario_key,
                "label": scenario["label"],
                "total_obligations": scenario["included_after_excluding_likely_vfc"]["total_obligations"],
                "absolute_difference": abs(
                    scenario["included_after_excluding_likely_vfc"]["total_obligations"] - comparison_target
                ),
                "target": comparison_target_key,
            }
            for scenario_key, scenario in scenarios.items()
        ),
        key=lambda row: row["absolute_difference"],
    )

    broad_excluded = scenarios["C_broad_defc_award_history_exclusion"][
        "excluded_by_emergency_supplemental_rule"
    ]["total_obligations"]
    profile_aligned_excluded = scenarios["F_profile_aligned_text_category_defc_exclusion"][
        "excluded_by_emergency_supplemental_rule"
    ]["total_obligations"]

    return {
        "scenarios": scenarios,
        "closest_to_funding_profiles_minus_vfc_minus_obvious_emergency_supplemental": closest,
        "broad_defc_over_exclusion_vs_profile_aligned": {
            "broad_defc_excluded_total": broad_excluded,
            "profile_aligned_excluded_total": profile_aligned_excluded,
            "additional_obligations_excluded_by_broad_defc": broad_excluded - profile_aligned_excluded,
        },
    }


def build_crosswalk_tables(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_listing: dict[tuple[str, str], Metrics] = defaultdict(Metrics)
    by_federal_account: dict[str, Metrics] = defaultdict(Metrics)
    by_defc_classification: dict[str, Metrics] = defaultdict(Metrics)
    by_defc_code: dict[str, Metrics] = defaultdict(Metrics)
    by_scenario_flags: dict[tuple[bool, bool, bool, bool, bool, bool], Metrics] = defaultdict(Metrics)
    profile_aligned_listing_candidates: dict[tuple[str, str], Metrics] = defaultdict(Metrics)
    profile_aligned_account_candidates: dict[str, Metrics] = defaultdict(Metrics)

    for record in records:
        listing_key = (record["cfda_number"] or "(blank)", record["cfda_title"] or "(blank)")
        federal_account = record["federal_accounts_funding_this_award"] or "(blank)"
        scenario_flags = record["scenario_exclusion_flags"]
        flags_key = (
            bool(scenario_flags["B_current_overall_award_covid_iija_amount"]),
            bool(scenario_flags["C_broad_defc_award_history"]),
            bool(scenario_flags["D_clean_defc_only"]),
            bool(scenario_flags["E_mixed_aware_defc"]),
            bool(scenario_flags["F_profile_aligned_text_category_defc"]),
            bool(record["is_likely_vfc"]),
        )

        add_record(by_listing[listing_key], record)
        add_record(by_federal_account[federal_account], record)
        add_record(by_defc_classification[record["defc_classification"]], record)
        add_record(by_scenario_flags[flags_key], record)

        if not record["defc_codes"]:
            add_record(by_defc_code["(blank)"], record)
        for code in record["defc_codes"]:
            add_record(by_defc_code[code], record)

        if scenario_flags["F_profile_aligned_text_category_defc"]:
            add_record(profile_aligned_listing_candidates[listing_key], record)
            add_record(profile_aligned_account_candidates[federal_account], record)

    return {
        "by_assistance_listing_number_title": sorted_metric_rows(
            by_listing,
            lambda key: {"assistance_listing_number": key[0], "assistance_listing_title": key[1]},
        ),
        "by_federal_accounts_funding_this_award": sorted_metric_rows(
            by_federal_account,
            lambda key: {"federal_accounts_funding_this_award": key},
        ),
        "by_defc_classification": sorted_metric_rows(
            by_defc_classification,
            lambda key: {"defc_classification": key},
        ),
        "by_individual_defc_code": sorted_metric_rows(
            by_defc_code,
            lambda key: {"defc_code": key},
        ),
        "by_emergency_supplemental_scenario_flags": sorted_metric_rows(
            by_scenario_flags,
            lambda key: {
                "current_overall_award_covid_iija_amount": key[0],
                "broad_defc_award_history": key[1],
                "clean_defc_only": key[2],
                "mixed_aware_defc": key[3],
                "profile_aligned_text_category_defc": key[4],
                "likely_vfc": key[5],
            },
        ),
        "profile_aligned_supplemental_assistance_listing_candidates": sorted_metric_rows(
            profile_aligned_listing_candidates,
            lambda key: {"assistance_listing_number": key[0], "assistance_listing_title": key[1]},
        ),
        "profile_aligned_supplemental_federal_account_candidates": sorted_metric_rows(
            profile_aligned_account_candidates,
            lambda key: {"federal_accounts_funding_this_award": key},
        ),
        "note": (
            "The individual DEFC code table is not additive when an award-history field "
            "contains multiple codes; the same transaction contributes to each observed code."
        ),
    }


def recommendation() -> dict[str, Any]:
    return {
        "map_default_rule": [
            "Do not use overall-award COVID obligated amount as a default transaction exclusion.",
            "Do not use any non-Q DEFC as a broad exclusion, because it over-excludes mixed awards.",
            "Use DEFC classification as an award-history flag, not transaction-level proof.",
            (
                "Keep mixed_regular_and_supplemental_award transactions by default unless "
                "they match strong profile-aligned supplemental signals."
            ),
        ],
        "funding_profiles_comparison_mode_rule": [
            (
                "Use a profile-aligned exclusion combining clean supplemental DEFC history, "
                "strong text/category patterns, and reviewed supplemental assistance listings "
                "or federal accounts discovered in the crosswalk tables."
            ),
            (
                "Strong text signals include PHSSEF, COVID, Coronavirus, CARES, American "
                "Rescue Plan, ARP, Hurricane Supplemental, supplemental, and public health "
                "crisis response."
            ),
            (
                "Do not exclude regular Public Health Emergency Preparedness solely because "
                "the word Emergency appears in the program name."
            ),
        ],
    }


def build_report(
    *,
    usaspending_csv: Path,
    funding_profiles_csv: Path,
    fiscal_year: int,
    output_path: Path,
) -> dict[str, Any]:
    if not usaspending_csv.exists():
        raise FileNotFoundError(f"USAspending CSV not found: {usaspending_csv}")
    if not funding_profiles_csv.exists():
        raise FileNotFoundError(f"CDC Funding Profiles CSV not found: {funding_profiles_csv}")

    profiles = funding_profiles_summary(funding_profiles_csv, fiscal_year)
    usaspending = read_usaspending_records(usaspending_csv, fiscal_year)
    scenario_summary = build_scenario_summary(usaspending["records"], profiles["targets"])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "usaspending_csv": usaspending_csv,
            "funding_profiles_csv": funding_profiles_csv,
            "fiscal_year": fiscal_year,
            "output_path": output_path,
        },
        "cdc_funding_profiles_summary": profiles,
        "usaspending_summary": {
            "input_path": usaspending_csv,
            "source_row_count": usaspending["source_row_count"],
            "included_cdc_funded_positive_fy_row_count": usaspending["included_row_count"],
            "filter": {
                "action_date_fiscal_year": fiscal_year,
                "funding_agency_name": CDC_FUNDING_AGENCY_NAME,
                "funding_sub_agency_name": CDC_FUNDING_SUB_AGENCY_NAME,
                "federal_action_obligation": "> 0",
            },
            "defc_code_sets": {
                "regular_or_not_designated": [DEFC_Q],
                "covid_era_emergency": sorted(DEFC_COVID_CODES),
                "arp": sorted(DEFC_ARP_CODES),
                "other_emergency_disaster_supplemental": sorted(DEFC_OTHER_EMERGENCY_CODES),
            },
        },
        "usaspending_filter_scenarios": scenario_summary["scenarios"],
        "closest_scenario": scenario_summary[
            "closest_to_funding_profiles_minus_vfc_minus_obvious_emergency_supplemental"
        ],
        "broad_defc_over_exclusion_vs_profile_aligned": scenario_summary[
            "broad_defc_over_exclusion_vs_profile_aligned"
        ],
        "crosswalk_tables": build_crosswalk_tables(usaspending["records"]),
        "recommendation": recommendation(),
    }


def write_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(json_ready(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def print_summary(report: dict[str, Any]) -> None:
    profiles = report["cdc_funding_profiles_summary"]
    target = profiles["targets"]["funding_profiles_minus_vfc_minus_obvious_emergency_supplemental"]
    print("USAspending vs CDC Funding Profiles disaster filter comparison")
    print(f"Fiscal year: {report['inputs']['fiscal_year']}")
    print(f"Output: {report['inputs']['output_path']}")
    print()
    print("CDC Funding Profiles")
    print(f"  Total: {format_money(profiles['total_amount'])}")
    print(f"  VFC: {format_money(profiles['vfc_total'])}")
    print(
        "  Obvious emergency/supplemental: "
        f"{format_money(profiles['obvious_emergency_supplemental_total'])}"
    )
    print(f"  Non-VFC / non-obvious-emergency target: {format_money(target)}")
    print()
    print("USAspending scenarios")
    for key, scenario in report["usaspending_filter_scenarios"].items():
        included = scenario["included"]
        non_vfc = scenario["included_after_excluding_likely_vfc"]
        print(
            f"  {scenario['label']}: "
            f"{format_money(included['total_obligations'])} "
            f"(non-VFC {format_money(non_vfc['total_obligations'])})"
        )
    print()
    closest = report["closest_scenario"]
    print("Closest to Funding Profiles minus VFC minus obvious emergency/supplemental")
    print(
        f"  {closest['label']}: {format_money(closest['total_obligations'])} "
        f"(abs diff {format_money(closest['absolute_difference'])})"
    )
    over = report["broad_defc_over_exclusion_vs_profile_aligned"]
    print()
    print("Broad DEFC vs profile-aligned exclusion")
    print(
        "  Additional obligations excluded by broad DEFC: "
        f"{format_money(over['additional_obligations_excluded_by_broad_defc'])}"
    )
    print()
    print("Recommendation")
    for line in report["recommendation"]["map_default_rule"]:
        print(f"  - {line}")
    for line in report["recommendation"]["funding_profiles_comparison_mode_rule"]:
        print(f"  - {line}")


def main() -> int:
    args = parse_args()
    report = build_report(
        usaspending_csv=args.usaspending_csv.expanduser().resolve(),
        funding_profiles_csv=args.funding_profiles_csv.expanduser().resolve(),
        fiscal_year=args.fiscal_year,
        output_path=args.output.expanduser().resolve(),
    )
    write_report(report, args.output.expanduser().resolve())
    print_summary(json_ready(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
