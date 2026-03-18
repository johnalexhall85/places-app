from __future__ import annotations

import csv
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.cdc_funding.appropriation import extract_defc_codes

METHODOLOGY_VERSION = "cdc_profile_alignment_v2026_03_13"
FUNDING_STREAM_LOGIC_VERSION = "funding_stream_logic_v2026_03_13"
TRAINING_FISCAL_YEARS = (2020, 2021, 2022, 2023)
ESTIMATED_FISCAL_YEARS = (2024, 2025, 2026)

FUNDING_STREAM_REGULAR = "regular_appropriation"
FUNDING_STREAM_COVID = "covid_emergency"
FUNDING_STREAM_ARPA = "arpa"
FUNDING_STREAM_OTHER_EMERGENCY = "other_emergency_or_disaster"
FUNDING_STREAM_NON_COVID_SUPPLEMENTAL = "non_covid_supplemental"
FUNDING_STREAM_TRANSFER_SPECIAL = "transfer_or_special"
FUNDING_STREAM_UNKNOWN = "unknown"

FUNDING_STREAMS = (
    FUNDING_STREAM_REGULAR,
    FUNDING_STREAM_COVID,
    FUNDING_STREAM_ARPA,
    FUNDING_STREAM_OTHER_EMERGENCY,
    FUNDING_STREAM_NON_COVID_SUPPLEMENTAL,
    FUNDING_STREAM_TRANSFER_SPECIAL,
    FUNDING_STREAM_UNKNOWN,
)

SOURCE_TAGGS = "taggs"
SOURCE_USASPENDING = "usaspending"

REPO_ROOT = Path(__file__).resolve().parents[3]
RULES_DIR = REPO_ROOT / "data" / "recon"

_WORD_RE = re.compile(r"\s+")


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    token = _WORD_RE.sub(" ", str(value).strip())
    return token or None


def _normalize_lower(value: Any) -> str:
    token = _normalize_text(value)
    return token.lower() if token else ""


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _to_bool(value: Any) -> bool:
    token = _normalize_lower(value)
    return token in {"1", "true", "t", "yes", "y"}


def _read_csv(name: str) -> list[dict[str, str]]:
    path = RULES_DIR / name
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            {str(key): str(value or "") for key, value in row.items() if key is not None}
            for row in reader
        ]


def load_rule_payloads() -> dict[str, Any]:
    defc_rules = []
    defc_lookup: dict[str, dict[str, Any]] = {}
    for row in _read_csv("defc_classification_rules.csv"):
        payload = {
            "defc_code": _normalize_text(row.get("defc_code")),
            "funding_stream": _normalize_text(row.get("funding_stream")) or FUNDING_STREAM_UNKNOWN,
            "appropriation_type_normalized": _normalize_text(row.get("appropriation_type_normalized")),
            "is_covid_related": _to_bool(row.get("is_covid_related")),
            "is_arpa_related": _to_bool(row.get("is_arpa_related")),
            "include_in_cdc_profile_scope_default": _to_bool(row.get("include_in_cdc_profile_scope_default")),
            "default_inclusion_weight": _to_decimal(row.get("default_inclusion_weight") or "0"),
            "notes": _normalize_text(row.get("notes")),
        }
        defc_rules.append(payload)
        if payload["defc_code"]:
            defc_lookup[str(payload["defc_code"]).upper()] = payload

    appropriation_type_rules = []
    appropriation_lookup: dict[str, dict[str, Any]] = {}
    for row in _read_csv("appropriation_type_rules.csv"):
        payload = {
            "appropriation_type_raw": _normalize_lower(row.get("appropriation_type_raw")),
            "appropriation_type_normalized": _normalize_text(row.get("appropriation_type_normalized")) or "unknown",
            "default_funding_stream": _normalize_text(row.get("default_funding_stream")) or FUNDING_STREAM_UNKNOWN,
            "default_include_in_cdc_profile_scope": _to_bool(row.get("default_include_in_cdc_profile_scope")),
            "default_inclusion_weight": _to_decimal(row.get("default_inclusion_weight") or "0"),
            "notes": _normalize_text(row.get("notes")),
        }
        appropriation_type_rules.append(payload)
        if payload["appropriation_type_raw"]:
            appropriation_lookup[str(payload["appropriation_type_raw"])] = payload

    federal_account_rules = []
    for row in _read_csv("federal_account_inclusion_rules.csv"):
        federal_account_rules.append(
            {
                "federal_account_symbol": _normalize_text(row.get("federal_account_symbol")),
                "treasury_account_symbol": _normalize_text(row.get("treasury_account_symbol")),
                "program_activity_name": _normalize_lower(row.get("program_activity_name")),
                "can_like_program_hint": _normalize_text(row.get("can_like_program_hint")),
                "default_funding_stream": _normalize_text(row.get("default_funding_stream")),
                "include_in_cdc_profile_scope_default": _to_bool(row.get("include_in_cdc_profile_scope_default")),
                "default_inclusion_weight": _to_decimal(row.get("default_inclusion_weight") or "0"),
                "notes": _normalize_text(row.get("notes")),
            }
        )

    scope_rules = []
    for row in _read_csv("cdc_profile_scope_rules.csv"):
        scope_rules.append(
            {
                "source_system": _normalize_lower(row.get("source_system")),
                "funding_stream": _normalize_text(row.get("funding_stream")),
                "can_code": _normalize_text(row.get("can_code")),
                "federal_account_symbol": _normalize_text(row.get("federal_account_symbol")),
                "treasury_account_symbol": _normalize_text(row.get("treasury_account_symbol")),
                "program_activity_name": _normalize_lower(row.get("program_activity_name")),
                "include_in_profile_scope": _to_bool(row.get("include_in_profile_scope")),
                "inclusion_weight": _to_decimal(row.get("inclusion_weight") or "0"),
                "rationale": _normalize_text(row.get("rationale")) or "Scope rule",
                "methodology_version": _normalize_text(row.get("methodology_version")) or METHODOLOGY_VERSION,
            }
        )

    return {
        "defc_rules": defc_rules,
        "defc_lookup": defc_lookup,
        "appropriation_type_rules": appropriation_type_rules,
        "appropriation_lookup": appropriation_lookup,
        "federal_account_rules": federal_account_rules,
        "scope_rules": scope_rules,
    }


