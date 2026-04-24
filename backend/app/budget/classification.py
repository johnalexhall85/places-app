from __future__ import annotations

import argparse
import os
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Mapping

from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from app.budget.models import (
    CdcBudgetClassificationRuleRegistry,
    CdcBudgetClassificationV1,
    CdcBudgetTrackerRaw,
)
from app.db import DEFAULT_DB_URL
from app.db_fqtn import budget_table
from app.db_schemas import BUDGET_SCHEMA

DEFAULT_CLASSIFICATION_VERSION = "v1_regular_appropriations"
CLASSIFICATION_METHOD = "rule_based_budget_grounded"
DEFAULT_BATCH_SIZE = 500
CONFIDENCE_QUANTIZER = Decimal("0.001")

NORMALIZE_PUNCTUATION_RE = re.compile(r"[&/\-,.()]")
NORMALIZE_WHITESPACE_RE = re.compile(r"\s+")

TRUE_TOKENS = {"1", "true", "t", "yes", "y"}
NON_ADD_TOKENS = TRUE_TOKENS | {"non add", "non-add"}
LEAF_GRANULARITIES = {
    "sub_program_level",
    "sub_program_2_level",
    "sub_program_3_level",
}
ROLLUP_GRANULARITIES = {"aggregate"}
REGULAR_ALLOWED_FUNDING_TYPES = {"", "discretionary"}

RAW_TABLE = CdcBudgetTrackerRaw.__table__
CLASSIFICATION_TABLE = CdcBudgetClassificationV1.__table__
RULE_REGISTRY_TABLE = CdcBudgetClassificationRuleRegistry.__table__
RAW_TABLE_FQTN = budget_table("cdc_budget_tracker_raw")
CLASSIFICATION_TABLE_FQTN = budget_table("cdc_budget_classification_v1")
RULE_REGISTRY_TABLE_FQTN = budget_table("cdc_budget_classification_rule_registry")
REGULAR_VIEW_FQTN = budget_table("v_cdc_budget_regular_appropriations_v1")
SUMMARY_VIEW_FQTN = budget_table("mv_cdc_budget_classification_v1_summary")

RAW_COPY_COLUMNS = (
    "raw_budget_id",
    "unique_id",
    "fiscal_year",
    "source_file",
    "source_sheet",
    "agency",
    "sub_agency",
    "program",
    "sub_program",
    "sub_program_2",
    "sub_program_3",
    "budget_source",
    "budget_stage",
    "granularity",
    "amount_millions",
    "amount_dollars",
    "funding_type",
    "program_status",
    "is_non_add",
    "notes",
    "verified",
    "crosswalk_note",
    "source_id",
    "source_page",
)

CATEGORY_ORDER = (
    "REGULAR",
    "PPHF",
    "SUPPLEMENTAL",
    "TRANSFER",
    "NON_ADD",
    "REQUEST_ONLY",
    "MANDATORY",
    "TOTAL_OR_SUBTOTAL",
    "UNKNOWN",
)

SUBTYPE_BY_RULE = {
    "NON_ADD_001": "non_add",
    "PPHF_001": "prevention_fund",
    "SUPPLEMENTAL_001": "emergency_supplemental",
    "COVID_001": "emergency_supplemental",
    "TRANSFER_001": "transfer",
    "REPROGRAM_001": "transfer",
    "MANDATORY_001": "mandatory",
    "TOTAL_001": "total_rollup",
    "REQUEST_001": "request",
    "REGULAR_001": None,
    "REGULAR_002": "annual_discretionary",
    "REGULAR_003": "annual_discretionary",
    "UNKNOWN_001": "unknown",
}

RULE_EXPLANATIONS = {
    "NON_ADD_001": "Record is explicitly marked as non-add, so it stays out of regular appropriations.",
    "PPHF_001": "Normalized text indicates Prevention and Public Health Fund funding.",
    "SUPPLEMENTAL_001": "Normalized text indicates supplemental or emergency appropriation language.",
    "COVID_001": "Normalized text indicates COVID-era emergency funding terms such as CARES, ARP, or pandemic.",
    "TRANSFER_001": "Normalized text indicates a transfer rather than a regular annual appropriation.",
    "REPROGRAM_001": "Normalized text indicates reprogramming activity, which is treated conservatively as transfer-like.",
    "MANDATORY_001": "Funding type is marked mandatory, so it is not treated as a regular discretionary appropriation.",
    "TOTAL_001": "Record looks like a rollup total or subtotal rather than a leaf appropriation line.",
    "REQUEST_001": "Budget stage is request-only and does not indicate enacted or operating-plan funding.",
    "REGULAR_001": "CDC row is enacted or operating-plan discretionary funding with no higher-priority exclusion signals.",
    "REGULAR_002": "Row is enacted or operating-plan discretionary funding and looks programmatic enough to treat as regular.",
    "REGULAR_003": "Cross-year continuity suggests a recurring programmatic enacted line, but the signal is weaker than the main regular rules.",
    "UNKNOWN_001": "No exclusion, request, rollup, or regular-appropriation rule matched with enough confidence.",
}

