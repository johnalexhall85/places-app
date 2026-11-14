from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db_fqtn import cdc_funding_table
from app.cdc_funding_api.schemas import CdcFundingScope


IMPORT_RUNS_TABLE = cdc_funding_table("cdc_funding_import_runs")
AWARDS_TABLE = cdc_funding_table("cdc_funding_awards")
ANNUAL_TABLE = cdc_funding_table("cdc_funding_account_annual")
MONTHLY_TABLE = cdc_funding_table("cdc_funding_account_monthly")
QUARTERLY_TABLE = cdc_funding_table("cdc_funding_account_quarterly")
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


def fetch_trend_quarter_coverage(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            text(
                f"""
                SELECT quarterly.fiscal_year, quarterly.fiscal_quarter
                  FROM {QUARTERLY_TABLE} AS quarterly
                 WHERE quarterly.fiscal_year >= :min_fiscal_year
                   AND EXISTS (
                       SELECT 1
                         FROM {IMPORT_RUNS_TABLE} AS run
                        WHERE run.fiscal_year = quarterly.fiscal_year
                          AND run.import_status = 'completed'
                   )
                 GROUP BY quarterly.fiscal_year, quarterly.fiscal_quarter
                 ORDER BY quarterly.fiscal_year,
                    CASE quarterly.fiscal_quarter
                        WHEN 'Q1' THEN 1 WHEN 'Q2' THEN 2
                        WHEN 'Q3' THEN 3 WHEN 'Q4' THEN 4
                        ELSE 99
                    END
                """
            ),
            {"min_fiscal_year": MIN_STANDALONE_FISCAL_YEAR},
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def fetch_trend_month_coverage(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            text(
                f"""
                SELECT
                    monthly.fiscal_year,
                    monthly.submission_period,
                    monthly.period_label,
                    monthly.fiscal_quarter
                  FROM {MONTHLY_TABLE} AS monthly
                 WHERE monthly.fiscal_year >= :min_fiscal_year
                   AND EXISTS (
                       SELECT 1
                         FROM {IMPORT_RUNS_TABLE} AS run
                        WHERE run.fiscal_year = monthly.fiscal_year
                          AND run.import_status = 'completed'
                   )
                 GROUP BY
                    monthly.fiscal_year,
                    monthly.submission_period,
                    monthly.period_label,
                    monthly.fiscal_quarter
                 ORDER BY monthly.fiscal_year, monthly.submission_period
                """
            ),
            {"min_fiscal_year": MIN_STANDALONE_FISCAL_YEAR},
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def _trend_filters(
    *,
    alias: str,
    federal_account_symbol: str | None,
    emergency_status: str,
    award_type: str,
) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if federal_account_symbol is not None:
        clauses.append(f"AND {alias}.federal_account_symbol = :federal_account_symbol")
        params["federal_account_symbol"] = federal_account_symbol
    if emergency_status != "all":
        clauses.append(f"AND {alias}.emergency = :emergency")
        params["emergency"] = "Emergency" if emergency_status == "emergency" else "NonEmergency"
    if award_type != "all":
        clauses.append(f"AND {alias}.grant_or_contract = :award_type")
        params["award_type"] = "Grant" if award_type == "grant" else "Contract"
    return "\n".join(clauses), params


def fetch_quarterly_trend_rows(
    db: Session,
    *,
    measure: str,
    federal_account_symbol: str | None,
    emergency_status: str,
    award_type: str,
) -> list[dict[str, Any]]:
    amount_column = (
        "transaction_obligated_amount"
        if measure == "obligations"
        else "gross_outlay_amount_fyb_to_period_end"
    )
    filters, params = _trend_filters(
        alias="quarterly",
        federal_account_symbol=federal_account_symbol,
        emergency_status=emergency_status,
        award_type=award_type,
    )
    params["min_fiscal_year"] = MIN_STANDALONE_FISCAL_YEAR
    rows = (
        db.execute(
            text(
                f"""
                SELECT
                    quarterly.fiscal_year,
                    quarterly.fiscal_quarter,
                    COUNT(*) AS matched_row_count,
                    COUNT(quarterly.{amount_column}) AS numeric_amount_rows,
                    SUM(quarterly.{amount_column}) AS amount
                  FROM {QUARTERLY_TABLE} AS quarterly
                 WHERE quarterly.fiscal_year >= :min_fiscal_year
                 {filters}
                 GROUP BY quarterly.fiscal_year, quarterly.fiscal_quarter
                 ORDER BY quarterly.fiscal_year,
                    CASE quarterly.fiscal_quarter
                        WHEN 'Q1' THEN 1 WHEN 'Q2' THEN 2
                        WHEN 'Q3' THEN 3 WHEN 'Q4' THEN 4
                        ELSE 99
                    END
                """
            ),
            params,
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def fetch_monthly_trend_rows(
    db: Session,
    *,
    measure: str,
    federal_account_symbol: str | None,
    emergency_status: str,
    award_type: str,
) -> list[dict[str, Any]]:
    amount_column = (
        "transaction_obligated_amount"
        if measure == "obligations"
        else "gross_outlay_amount_fyb_to_period_end"
    )
    filters, params = _trend_filters(
        alias="monthly",
        federal_account_symbol=federal_account_symbol,
        emergency_status=emergency_status,
        award_type=award_type,
    )
    params["min_fiscal_year"] = MIN_STANDALONE_FISCAL_YEAR
    rows = (
        db.execute(
            text(
                f"""
                SELECT
                    monthly.fiscal_year,
                    monthly.submission_period,
                    monthly.period_label,
                    monthly.fiscal_quarter,
                    COUNT(*) AS matched_row_count,
                    COUNT(monthly.{amount_column}) AS numeric_amount_rows,
                    SUM(monthly.{amount_column}) AS amount
                  FROM {MONTHLY_TABLE} AS monthly
                 WHERE monthly.fiscal_year >= :min_fiscal_year
                 {filters}
                 GROUP BY
                    monthly.fiscal_year,
                    monthly.submission_period,
                    monthly.period_label,
                    monthly.fiscal_quarter
                 ORDER BY monthly.fiscal_year, monthly.submission_period
                """
            ),
            params,
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def fetch_monthly_obligation_trend_rows(
    db: Session,
    *,
    federal_account_symbol: str | None,
    emergency_status: str,
    award_type: str,
) -> list[dict[str, Any]]:
    """Backward-compatible wrapper for obligation-only callers."""
    return fetch_monthly_trend_rows(
        db,
        measure="obligations",
        federal_account_symbol=federal_account_symbol,
        emergency_status=emergency_status,
        award_type=award_type,
    )


def fetch_positive_obligation_trend_rows(
    db: Session,
    *,
    period: str,
    federal_account_symbol: str | None,
    emergency_status: str,
    award_type: str,
) -> list[dict[str, Any]]:
    """Aggregate positive signed source records before period aggregation."""
    filters, params = _trend_filters(
        alias="award",
        federal_account_symbol=federal_account_symbol,
        emergency_status=emergency_status,
        award_type=award_type,
    )
    params["min_fiscal_year"] = MIN_STANDALONE_FISCAL_YEAR
    period_metadata = f"""
        SELECT DISTINCT
            fiscal_year,
            submission_period,
            period_label,
            fiscal_quarter
          FROM {MONTHLY_TABLE}
    """
    if period == "month":
        select_period = """
            award.submission_period,
            metadata.period_label,
            metadata.fiscal_quarter,
        """
        group_period = """
            award.submission_period,
            metadata.period_label,
            metadata.fiscal_quarter
        """
        order_period = "award.submission_period"
    else:
        select_period = "metadata.fiscal_quarter,"
        group_period = "metadata.fiscal_quarter"
        order_period = """
            CASE metadata.fiscal_quarter
                WHEN 'Q1' THEN 1 WHEN 'Q2' THEN 2
                WHEN 'Q3' THEN 3 WHEN 'Q4' THEN 4
                ELSE 99
            END
        """
    rows = (
        db.execute(
            text(
                f"""
                WITH period_metadata AS (
                    {period_metadata}
                )
                SELECT
                    award.fiscal_year,
                    {select_period}
                    COUNT(*) AS matched_row_count,
                    COUNT(award.transaction_obligated_amount) AS numeric_amount_rows,
                    SUM(
                        CASE
                            WHEN award.transaction_obligated_amount > 0
                            THEN award.transaction_obligated_amount
                            ELSE 0
                        END
                    ) AS amount
                  FROM {AWARDS_TABLE} AS award
                 JOIN period_metadata AS metadata
                    ON metadata.fiscal_year = award.fiscal_year
                   AND metadata.submission_period = award.submission_period
                 WHERE award.fiscal_year >= :min_fiscal_year
                   AND award.transaction_obligated_amount IS NOT NULL
                 {filters}
                 GROUP BY award.fiscal_year, {group_period}
                 ORDER BY award.fiscal_year, {order_period}
                """
            ),
            params,
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def fetch_positive_annual_obligation_trend_rows(
    db: Session,
    *,
    federal_account_symbol: str | None,
    emergency_status: str,
    award_type: str,
) -> list[dict[str, Any]]:
    filters, params = _trend_filters(
        alias="award",
        federal_account_symbol=federal_account_symbol,
        emergency_status=emergency_status,
        award_type=award_type,
    )
    params["min_fiscal_year"] = MIN_STANDALONE_FISCAL_YEAR
    rows = (
        db.execute(
            text(
                f"""
                SELECT
                    award.fiscal_year,
                    COUNT(*) AS matched_row_count,
                    COUNT(award.transaction_obligated_amount) AS numeric_amount_rows,
                    SUM(
                        CASE
                            WHEN award.transaction_obligated_amount > 0
                            THEN award.transaction_obligated_amount
                            ELSE 0
                        END
                    ) AS amount
                  FROM {AWARDS_TABLE} AS award
                 WHERE award.fiscal_year >= :min_fiscal_year
                   AND award.transaction_obligated_amount IS NOT NULL
                 {filters}
                 GROUP BY award.fiscal_year
                 ORDER BY award.fiscal_year
                """
            ),
            params,
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def fetch_annual_trend_rows(
    db: Session,
    *,
    measure: str,
    federal_account_symbol: str | None,
    emergency_status: str,
    award_type: str,
) -> list[dict[str, Any]]:
    amount_column = (
        "transaction_obligated_amount"
        if measure == "obligations"
        else "gross_outlay_amount_fyb_to_period_end"
    )
    filters, params = _trend_filters(
        alias="annual",
        federal_account_symbol=federal_account_symbol,
        emergency_status=emergency_status,
        award_type=award_type,
    )
    params["min_fiscal_year"] = MIN_STANDALONE_FISCAL_YEAR
    rows = (
        db.execute(
            text(
                f"""
                SELECT
                    annual.fiscal_year,
                    COUNT(*) AS matched_row_count,
                    COUNT(annual.{amount_column}) AS numeric_amount_rows,
                    SUM(annual.{amount_column}) AS amount
                  FROM {ANNUAL_TABLE} AS annual
                 WHERE annual.fiscal_year >= :min_fiscal_year
                 {filters}
                 GROUP BY annual.fiscal_year
                 ORDER BY annual.fiscal_year
                """
            ),
            params,
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def trend_account_exists(db: Session, federal_account_symbol: str) -> bool:
    return bool(
        db.execute(
            text(
                f"""
                SELECT 1
                  FROM {ANNUAL_TABLE}
                 WHERE fiscal_year >= :min_fiscal_year
                   AND federal_account_symbol = :federal_account_symbol
                   AND EXISTS (
                       SELECT 1
                         FROM {IMPORT_RUNS_TABLE} AS run
                        WHERE run.fiscal_year = {ANNUAL_TABLE}.fiscal_year
                          AND run.import_status = 'completed'
                   )
                 LIMIT 1
                """
            ),
            {
                "min_fiscal_year": MIN_STANDALONE_FISCAL_YEAR,
                "federal_account_symbol": federal_account_symbol,
            },
        ).first()
    )


def fetch_trend_account_options(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            text(
                f"""
                WITH symbols AS (
                    SELECT
                        federal_account_symbol,
                        MIN(fiscal_year) AS first_fiscal_year,
                        MAX(fiscal_year) AS last_fiscal_year
                      FROM {ANNUAL_TABLE}
                     WHERE fiscal_year >= :min_fiscal_year
                       AND NULLIF(BTRIM(federal_account_symbol), '') IS NOT NULL
                       AND EXISTS (
                           SELECT 1
                             FROM {IMPORT_RUNS_TABLE} AS run
                            WHERE run.fiscal_year = {ANNUAL_TABLE}.fiscal_year
                              AND run.import_status = 'completed'
                       )
                     GROUP BY federal_account_symbol
                ),
                latest_names AS (
                    SELECT DISTINCT ON (federal_account_symbol)
                        federal_account_symbol,
                        NULLIF(BTRIM(federal_account_name), '') AS federal_account_name
                      FROM {ANNUAL_TABLE}
                     WHERE fiscal_year >= :min_fiscal_year
                       AND NULLIF(BTRIM(federal_account_symbol), '') IS NOT NULL
                       AND NULLIF(BTRIM(federal_account_name), '') IS NOT NULL
                       AND EXISTS (
                           SELECT 1
                             FROM {IMPORT_RUNS_TABLE} AS run
                            WHERE run.fiscal_year = {ANNUAL_TABLE}.fiscal_year
                              AND run.import_status = 'completed'
                       )
                     ORDER BY federal_account_symbol, fiscal_year DESC, id DESC
                )
                SELECT
                    symbols.federal_account_symbol,
                    latest_names.federal_account_name,
                    symbols.first_fiscal_year,
                    symbols.last_fiscal_year
                  FROM symbols
                  LEFT JOIN latest_names USING (federal_account_symbol)
                 ORDER BY
                    COALESCE(latest_names.federal_account_name, symbols.federal_account_symbol),
                    symbols.federal_account_symbol
                """
            ),
            {"min_fiscal_year": MIN_STANDALONE_FISCAL_YEAR},
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
