#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import DATABASE_URL  # noqa: E402
from app.db_fqtn import cdc_funding_table  # noqa: E402


DEFAULT_OUTPUT_PATH = BACKEND_ROOT / "data_profiles" / "fy2023_cdc_funding_reconciliation.json"
DEFAULT_FISCAL_YEAR = 2023
FUNDING_MECHANISM = "grants_cooperative_agreements"

CDC_FUNDING_AGENCY_NAME = "Department of Health and Human Services"
CDC_SUB_AGENCY_NAME = "Centers for Disease Control and Prevention"

FACT_TABLE = cdc_funding_table("fact_cdc_funding_prime_transaction")
STATE_AGGREGATE = cdc_funding_table("mv_cdc_funding_map_state_all_positive")
COUNTY_AGGREGATE = cdc_funding_table("mv_cdc_funding_map_county")

STATE_LOOKUP_CTE = """
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
                CASE WHEN fact.pop_county_fips ~ '^[0-9]{5}$' THEN LEFT(fact.pop_county_fips, 2) END,
                recipient_state_lookup.state_fips,
                CASE WHEN fact.recipient_county_fips ~ '^[0-9]{5}$' THEN LEFT(fact.recipient_county_fips, 2) END,
                map_state_lookup.state_fips,
                CASE WHEN fact.map_state_code ~ '^[0-9]{2}$' THEN fact.map_state_code END
            ) AS normalized_state_fips
        FROM __FACT_TABLE__ AS fact
        LEFT JOIN state_lookup AS pop_state_lookup
          ON pop_state_lookup.state_code = UPPER(NULLIF(BTRIM(fact.pop_state_code), ''))
        LEFT JOIN state_lookup AS recipient_state_lookup
          ON recipient_state_lookup.state_code = UPPER(NULLIF(BTRIM(fact.recipient_state_code), ''))
        LEFT JOIN state_lookup AS map_state_lookup
          ON map_state_lookup.state_code = UPPER(NULLIF(BTRIM(fact.map_state_code), ''))
    )
""".replace("__FACT_TABLE__", FACT_TABLE)

BASE_PARAMS = {
    "funding_mechanism": FUNDING_MECHANISM,
    "cdc_funding_agency": CDC_FUNDING_AGENCY_NAME,
    "cdc_sub_agency": CDC_SUB_AGENCY_NAME,
}

ASSISTANCE_FY_WHERE = """
    source_fiscal_year = :fiscal_year
    AND funding_mechanism = :funding_mechanism
"""

POSITIVE_ASSISTANCE_FY_WHERE = f"""
    {ASSISTANCE_FY_WHERE}
    AND is_positive_obligation IS TRUE
    AND federal_action_obligation > 0
"""

CDC_FUNDED_STRICT_SQL = """
    funding_agency_name = :cdc_funding_agency
    AND funding_sub_agency_name = :cdc_sub_agency
"""

CDC_AWARDED_SQL = "awarding_sub_agency_name = :cdc_sub_agency"

LIKELY_VFC_SQL = """
    (
        assistance_listing_number = '93.268'
        OR assistance_listing_title ILIKE '%immunization%'
        OR transaction_description ILIKE '%VFC%'
        OR transaction_description ILIKE '%Vaccines for Children%'
        OR prime_award_base_transaction_description ILIKE '%VFC%'
        OR prime_award_base_transaction_description ILIKE '%Vaccines for Children%'
    )
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconcile FY2023 CDC funding map totals against CDC Funding Profiles."
    )
    parser.add_argument("--fiscal-year", type=int, default=DEFAULT_FISCAL_YEAR)
    parser.add_argument("--funding-profile-target", type=Decimal, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
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


def rows(conn: sa.Connection, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text(sql), params).mappings().all()]


def one_row(conn: sa.Connection, sql: str, params: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute(text(sql), params).mappings().first()
    return dict(row) if row is not None else {}


def scalar(conn: sa.Connection, sql: str, params: dict[str, Any]) -> Any:
    return conn.execute(text(sql), params).scalar()


def table_exists(conn: sa.Connection, fq_table: str) -> bool:
    schema, table = fq_table.split(".", 1)
    return bool(
        scalar(
            conn,
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = :schema
                  AND table_name = :table
                UNION ALL
                SELECT 1
                FROM pg_matviews
                WHERE schemaname = :schema
                  AND matviewname = :table
            )
            """,
            {"schema": schema, "table": table},
        )
    )