PPHF_PHRASES = (
    "pphf",
    "prevention and public health fund",
    "prevention public health fund",
)
SUPPLEMENTAL_PHRASES = (
    "supplemental",
    "emergency supplemental",
    "emergency funding",
    "emergency appropriation",
)
TRANSFER_PHRASES = (
    "transfer",
    "transfers",
    "transferred",
    "transfer in",
    "transfer out",
)
REPROGRAMMING_PHRASES = ("reprogramming", "reprogrammed")
TOTAL_PHRASES = ("total",)
SUBTOTAL_PHRASES = ("subtotal",)
PREVENTION_FUND_PHRASES = (
    "prevention fund",
    "prevention and public health fund",
    "prevention public health fund",
)
COVID_PHRASES = ("covid", "coronavirus", "pandemic")
ARP_PHRASES = ("arp",)
CARES_PHRASES = ("cares",)
RESCUE_PLAN_PHRASES = ("american rescue plan", "rescue plan")
NONRECURRING_PHRASES = ("nonrecurring", "non recurring")
OPERATING_PLAN_PHRASES = ("operating plan", "operational plan")


@dataclass(frozen=True)
class RuleDefinition:
    rule_code: str
    rule_group: str
    description: str
    category_output: str
    subtype_output: str | None
    confidence_output: Decimal
    priority: int


@dataclass(frozen=True)
class ContinuityStats:
    program_year_count: int | None
    program_first_year: int | None
    program_last_year: int | None
    program_has_substructure: bool


RULE_DEFINITIONS = (
    RuleDefinition(
        rule_code="NON_ADD_001",
        rule_group="priority_group_1_explicit_exclusions",
        description="Classify rows explicitly marked as non-add outside the regular appropriation base.",
        category_output="NON_ADD",
        subtype_output="non_add",
        confidence_output=Decimal("0.990"),
        priority=100,
    ),
    RuleDefinition(
        rule_code="PPHF_001",
        rule_group="priority_group_1_explicit_exclusions",
        description="Classify rows referencing PPHF or the Prevention and Public Health Fund as prevention-fund funding.",
        category_output="PPHF",
        subtype_output="prevention_fund",
        confidence_output=Decimal("0.990"),
        priority=110,
    ),
    RuleDefinition(
        rule_code="SUPPLEMENTAL_001",
        rule_group="priority_group_1_explicit_exclusions",
        description="Classify rows with supplemental or emergency appropriation language as supplemental funding.",
        category_output="SUPPLEMENTAL",
        subtype_output="emergency_supplemental",
        confidence_output=Decimal("0.970"),
        priority=120,
    ),
    RuleDefinition(
        rule_code="COVID_001",
        rule_group="priority_group_1_explicit_exclusions",
        description="Classify rows with COVID, CARES, ARP, or pandemic language as emergency supplemental funding.",
        category_output="SUPPLEMENTAL",
        subtype_output="emergency_supplemental",
        confidence_output=Decimal("0.970"),
        priority=130,
    ),
    RuleDefinition(
        rule_code="TRANSFER_001",
        rule_group="priority_group_1_explicit_exclusions",
        description="Classify rows with transfer language as transfer funding rather than regular appropriations.",
        category_output="TRANSFER",
        subtype_output="transfer",
        confidence_output=Decimal("0.960"),
        priority=140,
    ),
    RuleDefinition(
        rule_code="REPROGRAM_001",
        rule_group="priority_group_1_explicit_exclusions",
        description="Classify rows with reprogramming language as transfer-like funding.",
        category_output="TRANSFER",
        subtype_output="transfer",
        confidence_output=Decimal("0.920"),
        priority=150,
    ),
    RuleDefinition(
        rule_code="MANDATORY_001",
        rule_group="priority_group_1_explicit_exclusions",
        description="Classify rows whose funding type is mandatory as non-regular mandatory funding.",
        category_output="MANDATORY",
        subtype_output="mandatory",
        confidence_output=Decimal("0.950"),
        priority=160,
    ),
    RuleDefinition(
        rule_code="TOTAL_001",
        rule_group="priority_group_2_rollups",
        description="Classify rows with total or subtotal language and weak leaf-like structure as rollup rows.",
        category_output="TOTAL_OR_SUBTOTAL",
        subtype_output="total_rollup",
        confidence_output=Decimal("0.900"),
        priority=200,
    ),
    RuleDefinition(
        rule_code="REQUEST_001",
        rule_group="priority_group_3_stage",
        description="Classify request-only rows that do not also indicate enacted or operating-plan funding.",
        category_output="REQUEST_ONLY",
        subtype_output="request",
        confidence_output=Decimal("0.930"),
        priority=300,
    ),
    RuleDefinition(
        rule_code="REGULAR_001",
        rule_group="priority_group_4_regular",
        description="Classify CDC enacted or operating-plan discretionary rows with no exclusion signals as regular appropriations.",
        category_output="REGULAR",
        subtype_output=None,
        confidence_output=Decimal("0.950"),
        priority=400,
    ),
    RuleDefinition(
        rule_code="REGULAR_002",
        rule_group="priority_group_4_regular",
        description="Classify enacted or operating-plan discretionary rows that look leaf-like or otherwise programmatic as regular appropriations.",
        category_output="REGULAR",
        subtype_output="annual_discretionary",
        confidence_output=Decimal("0.900"),
        priority=410,
    ),
    RuleDefinition(
        rule_code="REGULAR_003",
        rule_group="priority_group_4_regular",
        description="Classify enacted or operating-plan rows with cross-year continuity as likely regular appropriations when other signals are absent.",
        category_output="REGULAR",
        subtype_output="annual_discretionary",
        confidence_output=Decimal("0.820"),
        priority=420,
    ),
    RuleDefinition(
        rule_code="UNKNOWN_001",
        rule_group="priority_group_5_fallback",
        description="Fallback classification when no higher-confidence rule matches.",
        category_output="UNKNOWN",
        subtype_output="unknown",
        confidence_output=Decimal("0.400"),
        priority=900,
    ),
)

