#!/usr/bin/env python3
"""Deterministic evaluation runner for the CHIP MCP server (Task M3 / M3b / H6 / F4).

Modes:
  --validate        Validate questions.yaml structure and coverage offline (no DB or server).
  --expected-only   Compute expected values directly from lookup layers against places_staging.
  --dataset-check   Fetch GET /funding/nofo/PS212102.json?subawards=1 and validate the v1 contract.
  --url URL         Run all expected_calls against the MCP server at URL, compare to lookup, and run checks.
  --report PATH     Write markdown evaluation report to PATH (default: deliverables/mcp/eval_report.md).
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import gzip
import json
import math
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# Ensure backend/ is importable when invoked from repo root or backend/
BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.area_pilot import lookup  # noqa: E402
from app.funding_report import lookup as funding_lookup  # noqa: E402

DEFAULT_QUESTIONS_PATH = Path(__file__).resolve().parent / "questions.yaml"
DEFAULT_REPORT_PATH = REPO_ROOT / "deliverables" / "mcp" / "eval_report.md"
TOPICS_PATH = BACKEND_DIR / "app" / "community" / "topics.json"

AREA_TOOLS: tuple[str, ...] = (
    "find_places",
    "search_measures",
    "get_measure_details",
    "get_area_values",
    "get_measure_across_areas",
    "get_measure_over_time",
    "get_area_context",
    "list_data_sources",
)

FUNDING_TOOLS: tuple[str, ...] = (
    "get_nofo_overview",
    "list_nofo_recipients",
    "get_recipient_funding",
)

ALL_TOOLS: tuple[str, ...] = AREA_TOOLS + FUNDING_TOOLS

PUBLIC_PRODUCTS: tuple[str, ...] = (
    "places",
    "acs",
    "acs_profile",
    "brfss",
    "clh",
    "cms_gv",
    "epa_aqi",
    "usda_fea",
)

FACILITY_BLOCKS: tuple[str, ...] = (
    "health_centers",
    "nursing_homes",
    "tri_facilities",
)

FUNDING_PRODUCTS: tuple[str, ...] = ("cdc_nofo_funding",)

FUNDING_SOURCE_IDS: frozenset[str] = frozenset({
    "usaspending_account",
    "usaspending_award",
    "taggs",
    "usaspending_subawards",
})

AREA_SOURCE_PRODUCTS: frozenset[str] = (
    frozenset(PUBLIC_PRODUCTS) | frozenset(FACILITY_BLOCKS) | frozenset({"ahrf"})
)

ALL_LEVELS: tuple[str, ...] = ("state", "county", "tract", "cd")

SHOWCASE_GEOIDS: tuple[str, ...] = ("37145", "54039", "06019", "5401")

REQUIRED_TRAP_KINDS: tuple[str, ...] = (
    "ahrf_excluded",
    "ahrf_withheld_topic",
    "ahrf_withheld_queries",
    "ahrf_over_time_withheld",
    "cd_no_earlier_periods",
    "unpublished_period_skipped",
    "no_computed_change",
    "across_areas_sort_single_period",
    "no_composite_score",
    "epa_aqi_no_monitor",
    "kentucky_brfss_not_published",
    "cms_not_published_for_cd",
    "tracts_require_county",
    "medicare_original_beneficiaries",
    "funding_nofo_no_match",
    "funding_non_cdc_nofo",
    "funding_subawards_no_add",
)

FUNDING_INTERPRETATION_RULES: tuple[str, ...] = (
    "Obligations are USAspending federal account (File C) obligations unless a row says otherwise; award-level and TAGGS amounts are shown for comparison and can differ.",
    "Sub-award amounts are reported by prime recipients and are not additional federal funding; never add them to prime obligations.",
    "Other federal awards are HHS awards recorded in TAGGS for the same UEI; they are not a complete federal funding portfolio.",
    "State the data-through date of each source and say when a fiscal year is not complete.",
    "Do not rank recipients by merit or describe funding as good or bad; report amounts, periods, and sources.",
)

FUNDING_ALLOWED_BEST_KEYS: frozenset[str] = frozenset({
    "best_available",
    "best_available_total",
    "best_available_basis",
})

DATASET_V1_TOP_KEYS: frozenset[str] = frozenset({
    "schema_version",
    "build",
    "sources",
    "nofo",
    "aggregates",
    "recipients",
    "subawards",
    "caveats",
})
DATASET_V1_BUILD_KEYS: frozenset[str] = frozenset({"build_id", "built_at", "method_version"})
DATASET_V1_SOURCE_KEYS: frozenset[str] = frozenset({
    "id",
    "publisher",
    "product",
    "coverage",
    "data_through",
    "citation",
})
DATASET_V1_NOFO_KEYS: frozenset[str] = frozenset({
    "nofo_key",
    "fon_display",
    "fon_variants",
    "awarding_agency",
    "awarding_offices",
    "cfda",
    "period_of_performance",
    "award_count",
    "recipient_count",
    "fiscal_years",
    "best_available_total",
})
DATASET_V1_NOFO_FY_KEYS: frozenset[str] = frozenset({
    "fiscal_year",
    "account_obligation",
    "award_obligation",
    "taggs_amount",
    "is_complete",
})
DATASET_V1_AGGREGATE_KEYS: frozenset[str] = frozenset({
    "by_state",
    "by_recipient_class",
    "by_recipient_type",
    "by_metro",
    "other_awards_by_opdiv",
    "other_awards_by_aln",
    "top_recipients_by_other_awards",
    "other_awards_top10_total",
    "other_award_rows",
    "recipients_without_other_awards",
})
DATASET_V1_RECIPIENT_KEYS: frozenset[str] = frozenset({
    "award_unique_key",
    "fain",
    "uei",
    "recipient_name",
    "name_variants",
    "parent",
    "address",
    "congressional_district",
    "congressional_district_source",
    "recipient_class",
    "recipient_type",
    "metro_status",
    "business_types",
    "project_title",
    "abstract",
    "cfda",
    "funding_office",
    "period_of_performance",
    "totals",
    "fiscal_years",
    "usaspending_url",
    "other_awards",
    "subawards",
})
DATASET_V1_ADDRESS_KEYS: frozenset[str] = frozenset({
    "line1",
    "line2",
    "city",
    "state",
    "zip",
    "county",
    "country",
})
DATASET_V1_TOTALS_KEYS: frozenset[str] = frozenset({
    "account_obligation",
    "award_obligation",
    "taggs_amount",
    "best_available",
    "best_available_basis",
})
DATASET_V1_RECIPIENT_FY_KEYS: frozenset[str] = frozenset({
    "fiscal_year",
    "account_obligation",
    "award_obligation",
    "taggs_amount",
})
DATASET_V1_OTHER_AWARDS_KEYS: frozenset[str] = frozenset({"count", "total", "top10_total", "top"})
DATASET_V1_OTHER_TOP_KEYS: frozenset[str] = frozenset({
    "rank",
    "award_number",
    "amount",
    "opdiv",
    "aln",
    "aln_title",
    "fon",
    "first_fiscal_year",
    "last_fiscal_year",
    "award_title",
})
DATASET_V1_RECIPIENT_SUBAWARDS_KEYS: frozenset[str] = frozenset({
    "subawardee_count",
    "action_count",
    "reported_amount",
})
DATASET_V1_SUBAWARDS_KEYS: frozenset[str] = frozenset({
    "summary",
    "by_fiscal_year",
    "by_state",
    "subawardees",
    "actions",
})
DATASET_V1_SUBAWARD_SUMMARY_KEYS: frozenset[str] = frozenset({
    "distinct_subawardees",
    "actions",
    "raw_records",
    "duplicates_removed",
    "reported_amount",
    "primes_with_subawards",
})
DATASET_V1_SUBAWARD_FY_KEYS: frozenset[str] = frozenset({
    "fiscal_year",
    "actions",
    "subawardees",
    "reported_amount",
})
DATASET_V1_SUBAWARD_STATE_KEYS: frozenset[str] = frozenset({"state", "subawardees"})
DATASET_V1_SUBAWARDEE_KEYS: frozenset[str] = frozenset({
    "uei",
    "name",
    "name_variants",
    "dba_names",
    "business_types",
    "address",
    "congressional_district",
    "prime_fains",
    "prime_recipients",
    "action_count",
    "reported_amount",
    "first_action_date",
    "last_action_date",
    "fiscal_years",
    "description_examples",
})
DATASET_V1_SUBAWARD_ACTION_KEYS: frozenset[str] = frozenset({
    "prime_fain",
    "prime_recipient",
    "subaward_number",
    "action_date",
    "fiscal_year",
    "amount",
    "subawardee_uei",
    "subawardee_name",
    "description",
    "sam_report_ids",
    "usaspending_url",
})
COMPACT_RECIPIENT_REQUIRED_KEYS: frozenset[str] = frozenset({
    "recipient_name",
    "state",
    "congressional_district",
    "uei",
    "fain",
    "award_unique_key",
    "best_available_total",
    "other_award_count",
})
FORBIDDEN_COMBINED_SUBAWARD_KEY_RE = re.compile(
    r"(combined_total|total_including_subaward|total_with_subaward|including_subaward|plus_subaward|prime_plus_subaward|prime_and_subaward)",
    re.IGNORECASE,
)

RULE_6_TEXT = (
    "Many measures also have earlier published periods. Each value carries its own period, release, "
    "and boundary vintage, and an earlier period can differ in method or boundaries (read its `note`). "
    "Present values from different periods side by side as published; CHIP does not compute changes or trends."
)

GENERAL_INTERPRETATION_RULES: tuple[str, ...] = (
    "Values are published by the named source for exactly the area shown; CHIP never adds, averages, or derives values across areas.",
    "A missing, suppressed, or not-published value is not zero; read `status_text`.",
    "Each value has its own period, population, and source; do not treat different periods or populations as directly comparable without saying so.",
    "Medicare (cms_gv) measures describe Original Medicare beneficiaries, not all residents.",
    "TRI facilities are facilities that report to EPA's Toxics Release Inventory; reporting does not mean a release, a violation, or a health risk.",
    RULE_6_TEXT,
)

OVER_TIME_WARNING = (
    "Values are shown as published for each period; earlier periods can differ in method or boundaries, "
    "and CHIP computes no change."
)

BOUNDARY_VINTAGE_WARNING = (
    "The boundary vintage differs between periods; compare the published areas with care."
)

ORDERING_WARNING = (
    "Order is by point estimate. Where uncertainty ranges overlap, the difference may not be meaningful. "
    "This is a list of one published measure, not a ranking of overall health."
)

WITHHELD_TOPIC_EXPLANATION = (
    "The topic 'Health care resources' (HRSA AHRF workforce and hospital measures) "
    "is on the CHIP website but not available through this public server."
)

DISTRICT_NO_EARLIER_PERIODS_ERROR = (
    "Congressional districts have no earlier periods in CHIP: older Congresses had different districts."
)

MAX_RESPONSE_BYTES = 50_000

VALUE_ROW_REQUIRED_KEYS: frozenset[str] = frozenset({
    "measure_key",
    "label",
    "area",
    "value",
    "unit",
    "storage_scale",
    "status",
    "status_text",
    "uncertainty",
    "period",
    "population",
    "value_type",
    "boundary_vintage",
    "release_id",
    "notes",
    "note",
    "source_credit",
    "citation",
})

ACROSS_AREAS_MEASURE_REQUIRED_KEYS: frozenset[str] = frozenset({
    "measure_key",
    "label",
    "unit",
    "storage_scale",
    "period",
    "population",
    "value_type",
    "release_id",
    "citation",
    "note",
    "uncertainty_kind",
    "uncertainty_label",
})

ACROSS_AREAS_MEASURE_OPTIONAL_KEYS: frozenset[str] = frozenset({
    "boundary_vintage",
    "source_credit",
    "product",
    "measure_id",
})

COMPACT_ROW_REQUIRED_KEYS: frozenset[str] = frozenset({
    "area",
    "value",
    "status",
    "status_text",
    "uncertainty",
})

MEASURE_PERIOD_ENTRY_REQUIRED_KEYS: frozenset[str] = frozenset({
    "period",
    "current",
    "available",
    "note",
    "boundary_vintage",
    "release_id",
})

SPEC_UNCERTAINTY: dict[str, str] = {spec.key: spec.uncertainty for spec in lookup.SPECS}

STATE_ABBR_TO_FIPS: dict[str, str] = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09",
    "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17",
    "IN": "18", "IA": "19", "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24",
    "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30", "NE": "31",
    "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38",
    "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54",
    "WI": "55", "WY": "56", "PR": "72",
}

FORBIDDEN_WORDS_RE = re.compile(r"\b(best|worst|score|top\s+performer)\b", re.IGNORECASE)
FORBIDDEN_KEY_TOKENS = {"best", "worst", "score"}

FORBIDDEN_CHANGE_KEY_RE = re.compile(
    r"(?:^|_)(change|trend|difference|diff|pct_change|percent_change|delta)(?:_|$)",
    re.IGNORECASE,
)
FORBIDDEN_CHANGE_TOKENS = {"change", "trend", "difference", "diff", "pct_change", "delta"}


# ---------------------------------------------------------------------------
# Pure check functions (unit-tested in test_checks.py)
# ---------------------------------------------------------------------------

def _norm_rule(text: str) -> str:
    """Normalize backticks and whitespace when comparing interpretation rules."""
    return " ".join(text.replace("`", "").strip().split())


def compute_competition_positions(values: list[float | int]) -> list[int]:
    """Compute standard competition positions (1, 2, 2, 4) for an ordered list of values."""
    positions: list[int] = []
    for idx, val in enumerate(values):
        if idx > 0 and val == values[idx - 1]:
            positions.append(positions[-1])
        else:
            positions.append(idx + 1)
    return positions


def check_no_ahrf(
    payload: Any,
    *,
    allow_excluded_list: bool = False,
    allow_withheld_warning: bool = False,
) -> list[str]:
    """Verify 'ahrf' never appears in data/sources output.

    - When `allow_excluded_list=True` (for `list_data_sources`), `data.excluded` is
      removed prior to scanning because TOOL_CONTRACT.md §7 specifies
      `excluded: [{"product": "ahrf", ...}]`.
    - When `allow_withheld_warning=True` (for `search_measures`), `warnings` may name
      HRSA AHRF in an explanatory withheld-content warning (Amendment 1 §7), while
      `data` and `sources` must still never contain 'ahrf'.
    """
    target = payload
    if isinstance(payload, dict) and (allow_excluded_list or allow_withheld_warning):
        target = copy.deepcopy(payload)
        if allow_excluded_list and isinstance(target.get("data"), dict):
            target["data"].pop("excluded", None)
        if allow_withheld_warning:
            warnings = target.pop("warnings", None)
            if isinstance(warnings, list):
                for w in warnings:
                    if isinstance(w, str) and "ahrf" in w.lower():
                        w_low = w.lower()
                        if not any(
                            phrase in w_low
                            for phrase in ("not available", "withheld", "excluded", "redistribution")
                        ):
                            return [
                                f"Warning mentions 'ahrf' without explaining that it is withheld/unavailable: {w!r}"
                            ]
    serialized = json.dumps(target, ensure_ascii=False)
    if "ahrf" in serialized.lower():
        return ["Found forbidden 'ahrf' reference in serialized response output"]
    return []


def measure_response_bytes(structured_content: Any) -> int:
    """Measure response size per Amendment 1 §1."""
    return len(
        json.dumps(structured_content, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )


def check_response_size(
    payload: Any,
    max_bytes: int = MAX_RESPONSE_BYTES,
) -> list[str]:
    """Verify serialized response size is under max_bytes (50,000 bytes, Amendment 1 §1)."""
    serialized_bytes = measure_response_bytes(payload)
    if serialized_bytes > max_bytes:
        return [f"Serialized response size {serialized_bytes} bytes exceeds cap of {max_bytes} bytes"]
    return []


def _collect_dict_keys(obj: Any, path: str = "") -> list[tuple[str, str]]:
    """Return (path, key) for every dictionary key in obj."""
    found: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key_str = str(k)
            cur = f"{path}.{key_str}" if path else key_str
            found.append((cur, key_str))
            found.extend(_collect_dict_keys(v, cur))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            found.extend(_collect_dict_keys(item, f"{path}[{idx}]"))
    return found


def check_forbidden_words(payload: Any) -> list[str]:
    """Check that 'best', 'worst', or 'score' do not appear in keys or warnings."""
    failures: list[str] = []
    for key_path, key_name in _collect_dict_keys(payload):
        tokens = [
            t.lower()
            for t in re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key_name).replace("-", "_").split("_")
            if t
        ]
        bad_tokens = sorted(set(tokens) & FORBIDDEN_KEY_TOKENS)
        if bad_tokens or FORBIDDEN_WORDS_RE.search(key_name):
            failures.append(f"Forbidden word in key '{key_path}'")

    if isinstance(payload, dict):
        warnings = payload.get("warnings")
        if isinstance(warnings, list):
            for idx, w in enumerate(warnings):
                if isinstance(w, str) and FORBIDDEN_WORDS_RE.search(w):
                    failures.append(f"Forbidden word in warnings[{idx}]: {w!r}")
    return failures


def check_no_change_keys(data: Any) -> list[str]:
    """Check that no key named like change, trend, difference, or pct_change appears anywhere in data."""
    failures: list[str] = []
    for key_path, key_name in _collect_dict_keys(data):
        normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key_name).replace("-", "_").lower()
        tokens = [t for t in normalized.split("_") if t]
        if (
            set(tokens) & FORBIDDEN_CHANGE_TOKENS
            or "pct_change" in normalized
            or "percent_change" in normalized
            or FORBIDDEN_CHANGE_KEY_RE.search(normalized)
        ):
            failures.append(f"Forbidden change/trend key in data at '{key_path}'")
    return failures


def check_competition_positions(
    with_value_rows: list[dict[str, Any]],
    sort_mode: str = "value_desc",
) -> list[str]:
    """Check sort order and position rules on with_value rows (Amendment 1 §3).

    - When sort_mode is 'value_desc' or 'value_asc': every row in with_value must carry
      'position' using competition numbering (1, 2, 2, 4).
    - When sort_mode is 'geoid': rows must be sorted by area.geoid and must NOT carry 'position'.
    """
    failures: list[str] = []
    values: list[float | int] = []
    actual_positions: list[int] = []
    geoids: list[str] = []

    for idx, row in enumerate(with_value_rows):
        val = row.get("value")
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            failures.append(f"with_value[{idx}] has null or non-numeric value: {val!r}")
            return failures
        values.append(val)
        area = row.get("area") or {}
        geoids.append(str(area.get("geoid", "")))

        if sort_mode in ("value_desc", "value_asc"):
            pos = row.get("position")
            if not isinstance(pos, int) or isinstance(pos, bool) or pos < 1:
                failures.append(f"with_value[{idx}] has invalid position: {pos!r}")
                return failures
            actual_positions.append(pos)
        elif sort_mode == "geoid":
            if "position" in row:
                failures.append(
                    f"with_value[{idx}] must not have 'position' when sort='geoid' (got {row.get('position')!r})"
                )
                return failures

    if sort_mode == "value_desc":
        for i in range(1, len(values)):
            if values[i] > values[i - 1]:
                failures.append(
                    f"with_value not sorted descending at index {i}: {values[i]} > {values[i - 1]}"
                )
                break
        expected_positions = compute_competition_positions(values)
        if actual_positions != expected_positions:
            failures.append(
                f"Competition positions mismatch for value_desc: got {actual_positions[:10]}, "
                f"expected {expected_positions[:10]}"
            )
    elif sort_mode == "value_asc":
        for i in range(1, len(values)):
            if values[i] < values[i - 1]:
                failures.append(
                    f"with_value not sorted ascending at index {i}: {values[i]} < {values[i - 1]}"
                )
                break
        expected_positions = compute_competition_positions(values)
        if actual_positions != expected_positions:
            failures.append(
                f"Competition positions mismatch for value_asc: got {actual_positions[:10]}, "
                f"expected {expected_positions[:10]}"
            )
    elif sort_mode == "geoid":
        for i in range(1, len(geoids)):
            if geoids[i] < geoids[i - 1]:
                failures.append(
                    f"with_value not sorted by geoid at index {i}: {geoids[i]!r} < {geoids[i - 1]!r}"
                )
                break
    else:
        failures.append(f"Unknown sort_mode {sort_mode!r}")

    return failures


def check_without_value_rows(without_value_rows: list[dict[str, Any]]) -> list[str]:
    """Check that every row in without_value has null value, no position, status/status_text, and GEOID order."""
    failures: list[str] = []
    prev_geoid = ""
    for idx, row in enumerate(without_value_rows):
        if row.get("value") is not None:
            failures.append(f"without_value[{idx}] has non-null value: {row.get('value')!r}")
        if "position" in row:
            failures.append(f"without_value[{idx}] must not contain 'position': {row.get('position')!r}")
        status = row.get("status")
        status_text = row.get("status_text")
        if not status or not isinstance(status, str):
            failures.append(f"without_value[{idx}] missing status")
        if status == "available":
            failures.append(f"without_value[{idx}] has status 'available' despite null value")
        if not status_text or not isinstance(status_text, str):
            failures.append(f"without_value[{idx}] missing status_text")
        area = row.get("area") or {}
        geoid = str(area.get("geoid", ""))
        if prev_geoid and geoid < prev_geoid:
            failures.append(
                f"without_value not in GEOID order at index {idx}: {geoid!r} < {prev_geoid!r}"
            )
        prev_geoid = geoid
    return failures


def check_value_row_shape(row: dict[str, Any]) -> list[str]:
    """Verify a full value row in `get_area_values` or `get_measure_over_time` conforms to Amendment 1 & 2."""
    failures: list[str] = []
    if not isinstance(row, dict):
        return [f"Value row is not a dict: {type(row).__name__}"]

    if "position" in row:
        failures.append(f"Full value row must not contain 'position' (got {row.get('position')!r})")

    missing = VALUE_ROW_REQUIRED_KEYS - set(row.keys())
    if missing:
        failures.append(f"Value row missing required keys: {sorted(missing)}")

    extra = set(row.keys()) - VALUE_ROW_REQUIRED_KEYS
    if extra:
        failures.append(f"Value row has unexpected extra keys: {sorted(extra)}")

    measure_key = row.get("measure_key")
    if not isinstance(measure_key, str) or ":" not in measure_key:
        failures.append(f"Invalid measure_key {measure_key!r}")
        product = ""
    else:
        product = measure_key.split(":", 1)[0]
        if product == "ahrf":
            failures.append(f"Excluded product 'ahrf' found in measure_key {measure_key!r}")

    area = row.get("area")
    if not isinstance(area, dict) or not area.get("level") or not area.get("geoid"):
        failures.append(f"Invalid area object on row {measure_key!r}: {area!r}")

    status = row.get("status")
    status_text = row.get("status_text")
    if not isinstance(status, str) or not status.strip():
        failures.append(f"Row {measure_key!r} missing status")
    if not isinstance(status_text, str) or not status_text.strip():
        failures.append(f"Row {measure_key!r} missing status_text")

    note_val = row.get("note")
    if note_val is not None and not isinstance(note_val, str):
        failures.append(f"Row {measure_key!r} note must be str or None, got {note_val!r}")

    citation = row.get("citation")
    if not isinstance(citation, str) or not citation.startswith("Source: ") or "release " not in citation:
        failures.append(f"Row {measure_key!r} has invalid citation format: {citation!r}")
    elif isinstance(row.get("period"), str) and row["period"] not in citation:
        failures.append(f"Row {measure_key!r} citation {citation!r} does not contain period {row['period']!r}")

    uncertainty = row.get("uncertainty")
    if not isinstance(uncertainty, dict) or "kind" not in uncertainty:
        failures.append(f"Row {measure_key!r} missing uncertainty.kind: {uncertainty!r}")
    elif product in SPEC_UNCERTAINTY:
        expected_kind = SPEC_UNCERTAINTY[product]
        if uncertainty.get("kind") != expected_kind:
            failures.append(
                f"Row {measure_key!r} uncertainty.kind={uncertainty.get('kind')!r}, "
                f"expected {expected_kind!r} for product {product!r}"
            )

    return failures


def check_across_areas_measure_meta(measure_meta: Any) -> list[str]:
    """Verify `data.measure` in `get_measure_across_areas` carries shared fields (Amendment 1 §2, §2a & Amendment 2 §3)."""
    failures: list[str] = []
    if not isinstance(measure_meta, dict):
        return [f"data.measure must be a dict, got {type(measure_meta).__name__}"]

    missing = ACROSS_AREAS_MEASURE_REQUIRED_KEYS - set(measure_meta.keys())
    if missing:
        failures.append(f"data.measure missing required shared keys: {sorted(missing)}")

    allowed = ACROSS_AREAS_MEASURE_REQUIRED_KEYS | ACROSS_AREAS_MEASURE_OPTIONAL_KEYS
    extra = set(measure_meta.keys()) - allowed
    if extra:
        failures.append(f"data.measure has unexpected extra keys: {sorted(extra)}")

    measure_key = measure_meta.get("measure_key")
    product = ""
    if not isinstance(measure_key, str) or ":" not in measure_key:
        failures.append(f"data.measure has invalid measure_key: {measure_key!r}")
    else:
        product = measure_key.split(":", 1)[0]
        if product == "ahrf":
            failures.append(f"Excluded product 'ahrf' in data.measure.measure_key: {measure_key!r}")

    note_val = measure_meta.get("note")
    if note_val is not None and not isinstance(note_val, str):
        failures.append(f"data.measure.note must be str or None, got {note_val!r}")

    citation = measure_meta.get("citation")
    if not isinstance(citation, str) or not citation.startswith("Source: ") or "release " not in citation:
        failures.append(f"data.measure has invalid citation format: {citation!r}")

    for str_key in (
        "label",
        "period",
        "population",
        "value_type",
        "release_id",
        "uncertainty_kind",
        "uncertainty_label",
    ):
        val = measure_meta.get(str_key)
        if not isinstance(val, str) or not val.strip():
            failures.append(f"data.measure.{str_key} must be a non-empty string, got {val!r}")

    unc_kind = measure_meta.get("uncertainty_kind")
    if isinstance(unc_kind, str) and unc_kind not in ("ci95", "moe90", "none"):
        failures.append(f"data.measure.uncertainty_kind must be 'ci95', 'moe90', or 'none', got {unc_kind!r}")
    elif product in SPEC_UNCERTAINTY and unc_kind != SPEC_UNCERTAINTY[product]:
        failures.append(
            f"data.measure.uncertainty_kind={unc_kind!r}, expected {SPEC_UNCERTAINTY[product]!r} for product {product!r}"
        )

    return failures


def check_compact_value_row_shape(
    row: dict[str, Any],
    *,
    product: str = "",
    uncertainty_kind: str = "",
    require_position: bool = False,
    allow_boundary_vintage: bool = False,
) -> list[str]:
    """Verify a compact row in `get_measure_across_areas` (Amendment 1 §2, §2a, §3)."""
    failures: list[str] = []
    if not isinstance(row, dict):
        return [f"Compact value row is not a dict: {type(row).__name__}"]

    required = COMPACT_ROW_REQUIRED_KEYS | ({"position"} if require_position else set())
    missing = required - set(row.keys())
    if missing:
        failures.append(f"Compact row missing required keys: {sorted(missing)}")

    if not require_position and "position" in row:
        failures.append(f"Compact row must not contain 'position' (got {row.get('position')!r})")

    if "notes" in row:
        notes_val = row.get("notes")
        if not isinstance(notes_val, dict) or len(notes_val) == 0:
            failures.append(f"Compact row must omit 'notes' when empty (got {notes_val!r})")

    allowed = (
        COMPACT_ROW_REQUIRED_KEYS
        | ({"position"} if require_position else set())
        | ({"notes"} if "notes" in row else set())
        | ({"boundary_vintage"} if allow_boundary_vintage else set())
    )
    extra = set(row.keys()) - allowed
    if extra:
        failures.append(f"Compact row has unexpected extra keys (must be in data.measure): {sorted(extra)}")

    area = row.get("area")
    if not isinstance(area, dict) or not area.get("geoid"):
        failures.append(f"Invalid area object on compact row: {area!r}")

    status = row.get("status")
    status_text = row.get("status_text")
    if not isinstance(status, str) or not status.strip():
        failures.append("Compact row missing status")
    if not isinstance(status_text, str) or not status_text.strip():
        failures.append("Compact row missing status_text")

    uncertainty = row.get("uncertainty")
    if not isinstance(uncertainty, dict):
        failures.append(f"Compact row uncertainty must be a dict: {uncertainty!r}")
    else:
        repeated_unc = {"kind", "label"} & set(uncertainty.keys())
        if repeated_unc:
            failures.append(
                f"Compact row uncertainty must not repeat {sorted(repeated_unc)} (moved to data.measure): {uncertainty!r}"
            )
        eff_kind = uncertainty_kind or SPEC_UNCERTAINTY.get(product, "")
        if eff_kind == "ci95":
            expected_unc_keys: set[str] | None = {"low", "high"}
        elif eff_kind == "moe90":
            expected_unc_keys = {"moe"}
        elif eff_kind == "none":
            expected_unc_keys = set()
        else:
            expected_unc_keys = None

        if expected_unc_keys is not None and set(uncertainty.keys()) != expected_unc_keys:
            failures.append(
                f"Compact row uncertainty keys {sorted(uncertainty.keys())} do not match "
                f"expected interval keys {sorted(expected_unc_keys)} for uncertainty_kind={eff_kind!r}"
            )

    return failures


def check_over_time_response(payload: Any) -> list[str]:
    """Verify `get_measure_over_time` structure, ascending periods, warnings, and no-change keys (Amendment 2 §5)."""
    failures: list[str] = []
    if not isinstance(payload, dict):
        return [f"Payload must be a dict, got {type(payload).__name__}"]

    data = payload.get("data")
    warnings = payload.get("warnings")
    if not isinstance(data, dict):
        return ["data must be a dict"]
    if not isinstance(warnings, list):
        return ["warnings must be a list"]

    failures.extend(check_no_change_keys(data))

    area = data.get("area")
    if not isinstance(area, dict) or not area.get("level") or not area.get("geoid"):
        failures.append(f"get_measure_over_time data.area invalid: {area!r}")

    measure = data.get("measure")
    if not isinstance(measure, dict):
        failures.append("get_measure_over_time data.measure must be a dict")
    else:
        if "period" in measure:
            failures.append("get_measure_over_time data.measure must not carry 'period'")
        for req_k in ("measure_key", "label"):
            if not isinstance(measure.get(req_k), str) or not measure[req_k].strip():
                failures.append(f"get_measure_over_time data.measure.{req_k} missing")

    unavailable = data.get("unavailable_periods")
    if not isinstance(unavailable, list):
        failures.append("get_measure_over_time data.unavailable_periods must be a list")
    else:
        for idx, item in enumerate(unavailable):
            if not isinstance(item, dict) or not item.get("period") or not item.get("reason"):
                failures.append(
                    f"get_measure_over_time unavailable_periods[{idx}] must have period and reason: {item!r}"
                )

    series = data.get("series")
    if not isinstance(series, list) or not series:
        failures.append("get_measure_over_time data.series must be a non-empty list")
    else:
        periods: list[str] = []
        vintages: set[str] = set()
        for idx, row in enumerate(series):
            row_errs = check_value_row_shape(row)
            if row_errs:
                failures.extend([f"series[{idx}]: {e}" for e in row_errs])
            if isinstance(row, dict):
                p = row.get("period")
                if not isinstance(p, str) or not p.strip():
                    failures.append(f"series[{idx}] missing period")
                else:
                    periods.append(p)
                for req_f in ("period", "note", "release_id", "boundary_vintage", "citation"):
                    if req_f not in row:
                        failures.append(f"series[{idx}] missing required key {req_f!r}")
                for non_empty_f in ("release_id", "boundary_vintage", "citation"):
                    val = row.get(non_empty_f)
                    if not isinstance(val, str) or not val.strip():
                        failures.append(f"series[{idx}].{non_empty_f} must be a non-empty string")
                bv = row.get("boundary_vintage")
                if isinstance(bv, str) and bv:
                    vintages.add(bv)

        if periods != sorted(periods):
            failures.append(f"series periods are not in ascending order: {periods!r}")
        if len(periods) != len(set(periods)):
            failures.append(f"series periods are not unique: {periods!r}")

        if len(vintages) > 1:
            if not any("boundary vintage" in str(w).lower() for w in warnings):
                failures.append(
                    f"series has multiple boundary vintages {sorted(vintages)}, "
                    f"but warnings has no boundary-vintage caution: {warnings!r}"
                )

    if not any(OVER_TIME_WARNING in str(w) for w in warnings):
        failures.append(f"get_measure_over_time missing fixed warning {OVER_TIME_WARNING!r}")

    return failures


def check_search_measures_periods(measures_list: Any) -> list[str]:
    """Verify every item in `search_measures` `data.measures` carries `periods` with current period first (Amendment 2 §6)."""
    failures: list[str] = []
    if not isinstance(measures_list, list):
        return ["search_measures data.measures must be a list"]
    for idx, item in enumerate(measures_list):
        if not isinstance(item, dict):
            failures.append(f"search_measures measures[{idx}] is not a dict")
            continue
        mk = item.get("measure_key", f"index {idx}")
        cur_period = item.get("period")
        periods = item.get("periods")
        if not isinstance(periods, list) or not periods:
            failures.append(f"search_measures[{mk}] missing non-empty 'periods' list: {periods!r}")
            continue
        if not all(isinstance(p, str) and p.strip() for p in periods):
            failures.append(f"search_measures[{mk}] 'periods' must contain non-empty strings: {periods!r}")
            continue
        if len(periods) != len(set(periods)):
            failures.append(f"search_measures[{mk}] 'periods' contains duplicates: {periods!r}")
        if cur_period and periods[0] != cur_period:
            failures.append(
                f"search_measures[{mk}] periods[0]={periods[0]!r} does not equal current period {cur_period!r}"
            )
    return failures


def check_measure_details_periods(measures_list: Any) -> list[str]:
    """Verify every item in `get_measure_details` `data.measures` carries full `periods` metadata (Amendment 2 §6)."""
    failures: list[str] = []
    if not isinstance(measures_list, list):
        return ["get_measure_details data.measures must be a list"]
    for idx, item in enumerate(measures_list):
        if not isinstance(item, dict):
            failures.append(f"get_measure_details measures[{idx}] is not a dict")
            continue
        mk = item.get("measure_key", f"index {idx}")
        cur_period = item.get("period")
        periods = item.get("periods")
        if not isinstance(periods, list) or not periods:
            failures.append(f"get_measure_details[{mk}] missing non-empty 'periods' list: {periods!r}")
            continue
        seen_periods: set[str] = set()
        for p_idx, p_entry in enumerate(periods):
            if not isinstance(p_entry, dict):
                failures.append(f"get_measure_details[{mk}] periods[{p_idx}] is not a dict")
                continue
            missing = MEASURE_PERIOD_ENTRY_REQUIRED_KEYS - set(p_entry.keys())
            if missing:
                failures.append(
                    f"get_measure_details[{mk}] periods[{p_idx}] missing required keys: {sorted(missing)}"
                )
            p_str = p_entry.get("period")
            if not isinstance(p_str, str) or not p_str.strip():
                failures.append(f"get_measure_details[{mk}] periods[{p_idx}].period must be non-empty string")
            elif p_str in seen_periods:
                failures.append(f"get_measure_details[{mk}] repeats period {p_str!r}")
            else:
                seen_periods.add(p_str)
            if not isinstance(p_entry.get("available"), bool):
                failures.append(f"get_measure_details[{mk}] periods[{p_idx}].available must be bool")
            if not isinstance(p_entry.get("current"), bool):
                failures.append(f"get_measure_details[{mk}] periods[{p_idx}].current must be bool")
            if p_idx > 0 and p_entry.get("note") is not None and not isinstance(p_entry.get("note"), str):
                failures.append(f"get_measure_details[{mk}] periods[{p_idx}].note must be str or None")
        if isinstance(periods[0], dict):
            if periods[0].get("current") is not True:
                failures.append(f"get_measure_details[{mk}] periods[0].current must be True")
            if cur_period and periods[0].get("period") != cur_period:
                failures.append(
                    f"get_measure_details[{mk}] periods[0].period={periods[0].get('period')!r} != {cur_period!r}"
                )
    return failures


def check_list_data_sources_notes(
    notes: Any,
    expected_product_lines: list[str] | None = None,
) -> list[str]:
    """Verify `list_data_sources` `data.notes` lists per-product period ranges and removes the old one-period claim (Amendment 2 §7)."""
    failures: list[str] = []
    if not isinstance(notes, list) or not notes or not all(isinstance(n, str) for n in notes):
        return [f"list_data_sources data.notes must be a non-empty list of strings, got {notes!r}"]

    joined_low = " ".join(notes).lower()
    if "no time series" in joined_low or "one period per measure" in joined_low or "one published period" in joined_low:
        failures.append(f"list_data_sources data.notes still contains superseded one-period text: {notes!r}")

    colon_lines = [n for n in notes if ":" in n and not n.startswith("Area context")]
    if len(colon_lines) < len(PUBLIC_PRODUCTS):
        failures.append(
            f"list_data_sources data.notes expected at least {len(PUBLIC_PRODUCTS)} per-product period lines, "
            f"found {len(colon_lines)}: {notes!r}"
        )

    if expected_product_lines:
        notes_set = set(notes)
        for exp_line in expected_product_lines:
            if exp_line not in notes_set:
                failures.append(
                    f"list_data_sources data.notes missing expected product period line {exp_line!r} (got {notes!r})"
                )

    return failures


def _normalize_recipient_sort_key(state: Any, name: Any) -> tuple[bool, str, str]:
    """Return a locale-independent sort key matching Postgres ORDER BY state NULLS LAST, recipient_name."""
    st = str(state).strip().upper() if isinstance(state, str) and state.strip() else None
    nm = str(name or "")
    alnum = re.sub(r"[^a-z0-9]+", "", nm.lower())
    return (st is None, st or "", alnum)


def check_funding_forbidden_words(payload: Any) -> list[str]:
    """Check evaluative words in funding keys/warnings while allowing contract `best_available*` keys."""
    failures: list[str] = []
    for key_path, key_name in _collect_dict_keys(payload):
        if key_name in FUNDING_ALLOWED_BEST_KEYS:
            continue
        tokens = [
            t.lower()
            for t in re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key_name).replace("-", "_").split("_")
            if t
        ]
        bad_tokens = sorted(set(tokens) & FORBIDDEN_KEY_TOKENS)
        if bad_tokens or FORBIDDEN_WORDS_RE.search(key_name):
            failures.append(f"Forbidden word in funding key '{key_path}'")

    if isinstance(payload, dict):
        warnings = payload.get("warnings")
        if isinstance(warnings, list):
            for idx, w in enumerate(warnings):
                if isinstance(w, str) and FORBIDDEN_WORDS_RE.search(w):
                    failures.append(f"Forbidden word in warnings[{idx}]: {w!r}")
    return failures


def check_no_area_sources_in_funding(sources: Any) -> list[str]:
    """Verify funding `sources` contains valid funding source records and zero area-product sources."""
    failures: list[str] = []
    if not isinstance(sources, list) or not sources:
        return [f"Funding response must have non-empty sources list, got {sources!r}"]
    seen_ids: set[str] = set()
    for idx, src in enumerate(sources):
        if not isinstance(src, dict):
            failures.append(f"sources[{idx}] must be a dict, got {type(src).__name__}")
            continue
        if "dataset_id" in src or src.get("product") in AREA_SOURCE_PRODUCTS:
            failures.append(f"Area-product source leaked into funding sources[{idx}]: {src!r}")
            continue
        missing = DATASET_V1_SOURCE_KEYS - set(src.keys())
        if missing:
            failures.append(f"Funding sources[{idx}] missing required keys: {sorted(missing)}")
        sid = src.get("id")
        if sid not in FUNDING_SOURCE_IDS:
            failures.append(f"Funding sources[{idx}] has unknown funding source id {sid!r}")
        else:
            seen_ids.add(sid)
        citation = src.get("citation")
        if not isinstance(citation, str) or not citation.startswith("Source: "):
            failures.append(f"Funding sources[{idx}] invalid citation: {citation!r}")
    if not seen_ids:
        failures.append("Funding sources contained no recognized funding source ids")
    return failures


def check_no_funding_sources_in_area(sources: Any, interpretation_rules: Any = None) -> list[str]:
    """Verify area responses never contain funding sources or funding interpretation rules."""
    failures: list[str] = []
    if isinstance(sources, list):
        for idx, src in enumerate(sources):
            if not isinstance(src, dict):
                continue
            sid = src.get("id")
            pub = str(src.get("publisher") or "").lower()
            if sid in FUNDING_SOURCE_IDS or "usaspending" in pub or "taggs" in pub:
                failures.append(f"Funding source leaked into area sources[{idx}]: {src!r}")
    if isinstance(interpretation_rules, list):
        norm_actual = {_norm_rule(r) for r in interpretation_rules if isinstance(r, str)}
        for f_rule in FUNDING_INTERPRETATION_RULES:
            if _norm_rule(f_rule) in norm_actual:
                failures.append(f"Funding interpretation rule leaked into area response: {f_rule!r}")
    return failures


def check_funding_fiscal_years_ordered(fy_rows: Any, label: str = "fiscal_years") -> list[str]:
    """Verify a fiscal_years list has strictly ascending, unique integer fiscal_year values."""
    failures: list[str] = []
    if not isinstance(fy_rows, list):
        return [f"{label} must be a list, got {type(fy_rows).__name__}"]
    prev_fy: int | None = None
    for idx, item in enumerate(fy_rows):
        if not isinstance(item, dict):
            failures.append(f"{label}[{idx}] must be a dict")
            continue
        fy = item.get("fiscal_year")
        if not isinstance(fy, int) or isinstance(fy, bool):
            failures.append(f"{label}[{idx}].fiscal_year must be int, got {fy!r}")
            continue
        if prev_fy is not None and fy <= prev_fy:
            failures.append(f"{label} not strictly ascending at index {idx}: {fy} <= {prev_fy}")
            break
        prev_fy = fy
    return failures


def check_funding_recipients_sorted(recipients: Any, label: str = "recipients") -> list[str]:
    """Verify recipients (full profile or compact listing) are sorted by state (NULLS LAST), then name."""
    failures: list[str] = []
    if not isinstance(recipients, list):
        return [f"{label} must be a list, got {type(recipients).__name__}"]
    prev_key: tuple[bool, str, str] | None = None
    prev_desc = ""
    for idx, rec in enumerate(recipients):
        if not isinstance(rec, dict):
            failures.append(f"{label}[{idx}] must be a dict")
            continue
        if isinstance(rec.get("address"), dict):
            state = rec["address"].get("state")
        else:
            state = rec.get("state")
        name = rec.get("recipient_name")
        cur_key = _normalize_recipient_sort_key(state, name)
        cur_desc = f"({state!r}, {name!r})"
        if prev_key is not None and cur_key < prev_key:
            failures.append(f"{label} out of (state, name) order at index {idx}: {prev_desc} -> {cur_desc}")
            break
        prev_key = cur_key
        prev_desc = cur_desc
    return failures


def check_funding_no_subawards_added(data: Any) -> list[str]:
    """Verify prime obligations and sub-award amounts are never combined into one field."""
    failures: list[str] = []
    for key_path, key_name in _collect_dict_keys(data):
        if FORBIDDEN_COMBINED_SUBAWARD_KEY_RE.search(key_name):
            failures.append(f"Forbidden combined prime+subaward key '{key_path}'")
    if isinstance(data, dict):
        nofo = data.get("nofo")
        sub = data.get("subawards")
        if isinstance(nofo, dict) and isinstance(sub, dict):
            summary = sub.get("summary") if isinstance(sub.get("summary"), dict) else sub
            sub_amt = summary.get("reported_amount")
            best_tot = nofo.get("best_available_total")
            fys = nofo.get("fiscal_years")
            if (
                isinstance(sub_amt, (int, float))
                and sub_amt > 0
                and isinstance(best_tot, (int, float))
                and isinstance(fys, list)
            ):
                acc_vals = [x.get("account_obligation") for x in fys if isinstance(x, dict) and isinstance(x.get("account_obligation"), (int, float))]
                if acc_vals:
                    prime_sum = round(sum(acc_vals), 2)
                    if abs(best_tot - (prime_sum + sub_amt)) < 0.05 and abs(best_tot - prime_sum) > 0.05:
                        failures.append(
                            f"nofo.best_available_total ({best_tot}) appears to add subawards ({sub_amt}) to prime ({prime_sum})"
                        )
    return failures


def _check_recipient_null_vs_zero(rec: dict[str, Any], label: str) -> list[str]:
    """Verify null money fields in a recipient profile are never coerced to 0 when no source rows exist."""
    failures: list[str] = []
    totals = rec.get("totals")
    fys = rec.get("fiscal_years")
    if not isinstance(totals, dict) or not isinstance(fys, list):
        return failures
    for field in ("account_obligation", "award_obligation", "taggs_amount"):
        non_null_vals = [
            x.get(field) for x in fys if isinstance(x, dict) and x.get(field) is not None
        ]
        tot_val = totals.get(field)
        if not non_null_vals:
            if tot_val is not None:
                failures.append(
                    f"{label}.totals.{field} is {tot_val!r} despite all fiscal_years.{field} being null (null must not be written as 0)"
                )
        else:
            if tot_val is None:
                failures.append(
                    f"{label}.totals.{field} is null despite non-null fiscal_years.{field} rows"
                )
            elif isinstance(tot_val, (int, float)) and not isinstance(tot_val, bool):
                expected_sum = round(sum(float(v) for v in non_null_vals), 2)
                if abs(float(tot_val) - expected_sum) > 0.02:
                    failures.append(
                        f"{label}.totals.{field}={tot_val} != sum of fiscal_years ({expected_sum})"
                    )
    return failures


def check_funding_envelope(
    payload: Any,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> list[str]:
    """Run global Amendment 3 / Plan checks on a funding MCP tool response."""
    failures: list[str] = []
    if not isinstance(payload, dict):
        return [f"Response is not a dict: {type(payload).__name__}"]

    for req_key in ("data", "sources", "interpretation_rules", "warnings"):
        if req_key not in payload:
            failures.append(f"Response envelope missing top-level key {req_key!r}")
    if failures:
        return failures

    if not isinstance(payload["data"], dict):
        failures.append("'data' must be a dict")
    if not isinstance(payload["sources"], list):
        failures.append("'sources' must be a list")
    if not isinstance(payload["interpretation_rules"], list):
        failures.append("'interpretation_rules' must be a list")
    if not isinstance(payload["warnings"], list):
        failures.append("'warnings' must be a list")
    if failures:
        return failures

    failures.extend(check_no_ahrf(payload))
    failures.extend(check_response_size(payload))
    failures.extend(check_funding_forbidden_words(payload))
    failures.extend(check_no_area_sources_in_funding(payload["sources"]))

    norm_actual_rules = {_norm_rule(r) for r in payload["interpretation_rules"] if isinstance(r, str)}
    for expected_rule in FUNDING_INTERPRETATION_RULES:
        if _norm_rule(expected_rule) not in norm_actual_rules:
            failures.append(f"Missing funding interpretation rule: {expected_rule!r}")
    if len(payload["interpretation_rules"]) != len(FUNDING_INTERPRETATION_RULES):
        failures.append(
            f"Expected exactly {len(FUNDING_INTERPRETATION_RULES)} funding interpretation_rules, "
            f"got {len(payload['interpretation_rules'])}"
        )
    for area_rule in GENERAL_INTERPRETATION_RULES:
        if _norm_rule(area_rule) in norm_actual_rules:
            failures.append(f"Area interpretation rule leaked into funding response: {area_rule!r}")

    data = payload["data"]
    args = arguments or {}

    dataset_url = data.get("dataset_url")
    if (
        not isinstance(dataset_url, str)
        or not (dataset_url.startswith("http://") or dataset_url.startswith("https://"))
        or "/funding/nofo/" not in dataset_url
        or ".json?subawards=" not in dataset_url
    ):
        failures.append(f"{tool_name} missing valid absolute data.dataset_url: {dataset_url!r}")

    if tool_name == "get_nofo_overview":
        for req_k in ("nofo", "aggregates", "subawards", "caveats", "dataset_url"):
            if req_k not in data:
                failures.append(f"get_nofo_overview data missing key {req_k!r}")
        nofo = data.get("nofo")
        if isinstance(nofo, dict):
            missing_n = DATASET_V1_NOFO_KEYS - set(nofo.keys())
            if missing_n:
                failures.append(f"get_nofo_overview data.nofo missing keys: {sorted(missing_n)}")
            failures.extend(check_funding_fiscal_years_ordered(nofo.get("fiscal_years"), "data.nofo.fiscal_years"))
        agg = data.get("aggregates")
        if isinstance(agg, dict):
            missing_a = DATASET_V1_AGGREGATE_KEYS - set(agg.keys())
            if missing_a:
                failures.append(f"get_nofo_overview data.aggregates missing keys: {sorted(missing_a)}")
        inc_sub = bool(args.get("include_subawards", False))
        if inc_sub:
            sub = data.get("subawards")
            if not isinstance(sub, dict):
                failures.append("get_nofo_overview with include_subawards=True must return dict data.subawards")
            else:
                missing_s = DATASET_V1_SUBAWARD_SUMMARY_KEYS - set(sub.keys())
                if missing_s:
                    failures.append(f"get_nofo_overview data.subawards missing keys: {sorted(missing_s)}")
        else:
            if data.get("subawards") is not None:
                failures.append("get_nofo_overview with include_subawards=False must have data.subawards=None")
        failures.extend(check_funding_no_subawards_added(data))

    elif tool_name == "list_nofo_recipients":
        for req_k in ("nofo_key", "fon_display", "total", "offset", "limit", "recipients", "dataset_url"):
            if req_k not in data:
                failures.append(f"list_nofo_recipients data missing key {req_k!r}")
        recs = data.get("recipients")
        if isinstance(recs, list):
            failures.extend(check_funding_recipients_sorted(recs, "data.recipients"))
            for idx, r in enumerate(recs):
                if not isinstance(r, dict):
                    failures.append(f"data.recipients[{idx}] must be a dict")
                    continue
                missing_r = COMPACT_RECIPIENT_REQUIRED_KEYS - set(r.keys())
                if missing_r:
                    failures.append(f"data.recipients[{idx}] missing keys: {sorted(missing_r)}")
                    break

    elif tool_name == "get_recipient_funding":
        for req_k in ("nofo_key", "recipient", "dataset_url"):
            if req_k not in data:
                failures.append(f"get_recipient_funding data missing key {req_k!r}")
        rec = data.get("recipient")
        if isinstance(rec, dict):
            missing_r = DATASET_V1_RECIPIENT_KEYS - set(rec.keys())
            if missing_r:
                failures.append(f"get_recipient_funding data.recipient missing keys: {sorted(missing_r)}")
            failures.extend(check_funding_fiscal_years_ordered(rec.get("fiscal_years"), "data.recipient.fiscal_years"))
            failures.extend(_check_recipient_null_vs_zero(rec, "data.recipient"))

    return failures


def check_nofo_dataset_v1(
    dataset: Any,
    *,
    expect_subawards: bool = True,
    expected_dataset: dict[str, Any] | None = None,
) -> list[str]:
    """Validate the full `chip.nofo_recipient_profile.v1` dataset contract."""
    failures: list[str] = []
    if not isinstance(dataset, dict):
        return [f"Dataset must be a JSON object, got {type(dataset).__name__}"]

    missing_top = DATASET_V1_TOP_KEYS - set(dataset.keys())
    if missing_top:
        failures.append(f"Dataset missing top-level keys: {sorted(missing_top)}")
    if dataset.get("schema_version") != "chip.nofo_recipient_profile.v1":
        failures.append(f"Unexpected schema_version: {dataset.get('schema_version')!r}")

    build = dataset.get("build")
    if not isinstance(build, dict):
        failures.append("Dataset 'build' must be a dict")
    else:
        missing_b = DATASET_V1_BUILD_KEYS - set(build.keys())
        if missing_b:
            failures.append(f"Dataset 'build' missing keys: {sorted(missing_b)}")
        if build.get("method_version") != "nofo-v1":
            failures.append(f"Unexpected build.method_version: {build.get('method_version')!r}")

    failures.extend(check_no_area_sources_in_funding(dataset.get("sources")))
    failures.extend(check_no_ahrf(dataset))

    nofo = dataset.get("nofo")
    if not isinstance(nofo, dict):
        failures.append("Dataset 'nofo' must be a dict")
    else:
        missing_n = DATASET_V1_NOFO_KEYS - set(nofo.keys())
        if missing_n:
            failures.append(f"Dataset 'nofo' missing keys: {sorted(missing_n)}")
        pop = nofo.get("period_of_performance")
        if not isinstance(pop, dict) or not {"start_min", "end_max"}.issubset(pop.keys()):
            failures.append(f"Dataset nofo.period_of_performance missing start_min/end_max: {pop!r}")
        for idx, cf in enumerate(nofo.get("cfda") or []):
            if not isinstance(cf, dict) or not {"number", "title", "award_count"}.issubset(cf.keys()):
                failures.append(f"Dataset nofo.cfda[{idx}] missing keys: {cf!r}")
                break
        nofo_fys = nofo.get("fiscal_years")
        failures.extend(check_funding_fiscal_years_ordered(nofo_fys, "nofo.fiscal_years"))
        if isinstance(nofo_fys, list):
            for idx, fy_row in enumerate(nofo_fys):
                if not isinstance(fy_row, dict):
                    continue
                missing_fy = DATASET_V1_NOFO_FY_KEYS - set(fy_row.keys())
                if missing_fy:
                    failures.append(f"nofo.fiscal_years[{idx}] missing keys: {sorted(missing_fy)}")
                    break

    agg = dataset.get("aggregates")
    if not isinstance(agg, dict):
        failures.append("Dataset 'aggregates' must be a dict")
    else:
        missing_a = DATASET_V1_AGGREGATE_KEYS - set(agg.keys())
        if missing_a:
            failures.append(f"Dataset 'aggregates' missing keys: {sorted(missing_a)}")
        for lst_name, req_keys in (
            ("by_state", {"state", "recipients", "nofo_total", "other_awards_top10_total"}),
            ("by_recipient_class", {"value", "recipients", "nofo_total"}),
            ("by_recipient_type", {"value", "recipients"}),
            ("by_metro", {"value", "recipients"}),
            ("other_awards_by_opdiv", {"opdiv", "awards", "total"}),
            ("other_awards_by_aln", {"aln", "title", "awards", "total"}),
            ("top_recipients_by_other_awards", {"award_unique_key", "recipient_name", "state", "other_award_count", "other_awards_top10_total"}),
        ):
            items = agg.get(lst_name)
            if not isinstance(items, list):
                failures.append(f"aggregates.{lst_name} must be a list")
            elif items and isinstance(items[0], dict):
                miss_i = req_keys - set(items[0].keys())
                if miss_i:
                    failures.append(f"aggregates.{lst_name}[0] missing keys: {sorted(miss_i)}")

    recipients = dataset.get("recipients")
    if not isinstance(recipients, list):
        failures.append("Dataset 'recipients' must be a list")
    else:
        if isinstance(nofo, dict) and isinstance(nofo.get("award_count"), int):
            if len(recipients) != nofo["award_count"]:
                failures.append(f"len(recipients)={len(recipients)} != nofo.award_count={nofo['award_count']}")
        failures.extend(check_funding_recipients_sorted(recipients, "recipients"))

        # Track per-FY non-null recipient values to verify NOFO-level null-vs-0 consistency
        rec_fy_nonnull: dict[tuple[int, str], list[float]] = {}
        for idx, rec in enumerate(recipients):
            if not isinstance(rec, dict):
                failures.append(f"recipients[{idx}] must be a dict")
                continue
            missing_r = DATASET_V1_RECIPIENT_KEYS - set(rec.keys())
            if missing_r:
                failures.append(f"recipients[{idx}] missing keys: {sorted(missing_r)}")
                break
            parent = rec.get("parent")
            if not isinstance(parent, dict) or not {"uei", "name"}.issubset(parent.keys()):
                failures.append(f"recipients[{idx}].parent missing uei/name")
                break
            addr = rec.get("address")
            if not isinstance(addr, dict) or not DATASET_V1_ADDRESS_KEYS.issubset(addr.keys()):
                failures.append(f"recipients[{idx}].address missing keys")
                break
            cfda = rec.get("cfda")
            if not isinstance(cfda, dict) or not {"number", "title"}.issubset(cfda.keys()):
                failures.append(f"recipients[{idx}].cfda missing number/title")
                break
            rpop = rec.get("period_of_performance")
            if not isinstance(rpop, dict) or not {"start", "end"}.issubset(rpop.keys()):
                failures.append(f"recipients[{idx}].period_of_performance missing start/end")
                break
            totals = rec.get("totals")
            if not isinstance(totals, dict) or not DATASET_V1_TOTALS_KEYS.issubset(totals.keys()):
                failures.append(f"recipients[{idx}].totals missing keys")
                break
            other = rec.get("other_awards")
            if not isinstance(other, dict) or not DATASET_V1_OTHER_AWARDS_KEYS.issubset(other.keys()):
                failures.append(f"recipients[{idx}].other_awards missing keys")
                break
            for t_idx, top_item in enumerate(other.get("top") or []):
                if not isinstance(top_item, dict) or not DATASET_V1_OTHER_TOP_KEYS.issubset(top_item.keys()):
                    failures.append(f"recipients[{idx}].other_awards.top[{t_idx}] missing keys")
                    break
            r_sub = rec.get("subawards")
            if expect_subawards:
                if not isinstance(r_sub, dict) or not DATASET_V1_RECIPIENT_SUBAWARDS_KEYS.issubset(r_sub.keys()):
                    failures.append(f"recipients[{idx}].subawards must be a dict with summary keys when subawards=1")
                    break
            else:
                if r_sub is not None:
                    failures.append(f"recipients[{idx}].subawards must be null when subawards=0")
                    break

            r_fys = rec.get("fiscal_years")
            fy_errs = check_funding_fiscal_years_ordered(r_fys, f"recipients[{idx}].fiscal_years")
            if fy_errs:
                failures.extend(fy_errs)
                break
            if isinstance(r_fys, list):
                for fy_row in r_fys:
                    if not isinstance(fy_row, dict):
                        continue
                    missing_rfy = DATASET_V1_RECIPIENT_FY_KEYS - set(fy_row.keys())
                    if missing_rfy:
                        failures.append(f"recipients[{idx}].fiscal_years entry missing keys: {sorted(missing_rfy)}")
                        break
                    fy_num = fy_row.get("fiscal_year")
                    if isinstance(fy_num, int):
                        for mf in ("account_obligation", "award_obligation", "taggs_amount"):
                            val = fy_row.get(mf)
                            if val is not None:
                                rec_fy_nonnull.setdefault((fy_num, mf), []).append(float(val))

            nvz_errs = _check_recipient_null_vs_zero(rec, f"recipients[{idx}] ({rec.get('fain')})")
            if nvz_errs:
                failures.extend(nvz_errs)
                if len(failures) > 20:
                    break

        # Cross-check NOFO-level fiscal_years null-vs-0 against recipient fiscal_years
        if isinstance(nofo, dict) and isinstance(nofo.get("fiscal_years"), list):
            for fy_row in nofo["fiscal_years"]:
                if not isinstance(fy_row, dict) or not isinstance(fy_row.get("fiscal_year"), int):
                    continue
                fy_num = fy_row["fiscal_year"]
                for mf in ("account_obligation", "award_obligation", "taggs_amount"):
                    vals = rec_fy_nonnull.get((fy_num, mf), [])
                    nofo_val = fy_row.get(mf)
                    if not vals:
                        if nofo_val is not None:
                            failures.append(
                                f"nofo.fiscal_years[{fy_num}].{mf} is {nofo_val!r} despite zero recipient source rows "
                                "(null must never be written as 0)"
                            )
                    else:
                        if nofo_val is None:
                            failures.append(
                                f"nofo.fiscal_years[{fy_num}].{mf} is null despite {len(vals)} non-null recipient rows"
                            )
                        elif isinstance(nofo_val, (int, float)) and not isinstance(nofo_val, bool):
                            exp_sum = round(sum(vals), 2)
                            if abs(float(nofo_val) - exp_sum) > 0.02:
                                failures.append(
                                    f"nofo.fiscal_years[{fy_num}].{mf}={nofo_val} != sum of recipients ({exp_sum})"
                                )

    sub = dataset.get("subawards")
    if expect_subawards:
        if not isinstance(sub, dict):
            failures.append("Dataset 'subawards' must be a dict when subawards=1")
        else:
            missing_sub = DATASET_V1_SUBAWARDS_KEYS - set(sub.keys())
            if missing_sub:
                failures.append(f"Dataset 'subawards' missing keys: {sorted(missing_sub)}")
            summary = sub.get("summary")
            if not isinstance(summary, dict) or not DATASET_V1_SUBAWARD_SUMMARY_KEYS.issubset(summary.keys()):
                failures.append(f"subawards.summary missing keys: {summary!r}")
            failures.extend(check_funding_fiscal_years_ordered(sub.get("by_fiscal_year"), "subawards.by_fiscal_year"))
            for idx, item in enumerate(sub.get("by_fiscal_year") or []):
                if not isinstance(item, dict) or not DATASET_V1_SUBAWARD_FY_KEYS.issubset(item.keys()):
                    failures.append(f"subawards.by_fiscal_year[{idx}] missing keys")
                    break
            for idx, item in enumerate(sub.get("by_state") or []):
                if not isinstance(item, dict) or not DATASET_V1_SUBAWARD_STATE_KEYS.issubset(item.keys()):
                    failures.append(f"subawards.by_state[{idx}] missing keys")
                    break
            for idx, sa in enumerate(sub.get("subawardees") or []):
                if not isinstance(sa, dict) or not DATASET_V1_SUBAWARDEE_KEYS.issubset(sa.keys()):
                    failures.append(f"subawards.subawardees[{idx}] missing keys")
                    break
                if not isinstance(sa.get("address"), dict) or not DATASET_V1_ADDRESS_KEYS.issubset(sa["address"].keys()):
                    failures.append(f"subawards.subawardees[{idx}].address missing keys")
                    break
                sa_fy_errs = check_funding_fiscal_years_ordered(sa.get("fiscal_years"), f"subawards.subawardees[{idx}].fiscal_years")
                if sa_fy_errs:
                    failures.extend(sa_fy_errs)
                    break
            for idx, act in enumerate(sub.get("actions") or []):
                if not isinstance(act, dict) or not DATASET_V1_SUBAWARD_ACTION_KEYS.issubset(act.keys()):
                    failures.append(f"subawards.actions[{idx}] missing keys")
                    break
    else:
        if sub is not None:
            failures.append("Dataset 'subawards' must be null when subawards=0")

    caveats = dataset.get("caveats")
    if not isinstance(caveats, list) or not caveats or not all(isinstance(c, str) and c.strip() for c in caveats):
        failures.append("Dataset 'caveats' must be a non-empty list of strings")
    else:
        caveat_text = " ".join(caveats).lower()
        if "not additional federal funding" not in caveat_text:
            failures.append("Dataset caveats missing sub-award non-addition warning")
        if "taggs" not in caveat_text:
            failures.append("Dataset caveats missing TAGGS scope caveat")

    failures.extend(check_funding_no_subawards_added(dataset))

    # Optional exact null-vs-0 & value parity check against lookup ground truth
    if expected_dataset is not None and isinstance(nofo, dict) and isinstance(recipients, list):
        exp_fys = {x["fiscal_year"]: x for x in expected_dataset.get("nofo", {}).get("fiscal_years", [])}
        for fy_row in nofo.get("fiscal_years", []):
            y = fy_row.get("fiscal_year")
            if y not in exp_fys:
                failures.append(f"Unexpected fiscal year {y} in nofo.fiscal_years")
                continue
            for mf in ("account_obligation", "award_obligation", "taggs_amount"):
                if (fy_row.get(mf) is None) != (exp_fys[y].get(mf) is None):
                    failures.append(
                        f"nofo.fiscal_years[{y}].{mf} nullness mismatch: got {fy_row.get(mf)!r}, lookup has {exp_fys[y].get(mf)!r}"
                    )
        exp_by_auk = {r["award_unique_key"]: r for r in expected_dataset.get("recipients", [])}
        for rec in recipients:
            auk = rec.get("award_unique_key")
            exp_rec = exp_by_auk.get(auk)
            if exp_rec is None:
                failures.append(f"Recipient {auk!r} not in lookup dataset")
                continue
            for mf in ("account_obligation", "award_obligation", "taggs_amount", "best_available"):
                if (rec["totals"].get(mf) is None) != (exp_rec["totals"].get(mf) is None):
                    failures.append(
                        f"Recipient {auk} totals.{mf} nullness mismatch: got {rec['totals'].get(mf)!r}, lookup has {exp_rec['totals'].get(mf)!r}"
                    )
            exp_rfys = {x["fiscal_year"]: x for x in exp_rec.get("fiscal_years", [])}
            for fy_row in rec.get("fiscal_years", []):
                y = fy_row.get("fiscal_year")
                exp_fy = exp_rfys.get(y)
                if exp_fy is None:
                    continue
                for mf in ("account_obligation", "award_obligation", "taggs_amount"):
                    if (fy_row.get(mf) is None) != (exp_fy.get(mf) is None):
                        failures.append(
                            f"Recipient {auk} FY{y}.{mf} nullness mismatch: got {fy_row.get(mf)!r}, lookup has {exp_fy.get(mf)!r}"
                        )
                        break

    return failures


def check_envelope(
    payload: Any,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> list[str]:
    """Run global contract checks on a structured tool response."""
    if tool_name in FUNDING_TOOLS:
        return check_funding_envelope(payload, tool_name, arguments)

    failures: list[str] = []
    if not isinstance(payload, dict):
        return [f"Response is not a dict: {type(payload).__name__}"]

    for req_key in ("data", "sources", "interpretation_rules", "warnings"):
        if req_key not in payload:
            failures.append(f"Response envelope missing top-level key {req_key!r}")

    if failures:
        return failures

    if not isinstance(payload["data"], dict):
        failures.append("'data' must be a dict")
    if not isinstance(payload["sources"], list):
        failures.append("'sources' must be a list")
    if not isinstance(payload["interpretation_rules"], list):
        failures.append("'interpretation_rules' must be a list")
    if not isinstance(payload["warnings"], list):
        failures.append("'warnings' must be a list")

    if failures:
        return failures

    # Global checks required by M3 / M3b / H6 / F4
    failures.extend(
        check_no_ahrf(
            payload,
            allow_excluded_list=(tool_name == "list_data_sources"),
            allow_withheld_warning=(tool_name == "search_measures"),
        )
    )
    failures.extend(check_response_size(payload))
    failures.extend(check_forbidden_words(payload))
    failures.extend(check_no_funding_sources_in_area(payload["sources"], payload["interpretation_rules"]))

    # General interpretation rules check (including Amendment 2 §1 Rule 6)
    norm_actual_rules = {_norm_rule(r) for r in payload["interpretation_rules"] if isinstance(r, str)}
    for expected_rule in GENERAL_INTERPRETATION_RULES:
        if _norm_rule(expected_rule) not in norm_actual_rules:
            failures.append(f"Missing general interpretation rule: {expected_rule!r}")

    data = payload["data"]
    args = arguments or {}
    source_products = {
        s.get("product") for s in payload["sources"] if isinstance(s, dict) and s.get("product")
    }

    if tool_name == "find_places":
        if payload["sources"] != []:
            failures.append(f"find_places sources must be [], got {payload['sources']!r}")

    elif tool_name == "search_measures":
        measures_list = data.get("measures") or []
        if measures_list:
            failures.extend(check_search_measures_periods(measures_list))
            expected_prods = {
                m["measure_key"].split(":", 1)[0]
                for m in measures_list
                if isinstance(m, dict) and isinstance(m.get("measure_key"), str) and ":" in m["measure_key"]
            }
            if source_products != expected_prods:
                failures.append(
                    f"search_measures sources products {sorted(source_products)} do not match "
                    f"data.measures products {sorted(expected_prods)}"
                )
        elif not data.get("topics") and payload["sources"] != []:
            failures.append(
                f"search_measures with no matching measures must have empty sources [], got {payload['sources']!r}"
            )

    elif tool_name == "get_measure_details":
        measures_list = data.get("measures")
        if not isinstance(measures_list, list):
            failures.append("get_measure_details data.measures must be a list")
        else:
            failures.extend(check_measure_details_periods(measures_list))
            expected_prods = set()
            for idx, m in enumerate(measures_list):
                if not isinstance(m, dict):
                    failures.append(f"get_measure_details measures[{idx}] is not a dict")
                    continue
                mk = m.get("measure_key")
                prod = m.get("product")
                mid = m.get("measure_id")
                if not mk or not prod or not mid:
                    failures.append(
                        f"get_measure_details measures[{idx}] must carry 'measure_key', 'product', and 'measure_id' "
                        f"(got measure_key={mk!r}, product={prod!r}, measure_id={mid!r})"
                    )
                elif mk != f"{prod}:{mid}":
                    failures.append(
                        f"get_measure_details measures[{idx}] measure_key={mk!r} != '{prod}:{mid}'"
                    )
                else:
                    expected_prods.add(str(prod))
            if source_products != expected_prods:
                failures.append(
                    f"get_measure_details sources products {sorted(source_products)} do not match "
                    f"data.measures products {sorted(expected_prods)}"
                )

    elif tool_name == "get_area_values":
        failures.extend(check_no_change_keys(data))
        values = data.get("values")
        if not isinstance(values, list):
            failures.append("get_area_values data.values must be a list")
        else:
            for idx, row in enumerate(values):
                row_errs = check_value_row_shape(row)
                if row_errs:
                    failures.extend([f"values[{idx}]: {e}" for e in row_errs])
                    if len(failures) > 15:
                        break
            row_products = {
                row["measure_key"].split(":", 1)[0]
                for row in values
                if isinstance(row, dict) and isinstance(row.get("measure_key"), str) and ":" in row["measure_key"]
            }
            if row_products != source_products:
                failures.append(
                    f"sources products {sorted(source_products)} do not match "
                    f"data products {sorted(row_products)}"
                )

    elif tool_name == "get_measure_across_areas":
        failures.extend(check_no_change_keys(data))
        measure_meta = data.get("measure")
        failures.extend(check_across_areas_measure_meta(measure_meta))
        mk = measure_meta.get("measure_key", "") if isinstance(measure_meta, dict) else ""
        product = mk.split(":", 1)[0] if isinstance(mk, str) and ":" in mk else ""
        unc_kind = (
            str(measure_meta.get("uncertainty_kind") or "")
            if isinstance(measure_meta, dict)
            else ""
        )
        has_shared_bv = isinstance(measure_meta, dict) and bool(measure_meta.get("boundary_vintage"))

        with_val = data.get("with_value")
        without_val = data.get("without_value")
        if not isinstance(with_val, list):
            failures.append("get_measure_across_areas data.with_value must be a list")
        if not isinstance(without_val, list):
            failures.append("get_measure_across_areas data.without_value must be a list")

        if isinstance(with_val, list) and isinstance(without_val, list):
            sort_mode = args.get("sort", "geoid")
            require_pos = sort_mode in ("value_desc", "value_asc")
            for idx, row in enumerate(with_val):
                row_errs = check_compact_value_row_shape(
                    row,
                    product=product,
                    uncertainty_kind=unc_kind,
                    require_position=require_pos,
                    allow_boundary_vintage=(not has_shared_bv),
                )
                if row_errs:
                    failures.extend([f"with_value[{idx}]: {e}" for e in row_errs])
                    if len(failures) > 15:
                        break
            for idx, row in enumerate(without_val):
                row_errs = check_compact_value_row_shape(
                    row,
                    product=product,
                    uncertainty_kind=unc_kind,
                    require_position=False,
                    allow_boundary_vintage=(not has_shared_bv),
                )
                if row_errs:
                    failures.extend([f"without_value[{idx}]: {e}" for e in row_errs])
                    if len(failures) > 15:
                        break

            all_rows = with_val + without_val
            if not has_shared_bv and all_rows:
                if not all(isinstance(r, dict) and bool(r.get("boundary_vintage")) for r in all_rows):
                    failures.append(
                        "boundary_vintage is missing from data.measure and not present on every row"
                    )

            failures.extend(check_competition_positions(with_val, sort_mode=sort_mode))
            failures.extend(check_without_value_rows(without_val))

            if sort_mode in ("value_desc", "value_asc"):
                if not any(ORDERING_WARNING in w for w in payload["warnings"] if isinstance(w, str)):
                    failures.append(
                        f"Missing required ordering warning on sort={sort_mode!r}: {ORDERING_WARNING!r}"
                    )

            if data.get("truncated") is True:
                if not any(
                    ("Showing " in w or "truncated" in w.lower() or "50,000" in w or "60,000" in w)
                    for w in payload["warnings"]
                    if isinstance(w, str)
                ):
                    failures.append("data.truncated is True, but warnings has no truncation notice")

            expected_prods = {product} if product and all_rows else set()
            if all_rows and source_products != expected_prods:
                failures.append(
                    f"sources products {sorted(source_products)} do not match "
                    f"data.measure product {sorted(expected_prods)}"
                )

    elif tool_name == "get_measure_over_time":
        failures.extend(check_over_time_response(payload))
        series = data.get("series") if isinstance(data.get("series"), list) else []
        row_products = {
            row["measure_key"].split(":", 1)[0]
            for row in series
            if isinstance(row, dict) and isinstance(row.get("measure_key"), str) and ":" in row["measure_key"]
        }
        if row_products != source_products:
            failures.append(
                f"get_measure_over_time sources products {sorted(source_products)} do not match "
                f"series products {sorted(row_products)}"
            )

    elif tool_name == "list_data_sources":
        if "notes" in data:
            failures.extend(check_list_data_sources_notes(data.get("notes")))

    return failures


# ---------------------------------------------------------------------------
# Offline question set validation (--validate)
# ---------------------------------------------------------------------------

def load_registry_measures_offline() -> dict[str, dict[str, Any]]:
    """Load all measures from lookup.SPECS without touching the database."""
    measures: dict[str, dict[str, Any]] = {}
    for spec in lookup.SPECS:
        cfg = spec.load()
        for m in cfg["measures"]:
            meta = lookup._measure_meta(spec, cfg, m)
            measures[f"{spec.key}:{m['measure_id']}"] = meta
    return measures


def validate_questions_yaml(path: Path = DEFAULT_QUESTIONS_PATH) -> tuple[bool, dict[str, Any], list[str]]:
    """Validate structure and coverage of questions.yaml without touching DB or server."""
    errors: list[str] = []
    if not path.exists():
        return False, {}, [f"File does not exist: {path}"]

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("questions"), list):
        return False, {}, ["Top-level YAML must be a mapping with a 'questions' list"]

    questions = raw["questions"]
    if len(questions) < 66:
        errors.append(f"Expected at least 66 questions (54 area + 12 funding), found {len(questions)}")

    reg_measures = load_registry_measures_offline()
    topics_data = json.loads(TOPICS_PATH.read_text(encoding="utf-8"))
    valid_topics = {t["slug"] for t in topics_data}

    seen_ids: set[str] = set()
    tool_counts: dict[str, int] = {t: 0 for t in ALL_TOOLS}
    product_counts: dict[str, int] = {
        p: 0 for p in PUBLIC_PRODUCTS + FACILITY_BLOCKS + ("ahrf",) + FUNDING_PRODUCTS
    }
    level_counts: dict[str, int] = {lvl: 0 for lvl in ALL_LEVELS}
    trap_questions: list[dict[str, Any]] = []
    trap_kinds_seen: set[str] = set()
    geoids_seen: set[str] = set()
    within_seen: set[str] = set()
    funding_questions_count = 0

    for idx, q in enumerate(questions):
        if not isinstance(q, dict):
            errors.append(f"Question at index {idx} is not a mapping")
            continue
        qid = q.get("id")
        if not qid or not isinstance(qid, str):
            errors.append(f"Question at index {idx} missing string 'id'")
            continue
        if qid in seen_ids:
            errors.append(f"Duplicate question id {qid!r}")
        seen_ids.add(qid)

        if not isinstance(q.get("question"), str) or not q["question"].strip():
            errors.append(f"{qid}: missing non-empty 'question' text")

        calls = q.get("expected_calls")
        if not isinstance(calls, list) or not calls:
            errors.append(f"{qid}: 'expected_calls' must be a non-empty list")
            continue

        if not isinstance(q.get("checks"), dict):
            errors.append(f"{qid}: missing 'checks' mapping")

        for p in q.get("products", []):
            if p in product_counts:
                product_counts[p] += 1
            else:
                errors.append(f"{qid}: unknown product {p!r} in 'products'")

        for lvl in q.get("levels", []):
            if lvl in level_counts:
                level_counts[lvl] += 1
            else:
                errors.append(f"{qid}: unknown level {lvl!r} in 'levels'")

        if q.get("trap") is True:
            trap_questions.append(q)
            tk = q.get("trap_kind")
            if tk:
                trap_kinds_seen.add(tk)
            else:
                errors.append(f"{qid}: trap=true but missing 'trap_kind'")

        if any(c.get("tool") in FUNDING_TOOLS for c in calls if isinstance(c, dict)):
            funding_questions_count += 1

        for c_idx, call in enumerate(calls):
            if not isinstance(call, dict):
                errors.append(f"{qid} call[{c_idx}]: must be a mapping")
                continue
            tool = call.get("tool")
            args = call.get("arguments")
            if tool not in tool_counts:
                errors.append(f"{qid} call[{c_idx}]: unknown tool {tool!r}")
            else:
                tool_counts[tool] += 1
            if not isinstance(args, dict):
                errors.append(f"{qid} call[{c_idx}]: 'arguments' must be a dict")
                continue

            if "geoid" in args and isinstance(args["geoid"], str):
                geoids_seen.add(args["geoid"])
            if "geoids" in args and isinstance(args["geoids"], list):
                for g in args["geoids"]:
                    geoids_seen.add(str(g))
            if "within" in args and args["within"] is not None:
                within_seen.add(str(args["within"]))
            if "level" in args and args["level"] in level_counts:
                level_counts[args["level"]] += 1

            if "topic" in args and args["topic"] is not None:
                if args["topic"] not in valid_topics and not q.get("trap"):
                    errors.append(f"{qid} call[{c_idx}]: unknown topic {args['topic']!r}")
            if "measure_key" in args and isinstance(args["measure_key"], str):
                mk = args["measure_key"]
                if mk not in reg_measures and not q.get("trap"):
                    errors.append(f"{qid} call[{c_idx}]: unknown measure_key {mk!r}")
            if "measure_keys" in args and isinstance(args["measure_keys"], list):
                for mk in args["measure_keys"]:
                    if mk not in reg_measures and not q.get("trap"):
                        errors.append(f"{qid} call[{c_idx}]: unknown measure_key {mk!r}")

    for tool, count in tool_counts.items():
        if count == 0:
            errors.append(f"Tool {tool!r} has 0 calls across questions.yaml")

    for prod in PUBLIC_PRODUCTS + FACILITY_BLOCKS + FUNDING_PRODUCTS:
        if product_counts[prod] == 0:
            errors.append(f"Public product / facility block {prod!r} is not covered in questions.yaml")

    if funding_questions_count < 12:
        errors.append(f"At least 12 funding questions required (F4), found {funding_questions_count}")

    for lvl in ALL_LEVELS:
        if level_counts[lvl] == 0:
            errors.append(f"Geographic level {lvl!r} is not covered in questions.yaml")

    for sg in SHOWCASE_GEOIDS:
        if sg not in geoids_seen and sg not in within_seen:
            errors.append(f"Showcase place GEOID {sg!r} is not covered in questions.yaml")

    if "01" not in within_seen and "AL" not in within_seen and "01" not in geoids_seen:
        errors.append("Alabama ('01') is not covered in questions.yaml")
    if "48" not in within_seen and "48" not in geoids_seen:
        errors.append("Texas ('48', 254 counties) is not covered in questions.yaml")

    if len(trap_questions) < 17:
        errors.append(f"At least 17 trap questions required (including H6 & F4 traps), found {len(trap_questions)}")

    missing_traps = set(REQUIRED_TRAP_KINDS) - trap_kinds_seen
    if missing_traps:
        errors.append(f"Missing required trap kinds: {sorted(missing_traps)}")

    summary = {
        "total_questions": len(questions),
        "area_questions": len(questions) - funding_questions_count,
        "funding_questions": funding_questions_count,
        "regular_questions": len(questions) - len(trap_questions),
        "trap_questions": len(trap_questions),
        "trap_kinds": sorted(trap_kinds_seen),
        "tool_call_counts": tool_counts,
        "product_question_counts": product_counts,
        "level_counts": level_counts,
        "showcase_geoids_covered": sorted(set(SHOWCASE_GEOIDS) & (geoids_seen | within_seen)),
    }
    return len(errors) == 0, summary, errors


# ---------------------------------------------------------------------------
# Ground-truth lookup computation (--expected-only and --url)
# ---------------------------------------------------------------------------

def resolve_within_geoid(db: Any, level: str, within: str | None) -> str | None:
    """Resolve state name/abbreviation or GEOID for get_measure_across_areas."""
    if within is None:
        return None
    val = str(within).strip()
    if not val:
        return None
    if level in ("county", "cd"):
        if re.fullmatch(r"\d{2}", val):
            return val
        upper = val.upper()
        if upper in STATE_ABBR_TO_FIPS:
            return STATE_ABBR_TO_FIPS[upper]
        for st in lookup.states(db):
            if st["name"].lower() == val.lower():
                return st["geoid"]
    return val


def load_topics() -> list[dict[str, Any]]:
    return json.loads(TOPICS_PATH.read_text(encoding="utf-8"))


def compute_expected_for_call(
    db: Any,
    tool: str,
    arguments: dict[str, Any],
    topics_list: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute ground-truth expectations directly from app.area_pilot.lookup."""
    if tool == "get_area_values":
        level = arguments["level"]
        geoids = list(arguments["geoids"])
        measure_keys = arguments.get("measure_keys")
        topic_slug = arguments.get("topic")
        period = arguments.get("period")

        if topic_slug == "health-care-resources":
            return {
                "expect_error": True,
                "reason": WITHHELD_TOPIC_EXPLANATION,
            }

        if measure_keys:
            for mk in measure_keys:
                if str(mk).startswith("ahrf:"):
                    return {"expect_error": True, "reason": "Excluded product ahrf requested"}

        cat = lookup.catalog(db)
        by_key = {
            f"{m['product']}:{m['measure_id']}": m
            for m in cat["measures"]
            if m["product"] in PUBLIC_PRODUCTS
        }

        candidate_keys: list[str] = []
        skipped_unpublished: list[tuple[str, list[str]]] = []
        if measure_keys:
            for mk in dict.fromkeys(measure_keys):
                meta = by_key.get(mk)
                if meta:
                    if level in meta["levels"]:
                        candidate_keys.append(mk)
                    else:
                        skipped_unpublished.append((mk, meta["levels"]))
        elif topic_slug:
            topic_obj = next((t for t in topics_list if t["slug"] == topic_slug), None)
            if topic_obj:
                for item in topic_obj["measure_keys"]:
                    mk = f"{item[0]}:{item[1]}" if isinstance(item, list) else str(item)
                    prod = mk.split(":", 1)[0]
                    if prod in PUBLIC_PRODUCTS:
                        meta = by_key.get(mk)
                        if meta and level in meta["levels"]:
                            candidate_keys.append(mk)
        else:
            for mk, meta in by_key.items():
                if level in meta["levels"]:
                    candidate_keys.append(mk)

        selected_keys: list[str] = []
        skipped_unpublished_periods: list[tuple[str, list[str]]] = []
        if period is not None:
            for mk in candidate_keys:
                meta = by_key[mk]
                pub_periods = [
                    p["period"]
                    for p in lookup.measure_periods(db, meta["product"], meta["measure_id"])
                    if p["available"]
                ]
                if period not in pub_periods:
                    skipped_unpublished_periods.append((mk, pub_periods))
                else:
                    selected_keys.append(mk)
        else:
            selected_keys = candidate_keys

        estimated_rows = len(set(geoids)) * len(selected_keys)
        if estimated_rows > 400:
            return {
                "expect_error": True,
                "reason": f"Row count {estimated_rows} exceeds 400-row cap",
                "estimated_rows": estimated_rows,
            }

        if not selected_keys:
            return {
                "expect_error": False,
                "skipped_unpublished": skipped_unpublished,
                "skipped_unpublished_periods": skipped_unpublished_periods,
                "rows_by_key_geoid": {},
                "expected_row_count": 0,
                "expected_sources": [],
                "area_names": {},
            }

        prods = list(dict.fromkeys(mk.split(":", 1)[0] for mk in selected_keys))
        mids = list(dict.fromkeys(mk.split(":", 1)[1] for mk in selected_keys))
        if period is not None:
            raw = lookup.area_values_for_period(
                db,
                level,
                geoids,
                period,
                [(mk.split(":", 1)[0], mk.split(":", 1)[1]) for mk in selected_keys],
            )
        else:
            raw = lookup.area_values(db, level, geoids, products=prods, measure_ids=mids)
        infos = {r["geoid"]: r["name"] for r in lookup.area_info(db, level, geoids)}

        selected_set = set(selected_keys)
        rows_by_key_geoid: dict[tuple[str, str], dict[str, Any]] = {}
        products_in_data: set[str] = set()
        for r in raw["values"]:
            mk = f"{r['product']}:{r['measure_id']}"
            if mk not in selected_set:
                continue
            row_copy = dict(r)
            row_copy.setdefault("note", None)
            rows_by_key_geoid[(mk, r["geoid"])] = row_copy
            products_in_data.add(r["product"])

        return {
            "expect_error": False,
            "skipped_unpublished": skipped_unpublished,
            "skipped_unpublished_periods": skipped_unpublished_periods,
            "rows_by_key_geoid": rows_by_key_geoid,
            "expected_row_count": len(rows_by_key_geoid),
            "expected_sources": sorted(products_in_data),
            "area_names": infos,
        }

    elif tool == "get_measure_across_areas":
        mk = arguments["measure_key"]
        level = arguments["level"]
        within = arguments.get("within")
        sort_mode = arguments.get("sort", "geoid")
        limit = int(arguments.get("limit", 25))
        period = arguments.get("period")

        if ":" not in mk:
            return {"expect_error": True, "reason": f"Invalid measure_key {mk!r}"}
        product, measure_id = mk.split(":", 1)
        if product == "ahrf":
            return {"expect_error": True, "reason": "Excluded product ahrf"}

        parent_geoid = resolve_within_geoid(db, level, within)
        try:
            if period is not None:
                raw = lookup.measure_values_within(db, product, measure_id, level, parent_geoid, period=period)
            else:
                raw = lookup.measure_values_within(db, product, measure_id, level, parent_geoid)
        except lookup.LookupError_ as exc:
            return {"expect_error": True, "reason": str(exc)}

        all_rows = raw["values"]
        with_val = [r for r in all_rows if r["value"] is not None]
        without_val = [r for r in all_rows if r["value"] is None]

        if sort_mode == "value_desc":
            with_val.sort(key=lambda r: (-r["value"], r["geoid"]))
        elif sort_mode == "value_asc":
            with_val.sort(key=lambda r: (r["value"], r["geoid"]))
        else:
            with_val.sort(key=lambda r: r["geoid"])

        if sort_mode in ("value_desc", "value_asc"):
            positions = compute_competition_positions([r["value"] for r in with_val])
            for r, pos in zip(with_val, positions):
                r["position"] = pos

        truncated_by_limit = len(with_val) > limit
        sliced_with_val = with_val[:limit]

        first_row = all_rows[0] if all_rows else {}
        first_unc = first_row.get("uncertainty") or {}
        measure_meta = {
            "measure_key": mk,
            "label": raw["measure"]["label"],
            "unit": raw["measure"]["unit"],
            "storage_scale": raw["measure"]["storage_scale"],
            "period": raw["measure"]["period"],
            "population": raw["measure"]["population"],
            "value_type": raw["measure"]["value_type"],
            "release_id": (raw["release"] or {}).get("release_id"),
            "boundary_vintage": first_row.get("boundary_vintage"),
            "note": raw["measure"].get("note", first_row.get("note")),
            "uncertainty_kind": raw["measure"].get("uncertainty_kind") or first_unc.get("kind"),
            "uncertainty_label": first_unc.get("label"),
        }

        return {
            "expect_error": False,
            "measure_meta": measure_meta,
            "total_areas": len(all_rows),
            "all_with_value_count": len(with_val),
            "with_value": sliced_with_val,
            "with_value_by_geoid": {r["geoid"]: r for r in with_val},
            "without_value": without_val,
            "truncated_by_limit": truncated_by_limit,
            "expected_sources": [product] if all_rows else [],
        }

    elif tool == "get_measure_over_time":
        level = arguments["level"]
        geoid = arguments["geoid"]
        mk = arguments["measure_key"]
        if ":" not in mk:
            return {"expect_error": True, "reason": f"Invalid measure_key {mk!r}"}
        product, measure_id = mk.split(":", 1)
        if product == "ahrf":
            return {"expect_error": True, "reason": "Excluded product ahrf"}

        try:
            raw = lookup.area_measure_series(db, level, geoid, product, measure_id)
        except lookup.LookupError_ as exc:
            return {"expect_error": True, "reason": str(exc)}

        series = list(raw["series"])
        if level == "cd":
            cat = lookup.catalog(db)
            m = next(
                (item for item in cat["measures"] if item["product"] == product and item["measure_id"] == measure_id),
                None,
            )
            if m:
                series = [r for r in series if r["period"] == m["period"]]

        infos = lookup.area_info(db, level, [geoid])
        area_name = infos[0]["name"] if infos else None
        return {
            "expect_error": False,
            "area_name": area_name,
            "series": series,
            "series_by_period": {r["period"]: r for r in series},
            "unavailable_periods": raw["unavailable_periods"] if level != "cd" else [],
            "expected_sources": [product] if series else [],
        }

    elif tool == "get_area_context":
        level = arguments["level"]
        geoid = arguments["geoid"]
        infos = lookup.area_info(db, level, [geoid])
        area = infos[0] if infos else None
        related: dict[str, Any] = {}
        if level == "state":
            related["counties"] = lookup.state_counties(db, geoid)
            related["districts"] = lookup.state_districts(db, geoid)
        elif level == "county":
            related["districts"] = lookup.county_districts(db, geoid)["districts"]
        elif level == "cd":
            related["counties"] = lookup.district_counties(db, geoid)["counties"]

        facilities = None
        if level in ("state", "county", "cd"):
            fac_raw = lookup.area_facilities(db, level, geoid)
            facilities = {
                block: {
                    "count": fac_raw[block]["count"],
                    "published": fac_raw[block]["published"],
                }
                for block in FACILITY_BLOCKS
            }
        return {
            "expect_error": False,
            "area": area,
            "related": related,
            "facilities": facilities,
        }

    elif tool == "get_measure_details":
        cat = lookup.catalog(db)
        by_key = {
            f"{m['product']}:{m['measure_id']}": m
            for m in cat["measures"]
            if m["product"] in PUBLIC_PRODUCTS
        }
        expected_measures = {}
        for mk in arguments.get("measure_keys", []):
            if mk in by_key:
                m = dict(by_key[mk])
                m["periods"] = lookup.measure_periods(db, m["product"], m["measure_id"])
                expected_measures[mk] = m
        return {"expect_error": False, "measures": expected_measures}

    elif tool == "list_data_sources":
        cat = lookup.catalog(db)
        pub_prods = {
            p["product"]: p for p in cat["products"] if p["product"] in PUBLIC_PRODUCTS
        }
        ms = [m for m in cat["measures"] if m["product"] in PUBLIC_PRODUCTS]
        expected_period_notes: list[str] = []
        for p in cat["products"]:
            if p["product"] not in PUBLIC_PRODUCTS:
                continue
            periods = {
                per["period"]
                for m in ms
                if m["product"] == p["product"]
                for per in lookup.measure_periods(db, m["product"], m["measure_id"])
                if per["available"]
            }
            if periods:
                first, last = min(periods), max(periods)
                span = (
                    ", ".join(sorted(periods))
                    if any("–" in per for per in periods)
                    else first if first == last else f"{first}–{last}"
                )
                expected_period_notes.append(f"{p['name']}: {span}")
        return {
            "expect_error": False,
            "products": pub_prods,
            "status_text": lookup.STATUS_TEXT,
            "expected_period_notes": expected_period_notes,
        }

    elif tool == "find_places":
        return {"expect_error": False, "query": arguments.get("query")}

    elif tool == "search_measures":
        if arguments.get("topic") == "health-care-resources":
            return {
                "expect_error": True,
                "reason": WITHHELD_TOPIC_EXPLANATION,
            }
        cat = lookup.catalog(db)
        periods_by_key = {
            f"{m['product']}:{m['measure_id']}": [
                p["period"]
                for p in lookup.measure_periods(db, m["product"], m["measure_id"])
                if p["available"]
            ]
            for m in cat["measures"]
            if m["product"] in PUBLIC_PRODUCTS
        }
        return {
            "expect_error": False,
            "arguments": arguments,
            "periods_by_key": periods_by_key,
        }

    elif tool == "get_nofo_overview":
        nofo = arguments["nofo"]
        include_subawards = bool(arguments.get("include_subawards", False))
        try:
            overview = funding_lookup.nofo_overview(db, nofo, include_subawards)
        except funding_lookup.UnsupportedNOFOError as exc:
            return {"expect_error": True, "error_kind": "unsupported_nofo", "reason": str(exc)}
        except funding_lookup.FundingLookupError as exc:
            return {"expect_error": True, "error_kind": "funding_lookup", "reason": str(exc)}
        return {
            "expect_error": False,
            "overview": overview,
            "expected_source_ids": [s["id"] for s in overview.get("sources", [])],
        }

    elif tool == "list_nofo_recipients":
        nofo = arguments["nofo"]
        offset = int(arguments.get("offset", 0))
        limit = int(arguments.get("limit", 50))
        try:
            dataset = funding_lookup.nofo_dataset(db, nofo, False)
            listing = funding_lookup.list_recipients(db, nofo, offset, limit)
        except funding_lookup.UnsupportedNOFOError as exc:
            return {"expect_error": True, "error_kind": "unsupported_nofo", "reason": str(exc)}
        except funding_lookup.FundingLookupError as exc:
            return {"expect_error": True, "error_kind": "funding_lookup", "reason": str(exc)}
        return {
            "expect_error": False,
            "listing": listing,
            "expected_source_ids": [s["id"] for s in dataset.get("sources", [])],
        }

    elif tool == "get_recipient_funding":
        nofo = arguments["nofo"]
        recipient = arguments["recipient"]
        try:
            profile = funding_lookup.recipient_profile(db, nofo, recipient)
            dataset = funding_lookup.nofo_dataset(db, nofo, False)
        except funding_lookup.UnsupportedNOFOError as exc:
            return {"expect_error": True, "error_kind": "unsupported_nofo", "reason": str(exc)}
        except funding_lookup.FundingLookupError as exc:
            return {"expect_error": True, "error_kind": "funding_lookup", "reason": str(exc)}
        return {
            "expect_error": False,
            "nofo_key": dataset["nofo"]["nofo_key"],
            "recipient": profile,
            "expected_source_ids": [s["id"] for s in dataset.get("sources", [])],
        }

    return {"expect_error": False}


