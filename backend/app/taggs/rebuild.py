from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import create_engine, text

from app.db import DEFAULT_DB_URL
from app.db_fqtn import taggs_table
from app.recon import normalization as recon_normalization
from app.taggs.can_profile_matcher import (
    CAN_MAPPING_VERSION,
    FALLBACK_METHOD,
    PROFILE_MATCH_METHOD,
    UNKNOWN_LABEL,
    UNKNOWN_METHOD,
    UNKNOWN_COUNTY_TOKENS,
    aggregate_taggs_awards,
    fetch_existing_classification_rows,
    fetch_taggs_raw_rows,
)
from app.taggs.models import TaggsAwardFundingSummary, TaggsStateFundingSummary

AWARD_SUMMARY_TABLE = TaggsAwardFundingSummary.__table__
STATE_SUMMARY_TABLE = TaggsStateFundingSummary.__table__


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild TAGGS derived summary layers from CAN mapping.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or the local development DSN).",
    )
    parser.add_argument(
        "--limit-years",
        default=None,
        help="Optional comma-separated fiscal years to refresh.",
    )
    parser.add_argument(
        "--limit-cans",
        default=None,
        help="Optional comma-separated CAN codes to refresh.",
    )
    parser.add_argument(
        "--rebuild-normalization",
        action="store_true",
        help="Also rebuild recon.normalized_state_funding and related normalization outputs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build summary payloads without writing to the database.",
    )
    return parser.parse_args()


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).strip()
    return token or None


def _normalize_code(value: Any) -> str | None:
    token = _clean_text(value)
    return token.upper() if token else None


def _parse_csv_years(value: str | None) -> tuple[int, ...] | None:
    token = _clean_text(value)
    if not token:
        return None
    years = []
    for piece in token.split(","):
        part = piece.strip()
        if not part:
            continue
        try:
            years.append(int(part))
        except ValueError:
            continue
    return tuple(sorted(set(years))) or None


def _parse_csv_cans(value: str | None) -> tuple[str, ...] | None:
    token = _clean_text(value)
    if not token:
        return None
    return tuple(
        sorted(
            {
                _normalize_code(piece)
                for piece in token.split(",")
                if _normalize_code(piece)
            }
        )
    ) or None


