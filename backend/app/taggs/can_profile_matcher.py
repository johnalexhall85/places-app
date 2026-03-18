from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import DEFAULT_DB_URL
from app.db_fqtn import cdc_profiles_table, taggs_table
from app.taggs.ingest import (
    DOMESTIC_SCOPE_CODES,
    INTERNATIONAL_KEYWORD_RE,
    SEED_HEADER_ALIASES,
    UNKNOWN_COUNTY_TOKENS,
    US_COUNTRY_TOKENS,
)
from app.taggs.models import TaggsCanClassification, TaggsCanProfileMatchAudit

CAN_MAPPING_VERSION = "taggs_cdc_profile_can_mapping_v2026_03_13"
PROFILE_REFERENCE_YEARS = (2020, 2021, 2022, 2023)
TAGGS_PROFILE_TRAINING_YEARS = (2021, 2022, 2023)
TAGGS_LATER_YEARS = (2024, 2025, 2026)

UNKNOWN_LABEL = "Unknown / Unclassified"
MANUAL_OVERRIDE_METHOD = "manual_override"
PROFILE_MATCH_METHOD = "cdc_profile_match"
FALLBACK_METHOD = "fallback_inference"
UNKNOWN_METHOD = "unknown"

PROFILE_ACCEPT_CONFIDENCE = Decimal("65.00")
FALLBACK_ACCEPT_CONFIDENCE = Decimal("55.00")

WEIGHT_RECIPIENT = Decimal("0.30")
WEIGHT_TITLE = Decimal("0.25")
WEIGHT_AMOUNT = Decimal("0.20")
WEIGHT_LOCATION = Decimal("0.10")
WEIGHT_LISTING = Decimal("0.10")
WEIGHT_OFFICE = Decimal("0.05")

IDENTIFIER_BONUS_EXACT = Decimal("0.15")
IDENTIFIER_BONUS_PARTIAL = Decimal("0.08")

STRONG_MATCH_THRESHOLD = Decimal("0.85")
PROBABLE_MATCH_THRESHOLD = Decimal("0.70")
WEAK_MATCH_THRESHOLD = Decimal("0.55")

RAW_PROFILE_ROWS_TABLE = cdc_profiles_table("raw_profile_rows")
RAW_AWARDS_TABLE = taggs_table("raw_awards")
CAN_CLASSIFICATION_TABLE = TaggsCanClassification.__table__
MATCH_AUDIT_TABLE = TaggsCanProfileMatchAudit.__table__

REVIEW_HEADER = [
    "can_code",
    "effective_program_name",
    "effective_category",
    "effective_subcategory",
    "effective_mapping_method",
    "profile_match_count",
    "profile_match_confidence",
    "fallback_guess_confidence",
    "dominant_program_office",
    "dominant_aln",
    "observed_total_funding",
    "is_manually_verified",
]

STOPWORDS = {
    "a",
    "an",
    "and",
    "award",
    "agreement",
    "cooperative",
    "for",
    "grant",
    "in",
    "inc",
    "incorporated",
    "of",
    "program",
    "project",
    "public",
    "services",
    "state",
    "the",
    "to",
    "university",
}

FUNDING_STREAM_RULES: tuple[tuple[str, dict[str, Any]], ...] = (
    (
        "vaccines for children",
        {
            "funding_stream": "Vaccines for Children",
            "appropriation_type": "regular",
            "is_covid_related": False,
            "is_arpa_related": False,
            "is_supplemental": False,
            "is_regular_appropriation": True,
        },
    ),
    (
        "drug free communit",
        {
            "funding_stream": "Drug Free Communities",
            "appropriation_type": "regular",
            "is_covid_related": False,
            "is_arpa_related": False,
            "is_supplemental": False,
            "is_regular_appropriation": True,
        },
    ),
    (
        "american rescue plan",
        {
            "funding_stream": "American Rescue Plan",
            "appropriation_type": "other_emergency",
            "is_covid_related": False,
            "is_arpa_related": True,
            "is_supplemental": True,
            "is_regular_appropriation": False,
        },
    ),
    (
        " arpa ",
        {
            "funding_stream": "American Rescue Plan",
            "appropriation_type": "other_emergency",
            "is_covid_related": False,
            "is_arpa_related": True,
            "is_supplemental": True,
            "is_regular_appropriation": False,
        },
    ),
    (
        "phssef",
        {
            "funding_stream": "COVID-19 / PHSSEF",
            "appropriation_type": "covid_emergency",
            "is_covid_related": True,
            "is_arpa_related": False,
            "is_supplemental": True,
            "is_regular_appropriation": False,
        },
    ),
    (
        "covid",
        {
            "funding_stream": "COVID-19 / PHSSEF",
            "appropriation_type": "covid_emergency",
            "is_covid_related": True,
            "is_arpa_related": False,
            "is_supplemental": True,
            "is_regular_appropriation": False,
        },
    ),
    (
        "coronavirus",
        {
            "funding_stream": "COVID-19 / PHSSEF",
            "appropriation_type": "covid_emergency",
            "is_covid_related": True,
            "is_arpa_related": False,
            "is_supplemental": True,
            "is_regular_appropriation": False,
        },
    ),
)


@dataclass(frozen=True)
class ProfileReferenceRow:
    id: int
    fiscal_year: int
    state_code: str
    category: str | None
    subcategory: str | None
    grantee_name: str | None
    city: str | None
    county: str | None
    amount: Decimal
    project_number: str | None
    reference_number: str | None
    nofo_number: str | None
    nofo_title: str | None
    funding_opportunity_title: str | None


@dataclass
class TaggsAwardAggregate:
    representative_raw_award_id: int
    award_number: str | None
    funding_fiscal_year: int
    can_code: str | None
    legal_entity_state_normalized: str | None
    legal_entity_county_normalized: str | None
    legal_entity_country_normalized: str | None
    program_office: str | None
    aln: str | None
    assistance_listing_title: str | None
    award_title: str | None
    award_description: str | None
    legal_entity_name: str | None
    legal_entity_city: str | None
    total_sum_of_actions: Decimal
    raw_row_count: int
    is_domestic_scope: bool


@dataclass(frozen=True)
class MatchCandidate:
    can_code: str | None
    fiscal_year: int
    state_code: str
    matched_profile_row_id: int
    matched_taggs_row_id: int
    match_score: Decimal
    match_strength: str
    match_method: str
    evidence_json: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build CDC-profile-assisted TAGGS CAN mapping.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or the local development DSN).",
    )
    parser.add_argument(
        "--limit-years",
        default=None,
        help="Optional comma-separated fiscal years to consider for TAGGS observation/rebuild.",
    )
    parser.add_argument(
        "--limit-cans",
        default=None,
        help="Optional comma-separated CAN codes to rebuild.",
    )
    parser.add_argument(
        "--only-unmapped",
        action="store_true",
        help="Only rebuild CANs that are currently unmapped or unknown in taggs.can_classification.",
    )
    parser.add_argument(
        "--export-review-csv",
        default=None,
        help="Optional review CSV path (defaults to data/taggs/review/can_profile_mapping_review.csv when used).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build mapping payloads without writing to the database.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print deterministic progress counts while matching.",
    )
    return parser.parse_args()


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).replace("\ufeff", "").strip()
    token = re.sub(r"\s+", " ", token)
    return token or None


def _normalize_code(value: Any) -> str | None:
    token = _clean_text(value)
    return token.upper() if token else None


def _normalize_free_text(value: Any) -> str:
    token = str(value or "").lower()
    token = re.sub(r"[^a-z0-9]+", " ", token)
    token = re.sub(r"\s+", " ", token).strip()
    return f" {token} " if token else ""


def _normalize_identifier_token(value: Any) -> str | None:
    token = _clean_text(value)
    if token is None:
        return None
    compact = re.sub(r"[^A-Za-z0-9]+", "", token).upper()
    return compact or None


