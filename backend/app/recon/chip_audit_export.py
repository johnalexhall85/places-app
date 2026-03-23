from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import create_engine, text

from app.cdc_funding.intelligence import canonical_program_area, classify_mechanism, classify_recipient_type
from app.db import DEFAULT_DB_URL
from app.db_fqtn import cdc_funding_table, places_table, recon_table, taggs_table, usaspending_table
from app.recon.profile_scope import METHODOLOGY_VERSION as PROFILE_SCOPE_METHODOLOGY_VERSION
from app.services.chip_funding_model import FUNDING_MODEL_VERSION

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EXPORTS_ROOT = REPO_ROOT / "exports"

PROFILE_SCOPE_TX_TABLE = recon_table("profile_scope_transactions")
ASSISTANCE_PROFILE_TABLE = recon_table("assistance_transactions_profile_enriched")
CONTRACT_PROFILE_TABLE = recon_table("contract_transactions_profile_enriched")
NORMALIZED_TABLE = recon_table("normalized_state_funding")
PRIME_TX_TABLE = cdc_funding_table("prime_transactions")
PRIME_AWARD_TABLE = cdc_funding_table("prime_awards")
CONTRACT_TABLE = usaspending_table("contract_transactions_raw")
TAGGS_RAW_TABLE = taggs_table("raw_awards")
TAGGS_SUMMARY_TABLE = taggs_table("award_funding_summary")
STATE_DIM_TABLE = places_table("dim_state_boundary")
COUNTY_DIM_TABLE = places_table("dim_county")

EXPORT_FILE_NAMES = {
    "included": "chip_model_transactions_included.csv",
    "excluded": "chip_model_transactions_excluded.csv",
    "unresolved": "chip_model_transactions_null_inclusion.csv",
    "dictionary": "chip_model_data_dictionary.csv",
    "readme": "chip_model_readme_methodology.md",
    "validation": "chip_model_validation_summary.csv",
}

APPEARS_IN_TRANSACTION_FILES = ";".join(
    [
        EXPORT_FILE_NAMES["included"],
        EXPORT_FILE_NAMES["excluded"],
        EXPORT_FILE_NAMES["unresolved"],
    ]
)

CHIP_AUDIT_COLUMNS = [
    "chip_row_id",
    "chip_model_version",
    "chip_export_timestamp",
    "chip_export_batch_id",
    "chip_inclusion_flag",
    "chip_inclusion_bucket",
    "chip_inclusion_reason",
    "chip_inclusion_reason_detail",
    "chip_review_status",
    "chip_data_source_primary",
    "chip_data_source_secondary",
    "chip_join_method",
    "chip_join_status",
    "chip_join_confidence",
    "chip_provenance_notes",
    "chip_funding_fy",
    "chip_net_amount_for_model",
    "chip_normalized_amount",
    "chip_geography_level",
    "chip_state_fips",
    "chip_county_fips",
    "chip_county_name_standardized",
    "chip_program_area_standardized",
]

PROVENANCE_COLUMNS = [
    "prov_usaspending_source_file",
    "prov_usaspending_extract_date",
    "prov_usaspending_table_name",
    "prov_usaspending_record_id",
    "prov_taggs_source_file",
    "prov_taggs_extract_date",
    "prov_taggs_table_name",
    "prov_taggs_record_id",
    "prov_merge_run_id",
    "prov_transformation_stage",
    "prov_last_modified_by_process",
]

CHIP_MODEL_VERSION = f"{FUNDING_MODEL_VERSION}+{PROFILE_SCOPE_METHODOLOGY_VERSION}"
EXPORT_PROCESS_NAME = "chip_funding_audit_export_v1"
NULL_BUCKET = "unresolved"
PROGRESS_ROW_INTERVAL = 10_000

NON_WORD_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class RawFieldSpec:
    source_system: str
    source_subsystem: str
    record_field: str
    payload_field: str
    output_prefix: str
    original_key: str
    output_column: str


@dataclass(frozen=True)
class AuditExportData:
    rows: list[dict[str, Any]]
    column_order: list[str]
    dictionary_rows: list[dict[str, Any]]
    model_total_normalized_amount: Decimal


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a reproducible CHIP funding audit export package.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or the local development DSN).",
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_EXPORTS_ROOT),
        help=f"Directory that will contain the dated export folder (default: {DEFAULT_EXPORTS_ROOT}).",
    )
    parser.add_argument(
        "--export-date",
        default=None,
        help="Optional UTC export date in YYYYMMDD format. Defaults to the current UTC date.",
    )
    parser.add_argument(
        "--overwrite",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Replace an existing dated export directory if present.",
    )
    return parser.parse_args()


def _normalize_identifier(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.strip().lower()
    token = NON_WORD_RE.sub("_", lowered).strip("_")
    return token or "field"


def _json_object_keys_query(table_name: str, json_column: str) -> str:
    return f"""
        SELECT DISTINCT key
        FROM (
            SELECT jsonb_object_keys({json_column}) AS key
            FROM {table_name}
            WHERE {json_column} IS NOT NULL
        ) AS raw_keys
        WHERE NULLIF(BTRIM(key), '') IS NOT NULL
        ORDER BY key
    """


def _table_exists(connection: Any, table_name: str) -> bool:
    row = connection.execute(
        text("SELECT to_regclass(:table_name) AS table_name"),
        {"table_name": table_name},
    ).mappings().one()
    return row.get("table_name") is not None


def _require_tables(connection: Any, table_names: Sequence[str]) -> None:
    missing = [table_name for table_name in table_names if not _table_exists(connection, table_name)]
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            "Required CHIP audit export tables are missing: "
            f"{joined}. Rebuild the CDC funding, USAspending, TAGGS, and profile-scope layers first."
        )


def _fetch_json_object_keys(connection: Any, *, table_name: str, json_column: str) -> list[str]:
    return [
        str(row["key"])
        for row in connection.execute(text(_json_object_keys_query(table_name, json_column))).mappings().all()
    ]


def _build_raw_field_specs(
    *,
    source_system: str,
    source_subsystem: str,
    record_field: str,
    payload_field: str,
    output_prefix: str,
    keys: Sequence[str],
) -> list[RawFieldSpec]:
    seen: set[str] = set()
    specs: list[RawFieldSpec] = []
    for key in sorted({str(item) for item in keys}, key=lambda value: value.lower()):
        base_column = f"{output_prefix}_{_normalize_identifier(key)}"
        output_column = base_column
        suffix = 2
        while output_column in seen:
            output_column = f"{base_column}_{suffix}"
            suffix += 1
        seen.add(output_column)
        specs.append(
            RawFieldSpec(
                source_system=source_system,
                source_subsystem=source_subsystem,
                record_field=record_field,
                payload_field=payload_field,
                output_prefix=output_prefix,
                original_key=key,
                output_column=output_column,
            )
        )
    return specs


def _normalized_aln_sql(expr: str) -> str:
    return f"LPAD(REGEXP_REPLACE(COALESCE({expr}, ''), '[^0-9]', '', 'g'), 5, '0')"


def _normalized_county_key_sql(expr: str) -> str:
    return f"UPPER(REGEXP_REPLACE(COALESCE({expr}, ''), '[^A-Za-z0-9]', '', 'g'))"


def _log_progress(message: str) -> None:
    print(f"[chip_audit_export] {message}", file=sys.stderr, flush=True)


def _taggs_best_candidates_ctes(candidate_relation: str = "taggs_candidates") -> str:
    return f"""
        taggs_ranked AS (
            SELECT
                candidates.*,
                MIN(rank) OVER (PARTITION BY source_transaction_id) AS best_rank
            FROM {candidate_relation} AS candidates
        ),
        taggs_best_rank AS (
            SELECT *
            FROM taggs_ranked
            WHERE rank = best_rank
        ),
        taggs_best AS (
            SELECT *
            FROM (
                SELECT
                    taggs_best_rank.*,
                    COUNT(*) OVER (PARTITION BY source_transaction_id) AS candidate_count,
                    ROW_NUMBER() OVER (
                        PARTITION BY source_transaction_id
                        ORDER BY
                            ABS(COALESCE(sum_of_actions, 0) - COALESCE(raw_amount, 0)),
                            id ASC
                    ) AS rn
                FROM taggs_best_rank
            ) AS ranked_candidates
            WHERE rn = 1
        )
    """