def enrich_award_summary_rows(
    award_rows: Iterable[Any],
    classification_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    refreshed_at = datetime.now(timezone.utc)
    for award in award_rows:
        can_code = _normalize_code(getattr(award, "can_code", None))
        classification = classification_lookup.get(can_code or "", {})
        effective_method = _clean_text(classification.get("effective_mapping_method")) or UNKNOWN_METHOD
        funding_stream = _clean_text(classification.get("funding_stream")) or UNKNOWN_LABEL
        appropriation_type = _clean_text(classification.get("appropriation_type")) or "unknown"
        rows.append(
            {
                "award_number": award.award_number,
                "funding_fiscal_year": int(award.funding_fiscal_year),
                "can_code": can_code,
                "legal_entity_state_normalized": award.legal_entity_state_normalized,
                "legal_entity_county_normalized": award.legal_entity_county_normalized,
                "legal_entity_country_normalized": award.legal_entity_country_normalized,
                "program_office": award.program_office,
                "aln": award.aln,
                "assistance_listing_title": award.assistance_listing_title,
                "award_title": award.award_title,
                "award_description": award.award_description,
                "legal_entity_name": award.legal_entity_name,
                "legal_entity_city": award.legal_entity_city,
                "effective_program_name": classification.get("effective_program_name"),
                "effective_category": classification.get("effective_category"),
                "effective_subcategory": classification.get("effective_subcategory"),
                "effective_mapping_method": effective_method,
                "funding_stream": funding_stream,
                "appropriation_type": appropriation_type,
                "has_profile_assisted_mapping": effective_method == PROFILE_MATCH_METHOD,
                "has_fallback_inference": effective_method == FALLBACK_METHOD,
                "can_mapping_version": classification.get("can_mapping_version") or CAN_MAPPING_VERSION,
                "total_sum_of_actions": award.total_sum_of_actions.quantize(Decimal("0.01")),
                "raw_row_count": int(award.raw_row_count),
                "is_domestic_scope": bool(award.is_domestic_scope),
                "refreshed_at": refreshed_at,
            }
        )
    return rows


def build_state_funding_summary_rows(
    award_rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in award_rows:
        state_code = _normalize_code(row.get("legal_entity_state_normalized"))
        fiscal_year = row.get("funding_fiscal_year")
        if not state_code or fiscal_year is None:
            continue
        key = (
            int(fiscal_year),
            state_code,
            _normalize_code(row.get("can_code")),
            _clean_text(row.get("program_office")),
            _clean_text(row.get("aln")),
            _clean_text(row.get("effective_program_name")),
            _clean_text(row.get("effective_category")),
            _clean_text(row.get("effective_subcategory")),
            _clean_text(row.get("effective_mapping_method")),
            _clean_text(row.get("funding_stream")),
            _clean_text(row.get("appropriation_type")),
            bool(row.get("has_profile_assisted_mapping")),
            bool(row.get("has_fallback_inference")),
            _clean_text(row.get("can_mapping_version")),
            bool(row.get("is_domestic_scope")),
        )
        accumulator = grouped.get(key)
        if accumulator is None:
            accumulator = {
                "funding_fiscal_year": int(fiscal_year),
                "legal_entity_state_normalized": state_code,
                "can_code": _normalize_code(row.get("can_code")),
                "program_office": _clean_text(row.get("program_office")),
                "aln": _clean_text(row.get("aln")),
                "effective_program_name": _clean_text(row.get("effective_program_name")),
                "effective_category": _clean_text(row.get("effective_category")),
                "effective_subcategory": _clean_text(row.get("effective_subcategory")),
                "effective_mapping_method": _clean_text(row.get("effective_mapping_method")),
                "funding_stream": _clean_text(row.get("funding_stream")) or UNKNOWN_LABEL,
                "appropriation_type": _clean_text(row.get("appropriation_type")) or "unknown",
                "has_profile_assisted_mapping": bool(row.get("has_profile_assisted_mapping")),
                "has_fallback_inference": bool(row.get("has_fallback_inference")),
                "can_mapping_version": _clean_text(row.get("can_mapping_version")) or CAN_MAPPING_VERSION,
                "total_sum_of_actions": Decimal("0"),
                "award_numbers": set(),
                "recipient_names": set(),
                "counties": set(),
                "is_domestic_scope": bool(row.get("is_domestic_scope")),
            }
            grouped[key] = accumulator

        accumulator["total_sum_of_actions"] += Decimal(str(row.get("total_sum_of_actions") or 0))
        if row.get("award_number"):
            accumulator["award_numbers"].add(str(row["award_number"]))
        if row.get("legal_entity_name"):
            accumulator["recipient_names"].add(str(row["legal_entity_name"]).strip())
        county = _normalize_code(row.get("legal_entity_county_normalized"))
        if county and county not in UNKNOWN_COUNTY_TOKENS:
            accumulator["counties"].add(county)

    refreshed_at = datetime.now(timezone.utc)
    rows = []
    for accumulator in grouped.values():
        rows.append(
            {
                "funding_fiscal_year": accumulator["funding_fiscal_year"],
                "legal_entity_state_normalized": accumulator["legal_entity_state_normalized"],
                "can_code": accumulator["can_code"],
                "program_office": accumulator["program_office"],
                "aln": accumulator["aln"],
                "effective_program_name": accumulator["effective_program_name"],
                "effective_category": accumulator["effective_category"],
                "effective_subcategory": accumulator["effective_subcategory"],
                "effective_mapping_method": accumulator["effective_mapping_method"],
                "funding_stream": accumulator["funding_stream"],
                "appropriation_type": accumulator["appropriation_type"],
                "has_profile_assisted_mapping": accumulator["has_profile_assisted_mapping"],
                "has_fallback_inference": accumulator["has_fallback_inference"],
                "can_mapping_version": accumulator["can_mapping_version"],
                "total_sum_of_actions": accumulator["total_sum_of_actions"].quantize(Decimal("0.01")),
                "award_count": len(accumulator["award_numbers"]),
                "unique_recipient_count": len(accumulator["recipient_names"]),
                "unique_county_count": len(accumulator["counties"]),
                "is_domestic_scope": accumulator["is_domestic_scope"],
                "refreshed_at": refreshed_at,
            }
        )
    return rows


def _delete_existing_rows(
    connection: Any,
    *,
    table_name: str,
    year_column: str,
    years: Iterable[int] | None,
    can_codes: Iterable[str] | None,
) -> None:
    if not years and not can_codes:
        connection.execute(text(f"TRUNCATE TABLE {table_name} RESTART IDENTITY"))
        return
    clauses = []
    params: dict[str, Any] = {}
    if years:
        clauses.append(f"{year_column} = ANY(:years)")
        params["years"] = list(years)
    if can_codes:
        clauses.append("can_code = ANY(:can_codes)")
        params["can_codes"] = list(can_codes)
    connection.execute(
        text(
            f"""
            DELETE FROM {table_name}
            WHERE {" AND ".join(clauses)}
            """
        ),
        params,
    )


def rebuild_taggs_derived_layers(
    *,
    db_url: str,
    limit_years: Iterable[int] | None = None,
    limit_cans: Iterable[str] | None = None,
    rebuild_normalization: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    engine = create_engine(db_url, pool_pre_ping=True)
    with engine.begin() as connection:
        raw_rows = fetch_taggs_raw_rows(
            connection,
            years=limit_years,
            can_codes=limit_cans,
        )
        aggregated_awards = aggregate_taggs_awards(raw_rows)
        classification_lookup = fetch_existing_classification_rows(connection)
        enriched_awards = enrich_award_summary_rows(aggregated_awards, classification_lookup)
        state_rows = build_state_funding_summary_rows(enriched_awards)

        summary = {
            "award_summary_rows": len(enriched_awards),
            "state_summary_rows": len(state_rows),
            "limit_years": list(limit_years or []),
            "limit_cans": list(limit_cans or []),
            "rebuild_normalization": rebuild_normalization,
        }
        if dry_run:
            return summary

        _delete_existing_rows(
            connection,
            table_name=taggs_table("state_funding_summary"),
            year_column="funding_fiscal_year",
            years=limit_years,
            can_codes=limit_cans,
        )
        _delete_existing_rows(
            connection,
            table_name=taggs_table("award_funding_summary"),
            year_column="funding_fiscal_year",
            years=limit_years,
            can_codes=limit_cans,
        )
        if enriched_awards:
            connection.execute(AWARD_SUMMARY_TABLE.insert(), enriched_awards)
        if state_rows:
            connection.execute(STATE_SUMMARY_TABLE.insert(), state_rows)

    if rebuild_normalization and not dry_run:
        recon_normalization.rebuild(
            db_url=db_url,
            truncate=True,
            dry_run=False,
        )
        summary["normalization_rebuilt"] = True
    else:
        summary["normalization_rebuilt"] = False
    return summary


def main() -> None:
    args = parse_args()
    summary = rebuild_taggs_derived_layers(
        db_url=args.db_url,
        limit_years=_parse_csv_years(args.limit_years),
        limit_cans=_parse_csv_cans(args.limit_cans),
        rebuild_normalization=bool(args.rebuild_normalization),
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
