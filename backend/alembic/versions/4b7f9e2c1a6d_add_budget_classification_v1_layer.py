"""add budget classification v1 layer

Revision ID: 4b7f9e2c1a6d
Revises: 3e2f4a9c1b77
Create Date: 2026-04-05 15:20:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "4b7f9e2c1a6d"
down_revision: Union[str, None] = "3e2f4a9c1b77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BUDGET_SCHEMA = "budget"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {BUDGET_SCHEMA}")

    op.create_table(
        "cdc_budget_classification_v1",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("raw_budget_id", sa.BigInteger(), nullable=False),
        sa.Column("unique_id", sa.Text(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("source_file", sa.Text(), nullable=False),
        sa.Column("source_sheet", sa.Text(), nullable=False),
        sa.Column("classification_version", sa.Text(), nullable=False),
        sa.Column("classification_method", sa.Text(), nullable=False),
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("classification_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency", sa.Text(), nullable=True),
        sa.Column("sub_agency", sa.Text(), nullable=True),
        sa.Column("program", sa.Text(), nullable=True),
        sa.Column("sub_program", sa.Text(), nullable=True),
        sa.Column("sub_program_2", sa.Text(), nullable=True),
        sa.Column("sub_program_3", sa.Text(), nullable=True),
        sa.Column("budget_source", sa.Text(), nullable=True),
        sa.Column("budget_stage", sa.Text(), nullable=True),
        sa.Column("granularity", sa.Text(), nullable=True),
        sa.Column("amount_millions", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("amount_dollars", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("funding_type", sa.Text(), nullable=True),
        sa.Column("program_status", sa.Text(), nullable=True),
        sa.Column("is_non_add", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("verified", sa.Text(), nullable=True),
        sa.Column("crosswalk_note", sa.Text(), nullable=True),
        sa.Column("source_id", sa.Text(), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("norm_program", sa.Text(), nullable=True),
        sa.Column("norm_sub_program", sa.Text(), nullable=True),
        sa.Column("norm_sub_program_2", sa.Text(), nullable=True),
        sa.Column("norm_sub_program_3", sa.Text(), nullable=True),
        sa.Column("norm_funding_type", sa.Text(), nullable=True),
        sa.Column("norm_budget_source", sa.Text(), nullable=True),
        sa.Column("norm_budget_stage", sa.Text(), nullable=True),
        sa.Column("norm_program_status", sa.Text(), nullable=True),
        sa.Column("norm_notes", sa.Text(), nullable=True),
        sa.Column("norm_crosswalk_note", sa.Text(), nullable=True),
        sa.Column("signal_budget_stage_enacted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_budget_stage_operating_plan", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_budget_stage_request", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_funding_type_discretionary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_funding_type_mandatory", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_non_add", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_keyword_pphf", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_keyword_supplemental", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_keyword_emergency", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_keyword_transfer", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_keyword_reprogramming", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_keyword_total", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_keyword_subtotal", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_keyword_base", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_keyword_prevention_fund", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_keyword_covid", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_keyword_arp", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_keyword_cares", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_keyword_rescue_plan", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_keyword_nonrecurring", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_program_has_substructure", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_record_is_leaf_like", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signal_program_repeats_across_years", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("program_year_count", sa.Integer(), nullable=True),
        sa.Column("program_first_year", sa.Integer(), nullable=True),
        sa.Column("program_last_year", sa.Integer(), nullable=True),
        sa.Column("appropriation_category", sa.Text(), nullable=False),
        sa.Column("appropriation_subtype", sa.Text(), nullable=True),
        sa.Column("is_regular_appropriation", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("classification_confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("primary_rule_code", sa.Text(), nullable=True),
        sa.Column("supporting_rule_codes", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("rule_explanation", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "appropriation_category IN ("
            "'REGULAR', 'PPHF', 'SUPPLEMENTAL', 'TRANSFER', 'NON_ADD', "
            "'REQUEST_ONLY', 'MANDATORY', 'TOTAL_OR_SUBTOTAL', 'UNKNOWN'"
            ")",
            name="ck_cdc_budget_classification_v1_category",
        ),
        sa.CheckConstraint(
            "classification_confidence >= 0 AND classification_confidence <= 1",
            name="ck_cdc_budget_classification_v1_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["raw_budget_id"],
            [f"{BUDGET_SCHEMA}.cdc_budget_tracker_raw.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "raw_budget_id",
            "classification_version",
            name="uq_cdc_budget_classification_v1_raw_version",
        ),
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_classification_v1_fiscal_year_idx",
        "cdc_budget_classification_v1",
        ["fiscal_year"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_classification_v1_category_idx",
        "cdc_budget_classification_v1",
        ["appropriation_category"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_classification_v1_regular_idx",
        "cdc_budget_classification_v1",
        ["is_regular_appropriation"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_classification_v1_sub_agency_idx",
        "cdc_budget_classification_v1",
        ["sub_agency"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_classification_v1_budget_stage_idx",
        "cdc_budget_classification_v1",
        ["budget_stage"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_classification_v1_budget_source_idx",
        "cdc_budget_classification_v1",
        ["budget_source"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_classification_v1_funding_type_idx",
        "cdc_budget_classification_v1",
        ["funding_type"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_classification_v1_primary_rule_idx",
        "cdc_budget_classification_v1",
        ["primary_rule_code"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )

    op.create_table(
        "cdc_budget_classification_rule_registry",
        sa.Column("rule_code", sa.Text(), nullable=False),
        sa.Column("classification_version", sa.Text(), nullable=False),
        sa.Column("rule_group", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category_output", sa.Text(), nullable=True),
        sa.Column("subtype_output", sa.Text(), nullable=True),
        sa.Column("confidence_output", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "confidence_output IS NULL OR (confidence_output >= 0 AND confidence_output <= 1)",
            name="ck_cdc_budget_classification_rule_registry_confidence",
        ),
        sa.PrimaryKeyConstraint("rule_code"),
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_classification_rule_registry_version_priority_idx",
        "cdc_budget_classification_rule_registry",
        ["classification_version", "priority"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_classification_rule_registry_active_idx",
        "cdc_budget_classification_rule_registry",
        ["is_active"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_regular_appropriations_v1 AS
        SELECT
            raw_budget_id,
            unique_id,
            fiscal_year,
            agency,
            sub_agency,
            program,
            sub_program,
            sub_program_2,
            sub_program_3,
            budget_source,
            budget_stage,
            granularity,
            amount_millions,
            amount_dollars,
            funding_type,
            appropriation_category,
            appropriation_subtype,
            classification_confidence,
            primary_rule_code,
            rule_explanation,
            source_id,
            source_page
        FROM {BUDGET_SCHEMA}.cdc_budget_classification_v1
        WHERE classification_version = 'v1_regular_appropriations'
          AND is_regular_appropriation = TRUE
        """
    )
    op.execute(
        f"""
        CREATE MATERIALIZED VIEW {BUDGET_SCHEMA}.mv_cdc_budget_classification_v1_summary AS
        SELECT
            classification_version,
            fiscal_year,
            appropriation_category,
            appropriation_subtype,
            is_regular_appropriation,
            COUNT(*)::bigint AS record_count,
            COALESCE(SUM(amount_dollars), 0)::numeric(20, 2) AS total_amount_dollars
        FROM {BUDGET_SCHEMA}.cdc_budget_classification_v1
        GROUP BY
            classification_version,
            fiscal_year,
            appropriation_category,
            appropriation_subtype,
            is_regular_appropriation
        WITH NO DATA
        """
    )
    op.create_index(
        "cdc_budget_classification_v1_summary_lookup_idx",
        "mv_cdc_budget_classification_v1_summary",
        [
            "classification_version",
            "fiscal_year",
            "appropriation_category",
            "appropriation_subtype",
            "is_regular_appropriation",
        ],
        unique=False,
        schema=BUDGET_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "cdc_budget_classification_v1_summary_lookup_idx",
        table_name="mv_cdc_budget_classification_v1_summary",
        schema=BUDGET_SCHEMA,
    )
    op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {BUDGET_SCHEMA}.mv_cdc_budget_classification_v1_summary")
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_regular_appropriations_v1")

    op.drop_index(
        "cdc_budget_classification_rule_registry_active_idx",
        table_name="cdc_budget_classification_rule_registry",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_classification_rule_registry_version_priority_idx",
        table_name="cdc_budget_classification_rule_registry",
        schema=BUDGET_SCHEMA,
    )
    op.drop_table("cdc_budget_classification_rule_registry", schema=BUDGET_SCHEMA)

    op.drop_index(
        "cdc_budget_classification_v1_primary_rule_idx",
        table_name="cdc_budget_classification_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_classification_v1_funding_type_idx",
        table_name="cdc_budget_classification_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_classification_v1_budget_source_idx",
        table_name="cdc_budget_classification_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_classification_v1_budget_stage_idx",
        table_name="cdc_budget_classification_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_classification_v1_sub_agency_idx",
        table_name="cdc_budget_classification_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_classification_v1_regular_idx",
        table_name="cdc_budget_classification_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_classification_v1_category_idx",
        table_name="cdc_budget_classification_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_classification_v1_fiscal_year_idx",
        table_name="cdc_budget_classification_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_table("cdc_budget_classification_v1", schema=BUDGET_SCHEMA)