def _candidate_rows_query() -> str:
    county_dim_key = _normalized_county_key_sql("county.county_name")
    raw_county_key = _normalized_county_key_sql("raw.recipient_county_name")
    usaspending_aln = _normalized_aln_sql(
        "COALESCE(NULLIF(TRIM(pt.cfda_number), ''), NULLIF(TRIM(pa.cfda_program_num), ''))"
    )
    taggs_aln = _normalized_aln_sql(
        "COALESCE(NULLIF(TRIM(tr.transaction_aln), ''), NULLIF(TRIM(tr.aln), ''))"
    )
    return f"""
        WITH contract_county_lookup AS (
            SELECT
                raw.id AS raw_id,
                county.location_id AS county_fips
            FROM {CONTRACT_TABLE} AS raw
            LEFT JOIN {COUNTY_DIM_TABLE} AS county
                ON county.state_abbr = COALESCE(raw.normalized_recipient_state, raw.recipient_state_code)
               AND {county_dim_key} = {raw_county_key}
        ),
        tx_base AS (
            SELECT
                tx.source_system,
                tx.source_transaction_id,
                tx.fiscal_year,
                tx.state_code,
                tx.include_in_profile_scope,
                tx.inclusion_weight,
                tx.inclusion_reason,
                tx.confidence_label,
                tx.raw_amount,
                tx.normalized_profile_scope_amount,
                tx.methodology_version AS profile_scope_methodology_version,
                tx.effective_funding_stream,
                tx.funding_scope_method,
                tx.effective_funding_scope,
                tx.federal_account_symbol,
                tx.federal_account_count,
                tx.federal_account_combination_key,
                tx.account_structure_type,
                tx.multi_account_interpretation,
                tx.conservative_inclusion_reason,
                tx.manual_review_recommended,
                tx.component_account_scopes,
                COALESCE(ae.decision_context, ce.decision_context) AS decision_context,
                COALESCE(ae.exclusion_reason, ce.exclusion_reason) AS exclusion_reason,
                COALESCE(ae.recipient_country_name, ce.recipient_country_name) AS recipient_country_name,
                COALESCE(ae.awarding_agency_name, ce.awarding_agency_name) AS awarding_agency_name,
                COALESCE(ae.funding_agency_name, ce.funding_agency_name) AS funding_agency_name,
                COALESCE(ae.assistance_listing_title, ce.award_description) AS primary_program_title,
                COALESCE(ae.assistance_listing_number, '') AS assistance_listing_number,
                COALESCE(ce.contract_category_guess, '') AS contract_category_guess,
                to_jsonb(pt) AS prime_tx_record,
                to_jsonb(pa) AS prime_award_record,
                to_jsonb(uc) AS contract_record,
                norm.normalized_amount AS app_state_normalized_amount,
                state_dim.state_fips,
                COALESCE(
                    NULLIF(TRIM(pt.prime_award_transaction_recipient_county_fips_code), ''),
                    NULLIF(TRIM(pa.recipient_county_fips), ''),
                    NULLIF(TRIM(contract_lookup.county_fips), '')
                ) AS standardized_county_fips,
                county_dim.county_name AS standardized_county_name,
                NULLIF(TRIM(COALESCE(pt.award_id_fain, pa.fain)), '') AS award_number_key,
                {usaspending_aln} AS normalized_usaspending_aln,
                UPPER(COALESCE(tx.state_code, '')) AS state_key
            FROM {PROFILE_SCOPE_TX_TABLE} AS tx
            LEFT JOIN {ASSISTANCE_PROFILE_TABLE} AS ae
                ON tx.source_system = 'assistance'
               AND ae.source_transaction_id = tx.source_transaction_id
            LEFT JOIN {CONTRACT_PROFILE_TABLE} AS ce
                ON tx.source_system = 'contracts'
               AND ce.source_transaction_id = tx.source_transaction_id
            LEFT JOIN {PRIME_TX_TABLE} AS pt
                ON tx.source_system = 'assistance'
               AND tx.source_transaction_id = COALESCE(NULLIF(TRIM(pt.assistance_transaction_unique_key), ''), pt.id::text)
            LEFT JOIN {PRIME_AWARD_TABLE} AS pa
                ON pt.assistance_award_unique_key = pa.unique_key
            LEFT JOIN {CONTRACT_TABLE} AS uc
                ON tx.source_system = 'contracts'
               AND tx.source_transaction_id = COALESCE(NULLIF(TRIM(uc.contract_transaction_unique_key), ''), uc.id::text)
            LEFT JOIN contract_county_lookup AS contract_lookup
                ON contract_lookup.raw_id = uc.id
            LEFT JOIN {COUNTY_DIM_TABLE} AS county_dim
                ON county_dim.location_id = COALESCE(
                    NULLIF(TRIM(pt.prime_award_transaction_recipient_county_fips_code), ''),
                    NULLIF(TRIM(pa.recipient_county_fips), ''),
                    NULLIF(TRIM(contract_lookup.county_fips), '')
                )
            LEFT JOIN {STATE_DIM_TABLE} AS state_dim
                ON state_dim.state_abbr = tx.state_code
            LEFT JOIN {NORMALIZED_TABLE} AS norm
                ON norm.source_system = 'usaspending'
               AND norm.fiscal_year = tx.fiscal_year
               AND norm.state_code = tx.state_code
        ),
        assistance_tx AS MATERIALIZED (
            SELECT
                source_transaction_id,
                fiscal_year,
                raw_amount,
                award_number_key,
                normalized_usaspending_aln,
                state_key
            FROM tx_base
            WHERE source_system = 'assistance'
        ),
        taggs_base AS MATERIALIZED (
            SELECT
                tr.*,
                to_jsonb(tr) AS taggs_record,
                summary.effective_category AS taggs_effective_category,
                COALESCE(
                    summary.effective_program_name,
                    summary.effective_subcategory,
                    summary.assistance_listing_title
                ) AS taggs_effective_program_name,
                NULLIF(TRIM(tr.award_number), '') AS award_number_key,
                {taggs_aln} AS normalized_taggs_aln,
                UPPER(COALESCE(tr.legal_entity_state_normalized, '')) AS state_key
            FROM {TAGGS_RAW_TABLE} AS tr
            LEFT JOIN {TAGGS_SUMMARY_TABLE} AS summary
                ON summary.award_number = tr.award_number
               AND summary.funding_fiscal_year = tr.funding_fiscal_year
               AND COALESCE(summary.can_code, '') = COALESCE(tr.can_code, '')
               AND UPPER(COALESCE(summary.legal_entity_state_normalized, '')) =
                   UPPER(COALESCE(tr.legal_entity_state_normalized, ''))
        ),
        taggs_candidates AS (
            SELECT
                tx.source_transaction_id,
                tx.raw_amount,
                taggs.id,
                taggs.sum_of_actions,
                taggs.taggs_record,
                taggs.taggs_effective_category,
                taggs.taggs_effective_program_name,
                1 AS rank,
                'award_number_state_year' AS join_method,
                'high' AS join_confidence
            FROM assistance_tx AS tx
            JOIN taggs_base AS taggs
                ON tx.award_number_key IS NOT NULL
               AND taggs.award_number_key = tx.award_number_key
               AND taggs.funding_fiscal_year = tx.fiscal_year
               AND taggs.state_key = tx.state_key

            UNION ALL

            SELECT
                tx.source_transaction_id,
                tx.raw_amount,
                taggs.id,
                taggs.sum_of_actions,
                taggs.taggs_record,
                taggs.taggs_effective_category,
                taggs.taggs_effective_program_name,
                2 AS rank,
                'award_number_fiscal_year' AS join_method,
                'medium' AS join_confidence
            FROM assistance_tx AS tx
            JOIN taggs_base AS taggs
                ON tx.award_number_key IS NOT NULL
               AND taggs.award_number_key = tx.award_number_key
               AND taggs.funding_fiscal_year = tx.fiscal_year

            UNION ALL

            SELECT
                tx.source_transaction_id,
                tx.raw_amount,
                taggs.id,
                taggs.sum_of_actions,
                taggs.taggs_record,
                taggs.taggs_effective_category,
                taggs.taggs_effective_program_name,
                3 AS rank,
                'aln_state_year' AS join_method,
                'medium' AS join_confidence
            FROM assistance_tx AS tx
            JOIN taggs_base AS taggs
                ON tx.normalized_usaspending_aln <> '00000'
               AND taggs.normalized_taggs_aln = tx.normalized_usaspending_aln
               AND taggs.funding_fiscal_year = tx.fiscal_year
               AND taggs.state_key = tx.state_key

            UNION ALL

            SELECT
                tx.source_transaction_id,
                tx.raw_amount,
                taggs.id,
                taggs.sum_of_actions,
                taggs.taggs_record,
                taggs.taggs_effective_category,
                taggs.taggs_effective_program_name,
                4 AS rank,
                'aln_fiscal_year' AS join_method,
                'low' AS join_confidence
            FROM assistance_tx AS tx
            JOIN taggs_base AS taggs
                ON tx.normalized_usaspending_aln <> '00000'
               AND taggs.normalized_taggs_aln = tx.normalized_usaspending_aln
               AND taggs.funding_fiscal_year = tx.fiscal_year
        ),
        {_taggs_best_candidates_ctes()}
        SELECT
            tx.source_system,
            tx.source_transaction_id,
            tx.fiscal_year,
            tx.state_code,
            tx.include_in_profile_scope,
            tx.inclusion_weight,
            tx.inclusion_reason,
            tx.confidence_label,
            tx.raw_amount,
            tx.normalized_profile_scope_amount,
            tx.profile_scope_methodology_version,
            tx.effective_funding_stream,
            tx.funding_scope_method,
            tx.effective_funding_scope,
            tx.federal_account_symbol,
            tx.federal_account_count,
            tx.federal_account_combination_key,
            tx.account_structure_type,
            tx.multi_account_interpretation,
            tx.conservative_inclusion_reason,
            tx.manual_review_recommended,
            tx.component_account_scopes,
            tx.decision_context,
            tx.exclusion_reason,
            tx.recipient_country_name,
            tx.awarding_agency_name,
            tx.funding_agency_name,
            tx.primary_program_title,
            tx.assistance_listing_number,
            tx.contract_category_guess,
            tx.prime_tx_record,
            tx.prime_award_record,
            tx.contract_record,
            taggs_best.taggs_record AS taggs_record,
            taggs_best.join_method AS taggs_join_method,
            taggs_best.join_confidence AS taggs_join_confidence,
            taggs_best.candidate_count AS taggs_join_candidate_count,
            taggs_best.taggs_effective_category,
            taggs_best.taggs_effective_program_name,
            tx.app_state_normalized_amount,
            tx.state_fips,
            tx.standardized_county_fips,
            tx.standardized_county_name
        FROM tx_base AS tx
        LEFT JOIN taggs_best
            ON tx.source_system = 'assistance'
           AND taggs_best.source_transaction_id = tx.source_transaction_id
    """


