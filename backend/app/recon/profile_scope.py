from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.cdc_funding.appropriation import (
    APPROPRIATION_SUBTYPE_ARP,
    APPROPRIATION_TYPE_COVID_EMERGENCY,
    APPROPRIATION_TYPE_OTHER_EMERGENCY,
    classify_official_emergency_code,
    extract_defc_codes,
)
from app.db import DEFAULT_DB_URL
from app.db_fqtn import cdc_funding_table, recon_table, usaspending_table
from app.recon.assistance_accounts import (
    METHOD_ALL_UNKNOWN,
    METHOD_BIOMEDICAL_RESEARCH_EXCLUDED,
    METHOD_EMERGENCY_PROFILE_RELEVANT,
    METHOD_EMERGENCY_UNCERTAIN,
    METHOD_EXPLICIT_EXCLUSION,
    METHOD_FEDERAL_HEALTH_TRANSFER_EXCLUDED,
    METHOD_INTERNATIONAL_HEALTH_ASSISTANCE_EXCLUDED,
    METHOD_MIXED_CORE_EMERGENCY_CONSERVATIVE,
    METHOD_MIXED_EMERGENCY_SUPPORT_CONSERVATIVE,
    METHOD_MIXED_INTERNATIONAL_CONSERVATIVE,
    METHOD_MIXED_PROBABLE,
    METHOD_MIXED_PROGRAM_SUPPORT_CONSERVATIVE,
    METHOD_MIXED_PROGRAM_TRANSFER_CONSERVATIVE,
    METHOD_MIXED_RESEARCH_CONSERVATIVE,
    METHOD_MIXED_SPECIAL_TRANSFER_CONSERVATIVE,
    METHOD_MIXED_UNCERTAIN,
    METHOD_NO_ACCOUNTS,
    METHOD_OTHER_PUBLIC_HEALTH_EXCLUDED,
    METHOD_PROCUREMENT_SUPPORT_PROFILE_RELEVANT,
    METHOD_PROCUREMENT_SUPPORT_UNCERTAIN,
    METHOD_REGULAR_PROBABLE,
    METHOD_REGULAR_PROFILE_RELEVANT,
    METHOD_SPECIAL_PROFILE_RELEVANT,
    METHOD_SPECIAL_UNCERTAIN,
    METHOD_UNKNOWN_MIXED_REVIEW,
    METHOD_UNKNOWN_UNCERTAIN,
    build_assistance_transaction_account_summary_rows_from_connection,
    fetch_assistance_source_rows as fetch_normalized_assistance_source_rows,
    fetch_assistance_transaction_account_summary_rows,
    refresh_assistance_transaction_account_summary,
    refresh_assistance_transaction_accounts,
)
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
    funding_scope_indicator_flags,
    funding_scope_to_legacy_scope_guess,
    normalize_funding_scope,
)
from app.recon.multi_account import (
    ACCOUNT_STRUCTURE_MULTI_MIXED_SCOPE,
    build_component_scope_payload,
)
from app.recon.models import (
    AssistanceTransactionProfileEnriched,
    ContractTransactionProfileEnriched,
    ProfileScopeRule,
    ProfileScopeStateYearSummary,
    ProfileScopeTransaction,
)
from app.usaspending.ingest import (
    CATEGORY_ADMIN,
    CATEGORY_IMMUNIZATION,
    CATEGORY_IT,
    CATEGORY_LAB,
    CATEGORY_LIKELY_VFC,
    CATEGORY_OTHER,
    CATEGORY_RESEARCH,
    CATEGORY_UNKNOWN,
    classify_contract_record,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RULES_CSV_PATH = REPO_ROOT / "data" / "recon" / "profile_scope_rules.csv"
DEFAULT_SUMMARY_PATH = REPO_ROOT / "data" / "recon" / "profile_scope_build_summary.json"
DEFAULT_MULTI_ACCOUNT_SUMMARY_PATH = REPO_ROOT / "data" / "recon" / "multi_account_attribution_summary.json"

METHODOLOGY_VERSION = "profile_scope_v5_verified_csv_multi_account_fy2021_diagnostics"
SOURCE_ASSISTANCE = "assistance"
SOURCE_CONTRACTS = "contracts"
SOURCE_BOTH = "both"

STREAM_REGULAR = "regular_appropriation"
STREAM_COVID = "covid_emergency"
STREAM_ARPA = "arpa"
STREAM_OTHER_EMERGENCY = "other_emergency_or_disaster"
STREAM_TRANSFER = "transfer_or_special"
STREAM_PROCUREMENT = "procurement_support"
STREAM_UNKNOWN = "unknown"
STREAM_MIXED = "mixed"

SCOPE_CORE = "likely_core_cdc"
SCOPE_SPECIAL = "likely_special_transfer"
SCOPE_EMERGENCY = "likely_emergency_supplemental"
SCOPE_PROCUREMENT = "likely_procurement_only"
SCOPE_UNCERTAIN = "uncertain"
SCOPE_MIXED = "mixed_or_multi_account"

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

NULL_TOKENS = {"", "na", "n/a", "none", "null", "nan"}
TRUE_TOKENS = {"1", "true", "t", "yes", "y"}
FALSE_TOKENS = {"0", "false", "f", "no", "n"}
NON_WORD_RE = re.compile(r"[^a-z0-9]+")
WHITESPACE_RE = re.compile(r"\s+")

DOMESTIC_COUNTRY_TOKENS = {
    "united states",
    "united states of america",
    "united states minor outlying islands",
    "usa",
    "us",
    "u.s.",
}

RULE_TABLE = ProfileScopeRule.__table__
ASSISTANCE_PROFILE_TABLE = AssistanceTransactionProfileEnriched.__table__
CONTRACT_PROFILE_TABLE = ContractTransactionProfileEnriched.__table__
PROFILE_SCOPE_TABLE = ProfileScopeTransaction.__table__
STATE_YEAR_SUMMARY_TABLE = ProfileScopeStateYearSummary.__table__

PROFILE_SCOPE_RULES_FQTN = recon_table("profile_scope_rules")
FEDERAL_ACCOUNT_LOOKUP_FQTN = recon_table("federal_account_lookup")
ASSISTANCE_ACCOUNTS_FQTN = recon_table("assistance_transaction_accounts")
ASSISTANCE_ACCOUNT_SUMMARY_FQTN = recon_table("assistance_transaction_account_summary")
CONTRACT_ACCOUNTS_FQTN = recon_table("contract_transaction_accounts")
ASSISTANCE_SOURCE_FQTN = cdc_funding_table("prime_transactions")
ASSISTANCE_AWARDS_FQTN = cdc_funding_table("prime_awards")
CONTRACT_SOURCE_FQTN = usaspending_table("contract_transactions_raw")
ASSISTANCE_PROFILE_FQTN = recon_table("assistance_transactions_profile_enriched")
CONTRACT_PROFILE_FQTN = recon_table("contract_transactions_profile_enriched")
PROFILE_SCOPE_TX_FQTN = recon_table("profile_scope_transactions")
STATE_YEAR_SUMMARY_FQTN = recon_table("profile_scope_state_year_summary")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the CDC profile-scope reconstruction layer for CHIP.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or the local development DSN).",
    )
    parser.add_argument(
        "--rules-path",
        default=str(DEFAULT_RULES_CSV_PATH),
        help="Seed CSV for profile-scope rules when recon.profile_scope_rules is empty.",
    )
    parser.add_argument(
        "--summary-path",
        default=str(DEFAULT_SUMMARY_PATH),
        help="JSON output path for the profile-scope build summary.",
    )
    parser.add_argument(
        "--truncate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Truncate and rebuild derived profile-scope tables before writing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build payloads and print summary without writing database rows.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print the summary payload after the rebuild completes.",
    )
    return parser.parse_args()


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


def _normalize_key(value: Any) -> str:
    token = _normalize_lower(value)
    return NON_WORD_RE.sub("_", token).strip("_")


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


def _quantize_weight(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal("0.01"))


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    token = _normalize_lower(value)
    if not token:
        return None
    if token in TRUE_TOKENS:
        return True
    if token in FALSE_TOKENS:
        return False
    return None


def _serialize_json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _serialize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_json_value(item) for item in value]
    return value


def _split_tokens(value: Any) -> list[str]:
    token = _normalize_text(value)
    if token is None:
        return []
    seen: set[str] = set()
    tokens: list[str] = []
    for piece in re.split(r"\s*[;,|]\s*", token):
        normalized = _normalize_text(piece)
        if normalized is None:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        tokens.append(normalized)
    return tokens


def _join_sorted_tokens(values: list[str]) -> str | None:
    normalized = sorted({token for token in values if _normalize_text(token)})
    if not normalized:
        return None
    return "; ".join(normalized)


def _stringify_match_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return format(value, "f")
    return _normalize_text(value)


def _table_exists(connection: Any, table_name: str) -> bool:
    row = connection.execute(
        text("SELECT to_regclass(:name) AS exists"),
        {"name": table_name},
    ).mappings().one()
    return row["exists"] is not None


def _require_tables(connection: Any, table_names: list[str]) -> None:
    missing = [table_name for table_name in table_names if not _table_exists(connection, table_name)]
    if missing:
        raise RuntimeError(
            "Required objects are missing for profile-scope rebuild: "
            + ", ".join(missing)
            + ". Run migrations, USAspending/CDC assistance ingest, and the federal-account lookup build first."
        )


def load_rule_seed_rows(path: str | Path) -> list[dict[str, Any]]:
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: list[dict[str, Any]] = []
        for idx, row in enumerate(reader, start=1):
            include_value = _bool_or_none(row.get("include_in_profile_scope"))
            weight_token = _normalize_text(row.get("inclusion_weight"))
            rows.append(
                {
                    "rule_id": idx,
                    "priority": int(row.get("priority") or 0),
                    "source_system": _normalize_lower(row.get("source_system")) or SOURCE_BOTH,
                    "match_field": _normalize_text(row.get("match_field")) or "decision_context",
                    "match_type": _normalize_lower(row.get("match_type")) or "equals",
                    "match_value": _normalize_text(row.get("match_value")) or "",
                    "include_in_profile_scope": include_value,
                    "inclusion_weight": (
                        _quantize_weight(_to_decimal(weight_token)) if weight_token is not None else None
                    ),
                    "assigned_reason": _normalize_text(row.get("assigned_reason")),
                    "confidence_label": _normalize_lower(row.get("confidence_label")) or None,
                    "notes": _normalize_text(row.get("notes")),
                    "is_active": _bool_or_none(row.get("is_active")) is not False,
                }
            )
    rows.sort(key=lambda item: (int(item["priority"]), int(item["rule_id"])))
    return rows


def _rule_count(connection: Any) -> int:
    row = connection.execute(
        text(f"SELECT COUNT(*) AS count FROM {PROFILE_SCOPE_RULES_FQTN}"),
    ).mappings().one()
    return int(row["count"] or 0)


def bootstrap_profile_scope_rules(connection: Any, seed_rows: list[dict[str, Any]]) -> None:
    if not seed_rows or _rule_count(connection) > 0:
        return
    insert_rows = [
        {
            "priority": row["priority"],
            "source_system": row["source_system"],
            "match_field": row["match_field"],
            "match_type": row["match_type"],
            "match_value": row["match_value"],
            "include_in_profile_scope": row["include_in_profile_scope"],
            "inclusion_weight": row["inclusion_weight"],
            "assigned_reason": row["assigned_reason"],
            "confidence_label": row["confidence_label"],
            "notes": row["notes"],
            "is_active": row["is_active"],
        }
        for row in seed_rows
    ]
    insert_stmt = pg_insert(RULE_TABLE).values(insert_rows)
    connection.execute(
        insert_stmt.on_conflict_do_nothing(
            constraint="uq_recon_profile_scope_rule_match",
        )
    )