RULES_BY_CODE = {rule.rule_code: rule for rule in RULE_DEFINITIONS}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the budget-grounded CDC regular appropriation classification v1 layer.",
    )
    parser.add_argument(
        "--classification-version",
        default=DEFAULT_CLASSIFICATION_VERSION,
        help=f"Classification version label stored in {CLASSIFICATION_TABLE_FQTN}.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Delete existing derived rows for the filtered scope before rebuilding.",
    )
    parser.add_argument(
        "--fiscal-year",
        type=int,
        default=None,
        help="Optional single fiscal year filter.",
    )
    parser.add_argument(
        "--sub-agency",
        default=None,
        help="Optional case-insensitive sub-agency filter.",
    )
    parser.add_argument(
        "--source-file-label",
        default=None,
        help="Optional source_file filter, usually the workbook basename.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute classifications and print summaries without writing to the database.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or the local development DSN).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Upsert batch size (default: {DEFAULT_BATCH_SIZE}).",
    )
    return parser.parse_args()


def normalize_rule_text(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).replace("\ufeff", "").strip().lower()
    token = NORMALIZE_PUNCTUATION_RE.sub(" ", token)
    token = NORMALIZE_WHITESPACE_RE.sub(" ", token).strip()
    return token or None


def normalize_token(value: Any) -> str:
    return normalize_rule_text(value) or ""


def contains_any_phrase(normalized_text: str | None, phrases: Iterable[str]) -> bool:
    if not normalized_text:
        return False
    padded = f" {normalized_text} "
    for phrase in phrases:
        phrase_token = normalize_rule_text(phrase)
        if phrase_token and f" {phrase_token} " in padded:
            return True
    return False


def build_combined_search_text(raw_row: Mapping[str, Any]) -> str:
    fields = (
        raw_row.get("program"),
        raw_row.get("sub_program"),
        raw_row.get("sub_program_2"),
        raw_row.get("sub_program_3"),
        raw_row.get("funding_type"),
        raw_row.get("notes"),
        raw_row.get("crosswalk_note"),
        raw_row.get("program_status"),
    )
    normalized_parts = [normalize_rule_text(value) for value in fields]
    return " ".join(part for part in normalized_parts if part)


def build_program_key(norm_program: str | None, norm_sub_program: str | None) -> str | None:
    if not norm_program:
        return None
    if norm_sub_program:
        return f"{norm_program} | {norm_sub_program}"
    return norm_program


def build_program_continuity_lookup(raw_rows: Iterable[Mapping[str, Any]]) -> dict[str, ContinuityStats]:
    years_by_key: dict[str, set[int]] = defaultdict(set)
    has_substructure_by_program: dict[str, bool] = defaultdict(bool)
    has_substructure_by_key: dict[str, bool] = defaultdict(bool)

    for raw_row in raw_rows:
        norm_program = normalize_rule_text(raw_row.get("program"))
        norm_sub_program = normalize_rule_text(raw_row.get("sub_program"))
        norm_sub_program_2 = normalize_rule_text(raw_row.get("sub_program_2"))
        norm_sub_program_3 = normalize_rule_text(raw_row.get("sub_program_3"))
        program_key = build_program_key(norm_program, norm_sub_program)
        if not program_key:
            continue

        if norm_program and (norm_sub_program or norm_sub_program_2 or norm_sub_program_3):
            has_substructure_by_program[norm_program] = True
        if norm_sub_program_2 or norm_sub_program_3:
            has_substructure_by_key[program_key] = True

        fiscal_year = raw_row.get("fiscal_year")
        if isinstance(fiscal_year, int):
            years_by_key[program_key].add(fiscal_year)

    continuity_lookup: dict[str, ContinuityStats] = {}
    for program_key, years in years_by_key.items():
        years_sorted = sorted(years)
        norm_program = program_key.split(" | ", 1)[0]
        continuity_lookup[program_key] = ContinuityStats(
            program_year_count=len(years_sorted),
            program_first_year=years_sorted[0] if years_sorted else None,
            program_last_year=years_sorted[-1] if years_sorted else None,
            program_has_substructure=bool(
                has_substructure_by_program.get(norm_program)
                or has_substructure_by_key.get(program_key)
            ),
        )

    return continuity_lookup