def metric_query(where_sql: str) -> str:
    return f"""
        SELECT
            COALESCE(SUM(federal_action_obligation), 0) AS total_obligations,
            COUNT(*)::bigint AS transaction_count,
            COUNT(DISTINCT COALESCE(
                NULLIF(award_unique_key, ''),
                NULLIF(generated_unique_award_id, ''),
                NULLIF(award_id_piid, ''),
                source_raw_table || ':' || source_raw_id::text
            ))::bigint AS award_count,
            COUNT(DISTINCT COALESCE(NULLIF(recipient_uei, ''), NULLIF(recipient_name, '')))::bigint AS recipient_count
        FROM {FACT_TABLE}
        WHERE {where_sql}
    """


def normalized_metric_query(where_sql: str) -> str:
    return f"""
        {STATE_LOOKUP_CTE}
        SELECT
            COALESCE(SUM(federal_action_obligation), 0) AS total_obligations,
            COUNT(*)::bigint AS transaction_count,
            COUNT(DISTINCT COALESCE(
                NULLIF(award_unique_key, ''),
                NULLIF(generated_unique_award_id, ''),
                NULLIF(award_id_piid, ''),
                source_raw_table || ':' || source_raw_id::text
            ))::bigint AS award_count,
            COUNT(DISTINCT COALESCE(NULLIF(recipient_uei, ''), NULLIF(recipient_name, '')))::bigint AS recipient_count
        FROM normalized_fact
        WHERE {where_sql}
    """


def compare_to_target(total: Decimal, target: Decimal | None) -> dict[str, float] | None:
    if target is None:
        return None
    diff = total - target
    percent = (diff / target * Decimal("100")) if target != 0 else None
    return {
        "difference": float(diff),
        "percent_difference": float(percent) if percent is not None else None,
    }


def with_target_comparisons(
    metrics: dict[str, dict[str, Any]],
    target: Decimal | None,
) -> dict[str, dict[str, Any]]:
    if target is None:
        return metrics
    output: dict[str, dict[str, Any]] = {}
    for key, value in metrics.items():
        copied = dict(value)
        copied["funding_profile_target_comparison"] = compare_to_target(
            amount(copied.get("total_obligations")),
            target,
        )
        output[key] = copied
    return output


