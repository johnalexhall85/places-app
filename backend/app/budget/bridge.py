from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from app.budget.classification import normalize_rule_text
from app.budget.models import CdcBudgetSpendingBridgeRuleRegistry, CdcBudgetSpendingBridgeV1
from app.db import DEFAULT_DB_URL
from app.db_fqtn import budget_table, cdc_funding_table, recon_table, taggs_table

DEFAULT_BRIDGE_VERSION = "v1_budget_spending_bridge"
DEFAULT_BATCH_SIZE = 500
MAX_FUZZY_CANDIDATES_PER_ANCHOR = 10
MAX_STRUCTURED_CANDIDATES_PER_RULE = 75

HIGH_CONFIDENCE_MIN = Decimal("0.9000")
MEDIUM_CONFIDENCE_MIN = Decimal("0.7500")
SCORE_QUANTIZER = Decimal("0.0001")

ANCHOR_VIEW_FQTN = budget_table("v_cdc_budget_anchor_v1")
BRIDGE_TABLE = CdcBudgetSpendingBridgeV1.__table__
BRIDGE_RULE_TABLE = CdcBudgetSpendingBridgeRuleRegistry.__table__
BRIDGE_TABLE_FQTN = budget_table("cdc_budget_spending_bridge_v1")
BRIDGE_RULE_TABLE_FQTN = budget_table("cdc_budget_spending_bridge_rule_registry")
CDC_PRIME_AWARDS_FQTN = cdc_funding_table("prime_awards")
CDC_PRIME_TRANSACTIONS_FQTN = cdc_funding_table("prime_transactions")
ASSISTANCE_ACCOUNTS_FQTN = recon_table("assistance_transaction_accounts")
FEDERAL_ACCOUNT_LOOKUP_FQTN = recon_table("federal_account_lookup")
ASSISTANCE_PROFILE_FQTN = recon_table("assistance_transactions_profile_enriched")
TAGGS_AWARD_SUMMARY_FQTN = taggs_table("award_funding_summary")
TAGGS_CAN_CLASSIFICATION_FQTN = taggs_table("can_classification")

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
    "pandemic",
    "covid",
    "coronavirus",
    "american rescue plan",
    "cares",
    "arp",
)
TRANSFER_PHRASES = (
    "transfer",
    "transfers",
    "transferred",
    "block grant",
    "reprogramming",
    "reprogrammed",
)
MANDATORY_HINT_PHRASES = (
    "mandatory",
    "vaccines for children",
    "world trade center",
    "eeoicpa",
)
EMERGENCY_PHRASES = (
    "covid",
    "pandemic",
    "american rescue plan",
    "cares",
    "supplemental",
    "emergency",
    "public health and social services emergency fund",
    "phssef",
)
GENERIC_MATCH_STOPWORDS = {
    "and",
    "for",
    "the",
    "of",
    "program",
    "programs",
    "public",
    "health",
    "prevention",
    "control",
    "activities",
    "services",
    "support",
    "system",
    "systems",
    "community",
    "grant",
    "grants",
    "cooperative",
    "agreements",
    "agreement",
    "disease",
    "diseases",
    "center",
    "centers",
    "national",
    "state",
    "states",
    "research",
    "response",
    "cdc",
    "based",
}
CDC_SUBAGENCY_HINTS = (
    "centers for disease control",
    "agency for toxic substances",
    "atsdr",
    "cdc",
)


@dataclass(frozen=True)
class BridgeRuleDefinition:
    rule_code: str
    rule_group: str
    tier: str
    system_name: str
    description: str
    match_type: str
    default_match_score: Decimal
    default_match_confidence: Decimal
    default_confidence_band: str
    priority: int


@dataclass(frozen=True)
class ManualBridgeHint:
    budget_key: str
    aln: str
    description: str


RULE_DEFINITIONS = (
    BridgeRuleDefinition(
        rule_code="BRIDGE_USA_A001",
        rule_group="tier_a_deterministic",
        tier="TIER_A_DETERMINISTIC",
        system_name="usaspending",
        description="Exact verified federal-account title match between the budget anchor program and USAspending award account lineage.",
        match_type="federal_account_exact",
        default_match_score=Decimal("0.9700"),
        default_match_confidence=Decimal("0.9650"),
        default_confidence_band="HIGH",
        priority=100,
    ),
    BridgeRuleDefinition(
        rule_code="BRIDGE_USA_A003",
        rule_group="tier_a_deterministic",
        tier="TIER_A_DETERMINISTIC",
        system_name="usaspending",
        description="Manual seeded ALN bridge for especially clear CDC budget-program to USAspending assistance award mappings.",
        match_type="manual_seeded_bridge",
        default_match_score=Decimal("0.9850"),
        default_match_confidence=Decimal("0.9800"),
        default_confidence_band="HIGH",
        priority=110,
    ),
    BridgeRuleDefinition(
        rule_code="BRIDGE_TAGGS_A001",
        rule_group="tier_a_deterministic",
        tier="TIER_A_DETERMINISTIC",
        system_name="taggs",
        description="Exact normalized program-path match against TAGGS effective program or funding-stream labels.",
        match_type="program_path_normalized_exact",
        default_match_score=Decimal("0.9500"),
        default_match_confidence=Decimal("0.9450"),
        default_confidence_band="HIGH",
        priority=120,
    ),
    BridgeRuleDefinition(
        rule_code="BRIDGE_TAGGS_A003",
        rule_group="tier_a_deterministic",
        tier="TIER_A_DETERMINISTIC",
        system_name="taggs",
        description="Manual seeded ALN bridge for especially clear CDC budget-program to TAGGS award mappings.",
        match_type="manual_seeded_bridge",
        default_match_score=Decimal("0.9850"),
        default_match_confidence=Decimal("0.9800"),
        default_confidence_band="HIGH",
        priority=130,
    ),
    BridgeRuleDefinition(
        rule_code="BRIDGE_USA_B001",
        rule_group="tier_b_structured",
        tier="TIER_B_STRUCTURED",
        system_name="usaspending",
        description="Structured budget-label phrase match against USAspending award titles, assistance listing titles, or program activity text.",
        match_type="program_name_exact",
        default_match_score=Decimal("0.8200"),
        default_match_confidence=Decimal("0.8000"),
        default_confidence_band="MEDIUM",
        priority=200,
    ),
    BridgeRuleDefinition(
        rule_code="BRIDGE_USA_B002",
        rule_group="tier_b_structured",
        tier="TIER_B_STRUCTURED",
        system_name="usaspending",
        description="Verified federal-account bridge combined with a subprogram text match inside USAspending award text.",
        match_type="account_to_program_bridge",
        default_match_score=Decimal("0.8800"),
        default_match_confidence=Decimal("0.8600"),
        default_confidence_band="MEDIUM",
        priority=210,
    ),
    BridgeRuleDefinition(
        rule_code="BRIDGE_TAGGS_B001",
        rule_group="tier_b_structured",
        tier="TIER_B_STRUCTURED",
        system_name="taggs",
        description="Structured budget-label phrase match against TAGGS funding-stream, program-name, or assistance-listing text.",
        match_type="program_name_exact",
        default_match_score=Decimal("0.8400"),
        default_match_confidence=Decimal("0.8200"),
        default_confidence_band="MEDIUM",
        priority=220,
    ),
    BridgeRuleDefinition(
        rule_code="BRIDGE_TAGGS_B002",
        rule_group="tier_b_structured",
        tier="TIER_B_STRUCTURED",
        system_name="taggs",
        description="Expected CDC program-office alignment plus program-name text match in TAGGS.",
        match_type="funding_mechanism_plus_program",
        default_match_score=Decimal("0.8900"),
        default_match_confidence=Decimal("0.8700"),
        default_confidence_band="MEDIUM",
        priority=230,
    ),
    BridgeRuleDefinition(
        rule_code="BRIDGE_USA_C001",
        rule_group="tier_c_fuzzy",
        tier="TIER_C_FUZZY_CANDIDATE",
        system_name="usaspending",
        description="Constrained fuzzy budget-label candidate generation against USAspending award text.",
        match_type="program_name_fuzzy",
        default_match_score=Decimal("0.6500"),
        default_match_confidence=Decimal("0.6200"),
        default_confidence_band="LOW",
        priority=300,
    ),
    BridgeRuleDefinition(
        rule_code="BRIDGE_TAGGS_C001",
        rule_group="tier_c_fuzzy",
        tier="TIER_C_FUZZY_CANDIDATE",
        system_name="taggs",
        description="Constrained fuzzy budget-label candidate generation against TAGGS program and award text.",
        match_type="subprogram_fuzzy",
        default_match_score=Decimal("0.6500"),
        default_match_confidence=Decimal("0.6200"),
        default_confidence_band="LOW",
        priority=310,
    ),
)

RULES_BY_CODE = {rule.rule_code: rule for rule in RULE_DEFINITIONS}

MANUAL_BRIDGE_HINTS = (
    ManualBridgeHint("section 317 immunization program", "93.268", "Section 317 budget lines align to Immunization Cooperative Agreements."),
    ManualBridgeHint("public health emergency preparedness cooperative agreement", "93.069", "PHEP budget lines align to the Public Health Emergency Preparedness Cooperative Agreement."),
    ManualBridgeHint("tuberculosis", "93.116", "Tuberculosis budget lines align to the tuberculosis control assistance listing."),
    ManualBridgeHint("global hiv aids program", "93.067", "Global HIV/AIDS budget lines align to the Global AIDS assistance listing."),
    ManualBridgeHint("global public health protection", "93.318", "Global Public Health Protection aligns to the global public health impact and systems listing."),
    ManualBridgeHint("cancer prevention and control", "93.898", "Cancer Prevention and Control budget lines align to the cancer prevention and control listing."),
    ManualBridgeHint("breast and cervical cancer", "93.919", "Breast and cervical cancer budget lines align to the state-based breast and cervical cancer listing."),
    ManualBridgeHint("drug free communities", "93.276", "Drug Free Communities budget lines align to the Drug-Free Communities assistance listing."),
    ManualBridgeHint("sexually transmitted infections", "93.977", "STI budget lines align to the STD prevention and control grants listing."),
    ManualBridgeHint("viral hepatitis", "93.270", "Viral hepatitis budget lines align to the viral hepatitis prevention and control listing."),
    ManualBridgeHint("occupational safety and health", "93.262", "Occupational safety and health aligns to the occupational safety and health assistance listing."),
    ManualBridgeHint(
        "health and development for people with disabilities",
        "93.184",
        "Disability-prevention budget lines align to the disabilities prevention assistance listing.",
    ),
    ManualBridgeHint("vaccines for children", "93.268", "Vaccines for Children maps to the immunization cooperative agreement listing."),
)
MANUAL_HINTS_BY_KEY = {hint.budget_key: hint for hint in MANUAL_BRIDGE_HINTS}

