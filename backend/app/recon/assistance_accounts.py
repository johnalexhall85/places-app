from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.db_fqtn import cdc_funding_table, recon_table
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
    funding_scope_from_stream,
    normalize_funding_scope,
)
from app.recon.multi_account import (
    ACCOUNT_STRUCTURE_MULTI_MIXED_SCOPE,
    ACCOUNT_STRUCTURE_MULTI_SAME_SCOPE,
    build_component_scope_payload,
    canonical_account_combination_key,
)
from app.recon.models import AssistanceTransactionAccount, AssistanceTransactionAccountSummary

STREAM_REGULAR = "regular_appropriation"
STREAM_COVID = "covid_emergency"
STREAM_ARPA = "arpa"
STREAM_OTHER_EMERGENCY = "other_emergency_or_disaster"
STREAM_TRANSFER = "transfer_or_special"
STREAM_PROCUREMENT = "procurement_support"
STREAM_UNKNOWN = "unknown"

SCOPE_CORE = "likely_core_cdc"
SCOPE_SPECIAL = "likely_special_transfer"
SCOPE_EMERGENCY = "likely_emergency_supplemental"
SCOPE_PROCUREMENT = "likely_procurement_only"
SCOPE_UNCERTAIN = "uncertain"
SCOPE_MIXED = "mixed_or_multi_account"

METHOD_NO_ACCOUNTS = "no_linked_accounts"
METHOD_ALL_UNKNOWN = "all_linked_accounts_unknown"
METHOD_CORE_PUBLIC_HEALTH_PROFILE_RELEVANT = "core_public_health_profile_relevant"
METHOD_CORE_PUBLIC_HEALTH_PROBABLE = "core_public_health_probable"
METHOD_MIXED_PROBABLE = "mixed_accounts_core_public_health_support"
METHOD_MIXED_UNCERTAIN = "mixed_accounts_uncertain"
METHOD_EMERGENCY_PUBLIC_HEALTH_PROFILE_RELEVANT = "emergency_public_health_profile_relevant"
METHOD_EMERGENCY_PUBLIC_HEALTH_UNCERTAIN = "emergency_public_health_uncertain"
METHOD_FEDERAL_HEALTH_TRANSFER_EXCLUDED = "federal_health_transfer_excluded"
METHOD_OTHER_PUBLIC_HEALTH_EXCLUDED = "other_public_health_excluded"
METHOD_BIOMEDICAL_RESEARCH_EXCLUDED = "biomedical_research_excluded"
METHOD_INTERNATIONAL_HEALTH_ASSISTANCE_EXCLUDED = "international_health_assistance_excluded"
METHOD_MIXED_CORE_EMERGENCY_CONSERVATIVE = "mixed_core_emergency_conservative"
METHOD_MIXED_PROGRAM_SUPPORT_CONSERVATIVE = "mixed_program_support_conservative"
METHOD_MIXED_PROGRAM_TRANSFER_CONSERVATIVE = "mixed_program_transfer_conservative"
METHOD_MIXED_EMERGENCY_SUPPORT_CONSERVATIVE = "mixed_emergency_support_conservative"
METHOD_MIXED_RESEARCH_CONSERVATIVE = "mixed_research_conservative"
METHOD_MIXED_INTERNATIONAL_CONSERVATIVE = "mixed_international_conservative"
METHOD_MIXED_SPECIAL_TRANSFER_CONSERVATIVE = "mixed_special_transfer_conservative"
METHOD_UNKNOWN_MIXED_REVIEW = "unknown_mixed_review"
METHOD_SPECIAL_PROFILE_RELEVANT = "special_transfer_profile_relevant"
METHOD_SPECIAL_UNCERTAIN = "special_transfer_uncertain"
METHOD_PROCUREMENT_SUPPORT_PROFILE_RELEVANT = "procurement_support_profile_relevant"
METHOD_PROCUREMENT_SUPPORT_UNCERTAIN = "procurement_support_uncertain"
METHOD_EXPLICIT_EXCLUSION = "explicit_account_exclusion"
METHOD_UNKNOWN_UNCERTAIN = "unknown_uncertain"

METHOD_REGULAR_PROFILE_RELEVANT = METHOD_CORE_PUBLIC_HEALTH_PROFILE_RELEVANT
METHOD_REGULAR_PROBABLE = METHOD_CORE_PUBLIC_HEALTH_PROBABLE
METHOD_EMERGENCY_PROFILE_RELEVANT = METHOD_EMERGENCY_PUBLIC_HEALTH_PROFILE_RELEVANT
METHOD_EMERGENCY_UNCERTAIN = METHOD_EMERGENCY_PUBLIC_HEALTH_UNCERTAIN

NULL_TOKENS = {"", "na", "n/a", "none", "null", "nan"}
WHITESPACE_RE = re.compile(r"\s+")
ACCOUNT_SYMBOL_RE = re.compile(r"[-\s]+")

ASSISTANCE_SOURCE_FQTN = cdc_funding_table("prime_transactions")
ASSISTANCE_AWARDS_FQTN = cdc_funding_table("prime_awards")
LOOKUP_FQTN = recon_table("federal_account_lookup")
ACCOUNTS_FQTN = recon_table("assistance_transaction_accounts")
ACCOUNT_SUMMARY_FQTN = recon_table("assistance_transaction_account_summary")

ACCOUNT_TABLE = AssistanceTransactionAccount.__table__
ACCOUNT_SUMMARY_TABLE = AssistanceTransactionAccountSummary.__table__


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    token = WHITESPACE_RE.sub(" ", str(value).replace("\ufeff", "").strip())
    if token.lower() in NULL_TOKENS:
        return None
    return token or None


def _normalize_lower(value: Any) -> str:
    token = _normalize_text(value)
    return token.lower() if token else ""


def _to_decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _quantize_money(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal("0.01"))