def classification_subtype_for_regular(signals: Mapping[str, Any]) -> str:
    if signals["signal_budget_stage_operating_plan"]:
        return "operating_plan_discretionary"
    if signals["signal_budget_stage_enacted"]:
        return "enacted_discretionary"
    return "annual_discretionary"


def build_rule_explanation(primary_rule_code: str, supporting_rule_codes: list[str]) -> str:
    explanation = RULE_EXPLANATIONS[primary_rule_code]
    if supporting_rule_codes:
        explanation = f"{explanation} Supporting matches: {', '.join(supporting_rule_codes)}."
    return explanation


def apply_classification_rules(signals: Mapping[str, Any]) -> dict[str, Any]:
    matched_rule_codes: list[str] = []

    def mark(rule_code: str, condition: bool) -> bool:
        if condition:
            matched_rule_codes.append(rule_code)
            return True
        return False

    non_add = mark("NON_ADD_001", signals["signal_non_add"])
    pphf = mark("PPHF_001", signals["signal_keyword_pphf"])
    supplemental = mark("SUPPLEMENTAL_001", signals["signal_keyword_supplemental"])
    covid = mark(
        "COVID_001",
        signals["signal_keyword_covid"]
        or signals["signal_keyword_cares"]
        or signals["signal_keyword_arp"]
        or signals["signal_keyword_rescue_plan"],
    )
    transfer = mark("TRANSFER_001", signals["signal_keyword_transfer"])
    reprogram = mark("REPROGRAM_001", signals["signal_keyword_reprogramming"])
    mandatory = mark("MANDATORY_001", signals["signal_funding_type_mandatory"])
    total_rollup = mark(
        "TOTAL_001",
        (signals["signal_keyword_total"] or signals["signal_keyword_subtotal"])
        and not signals["signal_record_is_leaf_like"],
    )
    request_only = mark(
        "REQUEST_001",
        signals["signal_budget_stage_request"]
        and not signals["signal_budget_stage_enacted"]
        and not signals["signal_budget_stage_operating_plan"],
    )

    has_priority_one_exclusion = any((non_add, pphf, supplemental, covid, transfer, reprogram, mandatory))
    has_rollup_keywords = signals["signal_keyword_total"] or signals["signal_keyword_subtotal"]
    enacted_or_operating = signals["signal_budget_stage_enacted"] or signals["signal_budget_stage_operating_plan"]
    funding_type_allows_regular_fallback = signals["norm_funding_type"] in REGULAR_ALLOWED_FUNDING_TYPES
    reasonably_programmatic = (
        signals["amount_millions"] is not None
        and bool(signals["norm_program"])
        and signals["norm_granularity"] not in ROLLUP_GRANULARITIES
        and not has_rollup_keywords
    )
    regular_001 = mark(
        "REGULAR_001",
        signals["norm_sub_agency"] == "cdc"
        and enacted_or_operating
        and signals["signal_funding_type_discretionary"]
        and not signals["signal_non_add"]
        and not has_priority_one_exclusion
        and not total_rollup
        and not request_only
        and not has_rollup_keywords,
    )
    regular_002 = mark(
        "REGULAR_002",
        enacted_or_operating
        and signals["signal_funding_type_discretionary"]
        and not has_priority_one_exclusion
        and not total_rollup
        and not request_only
        and not has_rollup_keywords
        and (signals["signal_record_is_leaf_like"] or reasonably_programmatic),
    )
    regular_003 = mark(
        "REGULAR_003",
        enacted_or_operating
        and signals["signal_program_repeats_across_years"]
        and not has_priority_one_exclusion
        and not total_rollup
        and not request_only
        and not has_rollup_keywords
        and funding_type_allows_regular_fallback
        and (
            signals["signal_record_is_leaf_like"]
            or reasonably_programmatic
            or signals["signal_program_has_substructure"]
        ),
    )

    if matched_rule_codes:
        primary_rule_code = matched_rule_codes[0]
    else:
        primary_rule_code = "UNKNOWN_001"

    primary_rule = RULES_BY_CODE[primary_rule_code]
    subtype_output = SUBTYPE_BY_RULE[primary_rule_code]
    if primary_rule_code == "REGULAR_001":
        subtype_output = classification_subtype_for_regular(signals)

    supporting_rule_codes = [code for code in matched_rule_codes if code != primary_rule_code]
    is_regular = primary_rule.category_output == "REGULAR"
    return {
        "appropriation_category": primary_rule.category_output,
        "appropriation_subtype": subtype_output,
        "is_regular_appropriation": is_regular,
        "classification_confidence": primary_rule.confidence_output.quantize(CONFIDENCE_QUANTIZER, rounding=ROUND_HALF_UP),
        "primary_rule_code": primary_rule_code,
        "supporting_rule_codes": supporting_rule_codes,
        "rule_explanation": build_rule_explanation(primary_rule_code, supporting_rule_codes),
        "matched_rule_codes": matched_rule_codes,
        "regular_rule_flags": {
            "regular_001": regular_001,
            "regular_002": regular_002,
            "regular_003": regular_003,
        },
    }


