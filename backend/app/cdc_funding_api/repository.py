from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db_fqtn import cdc_funding_table
from app.cdc_funding_api.schemas import CdcFundingScope


IMPORT_RUNS_TABLE = cdc_funding_table("cdc_funding_import_runs")
ANNUAL_TABLE = cdc_funding_table("cdc_funding_account_annual")
CATEGORY_MAPPING_TABLE = cdc_funding_table("cdc_funding_category_mapping")
MIN_STANDALONE_FISCAL_YEAR = 2021


def _mapped_scope_exists_sql(annual_alias: str = "annual") -> str:
    return f"""
                 AND EXISTS (
                    SELECT 1
                      FROM {CATEGORY_MAPPING_TABLE} AS mapping
                     WHERE mapping.fiscal_year = {annual_alias}.fiscal_year
                       AND mapping.federal_account_symbol = {annual_alias}.federal_account_symbol
                       AND mapping.grant_or_contract = {annual_alias}.grant_or_contract
                       AND mapping.emergency = {annual_alias}.emergency
                       AND mapping.mapping_status = 'Mapped'
                       AND NULLIF(BTRIM(mapping.federal_account_symbol), '') IS NOT NULL
                       AND NULLIF(BTRIM(mapping.grant_or_contract), '') IS NOT NULL
                       AND NULLIF(BTRIM(mapping.emergency), '') IS NOT NULL
                 )
    """


def _annual_scope_where(scope: CdcFundingScope, annual_alias: str = "annual") -> str:
    if scope == CdcFundingScope.cdc_funding_profiles:
        return _mapped_scope_exists_sql(annual_alias)
    return ""


def list_completed_fiscal_years(db: Session, scope: CdcFundingScope = CdcFundingScope.all_accounts) -> list[int]:
    scope_where = _annual_scope_where(scope, "annual")
    rows = (
        db.execute(
            text(
                f"""
                SELECT annual.fiscal_year
                  FROM {ANNUAL_TABLE} AS annual
                 WHERE EXISTS (
                    SELECT 1
                      FROM {IMPORT_RUNS_TABLE} AS run
                     WHERE run.fiscal_year = annual.fiscal_year
                       AND run.import_status = 'completed'
                 )
                   AND annual.fiscal_year >= :min_fiscal_year
                 {scope_where}
                 GROUP BY annual.fiscal_year
                 ORDER BY annual.fiscal_year DESC
                """
            ),
            {"min_fiscal_year": MIN_STANDALONE_FISCAL_YEAR},
        )
        .mappings()
        .all()
    )
    return [int(row["fiscal_year"]) for row in rows]