def _as_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _quantize_money(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal("0.01"))


def _iso_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            return str(value)
    token = str(value).strip()
    return token or None


def _raw_payload(record: Any, payload_field: str) -> Mapping[str, Any]:
    if not isinstance(record, Mapping):
        return {}
    payload = record.get(payload_field)
    return payload if isinstance(payload, Mapping) else {}


def _serialize_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat") and not isinstance(value, str):
        try:
            return value.isoformat()
        except TypeError:
            pass
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return str(value)


def _display_name(value: str) -> str:
    return " ".join(piece.capitalize() for piece in value.replace("_", " ").split())


def _sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    def _token(value: Any) -> str:
        return str(value or "").strip().lower()

    return (
        int(row.get("chip_funding_fy") or 9999),
        _token(row.get("_sort_agency")),
        _token(row.get("chip_program_area_standardized")),
        _token(row.get("_sort_award_id")),
        _token(row.get("_sort_transaction_id")),
    )


def _bucket_for_flag(value: bool | None) -> str:
    if value is True:
        return "included"
    if value is False:
        return "excluded"
    return NULL_BUCKET


def _join_status(row: Mapping[str, Any], *, source_system: str) -> str:
    if source_system != "assistance":
        return "not_applicable"
    taggs_record = row.get("taggs_record")
    if not isinstance(taggs_record, Mapping):
        award_id = None
        prime_tx = row.get("prime_tx_record")
        prime_award = row.get("prime_award_record")
        if isinstance(prime_tx, Mapping):
            award_id = str(prime_tx.get("award_id_fain") or "").strip()
        if not award_id and isinstance(prime_award, Mapping):
            award_id = str(prime_award.get("fain") or "").strip()
        raw_aln = ""
        if isinstance(prime_tx, Mapping):
            raw_aln = str(prime_tx.get("cfda_number") or "").strip()
        if not raw_aln and isinstance(prime_award, Mapping):
            raw_aln = str(prime_award.get("cfda_program_num") or "").strip()
        return "unmatched" if award_id or raw_aln else "not_attempted"
    candidate_count = int(row.get("taggs_join_candidate_count") or 0)
    return "matched_ambiguous" if candidate_count > 1 else "matched"


def _map_inclusion_reason(row: Mapping[str, Any]) -> str:
    flag = row.get("include_in_profile_scope")
    decision_context = str(row.get("decision_context") or "").strip().lower()
    source_system = str(row.get("source_system") or "").strip().lower()
    state_code = str(row.get("state_code") or "").strip().upper()

    if flag is True:
        return "included_profile_scope"

    if flag is False:
        if not state_code:
            return "missing_geography"
        if any(token in decision_context for token in ("non_domestic", "international", "non_cdc")):
            return "non_cdc_or_out_of_scope"
        if "duplicate" in decision_context:
            return "duplicate_transaction"
        return "no_relevant_program_mapping"

    if not state_code:
        return "missing_geography"
    if source_system == "assistance" and _join_status(row, source_system=source_system) in {"unmatched", "not_attempted"}:
        return "failed_join"
    return "manual_review_required"


def _inclusion_reason_detail(row: Mapping[str, Any], *, join_status: str) -> str | None:
    parts = [
        str(row.get("inclusion_reason") or "").strip(),
        str(row.get("exclusion_reason") or "").strip(),
        str(row.get("conservative_inclusion_reason") or "").strip(),
        f"decision_context={row['decision_context']}" if row.get("decision_context") else "",
        f"join_status={join_status}" if join_status not in {"matched", "not_applicable"} else "",
    ]
    combined = " | ".join(part for part in parts if part)
    return combined or None


def _review_status(row: Mapping[str, Any]) -> str:
    manual_review = bool(row.get("manual_review_recommended"))
    flag = row.get("include_in_profile_scope")
    if manual_review or flag is None:
        return "manual_review_required"
    if flag is True:
        return "auto_included"
    return "auto_excluded"


def _provenance_notes(
    row: Mapping[str, Any],
    *,
    join_status: str,
    join_method: str | None,
) -> str | None:
    parts = [
        f"profile_scope_methodology={row.get('profile_scope_methodology_version')}"
        if row.get("profile_scope_methodology_version")
        else "",
        f"funding_scope_method={row.get('funding_scope_method')}" if row.get("funding_scope_method") else "",
        f"decision_context={row.get('decision_context')}" if row.get("decision_context") else "",
        f"taggs_join_status={join_status}",
        f"taggs_join_method={join_method}" if join_method else "",
    ]
    combined = "; ".join(part for part in parts if part)
    return combined or None


def _program_area_value(row: Mapping[str, Any]) -> str:
    taggs_effective_category = row.get("taggs_effective_category")
    taggs_program_name = row.get("taggs_effective_program_name")
    primary_program = row.get("primary_program_title")
    awarding_agency_name = row.get("awarding_agency_name")
    contract_category_guess = row.get("contract_category_guess")
    return canonical_program_area(
        taggs_effective_category,
        taggs_program_name,
        primary_program,
        awarding_agency_name,
        contract_category_guess,
    )


def _award_id(row: Mapping[str, Any]) -> str | None:
    prime_tx = row.get("prime_tx_record")
    if isinstance(prime_tx, Mapping):
        token = str(prime_tx.get("award_id_fain") or "").strip()
        if token:
            return token
    prime_award = row.get("prime_award_record")
    if isinstance(prime_award, Mapping):
        token = str(prime_award.get("fain") or "").strip()
        if token:
            return token
    contract_record = row.get("contract_record")
    if isinstance(contract_record, Mapping):
        for field_name in ("award_id_piid", "generated_unique_award_id", "contract_award_unique_key"):
            token = str(contract_record.get(field_name) or "").strip()
            if token:
                return token
    return None


def _primary_usaspending_record_id(row: Mapping[str, Any]) -> str | None:
    prime_tx = row.get("prime_tx_record")
    if isinstance(prime_tx, Mapping):
        token = str(prime_tx.get("assistance_transaction_unique_key") or "").strip()
        if token:
            return token
        identifier = prime_tx.get("id")
        if identifier is not None:
            return str(identifier)
    contract_record = row.get("contract_record")
    if isinstance(contract_record, Mapping):
        token = str(contract_record.get("contract_transaction_unique_key") or "").strip()
        if token:
            return token
        identifier = contract_record.get("id")
        if identifier is not None:
            return str(identifier)
    return None


def _usaspending_source_file(row: Mapping[str, Any]) -> str | None:
    prime_tx = row.get("prime_tx_record")
    if isinstance(prime_tx, Mapping):
        token = str(prime_tx.get("source_file_name") or "").strip()
        if token:
            return token
    contract_record = row.get("contract_record")
    if isinstance(contract_record, Mapping):
        token = str(contract_record.get("source_filename") or "").strip()
        if token:
            return token
    prime_award = row.get("prime_award_record")
    if isinstance(prime_award, Mapping):
        token = str(prime_award.get("source_file_name") or "").strip()
        if token:
            return token
    return None


def _usaspending_extract_date(row: Mapping[str, Any]) -> str | None:
    prime_tx = row.get("prime_tx_record")
    if isinstance(prime_tx, Mapping):
        token = _iso_date(prime_tx.get("source_imported_at"))
        if token:
            return token
    contract_record = row.get("contract_record")
    if isinstance(contract_record, Mapping):
        token = _iso_date(contract_record.get("loaded_at"))
        if token:
            return token
    prime_award = row.get("prime_award_record")
    if isinstance(prime_award, Mapping):
        token = _iso_date(prime_award.get("source_imported_at"))
        if token:
            return token
    return None


def _taggs_source_file(row: Mapping[str, Any]) -> str | None:
    taggs_record = row.get("taggs_record")
    if not isinstance(taggs_record, Mapping):
        return None
    for field_name in ("source_filename", "source_file"):
        token = str(taggs_record.get(field_name) or "").strip()
        if token:
            return token
    return None


def _taggs_extract_date(row: Mapping[str, Any]) -> str | None:
    taggs_record = row.get("taggs_record")
    if not isinstance(taggs_record, Mapping):
        return None
    return _iso_date(taggs_record.get("loaded_at"))