def _extract_identifier_tokens(value: Any) -> set[str]:
    token = _clean_text(value)
    if token is None:
        return set()
    matches = {
        match.group(0).upper()
        for match in re.finditer(r"[A-Za-z0-9]{8,}", token)
    }
    normalized = {_normalize_identifier_token(item) for item in matches}
    return {item for item in normalized if item}


def _tokenize(value: Any) -> tuple[str, ...]:
    normalized = _normalize_free_text(value).strip()
    if not normalized:
        return ()
    return tuple(
        token
        for token in normalized.split()
        if len(token) >= 3 and token not in STOPWORDS
    )


def _parse_csv_years(value: str | None) -> tuple[int, ...] | None:
    token = _clean_text(value)
    if not token:
        return None
    years = []
    for part in token.split(","):
        piece = part.strip()
        if not piece:
            continue
        try:
            years.append(int(piece))
        except ValueError:
            continue
    return tuple(sorted(set(years))) or None


def _parse_csv_cans(value: str | None) -> tuple[str, ...] | None:
    token = _clean_text(value)
    if not token:
        return None
    return tuple(sorted({_normalize_code(part) for part in token.split(",") if _normalize_code(part)}))


def _parse_bool_token(value: Any) -> bool | None:
    token = str(value or "").strip().lower()
    if token in {"true", "t", "1", "yes", "y"}:
        return True
    if token in {"false", "f", "0", "no", "n"}:
        return False
    return None


def _candidate_seed_paths() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[3]
    return [
        (repo_root / "data" / "taggs" / "can_classification_seed.csv").resolve(),
        (repo_root / "data" / "taggs" / "review" / "can_classification_seed.csv").resolve(),
    ]


def _normalize_seed_header(value: Any) -> str:
    token = _clean_text(value) or ""
    token = token.lower()
    token = re.sub(r"[^a-z0-9]+", "_", token).strip("_")
    return SEED_HEADER_ALIASES.get(token, token)


def load_seed_overrides() -> dict[str, dict[str, Any]]:
    for seed_path in _candidate_seed_paths():
        if not seed_path.exists() or not seed_path.is_file():
            continue
        with seed_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                return {}
            rows: dict[str, dict[str, Any]] = {}
            for source_row in reader:
                normalized = {
                    _normalize_seed_header(key): _clean_text(value)
                    for key, value in source_row.items()
                }
                can_code = _normalize_code(normalized.get("can_code"))
                if not can_code:
                    continue
                rows[can_code] = {
                    "can_code": can_code,
                    "funding_stream": normalized.get("funding_stream"),
                    "appropriation_type": normalized.get("appropriation_type"),
                    "notes": normalized.get("notes"),
                    "manual_program_name": normalized.get("manual_program_name") or normalized.get("program_name"),
                    "manual_category": normalized.get("manual_category") or normalized.get("category_override"),
                    "manual_subcategory": normalized.get("manual_subcategory") or normalized.get("subcategory_override"),
                    "manual_notes": normalized.get("manual_notes") or normalized.get("notes"),
                    "is_manually_verified": _parse_bool_token(
                        normalized.get("is_manually_verified") or "true"
                    ),
                    "is_covid_related": _parse_bool_token(normalized.get("is_covid_related")),
                    "is_arpa_related": _parse_bool_token(normalized.get("is_arpa_related")),
                    "is_supplemental": _parse_bool_token(normalized.get("is_supplemental")),
                    "is_regular_appropriation": _parse_bool_token(
                        normalized.get("is_regular_appropriation")
                    ),
                }
            return rows
    return {}


def _combined_similarity(left: Any, right: Any) -> Decimal:
    left_norm = _normalize_free_text(left).strip()
    right_norm = _normalize_free_text(right).strip()
    if not left_norm or not right_norm:
        return Decimal("0")
    sequence_ratio = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_tokens = set(_tokenize(left_norm))
    right_tokens = set(_tokenize(right_norm))
    if not left_tokens or not right_tokens:
        token_ratio = 0.0
    else:
        token_ratio = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    return Decimal(str(round(sequence_ratio * 0.55 + token_ratio * 0.45, 4)))


def _amount_similarity(left: Decimal | None, right: Decimal | None) -> Decimal:
    if left is None or right is None:
        return Decimal("0")
    left_abs = abs(left)
    right_abs = abs(right)
    if left_abs == 0 and right_abs == 0:
        return Decimal("1")
    denominator = max(left_abs, right_abs, Decimal("1"))
    pct_diff = abs(left - right) / denominator
    if pct_diff <= Decimal("0.002"):
        return Decimal("1")
    if pct_diff <= Decimal("0.01"):
        return Decimal("0.90")
    if pct_diff <= Decimal("0.05"):
        return Decimal("0.75")
    if pct_diff <= Decimal("0.10"):
        return Decimal("0.55")
    if pct_diff <= Decimal("0.25"):
        return Decimal("0.35")
    return max(Decimal("0"), Decimal("1") - (pct_diff * Decimal("2")))


def _location_similarity(profile_row: ProfileReferenceRow, taggs_row: TaggsAwardAggregate) -> Decimal:
    components: list[Decimal] = []
    if profile_row.city and taggs_row.legal_entity_city:
        components.append(_combined_similarity(profile_row.city, taggs_row.legal_entity_city))
    if profile_row.county and taggs_row.legal_entity_county_normalized:
        components.append(_combined_similarity(profile_row.county, taggs_row.legal_entity_county_normalized))
    if not components:
        return Decimal("0")
    return sum(components) / Decimal(str(len(components)))


def _listing_similarity(profile_row: ProfileReferenceRow, taggs_row: TaggsAwardAggregate) -> Decimal:
    candidates = [
        profile_row.nofo_title,
        profile_row.funding_opportunity_title,
        profile_row.category,
        profile_row.subcategory,
    ]
    comparisons = [
        _combined_similarity(candidate, taggs_row.assistance_listing_title)
        for candidate in candidates
        if candidate and taggs_row.assistance_listing_title
    ]
    return max(comparisons, default=Decimal("0"))


def _program_office_similarity(profile_row: ProfileReferenceRow, taggs_row: TaggsAwardAggregate) -> Decimal:
    comparisons = [
        _combined_similarity(profile_row.category, taggs_row.program_office),
        _combined_similarity(profile_row.subcategory, taggs_row.program_office),
    ]
    return max(comparisons, default=Decimal("0"))


def _identifier_bonus(profile_row: ProfileReferenceRow, taggs_row: TaggsAwardAggregate) -> tuple[Decimal, str]:
    profile_ids = (
        _extract_identifier_tokens(profile_row.project_number)
        | _extract_identifier_tokens(profile_row.reference_number)
        | _extract_identifier_tokens(profile_row.nofo_number)
    )
    taggs_ids = _extract_identifier_tokens(taggs_row.award_number)
    if profile_ids and taggs_ids and profile_ids & taggs_ids:
        return IDENTIFIER_BONUS_EXACT, "award_identifier_exact"
    if any(
        profile_id in taggs_id or taggs_id in profile_id
        for profile_id in profile_ids
        for taggs_id in taggs_ids
    ):
        return IDENTIFIER_BONUS_PARTIAL, "award_identifier_partial"
    return Decimal("0"), "scored_candidate"