# ---------------------------------------------------------------------------
# Comparison between MCP server response and lookup ground truth
# ---------------------------------------------------------------------------

def _extract_error_text(call_result: Any) -> str:
    """Extract human-readable error text from a CallToolResult."""
    parts: list[str] = []
    for item in getattr(call_result, "content", []) or []:
        txt = getattr(item, "text", None)
        if txt:
            parts.append(txt)
    if not parts and getattr(call_result, "structured_content", None):
        parts.append(json.dumps(call_result.structured_content))
    return " ".join(parts)


def verify_error_message_checks(error_text: str, call_check_spec: dict[str, Any]) -> list[str]:
    """Validate error text against substring requirements and forbidden substrings."""
    failures: list[str] = []
    substrings_any = call_check_spec.get("expect_error_Substrings_any") or []
    if substrings_any:
        if not any(sub.lower() in error_text.lower() for sub in substrings_any):
            failures.append(
                f"ToolError message {error_text!r} did not contain any of {substrings_any}"
            )
    substrings_all = call_check_spec.get("expect_error_substrings_all") or []
    for sub in substrings_all:
        if sub.lower() not in error_text.lower():
            failures.append(
                f"ToolError message {error_text!r} missing required substring {sub!r}"
            )
    forbid_substrings = call_check_spec.get("forbid_error_substrings") or []
    for bad in forbid_substrings:
        if bad.lower() in error_text.lower():
            failures.append(
                f"ToolError message {error_text!r} contained forbidden substring {bad!r}"
            )
    return failures