def _prepare_export_row(
    raw_row: Mapping[str, Any],
    *,
    raw_field_specs: Sequence[RawFieldSpec],
    export_timestamp: datetime,
    export_batch_id: str,
) -> dict[str, Any]:
    source_system = str(raw_row.get("source_system") or "").strip().lower()
    join_method = (
        str(raw_row.get("taggs_join_method") or "").strip()
        if source_system == "assistance"
        else "not_applicable"
    )
    join_status = _join_status(raw_row, source_system=source_system)
    join_confidence = (
        str(raw_row.get("taggs_join_confidence") or "").strip()
        if join_status in {"matched", "matched_ambiguous"}
        else None
    )
    normalized_county_fips = str(raw_row.get("standardized_county_fips") or "").strip() or None
    state_fips = str(raw_row.get("state_fips") or "").strip() or None
    program_area = _program_area_value(raw_row)
    geography_level = (
        "county"
        if normalized_county_fips
        else ("state" if str(raw_row.get("state_code") or "").strip() else "unknown")
    )
    net_amount = (
        _quantize_money(_as_decimal(raw_row.get("normalized_profile_scope_amount")))
        if raw_row.get("include_in_profile_scope") is True
        else (Decimal("0.00") if raw_row.get("include_in_profile_scope") is False else None)
    )
    export_row = {
        "chip_row_id": f"{source_system}:{raw_row['source_transaction_id']}",
        "chip_model_version": CHIP_MODEL_VERSION,
        "chip_export_timestamp": export_timestamp,
        "chip_export_batch_id": export_batch_id,
        "chip_inclusion_flag": raw_row.get("include_in_profile_scope"),
        "chip_inclusion_bucket": _bucket_for_flag(raw_row.get("include_in_profile_scope")),
        "chip_inclusion_reason": _map_inclusion_reason(raw_row),
        "chip_inclusion_reason_detail": _inclusion_reason_detail(raw_row, join_status=join_status),
        "chip_review_status": _review_status(raw_row),
        "chip_data_source_primary": "USAspending",
        "chip_data_source_secondary": "TAGGS"
        if join_status in {"matched", "matched_ambiguous"}
        else None,
        "chip_join_method": join_method or None,
        "chip_join_status": join_status,
        "chip_join_confidence": join_confidence,
        "chip_provenance_notes": _provenance_notes(raw_row, join_status=join_status, join_method=join_method or None),
        "chip_funding_fy": raw_row.get("fiscal_year"),
        "chip_net_amount_for_model": net_amount,
        "chip_normalized_amount": None,
        "chip_geography_level": geography_level,
        "chip_state_fips": state_fips,
        "chip_county_fips": normalized_county_fips,
        "chip_county_name_standardized": raw_row.get("standardized_county_name"),
        "chip_program_area_standardized": program_area,
        "prov_usaspending_source_file": _usaspending_source_file(raw_row),
        "prov_usaspending_extract_date": _usaspending_extract_date(raw_row),
        "prov_usaspending_table_name": (
            PRIME_TX_TABLE if source_system == "assistance" else CONTRACT_TABLE
        ),
        "prov_usaspending_record_id": _primary_usaspending_record_id(raw_row),
        "prov_taggs_source_file": _taggs_source_file(raw_row),
        "prov_taggs_extract_date": _taggs_extract_date(raw_row),
        "prov_taggs_table_name": TAGGS_RAW_TABLE if join_status in {"matched", "matched_ambiguous"} else None,
        "prov_taggs_record_id": (
            str(raw_row["taggs_record"].get("id"))
            if isinstance(raw_row.get("taggs_record"), Mapping) and raw_row["taggs_record"].get("id") is not None
            else None
        ),
        "prov_merge_run_id": export_batch_id,
        "prov_transformation_stage": "recon.profile_scope_transactions_to_chip_audit_export",
        "prov_last_modified_by_process": EXPORT_PROCESS_NAME,
        "_state_year_key": (
            (int(raw_row["fiscal_year"]), str(raw_row["state_code"]).strip().upper())
            if raw_row.get("fiscal_year") is not None and str(raw_row.get("state_code") or "").strip()
            else None
        ),
        "_state_year_normalized_target": _quantize_money(_as_decimal(raw_row.get("app_state_normalized_amount"))),
        "_sort_agency": raw_row.get("awarding_agency_name") or raw_row.get("funding_agency_name"),
        "_sort_award_id": _award_id(raw_row),
        "_sort_transaction_id": raw_row.get("source_transaction_id"),
        "_raw_amount": _quantize_money(_as_decimal(raw_row.get("raw_amount"))),
    }

    records_by_field = {
        "prime_tx_record": raw_row.get("prime_tx_record"),
        "prime_award_record": raw_row.get("prime_award_record"),
        "contract_record": raw_row.get("contract_record"),
        "taggs_record": raw_row.get("taggs_record"),
    }
    for spec in raw_field_specs:
        payload = _raw_payload(records_by_field.get(spec.record_field), spec.payload_field)
        export_row[spec.output_column] = payload.get(spec.original_key)
    return export_row


def _allocate_group_amounts(
    rows: Sequence[dict[str, Any]],
    *,
    target_total: Decimal,
) -> dict[str, Decimal]:
    if not rows:
        return {}
    weights = [(_quantize_money(_as_decimal(row.get("chip_net_amount_for_model"))) or Decimal("0.00")) for row in rows]
    total_weight = sum(weights, Decimal("0.00"))
    if total_weight <= 0:
        return {str(row["chip_row_id"]): Decimal("0.00") for row in rows}

    exact_amounts = [(target_total * weight) / total_weight for weight in weights]
    floor_amounts = [amount.quantize(Decimal("0.01"), rounding=ROUND_DOWN) for amount in exact_amounts]
    allocated = sum(floor_amounts, Decimal("0.00"))
    remaining_cents = int((target_total - allocated) / Decimal("0.01"))

    indexed_remainders = sorted(
        enumerate(exact_amounts),
        key=lambda item: (item[1] - floor_amounts[item[0]], -weights[item[0]], str(rows[item[0]]["chip_row_id"])),
        reverse=True,
    )
    for index, _amount in indexed_remainders[:remaining_cents]:
        floor_amounts[index] += Decimal("0.01")

    return {
        str(row["chip_row_id"]): _quantize_money(amount) or Decimal("0.00")
        for row, amount in zip(rows, floor_amounts, strict=False)
    }


def _apply_normalized_allocations(rows: Sequence[dict[str, Any]]) -> Decimal:
    groups: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    targets: dict[tuple[int, str], Decimal] = {}

    for row in rows:
        key = row.get("_state_year_key")
        target_total = _quantize_money(_as_decimal(row.get("_state_year_normalized_target")))
        if key is not None and target_total is not None:
            existing = targets.get(key)
            if existing is None:
                targets[key] = target_total
            elif existing != target_total:
                raise RuntimeError(
                    "Inconsistent state-year normalized targets encountered while preparing the CHIP audit export "
                    f"for {key!r}: {existing} vs {target_total}."
                )
        if row.get("chip_inclusion_flag") is True and key is not None:
            groups[key].append(row)

    total_target = Decimal("0.00")
    for key, group_rows in groups.items():
        if key not in targets:
            raise RuntimeError(
                "Missing app normalization target for included CHIP export rows "
                f"in fiscal year {key[0]} / state {key[1]}."
            )
        target_total = targets[key]
        allocations = _allocate_group_amounts(group_rows, target_total=target_total)
        for row in group_rows:
            row["chip_normalized_amount"] = allocations[str(row["chip_row_id"])]
        total_target += target_total

    for row in rows:
        if row.get("chip_inclusion_flag") is False:
            row["chip_normalized_amount"] = Decimal("0.00")
        elif row.get("chip_inclusion_flag") is None:
            row["chip_normalized_amount"] = None

    return _quantize_money(total_target) or Decimal("0.00")