def build_descriptor_blob(*parts: Any) -> str:
    return " ".join(
        token
        for token in (_normalize_lower(part) for part in parts)
        if token
    )


def _match_federal_account_rule(
    *,
    federal_account_symbol: str | None,
    treasury_account_symbol: str | None,
    descriptor_blob: str,
    account_rules: list[dict[str, Any]],
) -> dict[str, Any] | None:
    normalized_federal = _normalize_lower(federal_account_symbol)
    normalized_treasury = _normalize_lower(treasury_account_symbol)
    best_match: dict[str, Any] | None = None
    best_score = -1
    for rule in account_rules:
        score = 0
        rule_federal = _normalize_lower(rule.get("federal_account_symbol"))
        if rule_federal:
            if rule_federal != normalized_federal:
                continue
            score += 40
        rule_treasury = _normalize_lower(rule.get("treasury_account_symbol"))
        if rule_treasury:
            if rule_treasury != normalized_treasury:
                continue
            score += 30
        rule_program = _normalize_lower(rule.get("program_activity_name"))
        if rule_program:
            if rule_program not in descriptor_blob:
                continue
            score += 20
        if score > best_score:
            best_match = rule
            best_score = score
    return best_match


def _match_scope_rule(
    *,
    source_system: str,
    funding_stream: str,
    can_code: str | None,
    federal_account_symbol: str | None,
    treasury_account_symbol: str | None,
    descriptor_blob: str,
    scope_rules: list[dict[str, Any]],
) -> dict[str, Any] | None:
    normalized_source = _normalize_lower(source_system)
    normalized_can = _normalize_lower(can_code)
    normalized_federal = _normalize_lower(federal_account_symbol)
    normalized_treasury = _normalize_lower(treasury_account_symbol)
    normalized_stream = _normalize_lower(funding_stream)
    best_match: dict[str, Any] | None = None
    best_score = -1
    for rule in scope_rules:
        if _normalize_lower(rule.get("source_system")) != normalized_source:
            continue
        score = 0
        rule_can = _normalize_lower(rule.get("can_code"))
        if rule_can:
            if rule_can != normalized_can:
                continue
            score += 80
        rule_federal = _normalize_lower(rule.get("federal_account_symbol"))
        if rule_federal:
            if rule_federal != normalized_federal:
                continue
            score += 40
        rule_treasury = _normalize_lower(rule.get("treasury_account_symbol"))
        if rule_treasury:
            if rule_treasury != normalized_treasury:
                continue
            score += 30
        rule_stream = _normalize_lower(rule.get("funding_stream"))
        if rule_stream:
            if rule_stream != normalized_stream:
                continue
            score += 20
        rule_program = _normalize_lower(rule.get("program_activity_name"))
        if rule_program:
            if rule_program not in descriptor_blob:
                continue
            # A direct program-name match should outrank a generic stream-wide default.
            score += 30
        if score > best_score:
            best_match = rule
            best_score = score
    return best_match


