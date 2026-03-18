from __future__ import annotations

import re
from typing import Any

from app.recon.funding_scope import (
    FUNDING_SCOPE_BIOMEDICAL_RESEARCH,
    FUNDING_SCOPE_CORE_PUBLIC_HEALTH,
    FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH,
    FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER,
    FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE,
    FUNDING_SCOPE_OTHER_PUBLIC_HEALTH,
    FUNDING_SCOPE_PROCUREMENT_SUPPORT,
    FUNDING_SCOPE_SPECIAL_TRANSFER,
    FUNDING_SCOPE_UNKNOWN,
    normalize_funding_scope,
)

ACCOUNT_STRUCTURE_SINGLE = "single_account"
ACCOUNT_STRUCTURE_MULTI_SAME_SCOPE = "multi_account_same_scope"
ACCOUNT_STRUCTURE_MULTI_MIXED_SCOPE = "multi_account_mixed_scope"

INTERPRETATION_SINGLE = "single_account"
INTERPRETATION_UNKNOWN_MIXED = "unknown_mixed"
INTERPRETATION_RESEARCH_MIXED = "research_mixed"
INTERPRETATION_INTERNATIONAL_MIXED = "international_mixed"
INTERPRETATION_SPECIAL_TRANSFER_MIXED = "special_transfer_mixed"
INTERPRETATION_MIXED_CORE_EMERGENCY = "mixed_core_emergency"
INTERPRETATION_MIXED_PROGRAM_SUPPORT = "mixed_program_support"
INTERPRETATION_MIXED_PROGRAM_TRANSFER = "mixed_program_transfer"
INTERPRETATION_MIXED_EMERGENCY_SUPPORT = "mixed_emergency_support"
INTERPRETATION_MIXED_EXCLUDED_SCOPES = "mixed_excluded_scopes"
INTERPRETATION_MIXED_SCOPE_CONSERVATIVE = "mixed_scope_conservative"

NULL_TOKENS = {"", "na", "n/a", "none", "null", "nan"}
NON_WORD_RE = re.compile(r"[^A-Z0-9-]+")


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).replace("\ufeff", "").strip()
    token = re.sub(r"\s+", " ", token)
    if token.lower() in NULL_TOKENS:
        return None
    return token or None


def normalize_account_symbol(value: Any) -> str | None:
    token = _normalize_text(value)
    if token is None:
        return None
    normalized = NON_WORD_RE.sub("-", token.upper()).strip("-")
    return normalized or None


def canonical_account_combination_key(values: list[Any]) -> str | None:
    ordered = sorted(
        {
            symbol
            for symbol in (normalize_account_symbol(value) for value in values)
            if symbol is not None
        }
    )
    return "|".join(ordered) if ordered else None