def _required_chip_dictionary_rows() -> dict[str, dict[str, Any]]:
    return {
        "chip_row_id": {
            "source_system": "CHIP",
            "source_subsystem": "audit_export",
            "column_group": "chip_audit",
            "data_type": "string",
            "format": "source_system:source_transaction_id",
            "allowed_values": "",
            "null_allowed": "no",
            "definition": "Stable row identifier for the CHIP audit export.",
            "provenance_description": "Built from the source system token and the underlying transaction identifier.",
            "transformation_rule": "Concatenate source system and source transaction id with a colon.",
        },
        "chip_model_version": {
            "source_system": "CHIP",
            "source_subsystem": "audit_export",
            "column_group": "chip_audit",
            "data_type": "string",
            "format": "",
            "allowed_values": "",
            "null_allowed": "no",
            "definition": "Combined CHIP funding-model and profile-scope methodology version used for the export.",
            "provenance_description": "Derived from the runtime constants in the CHIP funding model and profile-scope pipeline.",
            "transformation_rule": "Concatenate the app funding-model version and the profile-scope methodology version.",
        },
        "chip_export_timestamp": {
            "source_system": "CHIP",
            "source_subsystem": "audit_export",
            "column_group": "chip_audit",
            "data_type": "timestamp",
            "format": "ISO-8601 UTC",
            "allowed_values": "",
            "null_allowed": "no",
            "definition": "UTC timestamp when the audit export package was generated.",
            "provenance_description": "Captured once at the start of the export run and repeated on every row.",
            "transformation_rule": "Set to the export run timestamp.",
        },
        "chip_export_batch_id": {
            "source_system": "CHIP",
            "source_subsystem": "audit_export",
            "column_group": "chip_audit",
            "data_type": "string",
            "format": "",
            "allowed_values": "",
            "null_allowed": "no",
            "definition": "Stable batch identifier for all files emitted by the export run.",
            "provenance_description": "Generated from the export timestamp and a deterministic hash seed.",
            "transformation_rule": "Create once per export run; repeat on every row and summary artifact.",
        },
        "chip_inclusion_flag": {
            "source_system": "CHIP",
            "source_subsystem": "profile_scope",
            "column_group": "chip_audit",
            "data_type": "boolean",
            "format": "TRUE/FALSE/blank",
            "allowed_values": "TRUE,FALSE,NULL",
            "null_allowed": "yes",
            "definition": "Binary inclusion decision from the CHIP profile-scope layer.",
            "provenance_description": "Copied from recon.profile_scope_transactions.include_in_profile_scope.",
            "transformation_rule": "TRUE rows are included, FALSE rows are excluded, blank rows remain unresolved.",
        },
        "chip_inclusion_bucket": {
            "source_system": "CHIP",
            "source_subsystem": "audit_export",
            "column_group": "chip_audit",
            "data_type": "string",
            "format": "",
            "allowed_values": "included,excluded,unresolved",
            "null_allowed": "no",
            "definition": "Human-readable grouping derived from chip_inclusion_flag.",
            "provenance_description": "Derived entirely from chip_inclusion_flag.",
            "transformation_rule": "TRUE -> included; FALSE -> excluded; NULL -> unresolved.",
        },
        "chip_inclusion_reason": {
            "source_system": "CHIP",
            "source_subsystem": "audit_export",
            "column_group": "chip_audit",
            "data_type": "string",
            "format": "",
            "allowed_values": (
                "included_profile_scope,non_cdc_or_out_of_scope,duplicate_transaction,"
                "negative_adjustment_excluded,missing_geography,invalid_county_mapping,"
                "no_relevant_program_mapping,outside_fiscal_scope,failed_join,manual_review_required"
            ),
            "null_allowed": "no",
            "definition": "Controlled top-level reason used to summarize the CHIP inclusion decision.",
            "provenance_description": "Mapped from decision context, geography completeness, and join status.",
            "transformation_rule": "Apply deterministic export-time taxonomy mapping.",
        },
        "chip_inclusion_reason_detail": {
            "source_system": "CHIP",
            "source_subsystem": "profile_scope",
            "column_group": "chip_audit",
            "data_type": "string",
            "format": "",
            "allowed_values": "",
            "null_allowed": "yes",
            "definition": "Detailed narrative for the inclusion or exclusion decision.",
            "provenance_description": "Composed from the original profile-scope inclusion/exclusion reason fields and decision context.",
            "transformation_rule": "Concatenate non-empty reason fragments with separators.",
        },
        "chip_review_status": {
            "source_system": "CHIP",
            "source_subsystem": "audit_export",
            "column_group": "chip_audit",
            "data_type": "string",
            "format": "",
            "allowed_values": "auto_included,auto_excluded,manual_review_required",
            "null_allowed": "no",
            "definition": "Review status assigned for audit triage.",
            "provenance_description": "Derived from manual-review flags and the inclusion decision.",
            "transformation_rule": "Manual-review rows and unresolved rows are labeled manual_review_required.",
        },
        "chip_data_source_primary": {
            "source_system": "CHIP",
            "source_subsystem": "audit_export",
            "column_group": "chip_audit",
            "data_type": "string",
            "format": "",
            "allowed_values": "USAspending",
            "null_allowed": "no",
            "definition": "Primary source backbone used for the audit row.",
            "provenance_description": "The export is centered on the USAspending transaction universe.",
            "transformation_rule": "Set to USAspending for every row.",
        },
        "chip_data_source_secondary": {
            "source_system": "CHIP",
            "source_subsystem": "audit_export",
            "column_group": "chip_audit",
            "data_type": "string",
            "format": "",
            "allowed_values": "TAGGS",
            "null_allowed": "yes",
            "definition": "Secondary source used to enrich or validate the row when available.",
            "provenance_description": "Set only when a TAGGS record is matched to an assistance transaction.",
            "transformation_rule": "Populate with TAGGS for matched assistance rows; leave blank otherwise.",
        },
        "chip_join_method": {
            "source_system": "CHIP",
            "source_subsystem": "audit_export",
            "column_group": "chip_audit",
            "data_type": "string",
            "format": "",
            "allowed_values": "award_number_state_year,award_number_fiscal_year,aln_state_year,aln_fiscal_year,not_applicable",
            "null_allowed": "yes",
            "definition": "Best matching method used to attach TAGGS context to the USAspending row.",
            "provenance_description": "Derived from a deterministic ranking across exact award-number and ALN candidates.",
            "transformation_rule": "Select the highest-confidence available join candidate.",
        },
        "chip_join_status": {
            "source_system": "CHIP",
            "source_subsystem": "audit_export",
            "column_group": "chip_audit",
            "data_type": "string",
            "format": "",
            "allowed_values": "matched,matched_ambiguous,unmatched,not_attempted,not_applicable",
            "null_allowed": "no",
            "definition": "Outcome of the TAGGS best-effort join attempt.",
            "provenance_description": "Derived from the presence or absence of a selected TAGGS candidate row.",
            "transformation_rule": "Classify the join as matched, ambiguous, unmatched, not attempted, or not applicable.",
        },
        "chip_join_confidence": {
            "source_system": "CHIP",
            "source_subsystem": "audit_export",
            "column_group": "chip_audit",
            "data_type": "string",
            "format": "",
            "allowed_values": "high,medium,low",
            "null_allowed": "yes",
            "definition": "Confidence label for the selected TAGGS join method.",
            "provenance_description": "Assigned from the deterministic join ranking rules.",
            "transformation_rule": "Exact award-number matches rank above ALN-only matches.",
        },
        "chip_provenance_notes": {
            "source_system": "CHIP",
            "source_subsystem": "audit_export",
            "column_group": "chip_audit",
            "data_type": "string",
            "format": "",
            "allowed_values": "",
            "null_allowed": "yes",
            "definition": "Compact provenance note that captures the transformation path for the row.",
            "provenance_description": "Includes methodology, funding-scope method, and join notes.",
            "transformation_rule": "Concatenate the major export-time provenance fragments with semicolons.",
        },
        "chip_funding_fy": {
            "source_system": "CHIP",
            "source_subsystem": "profile_scope",
            "column_group": "chip_audit",
            "data_type": "integer",
            "format": "YYYY",
            "allowed_values": "",
            "null_allowed": "yes",
            "definition": "Fiscal year assigned to the transaction in the profile-scope layer.",
            "provenance_description": "Copied from recon.profile_scope_transactions.fiscal_year.",
            "transformation_rule": "Pass through the fiscal year when available.",
        },
        "chip_net_amount_for_model": {
            "source_system": "CHIP",
            "source_subsystem": "profile_scope",
            "column_group": "chip_audit",
            "data_type": "numeric",
            "format": "decimal(18,2)",
            "allowed_values": "",
            "null_allowed": "yes",
            "definition": "Transaction contribution to the pre-normalized CHIP model after inclusion weights are applied.",
            "provenance_description": "Derived from recon.profile_scope_transactions.normalized_profile_scope_amount for included rows.",
            "transformation_rule": "Included rows keep their normalized profile-scope amount; excluded rows are zero; unresolved rows remain blank.",
        },
        "chip_normalized_amount": {
            "source_system": "CHIP",
            "source_subsystem": "normalized_state_funding",
            "column_group": "chip_audit",
            "data_type": "numeric",
            "format": "decimal(18,2)",
            "allowed_values": "",
            "null_allowed": "yes",
            "definition": "Row-level allocation of the app's CHIP-normalized state-year total.",
            "provenance_description": "Allocated proportionally across included rows within each fiscal-year/state bucket.",
            "transformation_rule": "Distribute the app normalized state total by each row's chip_net_amount_for_model share.",
        },
        "chip_geography_level": {
            "source_system": "CHIP",
            "source_subsystem": "audit_export",
            "column_group": "chip_audit",
            "data_type": "string",
            "format": "",
            "allowed_values": "county,state,unknown",
            "null_allowed": "no",
            "definition": "Most granular resolved geography level available for the row.",
            "provenance_description": "Derived from the resolved county and state standardization fields.",
            "transformation_rule": "County beats state; rows missing both geography values are marked unknown.",
        },
        "chip_state_fips": {
            "source_system": "CHIP",
            "source_subsystem": "dim_state_boundary",
            "column_group": "chip_audit",
            "data_type": "string",
            "format": "2-digit FIPS",
            "allowed_values": "",
            "null_allowed": "yes",
            "definition": "Standardized state FIPS code used for audit review.",
            "provenance_description": "Resolved from the state abbreviation via the state dimension table.",
            "transformation_rule": "Lookup by state abbreviation in public.dim_state_boundary.",
        },
        "chip_county_fips": {
            "source_system": "CHIP",
            "source_subsystem": "dim_county",
            "column_group": "chip_audit",
            "data_type": "string",
            "format": "5-digit FIPS",
            "allowed_values": "",
            "null_allowed": "yes",
            "definition": "Standardized county FIPS code used for audit review.",
            "provenance_description": "Resolved from direct USAspending county FIPS values or contract county-name matching.",
            "transformation_rule": "Prefer direct USAspending county FIPS; otherwise fall back to deterministic county-name matching.",
        },
        "chip_county_name_standardized": {
            "source_system": "CHIP",
            "source_subsystem": "dim_county",
            "column_group": "chip_audit",
            "data_type": "string",
            "format": "",
            "allowed_values": "",
            "null_allowed": "yes",
            "definition": "Standardized county name associated with chip_county_fips.",
            "provenance_description": "Resolved from the county dimension table.",
            "transformation_rule": "Lookup by chip_county_fips in public.dim_county.",
        },
        "chip_program_area_standardized": {
            "source_system": "CHIP",
            "source_subsystem": "audit_export",
            "column_group": "chip_audit",
            "data_type": "string",
            "format": "",
            "allowed_values": "",
            "null_allowed": "no",
            "definition": "Standardized CHIP program-area bucket for the row.",
            "provenance_description": "Derived from TAGGS enrichment when available, then USAspending titles and office names.",
            "transformation_rule": "Apply the same keyword-driven canonical program-area classifier used in the app.",
        },
    }


