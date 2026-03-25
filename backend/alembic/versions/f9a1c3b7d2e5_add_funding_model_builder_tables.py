"""add funding model builder tables

Revision ID: f9a1c3b7d2e5
Revises: f8d2c6b4a901
Create Date: 2026-03-23 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f9a1c3b7d2e5"
down_revision: Union[str, None] = "f8d2c6b4a901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ANALYTICS_SCHEMA = "analytics"
CDC_FUNDING_SCHEMA = "cdc_funding"
RECON_SCHEMA = "recon"
TAGGS_SCHEMA = "taggs"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {ANALYTICS_SCHEMA}")

    op.create_table(
        "funding_profile_models",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("internal_model_id", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("chip_methodology_version", sa.Text(), nullable=False),
        sa.Column("funding_mode_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_user_editable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_visible_in_funding_mode", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("toolbar_page_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.Text(), nullable=False, server_default=sa.text("'system'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("current_version_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("internal_model_id", name="uq_funding_profile_models_internal_model_id"),
        sa.UniqueConstraint("slug", name="uq_funding_profile_models_slug"),
        schema=ANALYTICS_SCHEMA,
    )
    op.create_index(
        "funding_profile_models_status_idx",
        "funding_profile_models",
        ["status"],
        unique=False,
        schema=ANALYTICS_SCHEMA,
    )
    op.create_index(
        "funding_profile_models_mode_key_idx",
        "funding_profile_models",
        ["funding_mode_key"],
        unique=False,
        schema=ANALYTICS_SCHEMA,
    )

    op.create_table(
        "funding_profile_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("profile_model_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("version_label", sa.Text(), nullable=True),
        sa.Column("definition_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("generated_sql", sa.Text(), nullable=True),
        sa.Column("advanced_sql_override", sa.Text(), nullable=True),
        sa.Column("plain_language_summary", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("chip_state_profile_source_version", sa.Text(), nullable=True),
        sa.Column("chip_normalization_source_version", sa.Text(), nullable=True),
        sa.Column("build_script_name", sa.Text(), nullable=True),
        sa.Column("build_status", sa.Text(), nullable=True),
        sa.Column("validation_status", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False, server_default=sa.text("'system'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["profile_model_id"],
            [f"{ANALYTICS_SCHEMA}.funding_profile_models.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_model_id", "version_number", name="uq_funding_profile_versions_model_version"),
        schema=ANALYTICS_SCHEMA,
    )
    op.create_index(
        "funding_profile_versions_build_status_idx",
        "funding_profile_versions",
        ["build_status"],
        unique=False,
        schema=ANALYTICS_SCHEMA,
    )
    op.create_index(
        "funding_profile_versions_validation_status_idx",
        "funding_profile_versions",
        ["validation_status"],
        unique=False,
        schema=ANALYTICS_SCHEMA,
    )

    op.create_foreign_key(
        "fk_funding_profile_models_current_version_id",
        "funding_profile_models",
        "funding_profile_versions",
        ["current_version_id"],
        ["id"],
        source_schema=ANALYTICS_SCHEMA,
        referent_schema=ANALYTICS_SCHEMA,
        ondelete="SET NULL",
    )

    op.create_table(
        "funding_profile_build_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("profile_version_id", sa.Integer(), nullable=False),
        sa.Column("run_type", sa.Text(), nullable=False),
        sa.Column("script_name", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("log_excerpt", sa.Text(), nullable=True),
        sa.Column("output_table_name", sa.Text(), nullable=True),
        sa.Column("output_view_name", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["profile_version_id"],
            [f"{ANALYTICS_SCHEMA}.funding_profile_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=ANALYTICS_SCHEMA,
    )
    op.create_index(
        "funding_profile_build_runs_version_idx",
        "funding_profile_build_runs",
        ["profile_version_id"],
        unique=False,
        schema=ANALYTICS_SCHEMA,
    )
    op.create_index(
        "funding_profile_build_runs_status_idx",
        "funding_profile_build_runs",
        ["status"],
        unique=False,
        schema=ANALYTICS_SCHEMA,
    )

    op.create_table(
        "funding_mode_registry",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("funding_mode_key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("profile_model_id", sa.Integer(), nullable=False),
        sa.Column("profile_version_id", sa.Integer(), nullable=False),
        sa.Column("map_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["profile_model_id"],
            [f"{ANALYTICS_SCHEMA}.funding_profile_models.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_version_id"],
            [f"{ANALYTICS_SCHEMA}.funding_profile_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("funding_mode_key", name="uq_funding_mode_registry_key"),
        schema=ANALYTICS_SCHEMA,
    )
    op.create_index(
        "funding_mode_registry_active_idx",
        "funding_mode_registry",
        ["is_active"],
        unique=False,
        schema=ANALYTICS_SCHEMA,
    )
    op.create_index(
        "funding_mode_registry_sort_idx",
        "funding_mode_registry",
        ["sort_order"],
        unique=False,
        schema=ANALYTICS_SCHEMA,
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {ANALYTICS_SCHEMA}.funding_model_builder_base_v1 AS
        SELECT
            CONCAT('award:', COALESCE(prime.unique_key, prime.id::text)) AS record_key,
            'usaspending_awards'::text AS dataset_key,
            'usaspending'::text AS source_system,
            prime.award_latest_action_date_fiscal_year AS fiscal_year,
            NULL::text AS awarding_agency_name,
            prime.awarding_sub_agency_name AS awarding_subagency_name,
            prime.funding_sub_agency_name AS funding_agency_name,
            prime.recipient_name,
            prime.recipient_state_code,
            prime.recipient_state_name,
            prime.recipient_county_fips AS recipient_county_fips,
            prime.recipient_county_name AS recipient_county_name,
            prime.assistance_type_description AS award_type,
            prime.cfda_program_title AS assistance_listing,
            prime.cfda_program_num AS cfda_number,
            prime.prime_award_base_transaction_description AS program_activity,
            NULL::text AS treasury_account,
            NULL::text AS object_class,
            prime.disaster_emergency_fund_codes_raw AS disaster_emergency_fund_code,
            'award'::text AS transaction_type,
            COALESCE(prime.total_obligated_amount, prime.total_funding_amount, 0)::numeric AS obligation_amount,
            (COALESCE(prime.appropriation_type, '') ILIKE '%emergency%' OR COALESCE(prime.disaster_emergency_fund_codes_raw, '') <> '') AS is_emergency_funding,
            prime.assistance_type_description AS funding_mechanism,
            COALESCE(prime.awarding_sub_agency_name, prime.funding_sub_agency_name, 'USAspending Awards') AS program_area,
            prime.assistance_type_description AS mechanism,
            NULL::text AS recipient_type,
            COALESCE(prime.awarding_sub_agency_name, prime.funding_sub_agency_name, 'USAspending Awards') AS category,
            COALESCE(prime.cfda_program_title, prime.prime_award_base_transaction_description, 'Unclassified') AS subcategory,
            prime.prime_award_base_transaction_description AS project_title,
            prime.usaspending_permalink,
            TRUE AS is_finalized,
            (COALESCE(prime.total_obligated_amount, prime.total_funding_amount, 0) < 0) AS is_deobligation,
            FALSE AS is_pass_through
        FROM {CDC_FUNDING_SCHEMA}.prime_awards AS prime

        UNION ALL

        SELECT
            CONCAT('subaward:', COALESCE(sub.subaward_unique_key, sub.id::text)) AS record_key,
            'usaspending_subawards'::text AS dataset_key,
            'usaspending'::text AS source_system,
            sub.subaward_action_date_fiscal_year AS fiscal_year,
            NULL::text AS awarding_agency_name,
            sub.prime_award_awarding_sub_agency_name AS awarding_subagency_name,
            sub.prime_award_funding_sub_agency_name AS funding_agency_name,
            sub.subawardee_name AS recipient_name,
            sub.subawardee_state_code AS recipient_state_code,
            sub.subawardee_state_name AS recipient_state_name,
            sub.subawardee_county_fips AS recipient_county_fips,
            NULL::text AS recipient_county_name,
            sub.subaward_description AS award_type,
            NULL::text AS assistance_listing,
            NULL::text AS cfda_number,
            sub.prime_award_base_transaction_description AS program_activity,
            NULL::text AS treasury_account,
            NULL::text AS object_class,
            sub.prime_award_disaster_emergency_fund_codes_raw AS disaster_emergency_fund_code,
            'subaward'::text AS transaction_type,
            COALESCE(sub.subaward_amount, 0)::numeric AS obligation_amount,
            (COALESCE(sub.appropriation_type, '') ILIKE '%emergency%' OR COALESCE(sub.prime_award_disaster_emergency_fund_codes_raw, '') <> '') AS is_emergency_funding,
            sub.subaward_description AS funding_mechanism,
            COALESCE(sub.prime_award_awarding_sub_agency_name, sub.prime_award_funding_sub_agency_name, 'USAspending Subawards') AS program_area,
            sub.subaward_description AS mechanism,
            NULL::text AS recipient_type,
            COALESCE(sub.prime_award_awarding_sub_agency_name, sub.prime_award_funding_sub_agency_name, 'USAspending Subawards') AS category,
            COALESCE(sub.prime_award_base_transaction_description, sub.subaward_description, 'Unclassified') AS subcategory,
            sub.subaward_description AS project_title,
            sub.usaspending_permalink,
            TRUE AS is_finalized,
            (COALESCE(sub.subaward_amount, 0) < 0) AS is_deobligation,
            FALSE AS is_pass_through
        FROM {CDC_FUNDING_SCHEMA}.subawards AS sub

        UNION ALL

        SELECT
            CONCAT('assistance_tx:', tx.source_transaction_id) AS record_key,
            'usaspending_transactions'::text AS dataset_key,
            'usaspending_assistance'::text AS source_system,
            tx.fiscal_year,
            tx.awarding_agency_name,
            NULL::text AS awarding_subagency_name,
            tx.funding_agency_name,
            tx.recipient_name,
            tx.state_code AS recipient_state_code,
            NULL::text AS recipient_state_name,
            NULL::text AS recipient_county_fips,
            NULL::text AS recipient_county_name,
            tx.assistance_listing_title AS award_type,
            tx.assistance_listing_title AS assistance_listing,
            tx.assistance_listing_number AS cfda_number,
            tx.program_activity_name AS program_activity,
            tx.treasury_account_symbol AS treasury_account,
            NULL::text AS object_class,
            tx.disaster_emergency_fund_code,
            'transaction'::text AS transaction_type,
            COALESCE(tx.transaction_obligated_amount, 0)::numeric AS obligation_amount,
            (COALESCE(tx.appropriation_type, '') ILIKE '%emergency%' OR COALESCE(tx.disaster_emergency_fund_code, '') <> '') AS is_emergency_funding,
            tx.effective_funding_stream AS funding_mechanism,
            COALESCE(tx.effective_funding_scope, tx.effective_funding_stream, 'USAspending Transactions') AS program_area,
            tx.effective_funding_stream AS mechanism,
            NULL::text AS recipient_type,
            COALESCE(tx.effective_funding_scope, 'USAspending Transactions') AS category,
            COALESCE(tx.effective_funding_stream, tx.program_activity_name, 'Unclassified') AS subcategory,
            COALESCE(tx.assistance_listing_title, tx.program_activity_name, 'Unclassified') AS project_title,
            NULL::text AS usaspending_permalink,
            TRUE AS is_finalized,
            (COALESCE(tx.transaction_obligated_amount, 0) < 0) AS is_deobligation,
            FALSE AS is_pass_through
        FROM {RECON_SCHEMA}.assistance_transactions_profile_enriched AS tx

        UNION ALL

        SELECT
            CONCAT('contract_tx:', tx.source_transaction_id) AS record_key,
            'usaspending_transactions'::text AS dataset_key,
            'usaspending_contracts'::text AS source_system,
            tx.fiscal_year,
            tx.awarding_agency_name,
            NULL::text AS awarding_subagency_name,
            tx.funding_agency_name,
            tx.recipient_name,
            tx.state_code AS recipient_state_code,
            NULL::text AS recipient_state_name,
            NULL::text AS recipient_county_fips,
            NULL::text AS recipient_county_name,
            'contract'::text AS award_type,
            NULL::text AS assistance_listing,
            NULL::text AS cfda_number,
            tx.award_description AS program_activity,
            tx.treasury_account_symbol AS treasury_account,
            tx.product_or_service_code AS object_class,
            tx.disaster_emergency_fund_code,
            'transaction'::text AS transaction_type,
            COALESCE(tx.transaction_obligated_amount, 0)::numeric AS obligation_amount,
            (COALESCE(tx.appropriation_type, '') ILIKE '%emergency%' OR COALESCE(tx.disaster_emergency_fund_code, '') <> '') AS is_emergency_funding,
            tx.effective_funding_stream AS funding_mechanism,
            COALESCE(tx.effective_funding_scope, tx.effective_funding_stream, 'USAspending Transactions') AS program_area,
            tx.effective_funding_stream AS mechanism,
            NULL::text AS recipient_type,
            COALESCE(tx.effective_funding_scope, 'USAspending Transactions') AS category,
            COALESCE(tx.effective_funding_stream, tx.award_description, 'Unclassified') AS subcategory,
            COALESCE(tx.award_description, 'Unclassified') AS project_title,
            NULL::text AS usaspending_permalink,
            TRUE AS is_finalized,
            (COALESCE(tx.transaction_obligated_amount, 0) < 0) AS is_deobligation,
            FALSE AS is_pass_through
        FROM {RECON_SCHEMA}.contract_transactions_profile_enriched AS tx

        UNION ALL

        SELECT
            CONCAT('taggs:', COALESCE(taggs.award_number, taggs.id::text), ':', taggs.funding_fiscal_year::text) AS record_key,
            'taggs'::text AS dataset_key,
            'taggs'::text AS source_system,
            taggs.funding_fiscal_year AS fiscal_year,
            taggs.opdiv AS awarding_agency_name,
            taggs.program_office AS awarding_subagency_name,
            taggs.opdiv AS funding_agency_name,
            taggs.legal_entity_name AS recipient_name,
            taggs.legal_entity_state_normalized AS recipient_state_code,
            NULL::text AS recipient_state_name,
            NULL::text AS recipient_county_fips,
            taggs.legal_entity_county_normalized AS recipient_county_name,
            taggs.award_title AS award_type,
            taggs.assistance_listing_title AS assistance_listing,
            taggs.aln AS cfda_number,
            taggs.program_office AS program_activity,
            taggs.can_code AS treasury_account,
            NULL::text AS object_class,
            NULL::text AS disaster_emergency_fund_code,
            'award'::text AS transaction_type,
            COALESCE(taggs.total_sum_of_actions, 0)::numeric AS obligation_amount,
            (COALESCE(taggs.appropriation_type, '') ILIKE '%emergency%') AS is_emergency_funding,
            taggs.funding_stream AS funding_mechanism,
            COALESCE(taggs.effective_category, taggs.program_office, 'TAGGS') AS program_area,
            taggs.funding_stream AS mechanism,
            NULL::text AS recipient_type,
            COALESCE(taggs.effective_category, 'TAGGS') AS category,
            COALESCE(taggs.effective_subcategory, taggs.effective_program_name, 'Unclassified') AS subcategory,
            COALESCE(taggs.award_title, taggs.award_description, 'Unclassified') AS project_title,
            NULL::text AS usaspending_permalink,
            TRUE AS is_finalized,
            (COALESCE(taggs.total_sum_of_actions, 0) < 0) AS is_deobligation,
            FALSE AS is_pass_through
        FROM {TAGGS_SCHEMA}.award_funding_summary AS taggs
        """
    )


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {ANALYTICS_SCHEMA}.funding_model_builder_base_v1")
    op.drop_index("funding_mode_registry_sort_idx", table_name="funding_mode_registry", schema=ANALYTICS_SCHEMA)
    op.drop_index("funding_mode_registry_active_idx", table_name="funding_mode_registry", schema=ANALYTICS_SCHEMA)
    op.drop_table("funding_mode_registry", schema=ANALYTICS_SCHEMA)
    op.drop_index("funding_profile_build_runs_status_idx", table_name="funding_profile_build_runs", schema=ANALYTICS_SCHEMA)
    op.drop_index("funding_profile_build_runs_version_idx", table_name="funding_profile_build_runs", schema=ANALYTICS_SCHEMA)
    op.drop_table("funding_profile_build_runs", schema=ANALYTICS_SCHEMA)
    op.drop_constraint(
        "fk_funding_profile_models_current_version_id",
        "funding_profile_models",
        schema=ANALYTICS_SCHEMA,
        type_="foreignkey",
    )
    op.drop_index("funding_profile_versions_validation_status_idx", table_name="funding_profile_versions", schema=ANALYTICS_SCHEMA)
    op.drop_index("funding_profile_versions_build_status_idx", table_name="funding_profile_versions", schema=ANALYTICS_SCHEMA)
    op.drop_table("funding_profile_versions", schema=ANALYTICS_SCHEMA)
    op.drop_index("funding_profile_models_mode_key_idx", table_name="funding_profile_models", schema=ANALYTICS_SCHEMA)
    op.drop_index("funding_profile_models_status_idx", table_name="funding_profile_models", schema=ANALYTICS_SCHEMA)
    op.drop_table("funding_profile_models", schema=ANALYTICS_SCHEMA)