def build_classification_row(
    raw_row: Mapping[str, Any],
    *,
    classification_version: str,
    classification_batch_id: uuid.UUID,
    classified_at: datetime,
    continuity_lookup: Mapping[str, ContinuityStats],
) -> dict[str, Any]:
    norm_program = normalize_rule_text(raw_row.get("program"))
    norm_sub_program = normalize_rule_text(raw_row.get("sub_program"))
    norm_sub_program_2 = normalize_rule_text(raw_row.get("sub_program_2"))
    norm_sub_program_3 = normalize_rule_text(raw_row.get("sub_program_3"))
    norm_funding_type = normalize_rule_text(raw_row.get("funding_type"))
    norm_budget_source = normalize_rule_text(raw_row.get("budget_source"))
    norm_budget_stage = normalize_rule_text(raw_row.get("budget_stage"))
    norm_program_status = normalize_rule_text(raw_row.get("program_status"))
    norm_notes = normalize_rule_text(raw_row.get("notes"))
    norm_crosswalk_note = normalize_rule_text(raw_row.get("crosswalk_note"))
    norm_sub_agency = normalize_rule_text(raw_row.get("sub_agency"))
    norm_granularity = normalize_rule_text(raw_row.get("granularity"))
    combined_search_text = build_combined_search_text(raw_row)
    program_key = build_program_key(norm_program, norm_sub_program)
    continuity = continuity_lookup.get(
        program_key,
        ContinuityStats(
            program_year_count=None,
            program_first_year=None,
            program_last_year=None,
            program_has_substructure=False,
        ),
    )

    signals = {
        "amount_millions": raw_row.get("amount_millions"),
        "norm_budget_source": norm_budget_source or "",
        "norm_budget_stage": norm_budget_stage or "",
        "norm_funding_type": norm_funding_type or "",
        "norm_granularity": norm_granularity or "",
        "norm_program": norm_program or "",
        "norm_sub_agency": norm_sub_agency or "",
        "signal_budget_stage_enacted": contains_any_phrase(norm_budget_stage, ("enacted",)),
        "signal_budget_stage_operating_plan": contains_any_phrase(norm_budget_stage, OPERATING_PLAN_PHRASES)
        or contains_any_phrase(norm_budget_source, OPERATING_PLAN_PHRASES),
        "signal_budget_stage_request": contains_any_phrase(norm_budget_stage, ("request",)),
        "signal_funding_type_discretionary": contains_any_phrase(norm_funding_type, ("discretionary",)),
        "signal_funding_type_mandatory": contains_any_phrase(norm_funding_type, ("mandatory",)),
        "signal_non_add": normalize_token(raw_row.get("is_non_add")) in NON_ADD_TOKENS,
        "signal_keyword_pphf": contains_any_phrase(combined_search_text, PPHF_PHRASES),
        "signal_keyword_supplemental": contains_any_phrase(combined_search_text, SUPPLEMENTAL_PHRASES),
        "signal_keyword_emergency": contains_any_phrase(combined_search_text, ("emergency",)),
        "signal_keyword_transfer": contains_any_phrase(combined_search_text, TRANSFER_PHRASES),
        "signal_keyword_reprogramming": contains_any_phrase(combined_search_text, REPROGRAMMING_PHRASES),
        "signal_keyword_total": contains_any_phrase(combined_search_text, TOTAL_PHRASES),
        "signal_keyword_subtotal": contains_any_phrase(combined_search_text, SUBTOTAL_PHRASES),
        "signal_keyword_base": contains_any_phrase(combined_search_text, ("base",)),
        "signal_keyword_prevention_fund": contains_any_phrase(combined_search_text, PREVENTION_FUND_PHRASES),
        "signal_keyword_covid": contains_any_phrase(combined_search_text, COVID_PHRASES),
        "signal_keyword_arp": contains_any_phrase(combined_search_text, ARP_PHRASES),
        "signal_keyword_cares": contains_any_phrase(combined_search_text, CARES_PHRASES),
        "signal_keyword_rescue_plan": contains_any_phrase(combined_search_text, RESCUE_PLAN_PHRASES),
        "signal_keyword_nonrecurring": contains_any_phrase(combined_search_text, NONRECURRING_PHRASES),
        "signal_program_has_substructure": bool(norm_sub_program or norm_sub_program_2 or norm_sub_program_3)
        or continuity.program_has_substructure,
        "signal_record_is_leaf_like": raw_row.get("amount_millions") is not None and norm_granularity in LEAF_GRANULARITIES,
        "signal_program_repeats_across_years": bool(continuity.program_year_count and continuity.program_year_count >= 2),
        "program_year_count": continuity.program_year_count,
        "program_first_year": continuity.program_first_year,
        "program_last_year": continuity.program_last_year,
    }
    decision = apply_classification_rules(signals)

    classification_row = {
        "raw_budget_id": raw_row["id"],
        "unique_id": raw_row["unique_id"],
        "fiscal_year": raw_row.get("fiscal_year"),
        "source_file": raw_row["source_file"],
        "source_sheet": raw_row["source_sheet"],
        "classification_version": classification_version,
        "classification_method": CLASSIFICATION_METHOD,
        "classified_at": classified_at,
        "classification_batch_id": classification_batch_id,
        "agency": raw_row.get("agency"),
        "sub_agency": raw_row.get("sub_agency"),
        "program": raw_row.get("program"),
        "sub_program": raw_row.get("sub_program"),
        "sub_program_2": raw_row.get("sub_program_2"),
        "sub_program_3": raw_row.get("sub_program_3"),
        "budget_source": raw_row.get("budget_source"),
        "budget_stage": raw_row.get("budget_stage"),
        "granularity": raw_row.get("granularity"),
        "amount_millions": raw_row.get("amount_millions"),
        "amount_dollars": raw_row.get("amount_dollars"),
        "funding_type": raw_row.get("funding_type"),
        "program_status": raw_row.get("program_status"),
        "is_non_add": raw_row.get("is_non_add"),
        "notes": raw_row.get("notes"),
        "verified": raw_row.get("verified"),
        "crosswalk_note": raw_row.get("crosswalk_note"),
        "source_id": raw_row.get("source_id"),
        "source_page": raw_row.get("source_page"),
        "norm_program": norm_program,
        "norm_sub_program": norm_sub_program,
        "norm_sub_program_2": norm_sub_program_2,
        "norm_sub_program_3": norm_sub_program_3,
        "norm_funding_type": norm_funding_type,
        "norm_budget_source": norm_budget_source,
        "norm_budget_stage": norm_budget_stage,
        "norm_program_status": norm_program_status,
        "norm_notes": norm_notes,
        "norm_crosswalk_note": norm_crosswalk_note,
        "signal_budget_stage_enacted": signals["signal_budget_stage_enacted"],
        "signal_budget_stage_operating_plan": signals["signal_budget_stage_operating_plan"],
        "signal_budget_stage_request": signals["signal_budget_stage_request"],
        "signal_funding_type_discretionary": signals["signal_funding_type_discretionary"],
        "signal_funding_type_mandatory": signals["signal_funding_type_mandatory"],
        "signal_non_add": signals["signal_non_add"],
        "signal_keyword_pphf": signals["signal_keyword_pphf"],
        "signal_keyword_supplemental": signals["signal_keyword_supplemental"],
        "signal_keyword_emergency": signals["signal_keyword_emergency"],
        "signal_keyword_transfer": signals["signal_keyword_transfer"],
        "signal_keyword_reprogramming": signals["signal_keyword_reprogramming"],
        "signal_keyword_total": signals["signal_keyword_total"],
        "signal_keyword_subtotal": signals["signal_keyword_subtotal"],
        "signal_keyword_base": signals["signal_keyword_base"],
        "signal_keyword_prevention_fund": signals["signal_keyword_prevention_fund"],
        "signal_keyword_covid": signals["signal_keyword_covid"],
        "signal_keyword_arp": signals["signal_keyword_arp"],
        "signal_keyword_cares": signals["signal_keyword_cares"],
        "signal_keyword_rescue_plan": signals["signal_keyword_rescue_plan"],
        "signal_keyword_nonrecurring": signals["signal_keyword_nonrecurring"],
        "signal_program_has_substructure": signals["signal_program_has_substructure"],
        "signal_record_is_leaf_like": signals["signal_record_is_leaf_like"],
        "signal_program_repeats_across_years": signals["signal_program_repeats_across_years"],
        "program_year_count": signals["program_year_count"],
        "program_first_year": signals["program_first_year"],
        "program_last_year": signals["program_last_year"],
        "appropriation_category": decision["appropriation_category"],
        "appropriation_subtype": decision["appropriation_subtype"],
        "is_regular_appropriation": decision["is_regular_appropriation"],
        "classification_confidence": decision["classification_confidence"],
        "primary_rule_code": decision["primary_rule_code"],
        "supporting_rule_codes": decision["supporting_rule_codes"],
        "rule_explanation": decision["rule_explanation"],
    }
    return classification_row