def _default_scope_from_stream(funding_stream: str) -> tuple[bool, Decimal, str]:
    if funding_stream == FUNDING_STREAM_REGULAR:
        return True, Decimal("1.00"), "Regular appropriations are included by default."
    return False, Decimal("0.00"), "Non-regular streams are excluded by default unless a specific scope rule includes them."


def classify_usaspending_record(
    record: dict[str, Any],
    *,
    rules: dict[str, Any],
) -> dict[str, Any]:
    raw_appropriation_type = _normalize_lower(record.get("appropriation_type_raw") or record.get("appropriation_type"))
    appropriation_rule = rules["appropriation_lookup"].get(raw_appropriation_type)
    normalized_appropriation_type = (
        appropriation_rule.get("appropriation_type_normalized")
        if appropriation_rule
        else raw_appropriation_type or "unknown"
    )
    descriptor_blob = build_descriptor_blob(
        record.get("program_activity_name"),
        record.get("transaction_description"),
        record.get("prime_award_base_transaction_description"),
        record.get("cfda_title"),
        record.get("cfda_program_title"),
        record.get("cfda_numbers_and_titles"),
        record.get("appropriation_account"),
        record.get("federal_account_symbol"),
    )
    account_rule = _match_federal_account_rule(
        federal_account_symbol=record.get("federal_account_symbol"),
        treasury_account_symbol=record.get("treasury_account_symbol"),
        descriptor_blob=descriptor_blob,
        account_rules=rules["federal_account_rules"],
    )

    matched_defc_rules = [
        rules["defc_lookup"][code]
        for code in extract_defc_codes(record.get("raw_emergency_code"))
        if code in rules["defc_lookup"]
    ]
    defc_code_normalized = ",".join(
        code
        for code in extract_defc_codes(record.get("raw_emergency_code"))
    ) or None

    funding_stream = FUNDING_STREAM_UNKNOWN
    if str(record.get("appropriation_subtype_raw") or "").strip().upper() == "ARP":
        funding_stream = FUNDING_STREAM_ARPA
    elif any(rule.get("is_arpa_related") for rule in matched_defc_rules):
        funding_stream = FUNDING_STREAM_ARPA
    elif any(rule.get("funding_stream") == FUNDING_STREAM_COVID for rule in matched_defc_rules):
        funding_stream = FUNDING_STREAM_COVID
    elif any(rule.get("funding_stream") == FUNDING_STREAM_OTHER_EMERGENCY for rule in matched_defc_rules):
        funding_stream = FUNDING_STREAM_OTHER_EMERGENCY
    elif "american rescue plan" in descriptor_blob or re.search(r"\barpa\b", descriptor_blob):
        funding_stream = FUNDING_STREAM_ARPA
    elif any(term in descriptor_blob for term in ("covid", "coronavirus", "cares act", "crrsa")):
        funding_stream = FUNDING_STREAM_COVID
    elif "supplemental" in descriptor_blob:
        funding_stream = FUNDING_STREAM_NON_COVID_SUPPLEMENTAL
    elif "transfer" in descriptor_blob:
        funding_stream = FUNDING_STREAM_TRANSFER_SPECIAL
    elif "disaster" in descriptor_blob or "emergency" in descriptor_blob:
        funding_stream = FUNDING_STREAM_OTHER_EMERGENCY
    elif appropriation_rule:
        funding_stream = appropriation_rule.get("default_funding_stream") or FUNDING_STREAM_UNKNOWN
    elif not raw_appropriation_type:
        funding_stream = FUNDING_STREAM_REGULAR

    if account_rule and account_rule.get("default_funding_stream") and funding_stream in {
        FUNDING_STREAM_REGULAR,
        FUNDING_STREAM_UNKNOWN,
    }:
        funding_stream = account_rule["default_funding_stream"]

    scope_rule = _match_scope_rule(
        source_system=SOURCE_USASPENDING,
        funding_stream=funding_stream,
        can_code=None,
        federal_account_symbol=record.get("federal_account_symbol"),
        treasury_account_symbol=record.get("treasury_account_symbol"),
        descriptor_blob=descriptor_blob,
        scope_rules=rules["scope_rules"],
    )
    if scope_rule:
        include_in_scope = bool(scope_rule.get("include_in_profile_scope"))
        inclusion_weight = _to_decimal(scope_rule.get("inclusion_weight"))
        rationale = str(scope_rule.get("rationale") or "").strip()
    elif account_rule:
        include_in_scope = bool(account_rule.get("include_in_cdc_profile_scope_default"))
        inclusion_weight = _to_decimal(account_rule.get("default_inclusion_weight"))
        rationale = str(account_rule.get("notes") or "").strip()
    elif appropriation_rule:
        include_in_scope = bool(appropriation_rule.get("default_include_in_cdc_profile_scope"))
        inclusion_weight = _to_decimal(appropriation_rule.get("default_inclusion_weight"))
        rationale = str(appropriation_rule.get("notes") or "").strip()
    else:
        include_in_scope, inclusion_weight, rationale = _default_scope_from_stream(funding_stream)

    return {
        "funding_stream": funding_stream,
        "appropriation_type_normalized": normalized_appropriation_type,
        "defc_code_normalized": defc_code_normalized,
        "include_in_cdc_profile_scope": include_in_scope,
        "inclusion_weight": inclusion_weight,
        "inclusion_reason": rationale if include_in_scope else None,
        "exclusion_reason": None if include_in_scope else rationale,
    }


