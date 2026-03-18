"""expand verified funding scope categories

Revision ID: 9b5f1d7c3a44
Revises: 7f4c6d8e2b19
Create Date: 2026-03-16 15:05:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9b5f1d7c3a44"
down_revision: Union[str, None] = "7f4c6d8e2b19"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RECON_SCHEMA = "recon"
TAGGS_SCHEMA = "taggs"

SCOPE_BASES = (
    ("core_public_health", "core_public_health"),
    ("emergency_public_health", "emergency_public_health"),
    ("federal_health_transfer", "federal_health_transfer"),
    ("procurement_support", "procurement_support_scope"),
    ("special_transfer", "special_transfer"),
)
EXPANDED_SCOPE_BASES = (
    ("other_public_health", "other_public_health"),
    ("biomedical_research", "biomedical_research"),
    ("international_health_assistance", "international_health_assistance"),
)
UNKNOWN_SCOPE_BASE = ("unknown", "unknown_funding_scope")


def _drop_support_views() -> None:
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.profile_calibration_taggs_state_year_support")
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.profile_calibration_usaspending_state_year_support")


def _scope_defs(include_expanded: bool) -> list[tuple[str, str]]:
    scope_defs = list(SCOPE_BASES)
    if include_expanded:
        scope_defs.extend(EXPANDED_SCOPE_BASES)
    scope_defs.append(UNKNOWN_SCOPE_BASE)
    return scope_defs


def _usaspending_scope_sql(include_expanded: bool) -> str:
    parts: list[str] = []
    for scope_name, alias_base in _scope_defs(include_expanded):
        parts.extend(
            [
                (
                    "COALESCE(SUM(CASE WHEN effective_funding_scope = "
                    f"'{scope_name}' AND include_in_profile_scope IS TRUE "
                    "THEN normalized_profile_scope_amount ELSE 0 END), 0)::numeric(18, 2) "
                    f"AS {alias_base}_amount"
                ),
                (
                    "COALESCE(SUM(CASE WHEN effective_funding_scope = "
                    f"'{scope_name}' AND include_in_profile_scope IS FALSE "
                    "THEN raw_amount ELSE 0 END), 0)::numeric(18, 2) "
                    f"AS {alias_base}_excluded_amount"
                ),
                (
                    "COALESCE(SUM(CASE WHEN effective_funding_scope = "
                    f"'{scope_name}' AND include_in_profile_scope IS NULL "
                    "THEN raw_amount ELSE 0 END), 0)::numeric(18, 2) "
                    f"AS {alias_base}_uncertain_amount"
                ),
            ]
        )
    return ",\n            ".join(parts)


def _taggs_scope_sql(include_expanded: bool) -> str:
    parts = [
        "COALESCE(SUM(CASE WHEN funding_stream = 'regular_appropriation' AND include_in_cdc_profile_scope IS TRUE THEN COALESCE(raw_amount, 0) * COALESCE(inclusion_weight, 0) ELSE 0 END), 0)::numeric(18, 2) AS core_public_health_amount",
        "COALESCE(SUM(CASE WHEN funding_stream = 'regular_appropriation' AND include_in_cdc_profile_scope IS FALSE THEN COALESCE(raw_amount, 0) ELSE 0 END), 0)::numeric(18, 2) AS core_public_health_excluded_amount",
        "0::numeric(18, 2) AS core_public_health_uncertain_amount",
        "COALESCE(SUM(CASE WHEN funding_stream IN ('covid_emergency', 'arpa', 'other_emergency_or_disaster') AND include_in_cdc_profile_scope IS TRUE THEN COALESCE(raw_amount, 0) * COALESCE(inclusion_weight, 0) ELSE 0 END), 0)::numeric(18, 2) AS emergency_public_health_amount",
        "COALESCE(SUM(CASE WHEN funding_stream IN ('covid_emergency', 'arpa', 'other_emergency_or_disaster') AND include_in_cdc_profile_scope IS FALSE THEN COALESCE(raw_amount, 0) ELSE 0 END), 0)::numeric(18, 2) AS emergency_public_health_excluded_amount",
        "0::numeric(18, 2) AS emergency_public_health_uncertain_amount",
        "0::numeric(18, 2) AS federal_health_transfer_amount",
        "0::numeric(18, 2) AS federal_health_transfer_excluded_amount",
        "0::numeric(18, 2) AS federal_health_transfer_uncertain_amount",
        "COALESCE(SUM(CASE WHEN funding_stream = 'procurement_support' AND include_in_cdc_profile_scope IS TRUE THEN COALESCE(raw_amount, 0) * COALESCE(inclusion_weight, 0) ELSE 0 END), 0)::numeric(18, 2) AS procurement_support_scope_amount",
        "COALESCE(SUM(CASE WHEN funding_stream = 'procurement_support' AND include_in_cdc_profile_scope IS FALSE THEN COALESCE(raw_amount, 0) ELSE 0 END), 0)::numeric(18, 2) AS procurement_support_scope_excluded_amount",
        "0::numeric(18, 2) AS procurement_support_scope_uncertain_amount",
        "COALESCE(SUM(CASE WHEN funding_stream = 'transfer_or_special' AND include_in_cdc_profile_scope IS TRUE THEN COALESCE(raw_amount, 0) * COALESCE(inclusion_weight, 0) ELSE 0 END), 0)::numeric(18, 2) AS special_transfer_amount",
        "COALESCE(SUM(CASE WHEN funding_stream = 'transfer_or_special' AND include_in_cdc_profile_scope IS FALSE THEN COALESCE(raw_amount, 0) ELSE 0 END), 0)::numeric(18, 2) AS special_transfer_excluded_amount",
        "0::numeric(18, 2) AS special_transfer_uncertain_amount",
    ]
    if include_expanded:
        for _scope_name, alias_base in EXPANDED_SCOPE_BASES:
            parts.extend(
                [
                    f"0::numeric(18, 2) AS {alias_base}_amount",
                    f"0::numeric(18, 2) AS {alias_base}_excluded_amount",
                    f"0::numeric(18, 2) AS {alias_base}_uncertain_amount",
                ]
            )
    parts.extend(
        [
            "COALESCE(SUM(CASE WHEN funding_stream = 'unknown' AND include_in_cdc_profile_scope IS TRUE THEN COALESCE(raw_amount, 0) * COALESCE(inclusion_weight, 0) ELSE 0 END), 0)::numeric(18, 2) AS unknown_funding_scope_amount",
            "COALESCE(SUM(CASE WHEN funding_stream = 'unknown' AND include_in_cdc_profile_scope IS FALSE THEN COALESCE(raw_amount, 0) ELSE 0 END), 0)::numeric(18, 2) AS unknown_funding_scope_excluded_amount",
            "0::numeric(18, 2) AS unknown_funding_scope_uncertain_amount",
        ]
    )
    return ",\n                ".join(parts)


def _scope_projection_sql(prefix: str, include_expanded: bool) -> str:
    projection_parts: list[str] = []
    for _scope_name, alias_base in _scope_defs(include_expanded):
        projection_parts.extend(
            [
                f"{prefix}.{alias_base}_amount",
                f"{prefix}.{alias_base}_excluded_amount",
                f"{prefix}.{alias_base}_uncertain_amount",
            ]
        )
    return ",\n            ".join(projection_parts)


def _create_support_views(*, include_expanded: bool) -> None:
    usaspending_scope_sql = _usaspending_scope_sql(include_expanded)
    taggs_scope_sql = _taggs_scope_sql(include_expanded)
    normalized_scope_projection = _scope_projection_sql("normalized_rollup", include_expanded)

    op.execute(
        f"""
        CREATE VIEW {RECON_SCHEMA}.profile_calibration_usaspending_state_year_support AS
        SELECT
            'usaspending'::text AS source_system,
            fiscal_year,
            state_code,
            COALESCE(SUM(raw_amount), 0)::numeric(18, 2) AS raw_reconstructed_amount,
            COALESCE(SUM(normalized_profile_scope_amount), 0)::numeric(18, 2) AS reconstructed_profile_scope_amount,
            COALESCE(SUM(CASE WHEN effective_funding_stream = 'regular_appropriation' THEN normalized_profile_scope_amount ELSE 0 END), 0)::numeric(18, 2) AS regular_appropriation_amount,
            COALESCE(SUM(CASE WHEN effective_funding_stream = 'covid_emergency' THEN normalized_profile_scope_amount ELSE 0 END), 0)::numeric(18, 2) AS covid_emergency_amount,
            COALESCE(SUM(CASE WHEN effective_funding_stream = 'arpa' THEN normalized_profile_scope_amount ELSE 0 END), 0)::numeric(18, 2) AS arpa_amount,
            COALESCE(SUM(CASE WHEN effective_funding_stream = 'other_emergency_or_disaster' THEN normalized_profile_scope_amount ELSE 0 END), 0)::numeric(18, 2) AS other_emergency_or_disaster_amount,
            COALESCE(SUM(CASE WHEN effective_funding_stream = 'non_covid_supplemental' THEN normalized_profile_scope_amount ELSE 0 END), 0)::numeric(18, 2) AS non_covid_supplemental_amount,
            COALESCE(SUM(CASE WHEN effective_funding_stream = 'transfer_or_special' THEN normalized_profile_scope_amount ELSE 0 END), 0)::numeric(18, 2) AS transfer_or_special_amount,
            COALESCE(SUM(CASE WHEN effective_funding_stream = 'procurement_support' THEN normalized_profile_scope_amount ELSE 0 END), 0)::numeric(18, 2) AS procurement_support_amount,
            COALESCE(SUM(CASE WHEN effective_funding_stream = 'unknown' THEN raw_amount ELSE 0 END), 0)::numeric(18, 2) AS unknown_stream_amount,
            COALESCE(SUM(CASE WHEN effective_funding_stream = 'unknown' AND include_in_profile_scope IS TRUE THEN normalized_profile_scope_amount ELSE 0 END), 0)::numeric(18, 2) AS unknown_stream_included_amount,
            COALESCE(SUM(CASE WHEN effective_funding_stream = 'unknown' AND include_in_profile_scope IS FALSE THEN raw_amount ELSE 0 END), 0)::numeric(18, 2) AS unknown_stream_excluded_amount,
            COALESCE(SUM(CASE WHEN effective_funding_stream = 'unknown' AND include_in_profile_scope IS NULL THEN raw_amount ELSE 0 END), 0)::numeric(18, 2) AS unknown_stream_uncertain_amount,
            {usaspending_scope_sql},
            COUNT(*)::integer AS transaction_count,
            COUNT(*) FILTER (WHERE include_in_profile_scope IS TRUE)::integer AS included_transaction_count,
            COUNT(*) FILTER (WHERE include_in_profile_scope IS FALSE)::integer AS excluded_transaction_count,
            COUNT(*) FILTER (WHERE include_in_profile_scope IS NULL)::integer AS uncertain_transaction_count,
            COALESCE(SUM(CASE WHEN include_in_profile_scope IS NULL THEN raw_amount ELSE 0 END), 0)::numeric(18, 2) AS uncertain_amount,
            COALESCE(SUM(CASE WHEN include_in_profile_scope IS FALSE AND likely_domestic IS FALSE THEN raw_amount ELSE 0 END), 0)::numeric(18, 2) AS excluded_non_domestic_amount,
            COALESCE(SUM(CASE WHEN is_contract AND include_in_profile_scope IS FALSE THEN raw_amount ELSE 0 END), 0)::numeric(18, 2) AS excluded_contract_amount,
            MAX(methodology_version) AS methodology_version,
            MAX(refreshed_at) AS refreshed_at
        FROM {RECON_SCHEMA}.profile_scope_transaction_diagnostics
        GROUP BY fiscal_year, state_code
        """
    )

    op.execute(
        f"""
        CREATE VIEW {RECON_SCHEMA}.profile_calibration_taggs_state_year_support AS
        WITH raw_rollup AS (
            SELECT
                funding_fiscal_year AS fiscal_year,
                UPPER(BTRIM(legal_entity_state_normalized)) AS state_code,
                COALESCE(SUM(total_sum_of_actions), 0)::numeric(18, 2) AS raw_reconstructed_amount,
                COUNT(*)::integer AS transaction_count,
                COALESCE(SUM(CASE WHEN is_domestic_scope IS FALSE THEN total_sum_of_actions ELSE 0 END), 0)::numeric(18, 2) AS excluded_non_domestic_amount
            FROM {TAGGS_SCHEMA}.state_funding_summary
            WHERE funding_fiscal_year IS NOT NULL
              AND NULLIF(BTRIM(legal_entity_state_normalized), '') IS NOT NULL
            GROUP BY funding_fiscal_year, UPPER(BTRIM(legal_entity_state_normalized))
        ),
        normalized_rollup AS (
            SELECT
                fiscal_year,
                UPPER(BTRIM(state_code)) AS state_code,
                COALESCE(SUM(COALESCE(raw_amount, 0) * COALESCE(inclusion_weight, 0)), 0)::numeric(18, 2) AS reconstructed_profile_scope_amount,
                COALESCE(SUM(CASE WHEN funding_stream = 'regular_appropriation' THEN COALESCE(raw_amount, 0) * COALESCE(inclusion_weight, 0) ELSE 0 END), 0)::numeric(18, 2) AS regular_appropriation_amount,
                COALESCE(SUM(CASE WHEN funding_stream = 'covid_emergency' THEN COALESCE(raw_amount, 0) * COALESCE(inclusion_weight, 0) ELSE 0 END), 0)::numeric(18, 2) AS covid_emergency_amount,
                COALESCE(SUM(CASE WHEN funding_stream = 'arpa' THEN COALESCE(raw_amount, 0) * COALESCE(inclusion_weight, 0) ELSE 0 END), 0)::numeric(18, 2) AS arpa_amount,
                COALESCE(SUM(CASE WHEN funding_stream = 'other_emergency_or_disaster' THEN COALESCE(raw_amount, 0) * COALESCE(inclusion_weight, 0) ELSE 0 END), 0)::numeric(18, 2) AS other_emergency_or_disaster_amount,
                COALESCE(SUM(CASE WHEN funding_stream = 'non_covid_supplemental' THEN COALESCE(raw_amount, 0) * COALESCE(inclusion_weight, 0) ELSE 0 END), 0)::numeric(18, 2) AS non_covid_supplemental_amount,
                COALESCE(SUM(CASE WHEN funding_stream = 'transfer_or_special' THEN COALESCE(raw_amount, 0) * COALESCE(inclusion_weight, 0) ELSE 0 END), 0)::numeric(18, 2) AS transfer_or_special_amount,
                COALESCE(SUM(CASE WHEN funding_stream = 'procurement_support' THEN COALESCE(raw_amount, 0) * COALESCE(inclusion_weight, 0) ELSE 0 END), 0)::numeric(18, 2) AS procurement_support_amount,
                COALESCE(SUM(CASE WHEN funding_stream = 'unknown' THEN COALESCE(raw_amount, 0) ELSE 0 END), 0)::numeric(18, 2) AS unknown_stream_amount,
                COALESCE(SUM(CASE WHEN funding_stream = 'unknown' AND include_in_cdc_profile_scope IS TRUE THEN COALESCE(raw_amount, 0) * COALESCE(inclusion_weight, 0) ELSE 0 END), 0)::numeric(18, 2) AS unknown_stream_included_amount,
                COALESCE(SUM(CASE WHEN funding_stream = 'unknown' AND include_in_cdc_profile_scope IS FALSE THEN COALESCE(raw_amount, 0) ELSE 0 END), 0)::numeric(18, 2) AS unknown_stream_excluded_amount,
                0::numeric(18, 2) AS unknown_stream_uncertain_amount,
                {taggs_scope_sql},
                COUNT(*) FILTER (WHERE include_in_cdc_profile_scope IS TRUE)::integer AS included_transaction_count,
                COUNT(*) FILTER (WHERE include_in_cdc_profile_scope IS FALSE)::integer AS excluded_transaction_count,
                0::integer AS uncertain_transaction_count,
                0::numeric(18, 2) AS uncertain_amount,
                MAX(methodology_version) AS methodology_version,
                MAX(updated_at) AS refreshed_at
            FROM {RECON_SCHEMA}.taggs_funding_streams
            WHERE fiscal_year IS NOT NULL
              AND NULLIF(BTRIM(state_code), '') IS NOT NULL
            GROUP BY fiscal_year, UPPER(BTRIM(state_code))
        )
        SELECT
            'taggs'::text AS source_system,
            COALESCE(raw_rollup.fiscal_year, normalized_rollup.fiscal_year) AS fiscal_year,
            COALESCE(raw_rollup.state_code, normalized_rollup.state_code) AS state_code,
            raw_rollup.raw_reconstructed_amount,
            normalized_rollup.reconstructed_profile_scope_amount,
            normalized_rollup.regular_appropriation_amount,
            normalized_rollup.covid_emergency_amount,
            normalized_rollup.arpa_amount,
            normalized_rollup.other_emergency_or_disaster_amount,
            normalized_rollup.non_covid_supplemental_amount,
            normalized_rollup.transfer_or_special_amount,
            normalized_rollup.procurement_support_amount,
            normalized_rollup.unknown_stream_amount,
            normalized_rollup.unknown_stream_included_amount,
            normalized_rollup.unknown_stream_excluded_amount,
            normalized_rollup.unknown_stream_uncertain_amount,
            {normalized_scope_projection},
            COALESCE(raw_rollup.transaction_count, 0) AS transaction_count,
            COALESCE(normalized_rollup.included_transaction_count, 0) AS included_transaction_count,
            COALESCE(normalized_rollup.excluded_transaction_count, 0) AS excluded_transaction_count,
            COALESCE(normalized_rollup.uncertain_transaction_count, 0) AS uncertain_transaction_count,
            COALESCE(normalized_rollup.uncertain_amount, 0)::numeric(18, 2) AS uncertain_amount,
            COALESCE(raw_rollup.excluded_non_domestic_amount, 0)::numeric(18, 2) AS excluded_non_domestic_amount,
            0::numeric(18, 2) AS excluded_contract_amount,
            normalized_rollup.methodology_version,
            COALESCE(normalized_rollup.refreshed_at, now()) AS refreshed_at
        FROM raw_rollup
        FULL OUTER JOIN normalized_rollup
          ON raw_rollup.fiscal_year = normalized_rollup.fiscal_year
         AND raw_rollup.state_code = normalized_rollup.state_code
        """
    )


def upgrade() -> None:
    op.add_column("federal_account_lookup", sa.Column("likely_other_public_health", sa.Boolean(), nullable=True), schema=RECON_SCHEMA)
    op.add_column("federal_account_lookup", sa.Column("likely_biomedical_research", sa.Boolean(), nullable=True), schema=RECON_SCHEMA)
    op.add_column("federal_account_lookup", sa.Column("likely_international_health_assistance", sa.Boolean(), nullable=True), schema=RECON_SCHEMA)

    op.add_column("assistance_transaction_account_summary", sa.Column("has_other_public_health_account", sa.Boolean(), nullable=False, server_default=sa.text("false")), schema=RECON_SCHEMA)
    op.add_column("assistance_transaction_account_summary", sa.Column("has_biomedical_research_account", sa.Boolean(), nullable=False, server_default=sa.text("false")), schema=RECON_SCHEMA)
    op.add_column("assistance_transaction_account_summary", sa.Column("has_international_health_assistance_account", sa.Boolean(), nullable=False, server_default=sa.text("false")), schema=RECON_SCHEMA)

    op.add_column("assistance_transactions_profile_enriched", sa.Column("likely_other_public_health", sa.Boolean(), nullable=True), schema=RECON_SCHEMA)
    op.add_column("assistance_transactions_profile_enriched", sa.Column("likely_biomedical_research", sa.Boolean(), nullable=True), schema=RECON_SCHEMA)
    op.add_column("assistance_transactions_profile_enriched", sa.Column("likely_international_health_assistance", sa.Boolean(), nullable=True), schema=RECON_SCHEMA)

    op.add_column("contract_transactions_profile_enriched", sa.Column("likely_other_public_health", sa.Boolean(), nullable=True), schema=RECON_SCHEMA)
    op.add_column("contract_transactions_profile_enriched", sa.Column("likely_biomedical_research", sa.Boolean(), nullable=True), schema=RECON_SCHEMA)
    op.add_column("contract_transactions_profile_enriched", sa.Column("likely_international_health_assistance", sa.Boolean(), nullable=True), schema=RECON_SCHEMA)

    op.add_column("profile_scope_state_year_summary", sa.Column("other_public_health_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("profile_scope_state_year_summary", sa.Column("biomedical_research_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("profile_scope_state_year_summary", sa.Column("international_health_assistance_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)

    op.add_column("profile_reconciliation_state_year", sa.Column("other_public_health_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("profile_reconciliation_state_year", sa.Column("biomedical_research_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("profile_reconciliation_state_year", sa.Column("international_health_assistance_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)

    op.add_column("normalized_state_funding", sa.Column("other_public_health_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("normalized_state_funding", sa.Column("biomedical_research_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("normalized_state_funding", sa.Column("international_health_assistance_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)

    _drop_support_views()
    _create_support_views(include_expanded=True)


def downgrade() -> None:
    _drop_support_views()

    op.drop_column("normalized_state_funding", "international_health_assistance_amount", schema=RECON_SCHEMA)
    op.drop_column("normalized_state_funding", "biomedical_research_amount", schema=RECON_SCHEMA)
    op.drop_column("normalized_state_funding", "other_public_health_amount", schema=RECON_SCHEMA)

    op.drop_column("profile_reconciliation_state_year", "international_health_assistance_amount", schema=RECON_SCHEMA)
    op.drop_column("profile_reconciliation_state_year", "biomedical_research_amount", schema=RECON_SCHEMA)
    op.drop_column("profile_reconciliation_state_year", "other_public_health_amount", schema=RECON_SCHEMA)

    op.drop_column("profile_scope_state_year_summary", "international_health_assistance_amount", schema=RECON_SCHEMA)
    op.drop_column("profile_scope_state_year_summary", "biomedical_research_amount", schema=RECON_SCHEMA)
    op.drop_column("profile_scope_state_year_summary", "other_public_health_amount", schema=RECON_SCHEMA)

    op.drop_column("contract_transactions_profile_enriched", "likely_international_health_assistance", schema=RECON_SCHEMA)
    op.drop_column("contract_transactions_profile_enriched", "likely_biomedical_research", schema=RECON_SCHEMA)
    op.drop_column("contract_transactions_profile_enriched", "likely_other_public_health", schema=RECON_SCHEMA)

    op.drop_column("assistance_transactions_profile_enriched", "likely_international_health_assistance", schema=RECON_SCHEMA)
    op.drop_column("assistance_transactions_profile_enriched", "likely_biomedical_research", schema=RECON_SCHEMA)
    op.drop_column("assistance_transactions_profile_enriched", "likely_other_public_health", schema=RECON_SCHEMA)

    op.drop_column("assistance_transaction_account_summary", "has_international_health_assistance_account", schema=RECON_SCHEMA)
    op.drop_column("assistance_transaction_account_summary", "has_biomedical_research_account", schema=RECON_SCHEMA)
    op.drop_column("assistance_transaction_account_summary", "has_other_public_health_account", schema=RECON_SCHEMA)

    op.drop_column("federal_account_lookup", "likely_international_health_assistance", schema=RECON_SCHEMA)
    op.drop_column("federal_account_lookup", "likely_biomedical_research", schema=RECON_SCHEMA)
    op.drop_column("federal_account_lookup", "likely_other_public_health", schema=RECON_SCHEMA)

    _create_support_views(include_expanded=False)