def chunked(rows: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def ensure_table_exists(connection: Connection, fqtn: str) -> None:
    exists = connection.execute(
        text("SELECT to_regclass(:table_name)"),
        {"table_name": fqtn},
    ).scalar_one()
    if not exists:
        raise RuntimeError(
            f"Required relation {fqtn} is missing. Run `cd backend && ./.venv/bin/alembic upgrade head` first."
        )


def fetch_raw_rows(connection: Connection) -> list[dict[str, Any]]:
    return list(connection.execute(select(RAW_TABLE)).mappings())


def row_matches_filters(raw_row: Mapping[str, Any], args: argparse.Namespace) -> bool:
    if args.fiscal_year is not None and raw_row.get("fiscal_year") != args.fiscal_year:
        return False
    if args.source_file_label and raw_row.get("source_file") != args.source_file_label:
        return False
    if args.sub_agency and normalize_token(raw_row.get("sub_agency")) != normalize_token(args.sub_agency):
        return False
    return True


def seed_rule_registry(
    connection: Connection,
    *,
    classification_version: str,
    dry_run: bool,
) -> int:
    registry_rows = [
        {
            "rule_code": rule.rule_code,
            "classification_version": classification_version,
            "rule_group": rule.rule_group,
            "description": rule.description,
            "category_output": rule.category_output,
            "subtype_output": rule.subtype_output,
            "confidence_output": rule.confidence_output.quantize(CONFIDENCE_QUANTIZER, rounding=ROUND_HALF_UP),
            "priority": rule.priority,
            "is_active": True,
        }
        for rule in RULE_DEFINITIONS
    ]
    if dry_run:
        return len(registry_rows)

    insert_stmt = pg_insert(RULE_REGISTRY_TABLE).values(registry_rows)
    update_columns = {
        "classification_version": insert_stmt.excluded.classification_version,
        "rule_group": insert_stmt.excluded.rule_group,
        "description": insert_stmt.excluded.description,
        "category_output": insert_stmt.excluded.category_output,
        "subtype_output": insert_stmt.excluded.subtype_output,
        "confidence_output": insert_stmt.excluded.confidence_output,
        "priority": insert_stmt.excluded.priority,
        "is_active": insert_stmt.excluded.is_active,
    }
    connection.execute(
        insert_stmt.on_conflict_do_update(
            index_elements=["rule_code"],
            set_=update_columns,
        )
    )
    return len(registry_rows)


def fetch_existing_raw_ids(
    connection: Connection,
    *,
    classification_version: str,
    raw_budget_ids: list[int],
) -> set[int]:
    if not raw_budget_ids:
        return set()
    result = connection.execute(
        select(CLASSIFICATION_TABLE.c.raw_budget_id).where(
            CLASSIFICATION_TABLE.c.classification_version == classification_version,
            CLASSIFICATION_TABLE.c.raw_budget_id.in_(raw_budget_ids),
        )
    )
    return {row[0] for row in result}


def delete_filtered_rows(
    connection: Connection,
    *,
    classification_version: str,
    raw_budget_ids: list[int],
) -> int:
    if not raw_budget_ids:
        return 0
    deleted = connection.execute(
        CLASSIFICATION_TABLE.delete().where(
            CLASSIFICATION_TABLE.c.classification_version == classification_version,
            CLASSIFICATION_TABLE.c.raw_budget_id.in_(raw_budget_ids),
        )
    )
    return int(deleted.rowcount or 0)


def upsert_classification_rows(
    connection: Connection,
    *,
    classification_rows: list[dict[str, Any]],
    batch_size: int,
) -> int:
    if not classification_rows:
        return 0

    rows_written = 0
    for batch in chunked(classification_rows, batch_size):
        insert_stmt = pg_insert(CLASSIFICATION_TABLE).values(batch)
        update_columns = {
            column.name: getattr(insert_stmt.excluded, column.name)
            for column in CLASSIFICATION_TABLE.columns
            if column.name != "id"
        }
        connection.execute(
            insert_stmt.on_conflict_do_update(
                index_elements=["raw_budget_id", "classification_version"],
                set_=update_columns,
            )
        )
        rows_written += len(batch)
    return rows_written


def refresh_summary_materialized_view(connection: Connection, *, dry_run: bool) -> None:
    if dry_run:
        return
    connection.execute(text(f"REFRESH MATERIALIZED VIEW {SUMMARY_VIEW_FQTN}"))


def format_money(value: Decimal | None) -> str:
    if value is None:
        return "0.00"
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def print_summary(
    *,
    args: argparse.Namespace,
    classification_batch_id: uuid.UUID,
    all_raw_rows: list[dict[str, Any]],
    filtered_rows: list[dict[str, Any]],
    classification_rows: list[dict[str, Any]],
    seeded_rule_count: int,
    existing_ids: set[int],
    deleted_count: int,
) -> None:
    category_counts = Counter(row["appropriation_category"] for row in classification_rows)
    subtype_counts = Counter(row["appropriation_subtype"] for row in classification_rows)
    rule_counts = Counter(row["primary_rule_code"] for row in classification_rows)
    year_category_amounts: dict[tuple[int | None, str], Decimal] = defaultdict(lambda: Decimal("0"))
    regular_by_year: dict[int | None, Decimal] = defaultdict(lambda: Decimal("0"))

    for row in classification_rows:
        amount = row.get("amount_dollars") or Decimal("0")
        key = (row.get("fiscal_year"), row["appropriation_category"])
        year_category_amounts[key] += amount
        if row["is_regular_appropriation"]:
            regular_by_year[row.get("fiscal_year")] += amount

    insert_estimate = len(filtered_rows) if args.truncate else max(len(filtered_rows) - len(existing_ids), 0)
    update_estimate = 0 if args.truncate else min(len(existing_ids), len(filtered_rows))

    print(f"Classification version: {args.classification_version}")
    print(f"Classification method: {CLASSIFICATION_METHOD}")
    print(f"Classification batch id: {classification_batch_id}")
    print(f"Dry run: {args.dry_run}")
    print(f"Raw rows loaded: {len(all_raw_rows)}")
    print(f"Filtered rows classified: {len(filtered_rows)}")
    print(f"Registry rows seeded/updated: {seeded_rule_count}")
    print(f"Existing rows in scope before write: {len(existing_ids)}")
    if args.truncate:
        print(f"Deleted existing derived rows in scope: {deleted_count}")
    print(f"Rows inserted in scope: {insert_estimate}")
    print(f"Rows updated in scope: {update_estimate}")
    print("Counts by appropriation_category:")
    for category in CATEGORY_ORDER:
        if category in category_counts:
            print(f"  {category}: {category_counts[category]}")
    print("Counts by appropriation_subtype:")
    for subtype, count in sorted(subtype_counts.items(), key=lambda item: (-item[1], item[0] or "")):
        print(f"  {subtype}: {count}")
    print("Counts by primary_rule_code:")
    for rule_code, count in sorted(rule_counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {rule_code}: {count}")
    print("Amount by fiscal_year and appropriation_category:")
    for fiscal_year, category in sorted(year_category_amounts.keys(), key=lambda item: ((item[0] or 0), item[1])):
        print(f"  FY{fiscal_year} {category}: ${format_money(year_category_amounts[(fiscal_year, category)])}")
    print("Regular appropriation dollars by fiscal_year:")
    for fiscal_year in sorted(regular_by_year):
        print(f"  FY{fiscal_year}: ${format_money(regular_by_year[fiscal_year])}")


def main() -> None:
    args = parse_args()
    engine = create_engine(args.db_url, pool_pre_ping=True)

    with engine.begin() as connection:
        ensure_table_exists(connection, RAW_TABLE_FQTN)
        if not args.dry_run:
            ensure_table_exists(connection, CLASSIFICATION_TABLE_FQTN)
            ensure_table_exists(connection, RULE_REGISTRY_TABLE_FQTN)
            ensure_table_exists(connection, SUMMARY_VIEW_FQTN)

        all_raw_rows = fetch_raw_rows(connection)
        filtered_rows = [row for row in all_raw_rows if row_matches_filters(row, args)]
        continuity_lookup = build_program_continuity_lookup(all_raw_rows)
        classification_batch_id = uuid.uuid4()
        classified_at = datetime.now(timezone.utc)
        classification_rows = [
            build_classification_row(
                row,
                classification_version=args.classification_version,
                classification_batch_id=classification_batch_id,
                classified_at=classified_at,
                continuity_lookup=continuity_lookup,
            )
            for row in filtered_rows
        ]

        raw_budget_ids = [int(row["id"]) for row in filtered_rows]
        existing_ids = set()
        deleted_count = 0
        if not args.dry_run:
            existing_ids = fetch_existing_raw_ids(
                connection,
                classification_version=args.classification_version,
                raw_budget_ids=raw_budget_ids,
            )
            if args.truncate:
                deleted_count = delete_filtered_rows(
                    connection,
                    classification_version=args.classification_version,
                    raw_budget_ids=raw_budget_ids,
                )
                existing_ids = set()

        seeded_rule_count = seed_rule_registry(
            connection,
            classification_version=args.classification_version,
            dry_run=args.dry_run,
        )

        if not args.dry_run:
            upsert_classification_rows(
                connection,
                classification_rows=classification_rows,
                batch_size=args.batch_size,
            )
            refresh_summary_materialized_view(connection, dry_run=args.dry_run)

        print_summary(
            args=args,
            classification_batch_id=classification_batch_id,
            all_raw_rows=all_raw_rows,
            filtered_rows=filtered_rows,
            classification_rows=classification_rows,
            seeded_rule_count=seeded_rule_count,
            existing_ids=existing_ids,
            deleted_count=deleted_count,
        )


if __name__ == "__main__":
    main()