def classify_taggs_record(
    record: dict[str, Any],
    *,
    rules: dict[str, Any],
) -> dict[str, Any]:
    descriptor_blob = build_descriptor_blob(
        record.get("raw_funding_stream"),
        record.get("effective_program_name"),
        record.get("effective_category"),
        record.get("effective_subcategory"),
        record.get("award_title"),
        record.get("assistance_listing_title"),
    )
    raw_appropriation_type = _normalize_lower(record.get("appropriation_type"))
    if record.get("is_arpa_related") or "american rescue plan" in descriptor_blob or re.search(r"\barpa\b", descriptor_blob):
        funding_stream = FUNDING_STREAM_ARPA
    elif record.get("is_covid_related") or "covid" in descriptor_blob or "coronavirus" in descriptor_blob:
        funding_stream = FUNDING_STREAM_COVID
    elif record.get("is_supplemental") or "supplemental" in descriptor_blob:
        funding_stream = FUNDING_STREAM_NON_COVID_SUPPLEMENTAL
    elif any(term in descriptor_blob for term in ("vaccines for children", "drug free communities", "transfer")):
        funding_stream = FUNDING_STREAM_TRANSFER_SPECIAL
    elif raw_appropriation_type == "other_emergency" or "disaster" in descriptor_blob or "emergency" in descriptor_blob:
        funding_stream = FUNDING_STREAM_OTHER_EMERGENCY
    elif record.get("is_regular_appropriation") or raw_appropriation_type == "regular":
        funding_stream = FUNDING_STREAM_REGULAR
    else:
        funding_stream = FUNDING_STREAM_UNKNOWN

    if not bool(record.get("is_domestic_scope")):
        return {
            "funding_stream": funding_stream,
            "include_in_cdc_profile_scope": False,
            "inclusion_weight": Decimal("0.00"),
            "profile_scope_reason": "Excluded because the TAGGS row falls outside conservative domestic recipient scope.",
        }

    scope_rule = _match_scope_rule(
        source_system=SOURCE_TAGGS,
        funding_stream=funding_stream,
        can_code=record.get("can_code"),
        federal_account_symbol=None,
        treasury_account_symbol=None,
        descriptor_blob=descriptor_blob,
        scope_rules=rules["scope_rules"],
    )
    if scope_rule:
        include_in_scope = bool(scope_rule.get("include_in_profile_scope"))
        inclusion_weight = _to_decimal(scope_rule.get("inclusion_weight"))
        rationale = str(scope_rule.get("rationale") or "").strip()
    else:
        include_in_scope, inclusion_weight, rationale = _default_scope_from_stream(funding_stream)

    return {
        "funding_stream": funding_stream,
        "include_in_cdc_profile_scope": include_in_scope,
        "inclusion_weight": inclusion_weight,
        "profile_scope_reason": rationale,
    }


def build_major_difference_drivers(
    *,
    funding_stream_totals: dict[str, dict[str, Decimal]],
    cdc_profile_amount: Decimal,
    classified_profile_scope_amount: Decimal,
) -> list[dict[str, Any]]:
    drivers: list[dict[str, Any]] = []
    for funding_stream, totals in sorted(
        funding_stream_totals.items(),
        key=lambda item: abs(_to_decimal(item[1].get("raw_amount")) - _to_decimal(item[1].get("included_amount"))),
        reverse=True,
    ):
        raw_amount = _to_decimal(totals.get("raw_amount"))
        included_amount = _to_decimal(totals.get("included_amount"))
        excluded_amount = raw_amount - included_amount
        if raw_amount == 0 and included_amount == 0:
            continue
        drivers.append(
            {
                "funding_stream": funding_stream,
                "raw_amount": raw_amount,
                "included_amount": included_amount,
                "excluded_amount": excluded_amount,
            }
        )
    residual = cdc_profile_amount - classified_profile_scope_amount
    if residual != 0:
        drivers.append(
            {
                "funding_stream": "residual_difference",
                "raw_amount": Decimal("0"),
                "included_amount": classified_profile_scope_amount,
                "excluded_amount": residual,
            }
        )
    return drivers[:5]
