"""add funding scope refinement columns and support views

Revision ID: 7f4c6d8e2b19
Revises: 5f3a1b7c9d22
Create Date: 2026-03-16 00:45:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "7f4c6d8e2b19"
down_revision: Union[str, None] = "5f3a1b7c9d22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RECON_SCHEMA = "recon"
TAGGS_SCHEMA = "taggs"


def _drop_recon_support_views() -> None:
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.profile_calibration_taggs_state_year_support")
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.profile_calibration_usaspending_state_year_support")
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.profile_scope_transaction_diagnostics")


def _create_refined_support_views() -> None:
    op.execute(
        f"""
        CREATE VIEW {RECON_SCHEMA}.profile_scope_transaction_diagnostics AS
        SELECT
            tx.source_system,
            tx.source_transaction_id,
            tx.fiscal_year,
            UPPER(BTRIM(tx.state_code)) AS state_code,
            tx.recipient_name,
            tx.federal_account_symbol,
            COALESCE(NULLIF(BTRIM(tx.effective_funding_stream), ''), 'unknown') AS effective_funding_stream,
            COALESCE(NULLIF(BTRIM(tx.effective_funding_scope), ''), 'unknown') AS effective_funding_scope,
            tx.include_in_profile_scope,
            CASE
                WHEN tx.include_in_profile_scope IS TRUE THEN 'included'
                WHEN tx.include_in_profile_scope IS FALSE THEN 'excluded'
                ELSE 'uncertain'
            END AS inclusion_status,
            COALESCE(tx.inclusion_weight, 0)::numeric(5, 2) AS inclusion_weight,
            tx.inclusion_reason,
            tx.confidence_label,
            COALESCE(tx.raw_amount, 0)::numeric(18, 2) AS raw_amount,
            COALESCE(tx.normalized_profile_scope_amount, 0)::numeric(18, 2) AS normalized_profile_scope_amount,
            CASE
                WHEN tx.source_system = 'assistance' THEN assist.likely_domestic
                WHEN tx.source_system = 'contracts' THEN CASE
                    WHEN COALESCE(
                        NULLIF(BTRIM(contract.recipient_country_name), ''),
                        CASE WHEN tx.state_code IS NOT NULL THEN 'UNITED STATES' ELSE NULL END
                    ) IS NULL THEN NULL
                    WHEN lower(
                        COALESCE(
                            NULLIF(BTRIM(contract.recipient_country_name), ''),
                            CASE WHEN tx.state_code IS NOT NULL THEN 'UNITED STATES' ELSE NULL END
                        )
                    ) IN (
                        'united states',
                        'united states of america',
                        'united states minor outlying islands',
                        'usa',
                        'us',
                        'u.s.'
                    ) THEN TRUE
                    ELSE FALSE
                END
                ELSE NULL
            END AS likely_domestic,
            CASE WHEN tx.source_system = 'contracts' THEN TRUE ELSE FALSE END AS is_contract,
            COALESCE(contract.likely_vfc_related, FALSE) AS likely_vfc_related,
            tx.methodology_version,
            tx.refreshed_at
        FROM {RECON_SCHEMA}.profile_scope_transactions AS tx
        LEFT JOIN {RECON_SCHEMA}.assistance_transactions_profile_enriched AS assist
          ON tx.source_system = 'assistance'
         AND assist.source_transaction_id = tx.source_transaction_id
        LEFT JOIN {RECON_SCHEMA}.contract_transactions_profile_enriched AS contract
          ON tx.source_system = 'contracts'
         AND contract.source_transaction_id = tx.source_transaction_id
        WHERE tx.fiscal_year IS NOT NULL
          AND NULLIF(BTRIM(tx.state_code), '') IS NOT NULL
        """
    )

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
            COALESCE(SUM(CASE WHEN effective_funding_scope = 'core_public_health' AND include_in_profile_scope IS TRUE THEN normalized_profile_scope_amount ELSE 0 END), 0)::numeric(18, 2) AS core_public_health_amount,
            COALESCE(SUM(CASE WHEN effective_funding_scope = 'core_public_health' AND include_in_profile_scope IS FALSE THEN raw_amount ELSE 0 END), 0)::numeric(18, 2) AS core_public_health_excluded_amount,
            COALESCE(SUM(CASE WHEN effective_funding_scope = 'core_public_health' AND include_in_profile_scope IS NULL THEN raw_amount ELSE 0 END), 0)::numeric(18, 2) AS core_public_health_uncertain_amount,
            COALESCE(SUM(CASE WHEN effective_funding_scope = 'emergency_public_health' AND include_in_profile_scope IS TRUE THEN normalized_profile_scope_amount ELSE 0 END), 0)::numeric(18, 2) AS emergency_public_health_amount,
            COALESCE(SUM(CASE WHEN effective_funding_scope = 'emergency_public_health' AND include_in_profile_scope IS FALSE THEN raw_amount ELSE 0 END), 0)::numeric(18, 2) AS emergency_public_health_excluded_amount,
            COALESCE(SUM(CASE WHEN effective_funding_scope = 'emergency_public_health' AND include_in_profile_scope IS NULL THEN raw_amount ELSE 0 END), 0)::numeric(18, 2) AS emergency_public_health_uncertain_amount,
            COALESCE(SUM(CASE WHEN effective_funding_scope = 'federal_health_transfer' AND include_in_profile_scope IS TRUE THEN normalized_profile_scope_amount ELSE 0 END), 0)::numeric(18, 2) AS federal_health_transfer_amount,
            COALESCE(SUM(CASE WHEN effective_funding_scope = 'federal_health_transfer' AND include_in_profile_scope IS FALSE THEN raw_amount ELSE 0 END), 0)::numeric(18, 2) AS federal_health_transfer_excluded_amount,
            COALESCE(SUM(CASE WHEN effective_funding_scope = 'federal_health_transfer' AND include_in_profile_scope IS NULL THEN raw_amount ELSE 0 END), 0)::numeric(18, 2) AS federal_health_transfer_uncertain_amount,
            COALESCE(SUM(CASE WHEN effective_funding_scope = 'procurement_support' AND include_in_profile_scope IS TRUE THEN normalized_profile_scope_amount ELSE 0 END), 0)::numeric(18, 2) AS procurement_support_scope_amount,
            COALESCE(SUM(CASE WHEN effective_funding_scope = 'procurement_support' AND include_in_profile_scope IS FALSE THEN raw_amount ELSE 0 END), 0)::numeric(18, 2) AS procurement_support_scope_excluded_amount,
            COALESCE(SUM(CASE WHEN effective_funding_scope = 'procurement_support' AND include_in_profile_scope IS NULL THEN raw_amount ELSE 0 END), 0)::numeric(18, 2) AS procurement_support_scope_uncertain_amount,
            COALESCE(SUM(CASE WHEN effective_funding_scope = 'special_transfer' AND include_in_profile_scope IS TRUE THEN normalized_profile_scope_amount ELSE 0 END), 0)::numeric(18, 2) AS special_transfer_amount,
            COALESCE(SUM(CASE WHEN effective_funding_scope = 'special_transfer' AND include_in_profile_scope IS FALSE THEN raw_amount ELSE 0 END), 0)::numeric(18, 2) AS special_transfer_excluded_amount,
            COALESCE(SUM(CASE WHEN effective_funding_scope = 'special_transfer' AND include_in_profile_scope IS NULL THEN raw_amount ELSE 0 END), 0)::numeric(18, 2) AS special_transfer_uncertain_amount,
            COALESCE(SUM(CASE WHEN effective_funding_scope = 'unknown' AND include_in_profile_scope IS TRUE THEN normalized_profile_scope_amount ELSE 0 END), 0)::numeric(18, 2) AS unknown_funding_scope_amount,
            COALESCE(SUM(CASE WHEN effective_funding_scope = 'unknown' AND include_in_profile_scope IS FALSE THEN raw_amount ELSE 0 END), 0)::numeric(18, 2) AS unknown_funding_scope_excluded_amount,
            COALESCE(SUM(CASE WHEN effective_funding_scope = 'unknown' AND include_in_profile_scope IS NULL THEN raw_amount ELSE 0 END), 0)::numeric(18, 2) AS unknown_funding_scope_uncertain_amount,
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
                COALESCE(SUM(CASE WHEN funding_stream = 'regular_appropriation' AND include_in_cdc_profile_scope IS TRUE THEN COALESCE(raw_amount, 0) * COALESCE(inclusion_weight, 0) ELSE 0 END), 0)::numeric(18, 2) AS core_public_health_amount,
                COALESCE(SUM(CASE WHEN funding_stream = 'regular_appropriation' AND include_in_cdc_profile_scope IS FALSE THEN COALESCE(raw_amount, 0) ELSE 0 END), 0)::numeric(18, 2) AS core_public_health_excluded_amount,
                0::numeric(18, 2) AS core_public_health_uncertain_amount,
                COALESCE(SUM(CASE WHEN funding_stream IN ('covid_emergency', 'arpa', 'other_emergency_or_disaster') AND include_in_cdc_profile_scope IS TRUE THEN COALESCE(raw_amount, 0) * COALESCE(inclusion_weight, 0) ELSE 0 END), 0)::numeric(18, 2) AS emergency_public_health_amount,
                COALESCE(SUM(CASE WHEN funding_stream IN ('covid_emergency', 'arpa', 'other_emergency_or_disaster') AND include_in_cdc_profile_scope IS FALSE THEN COALESCE(raw_amount, 0) ELSE 0 END), 0)::numeric(18, 2) AS emergency_public_health_excluded_amount,
                0::numeric(18, 2) AS emergency_public_health_uncertain_amount,
                0::numeric(18, 2) AS federal_health_transfer_amount,
                0::numeric(18, 2) AS federal_health_transfer_excluded_amount,
                0::numeric(18, 2) AS federal_health_transfer_uncertain_amount,
                COALESCE(SUM(CASE WHEN funding_stream = 'procurement_support' AND include_in_cdc_profile_scope IS TRUE THEN COALESCE(raw_amount, 0) * COALESCE(inclusion_weight, 0) ELSE 0 END), 0)::numeric(18, 2) AS procurement_support_scope_amount,
                COALESCE(SUM(CASE WHEN funding_stream = 'procurement_support' AND include_in_cdc_profile_scope IS FALSE THEN COALESCE(raw_amount, 0) ELSE 0 END), 0)::numeric(18, 2) AS procurement_support_scope_excluded_amount,
                0::numeric(18, 2) AS procurement_support_scope_uncertain_amount,
                COALESCE(SUM(CASE WHEN funding_stream = 'transfer_or_special' AND include_in_cdc_profile_scope IS TRUE THEN COALESCE(raw_amount, 0) * COALESCE(inclusion_weight, 0) ELSE 0 END), 0)::numeric(18, 2) AS special_transfer_amount,
                COALESCE(SUM(CASE WHEN funding_stream = 'transfer_or_special' AND include_in_cdc_profile_scope IS FALSE THEN COALESCE(raw_amount, 0) ELSE 0 END), 0)::numeric(18, 2) AS special_transfer_excluded_amount,
                0::numeric(18, 2) AS special_transfer_uncertain_amount,
                COALESCE(SUM(CASE WHEN funding_stream = 'unknown' AND include_in_cdc_profile_scope IS TRUE THEN COALESCE(raw_amount, 0) * COALESCE(inclusion_weight, 0) ELSE 0 END), 0)::numeric(18, 2) AS unknown_funding_scope_amount,
                COALESCE(SUM(CASE WHEN funding_stream = 'unknown' AND include_in_cdc_profile_scope IS FALSE THEN COALESCE(raw_amount, 0) ELSE 0 END), 0)::numeric(18, 2) AS unknown_funding_scope_excluded_amount,
                0::numeric(18, 2) AS unknown_funding_scope_uncertain_amount,
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
            normalized_rollup.core_public_health_amount,
            normalized_rollup.core_public_health_excluded_amount,
            normalized_rollup.core_public_health_uncertain_amount,
            normalized_rollup.emergency_public_health_amount,
            normalized_rollup.emergency_public_health_excluded_amount,
            normalized_rollup.emergency_public_health_uncertain_amount,
            normalized_rollup.federal_health_transfer_amount,
            normalized_rollup.federal_health_transfer_excluded_amount,
            normalized_rollup.federal_health_transfer_uncertain_amount,
            normalized_rollup.procurement_support_scope_amount,
            normalized_rollup.procurement_support_scope_excluded_amount,
            normalized_rollup.procurement_support_scope_uncertain_amount,
            normalized_rollup.special_transfer_amount,
            normalized_rollup.special_transfer_excluded_amount,
            normalized_rollup.special_transfer_uncertain_amount,
            normalized_rollup.unknown_funding_scope_amount,
            normalized_rollup.unknown_funding_scope_excluded_amount,
            normalized_rollup.unknown_funding_scope_uncertain_amount,
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
    op.add_column("federal_account_lookup", sa.Column("funding_scope_guess", sa.Text(), nullable=True), schema=RECON_SCHEMA)
    op.add_column("federal_account_lookup", sa.Column("funding_scope_method", sa.Text(), nullable=True), schema=RECON_SCHEMA)
    op.add_column("federal_account_lookup", sa.Column("likely_core_public_health", sa.Boolean(), nullable=True), schema=RECON_SCHEMA)
    op.add_column("federal_account_lookup", sa.Column("likely_emergency_public_health", sa.Boolean(), nullable=True), schema=RECON_SCHEMA)
    op.add_column("federal_account_lookup", sa.Column("likely_federal_health_transfer", sa.Boolean(), nullable=True), schema=RECON_SCHEMA)
    op.add_column("federal_account_lookup", sa.Column("likely_procurement_support", sa.Boolean(), nullable=True), schema=RECON_SCHEMA)
    op.add_column("federal_account_lookup", sa.Column("manual_funding_scope", sa.Text(), nullable=True), schema=RECON_SCHEMA)
    op.add_column("federal_account_lookup", sa.Column("effective_funding_scope", sa.Text(), nullable=True), schema=RECON_SCHEMA)
    op.create_index(
        "recon_federal_account_lookup_scope_idx",
        "federal_account_lookup",
        ["effective_funding_scope"],
        unique=False,
        schema=RECON_SCHEMA,
    )

    op.add_column("federal_account_classification_rules", sa.Column("assigned_funding_scope", sa.Text(), nullable=True), schema=RECON_SCHEMA)

    op.add_column("assistance_transaction_account_summary", sa.Column("has_core_public_health_account", sa.Boolean(), nullable=False, server_default=sa.text("false")), schema=RECON_SCHEMA)
    op.add_column("assistance_transaction_account_summary", sa.Column("has_emergency_public_health_account", sa.Boolean(), nullable=False, server_default=sa.text("false")), schema=RECON_SCHEMA)
    op.add_column("assistance_transaction_account_summary", sa.Column("has_federal_health_transfer_account", sa.Boolean(), nullable=False, server_default=sa.text("false")), schema=RECON_SCHEMA)
    op.add_column("assistance_transaction_account_summary", sa.Column("has_special_transfer_account", sa.Boolean(), nullable=False, server_default=sa.text("false")), schema=RECON_SCHEMA)
    op.add_column("assistance_transaction_account_summary", sa.Column("has_procurement_support_account", sa.Boolean(), nullable=False, server_default=sa.text("false")), schema=RECON_SCHEMA)
    op.add_column("assistance_transaction_account_summary", sa.Column("effective_funding_scope", sa.Text(), nullable=True), schema=RECON_SCHEMA)

    op.add_column("assistance_transactions_profile_enriched", sa.Column("effective_funding_scope", sa.Text(), nullable=True), schema=RECON_SCHEMA)
    op.add_column("assistance_transactions_profile_enriched", sa.Column("likely_core_public_health", sa.Boolean(), nullable=True), schema=RECON_SCHEMA)
    op.add_column("assistance_transactions_profile_enriched", sa.Column("likely_emergency_public_health", sa.Boolean(), nullable=True), schema=RECON_SCHEMA)
    op.add_column("assistance_transactions_profile_enriched", sa.Column("likely_federal_health_transfer", sa.Boolean(), nullable=True), schema=RECON_SCHEMA)
    op.add_column("assistance_transactions_profile_enriched", sa.Column("likely_procurement_support", sa.Boolean(), nullable=True), schema=RECON_SCHEMA)

    op.add_column("contract_transactions_profile_enriched", sa.Column("effective_funding_scope", sa.Text(), nullable=True), schema=RECON_SCHEMA)
    op.add_column("contract_transactions_profile_enriched", sa.Column("likely_core_public_health", sa.Boolean(), nullable=True), schema=RECON_SCHEMA)
    op.add_column("contract_transactions_profile_enriched", sa.Column("likely_emergency_public_health", sa.Boolean(), nullable=True), schema=RECON_SCHEMA)
    op.add_column("contract_transactions_profile_enriched", sa.Column("likely_federal_health_transfer", sa.Boolean(), nullable=True), schema=RECON_SCHEMA)
    op.add_column("contract_transactions_profile_enriched", sa.Column("likely_procurement_support", sa.Boolean(), nullable=True), schema=RECON_SCHEMA)

    op.add_column("profile_scope_transactions", sa.Column("effective_funding_scope", sa.Text(), nullable=True), schema=RECON_SCHEMA)

    op.add_column("profile_scope_state_year_summary", sa.Column("core_public_health_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("profile_scope_state_year_summary", sa.Column("emergency_public_health_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("profile_scope_state_year_summary", sa.Column("federal_health_transfer_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("profile_scope_state_year_summary", sa.Column("procurement_support_scope_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("profile_scope_state_year_summary", sa.Column("special_transfer_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("profile_scope_state_year_summary", sa.Column("unknown_funding_scope_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)

    op.add_column("profile_reconciliation_state_year", sa.Column("core_public_health_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("profile_reconciliation_state_year", sa.Column("emergency_public_health_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("profile_reconciliation_state_year", sa.Column("federal_health_transfer_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("profile_reconciliation_state_year", sa.Column("procurement_support_scope_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("profile_reconciliation_state_year", sa.Column("special_transfer_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("profile_reconciliation_state_year", sa.Column("unknown_funding_scope_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)

    op.add_column("normalized_state_funding", sa.Column("core_public_health_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("normalized_state_funding", sa.Column("emergency_public_health_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("normalized_state_funding", sa.Column("federal_health_transfer_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("normalized_state_funding", sa.Column("procurement_support_scope_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("normalized_state_funding", sa.Column("special_transfer_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("normalized_state_funding", sa.Column("unknown_funding_scope_amount", sa.Numeric(precision=18, scale=2), nullable=True), schema=RECON_SCHEMA)
    op.add_column("normalized_state_funding", sa.Column("funding_scope_components_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema=RECON_SCHEMA)

    _drop_recon_support_views()
    _create_refined_support_views()


def downgrade() -> None:
    _drop_recon_support_views()

    op.drop_column("normalized_state_funding", "funding_scope_components_json", schema=RECON_SCHEMA)
    op.drop_column("normalized_state_funding", "unknown_funding_scope_amount", schema=RECON_SCHEMA)
    op.drop_column("normalized_state_funding", "special_transfer_amount", schema=RECON_SCHEMA)
    op.drop_column("normalized_state_funding", "procurement_support_scope_amount", schema=RECON_SCHEMA)
    op.drop_column("normalized_state_funding", "federal_health_transfer_amount", schema=RECON_SCHEMA)
    op.drop_column("normalized_state_funding", "emergency_public_health_amount", schema=RECON_SCHEMA)
    op.drop_column("normalized_state_funding", "core_public_health_amount", schema=RECON_SCHEMA)

    op.drop_column("profile_reconciliation_state_year", "unknown_funding_scope_amount", schema=RECON_SCHEMA)
    op.drop_column("profile_reconciliation_state_year", "special_transfer_amount", schema=RECON_SCHEMA)
    op.drop_column("profile_reconciliation_state_year", "procurement_support_scope_amount", schema=RECON_SCHEMA)
    op.drop_column("profile_reconciliation_state_year", "federal_health_transfer_amount", schema=RECON_SCHEMA)
    op.drop_column("profile_reconciliation_state_year", "emergency_public_health_amount", schema=RECON_SCHEMA)
    op.drop_column("profile_reconciliation_state_year", "core_public_health_amount", schema=RECON_SCHEMA)

    op.drop_column("profile_scope_state_year_summary", "unknown_funding_scope_amount", schema=RECON_SCHEMA)
    op.drop_column("profile_scope_state_year_summary", "special_transfer_amount", schema=RECON_SCHEMA)
    op.drop_column("profile_scope_state_year_summary", "procurement_support_scope_amount", schema=RECON_SCHEMA)
    op.drop_column("profile_scope_state_year_summary", "federal_health_transfer_amount", schema=RECON_SCHEMA)
    op.drop_column("profile_scope_state_year_summary", "emergency_public_health_amount", schema=RECON_SCHEMA)
    op.drop_column("profile_scope_state_year_summary", "core_public_health_amount", schema=RECON_SCHEMA)

    op.drop_column("profile_scope_transactions", "effective_funding_scope", schema=RECON_SCHEMA)

    op.drop_column("contract_transactions_profile_enriched", "likely_procurement_support", schema=RECON_SCHEMA)
    op.drop_column("contract_transactions_profile_enriched", "likely_federal_health_transfer", schema=RECON_SCHEMA)
    op.drop_column("contract_transactions_profile_enriched", "likely_emergency_public_health", schema=RECON_SCHEMA)
    op.drop_column("contract_transactions_profile_enriched", "likely_core_public_health", schema=RECON_SCHEMA)
    op.drop_column("contract_transactions_profile_enriched", "effective_funding_scope", schema=RECON_SCHEMA)

    op.drop_column("assistance_transactions_profile_enriched", "likely_procurement_support", schema=RECON_SCHEMA)
    op.drop_column("assistance_transactions_profile_enriched", "likely_federal_health_transfer", schema=RECON_SCHEMA)
    op.drop_column("assistance_transactions_profile_enriched", "likely_emergency_public_health", schema=RECON_SCHEMA)
    op.drop_column("assistance_transactions_profile_enriched", "likely_core_public_health", schema=RECON_SCHEMA)
    op.drop_column("assistance_transactions_profile_enriched", "effective_funding_scope", schema=RECON_SCHEMA)

    op.drop_column("assistance_transaction_account_summary", "effective_funding_scope", schema=RECON_SCHEMA)
    op.drop_column("assistance_transaction_account_summary", "has_procurement_support_account", schema=RECON_SCHEMA)
    op.drop_column("assistance_transaction_account_summary", "has_special_transfer_account", schema=RECON_SCHEMA)
    op.drop_column("assistance_transaction_account_summary", "has_federal_health_transfer_account", schema=RECON_SCHEMA)
    op.drop_column("assistance_transaction_account_summary", "has_emergency_public_health_account", schema=RECON_SCHEMA)
    op.drop_column("assistance_transaction_account_summary", "has_core_public_health_account", schema=RECON_SCHEMA)

    op.drop_column("federal_account_classification_rules", "assigned_funding_scope", schema=RECON_SCHEMA)

    op.drop_index("recon_federal_account_lookup_scope_idx", table_name="federal_account_lookup", schema=RECON_SCHEMA)
    op.drop_column("federal_account_lookup", "effective_funding_scope", schema=RECON_SCHEMA)
    op.drop_column("federal_account_lookup", "manual_funding_scope", schema=RECON_SCHEMA)
    op.drop_column("federal_account_lookup", "likely_procurement_support", schema=RECON_SCHEMA)
    op.drop_column("federal_account_lookup", "likely_federal_health_transfer", schema=RECON_SCHEMA)
    op.drop_column("federal_account_lookup", "likely_emergency_public_health", schema=RECON_SCHEMA)
    op.drop_column("federal_account_lookup", "likely_core_public_health", schema=RECON_SCHEMA)
    op.drop_column("federal_account_lookup", "funding_scope_method", schema=RECON_SCHEMA)
    op.drop_column("federal_account_lookup", "funding_scope_guess", schema=RECON_SCHEMA)

    op.execute(
        f"""
        CREATE VIEW {RECON_SCHEMA}.profile_scope_transaction_diagnostics AS
        SELECT
            tx.source_system,
            tx.source_transaction_id,
            tx.fiscal_year,
            UPPER(BTRIM(tx.state_code)) AS state_code,
            tx.recipient_name,
            tx.federal_account_symbol,
            COALESCE(NULLIF(BTRIM(tx.effective_funding_stream), ''), 'unknown') AS effective_funding_stream,
            tx.include_in_profile_scope,
            CASE
                WHEN tx.include_in_profile_scope IS TRUE THEN 'included'
                WHEN tx.include_in_profile_scope IS FALSE THEN 'excluded'
                ELSE 'uncertain'
            END AS inclusion_status,
            COALESCE(tx.inclusion_weight, 0)::numeric(5, 2) AS inclusion_weight,
            tx.inclusion_reason,
            tx.confidence_label,
            COALESCE(tx.raw_amount, 0)::numeric(18, 2) AS raw_amount,
            COALESCE(tx.normalized_profile_scope_amount, 0)::numeric(18, 2) AS normalized_profile_scope_amount,
            CASE
                WHEN tx.source_system = 'assistance' THEN assist.likely_domestic
                WHEN tx.source_system = 'contracts' THEN CASE
                    WHEN COALESCE(
                        NULLIF(BTRIM(contract.recipient_country_name), ''),
                        CASE WHEN tx.state_code IS NOT NULL THEN 'UNITED STATES' ELSE NULL END
                    ) IS NULL THEN NULL
                    WHEN lower(
                        COALESCE(
                            NULLIF(BTRIM(contract.recipient_country_name), ''),
                            CASE WHEN tx.state_code IS NOT NULL THEN 'UNITED STATES' ELSE NULL END
                        )
                    ) IN (
                        'united states',
                        'united states of america',
                        'united states minor outlying islands',
                        'usa',
                        'us',
                        'u.s.'
                    ) THEN TRUE
                    ELSE FALSE
                END
                ELSE NULL
            END AS likely_domestic,
            CASE WHEN tx.source_system = 'contracts' THEN TRUE ELSE FALSE END AS is_contract,
            COALESCE(contract.likely_vfc_related, FALSE) AS likely_vfc_related,
            tx.methodology_version,
            tx.refreshed_at
        FROM {RECON_SCHEMA}.profile_scope_transactions AS tx
        LEFT JOIN {RECON_SCHEMA}.assistance_transactions_profile_enriched AS assist
          ON tx.source_system = 'assistance'
         AND assist.source_transaction_id = tx.source_transaction_id
        LEFT JOIN {RECON_SCHEMA}.contract_transactions_profile_enriched AS contract
          ON tx.source_system = 'contracts'
         AND contract.source_transaction_id = tx.source_transaction_id
        WHERE tx.fiscal_year IS NOT NULL
          AND NULLIF(BTRIM(tx.state_code), '') IS NOT NULL
        """
    )

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