def build_component_scope_payload(component_items: list[dict[str, Any]]) -> dict[str, Any]:
    deduped_by_symbol: dict[str, dict[str, Any]] = {}
    for item in component_items:
        symbol = normalize_account_symbol(item.get("federal_account_symbol"))
        if symbol is None or symbol in deduped_by_symbol:
            continue
        deduped_by_symbol[symbol] = {
            "federal_account_symbol": symbol,
            "account_title": _normalize_text(item.get("account_title")),
            "effective_funding_scope": normalize_funding_scope(item.get("effective_funding_scope"))
            or FUNDING_SCOPE_UNKNOWN,
            "funding_scope_method": _normalize_text(item.get("funding_scope_method")) or "unclassified",
            "effective_profile_relevant": item.get("effective_profile_relevant"),
        }

    components = [deduped_by_symbol[symbol] for symbol in sorted(deduped_by_symbol)]
    component_symbols = [item["federal_account_symbol"] for item in components]
    component_titles = [item["account_title"] for item in components if item.get("account_title")]
    component_scopes = [item["effective_funding_scope"] for item in components]
    distinct_scopes = set(component_scopes)

    contains_core = FUNDING_SCOPE_CORE_PUBLIC_HEALTH in distinct_scopes
    contains_emergency = FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH in distinct_scopes
    contains_transfer = FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER in distinct_scopes
    contains_procurement = FUNDING_SCOPE_PROCUREMENT_SUPPORT in distinct_scopes
    contains_research = FUNDING_SCOPE_BIOMEDICAL_RESEARCH in distinct_scopes
    contains_international = FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE in distinct_scopes
    contains_special_transfer = FUNDING_SCOPE_SPECIAL_TRANSFER in distinct_scopes
    contains_unknown = FUNDING_SCOPE_UNKNOWN in distinct_scopes
    excluded_only_scopes = {
        FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER,
        FUNDING_SCOPE_OTHER_PUBLIC_HEALTH,
        FUNDING_SCOPE_BIOMEDICAL_RESEARCH,
        FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE,
    }

    if len(components) <= 1:
        account_structure_type = ACCOUNT_STRUCTURE_SINGLE
    elif contains_unknown or len(distinct_scopes) > 1:
        account_structure_type = ACCOUNT_STRUCTURE_MULTI_MIXED_SCOPE
    else:
        account_structure_type = ACCOUNT_STRUCTURE_MULTI_SAME_SCOPE

    manual_review_recommended = False
    conservative_inclusion_reason: str | None = None

    if account_structure_type == ACCOUNT_STRUCTURE_SINGLE:
        multi_account_interpretation = INTERPRETATION_SINGLE
    elif account_structure_type == ACCOUNT_STRUCTURE_MULTI_SAME_SCOPE:
        single_scope = component_scopes[0] if component_scopes else FUNDING_SCOPE_UNKNOWN
        multi_account_interpretation = f"same_scope_{single_scope}"
    elif contains_unknown:
        multi_account_interpretation = INTERPRETATION_UNKNOWN_MIXED
        conservative_inclusion_reason = (
            "The row links multiple federal accounts and at least one component scope is still unknown, so the "
            "derived normalization stays conservative and is flagged for manual review."
        )
        manual_review_recommended = True
    elif contains_international:
        multi_account_interpretation = INTERPRETATION_INTERNATIONAL_MIXED
        conservative_inclusion_reason = (
            "The row mixes international assistance with other funding scopes and the source does not provide an "
            "exact per-account split."
        )
    elif contains_research:
        multi_account_interpretation = INTERPRETATION_RESEARCH_MIXED
        conservative_inclusion_reason = (
            "The row mixes biomedical research funding with other scopes and the source does not provide an exact "
            "per-account split."
        )
    elif contains_special_transfer:
        multi_account_interpretation = INTERPRETATION_SPECIAL_TRANSFER_MIXED
        conservative_inclusion_reason = (
            "The row mixes special-transfer funding with other scopes and stays conservative without an exact split."
        )
    elif contains_core and contains_transfer:
        multi_account_interpretation = INTERPRETATION_MIXED_PROGRAM_TRANSFER
        conservative_inclusion_reason = (
            "The row mixes core public health and federal health transfer accounts without an exact source split, so "
            "the full dollars are not credited as core public health."
        )
    elif contains_core and contains_procurement:
        multi_account_interpretation = INTERPRETATION_MIXED_PROGRAM_SUPPORT
        conservative_inclusion_reason = (
            "The row mixes core public health and procurement-support accounts without an exact source split, so the "
            "full dollars are not credited as core public health."
        )
    elif contains_core and contains_emergency:
        multi_account_interpretation = INTERPRETATION_MIXED_CORE_EMERGENCY
        conservative_inclusion_reason = (
            "The row mixes core public health and emergency public health funding without an exact source split, so "
            "it stays conditional instead of being treated as pure core funding."
        )
    elif contains_emergency and contains_procurement:
        multi_account_interpretation = INTERPRETATION_MIXED_EMERGENCY_SUPPORT
        conservative_inclusion_reason = (
            "The row mixes emergency and procurement-support scopes without an exact source split, so it stays "
            "conditional instead of being treated as pure emergency or pure support spending."
        )
    elif distinct_scopes and distinct_scopes <= excluded_only_scopes:
        multi_account_interpretation = INTERPRETATION_MIXED_EXCLUDED_SCOPES
        conservative_inclusion_reason = (
            "The row mixes only non-core excluded scopes, so it remains excluded from the core CDC public health model."
        )
    else:
        multi_account_interpretation = INTERPRETATION_MIXED_SCOPE_CONSERVATIVE
        conservative_inclusion_reason = (
            "The row mixes multiple funding scopes without an exact source split, so it stays conservative in the "
            "derived normalization layer."
        )

    if account_structure_type == ACCOUNT_STRUCTURE_MULTI_MIXED_SCOPE and conservative_inclusion_reason and not manual_review_recommended:
        manual_review_recommended = contains_unknown

    scope_methods = sorted(
        {
            _normalize_text(item.get("funding_scope_method")) or "unclassified"
            for item in components
        }
    )
    funding_scope_method = scope_methods[0] if len(scope_methods) == 1 else "mixed"

    return {
        "federal_account_count": len(components),
        "federal_account_combination_key": "|".join(component_symbols) if component_symbols else None,
        "federal_account_titles_combined": " | ".join(component_titles) if component_titles else None,
        "component_account_scopes": components,
        "component_scope_count": len(distinct_scopes),
        "has_mixed_scopes": account_structure_type == ACCOUNT_STRUCTURE_MULTI_MIXED_SCOPE,
        "account_structure_type": account_structure_type,
        "multi_account_interpretation": multi_account_interpretation,
        "conservative_inclusion_reason": conservative_inclusion_reason,
        "manual_review_recommended": manual_review_recommended,
        "funding_scope_method": funding_scope_method,
        "mixed_scope_contains_core": contains_core,
        "mixed_scope_contains_emergency": contains_emergency,
        "mixed_scope_contains_transfer": contains_transfer,
        "mixed_scope_contains_procurement": contains_procurement,
        "mixed_scope_contains_research": contains_research,
        "mixed_scope_contains_international": contains_international,
        "mixed_scope_contains_special_transfer": contains_special_transfer,
        "mixed_scope_contains_unknown": contains_unknown,
    }