def _required_provenance_dictionary_rows() -> dict[str, dict[str, Any]]:
    base = {
        "source_system": "Provenance",
        "source_subsystem": "audit_export",
        "column_group": "provenance",
        "data_type": "string",
        "format": "",
        "allowed_values": "",
        "null_allowed": "yes",
    }
    return {
        "prov_usaspending_source_file": {
            **base,
            "null_allowed": "no",
            "definition": "USAspending source file name for the primary transaction record.",
            "provenance_description": "Copied from the USAspending-backed ingestion table.",
            "transformation_rule": "Prefer the primary transaction source file; fall back to the award file when needed.",
        },
        "prov_usaspending_extract_date": {
            **base,
            "definition": "Best available extract/import date for the USAspending source row.",
            "provenance_description": "Uses the import timestamp when the original extract date is not carried separately.",
            "transformation_rule": "Render as an ISO date from the import timestamp.",
        },
        "prov_usaspending_table_name": {
            **base,
            "null_allowed": "no",
            "definition": "Fully qualified USAspending-backed table used as the primary transaction source.",
            "provenance_description": "Set by the export pipeline from the active source system.",
            "transformation_rule": "Assistance rows point to cdc_funding.prime_transactions; contract rows point to usaspending.contract_transactions_raw.",
        },
        "prov_usaspending_record_id": {
            **base,
            "null_allowed": "no",
            "definition": "Primary USAspending transaction identifier used to build the row.",
            "provenance_description": "Copied from the underlying USAspending-backed transaction table.",
            "transformation_rule": "Prefer the native transaction unique key; fall back to the local row id.",
        },
        "prov_taggs_source_file": {
            **base,
            "definition": "TAGGS source file name for the matched enrichment row.",
            "provenance_description": "Copied from taggs.raw_awards when a TAGGS match is selected.",
            "transformation_rule": "Populate only when a TAGGS raw-award row is attached.",
        },
        "prov_taggs_extract_date": {
            **base,
            "definition": "Best available extract/import date for the matched TAGGS row.",
            "provenance_description": "Derived from the TAGGS load timestamp because the export file does not expose a clean row-level extract date field.",
            "transformation_rule": "Render the TAGGS load timestamp as an ISO date.",
        },
        "prov_taggs_table_name": {
            **base,
            "definition": "Fully qualified TAGGS table used for the matched enrichment row.",
            "provenance_description": "Set by the export pipeline when a TAGGS raw-award row is attached.",
            "transformation_rule": "Populate with taggs.raw_awards for matched assistance rows only.",
        },
        "prov_taggs_record_id": {
            **base,
            "definition": "Internal TAGGS raw-award record id selected by the export join.",
            "provenance_description": "Copied from taggs.raw_awards.id.",
            "transformation_rule": "Populate only when a TAGGS candidate row is selected.",
        },
        "prov_merge_run_id": {
            **base,
            "null_allowed": "no",
            "definition": "Export batch identifier used to join all files emitted in the same run.",
            "provenance_description": "Generated by the export pipeline at runtime.",
            "transformation_rule": "Repeat the chip_export_batch_id value on every row.",
        },
        "prov_transformation_stage": {
            **base,
            "null_allowed": "no",
            "definition": "Named transformation stage that created the export row.",
            "provenance_description": "Set by the audit export pipeline.",
            "transformation_rule": "Use a constant stage label for all rows in the package.",
        },
        "prov_last_modified_by_process": {
            **base,
            "null_allowed": "no",
            "definition": "Process label responsible for the final exported row.",
            "provenance_description": "Set by the audit export pipeline.",
            "transformation_rule": "Use the export process constant on every row.",
        },
    }


def _infer_data_type(value: Any) -> str:
    if value is None:
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, Decimal):
        return "numeric"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "numeric"
    if isinstance(value, datetime):
        return "timestamp"
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return "date"
    if isinstance(value, (dict, list)):
        return "json"
    return "string"