def collect_major_totals(conn: sa.Connection, fiscal_year: int) -> dict[str, dict[str, Any]]:
    params = {**BASE_PARAMS, "fiscal_year": fiscal_year}
    cdc_funded = f"{POSITIVE_ASSISTANCE_FY_WHERE} AND {CDC_FUNDED_STRICT_SQL}"
    cdc_awarded = f"{POSITIVE_ASSISTANCE_FY_WHERE} AND {CDC_AWARDED_SQL}"
    cdc_funded_non_supp = f"{cdc_funded} AND is_covid_or_emergency_supplemental IS FALSE"
    normalized_base = f"""
        source_fiscal_year = :fiscal_year
        AND funding_mechanism = :funding_mechanism
        AND is_positive_obligation IS TRUE
        AND federal_action_obligation > 0
        AND {CDC_FUNDED_STRICT_SQL}
        AND is_covid_or_emergency_supplemental IS FALSE
    """
    return {
        "all_assistance_prime_net": one_row(conn, metric_query(ASSISTANCE_FY_WHERE), params),
        "all_assistance_prime_positive": one_row(conn, metric_query(POSITIVE_ASSISTANCE_FY_WHERE), params),
        "positive_cdc_funded_strict": one_row(conn, metric_query(cdc_funded), params),
        "positive_cdc_awarded": one_row(conn, metric_query(cdc_awarded), params),
        "positive_cdc_funded_or_awarded": one_row(
            conn,
            metric_query(f"{POSITIVE_ASSISTANCE_FY_WHERE} AND (({CDC_FUNDED_STRICT_SQL}) OR ({CDC_AWARDED_SQL}))"),
            params,
        ),
        "positive_cdc_funded_and_awarded": one_row(
            conn,
            metric_query(f"{POSITIVE_ASSISTANCE_FY_WHERE} AND ({CDC_FUNDED_STRICT_SQL}) AND ({CDC_AWARDED_SQL})"),
            params,
        ),
        "positive_cdc_funded_strict_non_supplemental": one_row(
            conn,
            metric_query(cdc_funded_non_supp),
            params,
        ),
        "positive_cdc_funded_strict_supplemental_only": one_row(
            conn,
            metric_query(f"{cdc_funded} AND is_covid_or_emergency_supplemental IS TRUE"),
            params,
        ),
        "positive_cdc_funded_strict_non_supplemental_state_identifiable": one_row(
            conn,
            normalized_metric_query(f"{normalized_base} AND normalized_state_fips IS NOT NULL"),
            params,
        ),
        "positive_cdc_funded_strict_non_supplemental_state_unmapped": one_row(
            conn,
            normalized_metric_query(f"{normalized_base} AND normalized_state_fips IS NULL"),
            params,
        ),
        "positive_cdc_funded_strict_non_supplemental_non_vfc_state_identifiable": one_row(
            conn,
            normalized_metric_query(f"{normalized_base} AND NOT ({LIKELY_VFC_SQL}) AND normalized_state_fips IS NOT NULL"),
            params,
        ),
        "positive_cdc_funded_strict_non_supplemental_non_vfc_state_unmapped": one_row(
            conn,
            normalized_metric_query(f"{normalized_base} AND NOT ({LIKELY_VFC_SQL}) AND normalized_state_fips IS NULL"),
            params,
        ),
        "current_state_map_default_total": one_row(
            conn,
            f"""
            SELECT
                COALESCE(SUM(total_obligations), 0) AS total_obligations,
                COALESCE(SUM(transaction_count), 0)::bigint AS transaction_count,
                COALESCE(SUM(award_count), 0)::bigint AS award_count,
                COALESCE(SUM(recipient_count), 0)::bigint AS recipient_count
            FROM {STATE_AGGREGATE}
            WHERE source_fiscal_year = :fiscal_year
              AND funding_mechanism = :funding_mechanism
              AND is_covid_or_emergency_supplemental IS FALSE
            """,
            params,
        ),
        "current_county_default_map_eligible_total": one_row(
            conn,
            f"""
            SELECT
                COALESCE(SUM(total_obligations), 0) AS total_obligations,
                COALESCE(SUM(transaction_count), 0)::bigint AS transaction_count,
                COALESCE(SUM(award_count), 0)::bigint AS award_count,
                COALESCE(SUM(recipient_count), 0)::bigint AS recipient_count
            FROM {COUNTY_AGGREGATE}
            WHERE source_fiscal_year = :fiscal_year
              AND funding_mechanism = :funding_mechanism
              AND is_covid_or_emergency_supplemental IS FALSE
            """,
            params,
        )
        if table_exists(conn, COUNTY_AGGREGATE)
        else {"available": False},
    }