def normalize_federal_account_symbol(value: Any) -> str | None:
    token = _normalize_text(value)
    if token is None:
        return None
    normalized = ACCOUNT_SYMBOL_RE.sub("-", token.upper()).strip("-")
    normalized = normalized.replace(";", "")
    return normalized or None


def split_assistance_federal_account_symbols(value: Any) -> list[str]:
    token = _normalize_text(value)
    if token is None:
        return []
    symbols: list[str] = []
    for piece in token.split(";"):
        normalized = normalize_federal_account_symbol(piece)
        if normalized is None:
            continue
        symbols.append(normalized)
    return symbols


def fetch_assistance_source_rows(connection: Any) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            text(
                f"""
                SELECT
                    tx.id AS source_row_id,
                    COALESCE(tx.assistance_transaction_unique_key, CAST(tx.id AS text)) AS source_transaction_id,
                    COALESCE(tx.assistance_award_unique_key, tx.award_id_fain) AS award_key,
                    tx.action_date_fiscal_year AS fiscal_year,
                    tx.recipient_state_code AS state_code,
                    tx.recipient_name,
                    COALESCE(
                        NULLIF(BTRIM(tx.raw ->> 'recipient_country_name'), ''),
                        NULLIF(BTRIM(tx.raw ->> 'recipient_country'), ''),
                        NULLIF(BTRIM(p.raw ->> 'recipient_country_name'), ''),
                        NULLIF(BTRIM(p.raw ->> 'recipient_country'), ''),
                        CASE
                            WHEN tx.recipient_state_code IS NOT NULL THEN 'UNITED STATES'
                            ELSE NULL
                        END
                    ) AS recipient_country_name,
                    COALESCE(NULLIF(BTRIM(tx.awarding_sub_agency_name), ''), NULLIF(BTRIM(tx.awarding_office_name), ''))
                        AS awarding_agency_name,
                    COALESCE(NULLIF(BTRIM(tx.funding_sub_agency_name), ''), NULLIF(BTRIM(tx.funding_office_name), ''))
                        AS funding_agency_name,
                    COALESCE(NULLIF(BTRIM(tx.cfda_number), ''), NULLIF(BTRIM(p.cfda_program_num), ''))
                        AS assistance_listing_number,
                    COALESCE(NULLIF(BTRIM(tx.cfda_title), ''), NULLIF(BTRIM(p.cfda_program_title), ''))
                        AS assistance_listing_title,
                    COALESCE(
                        NULLIF(BTRIM(tx.raw ->> 'program_activity_name'), ''),
                        NULLIF(BTRIM(tx.raw ->> 'program_activity'), ''),
                        NULLIF(BTRIM(p.raw ->> 'program_activity_name'), ''),
                        NULLIF(BTRIM(p.raw ->> 'program_activity'), '')
                    ) AS program_activity_name,
                    COALESCE(
                        NULLIF(BTRIM(tx.raw ->> 'federal_account_symbol'), ''),
                        NULLIF(BTRIM(tx.raw ->> 'federal_account_identifier'), ''),
                        NULLIF(BTRIM(tx.raw ->> 'federal_accounts_funding_this_award'), ''),
                        NULLIF(BTRIM(p.raw ->> 'federal_account_symbol'), ''),
                        NULLIF(BTRIM(p.raw ->> 'federal_account_identifier'), ''),
                        NULLIF(BTRIM(p.raw ->> 'federal_accounts_funding_this_award'), '')
                    ) AS raw_federal_account_symbol,
                    COALESCE(
                        NULLIF(BTRIM(tx.raw ->> 'treasury_account_symbol'), ''),
                        NULLIF(BTRIM(tx.raw ->> 'treasury_account_identifier'), ''),
                        NULLIF(BTRIM(p.raw ->> 'treasury_account_symbol'), ''),
                        NULLIF(BTRIM(p.raw ->> 'treasury_account_identifier'), '')
                    ) AS raw_treasury_account_symbol,
                    tx.appropriation_type,
                    tx.appropriation_subtype,
                    tx.disaster_emergency_fund_codes_raw AS raw_emergency_code,
                    tx.transaction_description,
                    tx.prime_award_base_transaction_description,
                    COALESCE(tx.federal_action_obligation, 0)::numeric(18, 2) AS transaction_obligated_amount
                FROM {ASSISTANCE_SOURCE_FQTN} AS tx
                LEFT JOIN {ASSISTANCE_AWARDS_FQTN} AS p
                  ON p.unique_key = tx.assistance_award_unique_key
                ORDER BY tx.id
                """
            )
        ).mappings().all()
    ]


def build_assistance_transaction_account_rows(source_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_row in source_rows:
        source_transaction_id = _normalize_text(source_row.get("source_transaction_id"))
        if source_transaction_id is None:
            continue
        symbols = split_assistance_federal_account_symbols(source_row.get("raw_federal_account_symbol"))
        for account_position, federal_account_symbol in enumerate(symbols, start=1):
            rows.append(
                {
                    "source_transaction_id": source_transaction_id,
                    "federal_account_symbol": federal_account_symbol,
                    "account_position": account_position,
                    "source_row_id": source_row.get("source_row_id"),
                    "award_key": _normalize_text(source_row.get("award_key")),
                    "fiscal_year": source_row.get("fiscal_year"),
                    "state_code": _normalize_text(source_row.get("state_code")),
                    "transaction_obligated_amount": _quantize_money(
                        _to_decimal(source_row.get("transaction_obligated_amount"))
                    ),
                    "awarding_agency_name": _normalize_text(source_row.get("awarding_agency_name")),
                    "funding_agency_name": _normalize_text(source_row.get("funding_agency_name")),
                    "treasury_account_symbol": _normalize_text(source_row.get("raw_treasury_account_symbol")),
                    "appropriation_type": _normalize_text(source_row.get("appropriation_type")),
                    "appropriation_subtype": _normalize_text(source_row.get("appropriation_subtype")),
                    "raw_emergency_code": _normalize_text(source_row.get("raw_emergency_code")),
                    "psc_or_aln": _normalize_text(source_row.get("assistance_listing_number")),
                    "psc_or_aln_description": _normalize_text(source_row.get("assistance_listing_title")),
                    "award_description": None,
                    "transaction_description": _normalize_text(source_row.get("transaction_description")),
                    "prime_award_base_transaction_description": _normalize_text(
                        source_row.get("prime_award_base_transaction_description")
                    ),
                    "naics_description": None,
                    "program_activity_name": _normalize_text(source_row.get("program_activity_name")),
                    "raw_federal_account_symbol": _normalize_text(source_row.get("raw_federal_account_symbol")),
                    "created_at": datetime.now(timezone.utc),
                }
            )
    return rows


def _replace_table_rows(connection: Any, table: Any, rows: list[dict[str, Any]], *, chunk_size: int = 5000) -> None:
    connection.execute(table.delete())
    if not rows:
        return
    for start in range(0, len(rows), chunk_size):
        connection.execute(table.insert(), rows[start : start + chunk_size])


def _fetch_lookup_rows_by_symbol(connection: Any) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        text(
            f"""
            SELECT
                federal_account_symbol,
                account_title,
                effective_funding_stream,
                effective_funding_scope,
                funding_scope_method,
                effective_scope_guess,
                effective_profile_relevant
            FROM {LOOKUP_FQTN}
            """
        )
    ).mappings().all()
    return {str(row["federal_account_symbol"]): dict(row) for row in rows}


