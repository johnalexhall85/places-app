"""add profile calibration reconciliation layer

Revision ID: ab7e3f1c92d4
Revises: 4a6d2c8b1e90
Create Date: 2026-03-15 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "ab7e3f1c92d4"
down_revision: Union[str, None] = "4a6d2c8b1e90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CDC_PROFILES_SCHEMA = "cdc_profiles"
RECON_SCHEMA = "recon"
TAGGS_SCHEMA = "taggs"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {RECON_SCHEMA}")

    op.create_table(
        "profile_reconciliation_state_year",
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("state_code", sa.String(length=2), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("cdc_profile_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("reconstructed_profile_scope_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("raw_reconstructed_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("residual_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("residual_pct", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("abs_residual_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("regular_appropriation_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("covid_emergency_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("arpa_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("other_emergency_or_disaster_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("non_covid_supplemental_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("transfer_or_special_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("procurement_support_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("unknown_stream_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("unknown_stream_included_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("excluded_non_domestic_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("excluded_contract_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("uncertain_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column(
            "included_transaction_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "excluded_transaction_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "uncertain_transaction_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("calibration_status", sa.Text(), nullable=True),
        sa.Column("confidence_label", sa.Text(), nullable=True),
        sa.Column("methodology_version", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("fiscal_year", "state_code", "source_system"),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_profile_reconciliation_state_year_fy_idx",
        "profile_reconciliation_state_year",
        ["fiscal_year"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_profile_reconciliation_state_year_state_idx",
        "profile_reconciliation_state_year",
        ["state_code"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_profile_reconciliation_state_year_source_idx",
        "profile_reconciliation_state_year",
        ["source_system"],
        unique=False,
        schema=RECON_SCHEMA,
    )

    op.create_table(
        "profile_reconciliation_driver_breakdown",
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("state_code", sa.String(length=2), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("driver_name", sa.Text(), nullable=False),
        sa.Column("inclusion_status", sa.Text(), nullable=False),
        sa.Column(
            "driver_amount",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("methodology_version", sa.Text(), nullable=True),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "fiscal_year",
            "state_code",
            "source_system",
            "driver_name",
            "inclusion_status",
        ),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_profile_reconciliation_driver_fy_idx",
        "profile_reconciliation_driver_breakdown",
        ["fiscal_year"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_profile_reconciliation_driver_state_idx",
        "profile_reconciliation_driver_breakdown",
        ["state_code"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_profile_reconciliation_driver_source_idx",
        "profile_reconciliation_driver_breakdown",
        ["source_system"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_profile_reconciliation_driver_name_idx",
        "profile_reconciliation_driver_breakdown",
        ["driver_name"],
        unique=False,
        schema=RECON_SCHEMA,
    )

    op.create_table(
        "profile_reconciliation_summary",
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("state_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("avg_abs_residual_pct", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("median_abs_residual_pct", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("max_abs_residual_pct", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("exact_window_state_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("calibrated_state_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("needs_review_state_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("sparse_state_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_unknown_stream_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("total_uncertain_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("methodology_version", sa.Text(), nullable=True),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("fiscal_year", "source_system"),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_profile_reconciliation_summary_source_idx",
        "profile_reconciliation_summary",
        ["source_system"],
        unique=False,
        schema=RECON_SCHEMA,
    )

    op.add_column(
        "normalized_state_funding",
        sa.Column("cdc_profile_reference_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        "normalized_state_funding",
        sa.Column("residual_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        "normalized_state_funding",
        sa.Column("residual_pct", sa.Numeric(precision=12, scale=6), nullable=True),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        "normalized_state_funding",
        sa.Column("calibration_basis", sa.Text(), nullable=True),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        "normalized_state_funding",
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema=RECON_SCHEMA,
    )
    op.execute(
        f"""
        UPDATE {RECON_SCHEMA}.normalized_state_funding
        SET refreshed_at = COALESCE(updated_at, created_at, now())
        """
    )

    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.profile_calibration_taggs_state_year_support")
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.profile_calibration_usaspending_state_year_support")
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.profile_scope_transaction_diagnostics")
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.profile_calibration_cdc_reference")

    op.execute(
        f"""
        CREATE VIEW {RECON_SCHEMA}.profile_calibration_cdc_reference AS
        SELECT
            fiscal_year,
            UPPER(BTRIM(state_code)) AS state_code,
            NULLIF(BTRIM(state_name), '') AS state_name,
            COALESCE(amount, 0)::numeric(18, 2) AS cdc_profile_amount,
            COALESCE(row_count, 0)::integer AS row_count,
            methodology_version,
            refreshed_at
        FROM {CDC_PROFILES_SCHEMA}.state_year_totals
        WHERE fiscal_year BETWEEN 2020 AND 2023
          AND NULLIF(BTRIM(state_code), '') IS NOT NULL
        """
    )

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


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.profile_calibration_taggs_state_year_support")
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.profile_calibration_usaspending_state_year_support")
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.profile_scope_transaction_diagnostics")
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.profile_calibration_cdc_reference")

    op.drop_column("normalized_state_funding", "refreshed_at", schema=RECON_SCHEMA)
    op.drop_column("normalized_state_funding", "calibration_basis", schema=RECON_SCHEMA)
    op.drop_column("normalized_state_funding", "residual_pct", schema=RECON_SCHEMA)
    op.drop_column("normalized_state_funding", "residual_amount", schema=RECON_SCHEMA)
    op.drop_column("normalized_state_funding", "cdc_profile_reference_amount", schema=RECON_SCHEMA)

    op.drop_index(
        "recon_profile_reconciliation_summary_source_idx",
        table_name="profile_reconciliation_summary",
        schema=RECON_SCHEMA,
    )
    op.drop_table("profile_reconciliation_summary", schema=RECON_SCHEMA)

    op.drop_index(
        "recon_profile_reconciliation_driver_name_idx",
        table_name="profile_reconciliation_driver_breakdown",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_profile_reconciliation_driver_source_idx",
        table_name="profile_reconciliation_driver_breakdown",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_profile_reconciliation_driver_state_idx",
        table_name="profile_reconciliation_driver_breakdown",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_profile_reconciliation_driver_fy_idx",
        table_name="profile_reconciliation_driver_breakdown",
        schema=RECON_SCHEMA,
    )
    op.drop_table("profile_reconciliation_driver_breakdown", schema=RECON_SCHEMA)

    op.drop_index(
        "recon_profile_reconciliation_state_year_source_idx",
        table_name="profile_reconciliation_state_year",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_profile_reconciliation_state_year_state_idx",
        table_name="profile_reconciliation_state_year",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_profile_reconciliation_state_year_fy_idx",
        table_name="profile_reconciliation_state_year",
        schema=RECON_SCHEMA,
    )
    op.drop_table("profile_reconciliation_state_year", schema=RECON_SCHEMA)