def collect_supplemental_diagnostics(conn: sa.Connection, fiscal_year: int) -> dict[str, Any]:
    params = {**BASE_PARAMS, "fiscal_year": fiscal_year}
    where_sql = f"{POSITIVE_ASSISTANCE_FY_WHERE} AND {CDC_FUNDED_STRICT_SQL}"
    return {
        "by_is_covid_or_emergency_supplemental": rows(
            conn,
            f"""
            SELECT
                is_covid_or_emergency_supplemental AS bucket,
                COALESCE(SUM(federal_action_obligation), 0) AS total_obligations,
                COUNT(*)::bigint AS transaction_count,
                COUNT(DISTINCT COALESCE(NULLIF(award_unique_key, ''), NULLIF(generated_unique_award_id, ''), NULLIF(award_id_piid, ''), source_raw_table || ':' || source_raw_id::text))::bigint AS award_count
            FROM {FACT_TABLE}
            WHERE {where_sql}
            GROUP BY is_covid_or_emergency_supplemental
            ORDER BY bucket
            """,
            params,
        ),
        "amount_flag_buckets": rows(
            conn,
            f"""
            SELECT 'covid_supplemental_obligated_amount_gt_0' AS bucket,
                   COALESCE(SUM(federal_action_obligation), 0) AS total_obligations,
                   COUNT(*)::bigint AS transaction_count
            FROM {FACT_TABLE}
            WHERE {where_sql} AND COALESCE(covid_supplemental_obligated_amount, 0) > 0
            UNION ALL
            SELECT 'iija_supplemental_obligated_amount_gt_0',
                   COALESCE(SUM(federal_action_obligation), 0),
                   COUNT(*)::bigint
            FROM {FACT_TABLE}
            WHERE {where_sql} AND COALESCE(iija_supplemental_obligated_amount, 0) > 0
            UNION ALL
            SELECT 'other_supplemental_obligated_amount_gt_0',
                   COALESCE(SUM(federal_action_obligation), 0),
                   COUNT(*)::bigint
            FROM {FACT_TABLE}
            WHERE {where_sql} AND COALESCE(other_supplemental_obligated_amount, 0) > 0
            """,
            params,
        ),
    }


def collect_vfc_diagnostics(conn: sa.Connection, fiscal_year: int) -> dict[str, Any]:
    params = {**BASE_PARAMS, "fiscal_year": fiscal_year}
    where_sql = f"{POSITIVE_ASSISTANCE_FY_WHERE} AND {CDC_FUNDED_STRICT_SQL} AND {LIKELY_VFC_SQL}"
    non_supp_where_sql = f"{where_sql} AND is_covid_or_emergency_supplemental IS FALSE"
    summary = one_row(conn, metric_query(where_sql), params)
    return {
        "summary": summary,
        "non_supplemental_summary": one_row(conn, metric_query(non_supp_where_sql), params),
        "top_20_records_by_obligation": rows(
            conn,
            f"""
            SELECT
                federal_action_obligation,
                recipient_name,
                assistance_listing_number,
                assistance_listing_title,
                funding_sub_agency_name,
                awarding_sub_agency_name,
                federal_accounts_funding_this_award,
                treasury_accounts_funding_this_award,
                transaction_description,
                prime_award_base_transaction_description,
                map_state_code,
                map_county_fips,
                map_geography_source,
                is_covid_or_emergency_supplemental,
                usaspending_permalink
            FROM {FACT_TABLE}
            WHERE {where_sql}
            ORDER BY federal_action_obligation DESC NULLS LAST
            LIMIT 20
            """,
            params,
        ),
        "top_assistance_listings": rows(
            conn,
            f"""
            SELECT
                assistance_listing_number,
                assistance_listing_title,
                COALESCE(SUM(federal_action_obligation), 0) AS total_obligations,
                COUNT(*)::bigint AS transaction_count,
                COUNT(DISTINCT COALESCE(NULLIF(award_unique_key, ''), NULLIF(generated_unique_award_id, ''), NULLIF(award_id_piid, ''), source_raw_table || ':' || source_raw_id::text))::bigint AS award_count,
                COUNT(DISTINCT COALESCE(NULLIF(recipient_uei, ''), NULLIF(recipient_name, '')))::bigint AS recipient_count
            FROM {FACT_TABLE}
            WHERE {where_sql}
            GROUP BY assistance_listing_number, assistance_listing_title
            ORDER BY total_obligations DESC NULLS LAST
            LIMIT 20
            """,
            params,
        ),
    }


