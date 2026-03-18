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

from app.recon.assistance_accounts import (
    build_assistance_transaction_account_rows,
    fetch_assistance_source_rows,
    refresh_assistance_transaction_account_summary,
    refresh_assistance_transaction_accounts,
)
from app.db import DEFAULT_DB_URL
from app.db_fqtn import recon_table
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
    funding_stream_from_scope,
    normalize_funding_scope,
)
from app.recon.models import (
    FederalAccountClassificationRule,
    FederalAccountLookup,
    FederalAccountObservation,
)
from app.usaspending.ingest import CATEGORY_LIKELY_VFC, classify_contract_record

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REVIEW_CSV_PATH = REPO_ROOT / "data" / "usaspending" / "review" / "federal_account_review.csv"
DEFAULT_RULES_CSV_PATH = REPO_ROOT / "data" / "recon" / "federal_account_classification_rules.csv"
DEFAULT_VERIFIED_RULES_CSV_PATH = REPO_ROOT / "data" / "recon" / "federal_account_classification_verified.csv"
DEFAULT_VERIFIED_SUMMARY_PATH = REPO_ROOT / "data" / "recon" / "verified_account_mapping_summary.json"
DEFAULT_FALLBACK_VERIFICATION_SUMMARY_PATH = REPO_ROOT / "data" / "recon" / "fallback_account_verification_summary.json"
DEFAULT_METADATA_FILENAMES = (
    "federal_account_metadata.csv",
    "federal_account_lookup.csv",
    "treasury_account_metadata.csv",
    "treasury_account_lookup.csv",
)

SOURCE_CONTRACTS = "contracts"
SOURCE_ASSISTANCE = "assistance"

FUNDING_STREAM_REGULAR = "regular_appropriation"
FUNDING_STREAM_COVID = "covid_emergency"
FUNDING_STREAM_ARPA = "arpa"
FUNDING_STREAM_OTHER_EMERGENCY = "other_emergency_or_disaster"
FUNDING_STREAM_TRANSFER_SPECIAL = "transfer_or_special"
FUNDING_STREAM_PROCUREMENT = "procurement_support"
FUNDING_STREAM_UNKNOWN = "unknown"

SCOPE_CORE_CDC = "likely_core_cdc"
SCOPE_SPECIAL_TRANSFER = "likely_special_transfer"
SCOPE_EMERGENCY = "likely_emergency_supplemental"
SCOPE_PROCUREMENT = "likely_procurement_only"
SCOPE_UNCERTAIN = "uncertain"

NULL_TOKENS = {"", "na", "n/a", "none", "null", "nan"}
SYMBOL_RE = re.compile(
    r"^(?P<agency_identifier>\d{3})-(?P<main_account_code>[A-Za-z0-9]{4})(?:-(?P<sub_account_code>[A-Za-z0-9]{3}))?$"
)
NON_WORD_RE = re.compile(r"[^a-z0-9]+")
RULE_TRUE_TOKENS = {"1", "true", "t", "yes", "y"}
LOOKUP_TABLE = FederalAccountLookup.__table__
OBSERVATION_TABLE = FederalAccountObservation.__table__
RULE_TABLE = FederalAccountClassificationRule.__table__
CONTRACT_ACCOUNTS_VIEW = recon_table("contract_transaction_accounts")
ASSISTANCE_ACCOUNTS_VIEW = recon_table("assistance_transaction_accounts")
LOOKUP_FQTN = recon_table("federal_account_lookup")
OBSERVATION_FQTN = recon_table("federal_account_observations")
RULE_FQTN = recon_table("federal_account_classification_rules")

MANUAL_OVERRIDE_FIELDS = (
    "manual_funding_stream",
    "manual_funding_scope",
    "manual_scope_guess",
    "manual_profile_relevant",
)
REVIEW_EXPORT_FIELDS = (
    "federal_account_symbol",
    "account_title",
    "observed_in_contracts",
    "observed_in_assistance",
    "first_fiscal_year",
    "last_fiscal_year",
    "observed_total_obligations",
    "funding_stream_guess",
    "funding_scope_guess",
    "effective_funding_scope",
    "funding_scope_method",
    "appropriations_scope_guess",
    "likely_profile_relevant",
    "likely_core_public_health",
    "likely_emergency_public_health",
    "likely_federal_health_transfer",
    "likely_procurement_support",
    "likely_other_public_health",
    "likely_biomedical_research",
    "likely_international_health_assistance",
    "likely_vfc_related",
    "likely_emergency_related",
    "likely_arpa_related",
    "likely_regular_appropriation",
    "classification_confidence",
    "classification_method",
    "is_manually_verified",
)

VERIFIED_CLASSIFICATION_PREFIX = "verified_csv"
VERIFIED_EFFECTIVE_METHOD = "verified_csv"
VERIFIED_PRIORITY_OFFSET = 10000
KNOWN_FORMER_FALLBACK_ACCOUNTS = (
    "075-0125",
    "075-0961",
    "075-0844",
    "075-8514",
    "075-0131",
    "075-1362",
    "075-0843",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the observed federal account lookup and classification layer for CHIP.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or the local development DSN).",
    )
    parser.add_argument(
        "--reseed-from-observed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Seed/update the federal account lookup from currently observed contract and assistance symbols.",
    )
    parser.add_argument(
        "--rebuild-observations",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Rebuild per-source, per-year account observations.",
    )
    parser.add_argument(
        "--rebuild-classification",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Refresh deterministic account classification rules and effective classification fields.",
    )
    parser.add_argument(
        "--export-review-csv",
        action="store_true",
        help="Export the review CSV to data/usaspending/review/federal_account_review.csv by default.",
    )
    parser.add_argument(
        "--review-csv-path",
        default=None,
        help="Optional explicit path for the review CSV export.",
    )
    parser.add_argument(
        "--account-metadata-path",
        default=None,
        help="Optional CSV containing account metadata keyed by federal account symbol.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute lookup, observation, classification, and review payloads without writing database rows.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print a JSON-like summary of the rebuild inputs and outputs.",
    )
    return parser.parse_args()


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).replace("\ufeff", "").strip()
    token = re.sub(r"\s+", " ", token)
    if token.lower() in NULL_TOKENS:
        return None
    return token or None


def _normalize_lower(value: Any) -> str:
    token = _normalize_text(value)
    return token.lower() if token else ""


def _normalize_key(value: Any) -> str:
    token = _normalize_lower(value)
    return NON_WORD_RE.sub("_", token).strip("_")


def _normalize_account_title(value: Any) -> str | None:
    token = _normalize_lower(value)
    if not token:
        return None
    normalized = NON_WORD_RE.sub(" ", token).strip()
    return normalized or None


def _as_decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _quantize_money(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal("0.01"))


def _quantize_ratio(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal("0.01"))


def _decimal_ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return Decimal("0")
    return numerator / denominator


def _to_bool_or_none(value: Any) -> bool | None:
    token = _normalize_lower(value)
    if not token:
        return None
    if token in RULE_TRUE_TOKENS:
        return True
    if token in {"0", "false", "f", "no", "n"}:
        return False
    return None


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


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


def split_account_symbols(value: Any) -> list[str]:
    token = _normalize_text(value)
    if token is None:
        return []
    seen: set[str] = set()
    symbols: list[str] = []
    for raw_symbol in re.split(r"\s*[;,|]\s*", token):
        normalized = _normalize_text(raw_symbol)
        if normalized is None:
            continue
        canonical = normalized.upper()
        if canonical in seen:
            continue
        seen.add(canonical)
        symbols.append(canonical)
    return symbols