def score_profile_to_taggs(
    profile_row: ProfileReferenceRow,
    taggs_row: TaggsAwardAggregate,
) -> MatchCandidate:
    recipient_similarity = _combined_similarity(profile_row.grantee_name, taggs_row.legal_entity_name)
    title_similarity = max(
        _combined_similarity(profile_row.funding_opportunity_title, taggs_row.award_title),
        _combined_similarity(profile_row.nofo_title, taggs_row.award_title),
    )
    amount_similarity = _amount_similarity(profile_row.amount, taggs_row.total_sum_of_actions)
    location_similarity = _location_similarity(profile_row, taggs_row)
    listing_similarity = _listing_similarity(profile_row, taggs_row)
    office_similarity = _program_office_similarity(profile_row, taggs_row)
    identifier_bonus, match_method = _identifier_bonus(profile_row, taggs_row)

    weighted_score = (
        (recipient_similarity * WEIGHT_RECIPIENT)
        + (title_similarity * WEIGHT_TITLE)
        + (amount_similarity * WEIGHT_AMOUNT)
        + (location_similarity * WEIGHT_LOCATION)
        + (listing_similarity * WEIGHT_LISTING)
        + (office_similarity * WEIGHT_OFFICE)
    )
    final_score = min(Decimal("1"), weighted_score + identifier_bonus)

    if final_score >= STRONG_MATCH_THRESHOLD or (
        match_method == "award_identifier_exact" and weighted_score >= Decimal("0.65")
    ):
        strength = "strong_match"
    elif final_score >= PROBABLE_MATCH_THRESHOLD:
        strength = "probable_match"
    elif final_score >= WEAK_MATCH_THRESHOLD:
        strength = "weak_match"
    else:
        strength = "no_match"

    evidence_json = {
        "score_components": {
            "recipient_similarity": float(recipient_similarity),
            "title_similarity": float(title_similarity),
            "amount_similarity": float(amount_similarity),
            "location_similarity": float(location_similarity),
            "listing_similarity": float(listing_similarity),
            "program_office_similarity": float(office_similarity),
            "identifier_bonus": float(identifier_bonus),
        },
        "profile_identifiers": sorted(
            _extract_identifier_tokens(profile_row.project_number)
            | _extract_identifier_tokens(profile_row.reference_number)
            | _extract_identifier_tokens(profile_row.nofo_number)
        ),
        "taggs_identifiers": sorted(_extract_identifier_tokens(taggs_row.award_number)),
        "profile_grantee_name": profile_row.grantee_name,
        "taggs_legal_entity_name": taggs_row.legal_entity_name,
        "profile_title": profile_row.funding_opportunity_title or profile_row.nofo_title,
        "taggs_award_title": taggs_row.award_title,
        "profile_amount": float(profile_row.amount),
        "taggs_amount": float(taggs_row.total_sum_of_actions),
        "profile_category": profile_row.category,
        "profile_subcategory": profile_row.subcategory,
        "taggs_program_office": taggs_row.program_office,
        "taggs_assistance_listing_title": taggs_row.assistance_listing_title,
    }

    return MatchCandidate(
        can_code=taggs_row.can_code,
        fiscal_year=profile_row.fiscal_year,
        state_code=profile_row.state_code,
        matched_profile_row_id=profile_row.id,
        matched_taggs_row_id=taggs_row.representative_raw_award_id,
        match_score=final_score.quantize(Decimal("0.0001")),
        match_strength=strength,
        match_method=match_method,
        evidence_json=evidence_json,
    )


def resolve_effective_mapping(
    *,
    manual_row: dict[str, Any] | None,
    profile_row: dict[str, Any] | None,
    fallback_row: dict[str, Any] | None,
) -> dict[str, Any]:
    manual_row = dict(manual_row or {})
    profile_row = dict(profile_row or {})
    fallback_row = dict(fallback_row or {})

    manual_has_mapping = any(
        manual_row.get(field)
        for field in ("manual_program_name", "manual_category", "manual_subcategory")
    ) or bool(manual_row.get("is_manually_verified"))
    if manual_has_mapping:
        return {
            "effective_program_name": manual_row.get("manual_program_name")
            or profile_row.get("profile_inferred_program_name")
            or fallback_row.get("fallback_inferred_program_name"),
            "effective_category": manual_row.get("manual_category")
            or profile_row.get("profile_inferred_category")
            or fallback_row.get("fallback_inferred_category"),
            "effective_subcategory": manual_row.get("manual_subcategory")
            or profile_row.get("profile_inferred_subcategory")
            or fallback_row.get("fallback_inferred_subcategory"),
            "effective_mapping_method": MANUAL_OVERRIDE_METHOD,
        }

    profile_confidence = Decimal(str(profile_row.get("profile_match_confidence") or 0))
    if profile_row and profile_confidence >= PROFILE_ACCEPT_CONFIDENCE:
        return {
            "effective_program_name": profile_row.get("profile_inferred_program_name"),
            "effective_category": profile_row.get("profile_inferred_category"),
            "effective_subcategory": profile_row.get("profile_inferred_subcategory"),
            "effective_mapping_method": PROFILE_MATCH_METHOD,
        }

    fallback_confidence = Decimal(str(fallback_row.get("fallback_guess_confidence") or 0))
    if fallback_row and fallback_confidence >= FALLBACK_ACCEPT_CONFIDENCE:
        return {
            "effective_program_name": fallback_row.get("fallback_inferred_program_name"),
            "effective_category": fallback_row.get("fallback_inferred_category"),
            "effective_subcategory": fallback_row.get("fallback_inferred_subcategory"),
            "effective_mapping_method": FALLBACK_METHOD,
        }

    return {
        "effective_program_name": None,
        "effective_category": None,
        "effective_subcategory": None,
        "effective_mapping_method": UNKNOWN_METHOD,
    }


def _prefer_longer(existing: str | None, candidate: str | None) -> str | None:
    if not candidate:
        return existing
    if not existing:
        return candidate
    return candidate if len(candidate) > len(existing) else existing


def _row_is_domestic_scope(row: dict[str, Any]) -> bool:
    country = _normalize_code(row.get("legal_entity_country_normalized"))
    state = _normalize_code(row.get("legal_entity_state_normalized"))
    text_blob = " ".join(
        str(row.get(key) or "")
        for key in ("award_title", "assistance_listing_title", "award_description")
    )
    if country and country not in US_COUNTRY_TOKENS:
        return False
    if state and state not in DOMESTIC_SCOPE_CODES:
        return False
    if INTERNATIONAL_KEYWORD_RE.search(text_blob):
        return False
    return bool(country or state)


def aggregate_taggs_awards(raw_rows: Iterable[dict[str, Any]]) -> list[TaggsAwardAggregate]:
    aggregates: dict[tuple[Any, ...], TaggsAwardAggregate] = {}
    for row in raw_rows:
        award_number = _clean_text(row.get("award_number"))
        funding_fiscal_year = row.get("funding_fiscal_year")
        if award_number is None or funding_fiscal_year is None:
            continue
        key = (
            award_number,
            int(funding_fiscal_year),
            _normalize_code(row.get("can_code")),
            _normalize_code(row.get("legal_entity_state_normalized")),
            _normalize_code(row.get("legal_entity_county_normalized")),
            _clean_text(row.get("program_office")),
            _clean_text(row.get("aln")),
        )
        accumulator = aggregates.get(key)
        amount = Decimal(str(row.get("sum_of_actions") or 0))
        if accumulator is None:
            accumulator = TaggsAwardAggregate(
                representative_raw_award_id=int(row.get("id") or 0),
                award_number=award_number,
                funding_fiscal_year=int(funding_fiscal_year),
                can_code=_normalize_code(row.get("can_code")),
                legal_entity_state_normalized=_normalize_code(row.get("legal_entity_state_normalized")),
                legal_entity_county_normalized=_normalize_code(row.get("legal_entity_county_normalized")),
                legal_entity_country_normalized=_normalize_code(row.get("legal_entity_country_normalized")),
                program_office=_clean_text(row.get("program_office")),
                aln=_clean_text(row.get("aln")),
                assistance_listing_title=_clean_text(row.get("assistance_listing_title")),
                award_title=_clean_text(row.get("award_title")),
                award_description=_clean_text(row.get("award_description")),
                legal_entity_name=_clean_text(row.get("legal_entity_name")),
                legal_entity_city=_clean_text(row.get("legal_entity_city")),
                total_sum_of_actions=amount,
                raw_row_count=1,
                is_domestic_scope=_row_is_domestic_scope(row),
            )
            aggregates[key] = accumulator
            continue

        accumulator.representative_raw_award_id = min(
            accumulator.representative_raw_award_id,
            int(row.get("id") or accumulator.representative_raw_award_id),
        )
        accumulator.total_sum_of_actions += amount
        accumulator.raw_row_count += 1
        accumulator.is_domestic_scope = accumulator.is_domestic_scope and _row_is_domestic_scope(row)
        accumulator.award_title = _prefer_longer(accumulator.award_title, _clean_text(row.get("award_title")))
        accumulator.award_description = _prefer_longer(
            accumulator.award_description,
            _clean_text(row.get("award_description")),
        )
        accumulator.legal_entity_name = _prefer_longer(
            accumulator.legal_entity_name,
            _clean_text(row.get("legal_entity_name")),
        )
        accumulator.legal_entity_city = _prefer_longer(
            accumulator.legal_entity_city,
            _clean_text(row.get("legal_entity_city")),
        )
        accumulator.assistance_listing_title = _prefer_longer(
            accumulator.assistance_listing_title,
            _clean_text(row.get("assistance_listing_title")),
        )
        accumulator.legal_entity_country_normalized = (
            accumulator.legal_entity_country_normalized
            or _normalize_code(row.get("legal_entity_country_normalized"))
        )
    return list(aggregates.values())


