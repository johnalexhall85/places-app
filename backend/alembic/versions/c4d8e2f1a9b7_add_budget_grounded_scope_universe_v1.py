"""add budget grounded scope universe v1

Revision ID: c4d8e2f1a9b7
Revises: 8b6d2f4e1c77
Create Date: 2026-04-06 04:30:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4d8e2f1a9b7"
down_revision: Union[str, None] = "8b6d2f4e1c77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BUDGET_SCHEMA = "budget"
CDC_FUNDING_SCHEMA = "cdc_funding"
TAGGS_SCHEMA = "taggs"
PLACES_SCHEMA = "public"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {BUDGET_SCHEMA}")

    op.create_table(
        "cdc_budget_grounded_scope_universe_v1",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("scope_universe_version", sa.Text(), nullable=False),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("resolution_id", sa.BigInteger(), nullable=False),
        sa.Column("resolution_version", sa.Text(), nullable=False),
        sa.Column("bridge_version", sa.Text(), nullable=False),
        sa.Column("bridge_id", sa.BigInteger(), nullable=False),
        sa.Column("budget_anchor_id", sa.Text(), nullable=False),
        sa.Column("classification_id", sa.BigInteger(), nullable=False),
        sa.Column("raw_budget_id", sa.BigInteger(), nullable=False),
        sa.Column("unique_id", sa.Text(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("budget_agency", sa.Text(), nullable=True),
        sa.Column("budget_sub_agency", sa.Text(), nullable=True),
        sa.Column("budget_program", sa.Text(), nullable=True),
        sa.Column("budget_sub_program", sa.Text(), nullable=True),
        sa.Column("budget_sub_program_2", sa.Text(), nullable=True),
        sa.Column("budget_sub_program_3", sa.Text(), nullable=True),
        sa.Column("budget_program_key", sa.Text(), nullable=True),
        sa.Column("appropriation_category", sa.Text(), nullable=False),
        sa.Column("appropriation_subtype", sa.Text(), nullable=True),
        sa.Column("classification_confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("primary_rule_code", sa.Text(), nullable=True),
        sa.Column("system_name", sa.Text(), nullable=False),
        sa.Column("source_record_id", sa.Text(), nullable=False),
        sa.Column("source_parent_record_id", sa.Text(), nullable=True),
        sa.Column("source_fiscal_year", sa.Integer(), nullable=True),
        sa.Column("match_tier", sa.Text(), nullable=True),
        sa.Column("match_type", sa.Text(), nullable=True),
        sa.Column("match_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("match_confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("confidence_band", sa.Text(), nullable=True),
        sa.Column("resolution_status", sa.Text(), nullable=False),
        sa.Column("allocation_pct", sa.Numeric(precision=8, scale=6), nullable=True),
        sa.Column("allocation_method", sa.Text(), nullable=True),
        sa.Column("resolution_method", sa.Text(), nullable=False),
        sa.Column("resolution_confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("analyst_reviewed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("auto_seeded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("resolution_reason_code", sa.Text(), nullable=True),
        sa.Column("reviewer_name", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("analyst_review_state", sa.Text(), nullable=True),
        sa.Column("allocation_balance_status", sa.Text(), nullable=True),
        sa.Column("spending_program_name", sa.Text(), nullable=True),
        sa.Column("spending_assistance_listing_title", sa.Text(), nullable=True),
        sa.Column("spending_aln", sa.Text(), nullable=True),
        sa.Column("spending_can_code", sa.Text(), nullable=True),
        sa.Column("spending_program_office", sa.Text(), nullable=True),
        sa.Column("spending_award_title", sa.Text(), nullable=True),
        sa.Column("spending_award_description", sa.Text(), nullable=True),
        sa.Column("spending_appropriation_type", sa.Text(), nullable=True),
        sa.Column("discretionary_mandatory_type", sa.Text(), nullable=False),
        sa.Column("emergency_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("supplemental_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("pphf_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("transfer_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("non_add_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("include_in_master_universe", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("inclusion_reason", sa.Text(), nullable=False),
        sa.Column("double_count_exclusion_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("double_count_exclusion_reason", sa.Text(), nullable=True),
        sa.Column("effective_allocation_pct", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("scoped_amount_multiplier", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("effective_scope_weight", sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column("trusted_auto_seed_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("category_display_label", sa.Text(), nullable=True),
        sa.Column("filter_bucket", sa.Text(), nullable=True),
        sa.Column("budget_amount_dollars", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("budget_amount_millions", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("allocated_budget_amount_dollars", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("allocated_budget_amount_millions", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope_universe_version",
            "resolution_id",
            name="uq_cdc_budget_grounded_scope_universe_v1_ver_resolution",
        ),
        schema=BUDGET_SCHEMA,
    )

    op.create_index(
        "cdc_budget_grounded_scope_universe_v1_version_idx",
        "cdc_budget_grounded_scope_universe_v1",
        ["scope_universe_version"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_grounded_scope_universe_v1_fy_idx",
        "cdc_budget_grounded_scope_universe_v1",
        ["fiscal_year"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_grounded_scope_universe_v1_system_idx",
        "cdc_budget_grounded_scope_universe_v1",
        ["system_name"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_grounded_scope_universe_v1_category_idx",
        "cdc_budget_grounded_scope_universe_v1",
        ["appropriation_category"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_grounded_scope_universe_v1_disc_mand_idx",
        "cdc_budget_grounded_scope_universe_v1",
        ["discretionary_mandatory_type"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_grounded_scope_universe_v1_emergency_idx",
        "cdc_budget_grounded_scope_universe_v1",
        ["emergency_flag"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_grounded_scope_universe_v1_supplemental_idx",
        "cdc_budget_grounded_scope_universe_v1",
        ["supplemental_flag"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_grounded_scope_universe_v1_pphf_idx",
        "cdc_budget_grounded_scope_universe_v1",
        ["pphf_flag"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_grounded_scope_universe_v1_transfer_idx",
        "cdc_budget_grounded_scope_universe_v1",
        ["transfer_flag"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_grounded_scope_universe_v1_analyst_idx",
        "cdc_budget_grounded_scope_universe_v1",
        ["analyst_reviewed"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_grounded_scope_universe_v1_auto_idx",
        "cdc_budget_grounded_scope_universe_v1",
        ["auto_seeded"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_grounded_scope_universe_v1_include_idx",
        "cdc_budget_grounded_scope_universe_v1",
        ["include_in_master_universe"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_grounded_scope_universe_v1_budget_program_key_idx",
        "cdc_budget_grounded_scope_universe_v1",
        ["budget_program_key"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_grounded_scope_universe_v1_source_record_idx",
        "cdc_budget_grounded_scope_universe_v1",
        ["source_record_id"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_grounded_scope_universe_v1 AS
        SELECT *
        FROM {BUDGET_SCHEMA}.cdc_budget_grounded_scope_universe_v1
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_grounded_scope_universe_included_v1 AS
        SELECT *
        FROM {BUDGET_SCHEMA}.cdc_budget_grounded_scope_universe_v1
        WHERE include_in_master_universe = TRUE
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_grounded_scope_universe_excluded_v1 AS
        SELECT *
        FROM {BUDGET_SCHEMA}.cdc_budget_grounded_scope_universe_v1
        WHERE include_in_master_universe = FALSE
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_grounded_scope_ui_summary_v1 AS
        SELECT
            scope_universe_version,
            fiscal_year,
            appropriation_category,
            discretionary_mandatory_type,
            emergency_flag,
            supplemental_flag,
            pphf_flag,
            transfer_flag,
            analyst_reviewed,
            auto_seeded,
            trusted_auto_seed_flag,
            include_in_master_universe,
            COUNT(*)::bigint AS row_count,
            COUNT(DISTINCT budget_anchor_id)::bigint AS anchor_count,
            COALESCE(SUM(effective_allocation_pct), 0::numeric) AS allocation_pct_sum,
            COALESCE(SUM(allocated_budget_amount_dollars), 0::numeric) AS allocated_budget_amount_dollars,
            COALESCE(SUM(allocated_budget_amount_millions), 0::numeric) AS allocated_budget_amount_millions
        FROM {BUDGET_SCHEMA}.cdc_budget_grounded_scope_universe_v1
        GROUP BY
            scope_universe_version,
            fiscal_year,
            appropriation_category,
            discretionary_mandatory_type,
            emergency_flag,
            supplemental_flag,
            pphf_flag,
            transfer_flag,
            analyst_reviewed,
            auto_seeded,
            trusted_auto_seed_flag,
            include_in_master_universe
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_grounded_scope_funding_records_v1 AS
        WITH county_lookup AS (
            SELECT
                county.location_id AS county_fips,
                county.state_abbr,
                county.state_desc,
                county.county_name,
                UPPER(REGEXP_REPLACE(COALESCE(county.county_name, ''), '[^A-Za-z0-9]', '', 'g')) AS county_key
            FROM {PLACES_SCHEMA}.dim_county AS county
        ),
        taggs_geo AS (
            SELECT
                taggs.id::text AS source_record_id,
                UPPER(TRIM(taggs.legal_entity_state_normalized)) AS recipient_state_code,
                state_dim.state_name AS recipient_state_name,
                county_lookup.county_fips AS recipient_county_fips,
                COALESCE(county_lookup.county_name, taggs.legal_entity_county_normalized) AS recipient_county_name,
                taggs.legal_entity_name AS recipient_name,
                taggs.award_number,
                taggs.assistance_listing_title,
                taggs.award_title,
                taggs.award_description
            FROM {TAGGS_SCHEMA}.award_funding_summary AS taggs
            LEFT JOIN county_lookup
                ON county_lookup.state_abbr = UPPER(TRIM(taggs.legal_entity_state_normalized))
               AND county_lookup.county_key = UPPER(REGEXP_REPLACE(COALESCE(taggs.legal_entity_county_normalized, ''), '[^A-Za-z0-9]', '', 'g'))
            LEFT JOIN {PLACES_SCHEMA}.dim_state_boundary AS state_dim
                ON state_dim.state_abbr = UPPER(TRIM(taggs.legal_entity_state_normalized))
        )
        SELECT
            universe.id,
            universe.scope_universe_version,
            universe.built_at,
            universe.resolution_id,
            universe.bridge_id,
            universe.budget_anchor_id,
            universe.classification_id,
            universe.raw_budget_id,
            universe.unique_id,
            CONCAT('budget-grounded:', universe.scope_universe_version, ':', universe.resolution_id::text) AS record_key,
            CASE
                WHEN universe.system_name = 'usaspending' THEN 'budget_grounded_usaspending'
                ELSE 'budget_grounded_taggs'
            END AS dataset_key,
            universe.fiscal_year,
            universe.system_name,
            universe.source_record_id,
            universe.source_parent_record_id,
            universe.appropriation_category,
            universe.appropriation_subtype,
            universe.discretionary_mandatory_type,
            universe.emergency_flag,
            universe.supplemental_flag,
            universe.pphf_flag,
            universe.transfer_flag,
            universe.non_add_flag,
            universe.analyst_reviewed,
            universe.auto_seeded,
            universe.trusted_auto_seed_flag,
            universe.include_in_master_universe,
            universe.double_count_exclusion_flag,
            universe.double_count_exclusion_reason,
            universe.inclusion_reason,
            universe.effective_allocation_pct,
            universe.scoped_amount_multiplier,
            universe.effective_scope_weight,
            universe.allocated_budget_amount_dollars AS obligation_amount,
            universe.category_display_label AS category,
            COALESCE(
                NULLIF(universe.budget_program, ''),
                NULLIF(universe.budget_program_key, ''),
                NULLIF(universe.appropriation_subtype, ''),
                'Unspecified budget program'
            ) AS subcategory,
            COALESCE(universe.category_display_label, universe.appropriation_category) AS program_area,
            COALESCE(universe.filter_bucket, 'unknown') AS mechanism,
            NULL::text AS recipient_type,
            universe.emergency_flag AS is_emergency_funding,
            CASE
                WHEN universe.system_name = 'usaspending' THEN prime.recipient_state_code
                ELSE taggs_geo.recipient_state_code
            END AS recipient_state_code,
            CASE
                WHEN universe.system_name = 'usaspending' THEN COALESCE(prime.recipient_state_name, state_dim.state_name)
                ELSE taggs_geo.recipient_state_name
            END AS recipient_state_name,
            CASE
                WHEN universe.system_name = 'usaspending' THEN prime.recipient_county_fips
                ELSE taggs_geo.recipient_county_fips
            END AS recipient_county_fips,
            CASE
                WHEN universe.system_name = 'usaspending' THEN prime.recipient_county_name
                ELSE taggs_geo.recipient_county_name
            END AS recipient_county_name,
            CASE
                WHEN universe.system_name = 'usaspending' THEN prime.recipient_name
                ELSE taggs_geo.recipient_name
            END AS recipient_name,
            COALESCE(
                NULLIF(universe.spending_award_title, ''),
                NULLIF(universe.spending_award_description, ''),
                NULLIF(universe.spending_program_name, ''),
                NULLIF(universe.budget_program, ''),
                NULLIF(universe.budget_program_key, ''),
                'CDC budget-grounded scope row'
            ) AS project_title,
            CASE
                WHEN universe.system_name = 'usaspending' THEN prime.usaspending_permalink
                ELSE NULL::text
            END AS usaspending_permalink
        FROM {BUDGET_SCHEMA}.cdc_budget_grounded_scope_universe_v1 AS universe
        LEFT JOIN {CDC_FUNDING_SCHEMA}.prime_awards AS prime
          ON universe.system_name = 'usaspending'
         AND prime.unique_key = universe.source_record_id
        LEFT JOIN {PLACES_SCHEMA}.dim_state_boundary AS state_dim
          ON state_dim.state_abbr = prime.recipient_state_code
        LEFT JOIN taggs_geo
          ON universe.system_name = 'taggs'
         AND taggs_geo.source_record_id = universe.source_record_id
        """
    )


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_grounded_scope_funding_records_v1")
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_grounded_scope_ui_summary_v1")
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_grounded_scope_universe_excluded_v1")
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_grounded_scope_universe_included_v1")
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_grounded_scope_universe_v1")
    op.drop_index(
        "cdc_budget_grounded_scope_universe_v1_source_record_idx",
        table_name="cdc_budget_grounded_scope_universe_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_grounded_scope_universe_v1_budget_program_key_idx",
        table_name="cdc_budget_grounded_scope_universe_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_grounded_scope_universe_v1_include_idx",
        table_name="cdc_budget_grounded_scope_universe_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_grounded_scope_universe_v1_auto_idx",
        table_name="cdc_budget_grounded_scope_universe_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_grounded_scope_universe_v1_analyst_idx",
        table_name="cdc_budget_grounded_scope_universe_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_grounded_scope_universe_v1_transfer_idx",
        table_name="cdc_budget_grounded_scope_universe_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_grounded_scope_universe_v1_pphf_idx",
        table_name="cdc_budget_grounded_scope_universe_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_grounded_scope_universe_v1_supplemental_idx",
        table_name="cdc_budget_grounded_scope_universe_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_grounded_scope_universe_v1_emergency_idx",
        table_name="cdc_budget_grounded_scope_universe_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_grounded_scope_universe_v1_disc_mand_idx",
        table_name="cdc_budget_grounded_scope_universe_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_grounded_scope_universe_v1_category_idx",
        table_name="cdc_budget_grounded_scope_universe_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_grounded_scope_universe_v1_system_idx",
        table_name="cdc_budget_grounded_scope_universe_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_grounded_scope_universe_v1_fy_idx",
        table_name="cdc_budget_grounded_scope_universe_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_grounded_scope_universe_v1_version_idx",
        table_name="cdc_budget_grounded_scope_universe_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_table("cdc_budget_grounded_scope_universe_v1", schema=BUDGET_SCHEMA)