def parse_federal_account_symbol(symbol: str | None) -> dict[str, str | None]:
    token = _normalize_text(symbol)
    if token is None:
        return {
            "agency_identifier": None,
            "main_account_code": None,
            "sub_account_code": None,
        }
    match = SYMBOL_RE.fullmatch(token.upper())
    if match is None:
        return {
            "agency_identifier": None,
            "main_account_code": None,
            "sub_account_code": None,
        }
    return {
        "agency_identifier": match.group("agency_identifier"),
        "main_account_code": match.group("main_account_code"),
        "sub_account_code": match.group("sub_account_code"),
    }


def discover_account_metadata_path(
    repo_root: Path,
    *,
    explicit_path: str | None = None,
) -> Path | None:
    if explicit_path:
        path = Path(explicit_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Account metadata path does not exist: {path}")
        return path

    data_dir = repo_root / "data"
    for filename in DEFAULT_METADATA_FILENAMES:
        candidate = data_dir / filename
        if candidate.exists():
            return candidate.resolve()

    if not data_dir.exists():
        return None

    for candidate in sorted(data_dir.rglob("*account*.csv")):
        name = candidate.name.lower()
        if any(token in name for token in ("classification", "inclusion", "review", "rules")):
            continue
        return candidate.resolve()
    return None


def load_account_metadata_lookup(path: Path) -> dict[str, dict[str, str | None]]:
    lookup: dict[str, dict[str, str | None]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw_row in reader:
            row = {_normalize_key(key): _normalize_text(value) for key, value in (raw_row or {}).items() if key}
            agency_identifier = row.get("agency_identifier") or row.get("agency_id") or row.get("agency_code")
            main_account_code = (
                row.get("main_account_code")
                or row.get("main_account")
                or row.get("main_account_number")
                or row.get("account_code")
            )
            sub_account_code = row.get("sub_account_code") or row.get("sub_account")
            symbol = (
                row.get("federal_account_symbol")
                or row.get("federal_account")
                or row.get("account_symbol")
                or row.get("federal_account_identifier")
            )
            if symbol is None and agency_identifier and main_account_code:
                symbol = f"{agency_identifier}-{main_account_code}"
                if sub_account_code:
                    symbol = f"{symbol}-{sub_account_code}"
            canonical_symbols = split_account_symbols(symbol)
            if not canonical_symbols:
                continue
            account_title = (
                row.get("account_title")
                or row.get("account_name")
                or row.get("federal_account_name")
                or row.get("title")
                or row.get("main_account_name")
            )
            for federal_account_symbol in canonical_symbols:
                parsed = parse_federal_account_symbol(federal_account_symbol)
                lookup[federal_account_symbol] = {
                    "agency_identifier": agency_identifier or parsed["agency_identifier"],
                    "main_account_code": main_account_code or parsed["main_account_code"],
                    "sub_account_code": sub_account_code or parsed["sub_account_code"],
                    "account_title": account_title,
                }
    return lookup


def load_classification_rule_rows(path: Path = DEFAULT_RULES_CSV_PATH) -> list[dict[str, Any]]:
    verified_rows = load_verified_classification_rule_rows()
    verified_exact_symbols = {
        str(row["match_value"])
        for row in verified_rows
        if row.get("match_field") == "federal_account_symbol" and row.get("match_type") == "exact"
    }

    if not path.exists():
        if verified_rows:
            return verified_rows
        raise FileNotFoundError(f"Federal account classification rules CSV not found: {path}")

    rows: list[dict[str, Any]] = list(verified_rows)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw_row in reader:
            row = {_normalize_key(key): value for key, value in (raw_row or {}).items() if key}
            match_field = _normalize_text(row.get("match_field")) or ""
            match_type = _normalize_text(row.get("match_type")) or "exact"
            match_value = _normalize_text(row.get("match_value")) or ""
            if (
                match_field == "federal_account_symbol"
                and match_type == "exact"
                and match_value in verified_exact_symbols
            ):
                continue
            rows.append(
                {
                    "priority": int(_normalize_text(row.get("priority")) or "0") + VERIFIED_PRIORITY_OFFSET,
                    "match_field": match_field,
                    "match_type": match_type,
                    "match_value": match_value,
                    "assigned_funding_stream": _normalize_text(row.get("assigned_funding_stream")),
                    "assigned_funding_scope": normalize_funding_scope(row.get("assigned_funding_scope")),
                    "assigned_account_title": _normalize_text(row.get("assigned_account_title")),
                    "assigned_scope_guess": _normalize_text(row.get("assigned_scope_guess")),
                    "assigned_profile_relevant": _to_bool_or_none(row.get("assigned_profile_relevant")),
                    "assigned_vfc_related": _to_bool_or_none(row.get("assigned_vfc_related")),
                    "assigned_emergency_related": _to_bool_or_none(row.get("assigned_emergency_related")),
                    "assigned_arpa_related": _to_bool_or_none(row.get("assigned_arpa_related")),
                    "assigned_regular_appropriation": _to_bool_or_none(row.get("assigned_regular_appropriation")),
                    "is_verified_mapping": _to_bool_or_none(row.get("is_verified_mapping")),
                    "notes": _normalize_text(row.get("notes")),
                    "is_active": _to_bool_or_none(row.get("is_active")),
                }
            )

    rows.sort(key=lambda row: (int(row["priority"]), str(row["match_field"]), str(row["match_value"])))
    for row in rows:
        if row["is_active"] is None:
            row["is_active"] = True
        if row["is_verified_mapping"] is None:
            row["is_verified_mapping"] = False
    return rows


def _default_profile_relevant_for_scope(funding_scope: str | None) -> bool | None:
    scope = normalize_funding_scope(funding_scope)
    if scope == FUNDING_SCOPE_CORE_PUBLIC_HEALTH:
        return True
    if scope in {
        FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER,
        FUNDING_SCOPE_PROCUREMENT_SUPPORT,
        FUNDING_SCOPE_OTHER_PUBLIC_HEALTH,
        FUNDING_SCOPE_BIOMEDICAL_RESEARCH,
        FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE,
    }:
        return False
    if scope in {FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH, FUNDING_SCOPE_SPECIAL_TRANSFER}:
        return None
    return None


def load_verified_classification_rule_rows(
    path: Path = DEFAULT_VERIFIED_RULES_CSV_PATH,
) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, raw_row in enumerate(reader, start=1):
            row = {_normalize_key(key): value for key, value in (raw_row or {}).items() if key}
            verified = _to_bool_or_none(row.get("verified"))
            account_code = _normalize_text(row.get("account_code"))
            funding_scope = normalize_funding_scope(row.get("funding_scope"))
            if verified is False or account_code is None or funding_scope is None:
                continue
            rationale = _normalize_text(row.get("rationale"))
            assigned_account_title = _normalize_text(row.get("account_title"))
            rows.append(
                {
                    "priority": index,
                    "match_field": "federal_account_symbol",
                    "match_type": "exact",
                    "match_value": account_code,
                    "assigned_funding_stream": funding_stream_from_scope(funding_scope),
                    "assigned_funding_scope": funding_scope,
                    "assigned_account_title": assigned_account_title,
                    "assigned_scope_guess": funding_scope_to_legacy_scope_guess(funding_scope),
                    "assigned_profile_relevant": _default_profile_relevant_for_scope(funding_scope),
                    "assigned_vfc_related": False,
                    "assigned_emergency_related": funding_scope == FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH,
                    "assigned_arpa_related": None,
                    "assigned_regular_appropriation": funding_stream_from_scope(funding_scope) == FUNDING_STREAM_REGULAR,
                    "is_verified_mapping": True,
                    "notes": rationale,
                    "is_active": True,
                    "verified_agency": _normalize_text(row.get("agency")),
                    "verified_rationale": rationale,
                }
            )
    return rows


def _merge_metadata(existing: Any, updates: dict[str, Any]) -> dict[str, Any] | None:
    merged: dict[str, Any] = {}
    if isinstance(existing, dict):
        merged.update(existing)
    for key, value in updates.items():
        if value is None:
            continue
        merged[key] = value
    return merged or None


def _top_key(stats: dict[str, dict[str, Decimal | int]]) -> str | None:
    if not stats:
        return None
    ordered = sorted(
        stats.items(),
        key=lambda item: (
            -(item[1]["obligation_total"]),
            -(item[1]["count"]),
            item[0],
        ),
    )
    return ordered[0][0]


def _top_values(stats: dict[str, dict[str, Decimal | int]], limit: int = 3) -> list[str]:
    ordered = sorted(
        stats.items(),
        key=lambda item: (
            -(item[1]["obligation_total"]),
            -(item[1]["count"]),
            item[0],
        ),
    )
    return [value for value, _payload in ordered[:limit]]


def _bump_choice(stats: dict[str, dict[str, Decimal | int]], value: Any, amount: Decimal) -> None:
    token = _normalize_text(value)
    if token is None:
        return
    bucket = stats.setdefault(
        token,
        {
            "obligation_total": Decimal("0"),
            "count": 0,
        },
    )
    bucket["obligation_total"] += amount
    bucket["count"] += 1


def _derive_description_hint(row: dict[str, Any]) -> str | None:
    for key in (
        "award_description",
        "transaction_description",
        "prime_award_base_transaction_description",
        "program_activity_name",
        "psc_or_aln_description",
    ):
        token = _normalize_text(row.get(key))
        if token:
            return token[:240]
    return None


def _row_is_arpa_related(row: dict[str, Any]) -> bool:
    raw_subtype = _normalize_lower(row.get("appropriation_subtype"))
    raw_type = _normalize_lower(row.get("appropriation_type"))
    raw_code = _normalize_lower(row.get("raw_emergency_code"))
    descriptor = _normalize_lower(_derive_description_hint(row))
    return any(
        (
            raw_subtype == "arp",
            "arpa" in raw_type,
            "american rescue plan" in descriptor,
            "arpa" in descriptor,
            "117-2" in raw_code,
            raw_code.startswith("v"),
        )
    )


def _row_is_emergency_related(row: dict[str, Any]) -> bool:
    if _row_is_arpa_related(row):
        return True
    raw_type = _normalize_lower(row.get("appropriation_type"))
    raw_code = _normalize_lower(row.get("raw_emergency_code"))
    descriptor = _normalize_lower(_derive_description_hint(row))
    return any(
        (
            "covid" in raw_type,
            "emergency" in raw_type,
            "disaster" in raw_type,
            "supplemental" in raw_type,
            bool(raw_code),
            "covid" in descriptor,
            "coronavirus" in descriptor,
            "cares act" in descriptor,
            "crrsa" in descriptor,
            "emergency" in descriptor,
            "disaster" in descriptor,
        )
    )


def _row_is_regular_appropriation(row: dict[str, Any]) -> bool:
    raw_type = _normalize_lower(row.get("appropriation_type"))
    if _row_is_emergency_related(row):
        return False
    if raw_type in {"", "regular", "regular_appropriation"}:
        return True
    return "regular" in raw_type and "emergency" not in raw_type


def _classify_contract_observation_row(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("source_system") != SOURCE_CONTRACTS or row.get("contract_category_guess"):
        return row
    classification = classify_contract_record(
        {
            "award_description": row.get("award_description"),
            "transaction_description": row.get("transaction_description"),
            "prime_award_base_transaction_description": row.get("prime_award_base_transaction_description"),
            "product_or_service_code": row.get("psc_or_aln"),
            "product_or_service_code_description": row.get("psc_or_aln_description"),
            "naics_description": row.get("naics_description"),
        }
    )
    row["contract_category_guess"] = classification["contract_category_guess"]
    row["contract_likely_profile_relevant"] = classification["likely_profile_relevant"]
    return row


def build_lookup_rows(
    observed_rows: list[dict[str, Any]],
    *,
    existing_lookup_by_symbol: dict[str, dict[str, Any]] | None = None,
    metadata_lookup: dict[str, dict[str, str | None]] | None = None,
    metadata_source_path: Path | None = None,
) -> list[dict[str, Any]]:
    existing_lookup_by_symbol = existing_lookup_by_symbol or {}
    metadata_lookup = metadata_lookup or {}
    accumulators: dict[str, dict[str, Any]] = {}

    for source_row in observed_rows:
        row = _classify_contract_observation_row(dict(source_row))
        amount = _as_decimal(row.get("obligation_amount"))
        fiscal_year = row.get("fiscal_year")
        for federal_account_symbol in split_account_symbols(row.get("federal_account_symbol")):
            accumulator = accumulators.get(federal_account_symbol)
            if accumulator is None:
                accumulator = {
                    "federal_account_symbol": federal_account_symbol,
                    "observed_in_contracts": False,
                    "observed_in_assistance": False,
                    "first_fiscal_year": None,
                    "last_fiscal_year": None,
                    "observed_transaction_count": 0,
                    "observed_total_obligations": Decimal("0"),
                    "treasury_stats": {},
                    "source_systems": set(),
                }
                accumulators[federal_account_symbol] = accumulator

            if row.get("source_system") == SOURCE_CONTRACTS:
                accumulator["observed_in_contracts"] = True
            elif row.get("source_system") == SOURCE_ASSISTANCE:
                accumulator["observed_in_assistance"] = True
            accumulator["source_systems"].add(str(row.get("source_system") or "").strip().lower())
            accumulator["observed_transaction_count"] += 1
            accumulator["observed_total_obligations"] += amount

            if isinstance(fiscal_year, int):
                if accumulator["first_fiscal_year"] is None or fiscal_year < accumulator["first_fiscal_year"]:
                    accumulator["first_fiscal_year"] = fiscal_year
                if accumulator["last_fiscal_year"] is None or fiscal_year > accumulator["last_fiscal_year"]:
                    accumulator["last_fiscal_year"] = fiscal_year

            _bump_choice(accumulator["treasury_stats"], row.get("treasury_account_symbol"), amount)

    rows: list[dict[str, Any]] = []
    for federal_account_symbol in sorted(accumulators):
        accumulator = accumulators[federal_account_symbol]
        existing = dict(existing_lookup_by_symbol.get(federal_account_symbol, {}))
        metadata = metadata_lookup.get(federal_account_symbol, {})
        parsed = parse_federal_account_symbol(federal_account_symbol)
        account_title = metadata.get("account_title") or existing.get("account_title")
        source_metadata_json = _merge_metadata(
            existing.get("source_metadata_json"),
            {
                "metadata_source": str(metadata_source_path) if metadata_source_path else "none_found_in_repo",
                "observed_seed_sources": sorted(accumulator["source_systems"]),
                "dominant_treasury_account_symbol": _top_key(accumulator["treasury_stats"]),
            },
        )

        row = {
            "federal_account_symbol": federal_account_symbol,
            "agency_identifier": metadata.get("agency_identifier")
            or existing.get("agency_identifier")
            or parsed["agency_identifier"],
            "main_account_code": metadata.get("main_account_code")
            or existing.get("main_account_code")
            or parsed["main_account_code"],
            "sub_account_code": metadata.get("sub_account_code")
            or existing.get("sub_account_code")
            or parsed["sub_account_code"],
            "account_title": account_title,
            "account_title_normalized": _normalize_account_title(account_title)
            or existing.get("account_title_normalized"),
            "treasury_account_group_hint": _top_key(accumulator["treasury_stats"])
            or existing.get("treasury_account_group_hint"),
            "source_metadata_json": _serialize_json_value(source_metadata_json) if source_metadata_json else None,
            "observed_in_contracts": bool(accumulator["observed_in_contracts"]),
            "observed_in_assistance": bool(accumulator["observed_in_assistance"]),
            "first_fiscal_year": accumulator["first_fiscal_year"],
            "last_fiscal_year": accumulator["last_fiscal_year"],
            "observed_transaction_count": int(accumulator["observed_transaction_count"]),
            "observed_total_obligations": _quantize_money(accumulator["observed_total_obligations"]),
            "funding_stream_guess": existing.get("funding_stream_guess"),
            "funding_scope_guess": existing.get("funding_scope_guess"),
            "funding_scope_method": existing.get("funding_scope_method"),
            "appropriations_scope_guess": existing.get("appropriations_scope_guess"),
            "likely_profile_relevant": existing.get("likely_profile_relevant"),
            "likely_core_public_health": existing.get("likely_core_public_health"),
            "likely_emergency_public_health": existing.get("likely_emergency_public_health"),
            "likely_federal_health_transfer": existing.get("likely_federal_health_transfer"),
            "likely_procurement_support": existing.get("likely_procurement_support"),
            "likely_other_public_health": existing.get("likely_other_public_health"),
            "likely_biomedical_research": existing.get("likely_biomedical_research"),
            "likely_international_health_assistance": existing.get("likely_international_health_assistance"),
            "likely_vfc_related": existing.get("likely_vfc_related"),
            "likely_emergency_related": existing.get("likely_emergency_related"),
            "likely_arpa_related": existing.get("likely_arpa_related"),
            "likely_regular_appropriation": existing.get("likely_regular_appropriation"),
            "classification_confidence": existing.get("classification_confidence"),
            "classification_method": existing.get("classification_method"),
            "classification_notes": existing.get("classification_notes"),
            "manual_funding_stream": existing.get("manual_funding_stream"),
            "manual_funding_scope": existing.get("manual_funding_scope"),
            "manual_scope_guess": existing.get("manual_scope_guess"),
            "manual_profile_relevant": existing.get("manual_profile_relevant"),
            "manual_notes": existing.get("manual_notes"),
            "is_manually_verified": bool(existing.get("is_manually_verified", False)),
            "effective_funding_stream": existing.get("effective_funding_stream"),
            "effective_funding_scope": existing.get("effective_funding_scope"),
            "effective_scope_guess": existing.get("effective_scope_guess"),
            "effective_profile_relevant": existing.get("effective_profile_relevant"),
            "effective_classification_method": existing.get("effective_classification_method"),
        }
        rows.append(row)
    return rows


def build_observation_rows(observed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    accumulators: dict[tuple[str, str, int], dict[str, Any]] = {}
    for source_row in observed_rows:
        row = _classify_contract_observation_row(dict(source_row))
        fiscal_year = row.get("fiscal_year")
        if not isinstance(fiscal_year, int):
            continue
        amount = _as_decimal(row.get("obligation_amount"))
        for federal_account_symbol in split_account_symbols(row.get("federal_account_symbol")):
            key = (federal_account_symbol, str(row.get("source_system") or ""), fiscal_year)
            accumulator = accumulators.get(key)
            if accumulator is None:
                accumulator = {
                    "federal_account_symbol": federal_account_symbol,
                    "source_system": key[1],
                    "fiscal_year": fiscal_year,
                    "transaction_count": 0,
                    "total_obligations": Decimal("0"),
                    "awarding_agency_stats": {},
                    "funding_agency_stats": {},
                    "psc_or_aln_stats": {},
                    "description_stats": {},
                }
                accumulators[key] = accumulator

            accumulator["transaction_count"] += 1
            accumulator["total_obligations"] += amount
            _bump_choice(accumulator["awarding_agency_stats"], row.get("awarding_agency_name"), amount)
            _bump_choice(accumulator["funding_agency_stats"], row.get("funding_agency_name"), amount)
            _bump_choice(accumulator["psc_or_aln_stats"], row.get("psc_or_aln"), amount)
            _bump_choice(accumulator["description_stats"], _derive_description_hint(row), amount)

    rows: list[dict[str, Any]] = []
    for key in sorted(accumulators):
        accumulator = accumulators[key]
        rows.append(
            {
                "federal_account_symbol": accumulator["federal_account_symbol"],
                "source_system": accumulator["source_system"],
                "fiscal_year": accumulator["fiscal_year"],
                "transaction_count": int(accumulator["transaction_count"]),
                "total_obligations": _quantize_money(accumulator["total_obligations"]) or Decimal("0.00"),
                "awarding_agency_name": _top_key(accumulator["awarding_agency_stats"]),
                "funding_agency_name": _top_key(accumulator["funding_agency_stats"]),
                "top_psc_or_aln": _top_key(accumulator["psc_or_aln_stats"]),
                "top_description_hint": _top_key(accumulator["description_stats"]),
            }
        )
    return rows


def _build_classification_contexts(
    lookup_rows: list[dict[str, Any]],
    observed_rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    by_symbol: dict[str, dict[str, Any]] = {}
    for lookup_row in lookup_rows:
        total = _as_decimal(lookup_row.get("observed_total_obligations"))
        by_symbol[str(lookup_row["federal_account_symbol"])] = {
            "observed_total_obligations": total,
            "contract_total": Decimal("0"),
            "assistance_total": Decimal("0"),
            "emergency_total": Decimal("0"),
            "arpa_total": Decimal("0"),
            "regular_total": Decimal("0"),
            "vfc_contract_total": Decimal("0"),
            "description_stats": {},
            "psc_stats": {},
            "awarding_stats": {},
            "funding_stats": {},
            "program_activity_stats": {},
        }

    for source_row in observed_rows:
        row = _classify_contract_observation_row(dict(source_row))
        amount = _as_decimal(row.get("obligation_amount"))
        for federal_account_symbol in split_account_symbols(row.get("federal_account_symbol")):
            context = by_symbol.setdefault(
                federal_account_symbol,
                {
                    "observed_total_obligations": Decimal("0"),
                    "contract_total": Decimal("0"),
                    "assistance_total": Decimal("0"),
                    "emergency_total": Decimal("0"),
                    "arpa_total": Decimal("0"),
                    "regular_total": Decimal("0"),
                    "vfc_contract_total": Decimal("0"),
                    "description_stats": {},
                    "psc_stats": {},
                    "awarding_stats": {},
                    "funding_stats": {},
                    "program_activity_stats": {},
                },
            )
            _bump_choice(context["description_stats"], _derive_description_hint(row), amount)
            _bump_choice(context["psc_stats"], row.get("psc_or_aln"), amount)
            _bump_choice(context["awarding_stats"], row.get("awarding_agency_name"), amount)
            _bump_choice(context["funding_stats"], row.get("funding_agency_name"), amount)
            _bump_choice(context["program_activity_stats"], row.get("program_activity_name"), amount)

            if row.get("source_system") == SOURCE_CONTRACTS:
                context["contract_total"] += amount
                if row.get("contract_category_guess") == CATEGORY_LIKELY_VFC:
                    context["vfc_contract_total"] += amount
            elif row.get("source_system") == SOURCE_ASSISTANCE:
                context["assistance_total"] += amount

            if _row_is_arpa_related(row):
                context["arpa_total"] += amount
                context["emergency_total"] += amount
            elif _row_is_emergency_related(row):
                context["emergency_total"] += amount

            if _row_is_regular_appropriation(row):
                context["regular_total"] += amount

    final_contexts: dict[str, dict[str, Any]] = {}
    for lookup_row in lookup_rows:
        federal_account_symbol = str(lookup_row["federal_account_symbol"])
        stats = by_symbol[federal_account_symbol]
        total = _as_decimal(lookup_row.get("observed_total_obligations")) or stats["contract_total"] + stats["assistance_total"]
        descriptor_parts = [
            lookup_row.get("account_title_normalized"),
            *_top_values(stats["description_stats"]),
            *_top_values(stats["program_activity_stats"]),
            *_top_values(stats["psc_stats"]),
            *_top_values(stats["awarding_stats"]),
            *_top_values(stats["funding_stats"]),
        ]
        descriptor_blob = " ".join(token for token in (_normalize_lower(part) for part in descriptor_parts) if token)
        final_contexts[federal_account_symbol] = {
            "federal_account_symbol": federal_account_symbol,
            "agency_identifier": lookup_row.get("agency_identifier"),
            "main_account_code": lookup_row.get("main_account_code"),
            "sub_account_code": lookup_row.get("sub_account_code"),
            "account_title_normalized": lookup_row.get("account_title_normalized"),
            "descriptor_blob": descriptor_blob,
            "top_psc_or_aln": _top_key(stats["psc_stats"]),
            "top_description_hint": _top_key(stats["description_stats"]),
            "awarding_agency_blob": " ".join(_normalize_lower(value) for value in _top_values(stats["awarding_stats"])),
            "funding_agency_blob": " ".join(_normalize_lower(value) for value in _top_values(stats["funding_stats"])),
            "observed_in_contracts": bool(lookup_row.get("observed_in_contracts")),
            "observed_in_assistance": bool(lookup_row.get("observed_in_assistance")),
            "observed_total_obligations": total,
            "contract_obligation_ratio": _decimal_ratio(stats["contract_total"], total),
            "assistance_obligation_ratio": _decimal_ratio(stats["assistance_total"], total),
            "emergency_obligation_ratio": _decimal_ratio(stats["emergency_total"], total),
            "arpa_obligation_ratio": _decimal_ratio(stats["arpa_total"], total),
            "regular_obligation_ratio": _decimal_ratio(stats["regular_total"], total),
            "vfc_contract_obligation_ratio": _decimal_ratio(stats["vfc_contract_total"], stats["contract_total"]),
            "procurement_contract_obligation_ratio": _decimal_ratio(stats["contract_total"], total),
        }
    return final_contexts


def _match_rule(context: dict[str, Any], rule: dict[str, Any]) -> bool:
    field = str(rule.get("match_field") or "").strip()
    match_type = _normalize_lower(rule.get("match_type")) or "exact"
    match_value = rule.get("match_value")
    context_value = context.get(field)

    if match_type in {"gt", "ge", "lt", "le"}:
        if context_value is None:
            return False
        context_decimal = _as_decimal(context_value)
        target_decimal = _as_decimal(match_value)
        if match_type == "gt":
            return context_decimal > target_decimal
        if match_type == "ge":
            return context_decimal >= target_decimal
        if match_type == "lt":
            return context_decimal < target_decimal
        return context_decimal <= target_decimal

    if match_type == "regex":
        return bool(re.search(str(match_value or ""), _stringify(context_value), re.IGNORECASE))

    if match_type == "contains":
        return _normalize_lower(match_value) in _normalize_lower(context_value)

    if match_type == "startswith":
        return _normalize_lower(context_value).startswith(_normalize_lower(match_value))

    if match_type == "endswith":
        return _normalize_lower(context_value).endswith(_normalize_lower(match_value))

    if match_type == "in":
        options = {
            _normalize_lower(token)
            for token in re.split(r"\s*[|,]\s*", _stringify(match_value))
            if _normalize_lower(token)
        }
        return _normalize_lower(context_value) in options

    if isinstance(context_value, bool):
        target_bool = _to_bool_or_none(match_value)
        return target_bool is not None and context_value is target_bool

    if isinstance(context_value, Decimal):
        return _as_decimal(context_value) == _as_decimal(match_value)

    return _normalize_lower(context_value) == _normalize_lower(match_value)


def _rule_confidence(rule: dict[str, Any], context: dict[str, Any]) -> Decimal:
    match_type = _normalize_lower(rule.get("match_type"))
    match_field = str(rule.get("match_field") or "")
    base = Decimal("0.60")
    if match_type == "exact":
        base = Decimal("0.95") if match_field in {"federal_account_symbol", "account_title_normalized"} else Decimal("0.65")
    elif match_type in {"contains", "startswith", "endswith", "regex"}:
        base = Decimal("0.82")
    elif match_type in {"gt", "ge", "lt", "le"}:
        base = Decimal("0.72")
    elif match_type == "in":
        base = Decimal("0.70")

    if match_field.endswith("_ratio"):
        ratio_value = _as_decimal(context.get(match_field))
        if ratio_value >= Decimal("0.90"):
            base += Decimal("0.10")
        elif ratio_value >= Decimal("0.75"):
            base += Decimal("0.05")
    return min(base, Decimal("0.99")).quantize(Decimal("0.01"))


def _format_pct(value: Decimal) -> str:
    return f"{(value * Decimal('100')).quantize(Decimal('0.1'))}%"


def _derived_funding_scope(
    *,
    assigned_funding_scope: Any,
    assigned_funding_stream: Any,
    assigned_vfc_related: Any,
    context: dict[str, Any],
) -> str:
    explicit_scope = normalize_funding_scope(assigned_funding_scope)
    if explicit_scope is not None:
        return explicit_scope
    return funding_scope_from_stream(
        assigned_funding_stream,
        descriptor_blob=context.get("descriptor_blob"),
        likely_vfc_related=bool(assigned_vfc_related),
    )


def _derived_legacy_scope_guess(
    *,
    assigned_scope_guess: Any,
    funding_scope: str,
) -> str:
    scope_guess = _normalize_text(assigned_scope_guess)
    if scope_guess:
        return scope_guess
    return funding_scope_to_legacy_scope_guess(funding_scope)


def apply_effective_classification(row: dict[str, Any]) -> dict[str, Any]:
    manual_override_used = any(row.get(field) is not None for field in MANUAL_OVERRIDE_FIELDS)
    classification_method = _normalize_text(row.get("classification_method")) or "unclassified"
    verified_mapping_used = classification_method.startswith(f"{VERIFIED_CLASSIFICATION_PREFIX}:")
    if verified_mapping_used:
        effective_funding_stream = row.get("funding_stream_guess") or FUNDING_STREAM_UNKNOWN
    else:
        effective_funding_stream = row.get("manual_funding_stream") or row.get("funding_stream_guess") or FUNDING_STREAM_UNKNOWN
    effective_funding_scope = (
        (
            None
            if verified_mapping_used
            else normalize_funding_scope(row.get("manual_funding_scope"))
        )
        or normalize_funding_scope(row.get("funding_scope_guess"))
        or funding_scope_from_stream(
            effective_funding_stream,
            descriptor_blob=row.get("account_title_normalized") or row.get("account_title"),
            likely_vfc_related=bool(row.get("likely_vfc_related")),
        )
    )
    effective_scope_guess = (
        (None if verified_mapping_used else row.get("manual_scope_guess"))
        or row.get("appropriations_scope_guess")
        or funding_scope_to_legacy_scope_guess(effective_funding_scope)
    )
    effective_profile_relevant = (
        row.get("likely_profile_relevant")
        if verified_mapping_used
        else (
            row.get("manual_profile_relevant")
            if row.get("manual_profile_relevant") is not None
            else row.get("likely_profile_relevant")
        )
    )
    if verified_mapping_used:
        effective_method = VERIFIED_EFFECTIVE_METHOD
    elif manual_override_used:
        effective_method = "manual_override"
    elif row.get("is_manually_verified"):
        effective_method = "manual_verified"
    else:
        effective_method = classification_method

    row["effective_funding_stream"] = effective_funding_stream
    row["effective_funding_scope"] = effective_funding_scope
    row["effective_scope_guess"] = effective_scope_guess
    row["effective_profile_relevant"] = effective_profile_relevant
    row["effective_classification_method"] = effective_method
    row["funding_scope_method"] = (
        VERIFIED_EFFECTIVE_METHOD
        if verified_mapping_used
        else (
            "manual_override"
            if row.get("manual_funding_scope") is not None
            else row.get("funding_scope_method") or effective_method
        )
    )
    return row


def apply_classification_rows(
    lookup_rows: list[dict[str, Any]],
    observed_rows: list[dict[str, Any]],
    rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    contexts = _build_classification_contexts(lookup_rows, observed_rows)
    classified_rows: list[dict[str, Any]] = []
    active_rules = [rule for rule in rules if bool(rule.get("is_active", True))]

    for original_row in lookup_rows:
        row = dict(original_row)
        context = contexts[str(row["federal_account_symbol"])]
        matched_rule = next((rule for rule in active_rules if _match_rule(context, rule)), None)

        if matched_rule is None:
            row["funding_stream_guess"] = FUNDING_STREAM_UNKNOWN
            row["funding_scope_guess"] = FUNDING_SCOPE_UNKNOWN
            row["funding_scope_method"] = "unclassified"
            row["appropriations_scope_guess"] = SCOPE_UNCERTAIN
            row["likely_profile_relevant"] = None
            row["likely_core_public_health"] = None
            row["likely_emergency_public_health"] = None
            row["likely_federal_health_transfer"] = None
            row["likely_procurement_support"] = None
            row["likely_other_public_health"] = None
            row["likely_biomedical_research"] = None
            row["likely_international_health_assistance"] = None
            row["likely_vfc_related"] = None
            row["likely_emergency_related"] = None
            row["likely_arpa_related"] = None
            row["likely_regular_appropriation"] = None
            row["classification_confidence"] = Decimal("0.20")
            row["classification_method"] = "unclassified"
            row["is_manually_verified"] = bool(row.get("is_manually_verified", False))
            row["classification_notes"] = (
                "No active federal-account classification rule matched the observed symbol context. "
                f"contracts={_format_pct(context['contract_obligation_ratio'])}; "
                f"assistance={_format_pct(context['assistance_obligation_ratio'])}; "
                f"regular={_format_pct(context['regular_obligation_ratio'])}; "
                f"emergency={_format_pct(context['emergency_obligation_ratio'])}; "
                f"arpa={_format_pct(context['arpa_obligation_ratio'])}; "
                f"vfc_contract={_format_pct(context['vfc_contract_obligation_ratio'])}."
            )
        else:
            assigned_account_title = _normalize_text(matched_rule.get("assigned_account_title"))
            funding_scope_guess = _derived_funding_scope(
                assigned_funding_scope=matched_rule.get("assigned_funding_scope"),
                assigned_funding_stream=matched_rule.get("assigned_funding_stream"),
                assigned_vfc_related=matched_rule.get("assigned_vfc_related"),
                context=context,
            )
            scope_flags = funding_scope_indicator_flags(funding_scope_guess)
            method_prefix = (
                VERIFIED_CLASSIFICATION_PREFIX
                if bool(matched_rule.get("is_verified_mapping"))
                else "rule"
            )
            method_label = (
                f"{method_prefix}:{matched_rule['match_field']}:{matched_rule['match_type']}:{matched_rule['match_value']}"
            )
            if assigned_account_title:
                row["account_title"] = assigned_account_title
                row["account_title_normalized"] = _normalize_account_title(assigned_account_title)
            row["funding_stream_guess"] = matched_rule.get("assigned_funding_stream") or FUNDING_STREAM_UNKNOWN
            row["funding_scope_guess"] = funding_scope_guess
            row["funding_scope_method"] = (
                VERIFIED_EFFECTIVE_METHOD
                if bool(matched_rule.get("is_verified_mapping"))
                else method_label
            )
            row["appropriations_scope_guess"] = _derived_legacy_scope_guess(
                assigned_scope_guess=matched_rule.get("assigned_scope_guess"),
                funding_scope=funding_scope_guess,
            )
            row["likely_profile_relevant"] = matched_rule.get("assigned_profile_relevant")
            row["likely_core_public_health"] = scope_flags["likely_core_public_health"]
            row["likely_emergency_public_health"] = scope_flags["likely_emergency_public_health"]
            row["likely_federal_health_transfer"] = scope_flags["likely_federal_health_transfer"]
            row["likely_procurement_support"] = scope_flags["likely_procurement_support"]
            row["likely_other_public_health"] = scope_flags["likely_other_public_health"]
            row["likely_biomedical_research"] = scope_flags["likely_biomedical_research"]
            row["likely_international_health_assistance"] = scope_flags["likely_international_health_assistance"]
            row["likely_vfc_related"] = matched_rule.get("assigned_vfc_related")
            row["likely_emergency_related"] = matched_rule.get("assigned_emergency_related")
            row["likely_arpa_related"] = matched_rule.get("assigned_arpa_related")
            row["likely_regular_appropriation"] = matched_rule.get("assigned_regular_appropriation")
            row["classification_confidence"] = (
                Decimal("0.99")
                if bool(matched_rule.get("is_verified_mapping"))
                else _rule_confidence(matched_rule, context)
            )
            row["classification_method"] = method_label
            row["is_manually_verified"] = bool(matched_rule.get("is_verified_mapping")) or bool(
                row.get("is_manually_verified", False)
            )
            note = matched_rule.get("notes") or "Matched deterministic federal-account classification rule."
            row["classification_notes"] = (
                f"{note} "
                f"contracts={_format_pct(context['contract_obligation_ratio'])}; "
                f"assistance={_format_pct(context['assistance_obligation_ratio'])}; "
                f"regular={_format_pct(context['regular_obligation_ratio'])}; "
                f"emergency={_format_pct(context['emergency_obligation_ratio'])}; "
                f"arpa={_format_pct(context['arpa_obligation_ratio'])}; "
                f"vfc_contract={_format_pct(context['vfc_contract_obligation_ratio'])}."
            )

        row["classification_confidence"] = _quantize_ratio(_as_decimal(row.get("classification_confidence")))
        classified_rows.append(apply_effective_classification(row))

    classified_rows.sort(key=lambda row: str(row["federal_account_symbol"]))
    return classified_rows


def build_review_rows(lookup_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered_rows = sorted(
        lookup_rows,
        key=lambda row: (
            -_as_decimal(row.get("observed_total_obligations")),
            _as_decimal(row.get("classification_confidence")),
            str(row.get("federal_account_symbol") or ""),
        ),
    )
    return [
        {field: row.get(field) for field in REVIEW_EXPORT_FIELDS}
        for row in ordered_rows
    ]


def write_review_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REVIEW_EXPORT_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _stringify(value) for key, value in row.items()})


def _relation_exists(connection: Any, relation_name: str) -> bool:
    row = connection.execute(
        text("SELECT to_regclass(:relation_name) AS exists"),
        {"relation_name": relation_name},
    ).mappings().one()
    return row["exists"] is not None


def _require_relation(connection: Any, relation_name: str) -> None:
    if not _relation_exists(connection, relation_name):
        raise RuntimeError(
            f"Required relation is missing: {relation_name}. Run migrations before building the federal account lookup layer."
        )


def _fetch_rows(connection: Any, sql: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(text(sql)).mappings().all()]


def fetch_contract_account_rows(connection: Any) -> list[dict[str, Any]]:
    if not _relation_exists(connection, CONTRACT_ACCOUNTS_VIEW):
        return []
    rows = _fetch_rows(
        connection,
        f"""
        SELECT *
        FROM {CONTRACT_ACCOUNTS_VIEW}
        ORDER BY federal_account_symbol, fiscal_year NULLS LAST, source_row_id
        """,
    )
    return [_classify_contract_observation_row(row) for row in rows]


def fetch_assistance_account_rows(connection: Any) -> list[dict[str, Any]]:
    if not _relation_exists(connection, ASSISTANCE_ACCOUNTS_VIEW):
        return []
    return _fetch_rows(
        connection,
        f"""
        SELECT
            'assistance'::text AS source_system,
            source_row_id,
            federal_account_symbol,
            source_transaction_id AS transaction_unique_key,
            award_key,
            fiscal_year,
            COALESCE(transaction_obligated_amount, 0)::numeric(18, 2) AS obligation_amount,
            awarding_agency_name,
            funding_agency_name,
            treasury_account_symbol,
            appropriation_type,
            appropriation_subtype,
            raw_emergency_code,
            psc_or_aln,
            psc_or_aln_description,
            award_description,
            transaction_description,
            prime_award_base_transaction_description,
            naics_description,
            program_activity_name
        FROM {ASSISTANCE_ACCOUNTS_VIEW}
        ORDER BY federal_account_symbol, fiscal_year NULLS LAST, source_row_id
        """,
    )


def _dry_run_assistance_account_rows(connection: Any) -> list[dict[str, Any]]:
    rows = build_assistance_transaction_account_rows(fetch_assistance_source_rows(connection))
    return [
        {
            "source_system": SOURCE_ASSISTANCE,
            "source_row_id": row.get("source_row_id"),
            "federal_account_symbol": row.get("federal_account_symbol"),
            "transaction_unique_key": row.get("source_transaction_id"),
            "award_key": row.get("award_key"),
            "fiscal_year": row.get("fiscal_year"),
            "obligation_amount": row.get("transaction_obligated_amount"),
            "awarding_agency_name": row.get("awarding_agency_name"),
            "funding_agency_name": row.get("funding_agency_name"),
            "treasury_account_symbol": row.get("treasury_account_symbol"),
            "appropriation_type": row.get("appropriation_type"),
            "appropriation_subtype": row.get("appropriation_subtype"),
            "raw_emergency_code": row.get("raw_emergency_code"),
            "psc_or_aln": row.get("psc_or_aln"),
            "psc_or_aln_description": row.get("psc_or_aln_description"),
            "award_description": row.get("award_description"),
            "transaction_description": row.get("transaction_description"),
            "prime_award_base_transaction_description": row.get("prime_award_base_transaction_description"),
            "naics_description": row.get("naics_description"),
            "program_activity_name": row.get("program_activity_name"),
        }
        for row in rows
    ]


def fetch_lookup_rows(connection: Any) -> list[dict[str, Any]]:
    if not _relation_exists(connection, LOOKUP_FQTN):
        return []
    return [dict(row) for row in connection.execute(LOOKUP_TABLE.select().order_by(LOOKUP_TABLE.c.federal_account_symbol)).mappings()]


def fetch_lookup_rows_by_symbol(connection: Any) -> dict[str, dict[str, Any]]:
    return {
        str(row["federal_account_symbol"]): row
        for row in fetch_lookup_rows(connection)
    }


def replace_lookup_rows(connection: Any, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError("No observed federal account symbols were found; refusing to clear the lookup table.")
    symbols = [str(row["federal_account_symbol"]) for row in rows]
    connection.execute(LOOKUP_TABLE.delete().where(~LOOKUP_TABLE.c.federal_account_symbol.in_(symbols)))
    insert_stmt = pg_insert(LOOKUP_TABLE).values(rows)
    update_columns = {
        column.name: getattr(insert_stmt.excluded, column.name)
        for column in LOOKUP_TABLE.columns
        if column.name not in {"created_at", "federal_account_symbol"}
    }
    update_columns["updated_at"] = text("now()")
    connection.execute(
        insert_stmt.on_conflict_do_update(
            index_elements=[LOOKUP_TABLE.c.federal_account_symbol],
            set_=update_columns,
        )
    )


def replace_observation_rows(connection: Any, rows: list[dict[str, Any]]) -> None:
    connection.execute(OBSERVATION_TABLE.delete())
    if rows:
        connection.execute(OBSERVATION_TABLE.insert(), rows)


def replace_rule_rows(connection: Any, rows: list[dict[str, Any]]) -> None:
    connection.execute(RULE_TABLE.delete())
    if rows:
        allowed_keys = {column.name for column in RULE_TABLE.columns}
        payload = [{key: value for key, value in row.items() if key in allowed_keys} for row in rows]
        connection.execute(RULE_TABLE.insert(), payload)


def write_summary_file(path: str | Path, payload: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def build_verified_account_mapping_summary_payload(
    *,
    lookup_rows: list[dict[str, Any]],
    verified_rule_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    lookup_by_symbol = {str(row["federal_account_symbol"]): row for row in lookup_rows}
    loaded_accounts = []
    for rule in verified_rule_rows:
        symbol = str(rule["match_value"])
        lookup_row = lookup_by_symbol.get(symbol, {})
        loaded_accounts.append(
            {
                "account_code": symbol,
                "account_title": rule.get("assigned_account_title"),
                "agency": rule.get("verified_agency"),
                "funding_scope": rule.get("assigned_funding_scope"),
                "verified": True,
                "rationale": rule.get("verified_rationale"),
                "effective_funding_scope": lookup_row.get("effective_funding_scope"),
                "effective_profile_relevant": lookup_row.get("effective_profile_relevant"),
                "funding_scope_method": lookup_row.get("funding_scope_method"),
                "observed_total_obligations": lookup_row.get("observed_total_obligations"),
            }
        )

    fallback_accounts = [
        {
            "federal_account_symbol": row.get("federal_account_symbol"),
            "account_title": row.get("account_title"),
            "effective_funding_scope": row.get("effective_funding_scope"),
            "funding_scope_method": row.get("funding_scope_method"),
            "effective_profile_relevant": row.get("effective_profile_relevant"),
            "observed_total_obligations": row.get("observed_total_obligations"),
        }
        for row in sorted(
            (
                row
                for row in lookup_rows
                if _normalize_text(row.get("funding_scope_method")) != VERIFIED_EFFECTIVE_METHOD
            ),
            key=lambda item: _as_decimal(item.get("observed_total_obligations")),
            reverse=True,
        )
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verified_csv_path": str(DEFAULT_VERIFIED_RULES_CSV_PATH),
        "loaded_account_count": len(loaded_accounts),
        "loaded_accounts": loaded_accounts,
        "fallback_account_count": len(fallback_accounts),
        "fallback_accounts": fallback_accounts,
    }


def build_fallback_account_verification_summary_payload(
    *,
    current_verified_summary: dict[str, Any],
    previous_verified_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous_verified_summary = previous_verified_summary or {}
    previous_fallback_by_symbol = {
        str(row.get("federal_account_symbol")): row
        for row in previous_verified_summary.get("fallback_accounts", [])
        if _normalize_text(row.get("federal_account_symbol"))
    }
    current_loaded_by_symbol = {
        str(row.get("account_code")): row
        for row in current_verified_summary.get("loaded_accounts", [])
        if _normalize_text(row.get("account_code"))
    }

    former_fallback_accounts_now_verified = []
    for symbol in KNOWN_FORMER_FALLBACK_ACCOUNTS:
        loaded_row = current_loaded_by_symbol.get(symbol)
        if loaded_row is None:
            continue
        previous_row = previous_fallback_by_symbol.get(symbol, {})
        former_fallback_accounts_now_verified.append(
            {
                "account_code": symbol,
                "account_title": loaded_row.get("account_title"),
                "funding_scope": loaded_row.get("effective_funding_scope") or loaded_row.get("funding_scope"),
                "funding_scope_method": loaded_row.get("funding_scope_method"),
                "effective_profile_relevant": loaded_row.get("effective_profile_relevant"),
                "observed_total_obligations": loaded_row.get("observed_total_obligations"),
                "previous_fallback_scope": previous_row.get("effective_funding_scope"),
                "previous_fallback_method": previous_row.get("funding_scope_method"),
            }
        )

    remaining_fallback_accounts = current_verified_summary.get("fallback_accounts", [])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "former_fallback_account_count": len(former_fallback_accounts_now_verified),
        "former_fallback_accounts_now_verified": former_fallback_accounts_now_verified,
        "remaining_fallback_account_count": len(remaining_fallback_accounts),
        "remaining_fallback_accounts": remaining_fallback_accounts,
        "all_former_fallback_accounts_verified": len(former_fallback_accounts_now_verified) == len(KNOWN_FORMER_FALLBACK_ACCOUNTS),
    }


def build_federal_account_lookup(
    connection: Any,
    *,
    reseed_from_observed: bool = True,
    rebuild_observations: bool = True,
    rebuild_classification: bool = True,
    export_review_csv: bool = False,
    review_csv_path: Path | None = None,
    account_metadata_path: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    _require_relation(connection, LOOKUP_FQTN)
    _require_relation(connection, OBSERVATION_FQTN)
    _require_relation(connection, RULE_FQTN)
    _require_relation(connection, ASSISTANCE_ACCOUNTS_VIEW)

    assistance_refresh_summary = refresh_assistance_transaction_accounts(connection, dry_run=dry_run)

    contract_rows = fetch_contract_account_rows(connection)
    assistance_rows = _dry_run_assistance_account_rows(connection) if dry_run else fetch_assistance_account_rows(connection)
    observed_rows = [*contract_rows, *assistance_rows]
    if (reseed_from_observed or rebuild_observations or rebuild_classification) and not observed_rows:
        raise RuntimeError(
            "No observed federal account rows were found in the bridge views. Load USAspending contracts and assistance data first."
        )

    metadata_path = discover_account_metadata_path(REPO_ROOT, explicit_path=account_metadata_path)
    metadata_lookup = load_account_metadata_lookup(metadata_path) if metadata_path else {}
    existing_lookup_by_symbol = fetch_lookup_rows_by_symbol(connection)

    lookup_rows = fetch_lookup_rows(connection)
    observation_rows = []

    if reseed_from_observed:
        lookup_rows = build_lookup_rows(
            observed_rows,
            existing_lookup_by_symbol=existing_lookup_by_symbol,
            metadata_lookup=metadata_lookup,
            metadata_source_path=metadata_path,
        )
        if not dry_run:
            replace_lookup_rows(connection, lookup_rows)

    if rebuild_observations:
        observation_rows = build_observation_rows(observed_rows)
        if not dry_run:
            replace_observation_rows(connection, observation_rows)

    if rebuild_classification:
        previous_verified_summary = None
        if DEFAULT_VERIFIED_SUMMARY_PATH.exists():
            previous_verified_summary = json.loads(DEFAULT_VERIFIED_SUMMARY_PATH.read_text(encoding="utf-8"))
        rules = load_classification_rule_rows()
        if not dry_run:
            replace_rule_rows(connection, rules)
        if not lookup_rows:
            lookup_rows = fetch_lookup_rows(connection)
        lookup_rows = apply_classification_rows(lookup_rows, observed_rows, rules)
        if not dry_run:
            replace_lookup_rows(connection, lookup_rows)
            current_verified_summary = build_verified_account_mapping_summary_payload(
                lookup_rows=lookup_rows,
                verified_rule_rows=load_verified_classification_rule_rows(),
            )
            write_summary_file(
                DEFAULT_VERIFIED_SUMMARY_PATH,
                current_verified_summary,
            )
            write_summary_file(
                DEFAULT_FALLBACK_VERIFICATION_SUMMARY_PATH,
                build_fallback_account_verification_summary_payload(
                    current_verified_summary=current_verified_summary,
                    previous_verified_summary=previous_verified_summary,
                ),
            )

    assistance_account_summary_rebuild = {"summary_rows_written": 0}
    assistance_account_summary_rebuild = refresh_assistance_transaction_account_summary(connection, dry_run=dry_run)

    review_path = None
    exported_row_count = 0
    if export_review_csv:
        if not lookup_rows:
            lookup_rows = fetch_lookup_rows(connection)
        review_rows = build_review_rows(lookup_rows)
        review_path = (review_csv_path or DEFAULT_REVIEW_CSV_PATH).resolve()
        write_review_csv(review_path, review_rows)
        exported_row_count = len(review_rows)

    return {
        "contract_rows_observed": len(contract_rows),
        "assistance_rows_observed": len(assistance_rows),
        "distinct_symbols_observed": len({str(row["federal_account_symbol"]) for row in lookup_rows}) if lookup_rows else 0,
        "lookup_rows_built": len(lookup_rows),
        "observation_rows_built": len(observation_rows),
        "metadata_source_path": str(metadata_path) if metadata_path else None,
        "metadata_rows_loaded": len(metadata_lookup),
        "review_csv_path": str(review_path) if review_path else None,
        "review_rows_exported": exported_row_count,
        "assistance_account_bridge": assistance_refresh_summary,
        "assistance_account_summary": assistance_account_summary_rebuild,
        "dry_run": dry_run,
    }


def main() -> None:
    args = parse_args()
    engine = create_engine(args.db_url, pool_pre_ping=True)

    with engine.begin() as connection:
        summary = build_federal_account_lookup(
            connection,
            reseed_from_observed=bool(args.reseed_from_observed),
            rebuild_observations=bool(args.rebuild_observations),
            rebuild_classification=bool(args.rebuild_classification),
            export_review_csv=bool(args.export_review_csv),
            review_csv_path=Path(args.review_csv_path).expanduser().resolve() if args.review_csv_path else None,
            account_metadata_path=args.account_metadata_path,
            dry_run=bool(args.dry_run),
        )

    if args.verbose:
        for key in sorted(summary):
            print(f"{key}: {summary[key]}")


if __name__ == "__main__":
    main()