def _candidate_amount_window(
    profile_amount: Decimal,
    taggs_amount: Decimal,
    *,
    strict: bool = True,
) -> bool:
    if taggs_amount == 0 or profile_amount == 0:
        return strict is False
    ratio = abs(profile_amount / taggs_amount)
    lower = Decimal("0.5") if strict else Decimal("0.1")
    upper = Decimal("2.0") if strict else Decimal("10.0")
    return lower <= ratio <= upper


def build_candidate_indexes(
    taggs_rows: Iterable[TaggsAwardAggregate],
) -> dict[str, Any]:
    by_state_year: defaultdict[tuple[int, str], list[TaggsAwardAggregate]] = defaultdict(list)
    by_award_identifier: defaultdict[tuple[int, str, str], list[TaggsAwardAggregate]] = defaultdict(list)
    by_grantee_token: defaultdict[tuple[int, str, str], list[TaggsAwardAggregate]] = defaultdict(list)
    by_title_token: defaultdict[tuple[int, str, str], list[TaggsAwardAggregate]] = defaultdict(list)
    by_row_id: dict[int, TaggsAwardAggregate] = {}

    for row in taggs_rows:
        state_code = _normalize_code(row.legal_entity_state_normalized)
        if not state_code:
            continue
        by_state_year[(row.funding_fiscal_year, state_code)].append(row)
        by_row_id[row.representative_raw_award_id] = row
        for identifier in _extract_identifier_tokens(row.award_number):
            by_award_identifier[(row.funding_fiscal_year, state_code, identifier)].append(row)
        for token in _tokenize(row.legal_entity_name):
            by_grantee_token[(row.funding_fiscal_year, state_code, token)].append(row)
        for token in _tokenize(row.award_title):
            by_title_token[(row.funding_fiscal_year, state_code, token)].append(row)

    return {
        "by_state_year": by_state_year,
        "by_award_identifier": by_award_identifier,
        "by_grantee_token": by_grantee_token,
        "by_title_token": by_title_token,
        "by_row_id": by_row_id,
    }


def select_candidate_rows(
    profile_row: ProfileReferenceRow,
    indexes: dict[str, Any],
) -> list[TaggsAwardAggregate]:
    state_year_key = (profile_row.fiscal_year, profile_row.state_code)
    candidates: dict[int, TaggsAwardAggregate] = {}

    for identifier in (
        _extract_identifier_tokens(profile_row.project_number)
        | _extract_identifier_tokens(profile_row.reference_number)
        | _extract_identifier_tokens(profile_row.nofo_number)
    ):
        for row in indexes["by_award_identifier"].get((*state_year_key, identifier), []):
            candidates[row.representative_raw_award_id] = row

    if not candidates:
        token_hits: Counter[int] = Counter()
        for token in _tokenize(profile_row.grantee_name):
            for row in indexes["by_grantee_token"].get((*state_year_key, token), []):
                token_hits[row.representative_raw_award_id] += 3
        for token in _tokenize(profile_row.funding_opportunity_title or profile_row.nofo_title):
            for row in indexes["by_title_token"].get((*state_year_key, token), []):
                token_hits[row.representative_raw_award_id] += 1
        for row_id, _score in token_hits.most_common(80):
            candidate = indexes["by_row_id"][row_id]
            if _candidate_amount_window(profile_row.amount, candidate.total_sum_of_actions):
                candidates[row_id] = candidate

    if not candidates:
        broad_candidates = []
        for row in indexes["by_state_year"].get(state_year_key, []):
            if _candidate_amount_window(profile_row.amount, row.total_sum_of_actions, strict=False):
                broad_candidates.append(row)
            if len(broad_candidates) >= 80:
                break
        for row in broad_candidates:
            candidates[row.representative_raw_award_id] = row

    return list(candidates.values())


def match_profile_rows_to_taggs_rows(
    profile_rows: Iterable[ProfileReferenceRow],
    taggs_rows: Iterable[TaggsAwardAggregate],
    *,
    verbose: bool = False,
) -> list[MatchCandidate]:
    indexes = build_candidate_indexes(taggs_rows)
    grouped_profiles: defaultdict[tuple[int, str], list[ProfileReferenceRow]] = defaultdict(list)
    for row in profile_rows:
        grouped_profiles[(row.fiscal_year, row.state_code)].append(row)

    selected_matches: list[MatchCandidate] = []
    for state_year_key, rows in sorted(grouped_profiles.items()):
        state_year_matches: list[tuple[ProfileReferenceRow, list[MatchCandidate]]] = []
        for profile_row in rows:
            scored = sorted(
                (
                    score_profile_to_taggs(profile_row, candidate)
                    for candidate in select_candidate_rows(profile_row, indexes)
                ),
                key=lambda item: (item.match_score, item.match_strength == "strong_match"),
                reverse=True,
            )
            state_year_matches.append((profile_row, scored))

        assigned_taggs_rows: set[int] = set()
        for profile_row, candidates in sorted(
            state_year_matches,
            key=lambda item: (
                item[1][0].match_score if item[1] else Decimal("0"),
                item[1][0].match_method == "award_identifier_exact" if item[1] else False,
            ),
            reverse=True,
        ):
            chosen = None
            for candidate in candidates:
                if candidate.matched_taggs_row_id in assigned_taggs_rows:
                    continue
                chosen = candidate
                break
            if chosen is None and candidates:
                chosen = candidates[0]
            if chosen is None or chosen.match_strength == "no_match":
                continue
            assigned_taggs_rows.add(chosen.matched_taggs_row_id)
            selected_matches.append(chosen)

        if verbose:
            print(
                "[match-state-year]",
                f"fy={state_year_key[0]}",
                f"state={state_year_key[1]}",
                f"profile_rows={len(rows)}",
                f"accepted={sum(1 for item in selected_matches if (item.fiscal_year, item.state_code) == state_year_key)}",
            )
    return selected_matches


def _weighted_choice(counter: Counter[str]) -> str | None:
    if not counter:
        return None
    return counter.most_common(1)[0][0]