def _stream_bucket(stream: Any) -> str:
    token = _normalize_text(stream)
    if token == STREAM_REGULAR:
        return STREAM_REGULAR
    if token == STREAM_TRANSFER:
        return STREAM_TRANSFER
    if token == STREAM_PROCUREMENT:
        return STREAM_PROCUREMENT
    if token == STREAM_ARPA:
        return STREAM_ARPA
    if token in {STREAM_COVID, STREAM_OTHER_EMERGENCY}:
        return STREAM_OTHER_EMERGENCY
    return STREAM_UNKNOWN


def _join_distinct_symbols(account_rows: list[dict[str, Any]]) -> str | None:
    seen: set[str] = set()
    ordered: list[str] = []
    for row in sorted(account_rows, key=lambda item: int(item.get("account_position") or 0)):
        symbol = _normalize_text(row.get("federal_account_symbol"))
        if symbol is None or symbol in seen:
            continue
        seen.add(symbol)
        ordered.append(symbol)
    if not ordered:
        return None
    return "; ".join(ordered)


def _emergency_primary_stream(items: list[dict[str, Any]]) -> str:
    buckets = {_stream_bucket(item.get("effective_funding_stream")) for item in items}
    if buckets == {STREAM_ARPA}:
        return STREAM_ARPA
    if buckets == {STREAM_OTHER_EMERGENCY}:
        raw_streams = {
            _normalize_text(item.get("effective_funding_stream"))
            for item in items
            if _normalize_text(item.get("effective_funding_stream"))
        }
        if raw_streams == {STREAM_COVID}:
            return STREAM_COVID
        return STREAM_OTHER_EMERGENCY
    if STREAM_ARPA in buckets:
        return STREAM_ARPA
    return STREAM_OTHER_EMERGENCY