def collect_agency_diagnostics(conn: sa.Connection, fiscal_year: int) -> dict[str, Any]:
    params = {**BASE_PARAMS, "fiscal_year": fiscal_year}
    where_sql = POSITIVE_ASSISTANCE_FY_WHERE
    return {
        "by_full_agency_tuple": rows(
            conn,
            f"""
            SELECT
                funding_agency_name,
                funding_sub_agency_name,
                awarding_agency_name,
                awarding_sub_agency_name,
                COALESCE(SUM(federal_action_obligation), 0) AS total_obligations,
                COUNT(*)::bigint AS transaction_count,
                COUNT(DISTINCT COALESCE(NULLIF(award_unique_key, ''), NULLIF(generated_unique_award_id, ''), NULLIF(award_id_piid, ''), source_raw_table || ':' || source_raw_id::text))::bigint AS award_count,
                COUNT(DISTINCT COALESCE(NULLIF(recipient_uei, ''), NULLIF(recipient_name, '')))::bigint AS recipient_count
            FROM {FACT_TABLE}
            WHERE {where_sql}
            GROUP BY funding_agency_name, funding_sub_agency_name, awarding_agency_name, awarding_sub_agency_name
            ORDER BY total_obligations DESC NULLS LAST
            LIMIT 100
            """,
            params,
        ),
        "cdc_awarded_not_cdc_funded": one_row(
            conn,
            metric_query(f"{where_sql} AND NOT ({CDC_FUNDED_STRICT_SQL}) AND ({CDC_AWARDED_SQL})"),
            params,
        ),
        "cdc_funded_not_cdc_awarded": one_row(
            conn,
            metric_query(f"{where_sql} AND ({CDC_FUNDED_STRICT_SQL}) AND NOT ({CDC_AWARDED_SQL})"),
            params,
        ),
    }


def collect_geography_diagnostics(conn: sa.Connection, fiscal_year: int) -> dict[str, Any]:
    params = {**BASE_PARAMS, "fiscal_year": fiscal_year}
    where_sql = f"""
        source_fiscal_year = :fiscal_year
        AND funding_mechanism = :funding_mechanism
        AND is_positive_obligation IS TRUE
        AND federal_action_obligation > 0
        AND {CDC_FUNDED_STRICT_SQL}
        AND is_covid_or_emergency_supplemental IS FALSE
    """
    return {
        "by_map_geography_source": rows(
            conn,
            f"""
            {STATE_LOOKUP_CTE}
            SELECT
                map_geography_source,
                (normalized_state_fips IS NOT NULL) AS state_identifiable,
                COALESCE(SUM(federal_action_obligation), 0) AS total_obligations,
                COUNT(*)::bigint AS transaction_count
            FROM normalized_fact
            WHERE {where_sql}
            GROUP BY map_geography_source, (normalized_state_fips IS NOT NULL)
            ORDER BY total_obligations DESC NULLS LAST
            """,
            params,
        ),
        "presence_buckets": rows(
            conn,
            f"""
            {STATE_LOOKUP_CTE}
            SELECT
                (normalized_state_fips IS NOT NULL) AS state_identifiable,
                (NULLIF(BTRIM(recipient_state_code), '') IS NOT NULL OR NULLIF(BTRIM(recipient_state_name), '') IS NOT NULL) AS has_recipient_state,
                (NULLIF(BTRIM(pop_state_code), '') IS NOT NULL OR NULLIF(BTRIM(pop_state_name), '') IS NOT NULL) AS has_place_of_performance_state,
                (NULLIF(BTRIM(pop_county_fips), '') IS NOT NULL) AS has_place_of_performance_county_fips,
                (NULLIF(BTRIM(recipient_county_fips), '') IS NOT NULL) AS has_recipient_county_fips,
                COALESCE(SUM(federal_action_obligation), 0) AS total_obligations,
                COUNT(*)::bigint AS transaction_count
            FROM normalized_fact
            WHERE {where_sql}
            GROUP BY
                (normalized_state_fips IS NOT NULL),
                (NULLIF(BTRIM(recipient_state_code), '') IS NOT NULL OR NULLIF(BTRIM(recipient_state_name), '') IS NOT NULL),
                (NULLIF(BTRIM(pop_state_code), '') IS NOT NULL OR NULLIF(BTRIM(pop_state_name), '') IS NOT NULL),
                (NULLIF(BTRIM(pop_county_fips), '') IS NOT NULL),
                (NULLIF(BTRIM(recipient_county_fips), '') IS NOT NULL)
            ORDER BY total_obligations DESC NULLS LAST
            """,
            params,
        ),
    }