def build_can_observations(
    taggs_rows: Iterable[TaggsAwardAggregate],
) -> dict[str, dict[str, Any]]:
    observations: dict[str, dict[str, Any]] = {}
    office_counters: defaultdict[str, Counter[str]] = defaultdict(Counter)
    aln_counters: defaultdict[str, Counter[str]] = defaultdict(Counter)
    listing_counters: defaultdict[str, Counter[str]] = defaultdict(Counter)
    title_counters: defaultdict[str, Counter[str]] = defaultdict(Counter)
    description_counters: defaultdict[str, Counter[str]] = defaultdict(Counter)

    for row in taggs_rows:
        can_code = _normalize_code(row.can_code)
        if not can_code:
            continue
        record = observations.setdefault(
            can_code,
            {
                "can_code": can_code,
                "observed_first_fy": row.funding_fiscal_year,
                "observed_last_fy": row.funding_fiscal_year,
                "observed_row_count": 0,
                "observed_total_funding": Decimal("0"),
                "fiscal_years": set(),
            },
        )
        record["observed_first_fy"] = min(record["observed_first_fy"], row.funding_fiscal_year)
        record["observed_last_fy"] = max(record["observed_last_fy"], row.funding_fiscal_year)
        record["observed_row_count"] += row.raw_row_count
        record["observed_total_funding"] += row.total_sum_of_actions
        record["fiscal_years"].add(row.funding_fiscal_year)
        weight = float(abs(row.total_sum_of_actions))
        if row.program_office:
            office_counters[can_code][row.program_office] += weight
        if row.aln:
            aln_counters[can_code][row.aln] += weight
        if row.assistance_listing_title:
            listing_counters[can_code][row.assistance_listing_title] += weight
        if row.award_title:
            title_counters[can_code][row.award_title] += weight
        if row.award_description:
            description_counters[can_code][row.award_description] += weight

    for can_code, record in observations.items():
        record["dominant_program_office"] = _weighted_choice(office_counters[can_code])
        record["dominant_aln"] = _weighted_choice(aln_counters[can_code])
        record["dominant_assistance_listing_title"] = _weighted_choice(listing_counters[can_code])
        record["dominant_award_title"] = _weighted_choice(title_counters[can_code])
        record["dominant_award_description"] = _weighted_choice(description_counters[can_code])
    return observations


def aggregate_profile_matches_by_can(
    matches: Iterable[MatchCandidate],
    profile_rows_by_id: dict[int, ProfileReferenceRow],
) -> dict[str, dict[str, Any]]:
    combos_by_can: defaultdict[str, Counter[tuple[str | None, str | None, str | None]]] = defaultdict(Counter)
    title_counter_by_can: defaultdict[str, Counter[str]] = defaultdict(Counter)
    score_totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    amount_totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    state_sets: defaultdict[str, set[str]] = defaultdict(set)
    year_sets: defaultdict[str, set[int]] = defaultdict(set)
    evidence_rows: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    match_counts: defaultdict[str, int] = defaultdict(int)

    for match in matches:
        if match.match_strength not in {"strong_match", "probable_match"}:
            continue
        can_code = _normalize_code(match.can_code)
        if not can_code:
            continue
        profile_row = profile_rows_by_id.get(match.matched_profile_row_id)
        if profile_row is None:
            continue
        program_name = (
            profile_row.funding_opportunity_title
            or profile_row.nofo_title
            or profile_row.project_number
        )
        combo = (program_name, profile_row.category, profile_row.subcategory)
        combos_by_can[can_code][combo] += float(abs(profile_row.amount))
        if program_name:
            title_counter_by_can[can_code][program_name] += float(abs(profile_row.amount))
        score_totals[can_code] += match.match_score * abs(profile_row.amount)
        amount_totals[can_code] += abs(profile_row.amount)
        state_sets[can_code].add(match.state_code)
        year_sets[can_code].add(match.fiscal_year)
        match_counts[can_code] += 1
        if len(evidence_rows[can_code]) < 8:
            evidence_rows[can_code].append(
                {
                    "profile_row_id": match.matched_profile_row_id,
                    "taggs_row_id": match.matched_taggs_row_id,
                    "score": float(match.match_score),
                    "strength": match.match_strength,
                    "fiscal_year": match.fiscal_year,
                    "state_code": match.state_code,
                }
            )

    output: dict[str, dict[str, Any]] = {}
    for can_code, combos in combos_by_can.items():
        dominant_combo, dominant_amount = combos.most_common(1)[0]
        total_amount = Decimal(str(sum(combos.values())))
        weighted_score = (
            score_totals[can_code] / amount_totals[can_code]
            if amount_totals[can_code] > 0
            else Decimal("0")
        )
        agreement_share = (
            Decimal(str(dominant_amount)) / total_amount
            if total_amount > 0
            else Decimal("0")
        )
        state_factor = min(Decimal(str(len(state_sets[can_code]))) / Decimal("8"), Decimal("1"))
        year_factor = min(Decimal(str(len(year_sets[can_code]))) / Decimal("3"), Decimal("1"))
        confidence = (
            (agreement_share * Decimal("0.45"))
            + (weighted_score * Decimal("0.25"))
            + (state_factor * Decimal("0.15"))
            + (year_factor * Decimal("0.15"))
        ) * Decimal("100")

        output[can_code] = {
            "profile_inferred_program_name": dominant_combo[0],
            "profile_inferred_category": dominant_combo[1],
            "profile_inferred_subcategory": dominant_combo[2],
            "profile_match_count": match_counts[can_code],
            "profile_match_confidence": confidence.quantize(Decimal("0.01")),
            "profile_match_evidence_json": {
                "states_covered": sorted(state_sets[can_code]),
                "years_covered": sorted(year_sets[can_code]),
                "funding_weighted_agreement": float(agreement_share),
                "weighted_match_score": float(weighted_score),
                "top_combinations": [
                    {
                        "program_name": combo[0],
                        "category": combo[1],
                        "subcategory": combo[2],
                        "matched_amount": float(amount),
                    }
                    for combo, amount in combos.most_common(5)
                ],
                "representative_matches": evidence_rows[can_code],
            },
        }
    return output