def fetch_overview_rows(
    db: Session,
    fiscal_year: int,
    scope: CdcFundingScope = CdcFundingScope.all_accounts,
) -> list[dict[str, Any]]:
    scope_where = _annual_scope_where(scope, "annual")
    rows = (
        db.execute(
            text(
                f"""
                SELECT
                    annual.grant_or_contract,
                    annual.emergency,
                    SUM(annual.transaction_obligated_amount) AS obligations
                  FROM {ANNUAL_TABLE} AS annual
                 WHERE annual.fiscal_year = :fiscal_year
                 {scope_where}
                 GROUP BY annual.grant_or_contract, annual.emergency
                """
            ),
            {"fiscal_year": fiscal_year},
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def fetch_account_name_conflicts(
    db: Session,
    fiscal_year: int,
    scope: CdcFundingScope = CdcFundingScope.all_accounts,
) -> list[dict[str, Any]]:
    scope_where = _annual_scope_where(scope, "annual")
    rows = (
        db.execute(
            text(
                f"""
                SELECT
                    annual.federal_account_symbol,
                    ARRAY_AGG(DISTINCT NULLIF(BTRIM(annual.federal_account_name), '')) FILTER (
                        WHERE NULLIF(BTRIM(annual.federal_account_name), '') IS NOT NULL
                    ) AS account_names
                  FROM {ANNUAL_TABLE} AS annual
                 WHERE annual.fiscal_year = :fiscal_year
                 {scope_where}
                 GROUP BY annual.federal_account_symbol
                HAVING COUNT(DISTINCT NULLIF(BTRIM(annual.federal_account_name), '')) > 1
                """
            ),
            {"fiscal_year": fiscal_year},
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def fetch_account_rows(
    db: Session,
    fiscal_year: int,
    scope: CdcFundingScope = CdcFundingScope.all_accounts,
) -> list[dict[str, Any]]:
    scope_where = _annual_scope_where(scope, "annual")
    rows = (
        db.execute(
            text(
                f"""
                SELECT
                    annual.federal_account_symbol,
                    MAX(NULLIF(BTRIM(annual.federal_account_name), '')) AS federal_account_name,
                    SUM(annual.transaction_obligated_amount) AS total_obligations,
                    SUM(CASE
                        WHEN annual.emergency = 'Emergency'
                        THEN annual.transaction_obligated_amount
                        ELSE 0
                    END) AS emergency_obligations,
                    SUM(CASE
                        WHEN annual.emergency = 'NonEmergency'
                        THEN annual.transaction_obligated_amount
                        ELSE 0
                    END) AS nonemergency_obligations,
                    SUM(CASE
                        WHEN annual.emergency = 'Emergency' AND annual.grant_or_contract = 'Grant'
                        THEN annual.transaction_obligated_amount
                        ELSE 0
                    END) AS emergency_grants,
                    SUM(CASE
                        WHEN annual.emergency = 'Emergency' AND annual.grant_or_contract = 'Contract'
                        THEN annual.transaction_obligated_amount
                        ELSE 0
                    END) AS emergency_contracts,
                    SUM(CASE
                        WHEN annual.emergency = 'NonEmergency' AND annual.grant_or_contract = 'Grant'
                        THEN annual.transaction_obligated_amount
                        ELSE 0
                    END) AS nonemergency_grants,
                    SUM(CASE
                        WHEN annual.emergency = 'NonEmergency' AND annual.grant_or_contract = 'Contract'
                        THEN annual.transaction_obligated_amount
                        ELSE 0
                    END) AS nonemergency_contracts
                  FROM {ANNUAL_TABLE} AS annual
                 WHERE annual.fiscal_year = :fiscal_year
                 {scope_where}
                 GROUP BY annual.federal_account_symbol
                 ORDER BY
                    SUM(annual.transaction_obligated_amount) DESC,
                    MAX(NULLIF(BTRIM(annual.federal_account_name), '')) ASC NULLS LAST,
                    annual.federal_account_symbol ASC
                """
            ),
            {"fiscal_year": fiscal_year},
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def fetch_category_mapping_conflicts(db: Session, fiscal_year: int) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            text(
                f"""
                SELECT
                    mapping.fiscal_year,
                    mapping.federal_account_symbol,
                    mapping.grant_or_contract,
                    mapping.emergency,
                    ARRAY_AGG(DISTINCT mapping.category ORDER BY mapping.category) AS categories
                  FROM {CATEGORY_MAPPING_TABLE} AS mapping
                 WHERE mapping.fiscal_year = :fiscal_year
                   AND mapping.mapping_status = 'Mapped'
                   AND NULLIF(BTRIM(mapping.federal_account_symbol), '') IS NOT NULL
                   AND NULLIF(BTRIM(mapping.grant_or_contract), '') IS NOT NULL
                   AND NULLIF(BTRIM(mapping.emergency), '') IS NOT NULL
                   AND NULLIF(BTRIM(mapping.category), '') IS NOT NULL
                 GROUP BY
                    mapping.fiscal_year,
                    mapping.federal_account_symbol,
                    mapping.grant_or_contract,
                    mapping.emergency
                HAVING COUNT(DISTINCT mapping.category) > 1
                """
            ),
            {"fiscal_year": fiscal_year},
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def fetch_blank_category_mappings(db: Session, fiscal_year: int) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            text(
                f"""
                SELECT
                    mapping.fiscal_year,
                    mapping.federal_account_symbol,
                    mapping.grant_or_contract,
                    mapping.emergency
                  FROM {CATEGORY_MAPPING_TABLE} AS mapping
                 WHERE mapping.fiscal_year = :fiscal_year
                   AND mapping.mapping_status = 'Mapped'
                   AND NULLIF(BTRIM(mapping.federal_account_symbol), '') IS NOT NULL
                   AND NULLIF(BTRIM(mapping.grant_or_contract), '') IS NOT NULL
                   AND NULLIF(BTRIM(mapping.emergency), '') IS NOT NULL
                   AND NULLIF(BTRIM(mapping.category), '') IS NULL
                 GROUP BY
                    mapping.fiscal_year,
                    mapping.federal_account_symbol,
                    mapping.grant_or_contract,
                    mapping.emergency
                """
            ),
            {"fiscal_year": fiscal_year},
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def fetch_category_rows(db: Session, fiscal_year: int) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            text(
                f"""
                WITH mapped_keys AS (
                    SELECT DISTINCT
                        mapping.fiscal_year,
                        mapping.federal_account_symbol,
                        mapping.grant_or_contract,
                        mapping.emergency,
                        mapping.category
                      FROM {CATEGORY_MAPPING_TABLE} AS mapping
                     WHERE mapping.mapping_status = 'Mapped'
                       AND NULLIF(BTRIM(mapping.federal_account_symbol), '') IS NOT NULL
                       AND NULLIF(BTRIM(mapping.grant_or_contract), '') IS NOT NULL
                       AND NULLIF(BTRIM(mapping.emergency), '') IS NOT NULL
                       AND NULLIF(BTRIM(mapping.category), '') IS NOT NULL
                )
                SELECT
                    annual.fiscal_year,
                    mapped_keys.category,
                    COUNT(*) AS mapped_account_combination_count,
                    SUM(CASE
                        WHEN annual.emergency = 'Emergency'
                        THEN annual.transaction_obligated_amount
                        ELSE 0
                    END) AS emergency_obligations,
                    SUM(CASE
                        WHEN annual.emergency = 'NonEmergency'
                        THEN annual.transaction_obligated_amount
                        ELSE 0
                    END) AS nonemergency_obligations,
                    SUM(CASE
                        WHEN annual.grant_or_contract = 'Grant'
                        THEN annual.transaction_obligated_amount
                        ELSE 0
                    END) AS grant_obligations,
                    SUM(CASE
                        WHEN annual.grant_or_contract = 'Contract'
                        THEN annual.transaction_obligated_amount
                        ELSE 0
                    END) AS contract_obligations,
                    SUM(CASE
                        WHEN annual.emergency = 'Emergency' AND annual.grant_or_contract = 'Grant'
                        THEN annual.transaction_obligated_amount
                        ELSE 0
                    END) AS emergency_grants,
                    SUM(CASE
                        WHEN annual.emergency = 'Emergency' AND annual.grant_or_contract = 'Contract'
                        THEN annual.transaction_obligated_amount
                        ELSE 0
                    END) AS emergency_contracts,
                    SUM(CASE
                        WHEN annual.emergency = 'NonEmergency' AND annual.grant_or_contract = 'Grant'
                        THEN annual.transaction_obligated_amount
                        ELSE 0
                    END) AS nonemergency_grants,
                    SUM(CASE
                        WHEN annual.emergency = 'NonEmergency' AND annual.grant_or_contract = 'Contract'
                        THEN annual.transaction_obligated_amount
                        ELSE 0
                    END) AS nonemergency_contracts,
                    SUM(annual.transaction_obligated_amount) AS total_obligations
                  FROM {ANNUAL_TABLE} AS annual
                  JOIN mapped_keys
                    ON mapped_keys.fiscal_year = annual.fiscal_year
                   AND mapped_keys.federal_account_symbol = annual.federal_account_symbol
                   AND mapped_keys.grant_or_contract = annual.grant_or_contract
                   AND mapped_keys.emergency = annual.emergency
                 WHERE annual.fiscal_year = :fiscal_year
                 GROUP BY annual.fiscal_year, mapped_keys.category
                 ORDER BY
                    SUM(annual.transaction_obligated_amount) DESC,
                    mapped_keys.category ASC
                """
            ),
            {"fiscal_year": fiscal_year},
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]