def _build_dictionary_rows(
    *,
    column_order: Sequence[str],
    raw_field_specs: Sequence[RawFieldSpec],
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    sample_values: dict[str, Any] = {}
    for row in rows:
        for column_name in column_order:
            if column_name in sample_values:
                continue
            value = row.get(column_name)
            if value is None or value == "":
                continue
            sample_values[column_name] = value

    chip_meta = _required_chip_dictionary_rows()
    prov_meta = _required_provenance_dictionary_rows()
    raw_spec_by_column = {spec.output_column: spec for spec in raw_field_specs}
    dictionary_rows: list[dict[str, Any]] = []

    for column_name in column_order:
        if column_name in chip_meta:
            meta = chip_meta[column_name]
            dictionary_rows.append(
                {
                    "column_name": column_name,
                    "display_name": _display_name(column_name),
                    "source_system": meta["source_system"],
                    "source_subsystem": meta["source_subsystem"],
                    "source_column_name": column_name,
                    "column_group": meta["column_group"],
                    "data_type": meta["data_type"],
                    "format": meta["format"],
                    "allowed_values": meta["allowed_values"],
                    "null_allowed": meta["null_allowed"],
                    "definition": meta["definition"],
                    "provenance_description": meta["provenance_description"],
                    "transformation_rule": meta["transformation_rule"],
                    "example_value": _serialize_cell(sample_values.get(column_name)),
                    "appears_in_files": APPEARS_IN_TRANSACTION_FILES,
                }
            )
            continue

        if column_name in prov_meta:
            meta = prov_meta[column_name]
            dictionary_rows.append(
                {
                    "column_name": column_name,
                    "display_name": _display_name(column_name),
                    "source_system": meta["source_system"],
                    "source_subsystem": meta["source_subsystem"],
                    "source_column_name": column_name,
                    "column_group": meta["column_group"],
                    "data_type": meta["data_type"],
                    "format": meta["format"],
                    "allowed_values": meta["allowed_values"],
                    "null_allowed": meta["null_allowed"],
                    "definition": meta["definition"],
                    "provenance_description": meta["provenance_description"],
                    "transformation_rule": meta["transformation_rule"],
                    "example_value": _serialize_cell(sample_values.get(column_name)),
                    "appears_in_files": APPEARS_IN_TRANSACTION_FILES,
                }
            )
            continue

        raw_spec = raw_spec_by_column[column_name]
        dictionary_rows.append(
            {
                "column_name": column_name,
                "display_name": raw_spec.original_key,
                "source_system": "USAspending" if raw_spec.source_system == "usaspending" else "TAGGS",
                "source_subsystem": raw_spec.source_subsystem,
                "source_column_name": raw_spec.original_key,
                "column_group": f"{raw_spec.source_system}_source",
                "data_type": _infer_data_type(sample_values.get(column_name)),
                "format": "",
                "allowed_values": "",
                "null_allowed": "yes",
                "definition": (
                    "Raw source column preserved from the underlying "
                    f"{raw_spec.source_system.upper()} {raw_spec.source_subsystem} payload."
                ),
                "provenance_description": (
                    "Flattened from the source JSON payload so reviewers can inspect the original column value "
                    "without reverse engineering the ingest tables."
                ),
                "transformation_rule": "Pass through the raw source field value without normalization whenever available.",
                "example_value": _serialize_cell(sample_values.get(column_name)),
                "appears_in_files": APPEARS_IN_TRANSACTION_FILES,
            }
        )

    return dictionary_rows


def _validation_metrics(rows: Sequence[Mapping[str, Any]], *, model_total_normalized_amount: Decimal) -> dict[str, Any]:
    included = [row for row in rows if row.get("chip_inclusion_flag") is True]
    excluded = [row for row in rows if row.get("chip_inclusion_flag") is False]
    unresolved = [row for row in rows if row.get("chip_inclusion_flag") is None]

    matched_both_sources_count = sum(
        1 for row in rows if row.get("chip_join_status") in {"matched", "matched_ambiguous"}
    )
    missing_provenance_count = sum(
        1
        for row in rows
        if not row.get("prov_usaspending_source_file") or not row.get("prov_usaspending_record_id")
    )

    metrics = {
        "total_candidate_rows": len(rows),
        "included_rows": len(included),
        "excluded_rows": len(excluded),
        "unresolved_rows": len(unresolved),
        "included_amount_sum": _quantize_money(
            sum((_as_decimal(row.get("chip_net_amount_for_model")) or Decimal("0.00") for row in included), Decimal("0.00"))
        ),
        "excluded_amount_sum": _quantize_money(
            sum((_as_decimal(row.get("_raw_amount")) or Decimal("0.00") for row in excluded), Decimal("0.00"))
        ),
        "unresolved_amount_sum": _quantize_money(
            sum((_as_decimal(row.get("_raw_amount")) or Decimal("0.00") for row in unresolved), Decimal("0.00"))
        ),
        "included_net_amount_sum": _quantize_money(
            sum((_as_decimal(row.get("chip_net_amount_for_model")) or Decimal("0.00") for row in included), Decimal("0.00"))
        ),
        "included_normalized_amount_sum": _quantize_money(
            sum((_as_decimal(row.get("chip_normalized_amount")) or Decimal("0.00") for row in included), Decimal("0.00"))
        ),
        "included_raw_amount_sum": _quantize_money(
            sum((_as_decimal(row.get("_raw_amount")) or Decimal("0.00") for row in included), Decimal("0.00"))
        ),
        "matched_both_sources_count": matched_both_sources_count,
        "usaspending_only_count": len(rows) - matched_both_sources_count,
        "taggs_only_count": 0,
        "missing_provenance_count": missing_provenance_count,
        "app_model_total_normalized_sum": _quantize_money(model_total_normalized_amount),
    }
    return metrics


def _validate_export_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    column_order: Sequence[str],
    metrics: Mapping[str, Any],
) -> list[str]:
    violations: list[str] = []
    seen_row_ids: set[str] = set()
    split_row_ids: dict[str, set[str]] = {"included": set(), "excluded": set(), NULL_BUCKET: set()}

    for row in rows:
        row_id = str(row.get("chip_row_id") or "").strip()
        if not row_id:
            violations.append("Encountered a row without chip_row_id.")
            continue
        if row_id in seen_row_ids:
            violations.append(f"Duplicate chip_row_id detected in candidate universe: {row_id}.")
        seen_row_ids.add(row_id)

        row_columns = [column_name for column_name in row.keys() if not column_name.startswith("_")]
        if row_columns != list(column_order):
            violations.append(f"Column mismatch detected for chip_row_id={row_id}.")

        bucket = str(row.get("chip_inclusion_bucket") or "")
        if bucket not in split_row_ids:
            violations.append(f"Unexpected chip_inclusion_bucket={bucket!r} for chip_row_id={row_id}.")
            continue
        split_row_ids[bucket].add(row_id)

        flag = row.get("chip_inclusion_flag")
        if bucket == "included" and flag is not True:
            violations.append(f"Included bucket contains non-TRUE flag for chip_row_id={row_id}.")
        if bucket == "excluded" and flag is not False:
            violations.append(f"Excluded bucket contains non-FALSE flag for chip_row_id={row_id}.")
        if bucket == NULL_BUCKET and flag is not None:
            violations.append(f"Unresolved bucket contains non-NULL flag for chip_row_id={row_id}.")

    if split_row_ids["included"] & split_row_ids["excluded"]:
        violations.append("Included and excluded files are not mutually exclusive by chip_row_id.")
    if split_row_ids["included"] & split_row_ids[NULL_BUCKET]:
        violations.append("Included and unresolved files are not mutually exclusive by chip_row_id.")
    if split_row_ids["excluded"] & split_row_ids[NULL_BUCKET]:
        violations.append("Excluded and unresolved files are not mutually exclusive by chip_row_id.")

    if len(rows) != (
        len(split_row_ids["included"]) + len(split_row_ids["excluded"]) + len(split_row_ids[NULL_BUCKET])
    ):
        violations.append("Row counts across the three CHIP transaction exports do not sum to the candidate universe.")

    normalized_total = _quantize_money(_as_decimal(metrics.get("included_normalized_amount_sum")))
    app_total = _quantize_money(_as_decimal(metrics.get("app_model_total_normalized_sum")))
    if normalized_total != app_total:
        violations.append(
            "Included CHIP-normalized amount total does not reconcile to the app model total: "
            f"{normalized_total} vs {app_total}."
        )

    return violations