def infer_fallback_mappings(
    can_observations: dict[str, dict[str, Any]],
    profile_mappings: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    exact_signature_lookup: defaultdict[tuple[str, str, str], Counter[tuple[str | None, str | None, str | None]]] = defaultdict(Counter)
    office_aln_lookup: defaultdict[tuple[str, str], Counter[tuple[str | None, str | None, str | None]]] = defaultdict(Counter)
    office_listing_lookup: defaultdict[tuple[str, str], Counter[tuple[str | None, str | None, str | None]]] = defaultdict(Counter)
    aln_lookup: defaultdict[str, Counter[tuple[str | None, str | None, str | None]]] = defaultdict(Counter)
    listing_lookup: defaultdict[str, Counter[tuple[str | None, str | None, str | None]]] = defaultdict(Counter)

    for can_code, mapping in profile_mappings.items():
        observation = can_observations.get(can_code)
        if observation is None:
            continue
        if Decimal(str(mapping.get("profile_match_confidence") or 0)) < PROFILE_ACCEPT_CONFIDENCE:
            continue
        combo = (
            mapping.get("profile_inferred_program_name"),
            mapping.get("profile_inferred_category"),
            mapping.get("profile_inferred_subcategory"),
        )
        weight = float(observation.get("observed_total_funding") or 0)
        office = _normalize_free_text(observation.get("dominant_program_office")).strip()
        aln = _normalize_identifier_token(observation.get("dominant_aln"))
        listing = _normalize_free_text(observation.get("dominant_assistance_listing_title")).strip()
        if office and aln and listing:
            exact_signature_lookup[(office, aln, listing)][combo] += weight
        if office and aln:
            office_aln_lookup[(office, aln)][combo] += weight
        if office and listing:
            office_listing_lookup[(office, listing)][combo] += weight
        if aln:
            aln_lookup[aln][combo] += weight
        if listing:
            listing_lookup[listing][combo] += weight

    fallback_rows: dict[str, dict[str, Any]] = {}
    for can_code, observation in can_observations.items():
        if can_code in profile_mappings:
            continue
        office = _normalize_free_text(observation.get("dominant_program_office")).strip()
        aln = _normalize_identifier_token(observation.get("dominant_aln"))
        listing = _normalize_free_text(observation.get("dominant_assistance_listing_title")).strip()
        match_counter: Counter[tuple[str | None, str | None, str | None]] | None = None
        evidence: dict[str, Any] = {
            "dominant_program_office": observation.get("dominant_program_office"),
            "dominant_aln": observation.get("dominant_aln"),
            "dominant_assistance_listing_title": observation.get("dominant_assistance_listing_title"),
            "dominant_award_title": observation.get("dominant_award_title"),
            "dominant_award_description": observation.get("dominant_award_description"),
        }
        confidence = Decimal("0")

        if office and aln and listing and exact_signature_lookup.get((office, aln, listing)):
            match_counter = exact_signature_lookup[(office, aln, listing)]
            confidence = Decimal("85.00")
            evidence["fallback_basis"] = "exact_program_office_aln_listing_signature"
        elif office and aln and office_aln_lookup.get((office, aln)):
            match_counter = office_aln_lookup[(office, aln)]
            confidence = Decimal("75.00")
            evidence["fallback_basis"] = "exact_program_office_aln_signature"
        elif office and listing and office_listing_lookup.get((office, listing)):
            match_counter = office_listing_lookup[(office, listing)]
            confidence = Decimal("70.00")
            evidence["fallback_basis"] = "exact_program_office_listing_signature"
        elif aln and aln_lookup.get(aln):
            match_counter = aln_lookup[aln]
            confidence = Decimal("60.00")
            evidence["fallback_basis"] = "exact_aln_signature"
        elif listing and listing_lookup.get(listing):
            match_counter = listing_lookup[listing]
            confidence = Decimal("55.00")
            evidence["fallback_basis"] = "exact_listing_signature"

        if match_counter:
            dominant_combo, _weight = match_counter.most_common(1)[0]
            fallback_rows[can_code] = {
                "fallback_inferred_program_name": dominant_combo[0],
                "fallback_inferred_category": dominant_combo[1],
                "fallback_inferred_subcategory": dominant_combo[2],
                "fallback_guess_confidence": confidence.quantize(Decimal("0.01")),
                "fallback_guess_evidence_json": evidence,
            }
            continue

        dominant_program = observation.get("dominant_award_title") or observation.get("dominant_assistance_listing_title")
        dominant_category = observation.get("dominant_program_office")
        dominant_subcategory = observation.get("dominant_assistance_listing_title")
        stability_factor = min(
            Decimal(str(len(observation.get("fiscal_years") or ()))) / Decimal("3"),
            Decimal("1"),
        )
        text_blob = _normalize_free_text(
            " ".join(
                str(observation.get(field) or "")
                for field in (
                    "dominant_program_office",
                    "dominant_assistance_listing_title",
                    "dominant_award_title",
                    "dominant_award_description",
                )
            )
        )
        keyword_basis = None
        if "vaccines for children" in text_blob or " vfc " in text_blob:
            dominant_program = dominant_program or "Vaccines for Children"
            dominant_category = "Immunization"
            dominant_subcategory = "Vaccines for Children"
            keyword_basis = "vaccines_for_children_keyword"
        elif "drug free communit" in text_blob:
            dominant_program = dominant_program or "Drug Free Communities"
            dominant_category = dominant_category or "Drug Free Communities"
            dominant_subcategory = "Drug Free Communities"
            keyword_basis = "drug_free_communities_keyword"
        elif "covid" in text_blob or "coronavirus" in text_blob or "phssef" in text_blob:
            dominant_program = dominant_program or "COVID-19 / PHSSEF"
            dominant_category = dominant_category or "Public Health Emergency Response"
            dominant_subcategory = dominant_subcategory or "COVID-19 Activities"
            keyword_basis = "covid_keyword"

        base_confidence = Decimal("35.00")
        if dominant_category:
            base_confidence += Decimal("10.00")
        if dominant_subcategory:
            base_confidence += Decimal("10.00")
        if dominant_program:
            base_confidence += Decimal("5.00")
        base_confidence += stability_factor * Decimal("15.00")
        if keyword_basis:
            base_confidence += Decimal("10.00")
        fallback_rows[can_code] = {
            "fallback_inferred_program_name": dominant_program,
            "fallback_inferred_category": dominant_category,
            "fallback_inferred_subcategory": dominant_subcategory,
            "fallback_guess_confidence": min(base_confidence, Decimal("60.00")).quantize(Decimal("0.01")),
            "fallback_guess_evidence_json": {
                **evidence,
                "fallback_basis": keyword_basis or "dominant_taggs_metadata",
                "year_span": sorted(observation.get("fiscal_years") or []),
            },
        }
    return fallback_rows


def derive_funding_stream_fields(
    row: dict[str, Any],
    manual_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manual_row = dict(manual_row or {})
    if manual_row.get("funding_stream") or manual_row.get("appropriation_type"):
        funding_stream = manual_row.get("funding_stream")
        appropriation_type = manual_row.get("appropriation_type")
        return {
            "funding_stream": funding_stream,
            "appropriation_type": appropriation_type,
            "is_covid_related": manual_row.get("is_covid_related"),
            "is_arpa_related": manual_row.get("is_arpa_related"),
            "is_supplemental": manual_row.get("is_supplemental"),
            "is_regular_appropriation": manual_row.get("is_regular_appropriation"),
        }

    text_blob = _normalize_free_text(
        " ".join(
            str(row.get(field) or "")
            for field in (
                "effective_program_name",
                "effective_category",
                "effective_subcategory",
                "dominant_program_office",
                "dominant_assistance_listing_title",
            )
        )
    )
    for needle, mapping in FUNDING_STREAM_RULES:
        if needle in text_blob:
            return dict(mapping)

    funding_stream = (
        row.get("effective_subcategory")
        or row.get("effective_program_name")
        or row.get("effective_category")
        or UNKNOWN_LABEL
    )
    return {
        "funding_stream": funding_stream,
        "appropriation_type": "regular" if funding_stream != UNKNOWN_LABEL else "unknown",
        "is_covid_related": False,
        "is_arpa_related": False,
        "is_supplemental": False,
        "is_regular_appropriation": funding_stream != UNKNOWN_LABEL,
    }


def build_classification_rows(
    *,
    can_observations: dict[str, dict[str, Any]],
    profile_mappings: dict[str, dict[str, Any]],
    fallback_mappings: dict[str, dict[str, Any]],
    manual_overrides: dict[str, dict[str, Any]],
    existing_rows: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    existing_rows = existing_rows or {}
    all_can_codes = sorted(set(can_observations) | set(manual_overrides) | set(existing_rows))
    rows: list[dict[str, Any]] = []
    for can_code in all_can_codes:
        observation = dict(can_observations.get(can_code) or {})
        manual_row = dict(existing_rows.get(can_code) or {})
        manual_row.update(manual_overrides.get(can_code) or {})
        profile_row = dict(profile_mappings.get(can_code) or {})
        fallback_row = dict(fallback_mappings.get(can_code) or {})
        effective = resolve_effective_mapping(
            manual_row=manual_row,
            profile_row=profile_row,
            fallback_row=fallback_row,
        )
        derived_stream = derive_funding_stream_fields(
            {**observation, **profile_row, **fallback_row, **effective},
            manual_row=manual_row,
        )

        row = {
            "can_code": can_code,
            "funding_stream": derived_stream.get("funding_stream"),
            "appropriation_type": derived_stream.get("appropriation_type"),
            "category_override": manual_row.get("manual_category"),
            "subcategory_override": manual_row.get("manual_subcategory"),
            "notes": manual_row.get("notes") or manual_row.get("manual_notes"),
            "is_covid_related": derived_stream.get("is_covid_related"),
            "is_arpa_related": derived_stream.get("is_arpa_related"),
            "is_supplemental": derived_stream.get("is_supplemental"),
            "is_regular_appropriation": derived_stream.get("is_regular_appropriation"),
            "observed_first_fy": observation.get("observed_first_fy"),
            "observed_last_fy": observation.get("observed_last_fy"),
            "observed_row_count": observation.get("observed_row_count"),
            "observed_total_funding": observation.get("observed_total_funding"),
            "dominant_program_office": observation.get("dominant_program_office"),
            "dominant_aln": observation.get("dominant_aln"),
            "dominant_assistance_listing_title": observation.get("dominant_assistance_listing_title"),
            "profile_inferred_program_name": profile_row.get("profile_inferred_program_name"),
            "profile_inferred_category": profile_row.get("profile_inferred_category"),
            "profile_inferred_subcategory": profile_row.get("profile_inferred_subcategory"),
            "profile_match_count": profile_row.get("profile_match_count"),
            "profile_match_confidence": profile_row.get("profile_match_confidence"),
            "profile_match_evidence_json": profile_row.get("profile_match_evidence_json") or {},
            "fallback_inferred_program_name": fallback_row.get("fallback_inferred_program_name"),
            "fallback_inferred_category": fallback_row.get("fallback_inferred_category"),
            "fallback_inferred_subcategory": fallback_row.get("fallback_inferred_subcategory"),
            "fallback_guess_confidence": fallback_row.get("fallback_guess_confidence"),
            "fallback_guess_evidence_json": fallback_row.get("fallback_guess_evidence_json") or {},
            "manual_program_name": manual_row.get("manual_program_name"),
            "manual_category": manual_row.get("manual_category"),
            "manual_subcategory": manual_row.get("manual_subcategory"),
            "manual_notes": manual_row.get("manual_notes"),
            "is_manually_verified": bool(manual_row.get("is_manually_verified")),
            **effective,
            "can_mapping_version": CAN_MAPPING_VERSION,
            "updated_at": datetime.now(timezone.utc),
        }
        rows.append(row)
    return rows


def build_review_rows(classification_rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [
        {
            "can_code": row.get("can_code"),
            "effective_program_name": row.get("effective_program_name"),
            "effective_category": row.get("effective_category"),
            "effective_subcategory": row.get("effective_subcategory"),
            "effective_mapping_method": row.get("effective_mapping_method"),
            "profile_match_count": row.get("profile_match_count"),
            "profile_match_confidence": row.get("profile_match_confidence"),
            "fallback_guess_confidence": row.get("fallback_guess_confidence"),
            "dominant_program_office": row.get("dominant_program_office"),
            "dominant_aln": row.get("dominant_aln"),
            "observed_total_funding": row.get("observed_total_funding"),
            "is_manually_verified": row.get("is_manually_verified"),
        }
        for row in classification_rows
    ]
    priority_by_method = {
        UNKNOWN_METHOD: 0,
        FALLBACK_METHOD: 1,
        PROFILE_MATCH_METHOD: 2,
        MANUAL_OVERRIDE_METHOD: 3,
    }
    rows.sort(
        key=lambda row: (
            priority_by_method.get(str(row.get("effective_mapping_method") or UNKNOWN_METHOD), 9),
            float(row.get("profile_match_confidence") or row.get("fallback_guess_confidence") or 0),
            -float(row.get("observed_total_funding") or 0),
            str(row.get("can_code") or ""),
        )
    )
    return rows


def export_review_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_HEADER)
        writer.writeheader()
        for row in rows:
            serialized = {}
            for key in REVIEW_HEADER:
                value = row.get(key)
                if isinstance(value, Decimal):
                    serialized[key] = str(value)
                else:
                    serialized[key] = value
            writer.writerow(serialized)


def _table_exists(connection: Any, table_name: str) -> bool:
    row = connection.execute(
        text("SELECT to_regclass(:table_name) AS exists"),
        {"table_name": table_name},
    ).mappings().one()
    return row["exists"] is not None


def fetch_profile_reference_rows(
    connection: Any,
    *,
    years: Iterable[int],
) -> list[ProfileReferenceRow]:
    rows = connection.execute(
        text(
            f"""
            SELECT
                id,
                fiscal_year,
                state_code,
                category,
                subcategory,
                grantee_name,
                city,
                county,
                amount,
                project_number,
                reference_number,
                nofo_number,
                nofo_title,
                COALESCE(funding_opportunity_title, project_title) AS funding_opportunity_title
            FROM {RAW_PROFILE_ROWS_TABLE}
            WHERE fiscal_year = ANY(:years)
              AND state_code IS NOT NULL
            """
        ),
        {"years": list(years)},
    ).mappings().all()
    return [
        ProfileReferenceRow(
            id=int(row["id"]),
            fiscal_year=int(row["fiscal_year"]),
            state_code=str(row["state_code"]).strip().upper(),
            category=_clean_text(row.get("category")),
            subcategory=_clean_text(row.get("subcategory")),
            grantee_name=_clean_text(row.get("grantee_name")),
            city=_clean_text(row.get("city")),
            county=_clean_text(row.get("county")),
            amount=Decimal(str(row.get("amount") or 0)),
            project_number=_clean_text(row.get("project_number")),
            reference_number=_clean_text(row.get("reference_number")),
            nofo_number=_clean_text(row.get("nofo_number")),
            nofo_title=_clean_text(row.get("nofo_title")),
            funding_opportunity_title=_clean_text(row.get("funding_opportunity_title")),
        )
        for row in rows
    ]


def fetch_taggs_raw_rows(
    connection: Any,
    *,
    years: Iterable[int] | None = None,
    can_codes: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    filters = ["funding_fiscal_year IS NOT NULL"]
    params: dict[str, Any] = {}
    if years:
        filters.append("funding_fiscal_year = ANY(:years)")
        params["years"] = list(years)
    if can_codes:
        filters.append("can_code = ANY(:can_codes)")
        params["can_codes"] = list(can_codes)
    where_sql = " AND ".join(filters)
    rows = connection.execute(
        text(
            f"""
            SELECT
                id,
                issue_date_fiscal_year,
                opdiv,
                program_office,
                legal_entity_name,
                legal_entity_city,
                legal_entity_state_normalized,
                legal_entity_county_normalized,
                legal_entity_country_normalized,
                award_number,
                award_title,
                award_description,
                aln,
                assistance_listing_title,
                funding_fiscal_year,
                can_code,
                sum_of_actions
            FROM {RAW_AWARDS_TABLE}
            WHERE {where_sql}
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


def fetch_existing_classification_rows(connection: Any) -> dict[str, dict[str, Any]]:
    if not _table_exists(connection, f"{CAN_CLASSIFICATION_TABLE.schema}.{CAN_CLASSIFICATION_TABLE.name}"):
        return {}
    rows = connection.execute(
        text(f"SELECT * FROM {CAN_CLASSIFICATION_TABLE.schema}.{CAN_CLASSIFICATION_TABLE.name}")
    ).mappings().all()
    return {
        _normalize_code(row.get("can_code")): dict(row)
        for row in rows
        if _normalize_code(row.get("can_code"))
    }


def resolve_target_can_codes(
    existing_rows: dict[str, dict[str, Any]],
    *,
    explicit_can_codes: Iterable[str] | None,
    only_unmapped: bool,
) -> set[str] | None:
    explicit = {_normalize_code(can_code) for can_code in (explicit_can_codes or []) if _normalize_code(can_code)}
    explicit = {item for item in explicit if item}
    if not only_unmapped:
        return explicit or None
    if not existing_rows:
        return explicit or None
    unresolved = {
        can_code
        for can_code, row in existing_rows.items()
        if str(row.get("effective_mapping_method") or UNKNOWN_METHOD).strip().lower() in {"", UNKNOWN_METHOD}
    }
    return unresolved & explicit if explicit else unresolved


def write_can_classification_rows(
    connection: Any,
    *,
    rows: list[dict[str, Any]],
    audit_rows: list[dict[str, Any]],
    replace_all: bool,
    target_can_codes: set[str] | None,
) -> None:
    batch_size = 250

    if replace_all:
        connection.execute(text(f"TRUNCATE TABLE {MATCH_AUDIT_TABLE.schema}.{MATCH_AUDIT_TABLE.name} RESTART IDENTITY"))
        connection.execute(text(f"TRUNCATE TABLE {CAN_CLASSIFICATION_TABLE.schema}.{CAN_CLASSIFICATION_TABLE.name}"))
    elif target_can_codes:
        connection.execute(
            text(
                f"""
                DELETE FROM {MATCH_AUDIT_TABLE.schema}.{MATCH_AUDIT_TABLE.name}
                WHERE can_code = ANY(:can_codes)
                """
            ),
            {"can_codes": list(target_can_codes)},
        )

    if rows:
        for index in range(0, len(rows), batch_size):
            row_batch = rows[index : index + batch_size]
            insert_stmt = pg_insert(CAN_CLASSIFICATION_TABLE).values(row_batch)
            updatable_columns = {
                column.name: getattr(insert_stmt.excluded, column.name)
                for column in CAN_CLASSIFICATION_TABLE.columns
                if column.name != "can_code" and column.name != "created_at"
            }
            connection.execute(
                insert_stmt.on_conflict_do_update(
                    index_elements=[CAN_CLASSIFICATION_TABLE.c.can_code],
                    set_=updatable_columns,
                )
            )

    if audit_rows:
        if not replace_all and target_can_codes:
            connection.execute(
                text(
                    f"""
                    DELETE FROM {MATCH_AUDIT_TABLE.schema}.{MATCH_AUDIT_TABLE.name}
                    WHERE can_code = ANY(:can_codes)
                    """
                ),
                {"can_codes": list(target_can_codes)},
            )
        for index in range(0, len(audit_rows), batch_size):
            audit_batch = audit_rows[index : index + batch_size]
            connection.execute(MATCH_AUDIT_TABLE.insert(), audit_batch)


def build_can_profile_mapping(
    *,
    db_url: str,
    limit_years: Iterable[int] | None = None,
    limit_cans: Iterable[str] | None = None,
    only_unmapped: bool = False,
    export_review_csv_path: Path | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    engine = create_engine(db_url, pool_pre_ping=True)
    with engine.begin() as connection:
        existing_rows = fetch_existing_classification_rows(connection)
        target_can_codes = resolve_target_can_codes(
            existing_rows,
            explicit_can_codes=limit_cans,
            only_unmapped=only_unmapped,
        )

        requested_years = tuple(sorted(set(limit_years or (*TAGGS_PROFILE_TRAINING_YEARS, *TAGGS_LATER_YEARS))))
        raw_taggs_rows = fetch_taggs_raw_rows(
            connection,
            years=requested_years,
            can_codes=target_can_codes,
        )
        taggs_awards = aggregate_taggs_awards(raw_taggs_rows)
        can_observations = build_can_observations(taggs_awards)

        training_years = tuple(
            year
            for year in PROFILE_REFERENCE_YEARS
            if year in {row.funding_fiscal_year for row in taggs_awards}
        )
        profile_rows = fetch_profile_reference_rows(
            connection,
            years=PROFILE_REFERENCE_YEARS,
        )
        training_taggs_awards = [
            row
            for row in taggs_awards
            if row.funding_fiscal_year in training_years
            and (target_can_codes is None or _normalize_code(row.can_code) in target_can_codes)
        ]
        profile_rows = [
            row
            for row in profile_rows
            if row.fiscal_year in training_years
        ]
        if verbose:
            print(
                "[mapping-input]",
                f"profile_rows={len(profile_rows)}",
                f"taggs_award_rows={len(training_taggs_awards)}",
                f"training_years={list(training_years)}",
                f"target_can_codes={len(target_can_codes) if target_can_codes is not None else 'all'}",
            )

        matches = match_profile_rows_to_taggs_rows(
            profile_rows,
            training_taggs_awards,
            verbose=verbose,
        )
        profile_rows_by_id = {row.id: row for row in profile_rows}
        profile_mappings = aggregate_profile_matches_by_can(matches, profile_rows_by_id)
        fallback_mappings = infer_fallback_mappings(can_observations, profile_mappings)
        manual_overrides = load_seed_overrides()
        classification_rows = build_classification_rows(
            can_observations=can_observations,
            profile_mappings=profile_mappings,
            fallback_mappings=fallback_mappings,
            manual_overrides=manual_overrides,
            existing_rows=existing_rows,
        )

        if target_can_codes is not None:
            classification_rows = [
                row for row in classification_rows if _normalize_code(row.get("can_code")) in target_can_codes
            ]

        audit_rows = [
            {
                "can_code": _normalize_code(match.can_code),
                "fiscal_year": match.fiscal_year,
                "state_code": match.state_code,
                "matched_profile_row_id": match.matched_profile_row_id,
                "matched_taggs_row_id": match.matched_taggs_row_id,
                "match_score": match.match_score,
                "match_strength": match.match_strength,
                "match_method": match.match_method,
                "evidence_json": match.evidence_json,
                "can_mapping_version": CAN_MAPPING_VERSION,
            }
            for match in matches
            if _normalize_code(match.can_code)
            and (target_can_codes is None or _normalize_code(match.can_code) in target_can_codes)
        ]

        review_rows = build_review_rows(classification_rows)
        if export_review_csv_path:
            export_review_csv(export_review_csv_path, review_rows)

        summary = {
            "can_mapping_version": CAN_MAPPING_VERSION,
            "training_profile_years_requested": list(PROFILE_REFERENCE_YEARS),
            "training_years_with_taggs_matches": list(training_years),
            "later_taggs_years": list(TAGGS_LATER_YEARS),
            "profile_row_count": len(profile_rows),
            "taggs_award_row_count": len(training_taggs_awards),
            "observed_can_count": len(can_observations),
            "matched_rows_total": len(matches),
            "matched_rows_strong": sum(1 for match in matches if match.match_strength == "strong_match"),
            "matched_rows_probable": sum(1 for match in matches if match.match_strength == "probable_match"),
            "matched_rows_weak": sum(1 for match in matches if match.match_strength == "weak_match"),
            "profile_mapped_can_count": sum(
                1 for row in classification_rows if row.get("effective_mapping_method") == PROFILE_MATCH_METHOD
            ),
            "fallback_mapped_can_count": sum(
                1 for row in classification_rows if row.get("effective_mapping_method") == FALLBACK_METHOD
            ),
            "manual_override_can_count": sum(
                1 for row in classification_rows if row.get("effective_mapping_method") == MANUAL_OVERRIDE_METHOD
            ),
            "unknown_can_count": sum(
                1 for row in classification_rows if row.get("effective_mapping_method") == UNKNOWN_METHOD
            ),
            "review_csv_path": str(export_review_csv_path) if export_review_csv_path else None,
        }
        if dry_run:
            return summary

        write_can_classification_rows(
            connection,
            rows=classification_rows,
            audit_rows=audit_rows,
            replace_all=target_can_codes is None,
            target_can_codes=target_can_codes,
        )
        return summary


def main() -> None:
    args = parse_args()
    review_path = (
        Path(args.export_review_csv).expanduser().resolve()
        if args.export_review_csv
        else None
    )
    summary = build_can_profile_mapping(
        db_url=args.db_url,
        limit_years=_parse_csv_years(args.limit_years),
        limit_cans=_parse_csv_cans(args.limit_cans),
        only_unmapped=bool(args.only_unmapped),
        export_review_csv_path=review_path,
        dry_run=bool(args.dry_run),
        verbose=bool(args.verbose),
    )
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