def collect_account_diagnostics(conn: sa.Connection, fiscal_year: int) -> dict[str, Any]:
    params = {**BASE_PARAMS, "fiscal_year": fiscal_year}
    where_sql = f"{POSITIVE_ASSISTANCE_FY_WHERE} AND {CDC_FUNDED_STRICT_SQL} AND is_covid_or_emergency_supplemental IS FALSE"

    def grouped(column_sql: str, alias: str, limit: int = 30) -> list[dict[str, Any]]:
        return rows(
            conn,
            f"""
            SELECT
                {column_sql} AS {alias},
                COALESCE(SUM(federal_action_obligation), 0) AS total_obligations,
                COUNT(*)::bigint AS transaction_count,
                COUNT(DISTINCT COALESCE(NULLIF(award_unique_key, ''), NULLIF(generated_unique_award_id, ''), NULLIF(award_id_piid, ''), source_raw_table || ':' || source_raw_id::text))::bigint AS award_count,
                COUNT(DISTINCT COALESCE(NULLIF(recipient_uei, ''), NULLIF(recipient_name, '')))::bigint AS recipient_count
            FROM {FACT_TABLE}
            WHERE {where_sql}
            GROUP BY {column_sql}
            ORDER BY total_obligations DESC NULLS LAST
            LIMIT {limit}
            """,
            params,
        )

    return {
        "top_federal_accounts_funding_this_award": grouped(
            "COALESCE(NULLIF(BTRIM(federal_accounts_funding_this_award), ''), '(blank)')",
            "federal_accounts_funding_this_award",
        ),
        "top_treasury_accounts_funding_this_award": grouped(
            "COALESCE(NULLIF(BTRIM(treasury_accounts_funding_this_award), ''), '(blank)')",
            "treasury_accounts_funding_this_award",
        ),
        "top_assistance_listings": rows(
            conn,
            f"""
            SELECT
                assistance_listing_number,
                assistance_listing_title,
                COALESCE(SUM(federal_action_obligation), 0) AS total_obligations,
                COUNT(*)::bigint AS transaction_count,
                COUNT(DISTINCT COALESCE(NULLIF(award_unique_key, ''), NULLIF(generated_unique_award_id, ''), NULLIF(award_id_piid, ''), source_raw_table || ':' || source_raw_id::text))::bigint AS award_count,
                COUNT(DISTINCT COALESCE(NULLIF(recipient_uei, ''), NULLIF(recipient_name, '')))::bigint AS recipient_count
            FROM {FACT_TABLE}
            WHERE {where_sql}
            GROUP BY assistance_listing_number, assistance_listing_title
            ORDER BY total_obligations DESC NULLS LAST
            LIMIT 30
            """,
            params,
        ),
    }


def collect_top_records(conn: sa.Connection, fiscal_year: int) -> list[dict[str, Any]]:
    params = {**BASE_PARAMS, "fiscal_year": fiscal_year}
    where_sql = f"{POSITIVE_ASSISTANCE_FY_WHERE} AND {CDC_FUNDED_STRICT_SQL} AND is_covid_or_emergency_supplemental IS FALSE"
    return rows(
        conn,
        f"""
        {STATE_LOOKUP_CTE}
        SELECT
            federal_action_obligation,
            recipient_name,
            assistance_listing_number,
            assistance_listing_title,
            funding_sub_agency_name,
            awarding_sub_agency_name,
            federal_accounts_funding_this_award,
            treasury_accounts_funding_this_award,
            transaction_description,
            prime_award_base_transaction_description,
            map_state_code,
            normalized_state_fips AS map_state_fips,
            map_geography_source,
            is_covid_or_emergency_supplemental,
            usaspending_permalink
        FROM normalized_fact
        WHERE {where_sql}
        ORDER BY federal_action_obligation DESC NULLS LAST
        LIMIT 100
        """,
        params,
    )


