#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import sqlalchemy as sa
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import DATABASE_URL  # noqa: E402
from app.db_fqtn import cdc_funding_table  # noqa: E402


FISCAL_YEAR = 2021
FUNDING_MECHANISM = "grants_cooperative_agreements"
FUNDING_PROFILE_TARGET = Decimal("4075872116.00")
DEFAULT_OUTPUT_PATH = BACKEND_ROOT / "data_profiles" / "fy2021_immunization_outlier_diagnostic.json"
DEFAULT_SUMMARY_CSV_PATH = (
    BACKEND_ROOT / "data_profiles" / "fy2021_immunization_outlier_diagnostic_summary.csv"
)
FACT_TABLE = cdc_funding_table("fact_cdc_funding_prime_transaction")

COVID_TEXT_RE = re.compile(
    r"COVID|coronavirus|pandemic|vaccine response|vaccine preparedness|"
    r"vaccine implementation|ARP|American Rescue Plan|CARES|supplemental",
    re.IGNORECASE,
)
VFC_TEXT_RE = re.compile(
    r"immunization and vaccines for children|vaccines for children|\bVFC\b",
    re.IGNORECASE,
)
ORDINARY_TEXT_RE = re.compile(
    r"Section 317|immunization cooperative agreement|immunization cooperative agreements",
    re.IGNORECASE,
)

BASE_WHERE = """
    source_fiscal_year = :fiscal_year
    AND funding_mechanism = :funding_mechanism
    AND is_prime_award IS TRUE
    AND is_positive_obligation IS TRUE
    AND is_cdc_funded IS TRUE
    AND federal_action_obligation > 0
"""

IMMUNIZATION_WHERE = f"""
    {BASE_WHERE}
    AND (
        assistance_listing_number = '93.268'
        OR COALESCE(is_likely_vfc, false) IS TRUE
    )
"""

STATE_LOOKUP_CTE = f"""
    WITH state_lookup(state_fips, state_code, state_name) AS (
        VALUES
        ('01','AL','Alabama'),('02','AK','Alaska'),('04','AZ','Arizona'),('05','AR','Arkansas'),
        ('06','CA','California'),('08','CO','Colorado'),('09','CT','Connecticut'),('10','DE','Delaware'),
        ('11','DC','District of Columbia'),('12','FL','Florida'),('13','GA','Georgia'),('15','HI','Hawaii'),
        ('16','ID','Idaho'),('17','IL','Illinois'),('18','IN','Indiana'),('19','IA','Iowa'),
        ('20','KS','Kansas'),('21','KY','Kentucky'),('22','LA','Louisiana'),('23','ME','Maine'),
        ('24','MD','Maryland'),('25','MA','Massachusetts'),('26','MI','Michigan'),('27','MN','Minnesota'),
        ('28','MS','Mississippi'),('29','MO','Missouri'),('30','MT','Montana'),('31','NE','Nebraska'),
        ('32','NV','Nevada'),('33','NH','New Hampshire'),('34','NJ','New Jersey'),('35','NM','New Mexico'),
        ('36','NY','New York'),('37','NC','North Carolina'),('38','ND','North Dakota'),('39','OH','Ohio'),
        ('40','OK','Oklahoma'),('41','OR','Oregon'),('42','PA','Pennsylvania'),('44','RI','Rhode Island'),
        ('45','SC','South Carolina'),('46','SD','South Dakota'),('47','TN','Tennessee'),('48','TX','Texas'),
        ('49','UT','Utah'),('50','VT','Vermont'),('51','VA','Virginia'),('53','WA','Washington'),
        ('54','WV','West Virginia'),('55','WI','Wisconsin'),('56','WY','Wyoming'),('60','AS','American Samoa'),
        ('66','GU','Guam'),('69','MP','Northern Mariana Islands'),('72','PR','Puerto Rico'),('78','VI','U.S. Virgin Islands')
    ),
    normalized_fact AS (
        SELECT
            fact.*,
            COALESCE(
                pop_state_lookup.state_fips,
                CASE WHEN fact.pop_county_fips ~ '^[0-9]{{5}}$' THEN LEFT(fact.pop_county_fips, 2) END,
                recipient_state_lookup.state_fips,
                CASE WHEN fact.recipient_county_fips ~ '^[0-9]{{5}}$' THEN LEFT(fact.recipient_county_fips, 2) END,
                map_state_lookup.state_fips,
                CASE WHEN fact.map_state_code ~ '^[0-9]{{2}}$' THEN fact.map_state_code END
            ) AS normalized_state_fips
        FROM {FACT_TABLE} AS fact
        LEFT JOIN state_lookup AS pop_state_lookup
          ON pop_state_lookup.state_code = UPPER(NULLIF(BTRIM(fact.pop_state_code), ''))
        LEFT JOIN state_lookup AS recipient_state_lookup
          ON recipient_state_lookup.state_code = UPPER(NULLIF(BTRIM(fact.recipient_state_code), ''))
        LEFT JOIN state_lookup AS map_state_lookup
          ON map_state_lookup.state_code = UPPER(NULLIF(BTRIM(fact.map_state_code), ''))
    )
"""