def _build_linked_account_items(
    account_rows: list[dict[str, Any]],
    lookup_by_symbol: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for account_row in sorted(account_rows, key=lambda row: int(row.get("account_position") or 0)):
        symbol = _normalize_text(account_row.get("federal_account_symbol"))
        if symbol is None or symbol in seen:
            continue
        seen.add(symbol)
        lookup_row = lookup_by_symbol.get(symbol, {})
        items.append(
            {
                "federal_account_symbol": symbol,
                "account_title": _normalize_text(lookup_row.get("account_title")),
                "effective_funding_stream": _normalize_text(lookup_row.get("effective_funding_stream")) or STREAM_UNKNOWN,
                "effective_funding_scope": normalize_funding_scope(lookup_row.get("effective_funding_scope"))
                or funding_scope_from_stream(lookup_row.get("effective_funding_stream")),
                "funding_scope_method": _normalize_text(lookup_row.get("funding_scope_method")) or "unclassified",
                "effective_scope_guess": _normalize_text(lookup_row.get("effective_scope_guess")) or SCOPE_UNCERTAIN,
                "effective_profile_relevant": lookup_row.get("effective_profile_relevant"),
            }
        )
    return items


def derive_assistance_transaction_account_summary(
    *,
    source_row: dict[str, Any],
    account_rows: list[dict[str, Any]],
    lookup_by_symbol: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    linked_items = _build_linked_account_items(account_rows, lookup_by_symbol)
    account_count = len(account_rows)
    distinct_account_count = len(linked_items)
    joined_account_symbols = _join_distinct_symbols(account_rows)
    component_scope_payload = build_component_scope_payload(linked_items)
    account_structure_type = component_scope_payload["account_structure_type"]
    multi_account_interpretation = component_scope_payload["multi_account_interpretation"]
    conservative_inclusion_reason = component_scope_payload["conservative_inclusion_reason"]
    manual_review_recommended = bool(component_scope_payload["manual_review_recommended"])

    has_core_public_health_account = any(
        item["effective_funding_scope"] == FUNDING_SCOPE_CORE_PUBLIC_HEALTH for item in linked_items
    )
    has_emergency_public_health_account = any(
        item["effective_funding_scope"] == FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH for item in linked_items
    )
    has_federal_health_transfer_account = any(
        item["effective_funding_scope"] == FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER for item in linked_items
    )
    has_special_transfer_account = any(
        item["effective_funding_scope"] == FUNDING_SCOPE_SPECIAL_TRANSFER for item in linked_items
    )
    has_procurement_support_account = any(
        item["effective_funding_scope"] == FUNDING_SCOPE_PROCUREMENT_SUPPORT for item in linked_items
    )
    has_other_public_health_account = any(
        item["effective_funding_scope"] == FUNDING_SCOPE_OTHER_PUBLIC_HEALTH for item in linked_items
    )
    has_biomedical_research_account = any(
        item["effective_funding_scope"] == FUNDING_SCOPE_BIOMEDICAL_RESEARCH for item in linked_items
    )
    has_international_health_assistance_account = any(
        item["effective_funding_scope"] == FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE for item in linked_items
    )
    has_regular_account = any(_stream_bucket(item["effective_funding_stream"]) == STREAM_REGULAR for item in linked_items)
    has_emergency_account = any(
        _stream_bucket(item["effective_funding_stream"]) == STREAM_OTHER_EMERGENCY for item in linked_items
    )
    has_arpa_account = any(_stream_bucket(item["effective_funding_stream"]) == STREAM_ARPA for item in linked_items)
    has_transfer_or_special_account = has_federal_health_transfer_account or has_special_transfer_account
    has_procurement_account = has_procurement_support_account
    has_profile_relevant_account = any(item.get("effective_profile_relevant") is True for item in linked_items)
    has_non_profile_relevant_account = any(item.get("effective_profile_relevant") is False for item in linked_items)
    has_unknown_account = bool(
        account_count == 0
        or any(
            item["effective_funding_scope"] == FUNDING_SCOPE_UNKNOWN
            or _stream_bucket(item["effective_funding_stream"]) == STREAM_UNKNOWN
            or item.get("effective_profile_relevant") is None
            for item in linked_items
        )
    )
    distinct_known_scopes = {
        item["effective_funding_scope"]
        for item in linked_items
        if item["effective_funding_scope"] != FUNDING_SCOPE_UNKNOWN
    }
    excluded_only_scopes = {
        FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER,
        FUNDING_SCOPE_OTHER_PUBLIC_HEALTH,
        FUNDING_SCOPE_BIOMEDICAL_RESEARCH,
        FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE,
    }
    has_mixed_accounts = account_structure_type == ACCOUNT_STRUCTURE_MULTI_MIXED_SCOPE
    has_multiple_accounts = distinct_account_count > 1
    all_accounts_unknown = distinct_account_count > 0 and not distinct_known_scopes

    effective_funding_stream = STREAM_UNKNOWN
    effective_funding_scope = FUNDING_SCOPE_UNKNOWN
    effective_scope_guess = SCOPE_UNCERTAIN
    effective_profile_relevant: bool | None = None
    effective_classification_method = METHOD_UNKNOWN_UNCERTAIN
    classification_notes = "The linked account set is too incomplete to classify with confidence."

    core_items = [
        item
        for item in linked_items
        if item["effective_funding_scope"] == FUNDING_SCOPE_CORE_PUBLIC_HEALTH
    ]
    emergency_items = [
        item
        for item in linked_items
        if item["effective_funding_scope"] == FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH
    ]
    federal_health_transfer_items = [
        item
        for item in linked_items
        if item["effective_funding_scope"] == FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER
    ]
    special_transfer_items = [
        item
        for item in linked_items
        if item["effective_funding_scope"] == FUNDING_SCOPE_SPECIAL_TRANSFER
    ]
    procurement_support_items = [
        item
        for item in linked_items
        if item["effective_funding_scope"] == FUNDING_SCOPE_PROCUREMENT_SUPPORT
    ]
    other_public_health_items = [
        item
        for item in linked_items
        if item["effective_funding_scope"] == FUNDING_SCOPE_OTHER_PUBLIC_HEALTH
    ]
    biomedical_research_items = [
        item
        for item in linked_items
        if item["effective_funding_scope"] == FUNDING_SCOPE_BIOMEDICAL_RESEARCH
    ]
    international_health_assistance_items = [
        item
        for item in linked_items
        if item["effective_funding_scope"] == FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE
    ]
    hard_exclusion_scopes_present = bool(
        distinct_known_scopes
        & {
            FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER,
            FUNDING_SCOPE_OTHER_PUBLIC_HEALTH,
            FUNDING_SCOPE_BIOMEDICAL_RESEARCH,
            FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE,
        }
    )

    if account_count == 0:
        effective_classification_method = METHOD_NO_ACCOUNTS
        classification_notes = "No federal account symbol was present on the assistance transaction."
    elif all_accounts_unknown:
        effective_classification_method = METHOD_ALL_UNKNOWN
        classification_notes = (
            "All linked federal account symbols are still unknown in the current lookup, so the transaction remains "
            "uncertain instead of being excluded."
        )
    elif has_mixed_accounts:
        effective_scope_guess = SCOPE_MIXED
        effective_profile_relevant = None
        classification_notes = (
            conservative_inclusion_reason
            or "The linked account set mixes multiple funding scopes without an exact account-level split."
        )
        if component_scope_payload["mixed_scope_contains_unknown"]:
            effective_funding_scope = FUNDING_SCOPE_UNKNOWN
            effective_funding_stream = STREAM_UNKNOWN
            effective_classification_method = METHOD_UNKNOWN_MIXED_REVIEW
        elif distinct_known_scopes and distinct_known_scopes <= excluded_only_scopes:
            effective_profile_relevant = False
            if FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE in distinct_known_scopes:
                effective_funding_scope = FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE
                effective_funding_stream = STREAM_TRANSFER
                effective_classification_method = METHOD_INTERNATIONAL_HEALTH_ASSISTANCE_EXCLUDED
            elif FUNDING_SCOPE_BIOMEDICAL_RESEARCH in distinct_known_scopes:
                effective_funding_scope = FUNDING_SCOPE_BIOMEDICAL_RESEARCH
                effective_funding_stream = STREAM_REGULAR
                effective_classification_method = METHOD_BIOMEDICAL_RESEARCH_EXCLUDED
            elif FUNDING_SCOPE_OTHER_PUBLIC_HEALTH in distinct_known_scopes:
                effective_funding_scope = FUNDING_SCOPE_OTHER_PUBLIC_HEALTH
                effective_funding_stream = STREAM_REGULAR
                effective_classification_method = METHOD_OTHER_PUBLIC_HEALTH_EXCLUDED
            else:
                effective_funding_scope = FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER
                effective_funding_stream = STREAM_TRANSFER
                effective_classification_method = METHOD_FEDERAL_HEALTH_TRANSFER_EXCLUDED
        elif component_scope_payload["mixed_scope_contains_core"] and component_scope_payload["mixed_scope_contains_transfer"]:
            effective_funding_scope = FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER
            effective_funding_stream = STREAM_TRANSFER
            effective_classification_method = METHOD_MIXED_PROGRAM_TRANSFER_CONSERVATIVE
        elif component_scope_payload["mixed_scope_contains_core"] and component_scope_payload["mixed_scope_contains_procurement"]:
            effective_funding_scope = FUNDING_SCOPE_PROCUREMENT_SUPPORT
            effective_funding_stream = STREAM_PROCUREMENT
            effective_classification_method = METHOD_MIXED_PROGRAM_SUPPORT_CONSERVATIVE
        elif component_scope_payload["mixed_scope_contains_core"] and component_scope_payload["mixed_scope_contains_emergency"]:
            effective_funding_scope = FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH
            effective_funding_stream = _emergency_primary_stream(linked_items)
            effective_classification_method = METHOD_MIXED_CORE_EMERGENCY_CONSERVATIVE
        elif component_scope_payload["mixed_scope_contains_emergency"] and component_scope_payload["mixed_scope_contains_procurement"]:
            effective_funding_scope = FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH
            effective_funding_stream = _emergency_primary_stream(linked_items)
            effective_classification_method = METHOD_MIXED_EMERGENCY_SUPPORT_CONSERVATIVE
        elif component_scope_payload["mixed_scope_contains_special_transfer"]:
            effective_funding_scope = FUNDING_SCOPE_SPECIAL_TRANSFER
            effective_funding_stream = STREAM_TRANSFER
            effective_classification_method = METHOD_MIXED_SPECIAL_TRANSFER_CONSERVATIVE
        elif component_scope_payload["mixed_scope_contains_research"]:
            effective_funding_scope = FUNDING_SCOPE_BIOMEDICAL_RESEARCH
            effective_funding_stream = STREAM_REGULAR
            effective_classification_method = METHOD_MIXED_RESEARCH_CONSERVATIVE
        elif component_scope_payload["mixed_scope_contains_international"]:
            effective_funding_scope = FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE
            effective_funding_stream = STREAM_TRANSFER
            effective_classification_method = METHOD_MIXED_INTERNATIONAL_CONSERVATIVE
        else:
            effective_classification_method = METHOD_MIXED_UNCERTAIN
    elif has_core_public_health_account:
        effective_funding_scope = (
            FUNDING_SCOPE_CORE_PUBLIC_HEALTH
            if not hard_exclusion_scopes_present
            else FUNDING_SCOPE_UNKNOWN
        )
        effective_funding_stream = STREAM_REGULAR if not hard_exclusion_scopes_present else STREAM_UNKNOWN
        effective_scope_guess = SCOPE_MIXED if has_mixed_accounts else SCOPE_CORE
        any_core_supported = any(item.get("effective_profile_relevant") is not False for item in core_items)
        all_core_explicitly_excluded = bool(core_items) and not any_core_supported
        if has_mixed_accounts:
            if hard_exclusion_scopes_present:
                effective_classification_method = METHOD_MIXED_UNCERTAIN
                classification_notes = (
                    "The linked account set mixes core public health funding with excluded non-core scopes, so the "
                    "transaction stays uncertain instead of defaulting into the CDC core model."
                )
            elif any_core_supported or has_profile_relevant_account:
                effective_profile_relevant = True if has_profile_relevant_account else None
                effective_classification_method = METHOD_MIXED_PROBABLE
                classification_notes = (
                    "The linked account set mixes core public health funding with other funding scopes. Because at "
                    "least one core account is not explicitly excluded, the transaction is treated as core public "
                    "health support for reconstruction."
                )
            else:
                effective_classification_method = METHOD_MIXED_UNCERTAIN
                classification_notes = (
                    "The linked account set mixes core public health funding with other funding scopes, but the core accounts are "
                    "explicitly excluded. The transaction stays uncertain instead of defaulting out of scope."
                )
        elif all_core_explicitly_excluded and not has_unknown_account:
            effective_profile_relevant = False
            effective_classification_method = METHOD_EXPLICIT_EXCLUSION
            classification_notes = (
                "All linked core public health accounts are explicitly classified as not profile relevant."
            )
        elif has_profile_relevant_account:
            effective_profile_relevant = True
            effective_classification_method = METHOD_CORE_PUBLIC_HEALTH_PROFILE_RELEVANT
            classification_notes = (
                "At least one linked core public health federal account is explicitly profile relevant."
            )
        else:
            effective_classification_method = METHOD_CORE_PUBLIC_HEALTH_PROBABLE
            classification_notes = (
                "Only core public health federal accounts are linked, and none are explicitly excluded, so the "
                "transaction is treated as probably profile relevant."
            )
    elif federal_health_transfer_items and distinct_known_scopes == {FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER}:
        effective_funding_scope = FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER
        effective_funding_stream = STREAM_TRANSFER
        effective_scope_guess = SCOPE_SPECIAL
        effective_profile_relevant = False
        effective_classification_method = METHOD_FEDERAL_HEALTH_TRANSFER_EXCLUDED
        classification_notes = (
            "The linked account set resolves to Medicaid-like or other federal health financing transfers, which are "
            "excluded from the core CDC public health reconstruction."
        )
    elif international_health_assistance_items and distinct_known_scopes <= {
        FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE,
        FUNDING_SCOPE_UNKNOWN,
    }:
        effective_funding_scope = FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE
        effective_funding_stream = STREAM_TRANSFER
        effective_scope_guess = SCOPE_UNCERTAIN
        effective_profile_relevant = False
        effective_classification_method = METHOD_INTERNATIONAL_HEALTH_ASSISTANCE_EXCLUDED
        classification_notes = (
            "The linked account set resolves to international health or foreign assistance funding, which is excluded "
            "from the domestic CDC public health reconstruction."
        )
    elif biomedical_research_items and distinct_known_scopes <= {
        FUNDING_SCOPE_BIOMEDICAL_RESEARCH,
        FUNDING_SCOPE_UNKNOWN,
    }:
        effective_funding_scope = FUNDING_SCOPE_BIOMEDICAL_RESEARCH
        effective_funding_stream = STREAM_REGULAR
        effective_scope_guess = SCOPE_UNCERTAIN
        effective_profile_relevant = False
        effective_classification_method = METHOD_BIOMEDICAL_RESEARCH_EXCLUDED
        classification_notes = (
            "The linked account set resolves to biomedical research funding, which is excluded from the CDC public "
            "health reconstruction."
        )
    elif other_public_health_items and distinct_known_scopes <= {
        FUNDING_SCOPE_OTHER_PUBLIC_HEALTH,
        FUNDING_SCOPE_UNKNOWN,
    }:
        effective_funding_scope = FUNDING_SCOPE_OTHER_PUBLIC_HEALTH
        effective_funding_stream = STREAM_REGULAR
        effective_scope_guess = SCOPE_UNCERTAIN
        effective_profile_relevant = False
        effective_classification_method = METHOD_OTHER_PUBLIC_HEALTH_EXCLUDED
        classification_notes = (
            "The linked account set resolves to non-CDC public health or health-program funding, which is excluded "
            "from the CDC core public health reconstruction."
        )
    elif distinct_known_scopes and distinct_known_scopes <= excluded_only_scopes:
        if FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE in distinct_known_scopes:
            effective_funding_scope = FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE
            effective_funding_stream = STREAM_TRANSFER
            effective_classification_method = METHOD_INTERNATIONAL_HEALTH_ASSISTANCE_EXCLUDED
            classification_notes = (
                "The linked account set is dominated by international health assistance scopes and is excluded from "
                "the domestic CDC model."
            )
        elif FUNDING_SCOPE_BIOMEDICAL_RESEARCH in distinct_known_scopes:
            effective_funding_scope = FUNDING_SCOPE_BIOMEDICAL_RESEARCH
            effective_funding_stream = STREAM_REGULAR
            effective_classification_method = METHOD_BIOMEDICAL_RESEARCH_EXCLUDED
            classification_notes = (
                "The linked account set is dominated by biomedical research scopes and is excluded from the CDC core "
                "public health model."
            )
        elif FUNDING_SCOPE_OTHER_PUBLIC_HEALTH in distinct_known_scopes:
            effective_funding_scope = FUNDING_SCOPE_OTHER_PUBLIC_HEALTH
            effective_funding_stream = STREAM_REGULAR
            effective_classification_method = METHOD_OTHER_PUBLIC_HEALTH_EXCLUDED
            classification_notes = (
                "The linked account set is dominated by other public health scopes and is excluded from the CDC core "
                "public health model."
            )
        else:
            effective_funding_scope = FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER
            effective_funding_stream = STREAM_TRANSFER
            effective_classification_method = METHOD_FEDERAL_HEALTH_TRANSFER_EXCLUDED
            classification_notes = (
                "The linked account set is dominated by federal health financing transfer scopes and is excluded from "
                "the CDC core public health model."
            )
        effective_scope_guess = SCOPE_MIXED if has_mixed_accounts else SCOPE_UNCERTAIN
        effective_profile_relevant = False
    elif special_transfer_items:
        effective_funding_scope = FUNDING_SCOPE_SPECIAL_TRANSFER
        effective_funding_stream = STREAM_TRANSFER
        effective_scope_guess = SCOPE_MIXED if has_mixed_accounts else SCOPE_SPECIAL
        any_special_profile_relevant = any(item.get("effective_profile_relevant") is True for item in special_transfer_items)
        all_special_explicitly_excluded = bool(special_transfer_items) and all(
            item.get("effective_profile_relevant") is False for item in special_transfer_items
        )
        if any_special_profile_relevant:
            effective_profile_relevant = True
            effective_classification_method = METHOD_SPECIAL_PROFILE_RELEVANT
            classification_notes = (
                "The linked account set includes a special transfer account with explicit profile-scope support."
            )
        elif all_special_explicitly_excluded and not has_unknown_account:
            effective_profile_relevant = False
            effective_classification_method = METHOD_EXPLICIT_EXCLUSION
            classification_notes = (
                "All linked special transfer accounts are explicitly classified as not profile relevant."
            )
        else:
            effective_classification_method = METHOD_SPECIAL_UNCERTAIN
            classification_notes = (
                "The linked account set includes special transfer funding without enough profile support for a binary "
                "decision."
            )
    elif procurement_support_items:
        effective_funding_scope = FUNDING_SCOPE_PROCUREMENT_SUPPORT
        effective_funding_stream = STREAM_PROCUREMENT
        effective_scope_guess = SCOPE_MIXED if has_mixed_accounts else SCOPE_PROCUREMENT
        any_procurement_profile_relevant = any(
            item.get("effective_profile_relevant") is True for item in procurement_support_items
        )
        all_procurement_explicitly_excluded = bool(procurement_support_items) and all(
            item.get("effective_profile_relevant") is False for item in procurement_support_items
        )
        if any_procurement_profile_relevant:
            effective_profile_relevant = True
            effective_classification_method = METHOD_PROCUREMENT_SUPPORT_PROFILE_RELEVANT
            classification_notes = (
                "The linked account set includes a procurement-support account with explicit profile-scope support."
            )
        elif all_procurement_explicitly_excluded and not has_unknown_account:
            effective_profile_relevant = False
            effective_classification_method = METHOD_EXPLICIT_EXCLUSION
            classification_notes = (
                "All linked procurement-support accounts are explicitly classified as not profile relevant."
            )
        else:
            effective_classification_method = METHOD_PROCUREMENT_SUPPORT_UNCERTAIN
            classification_notes = (
                "The linked account set includes procurement-support funding without enough profile support for a "
                "binary decision."
            )
    elif emergency_items:
        effective_funding_scope = FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH
        effective_funding_stream = _emergency_primary_stream(linked_items)
        effective_scope_guess = SCOPE_EMERGENCY
        if has_profile_relevant_account:
            effective_profile_relevant = True
            effective_classification_method = METHOD_EMERGENCY_PUBLIC_HEALTH_PROFILE_RELEVANT
            classification_notes = (
                "The linked emergency public health accounts include explicit profile-relevant support, but the "
                "transaction still stays out of an automatic include path."
            )
        else:
            effective_classification_method = METHOD_EMERGENCY_PUBLIC_HEALTH_UNCERTAIN
            classification_notes = (
                "Only emergency public health-linked accounts were observed, so the transaction remains uncertain "
                "unless later rules explicitly include it."
            )
    else:
        effective_classification_method = METHOD_UNKNOWN_UNCERTAIN
        classification_notes = (
            "The linked account set does not provide a strong funding-scope classification."
        )

    return {
        "source_transaction_id": str(source_row["source_transaction_id"]),
        "account_count": account_count,
        "distinct_account_count": distinct_account_count,
        "joined_account_symbols": joined_account_symbols,
        "has_regular_account": has_regular_account,
        "has_emergency_account": has_emergency_account,
        "has_arpa_account": has_arpa_account,
        "has_core_public_health_account": has_core_public_health_account,
        "has_emergency_public_health_account": has_emergency_public_health_account,
        "has_federal_health_transfer_account": has_federal_health_transfer_account,
        "has_special_transfer_account": has_special_transfer_account,
        "has_procurement_support_account": has_procurement_support_account,
        "has_other_public_health_account": has_other_public_health_account,
        "has_biomedical_research_account": has_biomedical_research_account,
        "has_international_health_assistance_account": has_international_health_assistance_account,
        "has_profile_relevant_account": has_profile_relevant_account,
        "has_unknown_account": has_unknown_account,
        "has_transfer_or_special_account": has_transfer_or_special_account,
        "has_procurement_account": has_procurement_account,
        "has_non_profile_relevant_account": has_non_profile_relevant_account,
        "effective_funding_stream": effective_funding_stream,
        "effective_funding_scope": effective_funding_scope,
        "effective_scope_guess": effective_scope_guess,
        "effective_profile_relevant": effective_profile_relevant,
        "effective_classification_method": effective_classification_method,
        "funding_scope_method": component_scope_payload["funding_scope_method"],
        "federal_account_count": component_scope_payload["federal_account_count"],
        "federal_account_combination_key": component_scope_payload["federal_account_combination_key"],
        "federal_account_titles_combined": component_scope_payload["federal_account_titles_combined"],
        "component_account_scopes": component_scope_payload["component_account_scopes"],
        "component_scope_count": component_scope_payload["component_scope_count"],
        "has_mixed_scopes": component_scope_payload["has_mixed_scopes"],
        "account_structure_type": account_structure_type,
        "multi_account_interpretation": multi_account_interpretation,
        "conservative_inclusion_reason": conservative_inclusion_reason,
        "manual_review_recommended": manual_review_recommended,
        "mixed_scope_contains_core": component_scope_payload["mixed_scope_contains_core"],
        "mixed_scope_contains_emergency": component_scope_payload["mixed_scope_contains_emergency"],
        "mixed_scope_contains_transfer": component_scope_payload["mixed_scope_contains_transfer"],
        "mixed_scope_contains_procurement": component_scope_payload["mixed_scope_contains_procurement"],
        "mixed_scope_contains_research": component_scope_payload["mixed_scope_contains_research"],
        "mixed_scope_contains_international": component_scope_payload["mixed_scope_contains_international"],
        "mixed_scope_contains_special_transfer": component_scope_payload["mixed_scope_contains_special_transfer"],
        "mixed_scope_contains_unknown": component_scope_payload["mixed_scope_contains_unknown"],
        "classification_notes": classification_notes,
        "refreshed_at": datetime.now(timezone.utc),
    }


def build_assistance_transaction_account_summary_rows(
    *,
    source_rows: list[dict[str, Any]],
    account_rows: list[dict[str, Any]],
    lookup_by_symbol: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows_by_transaction_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for account_row in account_rows:
        source_transaction_id = _normalize_text(account_row.get("source_transaction_id"))
        if source_transaction_id is None:
            continue
        rows_by_transaction_id[source_transaction_id].append(account_row)

    summary_rows = [
        derive_assistance_transaction_account_summary(
            source_row=source_row,
            account_rows=rows_by_transaction_id.get(str(source_row["source_transaction_id"]), []),
            lookup_by_symbol=lookup_by_symbol,
        )
        for source_row in source_rows
        if _normalize_text(source_row.get("source_transaction_id")) is not None
    ]
    summary_rows.sort(key=lambda row: str(row["source_transaction_id"]))
    return summary_rows


def fetch_assistance_transaction_account_rows(connection: Any) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            text(
                f"""
                SELECT *
                FROM {ACCOUNTS_FQTN}
                ORDER BY federal_account_symbol, fiscal_year NULLS LAST, source_row_id, account_position
                """
            )
        ).mappings().all()
    ]


def fetch_assistance_transaction_account_summary_rows(connection: Any) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            text(
                f"""
                SELECT *
                FROM {ACCOUNT_SUMMARY_FQTN}
                ORDER BY source_transaction_id
                """
            )
        ).mappings().all()
    ]