def build_waterfall(
    major_totals: dict[str, dict[str, Any]],
    vfc_diagnostics: dict[str, Any],
) -> list[dict[str, Any]]:
    def total(key: str) -> Decimal:
        return amount(major_totals.get(key, {}).get("total_obligations"))

    all_net = total("all_assistance_prime_net")
    positive = total("all_assistance_prime_positive")
    cdc_funded = total("positive_cdc_funded_strict")
    non_supp = total("positive_cdc_funded_strict_non_supplemental")
    likely_vfc = amount(vfc_diagnostics["non_supplemental_summary"].get("total_obligations"))
    after_vfc = non_supp - likely_vfc
    state_identifiable_after_vfc = total("positive_cdc_funded_strict_non_supplemental_non_vfc_state_identifiable")
    final_mapped = total("current_state_map_default_total")
    steps = [
        ("all_fy_assistance_prime_net", all_net, None),
        ("positive_only", positive, positive - all_net),
        ("cdc_funded_strict", cdc_funded, cdc_funded - positive),
        ("non_supplemental", non_supp, non_supp - cdc_funded),
        ("remove_likely_vfc", after_vfc, -likely_vfc),
        ("state_identifiable_only_after_likely_vfc_removal", state_identifiable_after_vfc, state_identifiable_after_vfc - after_vfc),
        ("current_final_mapped_total_without_vfc_removal", final_mapped, final_mapped - state_identifiable_after_vfc),
    ]
    return [
        {
            "step": step,
            "total_obligations": total_value,
            "change_from_previous": change,
        }
        for step, total_value, change in steps
    ]


def infer_recommendations(report: dict[str, Any]) -> list[str]:
    recommendations: list[str] = []
    major = report["major_totals"]
    agency = report["agency_diagnostics"]
    vfc = report["vfc_diagnostics"]["summary"]
    supplemental = major["positive_cdc_funded_strict_supplemental_only"]
    state_unmapped = major["positive_cdc_funded_strict_non_supplemental_state_unmapped"]
    cdc_awarded_not_funded = agency["cdc_awarded_not_cdc_funded"]

    if amount(vfc.get("total_obligations")) > Decimal("0"):
        recommendations.append(
            "Investigate a VFC exclusion rule before changing ingestion; likely VFC records are material in the USAspending total."
        )
    if amount(supplemental.get("total_obligations")) > Decimal("0"):
        recommendations.append(
            "Keep supplemental exclusion explicit and verify whether CDC Funding Profiles excludes the same COVID, IIJA, and emergency supplemental obligations."
        )
    if amount(state_unmapped.get("total_obligations")) > Decimal("0"):
        recommendations.append(
            "Review state assignment for records with no normalized state before comparing map totals to profile totals."
        )
    if amount(cdc_awarded_not_funded.get("total_obligations")) > Decimal("100000000"):
        recommendations.append(
            "CDC-awarded but non-CDC-funded records are large enough to test as an alternate profile scope."
        )
    if not recommendations:
        recommendations.append(
            "No single diagnostic bucket dominated; compare the target to the waterfall and top account/listing tables before changing map scope."
        )
    return recommendations