PARAMS = {
    "fiscal_year": FISCAL_YEAR,
    "funding_mechanism": FUNDING_MECHANISM,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnose the FY2021 CDC Funding Profiles comparable-mode 93.268 outlier."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--summary-csv", type=Path, default=DEFAULT_SUMMARY_CSV_PATH)
    parser.add_argument(
        "--funding-profile-target",
        type=Decimal,
        default=FUNDING_PROFILE_TARGET,
    )
    return parser.parse_args()


def json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    return value


def amount(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rows(conn: sa.Connection, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text(sql), params or {}).mappings().all()]


def one_row(conn: sa.Connection, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    row = conn.execute(text(sql), params or {}).mappings().first()
    return dict(row) if row is not None else {}


def metric_dict(total: Decimal = Decimal("0"), count: int = 0) -> dict[str, Any]:
    return {
        "total_obligations": total,
        "transaction_count": count,
    }


def add_metric(bucket: dict[str, Any], row: dict[str, Any]) -> None:
    bucket["total_obligations"] += amount(row.get("federal_action_obligation"))
    bucket["transaction_count"] += 1


def text_blob(row: dict[str, Any]) -> str:
    fields = [
        "assistance_listing_title",
        "transaction_description",
        "prime_award_base_transaction_description",
        "federal_accounts_funding_this_award",
        "treasury_accounts_funding_this_award",
        "program_activities_funding_this_award",
        "object_classes_funding_this_award",
        "funding_profiles_exclusion_reason",
    ]
    raw_record = row.get("raw_record") or {}
    values = [str(row.get(field) or "") for field in fields]
    values.extend(
        str(raw_record.get(field) or "")
        for field in (
            "cfda_title",
            "disaster_emergency_fund_codes_for_overall_award",
            "obligated_amount_from_COVID-19_supplementals_for_overall_award",
            "obligated_amount_from_IIJA_supplemental_for_overall_award",
        )
    )
    return " ".join(values)


def has_covid_or_supplemental_text(row: dict[str, Any]) -> bool:
    return COVID_TEXT_RE.search(text_blob(row)) is not None


def classify_bucket(row: dict[str, Any]) -> str:
    blob = text_blob(row)
    covid_or_supplemental = has_covid_or_supplemental_text(row)
    has_covid_history = amount(row.get("covid_supplemental_obligated_amount")) > 0
    has_iija_history = amount(row.get("iija_supplemental_obligated_amount")) > 0
    has_defc_supplemental = bool(row.get("has_defc_non_q"))
    if covid_or_supplemental or has_covid_history or has_iija_history or has_defc_supplemental:
        return "likely_covid_immunization_response"
    if VFC_TEXT_RE.search(blob):
        return "likely_vfc_vaccine_purchase_or_vaccine_supply"
    if ORDINARY_TEXT_RE.search(blob):
        return "ordinary_immunization_cooperative_agreement"
    return "unclear"


def split_semicolon_values(value: str | None) -> list[str]:
    parts = [part.strip() for part in str(value or "").split(";")]
    return [part for part in parts if part]


def metric_rows(
    metrics: dict[Any, dict[str, Any]],
    key_builder,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    output = [
        {
            **key_builder(key),
            "total_obligations": metric["total_obligations"],
            "transaction_count": metric["transaction_count"],
        }
        for key, metric in metrics.items()
    ]
    output.sort(key=lambda row: (row["total_obligations"], row["transaction_count"]), reverse=True)
    return output[:limit] if limit is not None else output


def build_python_rollups(immunization_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_defc_classification: dict[str, dict[str, Any]] = defaultdict(metric_dict)
    by_defc_code: dict[str, dict[str, Any]] = defaultdict(metric_dict)
    by_federal_account: dict[str, dict[str, Any]] = defaultdict(metric_dict)
    by_treasury_account: dict[str, dict[str, Any]] = defaultdict(metric_dict)
    by_program_activity: dict[str, dict[str, Any]] = defaultdict(metric_dict)
    by_object_class: dict[str, dict[str, Any]] = defaultdict(metric_dict)
    by_assistance_type: dict[tuple[str, str], dict[str, Any]] = defaultdict(metric_dict)
    by_recipient_state: dict[str, dict[str, Any]] = defaultdict(metric_dict)
    by_pop_state: dict[str, dict[str, Any]] = defaultdict(metric_dict)
    by_map_state: dict[str, dict[str, Any]] = defaultdict(metric_dict)
    by_bucket: dict[str, dict[str, Any]] = defaultdict(metric_dict)

    for row in immunization_rows:
        add_metric(by_defc_classification[row.get("defc_classification") or "(blank)"], row)
        defc_codes = row.get("defc_codes") or []
        if not defc_codes:
            add_metric(by_defc_code["(blank)"], row)
        for code in defc_codes:
            add_metric(by_defc_code[str(code)], row)
        for value in split_semicolon_values(row.get("federal_accounts_funding_this_award")) or ["(blank)"]:
            add_metric(by_federal_account[value], row)
        for value in split_semicolon_values(row.get("treasury_accounts_funding_this_award")) or ["(blank)"]:
            add_metric(by_treasury_account[value], row)
        for value in split_semicolon_values(row.get("program_activities_funding_this_award")) or ["(blank)"]:
            add_metric(by_program_activity[value], row)
        for value in split_semicolon_values(row.get("object_classes_funding_this_award")) or ["(blank)"]:
            add_metric(by_object_class[value], row)
        add_metric(
            by_assistance_type[
                (
                    row.get("assistance_type_code") or "(blank)",
                    row.get("assistance_type_description") or "(blank)",
                )
            ],
            row,
        )
        add_metric(by_recipient_state[row.get("recipient_state_code") or "(blank)"], row)
        add_metric(by_pop_state[row.get("pop_state_code") or "(blank)"], row)
        add_metric(by_map_state[row.get("map_state_code") or "(blank)"], row)
        add_metric(by_bucket[classify_bucket(row)], row)

    return {
        "by_defc_classification": metric_rows(
            by_defc_classification,
            lambda key: {"defc_classification": key},
        ),
        "by_individual_defc_code": metric_rows(
            by_defc_code,
            lambda key: {"defc_code": key},
        ),
        "by_federal_account": metric_rows(
            by_federal_account,
            lambda key: {"federal_account_symbol_name": key},
        ),
        "by_treasury_account": metric_rows(
            by_treasury_account,
            lambda key: {"treasury_account_symbol_name": key},
        ),
        "by_program_activity": metric_rows(
            by_program_activity,
            lambda key: {"program_activity_code_name": key},
        ),
        "by_object_class": metric_rows(
            by_object_class,
            lambda key: {"object_class": key},
        ),
        "by_assistance_type": metric_rows(
            by_assistance_type,
            lambda key: {
                "assistance_type_code": key[0],
                "assistance_type_description": key[1],
            },
        ),
        "by_recipient_state": metric_rows(
            by_recipient_state,
            lambda key: {"recipient_state_code": key},
        ),
        "by_place_of_performance_state": metric_rows(
            by_pop_state,
            lambda key: {"pop_state_code": key},
        ),
        "by_map_state": metric_rows(
            by_map_state,
            lambda key: {"map_state_code": key},
        ),
        "heuristic_bucket_totals": metric_rows(
            by_bucket,
            lambda key: {"heuristic_bucket": key},
        ),
        "note": (
            "Federal account, treasury account, program activity, object class, and individual "
            "DEFC code rollups are not additive when an award-history field contains multiple values."
        ),
    }


def fetch_immunization_rows(conn: sa.Connection) -> list[dict[str, Any]]:
    return rows(
        conn,
        f"""
        SELECT
            id,
            source_raw_table,
            source_raw_id,
            source_fiscal_year,
            funding_mechanism,
            transaction_unique_key,
            award_unique_key,
            generated_unique_award_id,
            federal_action_obligation,
            action_date,
            recipient_name,
            recipient_state_code,
            pop_state_code,
            map_state_code,
            map_geography_source,
            assistance_listing_number,
            assistance_listing_title,
            assistance_type_code,
            assistance_type_description,
            federal_accounts_funding_this_award,
            treasury_accounts_funding_this_award,
            program_activities_funding_this_award,
            object_classes_funding_this_award,
            transaction_description,
            prime_award_base_transaction_description,
            usaspending_permalink,
            covid_supplemental_obligated_amount,
            iija_supplemental_obligated_amount,
            defc_codes,
            defc_classification,
            has_defc_non_q,
            has_overall_award_supplemental_history,
            is_likely_vfc,
            funding_profiles_comparison_excluded,
            funding_profiles_exclusion_reason,
            raw_record
        FROM {FACT_TABLE}
        WHERE {IMMUNIZATION_WHERE}
        ORDER BY federal_action_obligation DESC NULLS LAST
        """,
        PARAMS,
    )


def top_transactions(immunization_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in immunization_rows[:100]:
        raw_record = row.get("raw_record") or {}
        output.append(
            {
                "federal_action_obligation": row.get("federal_action_obligation"),
                "recipient_name": row.get("recipient_name"),
                "recipient_state_code": row.get("recipient_state_code"),
                "pop_state_code": row.get("pop_state_code"),
                "map_state_code": row.get("map_state_code"),
                "map_geography_source": row.get("map_geography_source"),
                "assistance_listing_number": row.get("assistance_listing_number"),
                "assistance_listing_title": row.get("assistance_listing_title"),
                "award_id_fain": raw_record.get("award_id_fain") or row.get("generated_unique_award_id"),
                "assistance_award_unique_key": raw_record.get("assistance_award_unique_key")
                or row.get("award_unique_key"),
                "action_date": row.get("action_date"),
                "disaster_emergency_fund_codes_for_overall_award": raw_record.get(
                    "disaster_emergency_fund_codes_for_overall_award"
                ),
                "obligated_amount_from_COVID-19_supplementals_for_overall_award": (
                    raw_record.get("obligated_amount_from_COVID-19_supplementals_for_overall_award")
                    or row.get("covid_supplemental_obligated_amount")
                ),
                "obligated_amount_from_IIJA_supplemental_for_overall_award": (
                    raw_record.get("obligated_amount_from_IIJA_supplemental_for_overall_award")
                    or row.get("iija_supplemental_obligated_amount")
                ),
                "federal_account_symbol_name": row.get("federal_accounts_funding_this_award"),
                "treasury_account_symbol_name": row.get("treasury_accounts_funding_this_award"),
                "program_activity_code_name": row.get("program_activities_funding_this_award"),
                "object_class": row.get("object_classes_funding_this_award"),
                "assistance_type_code": row.get("assistance_type_code"),
                "assistance_type_description": row.get("assistance_type_description"),
                "transaction_description": row.get("transaction_description"),
                "prime_award_base_transaction_description": row.get(
                    "prime_award_base_transaction_description"
                ),
                "usaspending_permalink": row.get("usaspending_permalink"),
                "defc_classification": row.get("defc_classification"),
                "heuristic_bucket": classify_bucket(row),
                "funding_profiles_comparison_excluded": row.get(
                    "funding_profiles_comparison_excluded"
                ),
            }
        )
    return output


def scenario_sql() -> str:
    covid_text_sql = """
        (
            COALESCE(assistance_listing_title, '') || ' ' ||
            COALESCE(transaction_description, '') || ' ' ||
            COALESCE(prime_award_base_transaction_description, '') || ' ' ||
            COALESCE(federal_accounts_funding_this_award, '') || ' ' ||
            COALESCE(treasury_accounts_funding_this_award, '') || ' ' ||
            COALESCE(program_activities_funding_this_award, '') || ' ' ||
            COALESCE(object_classes_funding_this_award, '') || ' ' ||
            COALESCE(funding_profiles_exclusion_reason, '') || ' ' ||
            COALESCE(raw_record->>'disaster_emergency_fund_codes_for_overall_award', '')
        ) ~* '(COVID|coronavirus|pandemic|vaccine response|vaccine preparedness|vaccine implementation|ARP|American Rescue Plan|CARES|supplemental)'
    """
    vfc_sql = """
        (
            COALESCE(assistance_listing_title, '') || ' ' ||
            COALESCE(transaction_description, '') || ' ' ||
            COALESCE(prime_award_base_transaction_description, '')
        ) ~* '(immunization and vaccines for children|vaccines for children|\\mVFC\\M)'
    """
    ordinary_sql = """
        (
            COALESCE(assistance_listing_title, '') || ' ' ||
            COALESCE(transaction_description, '') || ' ' ||
            COALESCE(prime_award_base_transaction_description, '')
        ) ~* '(Section 317|immunization cooperative agreement|immunization cooperative agreements)'
    """
    immunization_sql = "(assistance_listing_number = '93.268' OR COALESCE(is_likely_vfc, false) IS TRUE)"
    b_exclude_sql = f"""
        {immunization_sql}
        AND (
            {covid_text_sql}
            OR COALESCE(has_defc_non_q, false) IS TRUE
            OR COALESCE(has_overall_award_supplemental_history, false) IS TRUE
        )
    """
    c_exclude_sql = f"""
        {immunization_sql}
        AND (
            {covid_text_sql}
            OR COALESCE(covid_supplemental_obligated_amount, 0) > 0
            OR COALESCE(iija_supplemental_obligated_amount, 0) > 0
        )
    """
    d_exclude_sql = immunization_sql
    e_exclude_sql = f"""
        {immunization_sql}
        AND NOT (
            ({ordinary_sql} OR {vfc_sql})
            AND NOT ({covid_text_sql})
            AND COALESCE(covid_supplemental_obligated_amount, 0) = 0
            AND COALESCE(iija_supplemental_obligated_amount, 0) = 0
            AND COALESCE(has_defc_non_q, false) IS FALSE
        )
    """
    return f"""
        {STATE_LOOKUP_CTE}
        SELECT
            COALESCE(SUM(CASE WHEN COALESCE(funding_profiles_comparison_excluded, false) IS FALSE
                AND normalized_state_fips IS NOT NULL
                THEN federal_action_obligation ELSE 0 END), 0) AS a_state_mapped_total,
            COALESCE(SUM(CASE WHEN COALESCE(funding_profiles_comparison_excluded, false) IS FALSE
                AND normalized_state_fips IS NULL
                THEN federal_action_obligation ELSE 0 END), 0) AS a_unmapped_total,
            COALESCE(SUM(CASE WHEN COALESCE(funding_profiles_comparison_excluded, false) IS FALSE
                AND NOT ({b_exclude_sql})
                AND normalized_state_fips IS NOT NULL
                THEN federal_action_obligation ELSE 0 END), 0) AS b_state_mapped_total,
            COALESCE(SUM(CASE WHEN COALESCE(funding_profiles_comparison_excluded, false) IS FALSE
                AND NOT ({b_exclude_sql})
                AND normalized_state_fips IS NULL
                THEN federal_action_obligation ELSE 0 END), 0) AS b_unmapped_total,
            COALESCE(SUM(CASE WHEN COALESCE(funding_profiles_comparison_excluded, false) IS FALSE
                AND NOT ({c_exclude_sql})
                AND normalized_state_fips IS NOT NULL
                THEN federal_action_obligation ELSE 0 END), 0) AS c_state_mapped_total,
            COALESCE(SUM(CASE WHEN COALESCE(funding_profiles_comparison_excluded, false) IS FALSE
                AND NOT ({c_exclude_sql})
                AND normalized_state_fips IS NULL
                THEN federal_action_obligation ELSE 0 END), 0) AS c_unmapped_total,
            COALESCE(SUM(CASE WHEN COALESCE(funding_profiles_comparison_excluded, false) IS FALSE
                AND NOT ({d_exclude_sql})
                AND normalized_state_fips IS NOT NULL
                THEN federal_action_obligation ELSE 0 END), 0) AS d_state_mapped_total,
            COALESCE(SUM(CASE WHEN COALESCE(funding_profiles_comparison_excluded, false) IS FALSE
                AND NOT ({d_exclude_sql})
                AND normalized_state_fips IS NULL
                THEN federal_action_obligation ELSE 0 END), 0) AS d_unmapped_total,
            COALESCE(SUM(CASE WHEN COALESCE(funding_profiles_comparison_excluded, false) IS FALSE
                AND NOT ({e_exclude_sql})
                AND normalized_state_fips IS NOT NULL
                THEN federal_action_obligation ELSE 0 END), 0) AS e_state_mapped_total,
            COALESCE(SUM(CASE WHEN COALESCE(funding_profiles_comparison_excluded, false) IS FALSE
                AND NOT ({e_exclude_sql})
                AND normalized_state_fips IS NULL
                THEN federal_action_obligation ELSE 0 END), 0) AS e_unmapped_total
        FROM normalized_fact
        WHERE {BASE_WHERE}
    """


def build_scenarios(conn: sa.Connection, target: Decimal) -> list[dict[str, Any]]:
    row = one_row(conn, scenario_sql(), PARAMS)
    definitions = [
        ("A", "Current methodology: include 93.268 even when supplemental-history flagged."),
        ("B", "Exclude all 93.268/immunization with COVID/supplemental text or DEFC supplemental history."),
        (
            "C",
            "Include only 93.268/immunization records without COVID/supplemental text and without overall-award COVID/IIJA supplemental history.",
        ),
        ("D", "Exclude all 93.268/immunization from Funding Profiles Comparable."),
        ("E", "Include capped/ordinary 93.268/immunization amount from clear non-COVID ordinary/VFC text subset."),
    ]
    scenarios: list[dict[str, Any]] = []
    for key, label in definitions:
        state_total = amount(row.get(f"{key.lower()}_state_mapped_total"))
        unmapped_total = amount(row.get(f"{key.lower()}_unmapped_total"))
        total = state_total + unmapped_total
        scenarios.append(
            {
                "scenario": key,
                "label": label,
                "state_mapped_total": state_total,
                "unmapped_total": unmapped_total,
                "total_including_unmapped": total,
                "funding_profiles_target": target,
                "residual_vs_funding_profiles_target": total - target,
            }
        )
    return scenarios


def build_summary_metrics(immunization_rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum((amount(row.get("federal_action_obligation")) for row in immunization_rows), Decimal("0"))
    total_93268_only = sum(
        (
            amount(row.get("federal_action_obligation"))
            for row in immunization_rows
            if row.get("assistance_listing_number") == "93.268"
        ),
        Decimal("0"),
    )
    total_likely_vfc_non_93268 = total - total_93268_only
    included = sum(
        (
            amount(row.get("federal_action_obligation"))
            for row in immunization_rows
            if not row.get("funding_profiles_comparison_excluded")
        ),
        Decimal("0"),
    )
    excluded = total - included
    covid_history = sum(
        (
            amount(row.get("federal_action_obligation"))
            for row in immunization_rows
            if amount(row.get("covid_supplemental_obligated_amount")) > 0
        ),
        Decimal("0"),
    )
    iija_history = sum(
        (
            amount(row.get("federal_action_obligation"))
            for row in immunization_rows
            if amount(row.get("iija_supplemental_obligated_amount")) > 0
        ),
        Decimal("0"),
    )
    return {
        "total_fy2021_93268_immunization_amount": total,
        "total_fy2021_93268_only_amount": total_93268_only,
        "total_fy2021_likely_vfc_non_93268_amount": total_likely_vfc_non_93268,
        "currently_included_in_funding_profiles_comparable": included,
        "currently_excluded_in_funding_profiles_comparable": excluded,
        "amount_with_overall_award_covid_supplemental_amount_gt_0": covid_history,
        "amount_with_overall_award_iija_supplemental_amount_gt_0": iija_history,
        "transaction_count": len(immunization_rows),
    }


def recommendation(payload: dict[str, Any]) -> dict[str, Any]:
    scenarios = {row["scenario"]: row for row in payload["scenario_comparison"]}
    closest = min(
        scenarios.values(),
        key=lambda row: abs(amount(row["residual_vs_funding_profiles_target"])),
    )
    current_residual = amount(scenarios["A"]["residual_vs_funding_profiles_target"])
    b_residual = amount(scenarios["B"]["residual_vs_funding_profiles_target"])
    bucket_rows = payload["rollups"]["heuristic_bucket_totals"]
    covid_bucket = next(
        (
            amount(row["total_obligations"])
            for row in bucket_rows
            if row["heuristic_bucket"] == "likely_covid_immunization_response"
        ),
        Decimal("0"),
    )
    total_immunization = amount(
        payload["summary_metrics"]["total_fy2021_93268_immunization_amount"]
    )
    covid_share = covid_bucket / total_immunization if total_immunization else Decimal("0")

    if closest["scenario"] in {"B", "C"} and abs(b_residual) < abs(current_residual):
        decision = "year-specific COVID immunization exclusion"
    elif closest["scenario"] == "D":
        decision = "further manual review"
    elif closest["scenario"] == "A":
        decision = "no change"
    else:
        decision = "general rule excluding 93.268 when COVID/supplemental text/history is present"

    display_line = covid_share >= Decimal("0.50")
    options = {
        "no_change": decision == "no change",
        "year_specific_covid_immunization_exclusion": decision == "year-specific COVID immunization exclusion",
        "general_rule_excluding_93268_when_covid_supplemental_text_history_present": (
            decision == "general rule excluding 93.268 when COVID/supplemental text/history is present"
        ),
        "separate_display_line_for_covid_era_immunization_obligations": display_line,
        "further_manual_review": decision == "further manual review" or closest["scenario"] == "D",
    }
    return {
        "recommended_methodology_decision": decision,
        "recommended_option_flags": options,
        "closest_scenario": closest,
        "rationale": [
            (
                "The current comparable method retains 93.268/immunization records because "
                "93.268 is classified as likely VFC, even when award-level supplemental "
                "signals are present."
            ),
            (
                f"The likely COVID immunization-response heuristic bucket accounts for "
                f"{float(covid_share * Decimal('100')):.1f}% of the FY2021 93.268/immunization total."
            ),
            (
                "Treat this as diagnostic evidence only; review the top transactions and "
                "account/program-activity rollups before changing production behavior."
            ),
        ],
    }


def write_summary_csv(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "section",
        "key",
        "label",
        "total_obligations",
        "transaction_count",
        "state_mapped_total",
        "unmapped_total",
        "total_including_unmapped",
        "residual_vs_funding_profiles_target",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for key, value in payload["summary_metrics"].items():
            writer.writerow(
                {
                    "section": "summary_metrics",
                    "key": key,
                    "total_obligations": value if key != "transaction_count" else "",
                    "transaction_count": value if key == "transaction_count" else "",
                }
            )
        for row in payload["rollups"]["heuristic_bucket_totals"]:
            writer.writerow(
                {
                    "section": "heuristic_bucket_totals",
                    "key": row["heuristic_bucket"],
                    "total_obligations": row["total_obligations"],
                    "transaction_count": row["transaction_count"],
                }
            )
        for row in payload["scenario_comparison"]:
            writer.writerow(
                {
                    "section": "scenario_comparison",
                    "key": row["scenario"],
                    "label": row["label"],
                    "state_mapped_total": row["state_mapped_total"],
                    "unmapped_total": row["unmapped_total"],
                    "total_including_unmapped": row["total_including_unmapped"],
                    "residual_vs_funding_profiles_target": row[
                        "residual_vs_funding_profiles_target"
                    ],
                }
            )
        for row in payload["rollups"]["by_defc_classification"]:
            writer.writerow(
                {
                    "section": "by_defc_classification",
                    "key": row["defc_classification"],
                    "total_obligations": row["total_obligations"],
                    "transaction_count": row["transaction_count"],
                }
            )


def main() -> None:
    args = parse_args()
    engine = sa.create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.connect() as conn:
        immunization_rows = fetch_immunization_rows(conn)
        immunization_state_split = one_row(
            conn,
            f"""
            {STATE_LOOKUP_CTE}
            SELECT
                COALESCE(SUM(CASE WHEN assistance_listing_number = '93.268'
                    AND normalized_state_fips IS NOT NULL
                    THEN federal_action_obligation ELSE 0 END), 0) AS state_mapped_93268_only,
                COALESCE(SUM(CASE WHEN assistance_listing_number = '93.268'
                    AND normalized_state_fips IS NULL
                    THEN federal_action_obligation ELSE 0 END), 0) AS unmapped_93268_only,
                COALESCE(SUM(CASE WHEN (assistance_listing_number = '93.268'
                    OR COALESCE(is_likely_vfc, false) IS TRUE)
                    AND normalized_state_fips IS NOT NULL
                    THEN federal_action_obligation ELSE 0 END), 0) AS state_mapped_93268_immunization,
                COALESCE(SUM(CASE WHEN (assistance_listing_number = '93.268'
                    OR COALESCE(is_likely_vfc, false) IS TRUE)
                    AND normalized_state_fips IS NULL
                    THEN federal_action_obligation ELSE 0 END), 0) AS unmapped_93268_immunization
            FROM normalized_fact
            WHERE {IMMUNIZATION_WHERE}
            """,
            PARAMS,
        )
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "fiscal_year": FISCAL_YEAR,
            "funding_profiles_target": args.funding_profile_target,
            "source_table": FACT_TABLE,
            "filters": {
                "source_fiscal_year": FISCAL_YEAR,
                "funding_mechanism": FUNDING_MECHANISM,
                "is_prime_award": True,
                "is_positive_obligation": True,
                "is_cdc_funded": True,
                "assistance_listing_number_or_cfda_number": "93.268",
                "or_is_likely_vfc": True,
            },
            "summary_metrics": build_summary_metrics(immunization_rows),
            "immunization_state_mapping_split": immunization_state_split,
            "rollups": build_python_rollups(immunization_rows),
            "top_100_transactions_by_federal_action_obligation": top_transactions(immunization_rows),
            "scenario_comparison": build_scenarios(conn, args.funding_profile_target),
        }
        payload["recommendation"] = recommendation(payload)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(json_ready(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_summary_csv(args.summary_csv, json_ready(payload))

    print("FY2021 immunization outlier diagnostic written")
    print(f"JSON: {args.output}")
    print(f"CSV: {args.summary_csv}")
    print(
        "FY2021 93.268/immunization total: "
        f"{payload['summary_metrics']['total_fy2021_93268_immunization_amount']:,.2f}"
    )
    print("Scenario residuals:")
    for row in payload["scenario_comparison"]:
        print(
            f"  {row['scenario']}: total={row['total_including_unmapped']:,.2f}; "
            f"residual={row['residual_vs_funding_profiles_target']:,.2f}"
        )
    print(
        "Recommendation: "
        f"{payload['recommendation']['recommended_methodology_decision']}"
    )


if __name__ == "__main__":
    main()