def _write_csv(path: Path, *, fieldnames: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow({field_name: _serialize_cell(row.get(field_name)) for field_name in fieldnames})


def _write_validation_summary(path: Path, *, metrics: Mapping[str, Any]) -> None:
    rows = [{"metric_name": key, "metric_value": _serialize_cell(value)} for key, value in metrics.items()]
    _write_csv(path, fieldnames=["metric_name", "metric_value"], rows=rows)


def _write_readme(
    path: Path,
    *,
    export_batch_id: str,
    export_timestamp: datetime,
    metrics: Mapping[str, Any],
) -> None:
    content = f"""# CHIP Funding Audit Export

## Purpose

This package captures the CHIP funding-model transaction universe used for audit review.
It separates transactions into included, excluded, and unresolved partitions while preserving original USAspending and TAGGS source fields plus CHIP audit and provenance metadata.

Export batch id: `{export_batch_id}`
Export timestamp (UTC): `{export_timestamp.isoformat()}`
CHIP model version: `{CHIP_MODEL_VERSION}`

## Files

- `{EXPORT_FILE_NAMES["included"]}`: transactions with `chip_inclusion_flag = TRUE`
- `{EXPORT_FILE_NAMES["excluded"]}`: transactions with `chip_inclusion_flag = FALSE`
- `{EXPORT_FILE_NAMES["unresolved"]}`: transactions with `chip_inclusion_flag IS NULL`
- `{EXPORT_FILE_NAMES["dictionary"]}`: data dictionary for every exported column
- `{EXPORT_FILE_NAMES["validation"]}`: export validation metrics and reconciliation values
- `{EXPORT_FILE_NAMES["readme"]}`: methodology and limitations for reviewers

## Row Definition

Each exported row represents one USAspending-backed transaction from the CHIP profile-scope transaction universe in `recon.profile_scope_transactions`.
The export includes assistance transactions and contract transactions.
USAspending remains the primary transaction backbone.
TAGGS is attached only as secondary enrichment for assistance rows when the export can find a deterministic best-effort match.

## USAspending and TAGGS Join

The export attempts TAGGS enrichment only for assistance rows.
Join precedence is:

1. exact award number + fiscal year + state
2. exact award number + fiscal year
3. normalized ALN + fiscal year + state
4. normalized ALN + fiscal year

`chip_join_method`, `chip_join_status`, and `chip_join_confidence` expose the selected join path.
Rows without a usable award number or ALN are marked `not_attempted`.
Contract rows are marked `not_applicable` because the app does not use TAGGS as a contract backbone.

## Inclusion Logic

`chip_inclusion_flag` is copied from the CHIP profile-scope layer:

- `TRUE`: included in the model
- `FALSE`: excluded from the model
- `NULL`: unresolved and still requires manual or methodological review

`chip_inclusion_bucket` is a direct label wrapper around the flag.
`chip_inclusion_reason` is a controlled export taxonomy.
`chip_inclusion_reason_detail` preserves the original decision context and profile-scope narrative where possible.

Null inclusion means the row remains unresolved under the current profile-scope rules.
Typical causes include mixed or unknown funding scope, incomplete account evidence, conditional emergency handling, or insufficient supporting join context.

## Amount Fields

- Raw source amounts stay in the prefixed USAspending and TAGGS source columns.
- `chip_net_amount_for_model` is the row's pre-normalized contribution after CHIP inclusion weights are applied.
- `chip_normalized_amount` is a proportional allocation of the app's CHIP-normalized state-year total across included rows in the same fiscal-year/state bucket.

This means row-level normalized amounts are derived allocation values.
They are designed to sum exactly to the app's CHIP-normalized totals while preserving the relative contribution of included rows inside each state-year bucket.

## Provenance

Primary provenance columns describe the USAspending transaction record, source file, and source table used to build each row.
Secondary provenance columns describe the selected TAGGS raw-award row when a join is available.
When the original source extract date is not stored directly on the row, the export uses the source import/load timestamp as the best available audit date.

## Known Limitations

- TAGGS enrichment is a best-effort secondary join, not a guaranteed one-to-one transactional match.
- Contract rows do not have TAGGS secondary matches in the current app methodology.
- Row-level normalized amounts are proportional allocations rather than native source transaction values.
- Some geography standardization depends on county-name matching for contract rows when a direct county FIPS is absent.
- If a source system omitted a raw field entirely, the export preserves that omission as blank rather than manufacturing a replacement value.

## Validation Checks Performed

- All three transaction files use the exact same columns and column order.
- The three transaction files are mutually exclusive by `chip_row_id`.
- The combined row count across the three files equals the candidate universe row count.
- Included rows contain only `TRUE` inclusion flags.
- Excluded rows contain only `FALSE` inclusion flags.
- Unresolved rows contain only `NULL` inclusion flags.
- Included normalized totals reconcile to the app's CHIP-normalized total.

Validation summary highlights:

- total candidate rows: `{_serialize_cell(metrics["total_candidate_rows"])}`
- included rows: `{_serialize_cell(metrics["included_rows"])}`
- excluded rows: `{_serialize_cell(metrics["excluded_rows"])}`
- unresolved rows: `{_serialize_cell(metrics["unresolved_rows"])}`
- included normalized amount sum: `{_serialize_cell(metrics["included_normalized_amount_sum"])}`
- app model normalized total: `{_serialize_cell(metrics["app_model_total_normalized_sum"])}`
- matched both sources count: `{_serialize_cell(metrics["matched_both_sources_count"])}`
- missing provenance count: `{_serialize_cell(metrics["missing_provenance_count"])}`
"""
    path.write_text(content, encoding="utf-8")


def _read_csv_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        return next(reader)


def _write_transaction_files(
    export_dir: Path,
    *,
    column_order: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
) -> None:
    partitions = {
        "included": [row for row in rows if row.get("chip_inclusion_flag") is True],
        "excluded": [row for row in rows if row.get("chip_inclusion_flag") is False],
        "unresolved": [row for row in rows if row.get("chip_inclusion_flag") is None],
    }
    for partition_name, partition_rows in partitions.items():
        _write_csv(
            export_dir / EXPORT_FILE_NAMES[partition_name],
            fieldnames=column_order,
            rows=partition_rows,
        )

    header_pairs = {
        partition_name: _read_csv_header(export_dir / EXPORT_FILE_NAMES[partition_name])
        for partition_name in ("included", "excluded", "unresolved")
    }
    if not (header_pairs["included"] == header_pairs["excluded"] == header_pairs["unresolved"]):
        raise RuntimeError("Column parity validation failed after writing the CHIP transaction exports.")


def build_export_data(
    *,
    db_url: str,
    export_timestamp: datetime,
    export_batch_id: str,
) -> AuditExportData:
    engine = create_engine(db_url, pool_pre_ping=True)
    rows: list[dict[str, Any]] = []
    raw_field_specs: list[RawFieldSpec]
    with engine.connect() as connection:
        _require_tables(
            connection,
            [
                PROFILE_SCOPE_TX_TABLE,
                ASSISTANCE_PROFILE_TABLE,
                CONTRACT_PROFILE_TABLE,
                NORMALIZED_TABLE,
                PRIME_TX_TABLE,
                PRIME_AWARD_TABLE,
                CONTRACT_TABLE,
                TAGGS_RAW_TABLE,
                TAGGS_SUMMARY_TABLE,
                STATE_DIM_TABLE,
                COUNTY_DIM_TABLE,
            ],
        )

        raw_field_specs = [
            *_build_raw_field_specs(
                source_system="usaspending",
                source_subsystem="prime_transaction_raw_json",
                record_field="prime_tx_record",
                payload_field="raw",
                output_prefix="usaspending_prime_transaction",
                keys=_fetch_json_object_keys(connection, table_name=PRIME_TX_TABLE, json_column="raw"),
            ),
            *_build_raw_field_specs(
                source_system="usaspending",
                source_subsystem="prime_award_raw_json",
                record_field="prime_award_record",
                payload_field="raw",
                output_prefix="usaspending_prime_award",
                keys=_fetch_json_object_keys(connection, table_name=PRIME_AWARD_TABLE, json_column="raw"),
            ),
            *_build_raw_field_specs(
                source_system="usaspending",
                source_subsystem="contract_transaction_raw_json",
                record_field="contract_record",
                payload_field="raw_row_json",
                output_prefix="usaspending_contract",
                keys=_fetch_json_object_keys(connection, table_name=CONTRACT_TABLE, json_column="raw_row_json"),
            ),
            *_build_raw_field_specs(
                source_system="taggs",
                source_subsystem="raw_award_raw_json",
                record_field="taggs_record",
                payload_field="raw_row_json",
                output_prefix="taggs_raw_award",
                keys=_fetch_json_object_keys(connection, table_name=TAGGS_RAW_TABLE, json_column="raw_row_json"),
            ),
        ]
        _log_progress(f"Discovered {len(raw_field_specs)} raw source columns for CHIP audit export.")

    candidate_query = _candidate_rows_query()
    _log_progress("Running candidate transaction query.")
    raw_connection = engine.raw_connection()
    raw_cursor = None
    try:
        cursor_name = f"chip_audit_export_{export_batch_id}".replace("-", "_")[:63]
        raw_cursor = raw_connection.cursor(name=cursor_name)
        raw_cursor.itersize = 1_000
        raw_cursor.execute(candidate_query)
        column_names = [
            description.name if hasattr(description, "name") else description[0]
            for description in raw_cursor.description
        ]

        row_count = 0
        while True:
            batch = raw_cursor.fetchmany(1_000)
            if not batch:
                break
            for raw_tuple in batch:
                row_count += 1
                raw_row = dict(zip(column_names, raw_tuple))
                rows.append(
                    _prepare_export_row(
                        raw_row,
                        raw_field_specs=raw_field_specs,
                        export_timestamp=export_timestamp,
                        export_batch_id=export_batch_id,
                    )
                )
                if row_count % PROGRESS_ROW_INTERVAL == 0:
                    _log_progress(f"Prepared {row_count:,} export rows.")
    finally:
        if raw_cursor is not None:
            raw_cursor.close()
        raw_connection.close()

    _log_progress(f"Finished preparing {len(rows):,} export rows; applying allocations and sorting.")
    model_total_normalized_amount = _apply_normalized_allocations(rows)
    rows.sort(key=_sort_key)

    column_order = [
        *CHIP_AUDIT_COLUMNS,
        *PROVENANCE_COLUMNS,
        *[spec.output_column for spec in raw_field_specs],
    ]

    projected_rows: list[dict[str, Any]] = []
    for row in rows:
        projected_rows.append({column_name: row.get(column_name) for column_name in column_order})

    dictionary_rows = _build_dictionary_rows(
        column_order=column_order,
        raw_field_specs=raw_field_specs,
        rows=projected_rows,
    )
    return AuditExportData(
        rows=rows,
        column_order=column_order,
        dictionary_rows=dictionary_rows,
        model_total_normalized_amount=model_total_normalized_amount,
    )


def write_export_package(
    export_data: AuditExportData,
    *,
    output_root: str | Path,
    export_date: date,
    export_timestamp: datetime,
    export_batch_id: str,
    overwrite: bool = False,
) -> Path:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    export_dir = root / f"chip_funding_audit_export_{export_date.strftime('%Y%m%d')}"
    temp_dir = root / f".chip_funding_audit_export_{export_date.strftime('%Y%m%d')}_{export_batch_id}.tmp"

    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    if export_dir.exists():
        if not overwrite:
            raise FileExistsError(
                f"Export directory {export_dir} already exists. Re-run with --overwrite to replace it."
            )
        shutil.rmtree(export_dir)

    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        _log_progress("Writing export files and running validation checks.")
        _write_transaction_files(
            temp_dir,
            column_order=export_data.column_order,
            rows=export_data.rows,
        )
        _write_csv(
            temp_dir / EXPORT_FILE_NAMES["dictionary"],
            fieldnames=[
                "column_name",
                "display_name",
                "source_system",
                "source_subsystem",
                "source_column_name",
                "column_group",
                "data_type",
                "format",
                "allowed_values",
                "null_allowed",
                "definition",
                "provenance_description",
                "transformation_rule",
                "example_value",
                "appears_in_files",
            ],
            rows=export_data.dictionary_rows,
        )

        metrics = _validation_metrics(
            export_data.rows,
            model_total_normalized_amount=export_data.model_total_normalized_amount,
        )
        violations = _validate_export_rows(
            export_data.rows,
            column_order=export_data.column_order,
            metrics=metrics,
        )
        if violations:
            raise RuntimeError("CHIP audit export validation failed:\n- " + "\n- ".join(violations))

        _write_validation_summary(temp_dir / EXPORT_FILE_NAMES["validation"], metrics=metrics)
        _write_readme(
            temp_dir / EXPORT_FILE_NAMES["readme"],
            export_batch_id=export_batch_id,
            export_timestamp=export_timestamp,
            metrics=metrics,
        )
        temp_dir.rename(export_dir)
        return export_dir
    except Exception:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise


def build_export_batch_id(*, export_timestamp: datetime) -> str:
    seed = export_timestamp.isoformat()
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"chip_audit_{export_timestamp.strftime('%Y%m%dT%H%M%SZ')}_{digest}"


def _parse_export_date(value: str | None) -> date:
    if value is None:
        return datetime.now(timezone.utc).date()
    token = str(value).strip()
    return datetime.strptime(token, "%Y%m%d").date()


def main() -> None:
    args = parse_args()
    export_timestamp = datetime.now(timezone.utc)
    export_date = _parse_export_date(args.export_date)
    export_batch_id = build_export_batch_id(export_timestamp=export_timestamp)
    export_data = build_export_data(
        db_url=args.db_url,
        export_timestamp=export_timestamp,
        export_batch_id=export_batch_id,
    )
    export_dir = write_export_package(
        export_data,
        output_root=args.output_root,
        export_date=export_date,
        export_timestamp=export_timestamp,
        export_batch_id=export_batch_id,
        overwrite=bool(args.overwrite),
    )
    print(str(export_dir))


if __name__ == "__main__":
    main()