TAGGS_PROGRAM_OFFICE_HINTS = {
    "immunization and respiratory diseases": {"NIP"},
    "hiv aids viral hepatitis sexually transmitted diseases and tuberculosis prevention": {"NCPS"},
    "hiv aids viral hepatitis sti and tb prevention": {"NCPS"},
    "emerging and zoonotic infectious diseases": {"NCZVBED"},
    "chronic disease prevention and health promotion": {"NCCDPHP"},
    "birth defects developmental disabilities disability and health": {"NCBDDD"},
    "public health scientific services": {"OSELS", "NCHS"},
    "national center for health statistics": {"NCHS"},
    "environmental health": {"NCEH", "ATSDR"},
    "injury prevention and control": {"NCIPC"},
    "occupational safety and health": {"NIOSH"},
    "global health": {"COGH", "GHC"},
    "public health preparedness and response": {"COTPER", "PHIC"},
    "cdc wide activities and program support": {"CDC", "OSELS", "OSTLTS", "CSTLTS", "PHIC"},
    "atsdr": {"ATSDR"},
}

_PARALLEL_USASPENDING_BY_YEAR: dict[int | None, list[dict[str, Any]]] | None = None
_PARALLEL_TAGGS_BY_YEAR: dict[int | None, list[dict[str, Any]]] | None = None
_PARALLEL_USASPENDING_INDICES: dict[str, dict[tuple[int | None, str], list[dict[str, Any]]]] | None = None
_PARALLEL_TAGGS_INDICES: dict[str, dict[tuple[int | None, str], list[dict[str, Any]]]] | None = None
_PARALLEL_USASPENDING_TOKEN_INDEX: dict[tuple[int | None, str], list[dict[str, Any]]] | None = None
_PARALLEL_TAGGS_TOKEN_INDEX: dict[tuple[int | None, str], list[dict[str, Any]]] | None = None
_PARALLEL_BRIDGE_VERSION: str | None = None
_PARALLEL_REVIEW_STATUS: str | None = None
_PARALLEL_BRIDGE_BATCH_ID: uuid.UUID | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the budget-grounded CDC budget-to-spending bridge v1 layer.",
    )
    parser.add_argument(
        "--bridge-version",
        default=DEFAULT_BRIDGE_VERSION,
        help=f"Bridge version label stored in {BRIDGE_TABLE_FQTN}.",
    )
    parser.add_argument(
        "--system-name",
        default="all",
        choices=("all", "usaspending", "taggs"),
        help="Which downstream system to process.",
    )
    parser.add_argument(
        "--fiscal-year",
        type=int,
        default=None,
        help="Optional single fiscal year filter applied to budget anchors and downstream source rows.",
    )
    parser.add_argument(
        "--appropriation-category",
        default=None,
        help="Optional single category or comma-separated list of categories.",
    )
    parser.add_argument(
        "--only-regular",
        action="store_true",
        help="Limit anchors to rows where is_regular_appropriation is true.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Delete existing bridge rows for the selected scope before rebuilding.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute bridge candidates and summaries without writing to the database.",
    )
    parser.add_argument(
        "--limit-anchors",
        type=int,
        default=None,
        help="Optional anchor-row cap for debugging or quick validation.",
    )
    parser.add_argument(
        "--review-status-default",
        default="unreviewed",
        choices=("unreviewed", "accepted", "rejected", "needs_review"),
        help="Review status to stamp onto newly written candidate rows.",
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


def normalize_text(value: Any) -> str:
    return normalize_rule_text(value) or ""


def normalize_aln(value: Any) -> str:
    if value is None:
        return ""
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) >= 5:
        return digits[:5]
    return digits


def quantize_score(value: Decimal | float | int | str | None) -> Decimal:
    if value is None:
        return Decimal("0.0000")
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    if value < 0:
        value = Decimal("0")
    if value > 1:
        value = Decimal("1")
    return value.quantize(SCORE_QUANTIZER, rounding=ROUND_HALF_UP)


def confidence_band(confidence: Decimal | float | int | str | None) -> str:
    normalized = quantize_score(confidence)
    if normalized >= HIGH_CONFIDENCE_MIN:
        return "HIGH"
    if normalized >= MEDIUM_CONFIDENCE_MIN:
        return "MEDIUM"
    return "LOW"


def build_budget_program_key(*parts: Any) -> str | None:
    normalized_parts = [normalize_text(part) for part in parts]
    filtered = [part for part in normalized_parts if part]
    if not filtered:
        return None
    return " > ".join(filtered)


def build_search_text(values: Iterable[Any]) -> str:
    parts = [normalize_text(value) for value in values]
    return " ".join(part for part in parts if part)


def phrase_in_text(phrase: str, text_value: str) -> bool:
    normalized_phrase = normalize_text(phrase)
    normalized_text = normalize_text(text_value)
    if not normalized_phrase or not normalized_text:
        return False
    padded_text = f" {normalized_text} "
    return f" {normalized_phrase} " in padded_text


def tokenize(value: Any) -> set[str]:
    normalized = normalize_text(value)
    if not normalized:
        return set()
    tokens = set()
    for token in normalized.split():
        if len(token) <= 2:
            continue
        if token in GENERIC_MATCH_STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def jaccard_similarity(left_tokens: set[str], right_tokens: set[str]) -> Decimal:
    if not left_tokens or not right_tokens:
        return Decimal("0")
    intersection = len(left_tokens & right_tokens)
    if intersection == 0:
        return Decimal("0")
    union = len(left_tokens | right_tokens)
    return Decimal(str(intersection / union))


def sequence_similarity(left_text: str, right_text: str) -> Decimal:
    if not left_text or not right_text:
        return Decimal("0")
    return Decimal(str(SequenceMatcher(None, left_text, right_text).ratio()))


def compute_text_similarity(left_text: str, right_text: str) -> Decimal:
    normalized_left = normalize_text(left_text)
    normalized_right = normalize_text(right_text)
    if not normalized_left or not normalized_right:
        return Decimal("0")
    if normalized_left == normalized_right:
        return Decimal("1.0")
    if phrase_in_text(normalized_left, normalized_right) or phrase_in_text(normalized_right, normalized_left):
        return Decimal("0.8600")
    left_tokens = tokenize(normalized_left)
    right_tokens = tokenize(normalized_right)
    token_score = jaccard_similarity(left_tokens, right_tokens)
    sequence_score = sequence_similarity(normalized_left, normalized_right)
    return quantize_score(max(token_score, sequence_score, (token_score + sequence_score) / Decimal("2")))


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return value


def parse_category_filter(raw_value: str | None) -> set[str] | None:
    if raw_value is None:
        return None
    parts = [str(part).strip().upper() for part in raw_value.split(",")]
    categories = {part for part in parts if part}
    return categories or None


def sql_int_list(values: Iterable[int]) -> str:
    return ", ".join(str(int(value)) for value in sorted(set(values)))


def expected_taggs_offices(anchor: Mapping[str, Any]) -> set[str]:
    norm_program = normalize_text(anchor.get("norm_program") or anchor.get("program"))
    return TAGGS_PROGRAM_OFFICE_HINTS.get(norm_program, set())