def verify_call_against_lookup_and_checks(
    tool: str,
    arguments: dict[str, Any],
    call_result: Any,
    expected_lookup: dict[str, Any],
    call_check_spec: dict[str, Any],
    match_lookup_flag: bool,
) -> list[str]:
    """Verify a single MCP tool call result against global rules, lookup ground truth, and call_checks."""
    failures: list[str] = []
    is_error = bool(getattr(call_result, "is_error", False))
    structured = getattr(call_result, "structured_content", None)
    error_text = _extract_error_text(call_result) if is_error else ""

    # 1. Handle calls that expect a ToolError
    if call_check_spec.get("expect_error") is True:
        if not is_error:
            failures.append(
                f"Expected ToolError for {tool}({arguments}), but call succeeded with: "
                f"{json.dumps(structured)[:240]}"
            )
            return failures
        failures.extend(verify_error_message_checks(error_text, call_check_spec))
        return failures

    # 2. Handle unpublished level in get_area_values (Amendment 1 §4: must skip with warning, not raise ToolError)
    if "expect_unpublished_level_handled" in call_check_spec:
        spec_info = call_check_spec["expect_unpublished_level_handled"]
        skipped_key = spec_info["skipped_measure_key"]
        pub_levels = spec_info["published_levels"]
        if is_error:
            return [
                f"Amendment 1 §4 requires get_area_values to skip unpublished measure {skipped_key!r} "
                f"with a warning, not raise ToolError: {error_text!r}"
            ]
        if not isinstance(structured, dict):
            return ["Response missing structured_content"]
        failures.extend(check_envelope(structured, tool, arguments))
        values = structured.get("data", {}).get("values", [])
        if any(r.get("measure_key") == skipped_key for r in values if isinstance(r, dict)):
            failures.append(
                f"Unpublished measure {skipped_key!r} should have been skipped at level={arguments.get('level')!r}"
            )
        warnings_joined = " ".join(str(w) for w in structured.get("warnings", []))
        for lvl in pub_levels:
            if lvl.lower() not in warnings_joined.lower():
                failures.append(
                    f"Warnings {structured.get('warnings')!r} did not mention published level {lvl!r} "
                    f"for skipped measure {skipped_key!r}"
                )
        return failures

    # 2b. Handle unpublished period in get_area_values (Amendment 2 §2: must skip with warning listing published periods)
    if "expect_unpublished_period_handled" in call_check_spec:
        spec_info = call_check_spec["expect_unpublished_period_handled"]
        skipped_key = spec_info["skipped_measure_key"]
        req_period = str(spec_info["requested_period"])
        if is_error:
            return [
                f"Amendment 2 §2 requires get_area_values to skip measure {skipped_key!r} for unpublished period "
                f"{req_period!r} with a warning, not raise ToolError: {error_text!r}"
            ]
        if not isinstance(structured, dict):
            return ["Response missing structured_content"]
        failures.extend(check_envelope(structured, tool, arguments))
        values = structured.get("data", {}).get("values", [])
        if any(r.get("measure_key") == skipped_key for r in values if isinstance(r, dict)):
            failures.append(
                f"Measure {skipped_key!r} should have been skipped for unpublished period {req_period!r}"
            )
        warnings_joined = " ".join(str(w) for w in structured.get("warnings", []))
        if skipped_key.lower() not in warnings_joined.lower() or req_period not in warnings_joined:
            failures.append(
                f"Warnings {structured.get('warnings')!r} did not mention {skipped_key!r} and {req_period!r}"
            )
        expected_pub_periods: list[str] = []
        for mk, pub_list in expected_lookup.get("skipped_unpublished_periods", []):
            if mk == skipped_key:
                expected_pub_periods = pub_list
                break
        if not expected_pub_periods:
            expected_pub_periods = list(spec_info.get("min_published_periods", []))
        for pub_p in expected_pub_periods:
            if str(pub_p) not in warnings_joined:
                failures.append(
                    f"Warnings {structured.get('warnings')!r} did not list published period {pub_p!r} "
                    f"for {skipped_key!r}"
                )
        return failures

    # 3. Normal non-error call
    if is_error:
        return [f"Unexpected ToolError on {tool}({arguments}): {error_text}"]

    if not isinstance(structured, dict):
        return [f"{tool} did not return structured_content dict (got {type(structured).__name__})"]

    # Run global contract checks (includes check_response_size, check_no_ahrf, check_forbidden_words)
    failures.extend(check_envelope(structured, tool, arguments))
    if failures:
        return failures

    data = structured["data"]
    sources = structured["sources"]
    warnings = structured["warnings"]
    interp_rules = structured["interpretation_rules"]

    # 4. Compare against lookup ground truth when match_lookup is enabled
    effective_match_lookup = call_check_spec.get("match_lookup", match_lookup_flag)
    if effective_match_lookup and not expected_lookup.get("expect_error"):
        if tool == "get_area_values":
            exp_rows = expected_lookup["rows_by_key_geoid"]
            act_values = data.get("values", [])
            if not data.get("truncated") and len(act_values) != len(exp_rows):
                failures.append(
                    f"get_area_values row count mismatch: got {len(act_values)}, lookup has {len(exp_rows)}"
                )
            for row in act_values:
                key = (row.get("measure_key"), (row.get("area") or {}).get("geoid"))
                if key not in exp_rows:
                    failures.append(f"Unexpected (measure_key, geoid) row in get_area_values: {key}")
                    continue
                exp = exp_rows[key]
                for field in (
                    "value", "status", "status_text", "period", "population", "unit",
                    "storage_scale", "value_type", "boundary_vintage", "release_id", "note", "source_credit",
                ):
                    if row.get(field) != exp.get(field):
                        failures.append(
                            f"Row {key} field {field!r} mismatch: got {row.get(field)!r}, lookup has {exp.get(field)!r}"
                        )
                if row.get("uncertainty") != exp.get("uncertainty"):
                    failures.append(
                        f"Row {key} uncertainty mismatch: got {row.get('uncertainty')!r}, lookup has {exp.get('uncertainty')!r}"
                    )
                exp_name = expected_lookup["area_names"].get(key[1])
                act_name = (row.get("area") or {}).get("name")
                if exp_name is not None and act_name != exp_name:
                    failures.append(
                        f"Row {key} area.name mismatch: got {act_name!r}, lookup has {exp_name!r}"
                    )

        elif tool == "get_measure_across_areas":
            exp_meta = expected_lookup.get("measure_meta") or {}
            act_meta = data.get("measure") or {}
            for meta_field in (
                "measure_key",
                "label",
                "unit",
                "storage_scale",
                "period",
                "population",
                "value_type",
                "release_id",
                "note",
                "uncertainty_kind",
                "uncertainty_label",
            ):
                if meta_field in exp_meta and act_meta.get(meta_field) != exp_meta.get(meta_field):
                    failures.append(
                        f"data.measure.{meta_field} mismatch: got {act_meta.get(meta_field)!r}, "
                        f"lookup has {exp_meta.get(meta_field)!r}"
                    )
            if "boundary_vintage" in act_meta and exp_meta.get("boundary_vintage") is not None:
                if act_meta.get("boundary_vintage") != exp_meta.get("boundary_vintage"):
                    failures.append(
                        f"data.measure.boundary_vintage mismatch: got {act_meta.get('boundary_vintage')!r}, "
                        f"lookup has {exp_meta.get('boundary_vintage')!r}"
                    )

            if data.get("total_areas") != expected_lookup["total_areas"]:
                failures.append(
                    f"total_areas mismatch: got {data.get('total_areas')}, lookup has {expected_lookup['total_areas']}"
                )
            act_without = data.get("without_value", [])
            exp_without = expected_lookup["without_value"]
            if len(act_without) != len(exp_without):
                failures.append(
                    f"without_value count mismatch (must never be truncated): got {len(act_without)}, "
                    f"lookup has {len(exp_without)}"
                )
            else:
                for idx, (act_r, exp_r) in enumerate(zip(act_without, exp_without)):
                    act_geoid = (act_r.get("area") or {}).get("geoid")
                    if (
                        act_geoid != exp_r["geoid"]
                        or act_r.get("status") != exp_r["status"]
                        or act_r.get("status_text") != exp_r["status_text"]
                        or act_r.get("value") is not None
                    ):
                        failures.append(
                            f"without_value[{idx}] mismatch: got ({act_geoid}, {act_r.get('status')}, {act_r.get('value')}), "
                            f"lookup has ({exp_r['geoid']}, {exp_r['status']}, None)"
                        )
                        break

            act_with = data.get("with_value", [])
            exp_with = expected_lookup["with_value"]
            exp_by_geoid = expected_lookup.get("with_value_by_geoid") or {}
            if not data.get("truncated") and len(act_with) != len(exp_with):
                failures.append(
                    f"with_value count mismatch: got {len(act_with)}, lookup has {len(exp_with)}"
                )
            for idx, (act_r, exp_r) in enumerate(zip(act_with, exp_with)):
                act_geoid = (act_r.get("area") or {}).get("geoid")
                if act_r.get("value") != exp_r["value"]:
                    failures.append(
                        f"with_value[{idx}] value mismatch: got {act_r.get('value')} ({act_geoid}), "
                        f"lookup has {exp_r['value']} ({exp_r['geoid']})"
                    )
                    break
                exp_row_for_geoid = exp_by_geoid.get(str(act_geoid))
                if exp_row_for_geoid is None:
                    failures.append(f"with_value[{idx}] geoid {act_geoid!r} not found in lookup with_value rows")
                    break
                for fld in ("value", "status", "status_text"):
                    if act_r.get(fld) != exp_row_for_geoid.get(fld):
                        failures.append(
                            f"with_value[{idx}] ({act_geoid}) {fld} mismatch: got {act_r.get(fld)!r}, "
                            f"lookup has {exp_row_for_geoid.get(fld)!r}"
                        )
                        break
                act_unc = act_r.get("uncertainty") or {}
                exp_unc = exp_row_for_geoid.get("uncertainty") or {}
                for unc_k in ("low", "high", "moe"):
                    if unc_k in exp_unc and act_unc.get(unc_k) != exp_unc.get(unc_k):
                        failures.append(
                            f"with_value[{idx}] ({act_geoid}) uncertainty.{unc_k} mismatch: "
                            f"got {act_unc.get(unc_k)!r}, lookup has {exp_unc.get(unc_k)!r}"
                        )
                        break
                act_notes = act_r.get("notes") or {}
                exp_notes = exp_row_for_geoid.get("notes") or {}
                if act_notes != exp_notes:
                    failures.append(
                        f"with_value[{idx}] ({act_geoid}) notes mismatch: got {act_notes!r}, lookup has {exp_notes!r}"
                    )
                    break

        elif tool == "get_measure_over_time":
            exp_series = expected_lookup.get("series") or []
            act_series = data.get("series") or []
            if not data.get("truncated") and len(act_series) != len(exp_series):
                failures.append(
                    f"get_measure_over_time series count mismatch: got {len(act_series)}, lookup has {len(exp_series)}"
                )
            for idx, (act_r, exp_r) in enumerate(zip(act_series, exp_series)):
                for fld in (
                    "period",
                    "value",
                    "status",
                    "status_text",
                    "population",
                    "unit",
                    "storage_scale",
                    "value_type",
                    "boundary_vintage",
                    "release_id",
                    "note",
                ):
                    if act_r.get(fld) != exp_r.get(fld):
                        failures.append(
                            f"series[{idx}] ({act_r.get('period')}) {fld!r} mismatch: "
                            f"got {act_r.get(fld)!r}, lookup has {exp_r.get(fld)!r}"
                        )
                        break
                if act_r.get("uncertainty") != exp_r.get("uncertainty"):
                    failures.append(
                        f"series[{idx}] ({act_r.get('period')}) uncertainty mismatch: "
                        f"got {act_r.get('uncertainty')!r}, lookup has {exp_r.get('uncertainty')!r}"
                    )
                    break
            if data.get("unavailable_periods") != expected_lookup.get("unavailable_periods"):
                failures.append(
                    f"get_measure_over_time unavailable_periods mismatch: "
                    f"got {data.get('unavailable_periods')!r}, lookup has {expected_lookup.get('unavailable_periods')!r}"
                )

        elif tool == "get_area_context":
            exp_area = expected_lookup.get("area")
            act_area = data.get("area") or {}
            if exp_area and act_area.get("name") != exp_area.get("name"):
                failures.append(
                    f"get_area_context area.name mismatch: got {act_area.get('name')!r}, lookup has {exp_area.get('name')!r}"
                )
            exp_fac = expected_lookup.get("facilities")
            if exp_fac is not None:
                act_fac = data.get("facilities") or {}
                for block in FACILITY_BLOCKS:
                    b_act = act_fac.get(block) or {}
                    b_exp = exp_fac[block]
                    if b_act.get("count") != b_exp["count"]:
                        failures.append(
                            f"facilities.{block}.count mismatch: got {b_act.get('count')}, lookup has {b_exp['count']}"
                        )
                    examples = b_act.get("examples")
                    if not isinstance(examples, list):
                        failures.append(f"facilities.{block}.examples must be a list")
                    elif len(examples) > 10:
                        failures.append(
                            f"facilities.{block}.examples length {len(examples)} exceeds cap of 10"
                        )

        elif tool == "get_measure_details":
            exp_measures = expected_lookup["measures"]
            act_list = data.get("measures", [])
            if len(act_list) != len(exp_measures):
                failures.append(
                    f"get_measure_details count mismatch: got {len(act_list)}, expected {len(exp_measures)}"
                )
            for m in act_list:
                mk = m.get("measure_key")
                if mk not in exp_measures:
                    failures.append(f"Unexpected measure in get_measure_details: {mk!r}")
                    continue
                exp_m = exp_measures[mk]
                for fld in (
                    "product",
                    "measure_id",
                    "unit",
                    "storage_scale",
                    "period",
                    "population",
                    "value_type",
                    "levels",
                    "uncertainty_kind",
                    "periods",
                ):
                    if fld in exp_m and m.get(fld) != exp_m.get(fld):
                        failures.append(
                            f"get_measure_details[{mk}] field {fld!r} mismatch: got {m.get(fld)!r}, lookup has {exp_m.get(fld)!r}"
                        )

        elif tool == "search_measures":
            periods_by_key = expected_lookup.get("periods_by_key") or {}
            for m in data.get("measures", []):
                if not isinstance(m, dict):
                    continue
                mk = m.get("measure_key")
                if mk in periods_by_key and m.get("periods") != periods_by_key[mk]:
                    failures.append(
                        f"search_measures[{mk}] periods={m.get('periods')!r} != lookup {periods_by_key[mk]!r}"
                    )

        elif tool == "list_data_sources":
            act_prods = data.get("products", [])
            act_prod_keys = {
                p.get("product") or p.get("key") for p in act_prods if isinstance(p, dict)
            }
            if act_prod_keys != set(PUBLIC_PRODUCTS):
                failures.append(
                    f"list_data_sources products {sorted(filter(None, act_prod_keys))} != {sorted(PUBLIC_PRODUCTS)}"
                )
            if data.get("status_glossary") != expected_lookup["status_text"]:
                failures.append("list_data_sources status_glossary does not match lookup.STATUS_TEXT")
            failures.extend(
                check_list_data_sources_notes(
                    data.get("notes"),
                    expected_lookup.get("expected_period_notes"),
                )
            )

        elif tool == "get_nofo_overview":
            exp_ov = expected_lookup.get("overview") or {}
            if data.get("nofo") != exp_ov.get("nofo"):
                failures.append("get_nofo_overview data.nofo does not match funding_report.lookup")
            if data.get("aggregates") != exp_ov.get("aggregates"):
                failures.append("get_nofo_overview data.aggregates does not match funding_report.lookup")
            if data.get("subawards") != exp_ov.get("subawards"):
                failures.append("get_nofo_overview data.subawards does not match funding_report.lookup")
            if data.get("caveats") != exp_ov.get("caveats"):
                failures.append("get_nofo_overview data.caveats does not match funding_report.lookup")
            exp_src_ids = expected_lookup.get("expected_source_ids") or []
            act_src_ids = [s.get("id") for s in sources if isinstance(s, dict)]
            if act_src_ids != exp_src_ids:
                failures.append(f"get_nofo_overview source ids {act_src_ids!r} != lookup {exp_src_ids!r}")

        elif tool == "list_nofo_recipients":
            exp_list = expected_lookup.get("listing") or {}
            for fld in ("nofo_key", "fon_display", "total", "offset", "limit", "recipients"):
                if data.get(fld) != exp_list.get(fld):
                    failures.append(f"list_nofo_recipients data.{fld} does not match funding_report.lookup")
            exp_src_ids = expected_lookup.get("expected_source_ids") or []
            act_src_ids = [s.get("id") for s in sources if isinstance(s, dict)]
            if act_src_ids != exp_src_ids:
                failures.append(f"list_nofo_recipients source ids {act_src_ids!r} != lookup {exp_src_ids!r}")

        elif tool == "get_recipient_funding":
            if data.get("nofo_key") != expected_lookup.get("nofo_key"):
                failures.append(
                    f"get_recipient_funding nofo_key={data.get('nofo_key')!r} != lookup {expected_lookup.get('nofo_key')!r}"
                )
            if data.get("recipient") != expected_lookup.get("recipient"):
                failures.append("get_recipient_funding data.recipient does not match funding_report.lookup")
            exp_src_ids = expected_lookup.get("expected_source_ids") or []
            act_src_ids = [s.get("id") for s in sources if isinstance(s, dict)]
            if act_src_ids != exp_src_ids:
                failures.append(f"get_recipient_funding source ids {act_src_ids!r} != lookup {exp_src_ids!r}")

    # 5. Evaluate explicit call_checks from questions.yaml
    if "expect_match_geoid" in call_check_spec:
        target_geoid = call_check_spec["expect_match_geoid"]
        matches = data.get("matches", [])
        if not any(isinstance(m, dict) and m.get("geoid") == target_geoid for m in matches):
            failures.append(f"find_places matches did not contain geoid={target_geoid!r}: {matches!r}")
        if "expect_match_level" in call_check_spec:
            target_lvl = call_check_spec["expect_match_level"]
            if not any(
                isinstance(m, dict) and m.get("geoid") == target_geoid and m.get("level") == target_lvl
                for m in matches
            ):
                failures.append(
                    f"find_places match for {target_geoid!r} did not have level={target_lvl!r}"
                )

    if call_check_spec.get("expect_empty_matches") is True:
        matches = data.get("matches", [])
        if matches != []:
            failures.append(f"Expected empty matches list, got {matches!r}")

    if call_check_spec.get("expect_empty_measures") is True:
        measures = data.get("measures", [])
        if measures != []:
            failures.append(f"Expected empty measures list [], got {measures!r}")

    if call_check_spec.get("expect_warning_non_empty") is True:
        if not warnings:
            failures.append("Expected non-empty warnings list")

    if "expected_sources" in call_check_spec:
        exp_src = set(call_check_spec["expected_sources"])
        act_src = {s.get("product") for s in sources if isinstance(s, dict)}
        if act_src != exp_src:
            failures.append(f"Expected sources {sorted(exp_src)}, got {sorted(filter(None, act_src))}")

    if "expected_row_count" in call_check_spec:
        exp_cnt = call_check_spec["expected_row_count"]
        act_cnt = len(data.get("values", []))
        if act_cnt != exp_cnt:
            failures.append(f"Expected {exp_cnt} value rows, got {act_cnt}")

    if "spot_values" in call_check_spec:
        by_kg = {
            ((r.get("area") or {}).get("geoid"), r.get("measure_key")): r
            for r in data.get("values", [])
            if isinstance(r, dict)
        }
        for spot in call_check_spec["spot_values"]:
            k = (spot["geoid"], spot["measure_key"])
            if k not in by_kg:
                failures.append(f"Spot check row {k} not found in data.values")
                continue
            r = by_kg[k]
            if "value" in spot and r.get("value") != spot["value"]:
                failures.append(f"Spot {k} value={r.get('value')!r}, expected {spot['value']!r}")
            if "status" in spot and r.get("status") != spot["status"]:
                failures.append(f"Spot {k} status={r.get('status')!r}, expected {spot['status']!r}")
            if "uncertainty_kind" in spot and (r.get("uncertainty") or {}).get("kind") != spot["uncertainty_kind"]:
                failures.append(
                    f"Spot {k} uncertainty.kind={(r.get('uncertainty') or {}).get('kind')!r}, "
                    f"expected {spot['uncertainty_kind']!r}"
                )
            if "ci_low" in spot and (r.get("uncertainty") or {}).get("low") != spot["ci_low"]:
                failures.append(
                    f"Spot {k} uncertainty.low={(r.get('uncertainty') or {}).get('low')!r}, expected {spot['ci_low']!r}"
                )
            if "ci_high" in spot and (r.get("uncertainty") or {}).get("high") != spot["ci_high"]:
                failures.append(
                    f"Spot {k} uncertainty.high={(r.get('uncertainty') or {}).get('high')!r}, expected {spot['ci_high']!r}"
                )
            if "period" in spot and r.get("period") != spot["period"]:
                failures.append(f"Spot {k} period={r.get('period')!r}, expected {spot['period']!r}")
            if "population" in spot and r.get("population") != spot["population"]:
                failures.append(f"Spot {k} population={r.get('population')!r}, expected {spot['population']!r}")
            if "citation_contains" in spot and str(spot["citation_contains"]) not in str(r.get("citation", "")):
                failures.append(
                    f"Spot {k} citation={r.get('citation')!r} did not contain {spot['citation_contains']!r}"
                )
            if spot.get("expect_note_non_empty") is True:
                if not isinstance(r.get("note"), str) or not r["note"].strip():
                    failures.append(f"Spot {k} expected non-empty note, got {r.get('note')!r}")

    if "expected_facility_counts" in call_check_spec:
        facs = data.get("facilities") or {}
        for block, exp_count in call_check_spec["expected_facility_counts"].items():
            act_count = (facs.get(block) or {}).get("count")
            if act_count != exp_count:
                failures.append(f"Facility count for {block!r}={act_count!r}, expected {exp_count!r}")

    if "expected_related_counties_count" in call_check_spec:
        rel = data.get("related") or {}
        counties = rel.get("counties")
        if isinstance(counties, dict) and "counties" in counties:
            counties = counties["counties"]
        if not isinstance(counties, list) or len(counties) != call_check_spec["expected_related_counties_count"]:
            failures.append(
                f"Expected {call_check_spec['expected_related_counties_count']} related counties, "
                f"got {len(counties) if isinstance(counties, list) else type(counties).__name__}"
            )

    if "expected_related_districts_count" in call_check_spec:
        rel = data.get("related") or {}
        districts = rel.get("districts")
        if isinstance(districts, dict) and "districts" in districts:
            districts = districts["districts"]
        if not isinstance(districts, list) or len(districts) != call_check_spec["expected_related_districts_count"]:
            failures.append(
                f"Expected {call_check_spec['expected_related_districts_count']} related districts, "
                f"got {len(districts) if isinstance(districts, list) else type(districts).__name__}"
            )

    if "expected_total_areas" in call_check_spec:
        if data.get("total_areas") != call_check_spec["expected_total_areas"]:
            failures.append(
                f"total_areas={data.get('total_areas')!r}, expected {call_check_spec['expected_total_areas']!r}"
            )

    if "expected_with_value_count" in call_check_spec:
        act_w = len(data.get("with_value", []))
        if act_w != call_check_spec["expected_with_value_count"]:
            failures.append(
                f"len(with_value)={act_w}, expected {call_check_spec['expected_with_value_count']}"
            )

    if "expect_with_value_geoids" in call_check_spec:
        act_geoids = [(r.get("area") or {}).get("geoid") for r in data.get("with_value", [])]
        if act_geoids != call_check_spec["expect_with_value_geoids"]:
            failures.append(
                f"with_value geoids={act_geoids!r}, expected {call_check_spec['expect_with_value_geoids']!r}"
            )

    if "expected_without_value_count" in call_check_spec:
        act_wo = len(data.get("without_value", []))
        if act_wo != call_check_spec["expected_without_value_count"]:
            failures.append(
                f"len(without_value)={act_wo}, expected {call_check_spec['expected_without_value_count']}"
            )

    if "expected_without_value_geoids" in call_check_spec:
        act_geoids = [(r.get("area") or {}).get("geoid") for r in data.get("without_value", [])]
        if act_geoids != call_check_spec["expected_without_value_geoids"]:
            failures.append(
                f"without_value geoids={act_geoids!r}, expected {call_check_spec['expected_without_value_geoids']!r}"
            )

    if "expected_without_value_statuses" in call_check_spec:
        exp_statuses = {s["status"] for s in call_check_spec["expected_without_value_statuses"]}
        act_statuses = {r.get("status") for r in data.get("without_value", [])}
        if not exp_statuses.issubset(act_statuses):
            failures.append(
                f"without_value statuses {sorted(filter(None, act_statuses))} missing {sorted(exp_statuses)}"
            )

    if "expected_truncated" in call_check_spec:
        if bool(data.get("truncated")) is not bool(call_check_spec["expected_truncated"]):
            failures.append(
                f"truncated={data.get('truncated')!r}, expected {call_check_spec['expected_truncated']!r}"
            )

    if "spot_first_with_value" in call_check_spec:
        spot_first = call_check_spec["spot_first_with_value"]
        with_v = data.get("with_value", [])
        if not with_v:
            failures.append("with_value is empty; cannot check spot_first_with_value")
        else:
            first = with_v[0]
            if (first.get("area") or {}).get("geoid") != spot_first["geoid"] or first.get("value") != spot_first["value"]:
                failures.append(
                    f"First with_value row=({(first.get('area') or {}).get('geoid')}, {first.get('value')}), "
                    f"expected ({spot_first['geoid']}, {spot_first['value']})"
                )

    if "expect_measure_period" in call_check_spec:
        act_p = (data.get("measure") or {}).get("period")
        if act_p != call_check_spec["expect_measure_period"]:
            failures.append(
                f"data.measure.period={act_p!r}, expected {call_check_spec['expect_measure_period']!r}"
            )

    if "expect_measure_boundary_vintage_contains" in call_check_spec:
        sub = str(call_check_spec["expect_measure_boundary_vintage_contains"])
        bv = str((data.get("measure") or {}).get("boundary_vintage", ""))
        if sub not in bv:
            failures.append(f"data.measure.boundary_vintage={bv!r} did not contain {sub!r}")

    if call_check_spec.get("expect_measure_note_non_empty") is True:
        note_v = (data.get("measure") or {}).get("note")
        if not isinstance(note_v, str) or not note_v.strip():
            failures.append(f"Expected non-empty data.measure.note, got {note_v!r}")

    if call_check_spec.get("expect_topics_present") is True:
        topics = data.get("topics")
        if not isinstance(topics, list) or len(topics) != 6:
            failures.append(f"Expected 6 public topics in search_measures(), got {topics!r}")

    if call_check_spec.get("expect_no_withheld_topic") is True:
        topics = data.get("topics") or []
        slugs = {t.get("slug") for t in topics if isinstance(t, dict)}
        if "health-care-resources" in slugs:
            failures.append("Withheld topic 'health-care-resources' must not appear in search_measures() topics")

    if "expect_measure_keys_include" in call_check_spec:
        act_keys = {m.get("measure_key") for m in data.get("measures", []) if isinstance(m, dict)}
        for req_mk in call_check_spec["expect_measure_keys_include"]:
            if req_mk not in act_keys:
                failures.append(f"search_measures missing expected measure_key {req_mk!r}")

    if "expect_all_measures_have_level" in call_check_spec:
        req_lvl = call_check_spec["expect_all_measures_have_level"]
        for m in data.get("measures", []):
            if isinstance(m, dict) and req_lvl not in (m.get("levels") or []):
                failures.append(f"Measure {m.get('measure_key')!r} does not publish at level {req_lvl!r}")

    if call_check_spec.get("expect_search_measures_periods") is True:
        measures_list = data.get("measures", [])
        if not measures_list:
            failures.append("Expected non-empty measures list in search_measures")
        else:
            failures.extend(check_search_measures_periods(measures_list))

    if call_check_spec.get("expect_measure_details_periods") is True:
        measures_list = data.get("measures", [])
        if not measures_list:
            failures.append("Expected non-empty measures list in get_measure_details")
        else:
            failures.extend(check_measure_details_periods(measures_list))

    if "expected_measure_count" in call_check_spec:
        act_m = len(data.get("measures", []))
        if act_m != call_check_spec["expected_measure_count"]:
            failures.append(f"Expected {call_check_spec['expected_measure_count']} measures, got {act_m}")

    if "expect_public_products_exact" in call_check_spec:
        exp_set = set(call_check_spec["expect_public_products_exact"])
        act_set = {
            p.get("product") or p.get("key") for p in data.get("products", []) if isinstance(p, dict)
        }
        if act_set != exp_set:
            failures.append(f"Public products {sorted(filter(None, act_set))} != {sorted(exp_set)}")

    if call_check_spec.get("expect_excluded_ahrf") is True:
        excl = data.get("excluded") or []
        if not any(isinstance(e, dict) and e.get("product") == "ahrf" and e.get("reason") for e in excl):
            failures.append(f"list_data_sources.excluded missing 'ahrf' entry with reason: {excl!r}")

    if call_check_spec.get("expect_product_period_lines") is True:
        failures.extend(
            check_list_data_sources_notes(
                data.get("notes"),
                expected_lookup.get("expected_period_notes"),
            )
        )

    if call_check_spec.get("expect_no_ahrf_measures") is True:
        for m in data.get("measures", []):
            mk = str((m or {}).get("measure_key", ""))
            if mk.startswith("ahrf:"):
                failures.append(f"Found excluded AHRF measure in search_measures: {mk!r}")

    if call_check_spec.get("expect_over_time_series") is True:
        failures.extend(check_over_time_response(structured))

    if call_check_spec.get("expect_boundary_vintage_warning") is True:
        if not any("boundary vintage" in str(w).lower() for w in warnings):
            failures.append(f"Expected boundary-vintage warning in {warnings!r}")

    if call_check_spec.get("expect_series_has_available_and_unpublished_current") is True:
        series = data.get("series", [])
        if not isinstance(series, list) or len(series) < 2:
            failures.append(f"Expected multi-period series, got {series!r}")
        else:
            latest = series[-1]
            earlier_with_val = [r for r in series[:-1] if isinstance(r, dict) and r.get("value") is not None]
            if not isinstance(latest, dict) or latest.get("value") is not None:
                failures.append(
                    f"Expected current/latest period row in series to have value=None (unpublished), got {latest!r}"
                )
            if not earlier_with_val:
                failures.append("Expected earlier periods in series to have published non-null values")

    if call_check_spec.get("expect_no_change_computed") is True:
        failures.extend(check_no_change_keys(data))
        if not any("CHIP does not compute changes or trends" in str(r) for r in interp_rules):
            failures.append("interpretation_rules missing Rule 6 ('CHIP does not compute changes or trends')")

    if "expect_interpretation_rule_substring" in call_check_spec:
        sub = call_check_spec["expect_interpretation_rule_substring"]
        if not any(sub in str(r) for r in interp_rules):
            failures.append(f"interpretation_rules did not contain {sub!r}")

    if call_check_spec.get("expect_no_composite_measure") is True:
        for m in data.get("measures", []):
            label = str((m or {}).get("label", "")).lower()
            if "composite" in label or "overall health score" in label:
                failures.append(f"Unexpected composite score measure found: {m!r}")

    if "expect_warning_substring" in call_check_spec:
        sub = call_check_spec["expect_warning_substring"]
        if not any(sub in str(w) for w in warnings):
            failures.append(f"warnings did not contain {sub!r} (got {warnings!r})")

    if "expect_warning_substrings_any" in call_check_spec:
        subs = call_check_spec["expect_warning_substrings_any"]
        warnings_low = " ".join(str(w).lower() for w in warnings)
        if not warnings or not any(str(s).lower() in warnings_low for s in subs):
            failures.append(f"warnings {warnings!r} did not contain any of {subs!r}")

    if "expect_all_rows_population_substring" in call_check_spec:
        sub = call_check_spec["expect_all_rows_population_substring"]
        for r in data.get("values", []):
            pop = str((r or {}).get("population", ""))
            if sub not in pop:
                failures.append(f"Row {r.get('measure_key')} population {pop!r} missing {sub!r}")

    # Funding-specific call_checks (F4)
    if "expect_dataset_url_suffix" in call_check_spec:
        suf = str(call_check_spec["expect_dataset_url_suffix"])
        ds_url = str(data.get("dataset_url") or "")
        if not ds_url.endswith(suf):
            failures.append(f"dataset_url {ds_url!r} does not end with {suf!r}")

    if "expected_nofo_key" in call_check_spec:
        act_nk = (data.get("nofo") or {}).get("nofo_key") if isinstance(data.get("nofo"), dict) else data.get("nofo_key")
        if act_nk != call_check_spec["expected_nofo_key"]:
            failures.append(f"nofo_key={act_nk!r}, expected {call_check_spec['expected_nofo_key']!r}")

    if "expected_fon_display" in call_check_spec:
        act_fon = (data.get("nofo") or {}).get("fon_display") if isinstance(data.get("nofo"), dict) else data.get("fon_display")
        if act_fon != call_check_spec["expected_fon_display"]:
            failures.append(f"fon_display={act_fon!r}, expected {call_check_spec['expected_fon_display']!r}")

    if "expected_recipient_count" in call_check_spec:
        act_rc = (data.get("nofo") or {}).get("recipient_count")
        if act_rc != call_check_spec["expected_recipient_count"]:
            failures.append(f"nofo.recipient_count={act_rc!r}, expected {call_check_spec['expected_recipient_count']!r}")

    if "expected_award_count" in call_check_spec:
        act_ac = (data.get("nofo") or {}).get("award_count")
        if act_ac != call_check_spec["expected_award_count"]:
            failures.append(f"nofo.award_count={act_ac!r}, expected {call_check_spec['expected_award_count']!r}")

    if "expected_best_available_total" in call_check_spec:
        act_tot = (data.get("nofo") or {}).get("best_available_total")
        exp_tot = float(call_check_spec["expected_best_available_total"])
        if not isinstance(act_tot, (int, float)) or abs(float(act_tot) - exp_tot) > 0.02:
            failures.append(f"nofo.best_available_total={act_tot!r}, expected {exp_tot!r}")

    if call_check_spec.get("expected_subawards_null") is True:
        if data.get("subawards") is not None:
            failures.append(f"Expected data.subawards=None, got {data.get('subawards')!r}")

    if "expected_fiscal_year_accounts" in call_check_spec:
        by_y = {
            x.get("fiscal_year"): x
            for x in (data.get("nofo") or {}).get("fiscal_years", [])
            if isinstance(x, dict)
        }
        for y_key, exp_val in call_check_spec["expected_fiscal_year_accounts"].items():
            y_int = int(y_key)
            if y_int not in by_y:
                failures.append(f"Fiscal year {y_int} missing from data.nofo.fiscal_years")
                continue
            act_val = by_y[y_int].get("account_obligation")
            if not isinstance(act_val, (int, float)) or abs(float(act_val) - float(exp_val)) > 0.02:
                failures.append(f"FY{y_int} account_obligation={act_val!r}, expected {exp_val!r}")

    if "expect_null_fiscal_year_fields" in call_check_spec:
        by_y = {
            x.get("fiscal_year"): x
            for x in (data.get("nofo") or {}).get("fiscal_years", [])
            if isinstance(x, dict)
        }
        for spec_nf in call_check_spec["expect_null_fiscal_year_fields"]:
            y_int = int(spec_nf["fiscal_year"])
            fld = str(spec_nf["field"])
            if y_int not in by_y:
                failures.append(f"Fiscal year {y_int} missing for null field check {fld!r}")
            elif by_y[y_int].get(fld) is not None:
                failures.append(
                    f"FY{y_int}.{fld} must be null (never 0 when no source rows), got {by_y[y_int].get(fld)!r}"
                )

    if "expected_subaward_summary" in call_check_spec:
        sub = data.get("subawards")
        if not isinstance(sub, dict):
            failures.append(f"Expected dict data.subawards, got {sub!r}")
        else:
            for k, exp_v in call_check_spec["expected_subaward_summary"].items():
                act_v = sub.get(k)
                if isinstance(exp_v, float):
                    if not isinstance(act_v, (int, float)) or abs(float(act_v) - exp_v) > 0.02:
                        failures.append(f"subawards.{k}={act_v!r}, expected {exp_v!r}")
                elif act_v != exp_v:
                    failures.append(f"subawards.{k}={act_v!r}, expected {exp_v!r}")

    if call_check_spec.get("expect_no_subawards_added_to_prime") is True:
        failures.extend(check_funding_no_subawards_added(data))

    if "expected_total_recipients" in call_check_spec:
        if data.get("total") != call_check_spec["expected_total_recipients"]:
            failures.append(f"total={data.get('total')!r}, expected {call_check_spec['expected_total_recipients']!r}")

    if "expected_page_count" in call_check_spec:
        act_pc = len(data.get("recipients") or [])
        if act_pc != call_check_spec["expected_page_count"]:
            failures.append(f"len(recipients)={act_pc}, expected {call_check_spec['expected_page_count']}")

    if "expected_offset" in call_check_spec:
        if data.get("offset") != call_check_spec["expected_offset"]:
            failures.append(f"offset={data.get('offset')!r}, expected {call_check_spec['expected_offset']!r}")

    if "expected_first_fain" in call_check_spec:
        recs = data.get("recipients") or []
        first_fain = recs[0].get("fain") if recs and isinstance(recs[0], dict) else None
        if first_fain != call_check_spec["expected_first_fain"]:
            failures.append(f"first recipient fain={first_fain!r}, expected {call_check_spec['expected_first_fain']!r}")

    single_recipient_check_keys = {
        "expected_recipient_uei",
        "expected_recipient_fain",
        "expected_recipient_name",
        "expected_recipient_state",
        "expected_recipient_best_available",
        "expected_recipient_basis",
        "expected_recipient_subaward_actions",
        "expected_recipient_subaward_amount",
    }
    if single_recipient_check_keys & set(call_check_spec.keys()):
        rec = data.get("recipient")
        if not isinstance(rec, dict):
            failures.append(f"Expected dict data.recipient, got {rec!r}")
        else:
            if "expected_recipient_uei" in call_check_spec and rec.get("uei") != call_check_spec["expected_recipient_uei"]:
                failures.append(f"recipient.uei={rec.get('uei')!r}, expected {call_check_spec['expected_recipient_uei']!r}")
            if "expected_recipient_fain" in call_check_spec and rec.get("fain") != call_check_spec["expected_recipient_fain"]:
                failures.append(f"recipient.fain={rec.get('fain')!r}, expected {call_check_spec['expected_recipient_fain']!r}")
            if "expected_recipient_name" in call_check_spec and rec.get("recipient_name") != call_check_spec["expected_recipient_name"]:
                failures.append(f"recipient.recipient_name={rec.get('recipient_name')!r}, expected {call_check_spec['expected_recipient_name']!r}")
            if "expected_recipient_state" in call_check_spec and (rec.get("address") or {}).get("state") != call_check_spec["expected_recipient_state"]:
                failures.append(f"recipient.address.state={(rec.get('address') or {}).get('state')!r}, expected {call_check_spec['expected_recipient_state']!r}")
            if "expected_recipient_best_available" in call_check_spec:
                act_ba = (rec.get("totals") or {}).get("best_available")
                exp_ba = float(call_check_spec["expected_recipient_best_available"])
                if not isinstance(act_ba, (int, float)) or abs(float(act_ba) - exp_ba) > 0.02:
                    failures.append(f"recipient.totals.best_available={act_ba!r}, expected {exp_ba!r}")
            if "expected_recipient_basis" in call_check_spec and (rec.get("totals") or {}).get("best_available_basis") != call_check_spec["expected_recipient_basis"]:
                failures.append(
                    f"recipient.totals.best_available_basis={(rec.get('totals') or {}).get('best_available_basis')!r}, "
                    f"expected {call_check_spec['expected_recipient_basis']!r}"
                )
            if "expected_recipient_subaward_actions" in call_check_spec:
                act_sa = (rec.get("subawards") or {}).get("action_count")
                if act_sa != call_check_spec["expected_recipient_subaward_actions"]:
                    failures.append(
                        f"recipient.subawards.action_count={act_sa!r}, expected {call_check_spec['expected_recipient_subaward_actions']!r}"
                    )
            if "expected_recipient_subaward_amount" in call_check_spec:
                act_amt = (rec.get("subawards") or {}).get("reported_amount")
                exp_amt = float(call_check_spec["expected_recipient_subaward_amount"])
                if not isinstance(act_amt, (int, float)) or abs(float(act_amt) - exp_amt) > 0.02:
                    failures.append(f"recipient.subawards.reported_amount={act_amt!r}, expected {exp_amt!r}")

    return failures


