"""add chip v1.1 normalization lookup view

Revision ID: 91d3f4c2ab10
Revises: 7c1e4a2b9d60
Create Date: 2026-03-23 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "91d3f4c2ab10"
down_revision: Union[str, None] = "7c1e4a2b9d60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ANALYTICS_SCHEMA = "analytics"
RECON_SCHEMA = "recon"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE VIEW {ANALYTICS_SCHEMA}.chip_normalized_state_funding_v11_ec AS
        WITH legacy AS (
            SELECT
                source_system,
                fiscal_year,
                state_code,
                raw_amount,
                cdc_profile_reference_amount
            FROM {RECON_SCHEMA}.normalized_state_funding
            WHERE source_system = 'usaspending'
        )
        SELECT
            'usaspending'::text AS source_system,
            v11.fiscal_year,
            v11.state_code,
            legacy.raw_amount,
            v11.total_state_relevant_funding AS normalized_amount,
            'state_profile_v11_emergency_classification_aligned'::text AS normalized_amount_type,
            'v1_1_emergency_classification_state_profile_alignment'::text AS normalization_method,
            COALESCE(v11.chip_state_profile_source_version, 'chip_state_profile_v1_1_emergency_classification')::text AS funding_stream_logic_version,
            legacy.cdc_profile_reference_amount,
            (
                COALESCE(v11.total_state_relevant_funding, 0) - COALESCE(legacy.raw_amount, 0)
            )::numeric(18, 2) AS residual_amount,
            CASE
                WHEN legacy.raw_amount IS NULL OR legacy.raw_amount = 0 THEN NULL
                ELSE (
                    (COALESCE(v11.total_state_relevant_funding, 0) - COALESCE(legacy.raw_amount, 0))
                    / NULLIF(legacy.raw_amount, 0)
                )::numeric(12, 6)
            END AS residual_pct,
            'v1_1_emergency_classification_state_profile'::text AS calibration_basis,
            v11.core_cdc_program_funding AS core_public_health_amount,
            v11.emergency_distributed_funding AS emergency_public_health_amount,
            NULL::numeric AS federal_health_transfer_amount,
            NULL::numeric AS procurement_support_scope_amount,
            NULL::numeric AS special_transfer_amount,
            NULL::numeric AS other_public_health_amount,
            NULL::numeric AS biomedical_research_amount,
            NULL::numeric AS international_health_assistance_amount,
            NULL::numeric AS unknown_funding_scope_amount,
            jsonb_build_object(
                'core_cdc_program_funding', v11.core_cdc_program_funding,
                'emergency_distributed_funding', v11.emergency_distributed_funding,
                'state_profile_source_version', v11.chip_state_profile_source_version,
                'run_id', v11.run_id
            ) AS funding_scope_components_json,
            COALESCE(v11.methodology_version, 'v1.1')::text AS methodology_version,
            CASE
                WHEN legacy.raw_amount IS NULL THEN 'State benchmark is available from the v1.1 emergency-classification layer, but the legacy raw statewide denominator is missing; state totals can still render directly.'
                ELSE 'CHIP Normalized Funding v1.1 preserves the raw within-state distribution while rescaling it to the v1.1 emergency-classification state-profile benchmark.'
            END::text AS confidence_note,
            NOW() AS refreshed_at,
            CASE
                WHEN legacy.raw_amount IS NULL OR legacy.raw_amount = 0 THEN NULL
                ELSE v11.total_state_relevant_funding / NULLIF(legacy.raw_amount, 0)
            END AS normalization_factor
        FROM {ANALYTICS_SCHEMA}.chip_state_funding_profile_v11_ec AS v11
        LEFT JOIN legacy
          ON legacy.state_code = v11.state_code
         AND legacy.fiscal_year = v11.fiscal_year
        """
    )


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {ANALYTICS_SCHEMA}.chip_normalized_state_funding_v11_ec")