def budget_label_variants(anchor: Mapping[str, Any]) -> list[str]:
    raw_variants = [
        anchor.get("norm_sub_program_3"),
        anchor.get("norm_sub_program_2"),
        anchor.get("norm_sub_program"),
        anchor.get("norm_program_path"),
        anchor.get("norm_program"),
        build_budget_program_key(
            anchor.get("norm_program"),
            anchor.get("norm_sub_program"),
        ),
    ]
    variants: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_variants:
        normalized = normalize_text(raw_value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        variants.append(normalized)
    return variants


def anchor_primary_specific_text(anchor: Mapping[str, Any]) -> str:
    for value in (
        anchor.get("norm_sub_program_3"),
        anchor.get("norm_sub_program_2"),
        anchor.get("norm_sub_program"),
        anchor.get("norm_program"),
    ):
        normalized = normalize_text(value)
        if normalized:
            return normalized
    return ""


def anchor_match_tokens(anchor: Mapping[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for variant in budget_label_variants(anchor):
        tokens.update(tokenize(variant))
    return tokens


def manual_bridge_hints_for_anchor(anchor: Mapping[str, Any]) -> list[ManualBridgeHint]:
    hints: list[ManualBridgeHint] = []
    for variant in budget_label_variants(anchor):
        hint = MANUAL_HINTS_BY_KEY.get(variant)
        if hint is not None:
            hints.append(hint)
    return hints


def list_contains_phrase(values: Sequence[str], phrase: str) -> bool:
    return any(phrase_in_text(phrase, value) for value in values)


def usaspending_subagency_matches(anchor: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    anchor_sub_agency = normalize_text(anchor.get("sub_agency"))
    source_text = build_search_text(
        (
            row.get("awarding_sub_agency_name"),
            row.get("funding_sub_agency_name"),
        )
    )
    if "toxic substances" in anchor_sub_agency or anchor_sub_agency == "atsdr":
        return "toxic substances" in source_text or "atsdr" in source_text
    if anchor_sub_agency == "aha":
        return False
    return any(token in source_text for token in CDC_SUBAGENCY_HINTS)


def taggs_subagency_matches(anchor: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    anchor_sub_agency = normalize_text(anchor.get("sub_agency"))
    opdiv = normalize_text(row.get("opdiv"))
    if "toxic substances" in anchor_sub_agency or anchor_sub_agency == "atsdr":
        return opdiv == "atsdr"
    if anchor_sub_agency == "aha":
        return False
    return opdiv == "cdc"


def source_has_pphf_signal(row: Mapping[str, Any]) -> bool:
    values = row.get("source_text_values") or []
    return list_contains_phrase(values, "pphf") or any(
        phrase_in_text(phrase, row.get("search_text") or "") for phrase in PPHF_PHRASES
    )


def source_has_emergency_signal(row: Mapping[str, Any]) -> bool:
    if row.get("has_emergency_signal"):
        return True
    return any(phrase_in_text(phrase, row.get("search_text") or "") for phrase in EMERGENCY_PHRASES)


def source_has_transfer_signal(row: Mapping[str, Any]) -> bool:
    if row.get("has_transfer_signal"):
        return True
    return any(phrase_in_text(phrase, row.get("search_text") or "") for phrase in TRANSFER_PHRASES)


def source_has_mandatory_signal(row: Mapping[str, Any]) -> bool:
    if row.get("has_mandatory_signal"):
        return True
    return any(phrase_in_text(phrase, row.get("search_text") or "") for phrase in MANDATORY_HINT_PHRASES)


def usaspending_category_compatible(anchor: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    category = str(anchor.get("appropriation_category") or "").upper()
    if category == "REGULAR":
        if source_has_emergency_signal(row) or source_has_transfer_signal(row) or source_has_pphf_signal(row):
            return False
        return bool(row.get("has_regular_signal")) or normalize_text(row.get("appropriation_type")) in {"", "regular"}
    if category == "PPHF":
        return source_has_pphf_signal(row)
    if category == "SUPPLEMENTAL":
        return source_has_emergency_signal(row)
    if category == "TRANSFER":
        return source_has_transfer_signal(row)
    if category == "MANDATORY":
        return source_has_mandatory_signal(row)
    return False


def taggs_category_compatible(anchor: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    category = str(anchor.get("appropriation_category") or "").upper()
    if category == "REGULAR":
        if source_has_emergency_signal(row) or source_has_transfer_signal(row) or source_has_pphf_signal(row):
            return False
        return bool(row.get("is_regular_appropriation")) or bool(row.get("funding_stream"))
    if category == "PPHF":
        return source_has_pphf_signal(row)
    if category == "SUPPLEMENTAL":
        return source_has_emergency_signal(row)
    if category == "TRANSFER":
        return source_has_transfer_signal(row)
    if category == "MANDATORY":
        return source_has_mandatory_signal(row)
    return False


def load_budget_anchors(connection: Connection, args: argparse.Namespace) -> list[dict[str, Any]]:
    conditions = ["1=1"]
    params: dict[str, Any] = {}
    if args.fiscal_year is not None:
        conditions.append("fiscal_year = :fiscal_year")
        params["fiscal_year"] = args.fiscal_year
    categories = parse_category_filter(args.appropriation_category)
    if categories:
        conditions.append("appropriation_category = ANY(:appropriation_categories)")
        params["appropriation_categories"] = list(sorted(categories))
    if args.only_regular:
        conditions.append("is_regular_appropriation = TRUE")
    sql = (
        f"SELECT * FROM {ANCHOR_VIEW_FQTN} "
        f"WHERE {' AND '.join(conditions)} "
        "ORDER BY fiscal_year NULLS LAST, classification_id"
    )
    if args.limit_anchors:
        sql = f"{sql} LIMIT :limit_anchors"
        params["limit_anchors"] = args.limit_anchors
    rows = connection.execute(text(sql), params).mappings().all()
    return [dict(row) for row in rows]


def load_usaspending_awards(connection: Connection, fiscal_years: Sequence[int]) -> list[dict[str, Any]]:
    if not fiscal_years:
        return []
    years_sql = sql_int_list(fiscal_years)
    base_sql = f"""
        SELECT
            pa.unique_key,
            pa.fain,
            pa.award_latest_action_date_fiscal_year AS fiscal_year,
            pa.awarding_sub_agency_name,
            pa.funding_sub_agency_name,
            pa.cfda_program_num,
            pa.cfda_program_title,
            pa.prime_award_base_transaction_description,
            pa.appropriation_type,
            pa.total_obligated_amount
        FROM {CDC_PRIME_AWARDS_FQTN} AS pa
        WHERE pa.award_latest_action_date_fiscal_year IN ({years_sql})
          AND (
                COALESCE(pa.awarding_sub_agency_name, '') ILIKE '%Centers for Disease Control%'
             OR COALESCE(pa.funding_sub_agency_name, '') ILIKE '%Centers for Disease Control%'
             OR COALESCE(pa.awarding_sub_agency_name, '') ILIKE '%Agency for Toxic Substances%'
             OR COALESCE(pa.funding_sub_agency_name, '') ILIKE '%Agency for Toxic Substances%'
             OR COALESCE(pa.awarding_sub_agency_name, '') ILIKE '%CDC%'
             OR COALESCE(pa.funding_sub_agency_name, '') ILIKE '%CDC%'
          )
    """
    helper_sql = f"""
        SELECT
            pt.assistance_award_unique_key AS award_key,
            ARRAY_REMOVE(ARRAY_AGG(DISTINCT ata.federal_account_symbol), NULL) AS federal_account_symbols,
            ARRAY_REMOVE(ARRAY_AGG(DISTINCT fal.account_title), NULL) AS account_titles,
            ARRAY_REMOVE(ARRAY_AGG(DISTINCT pe.assistance_listing_number), NULL) AS assistance_listing_numbers,
            ARRAY_REMOVE(ARRAY_AGG(DISTINCT pe.assistance_listing_title), NULL) AS assistance_listing_titles,
            ARRAY_REMOVE(ARRAY_AGG(DISTINCT ata.program_activity_name), NULL) AS program_activity_names,
            BOOL_OR(COALESCE(fal.likely_regular_appropriation, FALSE)) AS has_regular_account,
            BOOL_OR(
                COALESCE(fal.effective_funding_stream, '') = 'transfer_or_special'
                OR COALESCE(fal.appropriations_scope_guess, '') = 'likely_special_transfer'
            ) AS has_transfer_account,
            BOOL_OR(
                COALESCE(fal.appropriations_scope_guess, '') = 'likely_emergency_supplemental'
                OR COALESCE(ata.appropriation_type, '') IN ('covid_emergency', 'other_emergency')
            ) AS has_emergency_account
        FROM {CDC_PRIME_TRANSACTIONS_FQTN} AS pt
        LEFT JOIN {ASSISTANCE_ACCOUNTS_FQTN} AS ata
          ON ata.source_transaction_id = pt.assistance_transaction_unique_key
        LEFT JOIN {FEDERAL_ACCOUNT_LOOKUP_FQTN} AS fal
          ON fal.federal_account_symbol = ata.federal_account_symbol
        LEFT JOIN {ASSISTANCE_PROFILE_FQTN} AS pe
          ON pe.source_transaction_id = pt.assistance_transaction_unique_key
        WHERE pt.action_date_fiscal_year IN ({years_sql})
        GROUP BY pt.assistance_award_unique_key
    """
    base_rows = connection.execute(text(base_sql)).mappings().all()
    helper_rows = connection.execute(text(helper_sql)).mappings().all()
    helper_by_award = {str(row["award_key"]): dict(row) for row in helper_rows if row.get("award_key")}

    rows: list[dict[str, Any]] = []
    for base_row in base_rows:
        source_record_id = str(base_row["unique_key"])
        helper = helper_by_award.get(source_record_id, {})
        federal_account_symbols = [str(value) for value in helper.get("federal_account_symbols") or [] if value]
        account_titles = [str(value) for value in helper.get("account_titles") or [] if value]
        assistance_listing_numbers = [
            str(value) for value in helper.get("assistance_listing_numbers") or [] if value
        ]
        assistance_listing_titles = [
            str(value) for value in helper.get("assistance_listing_titles") or [] if value
        ]
        program_activity_names = [
            str(value) for value in helper.get("program_activity_names") or [] if value
        ]
        source_text_values = [
            base_row.get("cfda_program_title"),
            base_row.get("prime_award_base_transaction_description"),
            *assistance_listing_titles,
            *program_activity_names,
            *account_titles,
        ]
        search_text = build_search_text(source_text_values)
        appropriation_type = normalize_text(base_row.get("appropriation_type"))
        rows.append(
            {
                "system_name": "usaspending",
                "source_table": CDC_PRIME_AWARDS_FQTN,
                "source_record_id": source_record_id,
                "source_parent_record_id": base_row.get("fain") or source_record_id,
                "source_fiscal_year": base_row.get("fiscal_year"),
                "awarding_sub_agency_name": base_row.get("awarding_sub_agency_name"),
                "funding_sub_agency_name": base_row.get("funding_sub_agency_name"),
                "cfda_program_num": base_row.get("cfda_program_num"),
                "cfda_program_title": base_row.get("cfda_program_title"),
                "prime_award_base_transaction_description": base_row.get("prime_award_base_transaction_description"),
                "appropriation_type": appropriation_type,
                "total_obligated_amount": base_row.get("total_obligated_amount"),
                "federal_account_symbols": federal_account_symbols,
                "account_titles": account_titles,
                "assistance_listing_numbers": assistance_listing_numbers,
                "assistance_listing_titles": assistance_listing_titles,
                "program_activity_names": program_activity_names,
                "normalized_alns": sorted(
                    {
                        normalize_aln(base_row.get("cfda_program_num")),
                        *(normalize_aln(value) for value in assistance_listing_numbers),
                    }
                    - {""}
                ),
                "normalized_account_titles": sorted({normalize_text(value) for value in account_titles} - {""}),
                "source_text_values": [normalize_text(value) for value in source_text_values if normalize_text(value)],
                "search_text": search_text,
                "has_regular_signal": bool(helper.get("has_regular_account")) or appropriation_type == "regular",
                "has_transfer_signal": bool(helper.get("has_transfer_account")),
                "has_emergency_signal": bool(helper.get("has_emergency_account"))
                or appropriation_type in {"covid_emergency", "other_emergency"},
                "has_mandatory_signal": any(
                    phrase_in_text(phrase, search_text) for phrase in MANDATORY_HINT_PHRASES
                ),
            }
        )
    return rows


def load_taggs_awards(connection: Connection, fiscal_years: Sequence[int]) -> list[dict[str, Any]]:
    if not fiscal_years:
        return []
    years_sql = sql_int_list(fiscal_years)
    sql = f"""
        SELECT
            s.id,
            s.award_number,
            s.funding_fiscal_year,
            s.opdiv,
            s.program_office,
            s.aln,
            s.can_code,
            s.assistance_listing_title,
            s.award_title,
            s.award_description,
            COALESCE(NULLIF(BTRIM(s.effective_program_name), ''), NULLIF(BTRIM(c.effective_program_name), '')) AS effective_program_name,
            COALESCE(NULLIF(BTRIM(s.funding_stream), ''), NULLIF(BTRIM(c.funding_stream), '')) AS funding_stream,
            COALESCE(NULLIF(BTRIM(s.appropriation_type), ''), NULLIF(BTRIM(c.appropriation_type), '')) AS appropriation_type,
            COALESCE(c.is_regular_appropriation, FALSE) AS is_regular_appropriation,
            COALESCE(c.is_supplemental, FALSE) AS is_supplemental,
            COALESCE(c.is_covid_related, FALSE) AS is_covid_related,
            COALESCE(c.is_arpa_related, FALSE) AS is_arpa_related,
            c.dominant_program_office,
            c.dominant_aln,
            s.total_sum_of_actions
        FROM {TAGGS_AWARD_SUMMARY_FQTN} AS s
        LEFT JOIN {TAGGS_CAN_CLASSIFICATION_FQTN} AS c
          ON c.can_code = s.can_code
        WHERE s.funding_fiscal_year IN ({years_sql})
          AND s.opdiv IN ('CDC', 'ATSDR')
    """
    rows = connection.execute(text(sql)).mappings().all()
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        source_text_values = [
            row.get("funding_stream"),
            row.get("effective_program_name"),
            row.get("assistance_listing_title"),
            row.get("award_title"),
            row.get("award_description"),
        ]
        search_text = build_search_text(source_text_values)
        normalized_rows.append(
            {
                "system_name": "taggs",
                "source_table": TAGGS_AWARD_SUMMARY_FQTN,
                "source_record_id": str(row["id"]),
                "source_parent_record_id": row.get("award_number"),
                "source_fiscal_year": row.get("funding_fiscal_year"),
                "opdiv": row.get("opdiv"),
                "program_office": row.get("program_office") or row.get("dominant_program_office"),
                "aln": row.get("aln") or row.get("dominant_aln"),
                "can_code": row.get("can_code"),
                "assistance_listing_title": row.get("assistance_listing_title"),
                "award_title": row.get("award_title"),
                "award_description": row.get("award_description"),
                "effective_program_name": row.get("effective_program_name"),
                "funding_stream": row.get("funding_stream"),
                "appropriation_type": normalize_text(row.get("appropriation_type")),
                "is_regular_appropriation": bool(row.get("is_regular_appropriation")),
                "is_supplemental": bool(row.get("is_supplemental")),
                "is_covid_related": bool(row.get("is_covid_related")),
                "is_arpa_related": bool(row.get("is_arpa_related")),
                "total_sum_of_actions": row.get("total_sum_of_actions"),
                "normalized_aln": normalize_aln(row.get("aln") or row.get("dominant_aln")),
                "source_text_values": [normalize_text(value) for value in source_text_values if normalize_text(value)],
                "search_text": search_text,
                "has_regular_signal": bool(row.get("is_regular_appropriation")),
                "has_transfer_signal": any(phrase_in_text(phrase, search_text) for phrase in TRANSFER_PHRASES),
                "has_emergency_signal": bool(row.get("is_covid_related"))
                or bool(row.get("is_arpa_related"))
                or bool(row.get("is_supplemental"))
                or any(phrase_in_text(phrase, search_text) for phrase in EMERGENCY_PHRASES),
                "has_mandatory_signal": any(phrase_in_text(phrase, search_text) for phrase in MANDATORY_HINT_PHRASES),
            }
        )
    return normalized_rows


def build_exact_indices(source_rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[tuple[int | None, str], list[dict[str, Any]]]]:
    indices = {
        "by_aln": defaultdict(list),
        "by_account_title": defaultdict(list),
        "by_program_text": defaultdict(list),
        "by_funding_stream": defaultdict(list),
        "by_effective_program": defaultdict(list),
    }
    for row in source_rows:
        year = row.get("source_fiscal_year")
        if row.get("system_name") == "usaspending":
            for aln in row.get("normalized_alns") or []:
                indices["by_aln"][(year, aln)].append(dict(row))
            for title in row.get("normalized_account_titles") or []:
                indices["by_account_title"][(year, title)].append(dict(row))
            for value in row.get("source_text_values") or []:
                normalized = normalize_text(value)
                if normalized:
                    indices["by_program_text"][(year, normalized)].append(dict(row))
        else:
            aln = normalize_text(row.get("normalized_aln"))
            if aln:
                indices["by_aln"][(year, aln)].append(dict(row))
            funding_stream = normalize_text(row.get("funding_stream"))
            if funding_stream:
                indices["by_funding_stream"][(year, funding_stream)].append(dict(row))
                indices["by_program_text"][(year, funding_stream)].append(dict(row))
            effective_program = normalize_text(row.get("effective_program_name"))
            if effective_program:
                indices["by_effective_program"][(year, effective_program)].append(dict(row))
                indices["by_program_text"][(year, effective_program)].append(dict(row))
            listing_title = normalize_text(row.get("assistance_listing_title"))
            if listing_title:
                indices["by_program_text"][(year, listing_title)].append(dict(row))
    return {key: dict(value) for key, value in indices.items()}


def build_token_index(source_rows: Sequence[Mapping[str, Any]]) -> dict[tuple[int | None, str], list[dict[str, Any]]]:
    index: defaultdict[tuple[int | None, str], list[dict[str, Any]]] = defaultdict(list)
    for row in source_rows:
        fiscal_year = row.get("source_fiscal_year")
        tokens = tokenize(row.get("search_text"))
        for token in tokens:
            index[(fiscal_year, token)].append(dict(row))
    return dict(index)


def build_budget_side_values(anchor: Mapping[str, Any], matched_label: str | None = None) -> dict[str, Any]:
    return json_safe(
        {
            "budget_anchor_id": anchor.get("budget_anchor_id"),
            "classification_id": anchor.get("classification_id"),
            "budget_program_key": anchor.get("budget_program_key"),
            "matched_budget_label": matched_label,
            "appropriation_category": anchor.get("appropriation_category"),
            "appropriation_subtype": anchor.get("appropriation_subtype"),
            "classification_confidence": anchor.get("classification_confidence"),
        }
    )


def build_usaspending_side_values(row: Mapping[str, Any]) -> dict[str, Any]:
    return json_safe(
        {
            "source_table": row.get("source_table"),
            "source_record_id": row.get("source_record_id"),
            "source_parent_record_id": row.get("source_parent_record_id"),
            "awarding_sub_agency_name": row.get("awarding_sub_agency_name"),
            "funding_sub_agency_name": row.get("funding_sub_agency_name"),
            "assistance_listing_number": row.get("cfda_program_num"),
            "cfda_program_title": row.get("cfda_program_title"),
            "assistance_listing_titles": row.get("assistance_listing_titles"),
            "program_activity_names": row.get("program_activity_names"),
            "award_title": row.get("cfda_program_title"),
            "award_description": row.get("prime_award_base_transaction_description"),
            "appropriation_type": row.get("appropriation_type"),
            "federal_account_symbols": row.get("federal_account_symbols"),
            "account_titles": row.get("account_titles"),
            "normalized_alns": row.get("normalized_alns"),
            "total_obligated_amount": row.get("total_obligated_amount"),
        }
    )


def build_taggs_side_values(row: Mapping[str, Any]) -> dict[str, Any]:
    return json_safe(
        {
            "source_table": row.get("source_table"),
            "source_record_id": row.get("source_record_id"),
            "source_parent_record_id": row.get("source_parent_record_id"),
            "opdiv": row.get("opdiv"),
            "program_office": row.get("program_office"),
            "aln": row.get("aln"),
            "can_code": row.get("can_code"),
            "assistance_listing_title": row.get("assistance_listing_title"),
            "award_title": row.get("award_title"),
            "award_description": row.get("award_description"),
            "effective_program_name": row.get("effective_program_name"),
            "funding_stream": row.get("funding_stream"),
            "appropriation_type": row.get("appropriation_type"),
            "is_regular_appropriation": row.get("is_regular_appropriation"),
            "is_supplemental": row.get("is_supplemental"),
            "is_covid_related": row.get("is_covid_related"),
            "is_arpa_related": row.get("is_arpa_related"),
            "total_sum_of_actions": row.get("total_sum_of_actions"),
        }
    )


def make_candidate_row(
    *,
    anchor: Mapping[str, Any],
    source_row: Mapping[str, Any],
    bridge_version: str,
    bridge_batch_id: uuid.UUID,
    review_status: str,
    rule_code: str,
    matched_fields: Sequence[str],
    matched_label: str | None,
    explanation: str,
    match_score: Decimal | None = None,
    match_confidence: Decimal | None = None,
) -> dict[str, Any]:
    rule = RULES_BY_CODE[rule_code]
    return {
        "bridge_batch_id": bridge_batch_id,
        "bridge_version": bridge_version,
        "budget_anchor_id": str(anchor["budget_anchor_id"]),
        "classification_id": anchor["classification_id"],
        "raw_budget_id": anchor["raw_budget_id"],
        "unique_id": anchor["unique_id"],
        "fiscal_year": anchor.get("fiscal_year"),
        "budget_agency": anchor.get("agency"),
        "budget_sub_agency": anchor.get("sub_agency"),
        "budget_program": anchor.get("program"),
        "budget_sub_program": anchor.get("sub_program"),
        "budget_sub_program_2": anchor.get("sub_program_2"),
        "budget_sub_program_3": anchor.get("sub_program_3"),
        "budget_program_key": anchor.get("budget_program_key"),
        "appropriation_category": anchor.get("appropriation_category"),
        "appropriation_subtype": anchor.get("appropriation_subtype"),
        "is_regular_appropriation": bool(anchor.get("is_regular_appropriation")),
        "classification_confidence": anchor.get("classification_confidence"),
        "primary_rule_code": anchor.get("primary_rule_code"),
        "system_name": source_row["system_name"],
        "source_table": source_row["source_table"],
        "source_record_id": str(source_row["source_record_id"]),
        "source_parent_record_id": source_row.get("source_parent_record_id"),
        "source_fiscal_year": source_row.get("source_fiscal_year"),
        "match_rule_code": rule.rule_code,
        "match_tier": rule.tier,
        "match_type": rule.match_type,
        "match_score": quantize_score(match_score or rule.default_match_score),
        "match_confidence": quantize_score(match_confidence or rule.default_match_confidence),
        "confidence_band": rule.default_confidence_band,
        "is_auto_accepted": False,
        "is_excluded": False,
        "exclusion_reason": None,
        "match_explanation": explanation,
        "matched_on_fields": sorted(set(str(value) for value in matched_fields if value)),
        "budget_side_values": build_budget_side_values(anchor, matched_label=matched_label),
        "spending_side_values": (
            build_usaspending_side_values(source_row)
            if source_row["system_name"] == "usaspending"
            else build_taggs_side_values(source_row)
        ),
        "review_status": review_status,
        "review_notes": None,
        "allocation_pct": None,
        "allocation_method": None,
        "allocation_notes": None,
    }


def deduplicate_candidates(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for candidate in candidates:
        key = (
            str(candidate["bridge_version"]),
            str(candidate["budget_anchor_id"]),
            str(candidate["system_name"]),
            str(candidate["source_record_id"]),
            str(candidate["match_type"]),
        )
        if key not in deduped:
            deduped[key] = dict(candidate)
            continue
        existing = deduped[key]
        if Decimal(str(candidate["match_score"])) > Decimal(str(existing["match_score"])):
            keep, merge = dict(candidate), existing
        else:
            keep, merge = existing, candidate
        keep["matched_on_fields"] = sorted(
            set(keep.get("matched_on_fields") or []) | set(merge.get("matched_on_fields") or [])
        )
        keep["match_confidence"] = quantize_score(
            max(Decimal(str(keep["match_confidence"])), Decimal(str(merge["match_confidence"])))
        )
        keep["match_score"] = quantize_score(
            max(Decimal(str(keep["match_score"])), Decimal(str(merge["match_score"])))
        )
        deduped[key] = keep
    return list(deduped.values())


def finalize_confidence_and_auto_accept(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_anchor_system: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_source_system: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        by_anchor_system[(candidate["budget_anchor_id"], candidate["system_name"])].append(candidate)
        by_source_system[(candidate["system_name"], candidate["source_record_id"])].append(candidate)

    for candidate in candidates:
        rule = RULES_BY_CODE[str(candidate["match_rule_code"])]
        base_confidence = Decimal(str(candidate["match_confidence"]))
        anchor_count = len(by_anchor_system[(candidate["budget_anchor_id"], candidate["system_name"])])
        source_count = len(by_source_system[(candidate["system_name"], candidate["source_record_id"])])
        anchor_penalty_step = {
            "TIER_A_DETERMINISTIC": Decimal("0.0050"),
            "TIER_B_STRUCTURED": Decimal("0.0100"),
            "TIER_C_FUZZY_CANDIDATE": Decimal("0.0150"),
        }[rule.tier]
        source_penalty_step = {
            "TIER_A_DETERMINISTIC": Decimal("0.0030"),
            "TIER_B_STRUCTURED": Decimal("0.0060"),
            "TIER_C_FUZZY_CANDIDATE": Decimal("0.0100"),
        }[rule.tier]
        confidence = base_confidence
        if anchor_count > 1:
            confidence -= anchor_penalty_step * Decimal(min(anchor_count - 1, 6))
        if source_count > 1:
            confidence -= source_penalty_step * Decimal(min(source_count - 1, 6))
        if anchor_count == 1 and source_count == 1 and rule.tier == "TIER_A_DETERMINISTIC":
            confidence += Decimal("0.0100")
        if rule.tier == "TIER_C_FUZZY_CANDIDATE":
            confidence = min(confidence, Decimal("0.7400"))
        candidate["match_confidence"] = quantize_score(confidence)
        candidate["confidence_band"] = confidence_band(candidate["match_confidence"])
        candidate["is_auto_accepted"] = (
            rule.tier == "TIER_A_DETERMINISTIC"
            and candidate["confidence_band"] == "HIGH"
            and anchor_count == 1
            and source_count == 1
            and not candidate["is_excluded"]
        )
    return candidates


def sort_candidates(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (dict(candidate) for candidate in candidates),
        key=lambda row: (
            row.get("system_name"),
            row.get("fiscal_year") or 0,
            row.get("budget_anchor_id"),
            -float(row.get("match_confidence") or 0),
            str(row.get("match_rule_code")),
            str(row.get("source_record_id")),
        ),
    )


def generate_manual_seeded_candidates(
    *,
    anchor: Mapping[str, Any],
    source_indices: Mapping[str, Mapping[tuple[int | None, str], list[dict[str, Any]]]],
    system_name: str,
    bridge_version: str,
    bridge_batch_id: uuid.UUID,
    review_status: str,
) -> list[dict[str, Any]]:
    fiscal_year = anchor.get("fiscal_year")
    candidates: list[dict[str, Any]] = []
    for hint in manual_bridge_hints_for_anchor(anchor):
        for row in source_indices["by_aln"].get((fiscal_year, normalize_aln(hint.aln)), []):
            if row["system_name"] != system_name:
                continue
            if system_name == "usaspending":
                if not usaspending_subagency_matches(anchor, row) or not usaspending_category_compatible(anchor, row):
                    continue
                rule_code = "BRIDGE_USA_A003"
                matched_fields = ("budget_program_key", "cfda_program_num", "assistance_listing_title")
            else:
                if not taggs_subagency_matches(anchor, row) or not taggs_category_compatible(anchor, row):
                    continue
                rule_code = "BRIDGE_TAGGS_A003"
                matched_fields = ("budget_program_key", "aln", "can_code")
            explanation = (
                f"Manual seeded bridge matched budget label '{hint.budget_key}' to ALN {hint.aln}. "
                f"{hint.description}"
            )
            candidates.append(
                make_candidate_row(
                    anchor=anchor,
                    source_row=row,
                    bridge_version=bridge_version,
                    bridge_batch_id=bridge_batch_id,
                    review_status=review_status,
                    rule_code=rule_code,
                    matched_fields=matched_fields,
                    matched_label=hint.budget_key,
                    explanation=explanation,
                )
            )
    return deduplicate_candidates(candidates)


def generate_usaspending_exact_account_candidates(
    *,
    anchor: Mapping[str, Any],
    source_indices: Mapping[str, Mapping[tuple[int | None, str], list[dict[str, Any]]]],
    bridge_version: str,
    bridge_batch_id: uuid.UUID,
    review_status: str,
) -> list[dict[str, Any]]:
    if any(anchor.get(field) for field in ("norm_sub_program", "norm_sub_program_2", "norm_sub_program_3")):
        return []
    fiscal_year = anchor.get("fiscal_year")
    norm_program = normalize_text(anchor.get("norm_program"))
    if not norm_program:
        return []
    candidates: list[dict[str, Any]] = []
    for row in source_indices["by_account_title"].get((fiscal_year, norm_program), []):
        if not usaspending_subagency_matches(anchor, row) or not usaspending_category_compatible(anchor, row):
            continue
        matched_symbols = row.get("federal_account_symbols") or []
        explanation = (
            f"Verified federal-account title exactly matches the budget program '{anchor.get('program')}'. "
            f"USAspending award lineage includes federal account(s): {', '.join(matched_symbols) or 'unknown'}."
        )
        candidates.append(
            make_candidate_row(
                anchor=anchor,
                source_row=row,
                bridge_version=bridge_version,
                bridge_batch_id=bridge_batch_id,
                review_status=review_status,
                rule_code="BRIDGE_USA_A001",
                matched_fields=("budget_program", "federal_account_symbol", "account_title"),
                matched_label=norm_program,
                explanation=explanation,
            )
        )
    return deduplicate_candidates(candidates)


def exact_program_match_fields(anchor_variants: Sequence[str], source_fields: Mapping[str, Any]) -> tuple[str | None, list[str]]:
    for variant in anchor_variants:
        if len(variant) < 5:
            continue
        matched_fields: list[str] = []
        for field_name, field_value in source_fields.items():
            field_text = normalize_text(field_value)
            if not field_text:
                continue
            if variant == field_text or phrase_in_text(variant, field_text):
                matched_fields.append(field_name)
        if matched_fields:
            return variant, matched_fields
    return None, []


def generate_usaspending_structured_candidates(
    *,
    anchor: Mapping[str, Any],
    source_indices: Mapping[str, Mapping[tuple[int | None, str], list[dict[str, Any]]]],
    by_year_rows: Mapping[int | None, Sequence[dict[str, Any]]],
    token_index: Mapping[tuple[int | None, str], Sequence[dict[str, Any]]],
    bridge_version: str,
    bridge_batch_id: uuid.UUID,
    review_status: str,
) -> list[dict[str, Any]]:
    anchor_variants = budget_label_variants(anchor)
    specific_label = anchor_primary_specific_text(anchor)
    candidates: list[dict[str, Any]] = []
    parent_program = normalize_text(anchor.get("norm_program"))
    parent_account_rows = []
    if parent_program:
        parent_account_rows = source_indices["by_account_title"].get((anchor.get("fiscal_year"), parent_program), [])
    for row in parent_account_rows:
        if not usaspending_subagency_matches(anchor, row) or not usaspending_category_compatible(anchor, row):
            continue
        if specific_label and specific_label != parent_program:
            supporting_fields = {
                "assistance_listing_titles": " ".join(row.get("assistance_listing_titles") or []),
                "program_activity_names": " ".join(row.get("program_activity_names") or []),
                "prime_award_base_transaction_description": row.get("prime_award_base_transaction_description"),
            }
            if any(phrase_in_text(specific_label, value or "") for value in supporting_fields.values()):
                explanation = (
                    f"USAspending award carries the verified parent federal account for '{anchor.get('program')}' "
                    f"and also references the more specific budget label '{specific_label}'."
                )
                candidates.append(
                    make_candidate_row(
                        anchor=anchor,
                        source_row=row,
                        bridge_version=bridge_version,
                        bridge_batch_id=bridge_batch_id,
                        review_status=review_status,
                        rule_code="BRIDGE_USA_B002",
                        matched_fields=("account_title", *supporting_fields.keys()),
                        matched_label=specific_label,
                        explanation=explanation,
                    )
                )
                if len(candidates) >= MAX_STRUCTURED_CANDIDATES_PER_RULE:
                    break

    structured_pool = filter_structured_pool(
        anchor=anchor,
        by_year_rows=by_year_rows,
        token_index=token_index,
        system_name="usaspending",
    )
    for row in structured_pool:
        if not usaspending_subagency_matches(anchor, row) or not usaspending_category_compatible(anchor, row):
            continue
        source_fields = {
            "cfda_program_title": row.get("cfda_program_title"),
            "assistance_listing_titles": " ".join(row.get("assistance_listing_titles") or []),
            "program_activity_names": " ".join(row.get("program_activity_names") or []),
            "prime_award_base_transaction_description": row.get("prime_award_base_transaction_description"),
        }
        matched_label, matched_fields = exact_program_match_fields(anchor_variants, source_fields)
        if matched_fields:
            explanation = (
                f"Budget label '{matched_label}' appears directly in USAspending award text for the same fiscal year."
            )
            candidates.append(
                make_candidate_row(
                    anchor=anchor,
                    source_row=row,
                    bridge_version=bridge_version,
                    bridge_batch_id=bridge_batch_id,
                    review_status=review_status,
                    rule_code="BRIDGE_USA_B001",
                    matched_fields=matched_fields,
                    matched_label=matched_label,
                    explanation=explanation,
                )
            )
        if len(candidates) >= MAX_STRUCTURED_CANDIDATES_PER_RULE * 2:
            break
    return deduplicate_candidates(candidates)


def generate_taggs_exact_candidates(
    *,
    anchor: Mapping[str, Any],
    source_indices: Mapping[str, Mapping[tuple[int | None, str], list[dict[str, Any]]]],
    bridge_version: str,
    bridge_batch_id: uuid.UUID,
    review_status: str,
) -> list[dict[str, Any]]:
    fiscal_year = anchor.get("fiscal_year")
    candidates: list[dict[str, Any]] = []
    for variant in budget_label_variants(anchor):
        matched_rows = []
        matched_rows.extend(source_indices["by_funding_stream"].get((fiscal_year, variant), []))
        matched_rows.extend(source_indices["by_effective_program"].get((fiscal_year, variant), []))
        for row in matched_rows:
            if not taggs_subagency_matches(anchor, row) or not taggs_category_compatible(anchor, row):
                continue
            explanation = (
                f"Budget label '{variant}' exactly matches a normalized TAGGS funding-stream or effective-program label."
            )
            candidates.append(
                make_candidate_row(
                    anchor=anchor,
                    source_row=row,
                    bridge_version=bridge_version,
                    bridge_batch_id=bridge_batch_id,
                    review_status=review_status,
                    rule_code="BRIDGE_TAGGS_A001",
                    matched_fields=("budget_program_key", "funding_stream", "effective_program_name"),
                    matched_label=variant,
                    explanation=explanation,
                )
            )
    return deduplicate_candidates(candidates)


def generate_taggs_structured_candidates(
    *,
    anchor: Mapping[str, Any],
    by_year_rows: Mapping[int | None, Sequence[dict[str, Any]]],
    token_index: Mapping[tuple[int | None, str], Sequence[dict[str, Any]]],
    bridge_version: str,
    bridge_batch_id: uuid.UUID,
    review_status: str,
) -> list[dict[str, Any]]:
    anchor_variants = budget_label_variants(anchor)
    office_hints = expected_taggs_offices(anchor)
    candidates: list[dict[str, Any]] = []
    structured_pool = filter_structured_pool(
        anchor=anchor,
        by_year_rows=by_year_rows,
        token_index=token_index,
        system_name="taggs",
    )
    for row in structured_pool:
        if not taggs_subagency_matches(anchor, row) or not taggs_category_compatible(anchor, row):
            continue
        source_fields = {
            "funding_stream": row.get("funding_stream"),
            "effective_program_name": row.get("effective_program_name"),
            "assistance_listing_title": row.get("assistance_listing_title"),
            "award_title": row.get("award_title"),
        }
        matched_label, matched_fields = exact_program_match_fields(anchor_variants, source_fields)
        if matched_fields:
            candidates.append(
                make_candidate_row(
                    anchor=anchor,
                    source_row=row,
                    bridge_version=bridge_version,
                    bridge_batch_id=bridge_batch_id,
                    review_status=review_status,
                    rule_code="BRIDGE_TAGGS_B001",
                    matched_fields=matched_fields,
                    matched_label=matched_label,
                    explanation=(
                        f"Budget label '{matched_label}' appears directly in TAGGS program, funding-stream, or assistance-listing text."
                    ),
                )
            )
            if len(candidates) >= MAX_STRUCTURED_CANDIDATES_PER_RULE:
                break
        if office_hints and str(row.get("program_office") or "") in office_hints:
            if matched_label:
                candidates.append(
                    make_candidate_row(
                        anchor=anchor,
                        source_row=row,
                        bridge_version=bridge_version,
                        bridge_batch_id=bridge_batch_id,
                        review_status=review_status,
                        rule_code="BRIDGE_TAGGS_B002",
                        matched_fields=("program_office", *matched_fields),
                        matched_label=matched_label,
                        explanation=(
                            f"Expected CDC TAGGS program office '{row.get('program_office')}' aligns with the budget program "
                            f"and the award also contains budget label '{matched_label}'."
                        ),
                    )
                )
                if len(candidates) >= MAX_STRUCTURED_CANDIDATES_PER_RULE * 2:
                    break
    return deduplicate_candidates(candidates)


def filter_fuzzy_pool(
    *,
    anchor: Mapping[str, Any],
    by_year_rows: Mapping[int | None, Sequence[dict[str, Any]]],
    token_index: Mapping[tuple[int | None, str], Sequence[dict[str, Any]]],
    system_name: str,
) -> list[dict[str, Any]]:
    fiscal_year = anchor.get("fiscal_year")
    primary_text = anchor_primary_specific_text(anchor)
    tokens = tokenize(primary_text)
    if not tokens:
        return []
    office_hints = expected_taggs_offices(anchor)
    hit_counts: Counter[str] = Counter()
    rows_by_id: dict[str, dict[str, Any]] = {}
    for token in tokens:
        for row in token_index.get((fiscal_year, token), []):
            if row["system_name"] != system_name:
                continue
            row_id = str(row["source_record_id"])
            if system_name == "usaspending":
                if not usaspending_subagency_matches(anchor, row) or not usaspending_category_compatible(anchor, row):
                    continue
            else:
                if not taggs_subagency_matches(anchor, row) or not taggs_category_compatible(anchor, row):
                    continue
                if office_hints and str(row.get("program_office") or "") not in office_hints:
                    continue
            hit_counts[row_id] += 1
            rows_by_id[row_id] = dict(row)
    minimum_hits = 2 if len(tokens) >= 2 else 1
    pool = {
        row_id: row
        for row_id, row in rows_by_id.items()
        if hit_counts[row_id] >= minimum_hits
    }
    if pool:
        return list(pool.values())
    # Fall back to the same-year pool only if token narrowing produced nothing.
    fallback_rows = list(by_year_rows.get(fiscal_year, []))
    trimmed: list[dict[str, Any]] = []
    for row in fallback_rows:
        if row["system_name"] != system_name:
            continue
        if system_name == "usaspending":
            if usaspending_subagency_matches(anchor, row) and usaspending_category_compatible(anchor, row):
                trimmed.append(dict(row))
        else:
            if taggs_subagency_matches(anchor, row) and taggs_category_compatible(anchor, row):
                if not office_hints or str(row.get("program_office") or "") in office_hints:
                    trimmed.append(dict(row))
    return trimmed


def filter_structured_pool(
    *,
    anchor: Mapping[str, Any],
    by_year_rows: Mapping[int | None, Sequence[dict[str, Any]]],
    token_index: Mapping[tuple[int | None, str], Sequence[dict[str, Any]]],
    system_name: str,
) -> list[dict[str, Any]]:
    fiscal_year = anchor.get("fiscal_year")
    tokens = tokenize(anchor_primary_specific_text(anchor))
    if not tokens:
        tokens = anchor_match_tokens(anchor)
    office_hints = expected_taggs_offices(anchor)
    hit_counts: Counter[str] = Counter()
    rows_by_id: dict[str, dict[str, Any]] = {}
    for token in tokens:
        for row in token_index.get((fiscal_year, token), []):
            if row["system_name"] != system_name:
                continue
            if system_name == "usaspending":
                if not usaspending_subagency_matches(anchor, row) or not usaspending_category_compatible(anchor, row):
                    continue
            else:
                if not taggs_subagency_matches(anchor, row) or not taggs_category_compatible(anchor, row):
                    continue
                if office_hints and str(row.get("program_office") or "") not in office_hints:
                    continue
            row_id = str(row["source_record_id"])
            hit_counts[row_id] += 1
            rows_by_id[row_id] = dict(row)
    minimum_hits = 2 if len(tokens) >= 2 else 1
    pool = {
        row_id: row
        for row_id, row in rows_by_id.items()
        if hit_counts[row_id] >= minimum_hits
    }
    if pool:
        return list(pool.values())
    return filter_fuzzy_pool(
        anchor=anchor,
        by_year_rows=by_year_rows,
        token_index=token_index,
        system_name=system_name,
    )


def generate_fuzzy_candidates(
    *,
    anchor: Mapping[str, Any],
    by_year_rows: Mapping[int | None, Sequence[dict[str, Any]]],
    token_index: Mapping[tuple[int | None, str], Sequence[dict[str, Any]]],
    bridge_version: str,
    bridge_batch_id: uuid.UUID,
    review_status: str,
    system_name: str,
    existing_count: int,
) -> list[dict[str, Any]]:
    if existing_count >= 5:
        return []
    primary_text = anchor_primary_specific_text(anchor)
    if not primary_text:
        return []
    rule_code = "BRIDGE_USA_C001" if system_name == "usaspending" else "BRIDGE_TAGGS_C001"
    pool = filter_fuzzy_pool(
        anchor=anchor,
        by_year_rows=by_year_rows,
        token_index=token_index,
        system_name=system_name,
    )
    scored: list[tuple[Decimal, dict[str, Any]]] = []
    for row in pool:
        similarity = compute_text_similarity(primary_text, row.get("search_text") or "")
        if similarity < Decimal("0.5500"):
            continue
        scored.append((similarity, row))
    scored.sort(key=lambda item: (-float(item[0]), str(item[1].get("source_record_id"))))
    candidates: list[dict[str, Any]] = []
    for similarity, row in scored[:MAX_FUZZY_CANDIDATES_PER_ANCHOR]:
        explanation = (
            f"Constrained fuzzy candidate: budget label '{primary_text}' is text-similar to downstream record text."
        )
        candidates.append(
            make_candidate_row(
                anchor=anchor,
                source_row=row,
                bridge_version=bridge_version,
                bridge_batch_id=bridge_batch_id,
                review_status=review_status,
                rule_code=rule_code,
                matched_fields=("budget_program_key", "search_text"),
                matched_label=primary_text,
                explanation=explanation,
                match_score=similarity,
                match_confidence=min(similarity, Decimal("0.7400")),
            )
        )
    return deduplicate_candidates(candidates)


def configure_parallel_context(
    *,
    usaspending_by_year: Mapping[int | None, Sequence[dict[str, Any]]],
    taggs_by_year: Mapping[int | None, Sequence[dict[str, Any]]],
    usaspending_indices: Mapping[str, Mapping[tuple[int | None, str], list[dict[str, Any]]]],
    taggs_indices: Mapping[str, Mapping[tuple[int | None, str], list[dict[str, Any]]]],
    usaspending_token_index: Mapping[tuple[int | None, str], Sequence[dict[str, Any]]],
    taggs_token_index: Mapping[tuple[int | None, str], Sequence[dict[str, Any]]],
    bridge_version: str,
    review_status: str,
    bridge_batch_id: uuid.UUID,
) -> None:
    global _PARALLEL_USASPENDING_BY_YEAR
    global _PARALLEL_TAGGS_BY_YEAR
    global _PARALLEL_USASPENDING_INDICES
    global _PARALLEL_TAGGS_INDICES
    global _PARALLEL_USASPENDING_TOKEN_INDEX
    global _PARALLEL_TAGGS_TOKEN_INDEX
    global _PARALLEL_BRIDGE_VERSION
    global _PARALLEL_REVIEW_STATUS
    global _PARALLEL_BRIDGE_BATCH_ID

    _PARALLEL_USASPENDING_BY_YEAR = {key: list(value) for key, value in usaspending_by_year.items()}
    _PARALLEL_TAGGS_BY_YEAR = {key: list(value) for key, value in taggs_by_year.items()}
    _PARALLEL_USASPENDING_INDICES = {key: dict(value) for key, value in usaspending_indices.items()}
    _PARALLEL_TAGGS_INDICES = {key: dict(value) for key, value in taggs_indices.items()}
    _PARALLEL_USASPENDING_TOKEN_INDEX = {key: list(value) for key, value in usaspending_token_index.items()}
    _PARALLEL_TAGGS_TOKEN_INDEX = {key: list(value) for key, value in taggs_token_index.items()}
    _PARALLEL_BRIDGE_VERSION = bridge_version
    _PARALLEL_REVIEW_STATUS = review_status
    _PARALLEL_BRIDGE_BATCH_ID = bridge_batch_id


def build_anchor_candidates(anchor: Mapping[str, Any]) -> list[dict[str, Any]]:
    if (
        _PARALLEL_USASPENDING_BY_YEAR is None
        or _PARALLEL_TAGGS_BY_YEAR is None
        or _PARALLEL_USASPENDING_INDICES is None
        or _PARALLEL_TAGGS_INDICES is None
        or _PARALLEL_USASPENDING_TOKEN_INDEX is None
        or _PARALLEL_TAGGS_TOKEN_INDEX is None
        or _PARALLEL_BRIDGE_VERSION is None
        or _PARALLEL_REVIEW_STATUS is None
        or _PARALLEL_BRIDGE_BATCH_ID is None
    ):
        raise RuntimeError("Parallel bridge context has not been configured.")

    anchor_candidates: list[dict[str, Any]] = []
    anchor_candidates.extend(
        generate_manual_seeded_candidates(
            anchor=anchor,
            source_indices=_PARALLEL_USASPENDING_INDICES,
            system_name="usaspending",
            bridge_version=_PARALLEL_BRIDGE_VERSION,
            bridge_batch_id=_PARALLEL_BRIDGE_BATCH_ID,
            review_status=_PARALLEL_REVIEW_STATUS,
        )
    )
    anchor_candidates.extend(
        generate_usaspending_exact_account_candidates(
            anchor=anchor,
            source_indices=_PARALLEL_USASPENDING_INDICES,
            bridge_version=_PARALLEL_BRIDGE_VERSION,
            bridge_batch_id=_PARALLEL_BRIDGE_BATCH_ID,
            review_status=_PARALLEL_REVIEW_STATUS,
        )
    )
    anchor_candidates.extend(
        generate_usaspending_structured_candidates(
            anchor=anchor,
            source_indices=_PARALLEL_USASPENDING_INDICES,
            by_year_rows=_PARALLEL_USASPENDING_BY_YEAR,
            token_index=_PARALLEL_USASPENDING_TOKEN_INDEX,
            bridge_version=_PARALLEL_BRIDGE_VERSION,
            bridge_batch_id=_PARALLEL_BRIDGE_BATCH_ID,
            review_status=_PARALLEL_REVIEW_STATUS,
        )
    )
    anchor_candidates.extend(
        generate_fuzzy_candidates(
            anchor=anchor,
            by_year_rows=_PARALLEL_USASPENDING_BY_YEAR,
            token_index=_PARALLEL_USASPENDING_TOKEN_INDEX,
            bridge_version=_PARALLEL_BRIDGE_VERSION,
            bridge_batch_id=_PARALLEL_BRIDGE_BATCH_ID,
            review_status=_PARALLEL_REVIEW_STATUS,
            system_name="usaspending",
            existing_count=len([row for row in anchor_candidates if row["system_name"] == "usaspending"]),
        )
    )
    anchor_candidates.extend(
        generate_manual_seeded_candidates(
            anchor=anchor,
            source_indices=_PARALLEL_TAGGS_INDICES,
            system_name="taggs",
            bridge_version=_PARALLEL_BRIDGE_VERSION,
            bridge_batch_id=_PARALLEL_BRIDGE_BATCH_ID,
            review_status=_PARALLEL_REVIEW_STATUS,
        )
    )
    anchor_candidates.extend(
        generate_taggs_exact_candidates(
            anchor=anchor,
            source_indices=_PARALLEL_TAGGS_INDICES,
            bridge_version=_PARALLEL_BRIDGE_VERSION,
            bridge_batch_id=_PARALLEL_BRIDGE_BATCH_ID,
            review_status=_PARALLEL_REVIEW_STATUS,
        )
    )
    anchor_candidates.extend(
        generate_taggs_structured_candidates(
            anchor=anchor,
            by_year_rows=_PARALLEL_TAGGS_BY_YEAR,
            token_index=_PARALLEL_TAGGS_TOKEN_INDEX,
            bridge_version=_PARALLEL_BRIDGE_VERSION,
            bridge_batch_id=_PARALLEL_BRIDGE_BATCH_ID,
            review_status=_PARALLEL_REVIEW_STATUS,
        )
    )
    anchor_candidates.extend(
        generate_fuzzy_candidates(
            anchor=anchor,
            by_year_rows=_PARALLEL_TAGGS_BY_YEAR,
            token_index=_PARALLEL_TAGGS_TOKEN_INDEX,
            bridge_version=_PARALLEL_BRIDGE_VERSION,
            bridge_batch_id=_PARALLEL_BRIDGE_BATCH_ID,
            review_status=_PARALLEL_REVIEW_STATUS,
            system_name="taggs",
            existing_count=len([row for row in anchor_candidates if row["system_name"] == "taggs"]),
        )
    )
    return deduplicate_candidates(anchor_candidates)


def build_bridge_rows(
    *,
    anchors: Sequence[Mapping[str, Any]],
    usaspending_rows: Sequence[Mapping[str, Any]],
    taggs_rows: Sequence[Mapping[str, Any]],
    bridge_version: str,
    review_status: str,
) -> list[dict[str, Any]]:
    bridge_batch_id = uuid.uuid4()
    usaspending_by_year: defaultdict[int | None, list[dict[str, Any]]] = defaultdict(list)
    for row in usaspending_rows:
        usaspending_by_year[row.get("source_fiscal_year")].append(dict(row))
    taggs_by_year: defaultdict[int | None, list[dict[str, Any]]] = defaultdict(list)
    for row in taggs_rows:
        taggs_by_year[row.get("source_fiscal_year")].append(dict(row))

    usaspending_indices = build_exact_indices(usaspending_rows)
    taggs_indices = build_exact_indices(taggs_rows)
    usaspending_token_index = build_token_index(usaspending_rows)
    taggs_token_index = build_token_index(taggs_rows)
    configure_parallel_context(
        usaspending_by_year=usaspending_by_year,
        taggs_by_year=taggs_by_year,
        usaspending_indices=usaspending_indices,
        taggs_indices=taggs_indices,
        usaspending_token_index=usaspending_token_index,
        taggs_token_index=taggs_token_index,
        bridge_version=bridge_version,
        review_status=review_status,
        bridge_batch_id=bridge_batch_id,
    )

    all_candidates: list[dict[str, Any]] = []
    if len(anchors) >= 100 and os.name != "nt":
        worker_count = min(4, os.cpu_count() or 1)
        with mp.get_context("fork").Pool(processes=worker_count) as pool:
            for anchor_candidates in pool.imap_unordered(build_anchor_candidates, anchors, chunksize=8):
                all_candidates.extend(anchor_candidates)
    else:
        for anchor in anchors:
            all_candidates.extend(build_anchor_candidates(anchor))

    deduped = deduplicate_candidates(all_candidates)
    return sort_candidates(finalize_confidence_and_auto_accept(deduped))


def seed_rule_registry(
    connection: Connection,
    *,
    bridge_version: str,
    dry_run: bool,
) -> None:
    rows = [
        {
            "rule_code": rule.rule_code,
            "bridge_version": bridge_version,
            "rule_group": rule.rule_group,
            "tier": rule.tier,
            "system_name": rule.system_name,
            "description": rule.description,
            "match_type": rule.match_type,
            "default_match_score": quantize_score(rule.default_match_score),
            "default_match_confidence": quantize_score(rule.default_match_confidence),
            "default_confidence_band": rule.default_confidence_band,
            "priority": rule.priority,
            "is_active": True,
        }
        for rule in RULE_DEFINITIONS
    ]
    if dry_run:
        return
    insert_stmt = pg_insert(BRIDGE_RULE_TABLE).values(rows)
    update_columns = {
        "bridge_version": insert_stmt.excluded.bridge_version,
        "rule_group": insert_stmt.excluded.rule_group,
        "tier": insert_stmt.excluded.tier,
        "system_name": insert_stmt.excluded.system_name,
        "description": insert_stmt.excluded.description,
        "match_type": insert_stmt.excluded.match_type,
        "default_match_score": insert_stmt.excluded.default_match_score,
        "default_match_confidence": insert_stmt.excluded.default_match_confidence,
        "default_confidence_band": insert_stmt.excluded.default_confidence_band,
        "priority": insert_stmt.excluded.priority,
        "is_active": insert_stmt.excluded.is_active,
    }
    connection.execute(
        insert_stmt.on_conflict_do_update(
            index_elements=[BRIDGE_RULE_TABLE.c.rule_code],
            set_=update_columns,
        )
    )


def truncate_bridge_scope(
    connection: Connection,
    *,
    bridge_version: str,
    anchor_ids: Sequence[str],
    system_name: str,
    dry_run: bool,
) -> int:
    if dry_run or not anchor_ids:
        return 0
    conditions = ["bridge_version = :bridge_version", "budget_anchor_id = ANY(:anchor_ids)"]
    params: dict[str, Any] = {
        "bridge_version": bridge_version,
        "anchor_ids": list(anchor_ids),
    }
    if system_name != "all":
        conditions.append("system_name = :system_name")
        params["system_name"] = system_name
    delete_sql = f"DELETE FROM {BRIDGE_TABLE_FQTN} WHERE {' AND '.join(conditions)}"
    result = connection.execute(text(delete_sql), params)
    return int(result.rowcount or 0)


def upsert_bridge_rows(
    connection: Connection,
    *,
    rows: Sequence[Mapping[str, Any]],
    batch_size: int,
    dry_run: bool,
) -> int:
    if dry_run or not rows:
        return 0
    written = 0
    for offset in range(0, len(rows), batch_size):
        batch = [dict(row) for row in rows[offset : offset + batch_size]]
        insert_stmt = pg_insert(BRIDGE_TABLE).values(batch)
        update_columns = {
            "bridge_batch_id": insert_stmt.excluded.bridge_batch_id,
            "classification_id": insert_stmt.excluded.classification_id,
            "raw_budget_id": insert_stmt.excluded.raw_budget_id,
            "unique_id": insert_stmt.excluded.unique_id,
            "fiscal_year": insert_stmt.excluded.fiscal_year,
            "budget_agency": insert_stmt.excluded.budget_agency,
            "budget_sub_agency": insert_stmt.excluded.budget_sub_agency,
            "budget_program": insert_stmt.excluded.budget_program,
            "budget_sub_program": insert_stmt.excluded.budget_sub_program,
            "budget_sub_program_2": insert_stmt.excluded.budget_sub_program_2,
            "budget_sub_program_3": insert_stmt.excluded.budget_sub_program_3,
            "budget_program_key": insert_stmt.excluded.budget_program_key,
            "appropriation_category": insert_stmt.excluded.appropriation_category,
            "appropriation_subtype": insert_stmt.excluded.appropriation_subtype,
            "is_regular_appropriation": insert_stmt.excluded.is_regular_appropriation,
            "classification_confidence": insert_stmt.excluded.classification_confidence,
            "primary_rule_code": insert_stmt.excluded.primary_rule_code,
            "source_table": insert_stmt.excluded.source_table,
            "source_parent_record_id": insert_stmt.excluded.source_parent_record_id,
            "source_fiscal_year": insert_stmt.excluded.source_fiscal_year,
            "match_rule_code": insert_stmt.excluded.match_rule_code,
            "match_tier": insert_stmt.excluded.match_tier,
            "match_score": insert_stmt.excluded.match_score,
            "match_confidence": insert_stmt.excluded.match_confidence,
            "confidence_band": insert_stmt.excluded.confidence_band,
            "is_auto_accepted": insert_stmt.excluded.is_auto_accepted,
            "is_excluded": insert_stmt.excluded.is_excluded,
            "exclusion_reason": insert_stmt.excluded.exclusion_reason,
            "match_explanation": insert_stmt.excluded.match_explanation,
            "matched_on_fields": insert_stmt.excluded.matched_on_fields,
            "budget_side_values": insert_stmt.excluded.budget_side_values,
            "spending_side_values": insert_stmt.excluded.spending_side_values,
            "review_status": insert_stmt.excluded.review_status,
            "review_notes": insert_stmt.excluded.review_notes,
            "allocation_pct": insert_stmt.excluded.allocation_pct,
            "allocation_method": insert_stmt.excluded.allocation_method,
            "allocation_notes": insert_stmt.excluded.allocation_notes,
            "updated_at": text("now()"),
        }
        connection.execute(
            insert_stmt.on_conflict_do_update(
                index_elements=[
                    BRIDGE_TABLE.c.bridge_version,
                    BRIDGE_TABLE.c.budget_anchor_id,
                    BRIDGE_TABLE.c.system_name,
                    BRIDGE_TABLE.c.source_record_id,
                    BRIDGE_TABLE.c.match_type,
                ],
                set_=update_columns,
            )
        )
        written += len(batch)
    return written


def filter_candidates_for_system(
    candidates: Sequence[Mapping[str, Any]],
    system_name: str,
) -> list[dict[str, Any]]:
    if system_name == "all":
        return [dict(candidate) for candidate in candidates]
    return [dict(candidate) for candidate in candidates if candidate.get("system_name") == system_name]


def print_summary(
    *,
    anchors: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
    bridge_version: str,
    truncated_rows: int,
    written_rows: int,
    dry_run: bool,
) -> None:
    print(f"bridge_version={bridge_version}")
    print(f"anchor_count={len(anchors)}")
    print(f"candidate_count={len(candidates)}")
    print(f"rows_deleted={truncated_rows}")
    print(f"rows_written={written_rows}")
    print(f"dry_run={dry_run}")

    by_system = Counter(str(candidate["system_name"]) for candidate in candidates)
    if by_system:
        print("counts_by_system:")
        for system_name, count in sorted(by_system.items()):
            print(f"  {system_name}={count}")

    by_tier_system = Counter((str(candidate["match_tier"]), str(candidate["system_name"])) for candidate in candidates)
    if by_tier_system:
        print("counts_by_tier_and_system:")
        for (tier, system_name), count in sorted(by_tier_system.items()):
            print(f"  {tier} | {system_name}={count}")

    by_band_system = Counter((str(candidate["confidence_band"]), str(candidate["system_name"])) for candidate in candidates)
    if by_band_system:
        print("counts_by_confidence_band_and_system:")
        for (band, system_name), count in sorted(by_band_system.items()):
            print(f"  {band} | {system_name}={count}")

    by_category_system = Counter(
        (str(candidate["appropriation_category"]), str(candidate["system_name"])) for candidate in candidates
    )
    if by_category_system:
        print("counts_by_category_and_system:")
        for (category, system_name), count in sorted(by_category_system.items()):
            print(f"  {category} | {system_name}={count}")

    anchors_with_candidates = defaultdict(set)
    for candidate in candidates:
        anchors_with_candidates[str(candidate["system_name"])].add(str(candidate["budget_anchor_id"]))
    print("anchor_coverage_by_system:")
    for system_name in ("usaspending", "taggs"):
        covered = len(anchors_with_candidates.get(system_name, set()))
        print(f"  {system_name}={covered}")


def main() -> None:
    args = parse_args()
    engine = create_engine(args.db_url, future=True)
    with engine.begin() as connection:
        anchors = load_budget_anchors(connection, args)
        if not anchors:
            seed_rule_registry(connection, bridge_version=args.bridge_version, dry_run=args.dry_run)
            print("bridge_version=" + args.bridge_version)
            print("anchor_count=0")
            print("candidate_count=0")
            print("rows_deleted=0")
            print("rows_written=0")
            print(f"dry_run={args.dry_run}")
            return

        fiscal_years = sorted({int(anchor["fiscal_year"]) for anchor in anchors if anchor.get("fiscal_year") is not None})
        usaspending_rows = []
        taggs_rows = []
        if args.system_name in {"all", "usaspending"}:
            usaspending_rows = load_usaspending_awards(connection, fiscal_years)
        if args.system_name in {"all", "taggs"}:
            taggs_rows = load_taggs_awards(connection, fiscal_years)

        seed_rule_registry(connection, bridge_version=args.bridge_version, dry_run=args.dry_run)
        all_candidates = build_bridge_rows(
            anchors=anchors,
            usaspending_rows=usaspending_rows,
            taggs_rows=taggs_rows,
            bridge_version=args.bridge_version,
            review_status=args.review_status_default,
        )
        candidates = filter_candidates_for_system(all_candidates, args.system_name)

        truncated_rows = 0
        if args.truncate:
            truncated_rows = truncate_bridge_scope(
                connection,
                bridge_version=args.bridge_version,
                anchor_ids=[str(anchor["budget_anchor_id"]) for anchor in anchors],
                system_name=args.system_name,
                dry_run=args.dry_run,
            )

        written_rows = upsert_bridge_rows(
            connection,
            rows=candidates,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )
        print_summary(
            anchors=anchors,
            candidates=candidates,
            bridge_version=args.bridge_version,
            truncated_rows=truncated_rows,
            written_rows=written_rows,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
