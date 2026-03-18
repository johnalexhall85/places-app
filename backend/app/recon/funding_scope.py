from __future__ import annotations

from typing import Any

FUNDING_SCOPE_CORE_PUBLIC_HEALTH = "core_public_health"
FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH = "emergency_public_health"
FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER = "federal_health_transfer"
FUNDING_SCOPE_PROCUREMENT_SUPPORT = "procurement_support"
FUNDING_SCOPE_SPECIAL_TRANSFER = "special_transfer"
FUNDING_SCOPE_OTHER_PUBLIC_HEALTH = "other_public_health"
FUNDING_SCOPE_BIOMEDICAL_RESEARCH = "biomedical_research"
FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE = "international_health_assistance"
FUNDING_SCOPE_UNKNOWN = "unknown"

ALLOWED_FUNDING_SCOPES = (
    FUNDING_SCOPE_CORE_PUBLIC_HEALTH,
    FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH,
    FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER,
    FUNDING_SCOPE_PROCUREMENT_SUPPORT,
    FUNDING_SCOPE_SPECIAL_TRANSFER,
    FUNDING_SCOPE_OTHER_PUBLIC_HEALTH,
    FUNDING_SCOPE_BIOMEDICAL_RESEARCH,
    FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE,
    FUNDING_SCOPE_UNKNOWN,
)

LEGACY_SCOPE_CORE = "likely_core_cdc"
LEGACY_SCOPE_SPECIAL = "likely_special_transfer"
LEGACY_SCOPE_EMERGENCY = "likely_emergency_supplemental"
LEGACY_SCOPE_PROCUREMENT = "likely_procurement_only"
LEGACY_SCOPE_UNCERTAIN = "uncertain"
LEGACY_SCOPE_MIXED = "mixed_or_multi_account"

STREAM_REGULAR = "regular_appropriation"
STREAM_COVID = "covid_emergency"
STREAM_ARPA = "arpa"
STREAM_OTHER_EMERGENCY = "other_emergency_or_disaster"
STREAM_TRANSFER = "transfer_or_special"
STREAM_PROCUREMENT = "procurement_support"
STREAM_UNKNOWN = "unknown"

MEDICAID_TRANSFER_HINTS = (
    "grants to states for medicaid",
    "medicaid",
    "centers for medicare and medicaid services",
    "cms",
)


def _clean_token(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_funding_scope(value: Any) -> str | None:
    token = _clean_token(value)
    if token in ALLOWED_FUNDING_SCOPES:
        return token
    return None


def descriptor_implies_federal_health_transfer(value: Any) -> bool:
    token = _clean_token(value)
    if not token:
        return False
    return any(hint in token for hint in MEDICAID_TRANSFER_HINTS)


def funding_scope_from_stream(
    funding_stream: Any,
    *,
    descriptor_blob: Any = None,
    likely_vfc_related: bool = False,
) -> str:
    stream_token = _clean_token(funding_stream)
    if likely_vfc_related or stream_token == STREAM_PROCUREMENT:
        return FUNDING_SCOPE_PROCUREMENT_SUPPORT
    if stream_token == STREAM_REGULAR:
        return FUNDING_SCOPE_CORE_PUBLIC_HEALTH
    if stream_token in {STREAM_COVID, STREAM_ARPA, STREAM_OTHER_EMERGENCY}:
        return FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH
    if stream_token == STREAM_TRANSFER:
        if descriptor_implies_federal_health_transfer(descriptor_blob):
            return FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER
        return FUNDING_SCOPE_SPECIAL_TRANSFER
    return FUNDING_SCOPE_UNKNOWN


def funding_stream_from_scope(
    funding_scope: Any,
    *,
    emergency_stream: Any = None,
) -> str:
    scope_token = normalize_funding_scope(funding_scope) or FUNDING_SCOPE_UNKNOWN
    if scope_token == FUNDING_SCOPE_CORE_PUBLIC_HEALTH:
        return STREAM_REGULAR
    if scope_token == FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH:
        emergency_token = _clean_token(emergency_stream)
        if emergency_token in {STREAM_COVID, STREAM_ARPA, STREAM_OTHER_EMERGENCY}:
            return emergency_token
        return STREAM_OTHER_EMERGENCY
    if scope_token in {FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER, FUNDING_SCOPE_SPECIAL_TRANSFER}:
        return STREAM_TRANSFER
    if scope_token in {FUNDING_SCOPE_OTHER_PUBLIC_HEALTH, FUNDING_SCOPE_BIOMEDICAL_RESEARCH}:
        return STREAM_REGULAR
    if scope_token == FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE:
        return STREAM_TRANSFER
    if scope_token == FUNDING_SCOPE_PROCUREMENT_SUPPORT:
        return STREAM_PROCUREMENT
    return STREAM_UNKNOWN


def funding_scope_to_legacy_scope_guess(
    funding_scope: Any,
    *,
    mixed: bool = False,
) -> str:
    if mixed:
        return LEGACY_SCOPE_MIXED
    scope_token = normalize_funding_scope(funding_scope) or FUNDING_SCOPE_UNKNOWN
    if scope_token == FUNDING_SCOPE_CORE_PUBLIC_HEALTH:
        return LEGACY_SCOPE_CORE
    if scope_token == FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH:
        return LEGACY_SCOPE_EMERGENCY
    if scope_token in {FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER, FUNDING_SCOPE_SPECIAL_TRANSFER}:
        return LEGACY_SCOPE_SPECIAL
    if scope_token == FUNDING_SCOPE_PROCUREMENT_SUPPORT:
        return LEGACY_SCOPE_PROCUREMENT
    if scope_token in {
        FUNDING_SCOPE_OTHER_PUBLIC_HEALTH,
        FUNDING_SCOPE_BIOMEDICAL_RESEARCH,
        FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE,
    }:
        return LEGACY_SCOPE_UNCERTAIN
    return LEGACY_SCOPE_UNCERTAIN


def funding_scope_indicator_flags(funding_scope: Any) -> dict[str, bool]:
    scope_token = normalize_funding_scope(funding_scope) or FUNDING_SCOPE_UNKNOWN
    return {
        "likely_core_public_health": scope_token == FUNDING_SCOPE_CORE_PUBLIC_HEALTH,
        "likely_emergency_public_health": scope_token == FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH,
        "likely_federal_health_transfer": scope_token == FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER,
        "likely_procurement_support": scope_token == FUNDING_SCOPE_PROCUREMENT_SUPPORT,
        "likely_other_public_health": scope_token == FUNDING_SCOPE_OTHER_PUBLIC_HEALTH,
        "likely_biomedical_research": scope_token == FUNDING_SCOPE_BIOMEDICAL_RESEARCH,
        "likely_international_health_assistance": (
            scope_token == FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE
        ),
    }