def fetch_active_profile_scope_rules(connection: Any) -> list[dict[str, Any]]:
    rows = connection.execute(
        text(
            f"""
            SELECT
                rule_id,
                priority,
                source_system,
                match_field,
                match_type,
                match_value,
                include_in_profile_scope,
                inclusion_weight,
                assigned_reason,
                confidence_label,
                notes,
                is_active
            FROM {PROFILE_SCOPE_RULES_FQTN}
            WHERE is_active = TRUE
            ORDER BY priority ASC, rule_id ASC
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def _fetch_assistance_source_rows(connection: Any) -> list[dict[str, Any]]:
    rows = fetch_normalized_assistance_source_rows(connection)
    return [
        {
            **row,
            "source_system": SOURCE_ASSISTANCE,
            "disaster_emergency_fund_code": row.get("raw_emergency_code"),
        }
        for row in rows
    ]


def _fetch_contract_source_rows(connection: Any) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            text(
                f"""
                SELECT
                    COALESCE(contract_transaction_unique_key, CAST(id AS text)) AS source_transaction_id,
                    'contracts'::text AS source_system,
                    fiscal_year,
                    COALESCE(normalized_recipient_state, recipient_state_code) AS state_code,
                    recipient_name,
                    COALESCE(
                        NULLIF(BTRIM(recipient_country_name), ''),
                        CASE
                            WHEN COALESCE(normalized_recipient_state, recipient_state_code) IS NOT NULL
                                THEN 'UNITED STATES'
                            ELSE NULL
                        END
                    ) AS recipient_country_name,
                    awarding_agency_name,
                    funding_agency_name,
                    COALESCE(normalized_federal_account_symbol, federal_account_symbol) AS raw_federal_account_symbol,
                    treasury_account_symbol AS raw_treasury_account_symbol,
                    appropriation_type,
                    disaster_emergency_fund_code,
                    award_description,
                    product_or_service_code,
                    product_or_service_code_description,
                    naics_code,
                    naics_description,
                    contract_award_type,
                    contract_transaction_type,
                    COALESCE(transaction_obligated_amount, 0)::numeric(18, 2) AS transaction_obligated_amount
                FROM {CONTRACT_SOURCE_FQTN}
                """
            )
        ).mappings().all()
    ]


def _fetch_account_rows(connection: Any, *, source_system: str) -> dict[str, list[dict[str, Any]]]:
    source_fqtn = ASSISTANCE_ACCOUNTS_FQTN if source_system == SOURCE_ASSISTANCE else CONTRACT_ACCOUNTS_FQTN
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rows = connection.execute(
        text(
            f"""
            SELECT
                transaction_unique_key AS source_transaction_id,
                account_row.federal_account_symbol,
                account_row.treasury_account_symbol,
                lookup.account_title,
                lookup.effective_funding_stream,
                lookup.effective_funding_scope,
                lookup.funding_scope_method,
                lookup.effective_scope_guess,
                lookup.effective_profile_relevant,
                lookup.likely_core_public_health,
                lookup.likely_emergency_public_health,
                lookup.likely_federal_health_transfer,
                lookup.likely_procurement_support,
                lookup.likely_other_public_health,
                lookup.likely_biomedical_research,
                lookup.likely_international_health_assistance,
                lookup.likely_vfc_related,
                lookup.likely_emergency_related,
                lookup.likely_arpa_related,
                lookup.likely_regular_appropriation
            FROM {source_fqtn} AS account_row
            LEFT JOIN {FEDERAL_ACCOUNT_LOOKUP_FQTN} AS lookup
              ON lookup.federal_account_symbol = account_row.federal_account_symbol
            """
        )
    ).mappings().all()
    for row in rows:
        key = _normalize_text(row.get("source_transaction_id"))
        if key is None:
            continue
        grouped[key].append(dict(row))
    return grouped


def _fetch_assistance_account_summary_map(connection: Any) -> dict[str, dict[str, Any]]:
    return {
        str(row["source_transaction_id"]): row
        for row in fetch_assistance_transaction_account_summary_rows(connection)
    }


def _resolve_consensus(values: list[str], *, mixed_value: str | None = None) -> str | None:
    distinct = sorted({token for token in values if _normalize_text(token)})
    if not distinct:
        return None
    if len(distinct) == 1:
        return distinct[0]
    return mixed_value


def _emergency_primary_stream(items: list[dict[str, Any]]) -> str:
    buckets = {_assistance_stream_bucket(_normalize_text(item.get("effective_funding_stream"))) for item in items}
    if buckets == {"arpa"}:
        return STREAM_ARPA
    if buckets == {"emergency"}:
        raw_streams = {
            _normalize_text(item.get("effective_funding_stream"))
            for item in items
            if _normalize_text(item.get("effective_funding_stream"))
        }
        if raw_streams == {STREAM_COVID}:
            return STREAM_COVID
        return STREAM_OTHER_EMERGENCY
    if "arpa" in buckets:
        return STREAM_ARPA
    return STREAM_OTHER_EMERGENCY


def _infer_funding_stream(
    *,
    appropriation_type: Any,
    disaster_emergency_fund_code: Any,
    descriptor_blob: str,
    force_transfer: bool = False,
    force_procurement: bool = False,
) -> str:
    if force_procurement:
        return STREAM_PROCUREMENT
    if force_transfer:
        return STREAM_TRANSFER

    defc_classification = classify_official_emergency_code(disaster_emergency_fund_code)
    defc_codes = {code.upper() for code in extract_defc_codes(disaster_emergency_fund_code)}
    if APPROPRIATION_SUBTYPE_ARP in str(defc_classification.get("appropriation_subtype") or "") or "V" in defc_codes:
        return STREAM_ARPA
    if defc_classification.get("appropriation_type") == APPROPRIATION_TYPE_COVID_EMERGENCY:
        return STREAM_COVID
    if defc_classification.get("appropriation_type") == APPROPRIATION_TYPE_OTHER_EMERGENCY:
        return STREAM_OTHER_EMERGENCY

    normalized_appropriation = _normalize_lower(appropriation_type)
    if normalized_appropriation == "regular" or not normalized_appropriation:
        if any(term in descriptor_blob for term in ("vaccines for children", "drug free communities", "transfer")):
            return STREAM_TRANSFER
        return STREAM_REGULAR
    if normalized_appropriation == "covid_emergency":
        return STREAM_COVID
    if normalized_appropriation == "other_emergency":
        return STREAM_OTHER_EMERGENCY
    if "american rescue plan" in descriptor_blob or re.search(r"\barpa\b", descriptor_blob):
        return STREAM_ARPA
    if any(term in descriptor_blob for term in ("covid", "coronavirus", "cares act", "crrsa")):
        return STREAM_COVID
    if any(term in descriptor_blob for term in ("transfer", "vaccines for children", "drug free communities")):
        return STREAM_TRANSFER
    if any(term in descriptor_blob for term in ("emergency", "disaster", "wildfire", "supplemental")):
        return STREAM_OTHER_EMERGENCY
    return STREAM_UNKNOWN


def _infer_scope_guess(
    funding_stream: str | None,
    *,
    likely_vfc_related: bool = False,
) -> str:
    if funding_stream == STREAM_MIXED:
        return SCOPE_MIXED
    inferred_scope = funding_scope_from_stream(
        funding_stream,
        likely_vfc_related=likely_vfc_related,
    )
    if inferred_scope == FUNDING_SCOPE_UNKNOWN:
        return SCOPE_UNCERTAIN
    return funding_scope_to_legacy_scope_guess(inferred_scope)


def _infer_funding_scope(
    funding_stream: str | None,
    *,
    descriptor_blob: str,
    likely_vfc_related: bool = False,
) -> str:
    return funding_scope_from_stream(
        funding_stream,
        descriptor_blob=descriptor_blob,
        likely_vfc_related=likely_vfc_related,
    )


def _resolve_rollup_funding_scope(
    scope_candidates: list[str],
    *,
    fallback_funding_stream: str | None,
    descriptor_blob: str,
    likely_vfc_related: bool = False,
) -> str:
    distinct_scope_set = {
        normalize_funding_scope(scope)
        for scope in scope_candidates
        if normalize_funding_scope(scope) is not None
    }
    distinct_scopes = sorted(
        {
            scope
            for scope in distinct_scope_set
            if scope is not None
        }
    )
    if not distinct_scopes:
        return _infer_funding_scope(
            fallback_funding_stream,
            descriptor_blob=descriptor_blob,
            likely_vfc_related=likely_vfc_related,
        )
    if len(distinct_scopes) == 1:
        return str(distinct_scopes[0])
    if FUNDING_SCOPE_CORE_PUBLIC_HEALTH in distinct_scopes:
        return FUNDING_SCOPE_CORE_PUBLIC_HEALTH
    for scope in (
        FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE,
        FUNDING_SCOPE_BIOMEDICAL_RESEARCH,
        FUNDING_SCOPE_OTHER_PUBLIC_HEALTH,
        FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER,
    ):
        if scope in distinct_scope_set and distinct_scope_set <= {
            FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE,
            FUNDING_SCOPE_BIOMEDICAL_RESEARCH,
            FUNDING_SCOPE_OTHER_PUBLIC_HEALTH,
            FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER,
        }:
            return scope
    if FUNDING_SCOPE_PROCUREMENT_SUPPORT in distinct_scopes and likely_vfc_related:
        return FUNDING_SCOPE_PROCUREMENT_SUPPORT
    if distinct_scopes == [FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER]:
        return FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER
    return FUNDING_SCOPE_UNKNOWN


def _scope_is_mixed(scope_candidates: list[str], resolved_scope: str) -> bool:
    distinct_scopes = {
        normalize_funding_scope(scope)
        for scope in scope_candidates
        if normalize_funding_scope(scope) is not None
    }
    distinct_scopes.discard(None)
    return len(distinct_scopes) > 1 or (
        bool(distinct_scopes)
        and resolved_scope == FUNDING_SCOPE_UNKNOWN
    )


def summarize_account_rows(
    account_rows: list[dict[str, Any]],
    *,
    fallback_federal_account_symbol: Any,
    fallback_treasury_account_symbol: Any,
    appropriation_type: Any,
    disaster_emergency_fund_code: Any,
    descriptor_blob: str,
    force_transfer: bool = False,
    force_procurement: bool = False,
) -> dict[str, Any]:
    federal_symbols = [str(row["federal_account_symbol"]) for row in account_rows if _normalize_text(row.get("federal_account_symbol"))]
    treasury_symbols = [str(row["treasury_account_symbol"]) for row in account_rows if _normalize_text(row.get("treasury_account_symbol"))]
    if not federal_symbols:
        federal_symbols = _split_tokens(fallback_federal_account_symbol)
    if not treasury_symbols:
        treasury_symbols = _split_tokens(fallback_treasury_account_symbol)

    stream_candidates = [
        str(row["effective_funding_stream"])
        for row in account_rows
        if _normalize_text(row.get("effective_funding_stream"))
    ]
    scope_candidates = [
        str(row["effective_funding_scope"])
        for row in account_rows
        if normalize_funding_scope(row.get("effective_funding_scope")) is not None
    ]
    payload_items = list(account_rows)
    if not payload_items and federal_symbols:
        payload_items = [
            {
                "federal_account_symbol": symbol,
                "account_title": None,
                "effective_funding_scope": FUNDING_SCOPE_UNKNOWN,
                "funding_scope_method": "unclassified",
                "effective_profile_relevant": None,
            }
            for symbol in federal_symbols
        ]
    component_scope_payload = build_component_scope_payload(payload_items)
    effective_funding_stream = _resolve_consensus(stream_candidates, mixed_value=STREAM_MIXED)
    likely_vfc_related = any(bool(row.get("likely_vfc_related")) for row in account_rows)
    likely_emergency_related = any(bool(row.get("likely_emergency_related")) for row in account_rows)
    likely_arpa_related = any(bool(row.get("likely_arpa_related")) for row in account_rows)
    likely_regular_appropriation = any(bool(row.get("likely_regular_appropriation")) for row in account_rows)
    likely_core_public_health = any(bool(row.get("likely_core_public_health")) for row in account_rows)
    likely_emergency_public_health = any(bool(row.get("likely_emergency_public_health")) for row in account_rows)
    likely_federal_health_transfer = any(bool(row.get("likely_federal_health_transfer")) for row in account_rows)
    likely_procurement_support = any(bool(row.get("likely_procurement_support")) for row in account_rows)
    likely_other_public_health = any(bool(row.get("likely_other_public_health")) for row in account_rows)
    likely_biomedical_research = any(bool(row.get("likely_biomedical_research")) for row in account_rows)
    likely_international_health_assistance = any(
        bool(row.get("likely_international_health_assistance")) for row in account_rows
    )

    if effective_funding_stream is None:
        effective_funding_stream = _infer_funding_stream(
            appropriation_type=appropriation_type,
            disaster_emergency_fund_code=disaster_emergency_fund_code,
            descriptor_blob=descriptor_blob,
            force_transfer=force_transfer,
            force_procurement=force_procurement,
        )

    effective_funding_scope = _resolve_rollup_funding_scope(
        scope_candidates,
        fallback_funding_stream=effective_funding_stream,
        descriptor_blob=descriptor_blob,
        likely_vfc_related=likely_vfc_related or force_procurement,
    )

    profile_relevant_values = [row.get("effective_profile_relevant") for row in account_rows if row.get("effective_profile_relevant") is not None]
    if True in profile_relevant_values:
        federal_account_profile_relevant = True
    elif profile_relevant_values and all(value is False for value in profile_relevant_values):
        federal_account_profile_relevant = False
    else:
        federal_account_profile_relevant = None

    if component_scope_payload["has_mixed_scopes"]:
        if component_scope_payload["mixed_scope_contains_unknown"]:
            effective_funding_scope = FUNDING_SCOPE_UNKNOWN
            effective_funding_stream = STREAM_UNKNOWN
            federal_account_profile_relevant = None
        elif (
            component_scope_payload["mixed_scope_contains_international"]
            and not component_scope_payload["mixed_scope_contains_core"]
            and not component_scope_payload["mixed_scope_contains_emergency"]
            and not component_scope_payload["mixed_scope_contains_procurement"]
            and not component_scope_payload["mixed_scope_contains_special_transfer"]
        ):
            effective_funding_scope = FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE
            effective_funding_stream = STREAM_TRANSFER
            federal_account_profile_relevant = False
        elif (
            component_scope_payload["mixed_scope_contains_research"]
            and not component_scope_payload["mixed_scope_contains_core"]
            and not component_scope_payload["mixed_scope_contains_emergency"]
            and not component_scope_payload["mixed_scope_contains_procurement"]
            and not component_scope_payload["mixed_scope_contains_special_transfer"]
        ):
            effective_funding_scope = FUNDING_SCOPE_BIOMEDICAL_RESEARCH
            effective_funding_stream = STREAM_REGULAR
            federal_account_profile_relevant = False
        elif component_scope_payload["mixed_scope_contains_core"] and component_scope_payload["mixed_scope_contains_transfer"]:
            effective_funding_scope = FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER
            effective_funding_stream = STREAM_TRANSFER
            federal_account_profile_relevant = None
        elif component_scope_payload["mixed_scope_contains_core"] and component_scope_payload["mixed_scope_contains_procurement"]:
            effective_funding_scope = FUNDING_SCOPE_PROCUREMENT_SUPPORT
            effective_funding_stream = STREAM_PROCUREMENT
            federal_account_profile_relevant = None
        elif component_scope_payload["mixed_scope_contains_core"] and component_scope_payload["mixed_scope_contains_emergency"]:
            effective_funding_scope = FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH
            effective_funding_stream = _emergency_primary_stream(account_rows)
            federal_account_profile_relevant = None
        elif component_scope_payload["mixed_scope_contains_emergency"] and component_scope_payload["mixed_scope_contains_procurement"]:
            effective_funding_scope = FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH
            effective_funding_stream = _emergency_primary_stream(account_rows)
            federal_account_profile_relevant = None
        elif component_scope_payload["mixed_scope_contains_special_transfer"]:
            effective_funding_scope = FUNDING_SCOPE_SPECIAL_TRANSFER
            effective_funding_stream = STREAM_TRANSFER
            federal_account_profile_relevant = None

    effective_scope_guess = funding_scope_to_legacy_scope_guess(
        effective_funding_scope,
        mixed=component_scope_payload["has_mixed_scopes"] or _scope_is_mixed(scope_candidates, effective_funding_scope),
    )

    scope_flags = funding_scope_indicator_flags(effective_funding_scope)

    return {
        "federal_account_symbol": _join_sorted_tokens(federal_symbols),
        "treasury_account_symbol": _join_sorted_tokens(treasury_symbols),
        "effective_funding_stream": effective_funding_stream,
        "funding_scope_method": component_scope_payload["funding_scope_method"],
        "effective_funding_scope": effective_funding_scope,
        "effective_scope_guess": effective_scope_guess,
        "federal_account_profile_relevant": federal_account_profile_relevant,
        "federal_account_count": component_scope_payload["federal_account_count"],
        "federal_account_combination_key": component_scope_payload["federal_account_combination_key"],
        "federal_account_titles_combined": component_scope_payload["federal_account_titles_combined"],
        "component_account_scopes": component_scope_payload["component_account_scopes"],
        "component_scope_count": component_scope_payload["component_scope_count"],
        "has_mixed_scopes": component_scope_payload["has_mixed_scopes"],
        "account_structure_type": component_scope_payload["account_structure_type"],
        "multi_account_interpretation": component_scope_payload["multi_account_interpretation"],
        "conservative_inclusion_reason": component_scope_payload["conservative_inclusion_reason"],
        "manual_review_recommended": component_scope_payload["manual_review_recommended"],
        "mixed_scope_contains_core": component_scope_payload["mixed_scope_contains_core"],
        "mixed_scope_contains_emergency": component_scope_payload["mixed_scope_contains_emergency"],
        "mixed_scope_contains_transfer": component_scope_payload["mixed_scope_contains_transfer"],
        "mixed_scope_contains_procurement": component_scope_payload["mixed_scope_contains_procurement"],
        "mixed_scope_contains_research": component_scope_payload["mixed_scope_contains_research"],
        "mixed_scope_contains_international": component_scope_payload["mixed_scope_contains_international"],
        "mixed_scope_contains_special_transfer": component_scope_payload["mixed_scope_contains_special_transfer"],
        "mixed_scope_contains_unknown": component_scope_payload["mixed_scope_contains_unknown"],
        "likely_core_public_health": likely_core_public_health or scope_flags["likely_core_public_health"],
        "likely_emergency_public_health": (
            likely_emergency_public_health or scope_flags["likely_emergency_public_health"]
        ),
        "likely_federal_health_transfer": (
            likely_federal_health_transfer or scope_flags["likely_federal_health_transfer"]
        ),
        "likely_procurement_support": likely_procurement_support or scope_flags["likely_procurement_support"],
        "likely_other_public_health": likely_other_public_health or scope_flags["likely_other_public_health"],
        "likely_biomedical_research": likely_biomedical_research or scope_flags["likely_biomedical_research"],
        "likely_international_health_assistance": (
            likely_international_health_assistance
            or scope_flags["likely_international_health_assistance"]
        ),
        "likely_vfc_related": likely_vfc_related,
        "likely_emergency_related": likely_emergency_related or effective_funding_scope == FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH,
        "likely_arpa_related": likely_arpa_related or effective_funding_stream == STREAM_ARPA,
        "likely_regular_appropriation": likely_regular_appropriation or effective_funding_stream == STREAM_REGULAR,
    }


def _is_cdc_agency(*agency_names: Any) -> bool:
    for agency_name in agency_names:
        token = _normalize_lower(agency_name)
        if not token:
            continue
        if "centers for disease control" in token:
            return True
        if re.search(r"\bcdc\b", token):
            return True
    return False


def _is_domestic(*, state_code: Any, recipient_country_name: Any) -> bool | None:
    state_token = _normalize_text(state_code)
    if state_token:
        return True
    country_token = _normalize_lower(recipient_country_name)
    if not country_token:
        return None
    return country_token in DOMESTIC_COUNTRY_TOKENS


def _assistance_stream_bucket(funding_stream: str | None) -> str:
    if funding_stream == STREAM_REGULAR:
        return "regular"
    if funding_stream == STREAM_TRANSFER:
        return "transfer"
    if funding_stream == STREAM_ARPA:
        return "arpa"
    if funding_stream in {STREAM_COVID, STREAM_OTHER_EMERGENCY}:
        return "emergency"
    return "unknown"


def _account_bucket(profile_relevant: bool | None) -> str:
    if profile_relevant is True:
        return "profile_relevant"
    if profile_relevant is False:
        return "account_not_profile_relevant"
    return "account_unknown"


def _resolve_weight(include_in_profile_scope: bool | None, inclusion_weight: Decimal | None) -> Decimal | None:
    if include_in_profile_scope is True:
        return _quantize_weight(inclusion_weight or Decimal("1.00"))
    if include_in_profile_scope is False:
        return Decimal("0.00")
    return None


def _build_reason_fields(
    include_in_profile_scope: bool | None,
    reason: str,
) -> tuple[str | None, str | None]:
    if include_in_profile_scope is True:
        return reason, None
    if include_in_profile_scope is False:
        return None, reason
    return f"Uncertain: {reason}", None


def _assistance_decision_context_from_summary(
    *,
    awarding_agency_is_cdc: bool,
    likely_domestic: bool | None,
    summary_interpretation: str | None,
    summary_method: str | None,
    summary_funding_scope: str | None,
    summary_stream: str | None,
) -> str:
    if likely_domestic is False:
        return "non_domestic"
    if summary_interpretation == "unknown_mixed":
        return "cdc_domestic_unknown_mixed_review"
    if summary_method == METHOD_UNKNOWN_MIXED_REVIEW:
        return "cdc_domestic_unknown_mixed_review"
    if summary_method == METHOD_MIXED_CORE_EMERGENCY_CONSERVATIVE:
        return "cdc_domestic_mixed_core_emergency_conservative"
    if summary_method == METHOD_MIXED_PROGRAM_SUPPORT_CONSERVATIVE:
        return "cdc_domestic_mixed_program_support_conservative"
    if summary_method == METHOD_MIXED_PROGRAM_TRANSFER_CONSERVATIVE:
        return "cdc_domestic_mixed_program_transfer_conservative"
    if summary_method == METHOD_MIXED_EMERGENCY_SUPPORT_CONSERVATIVE:
        return "cdc_domestic_mixed_emergency_support_conservative"
    if summary_method == METHOD_MIXED_RESEARCH_CONSERVATIVE:
        return "cdc_domestic_mixed_research_conservative"
    if summary_method == METHOD_MIXED_INTERNATIONAL_CONSERVATIVE:
        return "international_mixed_conservative"
    if summary_method == METHOD_MIXED_SPECIAL_TRANSFER_CONSERVATIVE:
        return "cdc_domestic_special_transfer_mixed_uncertain"
    if summary_funding_scope == FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE:
        return "international_health_assistance_excluded"
    if summary_method in {METHOD_REGULAR_PROFILE_RELEVANT, METHOD_REGULAR_PROBABLE, METHOD_MIXED_PROBABLE}:
        return "cdc_domestic_core_public_health"
    if summary_method in {METHOD_EMERGENCY_PROFILE_RELEVANT, METHOD_EMERGENCY_UNCERTAIN}:
        return "cdc_domestic_emergency_public_health_conditional"
    if summary_method == METHOD_FEDERAL_HEALTH_TRANSFER_EXCLUDED:
        return "cdc_domestic_federal_health_transfer_excluded"
    if summary_method in {METHOD_OTHER_PUBLIC_HEALTH_EXCLUDED}:
        return "cdc_domestic_other_public_health_excluded"
    if summary_method in {METHOD_BIOMEDICAL_RESEARCH_EXCLUDED}:
        return "cdc_domestic_biomedical_research_excluded"
    if summary_method in {METHOD_INTERNATIONAL_HEALTH_ASSISTANCE_EXCLUDED}:
        return "international_health_assistance_excluded"
    if summary_method in {METHOD_SPECIAL_PROFILE_RELEVANT, METHOD_SPECIAL_UNCERTAIN}:
        return "cdc_domestic_special_transfer_uncertain"
    if summary_method in {METHOD_PROCUREMENT_SUPPORT_PROFILE_RELEVANT, METHOD_PROCUREMENT_SUPPORT_UNCERTAIN}:
        return "cdc_domestic_procurement_support_uncertain"
    if summary_method == METHOD_EXPLICIT_EXCLUSION:
        return "cdc_domestic_explicitly_excluded"
    if summary_method in {METHOD_ALL_UNKNOWN, METHOD_UNKNOWN_UNCERTAIN}:
        return "cdc_domestic_unknown_uncertain"
    if summary_method == METHOD_NO_ACCOUNTS:
        if summary_funding_scope == FUNDING_SCOPE_CORE_PUBLIC_HEALTH or summary_stream == STREAM_REGULAR:
            return "cdc_domestic_core_public_health"
        if summary_funding_scope == FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER:
            return "cdc_domestic_federal_health_transfer_excluded"
        if summary_funding_scope == FUNDING_SCOPE_OTHER_PUBLIC_HEALTH:
            return "cdc_domestic_other_public_health_excluded"
        if summary_funding_scope == FUNDING_SCOPE_BIOMEDICAL_RESEARCH:
            return "cdc_domestic_biomedical_research_excluded"
        if summary_funding_scope == FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE:
            return "international_health_assistance_excluded"
        if summary_funding_scope == FUNDING_SCOPE_SPECIAL_TRANSFER:
            return "cdc_domestic_special_transfer_uncertain"
        if summary_funding_scope == FUNDING_SCOPE_PROCUREMENT_SUPPORT:
            return "cdc_domestic_procurement_support_uncertain"
        if summary_funding_scope == FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH or summary_stream in {STREAM_COVID, STREAM_ARPA, STREAM_OTHER_EMERGENCY}:
            return "cdc_domestic_emergency_public_health_conditional"
    if not awarding_agency_is_cdc:
        return "non_cdc"
    return "cdc_domestic_unknown_uncertain"


def _string_matches(actual: Any, expected: Any, *, mode: str) -> bool:
    actual_text = _normalize_lower(actual)
    expected_text = _normalize_lower(expected)
    if not actual_text or not expected_text:
        return False
    if mode == "contains":
        return expected_text in actual_text
    if mode == "starts_with":
        return actual_text.startswith(expected_text)
    if mode == "ends_with":
        return actual_text.endswith(expected_text)
    return False


def rule_matches(row: dict[str, Any], rule: dict[str, Any]) -> bool:
    source_system = _normalize_lower(rule.get("source_system"))
    if source_system not in {SOURCE_BOTH, _normalize_lower(row.get("source_system"))}:
        return False

    match_field = str(rule.get("match_field") or "").strip()
    match_type = _normalize_lower(rule.get("match_type"))
    actual = row.get(match_field)
    expected = rule.get("match_value")

    if match_type == "equals":
        return _normalize_lower(_stringify_match_value(actual)) == _normalize_lower(_stringify_match_value(expected))
    if match_type == "not_equals":
        return _normalize_lower(_stringify_match_value(actual)) != _normalize_lower(_stringify_match_value(expected))
    if match_type in {"contains", "starts_with", "ends_with"}:
        return _string_matches(actual, expected, mode=match_type)
    if match_type == "regex":
        actual_text = _stringify_match_value(actual)
        pattern = _normalize_text(expected)
        return bool(actual_text and pattern and re.search(pattern, actual_text, flags=re.IGNORECASE))
    if match_type == "is_true":
        return _bool_or_none(actual) is True
    if match_type == "is_false":
        return _bool_or_none(actual) is False
    if match_type == "is_null":
        return actual is None
    if match_type == "not_null":
        return actual is not None
    return False


def first_matching_rule(row: dict[str, Any], rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    for rule in sorted(
        (rule for rule in rules if bool(rule.get("is_active", True))),
        key=lambda item: (int(item.get("priority") or 0), int(item.get("rule_id") or 0)),
    ):
        if rule_matches(row, rule):
            return rule
    return None


def _apply_rule_override(
    *,
    default_include: bool | None,
    default_weight: Decimal | None,
    default_reason: str,
    default_confidence_label: str,
    matched_rule: dict[str, Any] | None,
) -> dict[str, Any]:
    include_in_profile_scope = default_include
    inclusion_weight = default_weight
    reason = default_reason
    confidence_label = default_confidence_label

    if matched_rule is not None:
        include_in_profile_scope = matched_rule.get("include_in_profile_scope")
        inclusion_weight = _resolve_weight(
            include_in_profile_scope,
            matched_rule.get("inclusion_weight"),
        )
        reason = _normalize_text(matched_rule.get("assigned_reason")) or default_reason
        confidence_label = _normalize_lower(matched_rule.get("confidence_label")) or default_confidence_label

    inclusion_reason, exclusion_reason = _build_reason_fields(include_in_profile_scope, reason)
    return {
        "include_in_profile_scope": include_in_profile_scope,
        "inclusion_weight": inclusion_weight,
        "inclusion_reason": inclusion_reason,
        "exclusion_reason": exclusion_reason,
        "confidence_label": confidence_label,
        "matched_rule_id": matched_rule.get("rule_id") if matched_rule is not None else None,
    }


def assistance_default_decision(row: dict[str, Any]) -> dict[str, Any]:
    decision_context = _normalize_text(row.get("decision_context"))

    if decision_context == "non_cdc":
        return {
            "include_in_profile_scope": False,
            "inclusion_weight": Decimal("0.00"),
            "reason": "Excluded because the awarding/funding agency does not resolve to CDC in the current assistance source.",
            "confidence_label": CONFIDENCE_HIGH,
        }
    if decision_context == "non_domestic":
        return {
            "include_in_profile_scope": False,
            "inclusion_weight": Decimal("0.00"),
            "reason": "Excluded because the assistance transaction appears to be outside domestic recipient scope.",
            "confidence_label": CONFIDENCE_HIGH,
        }
    if decision_context == "international_health_assistance_excluded":
        return {
            "include_in_profile_scope": False,
            "inclusion_weight": Decimal("0.00"),
            "reason": "Excluded because the linked account set resolves to international health or foreign assistance funding rather than domestic CDC public health investment.",
            "confidence_label": CONFIDENCE_HIGH,
        }
    if decision_context == "cdc_domestic_federal_health_transfer_excluded":
        return {
            "include_in_profile_scope": False,
            "inclusion_weight": Decimal("0.00"),
            "reason": "Excluded because the linked account set resolves to Medicaid-like or other federal health financing transfers rather than core CDC public health investment.",
            "confidence_label": CONFIDENCE_HIGH,
        }
    if decision_context == "cdc_domestic_other_public_health_excluded":
        return {
            "include_in_profile_scope": False,
            "inclusion_weight": Decimal("0.00"),
            "reason": "Excluded because the linked account set resolves to non-CDC public health or health-program funding rather than core CDC public health investment.",
            "confidence_label": CONFIDENCE_HIGH,
        }
    if decision_context == "cdc_domestic_biomedical_research_excluded":
        return {
            "include_in_profile_scope": False,
            "inclusion_weight": Decimal("0.00"),
            "reason": "Excluded because the linked account set resolves to biomedical research funding rather than CDC public health investment.",
            "confidence_label": CONFIDENCE_HIGH,
        }
    if decision_context == "cdc_domestic_explicitly_excluded":
        return {
            "include_in_profile_scope": False,
            "inclusion_weight": Decimal("0.00"),
            "reason": "Excluded because the linked account set is explicitly classified out of profile scope.",
            "confidence_label": CONFIDENCE_HIGH,
        }
    if decision_context == "cdc_domestic_core_public_health":
        return {
            "include_in_profile_scope": True,
            "inclusion_weight": Decimal("1.00"),
            "reason": "Included because the linked account set resolves to domestic CDC core public health funding.",
            "confidence_label": (
                CONFIDENCE_HIGH
                if row.get("effective_classification_method") == METHOD_REGULAR_PROFILE_RELEVANT
                or row.get("effective_profile_relevant") is True
                else CONFIDENCE_MEDIUM
            ),
        }
    if decision_context in {
        "cdc_domestic_unknown_mixed_review",
        "cdc_domestic_mixed_core_emergency_conservative",
        "cdc_domestic_mixed_program_support_conservative",
        "cdc_domestic_mixed_program_transfer_conservative",
        "cdc_domestic_mixed_emergency_support_conservative",
        "cdc_domestic_mixed_research_conservative",
        "international_mixed_conservative",
        "cdc_domestic_special_transfer_mixed_uncertain",
    }:
        return {
            "include_in_profile_scope": None,
            "inclusion_weight": None,
            "reason": _normalize_text(row.get("conservative_inclusion_reason"))
            or "The row mixes multiple funding scopes without an exact account-level split, so it stays conservative in the derived normalization layer.",
            "confidence_label": (
                CONFIDENCE_LOW
                if decision_context == "cdc_domestic_unknown_mixed_review"
                else CONFIDENCE_MEDIUM
            ),
        }
    if decision_context in {
        "cdc_domestic_unknown_uncertain",
        "cdc_domestic_emergency_public_health_conditional",
        "cdc_domestic_special_transfer_uncertain",
        "cdc_domestic_procurement_support_uncertain",
    }:
        return {
            "include_in_profile_scope": None,
            "inclusion_weight": None,
            "reason": (
                "The funding scope is informative, but this assistance row still stays conditional until explicit "
                "methodology rules support inclusion."
            ),
            "confidence_label": (
                CONFIDENCE_MEDIUM
                if decision_context
                in {
                    "cdc_domestic_emergency_public_health_conditional",
                }
                else CONFIDENCE_LOW
            ),
        }
    return {
        "include_in_profile_scope": None,
        "inclusion_weight": None,
        "reason": "The row remains uncertain because the funding scope and account classification are too incomplete for a binary scope decision.",
        "confidence_label": CONFIDENCE_LOW,
    }


def contract_default_decision(row: dict[str, Any]) -> dict[str, Any]:
    contract_category_guess = row.get("contract_category_guess")
    profile_relevant = row.get("federal_account_profile_relevant")
    likely_vfc_related = bool(row.get("likely_vfc_related"))
    decision_context = _normalize_text(row.get("decision_context"))
    effective_funding_scope = normalize_funding_scope(row.get("effective_funding_scope")) or FUNDING_SCOPE_UNKNOWN

    if decision_context == "non_cdc_agency":
        return {
            "include_in_profile_scope": False,
            "inclusion_weight": Decimal("0.00"),
            "reason": "Excluded because the awarding/funding agency does not resolve to CDC in the current contracts source.",
            "confidence_label": CONFIDENCE_HIGH,
        }
    if decision_context == "non_domestic":
        return {
            "include_in_profile_scope": False,
            "inclusion_weight": Decimal("0.00"),
            "reason": "Excluded because the contract recipient appears to be outside domestic recipient scope.",
            "confidence_label": CONFIDENCE_HIGH,
        }
    if decision_context == "international_health_assistance_excluded":
        return {
            "include_in_profile_scope": False,
            "inclusion_weight": Decimal("0.00"),
            "reason": "Excluded because the linked account set resolves to international health or foreign assistance funding rather than domestic CDC public health investment.",
            "confidence_label": CONFIDENCE_HIGH,
        }
    if decision_context == "cdc_domestic_federal_health_transfer_excluded":
        return {
            "include_in_profile_scope": False,
            "inclusion_weight": Decimal("0.00"),
            "reason": "Excluded because federal health financing transfers are not treated as core CDC public health investment in the contract reconstruction.",
            "confidence_label": CONFIDENCE_HIGH,
        }
    if decision_context == "cdc_domestic_other_public_health_excluded":
        return {
            "include_in_profile_scope": False,
            "inclusion_weight": Decimal("0.00"),
            "reason": "Excluded because the linked account set resolves to non-CDC public health or health-program funding rather than core CDC public health investment.",
            "confidence_label": CONFIDENCE_HIGH,
        }
    if decision_context == "cdc_domestic_biomedical_research_excluded":
        return {
            "include_in_profile_scope": False,
            "inclusion_weight": Decimal("0.00"),
            "reason": "Excluded because the linked account set resolves to biomedical research funding rather than CDC public health investment.",
            "confidence_label": CONFIDENCE_HIGH,
        }
    if decision_context in {
        "cdc_domestic_unknown_mixed_review",
        "cdc_domestic_mixed_core_emergency_conservative",
        "cdc_domestic_mixed_program_support_conservative",
        "cdc_domestic_mixed_program_transfer_conservative",
        "cdc_domestic_mixed_emergency_support_conservative",
        "cdc_domestic_mixed_research_conservative",
        "international_mixed_conservative",
        "cdc_domestic_special_transfer_mixed_uncertain",
    }:
        return {
            "include_in_profile_scope": None,
            "inclusion_weight": None,
            "reason": _normalize_text(row.get("conservative_inclusion_reason"))
            or "The row mixes multiple funding scopes without an exact account-level split, so it stays conservative in the derived normalization layer.",
            "confidence_label": (
                CONFIDENCE_LOW
                if decision_context == "cdc_domestic_unknown_mixed_review"
                else CONFIDENCE_MEDIUM
            ),
        }
    if decision_context == "cdc_domestic_procurement_vfc_relevant" or likely_vfc_related or contract_category_guess == CATEGORY_LIKELY_VFC:
        return {
            "include_in_profile_scope": True,
            "inclusion_weight": Decimal("1.00"),
            "reason": "Included because the contract looks like a conservative Vaccines for Children procurement case.",
            "confidence_label": CONFIDENCE_HIGH,
        }
    if decision_context == "cdc_domestic_emergency_public_health_conditional":
        return {
            "include_in_profile_scope": None,
            "inclusion_weight": None,
            "reason": "Emergency public health procurement stays conditional unless stronger methodology support exists.",
            "confidence_label": CONFIDENCE_MEDIUM,
        }
    if contract_category_guess == CATEGORY_IMMUNIZATION and profile_relevant is True:
        return {
            "include_in_profile_scope": None,
            "inclusion_weight": None,
            "reason": "Immunization-related contracts stay uncertain unless stronger VFC-style evidence exists.",
            "confidence_label": CONFIDENCE_MEDIUM,
        }
    if contract_category_guess in {CATEGORY_ADMIN, CATEGORY_IT, CATEGORY_RESEARCH, CATEGORY_LAB, CATEGORY_OTHER}:
        return {
            "include_in_profile_scope": False,
            "inclusion_weight": Decimal("0.00"),
            "reason": "Excluded because the contract appears to be support, operations, IT, research, lab, or other non-VFC procurement.",
            "confidence_label": CONFIDENCE_HIGH if contract_category_guess in {CATEGORY_ADMIN, CATEGORY_IT, CATEGORY_RESEARCH} else CONFIDENCE_MEDIUM,
        }
    if effective_funding_scope == FUNDING_SCOPE_PROCUREMENT_SUPPORT:
        return {
            "include_in_profile_scope": False,
            "inclusion_weight": Decimal("0.00"),
            "reason": "Excluded because procurement-support contracts remain out of scope unless they meet explicit VFC-style inclusion rules.",
            "confidence_label": CONFIDENCE_MEDIUM,
        }
    return {
        "include_in_profile_scope": False,
        "inclusion_weight": Decimal("0.00"),
        "reason": "Unknown contracts are excluded by default until manually reviewed.",
        "confidence_label": CONFIDENCE_LOW,
    }


def classify_assistance_row(
    source_row: dict[str, Any],
    account_summary: dict[str, Any] | None,
    *,
    rules: list[dict[str, Any]],
) -> dict[str, Any]:
    descriptor_blob = " ".join(
        token
        for token in (
            _normalize_lower(source_row.get("assistance_listing_title")),
            _normalize_lower(source_row.get("program_activity_name")),
            _normalize_lower(source_row.get("recipient_name")),
        )
        if token
    )
    fallback_funding_stream = _infer_funding_stream(
        appropriation_type=source_row.get("appropriation_type"),
        disaster_emergency_fund_code=source_row.get("disaster_emergency_fund_code"),
        descriptor_blob=descriptor_blob,
        force_transfer=any(term in descriptor_blob for term in ("vaccines for children", "drug free communities")),
    )
    fallback_scope_guess = _infer_scope_guess(
        fallback_funding_stream,
        likely_vfc_related="vaccines for children" in descriptor_blob,
    )
    fallback_funding_scope = _infer_funding_scope(
        fallback_funding_stream,
        descriptor_blob=descriptor_blob,
        likely_vfc_related="vaccines for children" in descriptor_blob,
    )
    fallback_symbols = _split_tokens(source_row.get("raw_federal_account_symbol"))
    fallback_component_scope_payload = build_component_scope_payload(
        [
            {
                "federal_account_symbol": symbol,
                "account_title": None,
                "effective_funding_scope": fallback_funding_scope if len(fallback_symbols) == 1 else FUNDING_SCOPE_UNKNOWN,
                "funding_scope_method": "unclassified",
                "effective_profile_relevant": None,
            }
            for symbol in fallback_symbols
        ]
    )
    summary_funding_stream = (
        _normalize_text(account_summary.get("effective_funding_stream"))
        if account_summary is not None
        else None
    )
    if summary_funding_stream in {None, STREAM_UNKNOWN}:
        summary_funding_stream = fallback_funding_stream
    summary_funding_scope = (
        normalize_funding_scope(account_summary.get("effective_funding_scope"))
        if account_summary is not None
        else None
    )
    if summary_funding_scope in {None, FUNDING_SCOPE_UNKNOWN}:
        summary_funding_scope = fallback_funding_scope
    summary = {
        "joined_account_symbols": (
            _normalize_text(account_summary.get("joined_account_symbols"))
            if account_summary is not None
            else None
        )
        or ("; ".join(fallback_symbols) if fallback_symbols else None),
        "account_count": int(account_summary.get("account_count") or 0) if account_summary is not None else 0,
        "distinct_account_count": (
            int(account_summary.get("distinct_account_count") or 0)
            if account_summary is not None
            else len(fallback_symbols)
        ),
        "has_profile_relevant_account": bool(account_summary.get("has_profile_relevant_account")) if account_summary else False,
        "has_unknown_account": bool(account_summary.get("has_unknown_account")) if account_summary else not bool(fallback_symbols),
        "effective_funding_stream": summary_funding_stream,
        "effective_funding_scope": summary_funding_scope,
        "effective_scope_guess": funding_scope_to_legacy_scope_guess(summary_funding_scope)
        if summary_funding_scope != FUNDING_SCOPE_UNKNOWN
        else (
            _normalize_text(account_summary.get("effective_scope_guess"))
            if account_summary is not None
            else None
        )
        or fallback_scope_guess,
        "effective_profile_relevant": account_summary.get("effective_profile_relevant") if account_summary else None,
        "effective_classification_method": (
            _normalize_text(account_summary.get("effective_classification_method"))
            if account_summary is not None
            else None
        )
        or METHOD_NO_ACCOUNTS,
        "funding_scope_method": (
            _normalize_text(account_summary.get("funding_scope_method"))
            if account_summary is not None
            else None
        )
        or fallback_component_scope_payload["funding_scope_method"],
        "federal_account_count": (
            int(account_summary.get("federal_account_count") or 0)
            if account_summary is not None
            else int(fallback_component_scope_payload["federal_account_count"] or 0)
        ),
        "federal_account_combination_key": (
            _normalize_text(account_summary.get("federal_account_combination_key"))
            if account_summary is not None
            else None
        )
        or fallback_component_scope_payload["federal_account_combination_key"],
        "federal_account_titles_combined": (
            _normalize_text(account_summary.get("federal_account_titles_combined"))
            if account_summary is not None
            else None
        )
        or fallback_component_scope_payload["federal_account_titles_combined"],
        "component_account_scopes": (
            account_summary.get("component_account_scopes")
            if account_summary is not None
            else fallback_component_scope_payload["component_account_scopes"]
        ),
        "component_scope_count": (
            int(account_summary.get("component_scope_count") or 0)
            if account_summary is not None
            else int(fallback_component_scope_payload["component_scope_count"] or 0)
        ),
        "has_mixed_scopes": bool(account_summary.get("has_mixed_scopes")) if account_summary else bool(
            fallback_component_scope_payload["has_mixed_scopes"]
        ),
        "account_structure_type": (
            _normalize_text(account_summary.get("account_structure_type"))
            if account_summary is not None
            else None
        )
        or fallback_component_scope_payload["account_structure_type"],
        "multi_account_interpretation": (
            _normalize_text(account_summary.get("multi_account_interpretation"))
            if account_summary is not None
            else None
        )
        or fallback_component_scope_payload["multi_account_interpretation"],
        "conservative_inclusion_reason": (
            _normalize_text(account_summary.get("conservative_inclusion_reason"))
            if account_summary is not None
            else None
        )
        or fallback_component_scope_payload["conservative_inclusion_reason"],
        "manual_review_recommended": bool(account_summary.get("manual_review_recommended")) if account_summary else bool(
            fallback_component_scope_payload["manual_review_recommended"]
        ),
        "mixed_scope_contains_core": bool(account_summary.get("mixed_scope_contains_core")) if account_summary else bool(
            fallback_component_scope_payload["mixed_scope_contains_core"]
        ),
        "mixed_scope_contains_emergency": bool(account_summary.get("mixed_scope_contains_emergency")) if account_summary else bool(
            fallback_component_scope_payload["mixed_scope_contains_emergency"]
        ),
        "mixed_scope_contains_transfer": bool(account_summary.get("mixed_scope_contains_transfer")) if account_summary else bool(
            fallback_component_scope_payload["mixed_scope_contains_transfer"]
        ),
        "mixed_scope_contains_procurement": bool(account_summary.get("mixed_scope_contains_procurement")) if account_summary else bool(
            fallback_component_scope_payload["mixed_scope_contains_procurement"]
        ),
        "mixed_scope_contains_research": bool(account_summary.get("mixed_scope_contains_research")) if account_summary else bool(
            fallback_component_scope_payload["mixed_scope_contains_research"]
        ),
        "mixed_scope_contains_international": bool(account_summary.get("mixed_scope_contains_international")) if account_summary else bool(
            fallback_component_scope_payload["mixed_scope_contains_international"]
        ),
        "mixed_scope_contains_special_transfer": bool(account_summary.get("mixed_scope_contains_special_transfer")) if account_summary else bool(
            fallback_component_scope_payload["mixed_scope_contains_special_transfer"]
        ),
        "mixed_scope_contains_unknown": bool(account_summary.get("mixed_scope_contains_unknown")) if account_summary else bool(
            fallback_component_scope_payload["mixed_scope_contains_unknown"]
        ),
        "classification_notes": (
            _normalize_text(account_summary.get("classification_notes"))
            if account_summary is not None
            else None
        ),
    }
    awarding_agency_is_cdc = _is_cdc_agency(
        source_row.get("awarding_agency_name"),
        source_row.get("funding_agency_name"),
    )
    likely_domestic = _is_domestic(
        state_code=source_row.get("state_code"),
        recipient_country_name=source_row.get("recipient_country_name"),
    )
    likely_special_transfer = (
        summary["effective_funding_scope"] in {
            FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER,
            FUNDING_SCOPE_SPECIAL_TRANSFER,
        }
    )
    likely_regular_assistance = (
        summary["effective_funding_scope"] == FUNDING_SCOPE_CORE_PUBLIC_HEALTH
        or summary["effective_classification_method"] in {METHOD_REGULAR_PROFILE_RELEVANT, METHOD_REGULAR_PROBABLE}
    )
    scope_flags = funding_scope_indicator_flags(summary["effective_funding_scope"])
    decision_context = _assistance_decision_context_from_summary(
        awarding_agency_is_cdc=awarding_agency_is_cdc,
        likely_domestic=likely_domestic,
        summary_interpretation=summary["multi_account_interpretation"],
        summary_method=summary["effective_classification_method"],
        summary_funding_scope=summary["effective_funding_scope"],
        summary_stream=summary["effective_funding_stream"],
    )

    candidate_row = {
        "source_system": SOURCE_ASSISTANCE,
        "decision_context": decision_context,
        "assistance_listing_title": source_row.get("assistance_listing_title"),
        "program_activity_name": source_row.get("program_activity_name"),
        "awarding_agency_is_cdc": awarding_agency_is_cdc,
        "likely_domestic": likely_domestic,
        "effective_funding_stream": summary["effective_funding_stream"],
        "funding_scope_method": summary["funding_scope_method"],
        "effective_funding_scope": summary["effective_funding_scope"],
        "federal_account_profile_relevant": summary["effective_profile_relevant"],
        "federal_account_count": summary["federal_account_count"],
        "federal_account_combination_key": summary["federal_account_combination_key"],
        "has_mixed_scopes": summary["has_mixed_scopes"],
        "account_structure_type": summary["account_structure_type"],
        "multi_account_interpretation": summary["multi_account_interpretation"],
        "conservative_inclusion_reason": summary["conservative_inclusion_reason"],
        "manual_review_recommended": summary["manual_review_recommended"],
        "likely_core_public_health": scope_flags["likely_core_public_health"],
        "likely_emergency_public_health": scope_flags["likely_emergency_public_health"],
        "likely_federal_health_transfer": scope_flags["likely_federal_health_transfer"],
        "likely_procurement_support": scope_flags["likely_procurement_support"],
        "likely_other_public_health": scope_flags["likely_other_public_health"],
        "likely_biomedical_research": scope_flags["likely_biomedical_research"],
        "likely_international_health_assistance": scope_flags["likely_international_health_assistance"],
        "likely_special_transfer": likely_special_transfer,
        "likely_regular_assistance": likely_regular_assistance,
        "likely_emergency_related": summary["effective_funding_scope"] == FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH,
        "likely_arpa_related": summary["effective_funding_stream"] == STREAM_ARPA,
    }
    default_decision = assistance_default_decision(
        {
            **candidate_row,
            **summary,
            "awarding_agency_is_cdc": awarding_agency_is_cdc,
            "likely_domestic": likely_domestic,
        }
    )
    matched_rule = first_matching_rule(candidate_row, rules)
    decision = _apply_rule_override(
        default_include=default_decision["include_in_profile_scope"],
        default_weight=default_decision["inclusion_weight"],
        default_reason=default_decision["reason"],
        default_confidence_label=default_decision["confidence_label"],
        matched_rule=matched_rule,
    )

    return {
        "source_transaction_id": str(source_row["source_transaction_id"]),
        "source_system": SOURCE_ASSISTANCE,
        "fiscal_year": source_row.get("fiscal_year"),
        "state_code": _normalize_text(source_row.get("state_code")),
        "recipient_name": _normalize_text(source_row.get("recipient_name")),
        "recipient_country_name": _normalize_text(source_row.get("recipient_country_name")),
        "awarding_agency_name": _normalize_text(source_row.get("awarding_agency_name")),
        "funding_agency_name": _normalize_text(source_row.get("funding_agency_name")),
        "assistance_listing_number": _normalize_text(source_row.get("assistance_listing_number")),
        "assistance_listing_title": _normalize_text(source_row.get("assistance_listing_title")),
        "program_activity_name": _normalize_text(source_row.get("program_activity_name")),
        "federal_account_symbol": summary["joined_account_symbols"],
        "treasury_account_symbol": _normalize_text(source_row.get("raw_treasury_account_symbol")),
        "appropriation_type": _normalize_text(source_row.get("appropriation_type")),
        "disaster_emergency_fund_code": _normalize_text(source_row.get("disaster_emergency_fund_code")),
        "transaction_obligated_amount": _quantize_money(_to_decimal(source_row.get("transaction_obligated_amount"))),
        "effective_funding_stream": summary["effective_funding_stream"],
        "funding_scope_method": summary["funding_scope_method"],
        "effective_funding_scope": summary["effective_funding_scope"],
        "effective_scope_guess": summary["effective_scope_guess"],
        "federal_account_profile_relevant": summary["effective_profile_relevant"],
        "federal_account_count": summary["federal_account_count"],
        "federal_account_combination_key": summary["federal_account_combination_key"],
        "federal_account_titles_combined": summary["federal_account_titles_combined"],
        "component_account_scopes": summary["component_account_scopes"],
        "component_scope_count": summary["component_scope_count"],
        "has_mixed_scopes": summary["has_mixed_scopes"],
        "account_structure_type": summary["account_structure_type"],
        "multi_account_interpretation": summary["multi_account_interpretation"],
        "conservative_inclusion_reason": summary["conservative_inclusion_reason"],
        "manual_review_recommended": summary["manual_review_recommended"],
        "mixed_scope_contains_core": summary["mixed_scope_contains_core"],
        "mixed_scope_contains_emergency": summary["mixed_scope_contains_emergency"],
        "mixed_scope_contains_transfer": summary["mixed_scope_contains_transfer"],
        "mixed_scope_contains_procurement": summary["mixed_scope_contains_procurement"],
        "mixed_scope_contains_research": summary["mixed_scope_contains_research"],
        "mixed_scope_contains_international": summary["mixed_scope_contains_international"],
        "mixed_scope_contains_special_transfer": summary["mixed_scope_contains_special_transfer"],
        "mixed_scope_contains_unknown": summary["mixed_scope_contains_unknown"],
        "include_in_profile_scope": decision["include_in_profile_scope"],
        "inclusion_weight": decision["inclusion_weight"],
        "inclusion_reason": decision["inclusion_reason"],
        "exclusion_reason": decision["exclusion_reason"],
        "confidence_label": decision["confidence_label"],
        "likely_domestic": likely_domestic,
        "likely_core_public_health": scope_flags["likely_core_public_health"],
        "likely_emergency_public_health": scope_flags["likely_emergency_public_health"],
        "likely_federal_health_transfer": scope_flags["likely_federal_health_transfer"],
        "likely_procurement_support": scope_flags["likely_procurement_support"],
        "likely_other_public_health": scope_flags["likely_other_public_health"],
        "likely_biomedical_research": scope_flags["likely_biomedical_research"],
        "likely_international_health_assistance": scope_flags["likely_international_health_assistance"],
        "likely_special_transfer": likely_special_transfer,
        "likely_regular_assistance": likely_regular_assistance,
        "likely_emergency_related": summary["effective_funding_scope"] == FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH,
        "likely_arpa_related": summary["effective_funding_stream"] == STREAM_ARPA,
        "decision_context": decision_context,
        "matched_rule_id": decision["matched_rule_id"],
        "methodology_version": METHODOLOGY_VERSION,
        "refreshed_at": datetime.now(timezone.utc),
    }


def classify_contract_row(
    source_row: dict[str, Any],
    account_rows: list[dict[str, Any]],
    *,
    rules: list[dict[str, Any]],
) -> dict[str, Any]:
    contract_classification = classify_contract_record(source_row)
    contract_category_guess = contract_classification["contract_category_guess"]
    descriptor_blob = " ".join(
        token
        for token in (
            _normalize_lower(source_row.get("award_description")),
            _normalize_lower(source_row.get("product_or_service_code_description")),
            _normalize_lower(source_row.get("naics_description")),
        )
        if token
    )
    force_procurement = contract_category_guess == CATEGORY_LIKELY_VFC
    rollup = summarize_account_rows(
        account_rows,
        fallback_federal_account_symbol=source_row.get("raw_federal_account_symbol"),
        fallback_treasury_account_symbol=source_row.get("raw_treasury_account_symbol"),
        appropriation_type=source_row.get("appropriation_type"),
        disaster_emergency_fund_code=source_row.get("disaster_emergency_fund_code"),
        descriptor_blob=descriptor_blob,
        force_procurement=force_procurement,
    )
    if force_procurement:
        rollup["effective_funding_stream"] = STREAM_PROCUREMENT
        rollup["effective_funding_scope"] = FUNDING_SCOPE_PROCUREMENT_SUPPORT
        rollup["effective_scope_guess"] = funding_scope_to_legacy_scope_guess(FUNDING_SCOPE_PROCUREMENT_SUPPORT)
        rollup["likely_procurement_support"] = True
    elif contract_category_guess in {CATEGORY_ADMIN, CATEGORY_IT, CATEGORY_RESEARCH, CATEGORY_LAB, CATEGORY_OTHER}:
        rollup["effective_funding_stream"] = STREAM_PROCUREMENT
        rollup["effective_funding_scope"] = FUNDING_SCOPE_PROCUREMENT_SUPPORT
        rollup["effective_scope_guess"] = funding_scope_to_legacy_scope_guess(FUNDING_SCOPE_PROCUREMENT_SUPPORT)
        rollup["likely_procurement_support"] = True
    awarding_agency_is_cdc = _is_cdc_agency(
        source_row.get("awarding_agency_name"),
        source_row.get("funding_agency_name"),
    )
    likely_domestic = _is_domestic(
        state_code=source_row.get("state_code"),
        recipient_country_name=source_row.get("recipient_country_name"),
    )
    likely_vfc_related = bool(rollup["likely_vfc_related"]) or contract_category_guess == CATEGORY_LIKELY_VFC
    scope_flags = funding_scope_indicator_flags(rollup["effective_funding_scope"])
    likely_immunization_related = contract_category_guess in {CATEGORY_LIKELY_VFC, CATEGORY_IMMUNIZATION}
    likely_profile_relevant_contract = likely_vfc_related or (
        likely_immunization_related and rollup["federal_account_profile_relevant"] is True
    )
    if rollup["multi_account_interpretation"] == "unknown_mixed":
        decision_context = "cdc_domestic_unknown_mixed_review"
    elif rollup["multi_account_interpretation"] == "mixed_core_emergency":
        decision_context = "cdc_domestic_mixed_core_emergency_conservative"
    elif rollup["multi_account_interpretation"] == "mixed_program_support":
        decision_context = "cdc_domestic_mixed_program_support_conservative"
    elif rollup["multi_account_interpretation"] == "mixed_program_transfer":
        decision_context = "cdc_domestic_mixed_program_transfer_conservative"
    elif rollup["multi_account_interpretation"] == "mixed_emergency_support":
        decision_context = "cdc_domestic_mixed_emergency_support_conservative"
    elif rollup["multi_account_interpretation"] == "research_mixed":
        decision_context = "cdc_domestic_mixed_research_conservative"
    elif rollup["multi_account_interpretation"] == "international_mixed":
        decision_context = "international_mixed_conservative"
    elif rollup["multi_account_interpretation"] == "special_transfer_mixed":
        decision_context = "cdc_domestic_special_transfer_mixed_uncertain"
    elif rollup["effective_funding_scope"] == FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE:
        decision_context = "international_health_assistance_excluded"
    elif likely_domestic is False:
        decision_context = "non_domestic"
    elif rollup["effective_funding_scope"] == FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER:
        decision_context = "cdc_domestic_federal_health_transfer_excluded"
    elif rollup["effective_funding_scope"] == FUNDING_SCOPE_OTHER_PUBLIC_HEALTH:
        decision_context = "cdc_domestic_other_public_health_excluded"
    elif rollup["effective_funding_scope"] == FUNDING_SCOPE_BIOMEDICAL_RESEARCH:
        decision_context = "cdc_domestic_biomedical_research_excluded"
    elif likely_vfc_related:
        decision_context = "cdc_domestic_procurement_vfc_relevant"
    elif rollup["effective_funding_scope"] == FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH:
        decision_context = "cdc_domestic_emergency_public_health_conditional"
    elif rollup["effective_funding_scope"] == FUNDING_SCOPE_SPECIAL_TRANSFER:
        decision_context = "cdc_domestic_special_transfer_uncertain"
    elif rollup["effective_funding_scope"] == FUNDING_SCOPE_PROCUREMENT_SUPPORT:
        decision_context = "cdc_domestic_procurement_support_excluded"
    elif not awarding_agency_is_cdc:
        decision_context = "non_cdc_agency"
    else:
        decision_context = (
            f"cdc_{'domestic' if likely_domestic is True else 'unknown_domestic'}_"
            f"{contract_category_guess}_{_account_bucket(rollup['federal_account_profile_relevant'])}"
        )

    candidate_row = {
        "source_system": SOURCE_CONTRACTS,
        "decision_context": decision_context,
        "contract_category_guess": contract_category_guess,
        "award_description": source_row.get("award_description"),
        "effective_funding_stream": rollup["effective_funding_stream"],
        "funding_scope_method": rollup["funding_scope_method"],
        "effective_funding_scope": rollup["effective_funding_scope"],
        "federal_account_profile_relevant": rollup["federal_account_profile_relevant"],
        "federal_account_count": rollup["federal_account_count"],
        "federal_account_combination_key": rollup["federal_account_combination_key"],
        "has_mixed_scopes": rollup["has_mixed_scopes"],
        "account_structure_type": rollup["account_structure_type"],
        "multi_account_interpretation": rollup["multi_account_interpretation"],
        "conservative_inclusion_reason": rollup["conservative_inclusion_reason"],
        "manual_review_recommended": rollup["manual_review_recommended"],
        "likely_core_public_health": scope_flags["likely_core_public_health"],
        "likely_emergency_public_health": scope_flags["likely_emergency_public_health"],
        "likely_federal_health_transfer": scope_flags["likely_federal_health_transfer"],
        "likely_procurement_support": scope_flags["likely_procurement_support"],
        "likely_other_public_health": scope_flags["likely_other_public_health"],
        "likely_biomedical_research": scope_flags["likely_biomedical_research"],
        "likely_international_health_assistance": scope_flags["likely_international_health_assistance"],
        "likely_vfc_related": likely_vfc_related,
        "likely_immunization_related": likely_immunization_related,
        "likely_emergency_related": rollup["likely_emergency_related"],
        "likely_domestic": likely_domestic,
    }
    default_decision = contract_default_decision(
        {
            **candidate_row,
            "awarding_agency_is_cdc": awarding_agency_is_cdc,
        }
    )
    matched_rule = first_matching_rule(candidate_row, rules)
    decision = _apply_rule_override(
        default_include=default_decision["include_in_profile_scope"],
        default_weight=default_decision["inclusion_weight"],
        default_reason=default_decision["reason"],
        default_confidence_label=default_decision["confidence_label"],
        matched_rule=matched_rule,
    )

    return {
        "source_transaction_id": str(source_row["source_transaction_id"]),
        "source_system": SOURCE_CONTRACTS,
        "fiscal_year": source_row.get("fiscal_year"),
        "state_code": _normalize_text(source_row.get("state_code")),
        "recipient_name": _normalize_text(source_row.get("recipient_name")),
        "recipient_country_name": _normalize_text(source_row.get("recipient_country_name")),
        "awarding_agency_name": _normalize_text(source_row.get("awarding_agency_name")),
        "funding_agency_name": _normalize_text(source_row.get("funding_agency_name")),
        "federal_account_symbol": rollup["federal_account_symbol"],
        "treasury_account_symbol": rollup["treasury_account_symbol"],
        "appropriation_type": _normalize_text(source_row.get("appropriation_type")),
        "disaster_emergency_fund_code": _normalize_text(source_row.get("disaster_emergency_fund_code")),
        "award_description": _normalize_text(source_row.get("award_description")),
        "product_or_service_code": _normalize_text(source_row.get("product_or_service_code")),
        "transaction_obligated_amount": _quantize_money(_to_decimal(source_row.get("transaction_obligated_amount"))),
        "contract_category_guess": contract_category_guess,
        "likely_profile_relevant_contract": likely_profile_relevant_contract,
        "effective_funding_stream": rollup["effective_funding_stream"],
        "funding_scope_method": rollup["funding_scope_method"],
        "effective_funding_scope": rollup["effective_funding_scope"],
        "effective_scope_guess": rollup["effective_scope_guess"],
        "federal_account_profile_relevant": rollup["federal_account_profile_relevant"],
        "federal_account_count": rollup["federal_account_count"],
        "federal_account_combination_key": rollup["federal_account_combination_key"],
        "federal_account_titles_combined": rollup["federal_account_titles_combined"],
        "component_account_scopes": rollup["component_account_scopes"],
        "component_scope_count": rollup["component_scope_count"],
        "has_mixed_scopes": rollup["has_mixed_scopes"],
        "account_structure_type": rollup["account_structure_type"],
        "multi_account_interpretation": rollup["multi_account_interpretation"],
        "conservative_inclusion_reason": rollup["conservative_inclusion_reason"],
        "manual_review_recommended": rollup["manual_review_recommended"],
        "mixed_scope_contains_core": rollup["mixed_scope_contains_core"],
        "mixed_scope_contains_emergency": rollup["mixed_scope_contains_emergency"],
        "mixed_scope_contains_transfer": rollup["mixed_scope_contains_transfer"],
        "mixed_scope_contains_procurement": rollup["mixed_scope_contains_procurement"],
        "mixed_scope_contains_research": rollup["mixed_scope_contains_research"],
        "mixed_scope_contains_international": rollup["mixed_scope_contains_international"],
        "mixed_scope_contains_special_transfer": rollup["mixed_scope_contains_special_transfer"],
        "mixed_scope_contains_unknown": rollup["mixed_scope_contains_unknown"],
        "include_in_profile_scope": decision["include_in_profile_scope"],
        "inclusion_weight": decision["inclusion_weight"],
        "inclusion_reason": decision["inclusion_reason"],
        "exclusion_reason": decision["exclusion_reason"],
        "confidence_label": decision["confidence_label"],
        "likely_core_public_health": scope_flags["likely_core_public_health"],
        "likely_emergency_public_health": scope_flags["likely_emergency_public_health"],
        "likely_federal_health_transfer": scope_flags["likely_federal_health_transfer"],
        "likely_procurement_support": scope_flags["likely_procurement_support"],
        "likely_other_public_health": scope_flags["likely_other_public_health"],
        "likely_biomedical_research": scope_flags["likely_biomedical_research"],
        "likely_international_health_assistance": scope_flags["likely_international_health_assistance"],
        "likely_vfc_related": likely_vfc_related,
        "likely_immunization_related": likely_immunization_related,
        "likely_emergency_related": rollup["likely_emergency_related"],
        "decision_context": decision_context,
        "matched_rule_id": decision["matched_rule_id"],
        "methodology_version": METHODOLOGY_VERSION,
        "refreshed_at": datetime.now(timezone.utc),
    }


def build_profile_scope_transaction_rows(
    assistance_rows: list[dict[str, Any]],
    contract_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    combined_rows: list[dict[str, Any]] = []
    for row in [*assistance_rows, *contract_rows]:
        raw_amount = _quantize_money(_to_decimal(row.get("transaction_obligated_amount")))
        include_in_profile_scope = row.get("include_in_profile_scope")
        inclusion_weight = row.get("inclusion_weight")
        normalized_amount = Decimal("0.00")
        if include_in_profile_scope is True and inclusion_weight is not None and raw_amount is not None:
            normalized_amount = _quantize_money(raw_amount * inclusion_weight) or Decimal("0.00")
        combined_rows.append(
            {
                "source_system": row["source_system"],
                "source_transaction_id": row["source_transaction_id"],
                "fiscal_year": row.get("fiscal_year"),
                "state_code": row.get("state_code"),
                "recipient_name": row.get("recipient_name"),
                "federal_account_symbol": row.get("federal_account_symbol"),
                "effective_funding_stream": row.get("effective_funding_stream"),
                "funding_scope_method": row.get("funding_scope_method"),
                "effective_funding_scope": row.get("effective_funding_scope"),
                "federal_account_count": row.get("federal_account_count"),
                "federal_account_combination_key": row.get("federal_account_combination_key"),
                "federal_account_titles_combined": row.get("federal_account_titles_combined"),
                "component_account_scopes": row.get("component_account_scopes"),
                "component_scope_count": row.get("component_scope_count"),
                "has_mixed_scopes": row.get("has_mixed_scopes"),
                "account_structure_type": row.get("account_structure_type"),
                "multi_account_interpretation": row.get("multi_account_interpretation"),
                "conservative_inclusion_reason": row.get("conservative_inclusion_reason"),
                "manual_review_recommended": row.get("manual_review_recommended"),
                "mixed_scope_contains_core": row.get("mixed_scope_contains_core"),
                "mixed_scope_contains_emergency": row.get("mixed_scope_contains_emergency"),
                "mixed_scope_contains_transfer": row.get("mixed_scope_contains_transfer"),
                "mixed_scope_contains_procurement": row.get("mixed_scope_contains_procurement"),
                "mixed_scope_contains_research": row.get("mixed_scope_contains_research"),
                "mixed_scope_contains_international": row.get("mixed_scope_contains_international"),
                "mixed_scope_contains_special_transfer": row.get("mixed_scope_contains_special_transfer"),
                "mixed_scope_contains_unknown": row.get("mixed_scope_contains_unknown"),
                "include_in_profile_scope": include_in_profile_scope,
                "inclusion_weight": inclusion_weight,
                "inclusion_reason": row.get("inclusion_reason") or row.get("exclusion_reason"),
                "confidence_label": row.get("confidence_label"),
                "raw_amount": raw_amount,
                "normalized_profile_scope_amount": normalized_amount,
                "methodology_version": row.get("methodology_version") or METHODOLOGY_VERSION,
                "refreshed_at": datetime.now(timezone.utc),
            }
        )
    return combined_rows


def build_state_year_summary_rows(profile_scope_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    accumulators: dict[tuple[str, int, str], dict[str, Any]] = {}
    for row in profile_scope_rows:
        fiscal_year = row.get("fiscal_year")
        state_code = _normalize_text(row.get("state_code"))
        source_system = _normalize_text(row.get("source_system"))
        if fiscal_year is None or state_code is None or source_system is None:
            continue
        key = (source_system, int(fiscal_year), state_code)
        accumulator = accumulators.setdefault(
            key,
            {
                "source_system": source_system,
                "fiscal_year": int(fiscal_year),
                "state_code": state_code,
                "raw_amount": Decimal("0.00"),
                "profile_scope_amount": Decimal("0.00"),
                "core_public_health_amount": Decimal("0.00"),
                "emergency_public_health_amount": Decimal("0.00"),
                "federal_health_transfer_amount": Decimal("0.00"),
                "procurement_support_scope_amount": Decimal("0.00"),
                "special_transfer_amount": Decimal("0.00"),
                "other_public_health_amount": Decimal("0.00"),
                "biomedical_research_amount": Decimal("0.00"),
                "international_health_assistance_amount": Decimal("0.00"),
                "unknown_funding_scope_amount": Decimal("0.00"),
                "transaction_count": 0,
                "included_transaction_count": 0,
                "methodology_version": METHODOLOGY_VERSION,
                "refreshed_at": datetime.now(timezone.utc),
            },
        )
        accumulator["raw_amount"] += _to_decimal(row.get("raw_amount"))
        accumulator["profile_scope_amount"] += _to_decimal(row.get("normalized_profile_scope_amount"))
        accumulator["transaction_count"] += 1
        scope_token = normalize_funding_scope(row.get("effective_funding_scope")) or FUNDING_SCOPE_UNKNOWN
        scope_field = {
            FUNDING_SCOPE_CORE_PUBLIC_HEALTH: "core_public_health_amount",
            FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH: "emergency_public_health_amount",
            FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER: "federal_health_transfer_amount",
            FUNDING_SCOPE_PROCUREMENT_SUPPORT: "procurement_support_scope_amount",
            FUNDING_SCOPE_SPECIAL_TRANSFER: "special_transfer_amount",
            FUNDING_SCOPE_OTHER_PUBLIC_HEALTH: "other_public_health_amount",
            FUNDING_SCOPE_BIOMEDICAL_RESEARCH: "biomedical_research_amount",
            FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE: "international_health_assistance_amount",
            FUNDING_SCOPE_UNKNOWN: "unknown_funding_scope_amount",
        }[scope_token]
        accumulator[scope_field] += _to_decimal(row.get("normalized_profile_scope_amount"))
        if row.get("include_in_profile_scope") is True:
            accumulator["included_transaction_count"] += 1

    rows = list(accumulators.values())
    for row in rows:
        row["raw_amount"] = _quantize_money(row["raw_amount"])
        row["profile_scope_amount"] = _quantize_money(row["profile_scope_amount"])
        row["core_public_health_amount"] = _quantize_money(row["core_public_health_amount"])
        row["emergency_public_health_amount"] = _quantize_money(row["emergency_public_health_amount"])
        row["federal_health_transfer_amount"] = _quantize_money(row["federal_health_transfer_amount"])
        row["procurement_support_scope_amount"] = _quantize_money(row["procurement_support_scope_amount"])
        row["special_transfer_amount"] = _quantize_money(row["special_transfer_amount"])
        row["other_public_health_amount"] = _quantize_money(row["other_public_health_amount"])
        row["biomedical_research_amount"] = _quantize_money(row["biomedical_research_amount"])
        row["international_health_assistance_amount"] = _quantize_money(
            row["international_health_assistance_amount"]
        )
        row["unknown_funding_scope_amount"] = _quantize_money(row["unknown_funding_scope_amount"])
    rows.sort(key=lambda item: (item["source_system"], item["fiscal_year"], item["state_code"]))
    return rows


def _sum_bucket_amount(rows: list[dict[str, Any]], *, include_value: bool | None, amount_field: str) -> Decimal:
    total = Decimal("0.00")
    for row in rows:
        if row.get("include_in_profile_scope") is include_value:
            total += _to_decimal(row.get(amount_field))
    return _quantize_money(total) or Decimal("0.00")


def _group_amounts(
    rows: list[dict[str, Any]],
    *,
    key_field: str,
    amount_field: str,
) -> list[dict[str, Any]]:
    totals: dict[Any, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for row in rows:
        key = row.get(key_field)
        if key is None:
            continue
        totals[key] += _to_decimal(row.get(amount_field))
    return [
        {
            key_field: key,
            amount_field: _quantize_money(amount) or Decimal("0.00"),
        }
        for key, amount in sorted(totals.items(), key=lambda item: item[0])
    ]


def _group_counts(
    rows: list[dict[str, Any]],
    *,
    key_field: str,
) -> list[dict[str, Any]]:
    totals: dict[Any, int] = defaultdict(int)
    for row in rows:
        key = row.get(key_field)
        if key is None:
            continue
        totals[key] += 1
    return [
        {
            key_field: key,
            "row_count": count,
        }
        for key, count in sorted(totals.items(), key=lambda item: item[0])
    ]


def _top_federal_accounts(
    rows: list[dict[str, Any]],
    *,
    include_value: bool,
) -> list[dict[str, Any]]:
    totals: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if row.get("include_in_profile_scope") is not include_value:
            continue
        symbol = _normalize_text(row.get("federal_account_symbol"))
        if symbol is None:
            continue
        key = (str(row.get("source_system")), symbol)
        accumulator = totals.setdefault(
            key,
            {
                "source_system": row.get("source_system"),
                "federal_account_symbol": symbol,
                "transaction_count": 0,
                "raw_amount": Decimal("0.00"),
            },
        )
        accumulator["transaction_count"] += 1
        accumulator["raw_amount"] += _to_decimal(row.get("transaction_obligated_amount"))
    ranked = sorted(
        totals.values(),
        key=lambda item: (item["raw_amount"], item["transaction_count"]),
        reverse=True,
    )
    return [
        {
            **item,
            "raw_amount": _quantize_money(item["raw_amount"]),
        }
        for item in ranked[:10]
    ]


def build_summary(
    *,
    assistance_rows: list[dict[str, Any]],
    contract_rows: list[dict[str, Any]],
    profile_scope_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    combined_enriched_rows = [*assistance_rows, *contract_rows]
    funding_scope_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    funding_scope_year_totals: dict[tuple[int, str], Decimal] = defaultdict(lambda: Decimal("0.00"))
    for row in profile_scope_rows:
        scope_token = normalize_funding_scope(row.get("effective_funding_scope")) or FUNDING_SCOPE_UNKNOWN
        amount = _to_decimal(row.get("normalized_profile_scope_amount"))
        funding_scope_totals[scope_token] += amount
        fiscal_year = row.get("fiscal_year")
        if fiscal_year is not None:
            funding_scope_year_totals[(int(fiscal_year), scope_token)] += amount
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology_version": METHODOLOGY_VERSION,
        "total_assistance_rows_evaluated": len(assistance_rows),
        "total_contract_rows_evaluated": len(contract_rows),
        "included_assistance_total": _sum_bucket_amount(
            [
                row
                for row in profile_scope_rows
                if row.get("source_system") == SOURCE_ASSISTANCE
            ],
            include_value=True,
            amount_field="normalized_profile_scope_amount",
        ),
        "included_contract_total": _sum_bucket_amount(
            [
                row
                for row in profile_scope_rows
                if row.get("source_system") == SOURCE_CONTRACTS
            ],
            include_value=True,
            amount_field="normalized_profile_scope_amount",
        ),
        "excluded_assistance_total": _sum_bucket_amount(assistance_rows, include_value=False, amount_field="transaction_obligated_amount"),
        "excluded_contract_total": _sum_bucket_amount(contract_rows, include_value=False, amount_field="transaction_obligated_amount"),
        "uncertain_assistance_total": _sum_bucket_amount(assistance_rows, include_value=None, amount_field="transaction_obligated_amount"),
        "uncertain_contract_total": _sum_bucket_amount(contract_rows, include_value=None, amount_field="transaction_obligated_amount"),
        "top_federal_accounts_included": _top_federal_accounts(combined_enriched_rows, include_value=True),
        "top_federal_accounts_excluded": _top_federal_accounts(combined_enriched_rows, include_value=False),
        "total_profile_scope_amount_by_fiscal_year": _group_amounts(
            profile_scope_rows,
            key_field="fiscal_year",
            amount_field="normalized_profile_scope_amount",
        ),
        "total_profile_scope_amount_by_state": _group_amounts(
            profile_scope_rows,
            key_field="state_code",
            amount_field="normalized_profile_scope_amount",
        ),
        "total_profile_scope_amount_by_source_system": _group_amounts(
            profile_scope_rows,
            key_field="source_system",
            amount_field="normalized_profile_scope_amount",
        ),
        "row_count_by_account_structure_type": _group_counts(
            combined_enriched_rows,
            key_field="account_structure_type",
        ),
        "raw_amount_by_account_structure_type": _group_amounts(
            combined_enriched_rows,
            key_field="account_structure_type",
            amount_field="transaction_obligated_amount",
        ),
        "included_profile_scope_amount_by_account_structure_type": _group_amounts(
            profile_scope_rows,
            key_field="account_structure_type",
            amount_field="normalized_profile_scope_amount",
        ),
        "row_count_by_multi_account_interpretation": _group_counts(
            combined_enriched_rows,
            key_field="multi_account_interpretation",
        ),
        "raw_amount_by_multi_account_interpretation": _group_amounts(
            combined_enriched_rows,
            key_field="multi_account_interpretation",
            amount_field="transaction_obligated_amount",
        ),
        "manual_review_recommended_row_count": sum(
            1 for row in combined_enriched_rows if bool(row.get("manual_review_recommended"))
        ),
        "manual_review_recommended_raw_amount": _quantize_money(
            sum(
                (_to_decimal(row.get("transaction_obligated_amount")) for row in combined_enriched_rows if bool(row.get("manual_review_recommended"))),
                Decimal("0.00"),
            )
        ),
        "included_profile_scope_amount_by_funding_scope": [
            {
                "effective_funding_scope": scope_name,
                "normalized_profile_scope_amount": _quantize_money(total) or Decimal("0.00"),
            }
            for scope_name, total in sorted(funding_scope_totals.items())
        ],
        "included_profile_scope_amount_by_funding_scope_and_year": [
            {
                "fiscal_year": fiscal_year,
                "effective_funding_scope": scope_name,
                "normalized_profile_scope_amount": _quantize_money(total) or Decimal("0.00"),
            }
            for (fiscal_year, scope_name), total in sorted(funding_scope_year_totals.items())
        ],
    }


def write_summary_file(path: str | Path, summary: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(_serialize_json_value(summary), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _insert_rows(connection: Any, table: Any, rows: list[dict[str, Any]], *, chunk_size: int = 5000) -> None:
    if not rows:
        return
    for start in range(0, len(rows), chunk_size):
        connection.execute(table.insert(), rows[start : start + chunk_size])


def rebuild(
    *,
    db_url: str,
    rules_path: str | Path = DEFAULT_RULES_CSV_PATH,
    summary_path: str | Path = DEFAULT_SUMMARY_PATH,
    multi_account_summary_path: str | Path = DEFAULT_MULTI_ACCOUNT_SUMMARY_PATH,
    truncate: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    seed_rules = load_rule_seed_rows(rules_path)
    engine = create_engine(db_url, pool_pre_ping=True)
    with engine.begin() as connection:
        _require_tables(
            connection,
            [
                FEDERAL_ACCOUNT_LOOKUP_FQTN,
                ASSISTANCE_ACCOUNTS_FQTN,
                ASSISTANCE_ACCOUNT_SUMMARY_FQTN,
                CONTRACT_ACCOUNTS_FQTN,
                ASSISTANCE_SOURCE_FQTN,
                CONTRACT_SOURCE_FQTN,
                PROFILE_SCOPE_RULES_FQTN,
                ASSISTANCE_PROFILE_FQTN,
                CONTRACT_PROFILE_FQTN,
                PROFILE_SCOPE_TX_FQTN,
                STATE_YEAR_SUMMARY_FQTN,
            ],
        )

        if not dry_run:
            bootstrap_profile_scope_rules(connection, seed_rules)

        active_rules = (
            fetch_active_profile_scope_rules(connection)
            if _rule_count(connection) > 0
            else seed_rules
        )

        refresh_assistance_transaction_accounts(connection, dry_run=dry_run)
        refresh_assistance_transaction_account_summary(connection, dry_run=dry_run)

        assistance_source_rows = _fetch_assistance_source_rows(connection)
        contract_source_rows = _fetch_contract_source_rows(connection)
        assistance_account_summaries = (
            {
                str(row["source_transaction_id"]): row
                for row in build_assistance_transaction_account_summary_rows_from_connection(connection)
            }
            if dry_run
            else _fetch_assistance_account_summary_map(connection)
        )
        contract_account_rows = _fetch_account_rows(connection, source_system=SOURCE_CONTRACTS)

        assistance_rows = [
            classify_assistance_row(
                source_row,
                assistance_account_summaries.get(str(source_row["source_transaction_id"])),
                rules=active_rules,
            )
            for source_row in assistance_source_rows
        ]
        contract_rows = [
            classify_contract_row(
                source_row,
                contract_account_rows.get(str(source_row["source_transaction_id"]), []),
                rules=active_rules,
            )
            for source_row in contract_source_rows
        ]
        profile_scope_rows = build_profile_scope_transaction_rows(assistance_rows, contract_rows)
        state_year_rows = build_state_year_summary_rows(profile_scope_rows)
        summary = build_summary(
            assistance_rows=assistance_rows,
            contract_rows=contract_rows,
            profile_scope_rows=profile_scope_rows,
        )
        summary.update(
            {
                "profile_scope_rule_count_used": len(active_rules),
                "assistance_profile_rows_written": len(assistance_rows),
                "contract_profile_rows_written": len(contract_rows),
                "profile_scope_transaction_rows_written": len(profile_scope_rows),
                "profile_scope_state_year_rows_written": len(state_year_rows),
            }
        )

        if dry_run:
            return summary

        if truncate:
            connection.execute(text(f"TRUNCATE TABLE {STATE_YEAR_SUMMARY_FQTN} RESTART IDENTITY"))
            connection.execute(text(f"TRUNCATE TABLE {PROFILE_SCOPE_TX_FQTN}"))
            connection.execute(text(f"TRUNCATE TABLE {CONTRACT_PROFILE_FQTN}"))
            connection.execute(text(f"TRUNCATE TABLE {ASSISTANCE_PROFILE_FQTN}"))

        _insert_rows(connection, ASSISTANCE_PROFILE_TABLE, assistance_rows)
        _insert_rows(connection, CONTRACT_PROFILE_TABLE, contract_rows)
        _insert_rows(connection, PROFILE_SCOPE_TABLE, profile_scope_rows)
        _insert_rows(connection, STATE_YEAR_SUMMARY_TABLE, state_year_rows)
        write_summary_file(summary_path, summary)
        write_summary_file(multi_account_summary_path, summary)
        return summary


def print_summary(summary: dict[str, Any]) -> None:
    print(json.dumps(_serialize_json_value(summary), indent=2, sort_keys=True))


def main() -> None:
    args = parse_args()
    summary = rebuild(
        db_url=args.db_url,
        rules_path=args.rules_path,
        summary_path=args.summary_path,
        truncate=args.truncate,
        dry_run=args.dry_run,
    )
    if args.verbose or args.dry_run:
        print_summary(summary)


if __name__ == "__main__":
    main()
