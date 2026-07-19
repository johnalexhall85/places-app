#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from app.db import DATABASE_URL  # noqa: E402
from app.db_fqtn import cdc_funding_table  # noqa: E402
from reconcile_fy2023_cdc_funding import (  # noqa: E402
    BASE_PARAMS,
    CDC_FUNDED_STRICT_SQL,
    FACT_TABLE,
    FUNDING_MECHANISM,
    LIKELY_VFC_SQL,
    POSITIVE_ASSISTANCE_FY_WHERE,
    STATE_LOOKUP_CTE,
    amount,
    json_ready,
    metric_query,
    normalized_metric_query,
    one_row,
    rows,
)


DEFAULT_FISCAL_YEAR = 2023
DEFAULT_OUTPUT_PATH = BACKEND_ROOT / "data_profiles" / "fy2023_cdc_funding_deep_dive.json"
RAW_ASSISTANCE_TABLE = cdc_funding_table("raw_usaspending_assistance_prime_transactions")

STATE_FIELD_PATTERNS = ("state",)
ZIP_FIELD_PATTERNS = ("zip",)
PLACE_FIELD_PATTERNS = ("place",)
PERFORMANCE_FIELD_PATTERNS = ("performance",)
SUPPLEMENTAL_FIELD_PATTERNS = ("covid", "supplemental", "disaster", "emergency", "defc", "iija")

STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM",
    "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
    "WV", "WI", "WY", "AS", "GU", "MP", "PR", "VI",
}
STATE_FIPS = {
    "01", "02", "04", "05", "06", "08", "09", "10", "11", "12", "13", "15", "16", "17", "18", "19",
    "20", "21", "22", "23", "24", "25", "26", "27", "28", "29", "30", "31", "32", "33", "34", "35",
    "36", "37", "38", "39", "40", "41", "42", "44", "45", "46", "47", "48", "49", "50", "51", "53",
    "54", "55", "56", "60", "66", "69", "72", "78",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deep-dive FY2023 CDC funding reconciliation diagnostics.")
    parser.add_argument("--fiscal-year", type=int, default=DEFAULT_FISCAL_YEAR)
    parser.add_argument("--funding-profile-target", type=Decimal, default=None)
    parser.add_argument("--funding-profiles-csv", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def clean_token(value: Any) -> str:
    if value is None:
        return ""
    token = str(value).strip()
    if token.lower() in {"", "na", "n/a", "nan", "none", "null"}:
        return ""
    return token


def parse_decimal(value: Any) -> Decimal:
    token = clean_token(value)
    if not token:
        return Decimal("0")
    token = token.replace("$", "").replace(",", "")
    try:
        return Decimal(token)
    except InvalidOperation:
        return Decimal("0")


def filtered_raw_fields(raw_record: dict[str, Any] | None, patterns: tuple[str, ...]) -> dict[str, Any]:
    raw = raw_record if isinstance(raw_record, dict) else {}
    output: dict[str, Any] = {}
    for key, value in raw.items():
        lower = str(key).lower()
        if any(pattern.lower() in lower for pattern in patterns):
            cleaned = clean_token(value)
            if cleaned:
                output[key] = cleaned
    return output


def add_raw_field_subsets(row: dict[str, Any]) -> dict[str, Any]:
    raw_record = row.pop("raw_record", None)
    row["raw_state_fields"] = filtered_raw_fields(raw_record, STATE_FIELD_PATTERNS)
    row["raw_zip_fields"] = filtered_raw_fields(raw_record, ZIP_FIELD_PATTERNS)
    row["raw_place_fields"] = filtered_raw_fields(raw_record, PLACE_FIELD_PATTERNS)
    row["raw_performance_fields"] = filtered_raw_fields(raw_record, PERFORMANCE_FIELD_PATTERNS)
    return row


def add_supplemental_raw_field_subsets(row: dict[str, Any]) -> dict[str, Any]:
    raw_record = row.pop("raw_record", None)
    row["raw_covid_fields"] = filtered_raw_fields(raw_record, ("covid",))
    row["raw_supplemental_fields"] = filtered_raw_fields(raw_record, ("supplemental",))
    row["raw_disaster_fields"] = filtered_raw_fields(raw_record, ("disaster",))
    row["raw_defc_fields"] = filtered_raw_fields(raw_record, ("defc",))
    row["raw_treasury_fields"] = filtered_raw_fields(raw_record, ("treasury",))
    row["raw_account_fields"] = filtered_raw_fields(raw_record, ("account",))
    return row


def looks_like_state_token(value: Any) -> bool:
    token = clean_token(value).upper()
    if token in STATE_CODES or token in STATE_FIPS:
        return True
    digits = re.sub(r"[^0-9]", "", token)
    return len(digits) == 5 and digits[:2] in STATE_FIPS


def state_recovery_analysis(unmapped_rows: list[dict[str, Any]]) -> dict[str, Any]:
    recoverable_rows = []
    field_hits: Counter[str] = Counter()
    zip_hits: Counter[str] = Counter()
    total_recoverable = Decimal("0")
    for row in unmapped_rows:
        candidates: dict[str, Any] = {}
        raw_state_fields = row.get("raw_state_fields") or {}
        raw_zip_fields = row.get("raw_zip_fields") or {}
        for key, value in raw_state_fields.items():
            if looks_like_state_token(value):
                candidates[key] = value
                field_hits[key] += 1
        for key, value in raw_zip_fields.items():
            digits = re.sub(r"[^0-9]", "", clean_token(value))
            if len(digits) >= 5:
                candidates[key] = value
                zip_hits[key] += 1
        if candidates:
            total_recoverable += amount(row.get("federal_action_obligation"))
            recoverable_rows.append(
                {
                    "federal_action_obligation": row.get("federal_action_obligation"),
                    "recipient_name": row.get("recipient_name"),
                    "assistance_listing_number": row.get("assistance_listing_number"),
                    "candidate_fields": candidates,
                    "usaspending_permalink": row.get("usaspending_permalink"),
                }
            )
    return {
        "potentially_recoverable_amount_using_raw_state_or_zip_fields": total_recoverable,
        "potentially_recoverable_transaction_count": len(recoverable_rows),
        "candidate_state_field_hit_counts": dict(field_hits.most_common()),
        "candidate_zip_field_hit_counts": dict(zip_hits.most_common()),
        "top_recoverable_candidates": sorted(
            recoverable_rows,
            key=lambda item: amount(item.get("federal_action_obligation")),
            reverse=True,
        )[:50],
        "recommendation": (
            "Current fact columns miss at least some raw state/ZIP signals; review candidate fields before changing map logic."
            if recoverable_rows
            else "The unmapped bucket has no obvious raw state or ZIP values under the inspected fields, so better state normalization is unlikely to recover much without external enrichment."
        ),
    }


def base_params(fiscal_year: int) -> dict[str, Any]:
    return {**BASE_PARAMS, "fiscal_year": fiscal_year}


def cdc_positive_where() -> str:
    return f"{POSITIVE_ASSISTANCE_FY_WHERE} AND {CDC_FUNDED_STRICT_SQL}"


def cdc_positive_non_supp_where() -> str:
    return f"{cdc_positive_where()} AND is_covid_or_emergency_supplemental IS FALSE"


def normalized_unmapped_where() -> str:
    return f"""
        source_fiscal_year = :fiscal_year
        AND funding_mechanism = :funding_mechanism
        AND is_positive_obligation IS TRUE
        AND federal_action_obligation > 0
        AND {CDC_FUNDED_STRICT_SQL}
        AND is_covid_or_emergency_supplemental IS FALSE
        AND normalized_state_fips IS NULL
    """


def collect_unmapped_diagnostic(conn: sa.Connection, fiscal_year: int) -> dict[str, Any]:
    params = base_params(fiscal_year)
    summary = one_row(conn, normalized_metric_query(normalized_unmapped_where()), params)
    all_unmapped = rows(
        conn,
        f"""
        {STATE_LOOKUP_CTE}
        SELECT
            id,
            federal_action_obligation,
            recipient_name,
            recipient_uei,
            recipient_state_code,
            recipient_state_name,
            recipient_county_name,
            recipient_county_fips,
            recipient_zip,
            recipient_country_code,
            pop_state_code,
            pop_state_name,
            pop_county_name,
            pop_county_fips,
            pop_zip,
            pop_country_code,
            assistance_listing_number,
            assistance_listing_title,
            federal_accounts_funding_this_award,
            treasury_accounts_funding_this_award,
            transaction_description,
            prime_award_base_transaction_description,
            usaspending_permalink,
            raw_record
        FROM normalized_fact
        WHERE {normalized_unmapped_where()}
        ORDER BY federal_action_obligation DESC NULLS LAST
        """,
        params,
    )
    all_unmapped = [add_raw_field_subsets(row) for row in all_unmapped]

    group_queries = {
        "by_recipient_country_code": "recipient_country_code",
        "by_pop_country_code": "pop_country_code",
        "by_assistance_listing": "assistance_listing_number, assistance_listing_title",
        "by_federal_accounts": "COALESCE(NULLIF(BTRIM(federal_accounts_funding_this_award), ''), '(blank)')",
        "by_recipient_name": "COALESCE(NULLIF(BTRIM(recipient_name), ''), '(blank)')",
        "by_presence_flags": """
            (NULLIF(BTRIM(recipient_state_code), '') IS NOT NULL OR NULLIF(BTRIM(recipient_state_name), '') IS NOT NULL),
            (NULLIF(BTRIM(pop_state_code), '') IS NOT NULL OR NULLIF(BTRIM(pop_state_name), '') IS NOT NULL),
            (NULLIF(BTRIM(recipient_zip), '') IS NOT NULL OR NULLIF(BTRIM(pop_zip), '') IS NOT NULL)
        """,
    }
    grouped: dict[str, Any] = {}
    for key, group_sql in group_queries.items():
        if key == "by_assistance_listing":
            select_sql = "assistance_listing_number, assistance_listing_title"
        elif key == "by_presence_flags":
            select_sql = """
                (NULLIF(BTRIM(recipient_state_code), '') IS NOT NULL OR NULLIF(BTRIM(recipient_state_name), '') IS NOT NULL) AS has_recipient_state_field,
                (NULLIF(BTRIM(pop_state_code), '') IS NOT NULL OR NULLIF(BTRIM(pop_state_name), '') IS NOT NULL) AS has_place_of_performance_state_field,
                (NULLIF(BTRIM(recipient_zip), '') IS NOT NULL OR NULLIF(BTRIM(pop_zip), '') IS NOT NULL) AS has_zip_field
            """
        else:
            select_sql = f"{group_sql} AS value"
        grouped[key] = rows(
            conn,
            f"""
            {STATE_LOOKUP_CTE}
            SELECT
                {select_sql},
                COALESCE(SUM(federal_action_obligation), 0) AS total_obligations,
                COUNT(*)::bigint AS transaction_count,
                COUNT(DISTINCT COALESCE(NULLIF(award_unique_key, ''), NULLIF(generated_unique_award_id, ''), NULLIF(award_id_piid, ''), source_raw_table || ':' || source_raw_id::text))::bigint AS award_count,
                COUNT(DISTINCT COALESCE(NULLIF(recipient_uei, ''), NULLIF(recipient_name, '')))::bigint AS recipient_count
            FROM normalized_fact
            WHERE {normalized_unmapped_where()}
            GROUP BY {group_sql}
            ORDER BY total_obligations DESC NULLS LAST
            LIMIT 100
            """,
            params,
        )

    return {
        "summary": summary,
        "top_100_unmapped_records": all_unmapped[:100],
        "groups": grouped,
        "state_recovery_analysis": state_recovery_analysis(all_unmapped),
    }


def collect_raw_supplemental_fields(conn: sa.Connection, fiscal_year: int) -> dict[str, Any]:
    params = {"fiscal_year": fiscal_year}
    field_rows = rows(
        conn,
        f"""
        SELECT DISTINCT key
        FROM {RAW_ASSISTANCE_TABLE} raw,
             jsonb_object_keys(raw.raw_record) AS key
        WHERE raw.source_fiscal_year = :fiscal_year
          AND (
            key ILIKE '%COVID%'
            OR key ILIKE '%supplemental%'
            OR key ILIKE '%disaster%'
            OR key ILIKE '%emergency%'
            OR key ILIKE '%DEFC%'
            OR key ILIKE '%IIJA%'
          )
        ORDER BY key
        """,
        params,
    )
    fields = [row["key"] for row in field_rows]
    overall = [field for field in fields if "overall_award" in field.lower() or "overall award" in field.lower()]
    likely_transaction = [field for field in fields if field not in overall]
    return {
        "matching_prime_transaction_fields": fields,
        "overall_award_fields": overall,
        "possible_transaction_level_fields": likely_transaction,
        "has_transaction_level_defc_or_disaster_field": any(
            ("defc" in field.lower() or "disaster" in field.lower())
            and field not in overall
            for field in fields
        ),
        "interpretation": (
            "The inspected USAspending prime transaction raw fields only expose overall-award supplemental/DEFC-like indicators."
            if fields and not likely_transaction
            else "At least one non-overall supplemental/DEFC-like field exists; inspect possible_transaction_level_fields before changing exclusion logic."
        ),
    }


def grouped_total(
    conn: sa.Connection,
    *,
    fiscal_year: int,
    where_sql: str,
    group_sql: str,
    select_sql: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    return rows(
        conn,
        f"""
        SELECT
            {select_sql},
            COALESCE(SUM(federal_action_obligation), 0) AS total_obligations,
            COUNT(*)::bigint AS transaction_count,
            COUNT(DISTINCT COALESCE(NULLIF(award_unique_key, ''), NULLIF(generated_unique_award_id, ''), NULLIF(award_id_piid, ''), source_raw_table || ':' || source_raw_id::text))::bigint AS award_count,
            COUNT(DISTINCT COALESCE(NULLIF(recipient_uei, ''), NULLIF(recipient_name, '')))::bigint AS recipient_count
        FROM {FACT_TABLE}
        WHERE {where_sql}
        GROUP BY {group_sql}
        ORDER BY total_obligations DESC NULLS LAST
        LIMIT {limit}
        """,
        base_params(fiscal_year),
    )


def collect_supplemental_diagnostic(conn: sa.Connection, fiscal_year: int) -> dict[str, Any]:
    where_sql = f"{cdc_positive_where()} AND is_covid_or_emergency_supplemental IS TRUE"
    params = base_params(fiscal_year)
    top_records = rows(
        conn,
        f"""
        SELECT
            federal_action_obligation,
            covid_supplemental_obligated_amount,
            iija_supplemental_obligated_amount,
            other_supplemental_obligated_amount,
            recipient_name,
            assistance_listing_number,
            assistance_listing_title,
            federal_accounts_funding_this_award,
            treasury_accounts_funding_this_award,
            transaction_description,
            prime_award_base_transaction_description,
            action_date,
            usaspending_permalink,
            raw_record
        FROM {FACT_TABLE}
        WHERE {where_sql}
        ORDER BY federal_action_obligation DESC NULLS LAST
        LIMIT 200
        """,
        params,
    )
    top_records = [add_supplemental_raw_field_subsets(row) for row in top_records]
    clear_text_condition = supplemental_clear_text_condition()
    suspicious_top = [
        row for row in top_records
        if not text_supplemental_signal(row)
    ][:20]
    return {
        "summary": one_row(conn, metric_query(where_sql), params),
        "by_assistance_listing": grouped_total(
            conn,
            fiscal_year=fiscal_year,
            where_sql=where_sql,
            group_sql="assistance_listing_number, assistance_listing_title",
            select_sql="assistance_listing_number, assistance_listing_title",
        ),
        "by_federal_accounts": grouped_total(
            conn,
            fiscal_year=fiscal_year,
            where_sql=where_sql,
            group_sql="COALESCE(NULLIF(BTRIM(federal_accounts_funding_this_award), ''), '(blank)')",
            select_sql="COALESCE(NULLIF(BTRIM(federal_accounts_funding_this_award), ''), '(blank)') AS federal_accounts_funding_this_award",
        ),
        "by_treasury_accounts": grouped_total(
            conn,
            fiscal_year=fiscal_year,
            where_sql=where_sql,
            group_sql="COALESCE(NULLIF(BTRIM(treasury_accounts_funding_this_award), ''), '(blank)')",
            select_sql="COALESCE(NULLIF(BTRIM(treasury_accounts_funding_this_award), ''), '(blank)') AS treasury_accounts_funding_this_award",
        ),
        "by_recipient_name": grouped_total(
            conn,
            fiscal_year=fiscal_year,
            where_sql=where_sql,
            group_sql="COALESCE(NULLIF(BTRIM(recipient_name), ''), '(blank)')",
            select_sql="COALESCE(NULLIF(BTRIM(recipient_name), ''), '(blank)') AS recipient_name",
        ),
        "by_supplemental_amount_flags": rows(
            conn,
            f"""
            SELECT
                (COALESCE(covid_supplemental_obligated_amount, 0) > 0) AS covid_supplemental_obligated_amount_gt_0,
                (COALESCE(iija_supplemental_obligated_amount, 0) > 0) AS iija_supplemental_obligated_amount_gt_0,
                (COALESCE(other_supplemental_obligated_amount, 0) > 0) AS other_supplemental_obligated_amount_gt_0,
                COALESCE(SUM(federal_action_obligation), 0) AS total_obligations,
                COUNT(*)::bigint AS transaction_count
            FROM {FACT_TABLE}
            WHERE {where_sql}
            GROUP BY
                (COALESCE(covid_supplemental_obligated_amount, 0) > 0),
                (COALESCE(iija_supplemental_obligated_amount, 0) > 0),
                (COALESCE(other_supplemental_obligated_amount, 0) > 0)
            ORDER BY total_obligations DESC NULLS LAST
            """,
            params,
        ),
        "raw_field_diagnostic": collect_raw_supplemental_fields(conn, fiscal_year),
        "top_200_supplemental_excluded_records": top_records,
        "top_20_suspicious_overall_award_flag_exclusions": suspicious_top,
        "clear_transaction_text_condition_used_for_suspicion": clear_text_condition,
    }


def supplemental_clear_text_condition() -> str:
    return """
        (
            assistance_listing_title ILIKE '%COVID%'
            OR assistance_listing_title ILIKE '%coronavirus%'
            OR assistance_listing_title ILIKE '%emergency%'
            OR assistance_listing_title ILIKE '%disaster%'
            OR transaction_description ILIKE '%COVID%'
            OR transaction_description ILIKE '%coronavirus%'
            OR transaction_description ILIKE '%emergency%'
            OR transaction_description ILIKE '%disaster%'
            OR transaction_description ILIKE '%supplemental%'
            OR prime_award_base_transaction_description ILIKE '%COVID%'
            OR prime_award_base_transaction_description ILIKE '%coronavirus%'
            OR prime_award_base_transaction_description ILIKE '%emergency%'
            OR prime_award_base_transaction_description ILIKE '%disaster%'
            OR prime_award_base_transaction_description ILIKE '%supplemental%'
        )
    """


def text_supplemental_signal(row: dict[str, Any]) -> bool:
    blob = " ".join(
        clean_token(row.get(key))
        for key in (
            "assistance_listing_title",
            "transaction_description",
            "prime_award_base_transaction_description",
        )
    ).lower()
    return any(token in blob for token in ("covid", "coronavirus", "emergency", "disaster", "supplemental"))


def scenario_where(scenario: str) -> str:
    base = cdc_positive_where()
    if scenario == "current_overall_award_supplemental_exclusion":
        return f"{base} AND is_covid_or_emergency_supplemental IS FALSE"
    if scenario == "transaction_level_defc_if_available":
        # No transaction-level DEFC-like field is present in current raw FY2023 prime files, so this scenario
        # deliberately keeps all records and reports the absence in raw_field_diagnostic.
        return base
    if scenario == "clear_text_listing_or_account_supplemental_exclusion":
        return f"{base} AND NOT ({supplemental_clear_text_condition()})"
    if scenario == "no_overall_award_exclusion_report_supplemental_separately":
        return base
    raise ValueError(f"Unknown scenario: {scenario}")


def scenario_totals(conn: sa.Connection, fiscal_year: int) -> list[dict[str, Any]]:
    scenarios = [
        {
            "scenario": "current_overall_award_supplemental_exclusion",
            "description": "Exclude if the canonical overall-award COVID/IIJA/other supplemental fields are positive.",
        },
        {
            "scenario": "transaction_level_defc_if_available",
            "description": "Exclude transaction-level DEFC/disaster/emergency records only. No such field was found, so this is currently equivalent to no supplemental exclusion.",
        },
        {
            "scenario": "clear_text_listing_or_account_supplemental_exclusion",
            "description": "Exclude records with clear COVID/coronavirus/emergency/disaster/supplemental text in assistance title or descriptions.",
        },
        {
            "scenario": "no_overall_award_exclusion_report_supplemental_separately",
            "description": "Do not exclude by overall-award supplemental amount; report supplemental amount separately.",
        },
    ]
    output: list[dict[str, Any]] = []
    params = base_params(fiscal_year)
    for scenario in scenarios:
        where_sql = scenario_where(scenario["scenario"])
        state_where = f"""
            source_fiscal_year = :fiscal_year
            AND funding_mechanism = :funding_mechanism
            AND is_positive_obligation IS TRUE
            AND federal_action_obligation > 0
            AND {CDC_FUNDED_STRICT_SQL}
        """
        if "is_covid_or_emergency_supplemental IS FALSE" in where_sql:
            state_where += " AND is_covid_or_emergency_supplemental IS FALSE"
        elif "NOT (" in where_sql and "assistance_listing_title ILIKE" in where_sql:
            state_where += f" AND NOT ({supplemental_clear_text_condition()})"
        all_records = one_row(conn, metric_query(where_sql), params)
        state_identifiable = one_row(
            conn,
            normalized_metric_query(f"{state_where} AND normalized_state_fips IS NOT NULL"),
            params,
        )
        state_unmapped = one_row(
            conn,
            normalized_metric_query(f"{state_where} AND normalized_state_fips IS NULL"),
            params,
        )
        likely_vfc = one_row(conn, metric_query(f"{where_sql} AND {LIKELY_VFC_SQL}"), params)
        non_vfc = one_row(conn, metric_query(f"{where_sql} AND NOT ({LIKELY_VFC_SQL})"), params)
        output.append(
            {
                **scenario,
                "all_records": all_records,
                "state_identifiable_records": state_identifiable,
                "state_unmapped_records": state_unmapped,
                "likely_vfc_excluded_if_applied": likely_vfc,
                "non_vfc_total": non_vfc,
            }
        )
    return output


def reconciliation_tables(conn: sa.Connection, fiscal_year: int) -> dict[str, Any]:
    params = base_params(fiscal_year)
    base = cdc_positive_where()
    select_metrics = """
        COALESCE(SUM(federal_action_obligation), 0) AS total_positive_amount,
        COALESCE(SUM(federal_action_obligation) FILTER (WHERE is_covid_or_emergency_supplemental IS FALSE), 0) AS current_non_supplemental_included_amount,
        COALESCE(SUM(federal_action_obligation) FILTER (WHERE is_covid_or_emergency_supplemental IS TRUE), 0) AS current_supplemental_excluded_amount,
        COALESCE(SUM(federal_action_obligation) FILTER (WHERE {vfc}), 0) AS likely_vfc_amount,
        COUNT(*)::bigint AS transaction_count,
        COUNT(DISTINCT COALESCE(NULLIF(award_unique_key, ''), NULLIF(generated_unique_award_id, ''), NULLIF(award_id_piid, ''), source_raw_table || ':' || source_raw_id::text))::bigint AS award_count,
        COUNT(DISTINCT COALESCE(NULLIF(recipient_uei, ''), NULLIF(recipient_name, '')))::bigint AS recipient_count
    """.format(vfc=LIKELY_VFC_SQL)
    by_listing = rows(
        conn,
        f"""
        {STATE_LOOKUP_CTE}
        SELECT
            assistance_listing_number,
            assistance_listing_title,
            {select_metrics},
            COALESCE(SUM(federal_action_obligation) FILTER (
                WHERE is_covid_or_emergency_supplemental IS FALSE AND normalized_state_fips IS NOT NULL
            ), 0) AS state_identifiable_included_amount,
            COALESCE(SUM(federal_action_obligation) FILTER (
                WHERE is_covid_or_emergency_supplemental IS FALSE AND normalized_state_fips IS NULL
            ), 0) AS state_unmapped_amount
        FROM normalized_fact
        WHERE {base}
        GROUP BY assistance_listing_number, assistance_listing_title
        ORDER BY total_positive_amount DESC NULLS LAST
        """,
        params,
    )
    by_account = rows(
        conn,
        f"""
        {STATE_LOOKUP_CTE}
        SELECT
            COALESCE(NULLIF(BTRIM(federal_accounts_funding_this_award), ''), '(blank)') AS federal_accounts_funding_this_award,
            {select_metrics},
            COALESCE(SUM(federal_action_obligation) FILTER (
                WHERE is_covid_or_emergency_supplemental IS FALSE AND normalized_state_fips IS NOT NULL
            ), 0) AS state_identifiable_included_amount,
            COALESCE(SUM(federal_action_obligation) FILTER (
                WHERE is_covid_or_emergency_supplemental IS FALSE AND normalized_state_fips IS NULL
            ), 0) AS state_unmapped_amount
        FROM normalized_fact
        WHERE {base}
        GROUP BY COALESCE(NULLIF(BTRIM(federal_accounts_funding_this_award), ''), '(blank)')
        ORDER BY total_positive_amount DESC NULLS LAST
        """,
        params,
    )
    return {"by_assistance_listing": by_listing, "by_federal_account": by_account}


def maybe_compare_profiles_csv(csv_path: Path | None, tables: dict[str, Any]) -> dict[str, Any] | None:
    if csv_path is None:
        return None
    if not csv_path.exists():
        return {"error": f"File does not exist: {csv_path}"}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        source_rows = list(reader)
    columns = list(source_rows[0].keys()) if source_rows else []
    listing_columns = [col for col in columns if re.search(r"(assistance|cfda|aln).*number|listing.*number", col, re.I)]
    amount_columns = [col for col in columns if re.search(r"amount|funding|obligation|total", col, re.I)]
    comparison: dict[str, Any] = {
        "path": str(csv_path),
        "row_count": len(source_rows),
        "columns": columns,
        "detected_listing_columns": listing_columns,
        "detected_amount_columns": amount_columns,
        "matched_by_assistance_listing": [],
        "notes": [],
    }
    if not listing_columns:
        comparison["notes"].append("No assistance-listing-number-like column was detected.")
        return comparison
    listing_column = listing_columns[0]
    amount_column = amount_columns[0] if amount_columns else None
    profile_by_listing: dict[str, Decimal] = defaultdict(Decimal)
    profile_counts: Counter[str] = Counter()
    for row in source_rows:
        listing = clean_token(row.get(listing_column))
        if not listing:
            continue
        listing = re.sub(r"[^0-9.]", "", listing)
        profile_by_listing[listing] += parse_decimal(row.get(amount_column)) if amount_column else Decimal("0")
        profile_counts[listing] += 1
    map_by_listing = {
        clean_token(row.get("assistance_listing_number")): row
        for row in tables.get("by_assistance_listing", [])
        if clean_token(row.get("assistance_listing_number"))
    }
    for listing, profile_total in sorted(profile_by_listing.items()):
        map_row = map_by_listing.get(listing, {})
        comparison["matched_by_assistance_listing"].append(
            {
                "assistance_listing_number": listing,
                "profile_csv_amount": profile_total if amount_column else None,
                "profile_csv_row_count": profile_counts[listing],
                "map_current_non_supplemental_included_amount": map_row.get("current_non_supplemental_included_amount"),
                "map_total_positive_amount": map_row.get("total_positive_amount"),
                "difference_vs_current_non_supplemental": (
                    amount(map_row.get("current_non_supplemental_included_amount")) - profile_total
                    if amount_column and map_row
                    else None
                ),
            }
        )
    return comparison


def target_comparisons(scenarios: list[dict[str, Any]], target: Decimal | None) -> list[dict[str, Any]]:
    if target is None:
        return []
    output = []
    for scenario in scenarios:
        for total_key in ("all_records", "state_identifiable_records", "non_vfc_total"):
            total = amount(scenario[total_key].get("total_obligations"))
            difference = total - target
            output.append(
                {
                    "scenario": scenario["scenario"],
                    "total_key": total_key,
                    "total_obligations": total,
                    "funding_profile_target": target,
                    "difference": difference,
                    "percent_difference": (difference / target * Decimal("100")) if target else None,
                }
            )
    return output


def build_report(
    conn: sa.Connection,
    *,
    fiscal_year: int,
    output_path: Path,
    funding_profile_target: Decimal | None,
    funding_profiles_csv: Path | None,
) -> dict[str, Any]:
    unmapped = collect_unmapped_diagnostic(conn, fiscal_year)
    supplemental = collect_supplemental_diagnostic(conn, fiscal_year)
    scenarios = scenario_totals(conn, fiscal_year)
    tables = reconciliation_tables(conn, fiscal_year)
    comparison = maybe_compare_profiles_csv(funding_profiles_csv, tables)
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc),
        "database_url": DATABASE_URL,
        "fiscal_year": fiscal_year,
        "funding_mechanism": FUNDING_MECHANISM,
        "amount_field": "federal_action_obligation",
        "output_path": output_path,
        "funding_profile_target": funding_profile_target,
        "funding_profiles_csv": funding_profiles_csv,
        "state_unmapped_diagnostic": unmapped,
        "supplemental_exclusion_diagnostic": supplemental,
        "alternative_supplemental_exclusion_scenarios": scenarios,
        "funding_profile_target_comparisons": target_comparisons(scenarios, funding_profile_target),
        "assistance_listing_and_federal_account_reconciliation": tables,
        "funding_profiles_csv_comparison": comparison,
    }
    report["recommended_next_adjustment"] = recommend(report)
    return report


def recommend(report: dict[str, Any]) -> list[str]:
    recommendations: list[str] = []
    raw_diag = report["supplemental_exclusion_diagnostic"]["raw_field_diagnostic"]
    recovery = report["state_unmapped_diagnostic"]["state_recovery_analysis"]
    current = next(
        item for item in report["alternative_supplemental_exclusion_scenarios"]
        if item["scenario"] == "current_overall_award_supplemental_exclusion"
    )
    no_overall = next(
        item for item in report["alternative_supplemental_exclusion_scenarios"]
        if item["scenario"] == "no_overall_award_exclusion_report_supplemental_separately"
    )
    delta = amount(no_overall["state_identifiable_records"]["total_obligations"]) - amount(
        current["state_identifiable_records"]["total_obligations"]
    )
    if not raw_diag["possible_transaction_level_fields"] and delta > Decimal("1000000000"):
        recommendations.append(
            "Treat the current overall-award supplemental exclusion as potentially too broad; no transaction-level DEFC/COVID field was found in the raw FY2023 prime transaction files."
        )
    if amount(recovery["potentially_recoverable_amount_using_raw_state_or_zip_fields"]) > Decimal("0"):
        recommendations.append(
            "Before changing map totals, inspect raw state/ZIP candidate fields for unmapped rows and add a tested normalization rule if those fields are reliable."
        )
    recommendations.append(
        "Compare CDC Funding Profiles by assistance listing/federal account before changing ingestion; the largest differences concentrate in a small number of listings and accounts."
    )
    return recommendations


def format_money(value: Any) -> str:
    return f"${amount(value):,.2f}"


def print_summary(report: dict[str, Any]) -> None:
    unmapped = report["state_unmapped_diagnostic"]
    recovery = unmapped["state_recovery_analysis"]
    supp = report["supplemental_exclusion_diagnostic"]
    scenarios = report["alternative_supplemental_exclusion_scenarios"]
    print(f"FY{report['fiscal_year']} CDC funding deep dive")
    print(f"Output: {report['output_path']}")
    print()
    print("State-unmapped bucket")
    print(f"  Total: {format_money(unmapped['summary']['total_obligations'])}")
    print(f"  Potentially recoverable from raw state/ZIP fields: {format_money(recovery['potentially_recoverable_amount_using_raw_state_or_zip_fields'])}")
    print(f"  Candidate transactions: {recovery['potentially_recoverable_transaction_count']}")
    print()
    print("Supplemental exclusion")
    print(f"  Current excluded total: {format_money(supp['summary']['total_obligations'])}")
    print(f"  Raw matching fields: {', '.join(supp['raw_field_diagnostic']['matching_prime_transaction_fields']) or 'none'}")
    print(f"  Possible transaction-level fields: {', '.join(supp['raw_field_diagnostic']['possible_transaction_level_fields']) or 'none'}")
    print()
    print("Alternative scenario totals")
    for scenario in scenarios:
        print(
            f"  {scenario['scenario']}: all={format_money(scenario['all_records']['total_obligations'])}; "
            f"state-identifiable={format_money(scenario['state_identifiable_records']['total_obligations'])}; "
            f"state-unmapped={format_money(scenario['state_unmapped_records']['total_obligations'])}; "
            f"non-VFC={format_money(scenario['non_vfc_total']['total_obligations'])}"
        )
    print()
    print("Top current supplemental-excluded assistance listings")
    for row in supp["by_assistance_listing"][:8]:
        print(f"  {row.get('assistance_listing_number') or '(blank)'} {row.get('assistance_listing_title') or ''}: {format_money(row['total_obligations'])}")
    print()
    print("Top current supplemental-excluded federal accounts")
    for row in supp["by_federal_accounts"][:8]:
        print(f"  {row.get('federal_accounts_funding_this_award') or '(blank)'}: {format_money(row['total_obligations'])}")
    print()
    print("Recommendations")
    for item in report["recommended_next_adjustment"]:
        print(f"  - {item}")


def main() -> int:
    args = parse_args()
    output_path = args.output.resolve()
    engine = sa.create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.connect() as conn:
        report = build_report(
            conn,
            fiscal_year=args.fiscal_year,
            output_path=output_path,
            funding_profile_target=args.funding_profile_target,
            funding_profiles_csv=args.funding_profiles_csv,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(json_ready(report), indent=2, sort_keys=True), encoding="utf-8")
    print_summary(json_ready(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