def build_assistance_transaction_account_summary_rows_from_connection(connection: Any) -> list[dict[str, Any]]:
    source_rows = fetch_assistance_source_rows(connection)
    account_rows = build_assistance_transaction_account_rows(source_rows)
    lookup_by_symbol = _fetch_lookup_rows_by_symbol(connection)
    return build_assistance_transaction_account_summary_rows(
        source_rows=source_rows,
        account_rows=account_rows,
        lookup_by_symbol=lookup_by_symbol,
    )


def refresh_assistance_transaction_accounts(connection: Any, *, dry_run: bool = False) -> dict[str, Any]:
    source_rows = fetch_assistance_source_rows(connection)
    account_rows = build_assistance_transaction_account_rows(source_rows)
    if not dry_run:
        _replace_table_rows(connection, ACCOUNT_TABLE, account_rows)
    diagnostics = build_multi_account_diagnostics(source_rows)
    diagnostics.update(
        {
            "bridge_rows_written": len(account_rows),
            "source_rows_evaluated": len(source_rows),
        }
    )
    return diagnostics


def refresh_assistance_transaction_account_summary(connection: Any, *, dry_run: bool = False) -> dict[str, Any]:
    source_rows = fetch_assistance_source_rows(connection)
    account_rows = (
        build_assistance_transaction_account_rows(source_rows)
        if dry_run
        else fetch_assistance_transaction_account_rows(connection)
    )
    lookup_by_symbol = _fetch_lookup_rows_by_symbol(connection)
    summary_rows = build_assistance_transaction_account_summary_rows(
        source_rows=source_rows,
        account_rows=account_rows,
        lookup_by_symbol=lookup_by_symbol,
    )
    if not dry_run:
        _replace_table_rows(connection, ACCOUNT_SUMMARY_TABLE, summary_rows)
    return {
        "summary_rows_written": len(summary_rows),
        "profile_relevant_summaries": sum(
            1
            for row in summary_rows
            if row.get("effective_classification_method")
            in {
                METHOD_REGULAR_PROFILE_RELEVANT,
                METHOD_REGULAR_PROBABLE,
                METHOD_MIXED_PROBABLE,
                METHOD_SPECIAL_PROFILE_RELEVANT,
                METHOD_PROCUREMENT_SUPPORT_PROFILE_RELEVANT,
            }
        ),
        "uncertain_summaries": sum(
            1
            for row in summary_rows
            if row.get("effective_classification_method")
            in {
                METHOD_NO_ACCOUNTS,
                METHOD_ALL_UNKNOWN,
                METHOD_UNKNOWN_MIXED_REVIEW,
                METHOD_MIXED_CORE_EMERGENCY_CONSERVATIVE,
                METHOD_MIXED_PROGRAM_SUPPORT_CONSERVATIVE,
                METHOD_MIXED_PROGRAM_TRANSFER_CONSERVATIVE,
                METHOD_MIXED_EMERGENCY_SUPPORT_CONSERVATIVE,
                METHOD_MIXED_RESEARCH_CONSERVATIVE,
                METHOD_MIXED_INTERNATIONAL_CONSERVATIVE,
                METHOD_MIXED_SPECIAL_TRANSFER_CONSERVATIVE,
                METHOD_MIXED_UNCERTAIN,
                METHOD_EMERGENCY_UNCERTAIN,
                METHOD_SPECIAL_UNCERTAIN,
                METHOD_UNKNOWN_UNCERTAIN,
            }
        ),
    }