def build_report(
    conn: sa.Connection,
    *,
    fiscal_year: int,
    output_path: Path,
    funding_profile_target: Decimal | None,
) -> dict[str, Any]:
    major_totals = collect_major_totals(conn, fiscal_year)
    major_totals = with_target_comparisons(major_totals, funding_profile_target)
    supplemental = collect_supplemental_diagnostics(conn, fiscal_year)
    vfc = collect_vfc_diagnostics(conn, fiscal_year)
    agency = collect_agency_diagnostics(conn, fiscal_year)
    geography = collect_geography_diagnostics(conn, fiscal_year)
    accounts = collect_account_diagnostics(conn, fiscal_year)
    top_records = collect_top_records(conn, fiscal_year)
    waterfall = build_waterfall(major_totals, vfc)

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc),
        "database_url": DATABASE_URL,
        "fiscal_year": fiscal_year,
        "funding_mechanism": FUNDING_MECHANISM,
        "amount_field": "federal_action_obligation",
        "output_path": output_path,
        "funding_profile_target": funding_profile_target,
        "scope_definitions": {
            "cdc_funded_strict": {
                "funding_agency_name": CDC_FUNDING_AGENCY_NAME,
                "funding_sub_agency_name": CDC_SUB_AGENCY_NAME,
            },
            "cdc_awarded": {
                "awarding_sub_agency_name": CDC_SUB_AGENCY_NAME,
            },
            "likely_vfc": [
                "assistance_listing_number = '93.268'",
                "assistance_listing_title ILIKE '%immunization%'",
                "transaction_description ILIKE '%VFC%'",
                "transaction_description ILIKE '%Vaccines for Children%'",
                "prime_award_base_transaction_description ILIKE '%VFC%'",
                "prime_award_base_transaction_description ILIKE '%Vaccines for Children%'",
            ],
        },
        "major_totals": major_totals,
        "supplemental_diagnostics": supplemental,
        "vfc_diagnostics": vfc,
        "agency_diagnostics": agency,
        "geography_diagnostics": geography,
        "federal_account_diagnostics": accounts,
        "top_100_positive_cdc_funded_non_supplemental_grant_transactions": top_records,
        "waterfall": waterfall,
    }
    report["recommended_next_checks"] = infer_recommendations(report)
    return report


def format_money(value: Any) -> str:
    value_decimal = amount(value)
    return f"${value_decimal:,.2f}"


def print_summary(report: dict[str, Any]) -> None:
    major = report["major_totals"]
    vfc = report["vfc_diagnostics"]["summary"]
    supplemental = major["positive_cdc_funded_strict_supplemental_only"]
    unmapped = major["positive_cdc_funded_strict_non_supplemental_state_unmapped"]
    awarded_not_funded = report["agency_diagnostics"]["cdc_awarded_not_cdc_funded"]

    print(f"FY{report['fiscal_year']} CDC funding reconciliation")
    print(f"Output: {report['output_path']}")
    print()
    print("Key totals")
    print(f"  Current state map total: {format_money(major['current_state_map_default_total']['total_obligations'])}")
    print(
        "  Positive CDC-funded non-supplemental grants before state mapping: "
        f"{format_money(major['positive_cdc_funded_strict_non_supplemental']['total_obligations'])}"
    )
    print(f"  State-unmapped amount: {format_money(unmapped['total_obligations'])}")
    print(f"  Likely VFC amount: {format_money(vfc['total_obligations'])}")
    print(f"  Supplemental amount removed: {format_money(supplemental['total_obligations'])}")
    print(f"  CDC-awarded but not CDC-funded: {format_money(awarded_not_funded['total_obligations'])}")
    print()
    print("Waterfall")
    for step in report["waterfall"]:
        change = step["change_from_previous"]
        change_text = "start" if change is None else f"{format_money(change)}"
        print(f"  {step['step']}: {format_money(step['total_obligations'])} ({change_text})")
    print()
    print("Top assistance listings")
    for row in report["federal_account_diagnostics"]["top_assistance_listings"][:8]:
        listing = row.get("assistance_listing_number") or "(blank)"
        title = row.get("assistance_listing_title") or ""
        print(f"  {listing} {title}: {format_money(row['total_obligations'])}")
    print()
    print("Top federal accounts")
    for row in report["federal_account_diagnostics"]["top_federal_accounts_funding_this_award"][:8]:
        account = row.get("federal_accounts_funding_this_award") or "(blank)"
        print(f"  {account}: {format_money(row['total_obligations'])}")
    print()
    print("Recommendations")
    for recommendation in report["recommended_next_checks"]:
        print(f"  - {recommendation}")


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
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(json_ready(report), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print_summary(json_ready(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
