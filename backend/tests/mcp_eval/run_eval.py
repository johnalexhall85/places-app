#!/usr/bin/env python3
"""Deterministic evaluation runner for the CHIP MCP server (Task M3).

Modes:
  --validate        Validate questions.yaml structure and coverage offline (no DB or server).
  --expected-only   Compute expected values directly from app.area_pilot.lookup against places_staging.
  --url URL         Run all expected_calls against the MCP server at URL, compare to lookup, and run checks.
  --report PATH     Write markdown evaluation report to PATH (default: deliverables/mcp/eval_report.md).
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import math
import os
import re
import subprocess
import sys
import time
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

DEFAULT_QUESTIONS_PATH = Path(__file__).resolve().parent / "questions.yaml"
DEFAULT_REPORT_PATH = REPO_ROOT / "deliverables" / "mcp" / "eval_report.md"
TOPICS_PATH = BACKEND_DIR / "app" / "community" / "topics.json"

ALL_TOOLS: tuple[str, ...] = (
    "find_places",
    "search_measures",
    "get_measure_details",
    "get_area_values",
    "get_measure_across_areas",
    "get_area_context",
    "list_data_sources",
)

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

ALL_LEVELS: tuple[str, ...] = ("state", "county", "tract", "cd")

SHOWCASE_GEOIDS: tuple[str, ...] = ("37145", "54039", "06019", "5401")

REQUIRED_TRAP_KINDS: tuple[str, ...] = (
    "ahrf_excluded",
    "time_trend_one_period",
    "no_composite_score",
    "epa_aqi_no_monitor",
    "kentucky_brfss_not_published",
    "cms_not_published_for_cd",
    "tracts_require_county",
    "medicare_original_beneficiaries",
)

GENERAL_INTERPRETATION_RULES: tuple[str, ...] = (
    "Values are published by the named source for exactly the area shown; CHIP never adds, averages, or derives values across areas.",
    "A missing, suppressed, or not-published value is not zero; read `status_text`.",
    "Each value has its own period, population, and source; do not treat different periods or populations as directly comparable without saying so.",
    "Medicare (cms_gv) measures describe Original Medicare beneficiaries, not all residents.",
    "TRI facilities are facilities that report to EPA's Toxics Release Inventory; reporting does not mean a release, a violation, or a health risk.",
    "Each measure has one published period in CHIP; there is no time series.",
)

ORDERING_WARNING = (
    "Order is by point estimate. Where uncertainty ranges overlap, the difference may not be meaningful. "
    "This is a list of one published measure, not a ranking of overall health."
)

MAX_RESPONSE_BYTES = 60_000

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
    "source_credit",
    "citation",
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


def check_no_ahrf(payload: Any, *, allow_excluded_list: bool = False) -> list[str]:
    """Verify 'ahrf' never appears anywhere in the serialized output.

    When `allow_excluded_list=True` (for `list_data_sources`), `data.excluded` is
    removed prior to scanning because TOOL_CONTRACT.md §7 specifies
    `excluded: [{"product": "ahrf", ...}]`.
    """
    target = payload
    if allow_excluded_list and isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        target = copy.deepcopy(payload)
        target["data"].pop("excluded", None)
    serialized = json.dumps(target, ensure_ascii=False)
    if "ahrf" in serialized.lower():
        return ["Found forbidden 'ahrf' reference in serialized response output"]
    return []


def check_response_size(
    payload: Any,
    raw_text: str | None = None,
    max_bytes: int = MAX_RESPONSE_BYTES,
) -> list[str]:
    """Verify serialized response size is under max_bytes (60,000 bytes)."""
    serialized_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    if serialized_bytes > max_bytes:
        return [f"Serialized response size {serialized_bytes} bytes exceeds cap of {max_bytes} bytes"]
    if raw_text is not None:
        raw_bytes = len(raw_text.encode("utf-8"))
        # Only fail on raw_text if compact JSON also exceeds or if raw_text is compact
        if raw_bytes > max_bytes and "\n  " not in raw_text:
            return [f"Raw text response size {raw_bytes} bytes exceeds cap of {max_bytes} bytes"]
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
        # Split camelCase and snake_case tokens
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


def check_competition_positions(
    with_value_rows: list[dict[str, Any]],
    sort_mode: str = "value_desc",
) -> list[str]:
    """Check sort order and competition position numbering (1, 2, 2, 4) on with_value rows."""
    failures: list[str] = []
    values: list[float | int] = []
    actual_positions: list[int] = []
    geoids: list[str] = []

    for idx, row in enumerate(with_value_rows):
        val = row.get("value")
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            failures.append(f"with_value[{idx}] has null or non-numeric value: {val!r}")
            return failures
        pos = row.get("position")
        if not isinstance(pos, int) or isinstance(pos, bool) or pos < 1:
            failures.append(f"with_value[{idx}] has invalid position: {pos!r}")
            return failures
        values.append(val)
        actual_positions.append(pos)
        area = row.get("area") or {}
        geoids.append(str(area.get("geoid", "")))

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
        expected_adjacent = compute_competition_positions(values)
        sequential = list(range(1, len(values) + 1))
        # Also allow competition rank computed by value_desc or value_asc
        desc_rank_map: dict[float | int, int] = {}
        for idx, v in enumerate(sorted(values, reverse=True)):
            desc_rank_map.setdefault(v, idx + 1)
        asc_rank_map: dict[float | int, int] = {}
        for idx, v in enumerate(sorted(values)):
            asc_rank_map.setdefault(v, idx + 1)
        by_desc = [desc_rank_map[v] for v in values]
        by_asc = [asc_rank_map[v] for v in values]
        if actual_positions not in (expected_adjacent, sequential, by_desc, by_asc):
            failures.append(
                f"Positions under sort='geoid' did not match competition numbering: got {actual_positions[:10]}"
            )
    else:
        failures.append(f"Unknown sort_mode {sort_mode!r}")

    return failures


def check_without_value_rows(without_value_rows: list[dict[str, Any]]) -> list[str]:
    """Check that every row in without_value has null value, status/status_text, and GEOID order."""
    failures: list[str] = []
    prev_geoid = ""
    for idx, row in enumerate(without_value_rows):
        if row.get("value") is not None:
            failures.append(f"without_value[{idx}] has non-null value: {row.get('value')!r}")
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


def check_value_row_shape(row: dict[str, Any], *, allow_position: bool = False) -> list[str]:
    """Verify a single value row conforms to TOOL_CONTRACT.md §Value row."""
    failures: list[str] = []
    if not isinstance(row, dict):
        return [f"Value row is not a dict: {type(row).__name__}"]

    missing = VALUE_ROW_REQUIRED_KEYS - set(row.keys())
    if missing:
        failures.append(f"Value row missing required keys: {sorted(missing)}")

    allowed = VALUE_ROW_REQUIRED_KEYS | (
        {"position"} if (allow_position or row.get("position") is None) else set()
    )
    extra = set(row.keys()) - allowed
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

    citation = row.get("citation")
    if not isinstance(citation, str) or not citation.startswith("Source: ") or "release " not in citation:
        failures.append(f"Row {measure_key!r} has invalid citation format: {citation!r}")

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


def check_envelope(
    payload: Any,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> list[str]:
    """Run global contract checks on a structured tool response."""
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

    # Global checks required by M3
    failures.extend(
        check_no_ahrf(payload, allow_excluded_list=(tool_name == "list_data_sources"))
    )
    failures.extend(check_response_size(payload))
    failures.extend(check_forbidden_words(payload))

    # General interpretation rules check
    norm_actual_rules = {_norm_rule(r) for r in payload["interpretation_rules"] if isinstance(r, str)}
    for expected_rule in GENERAL_INTERPRETATION_RULES:
        if _norm_rule(expected_rule) not in norm_actual_rules:
            failures.append(f"Missing general interpretation rule: {expected_rule!r}")

    data = payload["data"]
    args = arguments or {}

    if tool_name == "get_area_values":
        values = data.get("values")
        if not isinstance(values, list):
            failures.append("get_area_values data.values must be a list")
        else:
            for idx, row in enumerate(values):
                row_errs = check_value_row_shape(row, allow_position=False)
                if row_errs:
                    failures.extend([f"values[{idx}]: {e}" for e in row_errs])
                    if len(failures) > 15:
                        break
            row_products = {
                row["measure_key"].split(":", 1)[0]
                for row in values
                if isinstance(row, dict) and isinstance(row.get("measure_key"), str) and ":" in row["measure_key"]
            }
            source_products = {
                s.get("product") for s in payload["sources"] if isinstance(s, dict)
            }
            if row_products != source_products:
                failures.append(
                    f"sources products {sorted(filter(None, source_products))} do not match "
                    f"data products {sorted(row_products)}"
                )

    elif tool_name == "get_measure_across_areas":
        with_val = data.get("with_value")
        without_val = data.get("without_value")
        if not isinstance(with_val, list):
            failures.append("get_measure_across_areas data.with_value must be a list")
        if not isinstance(without_val, list):
            failures.append("get_measure_across_areas data.without_value must be a list")
        if isinstance(with_val, list) and isinstance(without_val, list):
            for idx, row in enumerate(with_val):
                row_errs = check_value_row_shape(row, allow_position=True)
                if row_errs:
                    failures.extend([f"with_value[{idx}]: {e}" for e in row_errs])
                    if len(failures) > 15:
                        break
            for idx, row in enumerate(without_val):
                row_errs = check_value_row_shape(row, allow_position=True)
                if row_errs:
                    failures.extend([f"without_value[{idx}]: {e}" for e in row_errs])
                    if len(failures) > 15:
                        break

            sort_mode = args.get("sort", "geoid")
            failures.extend(check_competition_positions(with_val, sort_mode=sort_mode))
            failures.extend(check_without_value_rows(without_val))

            if sort_mode in ("value_desc", "value_asc"):
                if not any(ORDERING_WARNING in w for w in payload["warnings"] if isinstance(w, str)):
                    failures.append(
                        f"Missing required ordering warning on sort={sort_mode!r}: {ORDERING_WARNING!r}"
                    )

            if data.get("truncated") is True:
                if not any(
                    ("Showing " in w or "truncated" in w.lower() or "60,000" in w)
                    for w in payload["warnings"]
                    if isinstance(w, str)
                ):
                    failures.append("data.truncated is True, but warnings has no truncation notice")

            all_rows = with_val + without_val
            row_products = {
                row["measure_key"].split(":", 1)[0]
                for row in all_rows
                if isinstance(row, dict) and isinstance(row.get("measure_key"), str) and ":" in row["measure_key"]
            }
            source_products = {
                s.get("product") for s in payload["sources"] if isinstance(s, dict)
            }
            if all_rows and row_products != source_products:
                failures.append(
                    f"sources products {sorted(filter(None, source_products))} do not match "
                    f"data products {sorted(row_products)}"
                )

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
    if len(questions) < 35:
        errors.append(f"Expected around 40 questions (>=35), found {len(questions)}")

    reg_measures = load_registry_measures_offline()
    topics_data = json.loads(TOPICS_PATH.read_text(encoding="utf-8"))
    valid_topics = {t["slug"] for t in topics_data}

    seen_ids: set[str] = set()
    tool_counts: dict[str, int] = {t: 0 for t in ALL_TOOLS}
    product_counts: dict[str, int] = {p: 0 for p in PUBLIC_PRODUCTS + FACILITY_BLOCKS + ("ahrf",)}
    level_counts: dict[str, int] = {lvl: 0 for lvl in ALL_LEVELS}
    trap_questions: list[dict[str, Any]] = []
    trap_kinds_seen: set[str] = set()
    geoids_seen: set[str] = set()
    within_seen: set[str] = set()

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

            # Track GEOIDs and within values for showcase/state coverage checks
            if "geoid" in args and isinstance(args["geoid"], str):
                geoids_seen.add(args["geoid"])
            if "geoids" in args and isinstance(args["geoids"], list):
                for g in args["geoids"]:
                    geoids_seen.add(str(g))
            if "within" in args and args["within"] is not None:
                within_seen.add(str(args["within"]))
            if "level" in args and args["level"] in level_counts:
                level_counts[args["level"]] += 1

            # Validate measure_key / measure_keys / topic references offline
            if "topic" in args and args["topic"] is not None:
                if args["topic"] not in valid_topics:
                    errors.append(f"{qid} call[{c_idx}]: unknown topic {args['topic']!r}")
            if "measure_key" in args and isinstance(args["measure_key"], str):
                mk = args["measure_key"]
                if mk not in reg_measures and not q.get("trap"):
                    errors.append(f"{qid} call[{c_idx}]: unknown measure_key {mk!r}")
            if "measure_keys" in args and isinstance(args["measure_keys"], list):
                for mk in args["measure_keys"]:
                    if mk not in reg_measures and not q.get("trap"):
                        errors.append(f"{qid} call[{c_idx}]: unknown measure_key {mk!r}")

    # Coverage checks required by M3-antigravity.md
    for tool, count in tool_counts.items():
        if count == 0:
            errors.append(f"Tool {tool!r} has 0 calls across questions.yaml")

    for prod in PUBLIC_PRODUCTS + FACILITY_BLOCKS:
        if product_counts[prod] == 0:
            errors.append(f"Public product / facility block {prod!r} is not covered in questions.yaml")

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

    if len(trap_questions) < 8:
        errors.append(f"At least 8 trap questions required, found {len(trap_questions)}")

    missing_traps = set(REQUIRED_TRAP_KINDS) - trap_kinds_seen
    if missing_traps:
        errors.append(f"Missing required trap kinds: {sorted(missing_traps)}")

    summary = {
        "total_questions": len(questions),
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

        if measure_keys:
            for mk in measure_keys:
                if str(mk).startswith("ahrf:"):
                    return {"expect_error": True, "reason": "Excluded product ahrf requested"}

        # Determine requested (product, measure_id) pairs
        cat = lookup.catalog(db)
        by_key = {
            f"{m['product']}:{m['measure_id']}": m
            for m in cat["measures"]
            if m["product"] in PUBLIC_PRODUCTS
        }

        selected_keys: list[str] = []
        skipped_unpublished: list[tuple[str, list[str]]] = []
        if measure_keys:
            for mk in measure_keys:
                meta = by_key.get(mk)
                if meta:
                    if level in meta["levels"]:
                        selected_keys.append(mk)
                    else:
                        skipped_unpublished.append((mk, meta["levels"]))
        elif topic_slug:
            topic_obj = next((t for t in topics_list if t["slug"] == topic_slug), None)
            if topic_obj:
                for prod, mid in topic_obj["measure_keys"]:
                    if prod in PUBLIC_PRODUCTS:
                        mk = f"{prod}:{mid}"
                        meta = by_key.get(mk)
                        if meta and level in meta["levels"]:
                            selected_keys.append(mk)
        else:
            for mk, meta in by_key.items():
                if level in meta["levels"]:
                    selected_keys.append(mk)

        estimated_rows = len(geoids) * len(selected_keys)
        if estimated_rows > 400:
            return {
                "expect_error": True,
                "reason": f"Row count {estimated_rows} exceeds 400-row cap",
                "estimated_rows": estimated_rows,
            }

        if not selected_keys:
            return {
                "expect_error_or_empty": True,
                "skipped_unpublished": skipped_unpublished,
                "rows_by_key_geoid": {},
                "expected_sources": [],
                "area_names": {},
            }

        prods = list(dict.fromkeys(mk.split(":", 1)[0] for mk in selected_keys))
        mids = list(dict.fromkeys(mk.split(":", 1)[1] for mk in selected_keys))
        raw = lookup.area_values(db, level, geoids, products=prods, measure_ids=mids)
        infos = {r["geoid"]: r["name"] for r in lookup.area_info(db, level, geoids)}

        selected_set = set(selected_keys)
        rows_by_key_geoid: dict[tuple[str, str], dict[str, Any]] = {}
        products_in_data: set[str] = set()
        for r in raw["values"]:
            mk = f"{r['product']}:{r['measure_id']}"
            if mk not in selected_set:
                continue
            rows_by_key_geoid[(mk, r["geoid"])] = r
            products_in_data.add(r["product"])

        return {
            "expect_error": False,
            "skipped_unpublished": skipped_unpublished,
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

        if ":" not in mk:
            return {"expect_error": True, "reason": f"Invalid measure_key {mk!r}"}
        product, measure_id = mk.split(":", 1)
        if product == "ahrf":
            return {"expect_error": True, "reason": "Excluded product ahrf"}

        parent_geoid = resolve_within_geoid(db, level, within)
        try:
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

        positions = compute_competition_positions([r["value"] for r in with_val])
        for r, pos in zip(with_val, positions):
            r["position"] = pos

        truncated_by_limit = len(with_val) > limit
        sliced_with_val = with_val[:limit]

        return {
            "expect_error": False,
            "total_areas": len(all_rows),
            "all_with_value_count": len(with_val),
            "with_value": sliced_with_val,
            "without_value": without_val,
            "truncated_by_limit": truncated_by_limit,
            "expected_sources": [product] if all_rows else [],
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
                expected_measures[mk] = by_key[mk]
        return {"expect_error": False, "measures": expected_measures}

    elif tool == "list_data_sources":
        cat = lookup.catalog(db)
        pub_prods = {
            p["product"]: p for p in cat["products"] if p["product"] in PUBLIC_PRODUCTS
        }
        return {
            "expect_error": False,
            "products": pub_prods,
            "status_text": lookup.STATUS_TEXT,
        }

    elif tool == "find_places":
        return {"expect_error": False, "query": arguments.get("query")}

    elif tool == "search_measures":
        return {"expect_error": False, "arguments": arguments}

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
            # Check if the server returned an empty values list with a warning instead
            failures.append(
                f"Expected ToolError for {tool}({arguments}), but call succeeded with: "
                f"{json.dumps(structured)[:240]}"
            )
            return failures
        substrings_any = call_check_spec.get("expect_error_Substrings_any") or []
        if substrings_any:
            if not any(sub.lower() in error_text.lower() for sub in substrings_any):
                failures.append(
                    f"ToolError message {error_text!r} did not contain any of {substrings_any}"
                )
        return failures

    # 2. Handle unpublished level in get_area_values (contract allows skipping with warning OR ToolError)
    if "expect_unpublished_level_handled" in call_check_spec:
        spec_info = call_check_spec["expect_unpublished_level_handled"]
        skipped_key = spec_info["skipped_measure_key"]
        pub_levels = spec_info["published_levels"]
        if is_error:
            for lvl in pub_levels:
                if lvl.lower() not in error_text.lower():
                    failures.append(
                        f"Error message {error_text!r} did not mention published level {lvl!r}"
                    )
            return failures
        # Otherwise it succeeded: verify skipped_key is NOT in data.values and IS mentioned in warnings
        if not isinstance(structured, dict):
            return ["Response missing structured_content"]
        failures.extend(check_envelope(structured, tool, arguments))
        values = structured.get("data", {}).get("values", [])
        if any(r.get("measure_key") == skipped_key for r in values if isinstance(r, dict)):
            failures.append(f"Unpublished measure {skipped_key!r} should have been skipped at level={arguments.get('level')!r}")
        warnings_joined = " ".join(str(w) for w in structured.get("warnings", []))
        for lvl in pub_levels:
            if lvl.lower() not in warnings_joined.lower():
                failures.append(
                    f"Warnings {structured.get('warnings')!r} did not mention published level {lvl!r} for skipped measure {skipped_key!r}"
                )
        return failures

    # 3. Normal non-error call
    if is_error:
        return [f"Unexpected ToolError on {tool}({arguments}): {error_text}"]

    if not isinstance(structured, dict):
        return [f"{tool} did not return structured_content dict (got {type(structured).__name__})"]

    # Run global contract checks
    raw_text = None
    content_list = getattr(call_result, "content", None)
    if content_list and hasattr(content_list[0], "text"):
        raw_text = content_list[0].text
    failures.extend(check_response_size(structured, raw_text=raw_text))
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
                for field in ("value", "status", "status_text", "period", "population", "unit", "storage_scale", "value_type", "boundary_vintage", "release_id", "source_credit"):
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
            if data.get("total_areas") != expected_lookup["total_areas"]:
                failures.append(
                    f"total_areas mismatch: got {data.get('total_areas')}, lookup has {expected_lookup['total_areas']}"
                )
            act_without = data.get("without_value", [])
            exp_without = expected_lookup["without_value"]
            if len(act_without) != len(exp_without):
                failures.append(
                    f"without_value count mismatch (must never be truncated): got {len(act_without)}, lookup has {len(exp_without)}"
                )
            else:
                for idx, (act_r, exp_r) in enumerate(zip(act_without, exp_without)):
                    act_geoid = (act_r.get("area") or {}).get("geoid")
                    if act_geoid != exp_r["geoid"] or act_r.get("status") != exp_r["status"] or act_r.get("value") is not None:
                        failures.append(
                            f"without_value[{idx}] mismatch: got ({act_geoid}, {act_r.get('status')}, {act_r.get('value')}), "
                            f"lookup has ({exp_r['geoid']}, {exp_r['status']}, None)"
                        )
                        break

            act_with = data.get("with_value", [])
            exp_with = expected_lookup["with_value"]
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
                if act_geoid == exp_r["geoid"] and act_r.get("status") != exp_r["status"]:
                    failures.append(
                        f"with_value[{idx}] status mismatch for {act_geoid}: got {act_r.get('status')!r}, lookup has {exp_r['status']!r}"
                    )
                    break

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
                mk = m.get("measure_key") or f"{m.get('product')}:{m.get('measure_id')}"
                if mk not in exp_measures:
                    failures.append(f"Unexpected measure in get_measure_details: {mk!r}")
                    continue
                exp_m = exp_measures[mk]
                for fld in ("unit", "storage_scale", "period", "population", "value_type", "levels", "uncertainty_kind"):
                    if m.get(fld) != exp_m.get(fld):
                        failures.append(
                            f"get_measure_details[{mk}] field {fld!r} mismatch: got {m.get(fld)!r}, lookup has {exp_m.get(fld)!r}"
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

    if call_check_spec.get("expect_warning_non_empty") is True:
        if not warnings:
            failures.append("Expected non-empty warnings list when no places matched")

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

    if call_check_spec.get("expect_topics_present") is True:
        topics = data.get("topics")
        if not isinstance(topics, list) or len(topics) < 6:
            failures.append(f"Expected topics list in search_measures(), got {topics!r}")

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

    if call_check_spec.get("expect_no_ahrf_measures") is True:
        for m in data.get("measures", []):
            mk = str((m or {}).get("measure_key", ""))
            if mk.startswith("ahrf:"):
                failures.append(f"Found excluded AHRF measure in search_measures: {mk!r}")

    if call_check_spec.get("expect_single_period_per_measure") is True:
        values = data.get("values", [])
        periods = {r.get("period") for r in values if isinstance(r, dict)}
        if len(periods) != 1:
            failures.append(f"Expected single published period for measure, got {periods!r}")

    if "expect_interpretation_rule_substring" in call_check_spec:
        sub = call_check_spec["expect_interpretation_rule_substring"]
        if not any(sub in str(r) for r in interp_rules):
            failures.append(f"interpretation_rules did not contain {sub!r}")

    if call_check_spec.get("expect_notes_mention_no_time_series") is True:
        notes_blob = json.dumps(data.get("notes", ""), ensure_ascii=False).lower()
        if "time series" not in notes_blob and "one period" not in notes_blob and "single period" not in notes_blob:
            failures.append(f"list_data_sources data.notes did not mention one period / no time series: {data.get('notes')!r}")

    if call_check_spec.get("expect_no_composite_measure") is True:
        for m in data.get("measures", []):
            label = str((m or {}).get("label", "")).lower()
            if "composite" in label or "overall health score" in label:
                failures.append(f"Unexpected composite score measure found: {m!r}")

    if "expect_warning_substring" in call_check_spec:
        sub = call_check_spec["expect_warning_substring"]
        if not any(sub in str(w) for w in warnings):
            failures.append(f"warnings did not contain {sub!r}")

    if "expect_all_rows_population_substring" in call_check_spec:
        sub = call_check_spec["expect_all_rows_population_substring"]
        for r in data.get("values", []):
            pop = str((r or {}).get("population", ""))
            if sub not in pop:
                failures.append(f"Row {r.get('measure_key')} population {pop!r} missing {sub!r}")

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
            call_summaries: list[dict[str, Any]] = []
            for idx, call in enumerate(calls):
                tool = call["tool"]
                args = call.get("arguments", {})
                c_check = call_checks_by_idx.get(idx, {})
                exp = compute_expected_for_call(db, tool, args, topics_list)
                call_summaries.append({"tool": tool, "arguments": args, "expected": exp})

                # Validate that spot checks in questions.yaml match lookup on places_staging
                if c_check.get("expect_error") is True:
                    if tool in ("get_area_values", "get_measure_across_areas") and not exp.get("expect_error"):
                        q_failures.append(
                            f"Call {idx} ({tool}) expected error in YAML, but lookup succeeded"
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
                            substrings_any = c_check.get("expect_error_Substrings_any") or []
                            if substrings_any and not any(
                                s.lower() in str(exc).lower() for s in substrings_any
                            ):
                                q_failures.append(
                                    f"Call {idx} ({tool}) raised {exc!r}, missing expected {substrings_any}"
                                )
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
        help="Compute and verify expected values from app.area_pilot.lookup without a server",
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
                mode="validate-offline (awaiting M4 live server run)",
                server_url=None,
                question_results=q_results,
                latencies_ms=[],
            )
        print("Validation PASSED.")
        return 0

    if args.expected_only:
        return run_expected_only(args.questions, report_path=args.report)

    if args.url:
        report_path = args.report or DEFAULT_REPORT_PATH
        return asyncio.run(run_live_eval(args.url, args.questions, report_path))

    parser.error("Provide one of --validate, --expected-only, or --url http://127.0.0.1:<port>/mcp")
    return 2


if __name__ == "__main__":
    sys.exit(main())