def build_multi_account_diagnostics(source_rows: list[dict[str, Any]]) -> dict[str, Any]:
    single_count = 0
    multi_count = 0
    missing_count = 0
    single_amount = Decimal("0.00")
    multi_amount = Decimal("0.00")
    missing_amount = Decimal("0.00")
    combo_totals: dict[str, dict[str, Any]] = defaultdict(lambda: {"transaction_count": 0, "amount": Decimal("0.00")})
    individual_from_multi: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"transaction_count": 0, "amount": Decimal("0.00")}
    )

    for source_row in source_rows:
        amount = _quantize_money(_to_decimal(source_row.get("transaction_obligated_amount"))) or Decimal("0.00")
        symbols = split_assistance_federal_account_symbols(source_row.get("raw_federal_account_symbol"))
        if not symbols:
            missing_count += 1
            missing_amount += amount
            continue
        if len(symbols) == 1:
            single_count += 1
            single_amount += amount
            continue

        multi_count += 1
        multi_amount += amount
        combo_key = canonical_account_combination_key(symbols) or "; ".join(symbols)
        combo_totals[combo_key]["transaction_count"] += 1
        combo_totals[combo_key]["amount"] += amount
        for symbol in dict.fromkeys(symbols):
            individual_from_multi[symbol]["transaction_count"] += 1
            individual_from_multi[symbol]["amount"] += amount

    top_combos = sorted(
        (
            {
                "account_symbols": key,
                "transaction_count": value["transaction_count"],
                "transaction_obligated_amount": _quantize_money(value["amount"]),
            }
            for key, value in combo_totals.items()
        ),
        key=lambda row: (row["transaction_obligated_amount"], row["transaction_count"], row["account_symbols"]),
        reverse=True,
    )[:10]
    top_individual_accounts = sorted(
        (
            {
                "federal_account_symbol": key,
                "transaction_count": value["transaction_count"],
                "transaction_obligated_amount": _quantize_money(value["amount"]),
            }
            for key, value in individual_from_multi.items()
        ),
        key=lambda row: (
            row["transaction_obligated_amount"],
            row["transaction_count"],
            row["federal_account_symbol"],
        ),
        reverse=True,
    )[:15]

    return {
        "single_account_rows": single_count,
        "single_account_amount": _quantize_money(single_amount),
        "multi_account_rows": multi_count,
        "multi_account_amount": _quantize_money(multi_amount),
        "missing_account_rows": missing_count,
        "missing_account_amount": _quantize_money(missing_amount),
        "top_multi_account_combinations": top_combos,
        "top_individual_account_symbols_from_multi_account_rows": top_individual_accounts,
    }