# ---------------------------------------------------------------------------
# Report generation & CLI modes
# ---------------------------------------------------------------------------

def percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    low = int(math.floor(rank))
    high = int(math.ceil(rank))
    if low == high:
        return sorted_vals[low]
    weight = rank - low
    return sorted_vals[low] * (1.0 - weight) + sorted_vals[high] * weight


def get_git_commit() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(REPO_ROOT),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out or "unknown"
    except Exception:
        return "unknown"


def write_eval_report(
    report_path: Path,
    *,
    mode: str,
    server_url: str | None,
    question_results: list[dict[str, Any]],
    latencies_ms: list[float],
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    commit = get_git_commit()
    sorted_lat = sorted(latencies_ms)
    p50 = percentile(sorted_lat, 50)
    p95 = percentile(sorted_lat, 95)

    passed_count = sum(1 for r in question_results if r["passed"])
    total_count = len(question_results)

    lines: list[str] = [
        "# CHIP MCP Server Evaluation Report",
        "",
        f"- **Timestamp:** `{ts}`",
        f"- **Commit:** `{commit}`",
        f"- **Mode:** `{mode}`",
        f"- **Server URL:** `{server_url or 'N/A (no server called)'}`",
        f"- **Questions Passed:** **{passed_count} / {total_count}**",
        f"- **Total Tool Calls:** `{len(latencies_ms)}`",
        f"- **Latency p50:** `{p50:.1f} ms`" if latencies_ms else "- **Latency p50:** `N/A`",
        f"- **Latency p95:** `{p95:.1f} ms`" if latencies_ms else "- **Latency p95:** `N/A`",
        "",
        "## Summary Table",
        "",
        "| ID | Trap | Tools | Products | Levels | Latency (ms) | Result |",
        "|---|---|---|---|---|---:|---|",
    ]

    for r in question_results:
        trap_label = f"Yes (`{r['trap_kind']}`)" if r.get("trap") else "No"
        tools_str = ", ".join(f"`{t}`" for t in r["tools"])
        prods_str = ", ".join(f"`{p}`" for p in r["products"])
        lvls_str = ", ".join(f"`{l}`" for l in r["levels"])
        lat_str = f"{r['latency_ms']:.1f}" if r.get("latency_ms") is not None else "—"
        status_str = "PASS" if r["passed"] else "**FAIL**"
        lines.append(
            f"| {r['id']} | {trap_label} | {tools_str} | {prods_str} | {lvls_str} | {lat_str} | {status_str} |"
        )

    failures = [r for r in question_results if not r["passed"]]
    lines.extend(["", "## Failures", ""])
    if not failures:
        lines.append("None — all checks passed.")
    else:
        for r in failures:
            lines.append(f"### {r['id']}: {r['question']}")
            for err in r["failures"]:
                lines.append(f"- {err}")
            lines.append("")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def open_staging_db():
    """Open a read-only SQLAlchemy session using backend/.env."""
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env")
    from app.db import SessionLocal
    return SessionLocal()


def run_expected_only(questions_path: Path, report_path: Path | None = None) -> int:
    ok, summary, errors = validate_questions_yaml(questions_path)
    if not ok:
        for e in errors:
            print(f"[VALIDATE ERROR] {e}", file=sys.stderr)
        return 1

    raw = yaml.safe_load(questions_path.read_text(encoding="utf-8"))
    questions = raw["questions"]
    topics_list = load_topics()

    db = open_staging_db()
    question_results: list[dict[str, Any]] = []
    all_passed = True
    try:
        for q in questions:
            qid = q["id"]
            calls = q["expected_calls"]
            call_checks_by_idx = {
                c["call_index"]: c for c in q.get("checks", {}).get("call_checks", [])
            }
            q_failures: list[str] = []
            paging_keys: list[str] = []
            for idx, call in enumerate(calls):
                tool = call["tool"]
                args = call.get("arguments", {})
                c_check = call_checks_by_idx.get(idx, {})
                exp = compute_expected_for_call(db, tool, args, topics_list)

                if c_check.get("expect_error") is True:
                    if (
                        tool in (
                            "get_area_values",
                            "get_measure_across_areas",
                            "get_measure_over_time",
                            "search_measures",
                            *FUNDING_TOOLS,
                        )
                        and not exp.get("expect_error")
                    ):
                        q_failures.append(
                            f"Call {idx} ({tool}) expected error in YAML, but lookup succeeded"
                        )
                    elif tool in FUNDING_TOOLS and exp.get("expect_error"):
                        q_failures.extend(
                            f"Call {idx} ({tool}): {e}"
                            for e in verify_error_message_checks(str(exp.get("reason") or ""), c_check)
                        )
                elif exp.get("expect_error"):
                    q_failures.append(
                        f"Call {idx} ({tool}) unexpectedly raised lookup error: {exp.get('reason')}"
                    )
                else:
                    if "expected_row_count" in c_check and "expected_row_count" in exp:
                        if c_check["expected_row_count"] != exp["expected_row_count"]:
                            q_failures.append(
                                f"Call {idx} expected_row_count={c_check['expected_row_count']} != lookup {exp['expected_row_count']}"
                            )
                    if "expected_total_areas" in c_check and "total_areas" in exp:
                        if c_check["expected_total_areas"] != exp["total_areas"]:
                            q_failures.append(
                                f"Call {idx} expected_total_areas={c_check['expected_total_areas']} != lookup {exp['total_areas']}"
                            )
                    if "expected_without_value_count" in c_check and "without_value" in exp:
                        if c_check["expected_without_value_count"] != len(exp["without_value"]):
                            q_failures.append(
                                f"Call {idx} expected_without_value_count={c_check['expected_without_value_count']} != lookup {len(exp['without_value'])}"
                            )
                    if "expect_with_value_geoids" in c_check and "with_value" in exp:
                        exp_geoids = [r["geoid"] for r in exp["with_value"]]
                        if c_check["expect_with_value_geoids"] != exp_geoids:
                            q_failures.append(
                                f"Call {idx} expect_with_value_geoids={c_check['expect_with_value_geoids']} != lookup {exp_geoids}"
                            )
                    if "spot_values" in c_check and "rows_by_key_geoid" in exp:
                        for spot in c_check["spot_values"]:
                            lk = (spot["measure_key"], spot["geoid"])
                            row = exp["rows_by_key_geoid"].get(lk)
                            if row is None:
                                q_failures.append(f"Call {idx} spot row {lk} missing in lookup")
                            else:
                                if "value" in spot and row["value"] != spot["value"]:
                                    q_failures.append(
                                        f"Call {idx} spot {lk} value={spot['value']} != lookup {row['value']}"
                                    )
                                if "status" in spot and row["status"] != spot["status"]:
                                    q_failures.append(
                                        f"Call {idx} spot {lk} status={spot['status']!r} != lookup {row['status']!r}"
                                    )
                                if "period" in spot and row["period"] != spot["period"]:
                                    q_failures.append(
                                        f"Call {idx} spot {lk} period={spot['period']!r} != lookup {row['period']!r}"
                                    )

                    # Funding lookup ground-truth checks (--expected-only)
                    if tool == "get_nofo_overview":
                        ov = exp["overview"]
                        nofo = ov["nofo"]
                        q_failures.extend(
                            f"Call {idx} ({tool}): {e}"
                            for e in check_no_area_sources_in_funding(ov.get("sources"))
                        )
                        q_failures.extend(
                            f"Call {idx} ({tool}): {e}"
                            for e in check_funding_fiscal_years_ordered(nofo.get("fiscal_years"), "nofo.fiscal_years")
                        )
                        q_failures.extend(
                            f"Call {idx} ({tool}): {e}"
                            for e in check_funding_no_subawards_added(ov)
                        )
                        if "expected_nofo_key" in c_check and nofo["nofo_key"] != c_check["expected_nofo_key"]:
                            q_failures.append(f"Call {idx} nofo_key={nofo['nofo_key']!r} != {c_check['expected_nofo_key']!r}")
                        if "expected_fon_display" in c_check and nofo["fon_display"] != c_check["expected_fon_display"]:
                            q_failures.append(f"Call {idx} fon_display={nofo['fon_display']!r} != {c_check['expected_fon_display']!r}")
                        if "expected_recipient_count" in c_check and nofo["recipient_count"] != c_check["expected_recipient_count"]:
                            q_failures.append(f"Call {idx} recipient_count={nofo['recipient_count']!r} != {c_check['expected_recipient_count']!r}")
                        if "expected_award_count" in c_check and nofo["award_count"] != c_check["expected_award_count"]:
                            q_failures.append(f"Call {idx} award_count={nofo['award_count']!r} != {c_check['expected_award_count']!r}")
                        if "expected_best_available_total" in c_check:
                            if abs(float(nofo["best_available_total"] or 0) - float(c_check["expected_best_available_total"])) > 0.02:
                                q_failures.append(
                                    f"Call {idx} best_available_total={nofo['best_available_total']} != {c_check['expected_best_available_total']}"
                                )
                        if c_check.get("expected_subawards_null") is True and ov.get("subawards") is not None:
                            q_failures.append(f"Call {idx} expected subawards=None, got {ov.get('subawards')!r}")
                        if "expected_fiscal_year_accounts" in c_check:
                            by_y = {x["fiscal_year"]: x for x in nofo["fiscal_years"]}
                            for y_k, exp_v in c_check["expected_fiscal_year_accounts"].items():
                                y_i = int(y_k)
                                if y_i not in by_y or abs(float(by_y[y_i]["account_obligation"] or 0) - float(exp_v)) > 0.02:
                                    q_failures.append(f"Call {idx} FY{y_i} account_obligation={by_y.get(y_i, {}).get('account_obligation')} != {exp_v}")
                        if "expect_null_fiscal_year_fields" in c_check:
                            by_y = {x["fiscal_year"]: x for x in nofo["fiscal_years"]}
                            for spec_nf in c_check["expect_null_fiscal_year_fields"]:
                                y_i = int(spec_nf["fiscal_year"])
                                fld = str(spec_nf["field"])
                                if y_i not in by_y or by_y[y_i].get(fld) is not None:
                                    q_failures.append(f"Call {idx} FY{y_i}.{fld} expected None, got {by_y.get(y_i, {}).get(fld)!r}")
                        if "expected_subaward_summary" in c_check:
                            sub = ov.get("subawards") or {}
                            for k, exp_v in c_check["expected_subaward_summary"].items():
                                act_v = sub.get(k)
                                if isinstance(exp_v, float):
                                    if not isinstance(act_v, (int, float)) or abs(float(act_v) - exp_v) > 0.02:
                                        q_failures.append(f"Call {idx} subawards.{k}={act_v!r} != {exp_v!r}")
                                elif act_v != exp_v:
                                    q_failures.append(f"Call {idx} subawards.{k}={act_v!r} != {exp_v!r}")
                        if "expect_warning_substring" in c_check:
                            sub_txt = c_check["expect_warning_substring"]
                            if not any(sub_txt in str(c) for c in ov.get("caveats", [])):
                                q_failures.append(f"Call {idx} caveats missing {sub_txt!r}")

                    elif tool == "list_nofo_recipients":
                        listing = exp["listing"]
                        q_failures.extend(
                            f"Call {idx} ({tool}): {e}"
                            for e in check_funding_recipients_sorted(listing.get("recipients"), "listing.recipients")
                        )
                        if "expected_nofo_key" in c_check and listing["nofo_key"] != c_check["expected_nofo_key"]:
                            q_failures.append(f"Call {idx} nofo_key={listing['nofo_key']!r} != {c_check['expected_nofo_key']!r}")
                        if "expected_total_recipients" in c_check and listing["total"] != c_check["expected_total_recipients"]:
                            q_failures.append(f"Call {idx} total={listing['total']!r} != {c_check['expected_total_recipients']!r}")
                        if "expected_page_count" in c_check and len(listing["recipients"]) != c_check["expected_page_count"]:
                            q_failures.append(f"Call {idx} page count={len(listing['recipients'])} != {c_check['expected_page_count']}")
                        if "expected_offset" in c_check and listing["offset"] != c_check["expected_offset"]:
                            q_failures.append(f"Call {idx} offset={listing['offset']} != {c_check['expected_offset']}")
                        if "expected_first_fain" in c_check:
                            first_f = listing["recipients"][0]["fain"] if listing["recipients"] else None
                            if first_f != c_check["expected_first_fain"]:
                                q_failures.append(f"Call {idx} first fain={first_f!r} != {c_check['expected_first_fain']!r}")
                        paging_keys.extend(r["award_unique_key"] for r in listing["recipients"])

                    elif tool == "get_recipient_funding":
                        rec = exp["recipient"]
                        q_failures.extend(
                            f"Call {idx} ({tool}): {e}"
                            for e in check_funding_fiscal_years_ordered(rec.get("fiscal_years"), "recipient.fiscal_years")
                        )
                        q_failures.extend(
                            f"Call {idx} ({tool}): {e}"
                            for e in _check_recipient_null_vs_zero(rec, "recipient")
                        )
                        if "expected_nofo_key" in c_check and exp["nofo_key"] != c_check["expected_nofo_key"]:
                            q_failures.append(f"Call {idx} nofo_key={exp['nofo_key']!r} != {c_check['expected_nofo_key']!r}")
                        if "expected_recipient_uei" in c_check and rec.get("uei") != c_check["expected_recipient_uei"]:
                            q_failures.append(f"Call {idx} recipient.uei={rec.get('uei')!r} != {c_check['expected_recipient_uei']!r}")
                        if "expected_recipient_fain" in c_check and rec.get("fain") != c_check["expected_recipient_fain"]:
                            q_failures.append(f"Call {idx} recipient.fain={rec.get('fain')!r} != {c_check['expected_recipient_fain']!r}")
                        if "expected_recipient_name" in c_check and rec.get("recipient_name") != c_check["expected_recipient_name"]:
                            q_failures.append(f"Call {idx} recipient.recipient_name={rec.get('recipient_name')!r} != {c_check['expected_recipient_name']!r}")
                        if "expected_recipient_state" in c_check and (rec.get("address") or {}).get("state") != c_check["expected_recipient_state"]:
                            q_failures.append(f"Call {idx} recipient.state={(rec.get('address') or {}).get('state')!r} != {c_check['expected_recipient_state']!r}")
                        if "expected_recipient_best_available" in c_check:
                            if abs(float(rec["totals"]["best_available"] or 0) - float(c_check["expected_recipient_best_available"])) > 0.02:
                                q_failures.append(f"Call {idx} recipient best_available={rec['totals']['best_available']} != {c_check['expected_recipient_best_available']}")
                        if "expected_recipient_basis" in c_check and rec["totals"].get("best_available_basis") != c_check["expected_recipient_basis"]:
                            q_failures.append(f"Call {idx} recipient basis={rec['totals'].get('best_available_basis')!r} != {c_check['expected_recipient_basis']!r}")
                        if "expected_recipient_subaward_actions" in c_check:
                            if (rec.get("subawards") or {}).get("action_count") != c_check["expected_recipient_subaward_actions"]:
                                q_failures.append(f"Call {idx} recipient subaward actions={(rec.get('subawards') or {}).get('action_count')!r} != {c_check['expected_recipient_subaward_actions']!r}")
                        if "expected_recipient_subaward_amount" in c_check:
                            if abs(float((rec.get("subawards") or {}).get("reported_amount") or 0) - float(c_check["expected_recipient_subaward_amount"])) > 0.02:
                                q_failures.append(f"Call {idx} recipient subaward amount={(rec.get('subawards') or {}).get('reported_amount')!r} != {c_check['expected_recipient_subaward_amount']!r}")

            if "expect_paging_union_total" in q.get("checks", {}):
                exp_union = int(q["checks"]["expect_paging_union_total"])
                if len(paging_keys) != len(set(paging_keys)):
                    q_failures.append(f"Paging returned duplicate recipients across pages ({len(paging_keys)} total vs {len(set(paging_keys))} unique)")
                if len(set(paging_keys)) != exp_union:
                    q_failures.append(f"Paging union count {len(set(paging_keys))} != expected {exp_union}")

            passed = len(q_failures) == 0
            if not passed:
                all_passed = False
            question_results.append({
                "id": qid,
                "question": q["question"],
                "trap": bool(q.get("trap")),
                "trap_kind": q.get("trap_kind"),
                "tools": [c["tool"] for c in calls],
                "products": q.get("products", []),
                "levels": q.get("levels", []),
                "latency_ms": None,
                "passed": passed,
                "failures": q_failures,
            })
            status_tag = "OK" if passed else "FAIL"
            print(f"[{status_tag}] {qid}: {q['question']}")
            for err in q_failures:
                print(f"    -> {err}")
    finally:
        db.close()

    if report_path is not None:
        write_eval_report(
            report_path,
            mode="expected-only",
            server_url=None,
            question_results=question_results,
            latencies_ms=[],
        )

    passed_total = sum(1 for r in question_results if r["passed"])
    print(f"\nExpected-only summary: {passed_total}/{len(question_results)} questions verified against lookup.")
    return 0 if all_passed else 1


async def run_live_eval(
    url: str,
    questions_path: Path,
    report_path: Path,
) -> int:
    from mcp import Client

    ok, _, errors = validate_questions_yaml(questions_path)
    if not ok:
        for e in errors:
            print(f"[VALIDATE ERROR] {e}", file=sys.stderr)
        return 1

    raw = yaml.safe_load(questions_path.read_text(encoding="utf-8"))
    questions = raw["questions"]
    topics_list = load_topics()

    db = open_staging_db()
    question_results: list[dict[str, Any]] = []
    latencies_ms: list[float] = []
    all_passed = True

    try:
        async with Client(url) as client:
            for q in questions:
                qid = q["id"]
                calls = q["expected_calls"]
                match_lookup_flag = bool(q.get("checks", {}).get("match_lookup", False))
                call_checks_by_idx = {
                    c["call_index"]: c for c in q.get("checks", {}).get("call_checks", [])
                }
                q_failures: list[str] = []
                q_latencies: list[float] = []
                paging_keys: list[str] = []

                for idx, call in enumerate(calls):
                    tool = call["tool"]
                    args = call.get("arguments", {})
                    c_check = call_checks_by_idx.get(idx, {})
                    exp_lookup = compute_expected_for_call(db, tool, args, topics_list)

                    t0 = time.perf_counter()
                    try:
                        res = await client.call_tool(tool, args)
                    except Exception as exc:
                        dt_ms = (time.perf_counter() - t0) * 1000.0
                        latencies_ms.append(dt_ms)
                        q_latencies.append(dt_ms)
                        if c_check.get("expect_error") is True:
                            err_checks = verify_error_message_checks(str(exc), c_check)
                            for e in err_checks:
                                q_failures.append(f"Call {idx} ({tool}): {e}")
                        else:
                            q_failures.append(f"Call {idx} ({tool}) raised exception: {exc}")
                        continue

                    dt_ms = (time.perf_counter() - t0) * 1000.0
                    latencies_ms.append(dt_ms)
                    q_latencies.append(dt_ms)

                    call_errs = verify_call_against_lookup_and_checks(
                        tool=tool,
                        arguments=args,
                        call_result=res,
                        expected_lookup=exp_lookup,
                        call_check_spec=c_check,
                        match_lookup_flag=match_lookup_flag,
                    )
                    for e in call_errs:
                        q_failures.append(f"Call {idx} ({tool}): {e}")
                    if tool == "list_nofo_recipients" and not getattr(res, "is_error", False):
                        sc = getattr(res, "structured_content", None) or {}
                        for rec in (sc.get("data") or {}).get("recipients") or []:
                            if isinstance(rec, dict) and rec.get("award_unique_key"):
                                paging_keys.append(rec["award_unique_key"])

                if "expect_paging_union_total" in q.get("checks", {}):
                    exp_union = int(q["checks"]["expect_paging_union_total"])
                    if len(paging_keys) != len(set(paging_keys)):
                        q_failures.append(
                            f"Paging returned duplicate recipients across pages ({len(paging_keys)} total vs {len(set(paging_keys))} unique)"
                        )
                    if len(set(paging_keys)) != exp_union:
                        q_failures.append(f"Paging union count {len(set(paging_keys))} != expected {exp_union}")

                passed = len(q_failures) == 0
                if not passed:
                    all_passed = False
                question_results.append({
                    "id": qid,
                    "question": q["question"],
                    "trap": bool(q.get("trap")),
                    "trap_kind": q.get("trap_kind"),
                    "tools": [c["tool"] for c in calls],
                    "products": q.get("products", []),
                    "levels": q.get("levels", []),
                    "latency_ms": sum(q_latencies),
                    "passed": passed,
                    "failures": q_failures,
                })
                status_tag = "PASS" if passed else "FAIL"
                print(f"[{status_tag}] {qid} ({sum(q_latencies):.1f} ms): {q['question']}")
                for err in q_failures:
                    print(f"    -> {err}")
    finally:
        db.close()

    write_eval_report(
        report_path,
        mode="live-mcp",
        server_url=url,
        question_results=question_results,
        latencies_ms=latencies_ms,
    )

    sorted_lat = sorted(latencies_ms)
    p50 = percentile(sorted_lat, 50)
    p95 = percentile(sorted_lat, 95)
    passed_total = sum(1 for r in question_results if r["passed"])
    print(
        f"\nEval complete: {passed_total}/{len(question_results)} questions passed | "
        f"calls={len(latencies_ms)} | p50={p50:.1f} ms | p95={p95:.1f} ms | report={report_path}"
    )
    return 0 if all_passed else 1


def _origin_from_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid server URL: {url!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


def run_dataset_check(server_url: str, nofo_key: str = "PS212102") -> int:
    """Fetch GET /funding/nofo/{nofo_key}.json?subawards=1 and validate the v1 contract."""
    origin = _origin_from_url(server_url)
    target_url = f"{origin}/funding/nofo/{nofo_key}.json?subawards=1"
    req = urllib.request.Request(target_url, headers={"Accept-Encoding": "gzip"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            headers = {k.lower(): v for k, v in resp.headers.items()}
            raw_bytes = resp.read()
    except urllib.error.HTTPError as exc:
        print(f"[FAIL] GET {target_url} returned HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[FAIL] GET {target_url} failed: {exc}", file=sys.stderr)
        return 1
    dt_ms = (time.perf_counter() - t0) * 1000.0

    failures: list[str] = []
    if status != 200:
        failures.append(f"Expected HTTP 200, got {status}")
    if "etag" not in headers:
        failures.append("Response missing ETag header")
    if "max-age=3600" not in headers.get("cache-control", ""):
        failures.append(f"Expected Cache-Control public, max-age=3600; got {headers.get('cache-control')!r}")

    encoding = headers.get("content-encoding", "").lower()
    if encoding == "gzip":
        try:
            raw_bytes = gzip.decompress(raw_bytes)
        except Exception as exc:
            failures.append(f"Failed to gunzip response body: {exc}")
            raw_bytes = b""

    try:
        dataset = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        print(f"[FAIL] Invalid JSON from {target_url}: {exc}", file=sys.stderr)
        return 1

    expected_ds: dict[str, Any] | None = None
    try:
        db = open_staging_db()
        try:
            expected_ds = funding_lookup.nofo_dataset(db, nofo_key, True)
        finally:
            db.close()
    except Exception:
        expected_ds = None

    failures.extend(check_nofo_dataset_v1(dataset, expect_subawards=True, expected_dataset=expected_ds))

    if failures:
        print(f"[FAIL] Dataset check failed for {target_url} ({dt_ms:.1f} ms):", file=sys.stderr)
        for err in failures:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(
        f"[PASS] Dataset check passed for {target_url} ({dt_ms:.1f} ms) | "
        f"schema={dataset['schema_version']} | recipients={len(dataset['recipients'])} | "
        f"fiscal_years={len(dataset['nofo']['fiscal_years'])} | "
        f"subaward_actions={dataset['subawards']['summary']['actions']}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CHIP MCP Server deterministic evaluation runner")
    parser.add_argument(
        "--questions",
        type=Path,
        default=DEFAULT_QUESTIONS_PATH,
        help="Path to questions.yaml",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate questions.yaml offline without touching the database or server",
    )
    parser.add_argument(
        "--expected-only",
        action="store_true",
        help="Compute and verify expected values from lookup layers without a server",
    )
    parser.add_argument(
        "--dataset-check",
        action="store_true",
        help="Fetch GET /funding/nofo/PS212102.json?subawards=1 from --url (default http://127.0.0.1:8011) and validate v1 contract",
    )
    parser.add_argument(
        "--nofo",
        type=str,
        default="PS212102",
        help="NOFO key for --dataset-check (default: PS212102)",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=None,
        help="MCP Streamable HTTP server URL (e.g. http://127.0.0.1:8011/mcp)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Path to write markdown report (default: deliverables/mcp/eval_report.md)",
    )
    args = parser.parse_args(argv)

    if args.validate:
        ok, summary, errors = validate_questions_yaml(args.questions)
        print(json.dumps(summary, indent=2))
        if not ok:
            for e in errors:
                print(f"ERROR: {e}", file=sys.stderr)
            return 1
        if args.report is not None:
            raw = yaml.safe_load(args.questions.read_text(encoding="utf-8"))
            q_results = [
                {
                    "id": q["id"],
                    "question": q["question"],
                    "trap": bool(q.get("trap")),
                    "trap_kind": q.get("trap_kind"),
                    "tools": [c["tool"] for c in q["expected_calls"]],
                    "products": q.get("products", []),
                    "levels": q.get("levels", []),
                    "latency_ms": None,
                    "passed": True,
                    "failures": [],
                }
                for q in raw["questions"]
            ]
            write_eval_report(
                args.report,
                mode="validate-offline (awaiting F4 live server run)",
                server_url=None,
                question_results=q_results,
                latencies_ms=[],
            )
        print("Validation PASSED.")
        return 0

    if args.expected_only:
        return run_expected_only(args.questions, report_path=args.report)

    if args.dataset_check:
        base = args.url or "http://127.0.0.1:8011"
        return run_dataset_check(base, nofo_key=args.nofo)

    if args.url:
        report_path = args.report or DEFAULT_REPORT_PATH
        return asyncio.run(run_live_eval(args.url, args.questions, report_path))

    parser.error("Provide one of --validate, --expected-only, --dataset-check, or --url http://127.0.0.1:<port>/mcp")
    return 2


if __name__ == "__main__":
    sys.exit(main())
