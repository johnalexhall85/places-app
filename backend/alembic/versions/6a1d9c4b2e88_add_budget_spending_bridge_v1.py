"""add budget spending bridge v1

Revision ID: 6a1d9c4b2e88
Revises: 4b7f9e2c1a6d
Create Date: 2026-04-05 18:40:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "6a1d9c4b2e88"
down_revision: Union[str, None] = "4b7f9e2c1a6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BUDGET_SCHEMA = "budget"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {BUDGET_SCHEMA}")

    op.create_table(
        "cdc_budget_spending_bridge_v1",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("bridge_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bridge_version", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
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
        sa.Column("is_regular_appropriation", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("classification_confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("primary_rule_code", sa.Text(), nullable=True),
        sa.Column("system_name", sa.Text(), nullable=False),
        sa.Column("source_table", sa.Text(), nullable=False),
        sa.Column("source_record_id", sa.Text(), nullable=False),
        sa.Column("source_parent_record_id", sa.Text(), nullable=True),
        sa.Column("source_fiscal_year", sa.Integer(), nullable=True),
        sa.Column("match_rule_code", sa.Text(), nullable=False),
        sa.Column("match_tier", sa.Text(), nullable=False),
        sa.Column("match_type", sa.Text(), nullable=False),
        sa.Column("match_score", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("match_confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("confidence_band", sa.Text(), nullable=False),
        sa.Column("is_auto_accepted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_excluded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("exclusion_reason", sa.Text(), nullable=True),
        sa.Column("match_explanation", sa.Text(), nullable=False),
        sa.Column("matched_on_fields", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("budget_side_values", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("spending_side_values", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("review_status", sa.Text(), nullable=False, server_default=sa.text("'unreviewed'")),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("allocation_pct", sa.Numeric(precision=8, scale=6), nullable=True),
        sa.Column("allocation_method", sa.Text(), nullable=True),
        sa.Column("allocation_notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "system_name IN ('usaspending', 'taggs')",
            name="ck_cdc_budget_spending_bridge_v1_system_name",
        ),
        sa.CheckConstraint(
            "match_tier IN ('TIER_A_DETERMINISTIC', 'TIER_B_STRUCTURED', 'TIER_C_FUZZY_CANDIDATE')",
            name="ck_cdc_budget_spending_bridge_v1_match_tier",
        ),
        sa.CheckConstraint(
            "confidence_band IN ('HIGH', 'MEDIUM', 'LOW')",
            name="ck_cdc_budget_spending_bridge_v1_confidence_band",
        ),
        sa.CheckConstraint(
            "review_status IN ('unreviewed', 'accepted', 'rejected', 'needs_review')",
            name="ck_cdc_budget_spending_bridge_v1_review_status",
        ),
        sa.CheckConstraint(
            "match_score >= 0 AND match_score <= 1",
            name="ck_cdc_budget_spending_bridge_v1_match_score",
        ),
        sa.CheckConstraint(
            "match_confidence >= 0 AND match_confidence <= 1",
            name="ck_cdc_budget_spending_bridge_v1_match_confidence",
        ),
        sa.CheckConstraint(
            "allocation_pct IS NULL OR (allocation_pct >= 0 AND allocation_pct <= 1)",
            name="ck_cdc_budget_spending_bridge_v1_allocation_pct",
        ),
        sa.ForeignKeyConstraint(
            ["classification_id"],
            [f"{BUDGET_SCHEMA}.cdc_budget_classification_v1.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["raw_budget_id"],
            [f"{BUDGET_SCHEMA}.cdc_budget_tracker_raw.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "bridge_version",
            "budget_anchor_id",
            "system_name",
            "source_record_id",
            "match_type",
            name="uq_cdc_budget_spending_bridge_v1_key",
        ),
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spending_bridge_v1_fiscal_year_idx",
        "cdc_budget_spending_bridge_v1",
        ["fiscal_year"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spending_bridge_v1_system_name_idx",
        "cdc_budget_spending_bridge_v1",
        ["system_name"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spending_bridge_v1_category_idx",
        "cdc_budget_spending_bridge_v1",
        ["appropriation_category"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spending_bridge_v1_regular_idx",
        "cdc_budget_spending_bridge_v1",
        ["is_regular_appropriation"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spending_bridge_v1_match_tier_idx",
        "cdc_budget_spending_bridge_v1",
        ["match_tier"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spending_bridge_v1_confidence_band_idx",
        "cdc_budget_spending_bridge_v1",
        ["confidence_band"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spending_bridge_v1_review_status_idx",
        "cdc_budget_spending_bridge_v1",
        ["review_status"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spending_bridge_v1_source_record_idx",
        "cdc_budget_spending_bridge_v1",
        ["source_record_id"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spending_bridge_v1_budget_program_key_idx",
        "cdc_budget_spending_bridge_v1",
        ["budget_program_key"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spending_bridge_v1_match_rule_code_idx",
        "cdc_budget_spending_bridge_v1",
        ["match_rule_code"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spending_bridge_v1_budget_anchor_idx",
        "cdc_budget_spending_bridge_v1",
        ["budget_anchor_id"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )

    op.create_table(
        "cdc_budget_spending_bridge_rule_registry",
        sa.Column("rule_code", sa.Text(), nullable=False),
        sa.Column("bridge_version", sa.Text(), nullable=False),
        sa.Column("rule_group", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("system_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("match_type", sa.Text(), nullable=False),
        sa.Column("default_match_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("default_match_confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("default_confidence_band", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "tier IN ('TIER_A_DETERMINISTIC', 'TIER_B_STRUCTURED', 'TIER_C_FUZZY_CANDIDATE')",
            name="ck_cdc_budget_spending_bridge_rule_registry_tier",
        ),
        sa.CheckConstraint(
            "system_name IN ('usaspending', 'taggs')",
            name="ck_cdc_budget_spending_bridge_rule_registry_system_name",
        ),
        sa.CheckConstraint(
            "default_match_score IS NULL OR (default_match_score >= 0 AND default_match_score <= 1)",
            name="ck_cdc_budget_spending_bridge_rule_registry_score",
        ),
        sa.CheckConstraint(
            "default_match_confidence IS NULL OR (default_match_confidence >= 0 AND default_match_confidence <= 1)",
            name="ck_cdc_budget_spending_bridge_rule_registry_confidence",
        ),
        sa.CheckConstraint(
            "default_confidence_band IS NULL OR default_confidence_band IN ('HIGH', 'MEDIUM', 'LOW')",
            name="ck_cdc_budget_spending_bridge_rule_registry_confidence_band",
        ),
        sa.PrimaryKeyConstraint("rule_code"),
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spending_bridge_rule_registry_version_priority_idx",
        "cdc_budget_spending_bridge_rule_registry",
        ["bridge_version", "priority"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spending_bridge_rule_registry_active_idx",
        "cdc_budget_spending_bridge_rule_registry",
        ["is_active"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_anchor_v1 AS
        SELECT
            c.id::text AS budget_anchor_id,
            c.id AS classification_id,
            c.raw_budget_id,
            c.unique_id,
            c.fiscal_year,
            c.agency,
            c.sub_agency,
            c.program,
            c.sub_program,
            c.sub_program_2,
            c.sub_program_3,
            c.budget_source,
            c.budget_stage,
            c.granularity,
            c.amount_millions,
            c.amount_dollars,
            c.funding_type,
            c.appropriation_category,
            c.appropriation_subtype,
            c.is_regular_appropriation,
            c.classification_confidence,
            c.primary_rule_code,
            c.rule_explanation,
            c.source_id,
            c.source_page,
            c.norm_program,
            c.norm_sub_program,
            c.norm_sub_program_2,
            c.norm_sub_program_3,
            CONCAT_WS(
                ' > ',
                NULLIF(c.norm_program, ''),
                NULLIF(c.norm_sub_program, ''),
                NULLIF(c.norm_sub_program_2, ''),
                NULLIF(c.norm_sub_program_3, '')
            ) AS norm_program_path,
            c.norm_budget_stage,
            c.norm_funding_type,
            CONCAT_WS(
                ' > ',
                NULLIF(c.norm_program, ''),
                NULLIF(c.norm_sub_program, ''),
                NULLIF(c.norm_sub_program_2, ''),
                NULLIF(c.norm_sub_program_3, '')
            ) AS budget_program_key
        FROM {BUDGET_SCHEMA}.cdc_budget_classification_v1 AS c
        WHERE c.classification_version = 'v1_regular_appropriations'
          AND c.appropriation_category IN ('REGULAR', 'PPHF', 'SUPPLEMENTAL', 'TRANSFER', 'MANDATORY')
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_spending_bridge_v1 AS
        SELECT
            b.id,
            b.bridge_batch_id,
            b.bridge_version,
            b.created_at,
            b.updated_at,
            b.budget_anchor_id,
            b.classification_id,
            b.raw_budget_id,
            b.unique_id,
            b.fiscal_year,
            b.budget_agency,
            b.budget_sub_agency,
            b.budget_program,
            b.budget_sub_program,
            b.budget_sub_program_2,
            b.budget_sub_program_3,
            b.budget_program_key,
            b.appropriation_category,
            b.appropriation_subtype,
            b.is_regular_appropriation,
            b.classification_confidence,
            b.primary_rule_code,
            b.system_name,
            b.source_table,
            b.source_record_id,
            b.source_parent_record_id,
            b.source_fiscal_year,
            b.match_rule_code,
            b.match_tier,
            b.match_type,
            b.match_score,
            b.match_confidence,
            b.confidence_band,
            b.is_auto_accepted,
            b.is_excluded,
            b.exclusion_reason,
            b.match_explanation,
            b.matched_on_fields,
            b.review_status,
            b.review_notes,
            b.allocation_pct,
            b.allocation_method,
            b.allocation_notes,
            COALESCE(
                b.spending_side_values->>'effective_program_name',
                b.spending_side_values->>'funding_stream',
                b.spending_side_values->>'cfda_program_title',
                b.spending_side_values->>'assistance_listing_title',
                b.spending_side_values->>'award_title'
            ) AS spending_program_name,
            COALESCE(
                b.spending_side_values->>'assistance_listing_title',
                b.spending_side_values->>'cfda_program_title'
            ) AS spending_assistance_listing_title,
            COALESCE(
                b.spending_side_values->>'aln',
                b.spending_side_values->>'assistance_listing_number'
            ) AS spending_aln,
            b.spending_side_values->>'can_code' AS spending_can_code,
            b.spending_side_values->>'program_office' AS spending_program_office,
            b.spending_side_values->>'award_title' AS spending_award_title,
            b.spending_side_values->>'award_description' AS spending_award_description,
            b.spending_side_values->>'appropriation_type' AS spending_appropriation_type,
            b.spending_side_values->'federal_account_symbols' AS spending_federal_account_symbols,
            b.budget_side_values,
            b.spending_side_values
        FROM {BUDGET_SCHEMA}.cdc_budget_spending_bridge_v1 AS b
        WHERE b.bridge_version = 'v1_budget_spending_bridge'
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_spending_bridge_high_confidence_v1 AS
        SELECT *
        FROM {BUDGET_SCHEMA}.v_cdc_budget_spending_bridge_v1
        WHERE confidence_band = 'HIGH'
          AND is_excluded = FALSE
        """
    )


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_spending_bridge_high_confidence_v1")
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_spending_bridge_v1")
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_anchor_v1")

    op.drop_index(
        "cdc_budget_spending_bridge_rule_registry_active_idx",
        table_name="cdc_budget_spending_bridge_rule_registry",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spending_bridge_rule_registry_version_priority_idx",
        table_name="cdc_budget_spending_bridge_rule_registry",
        schema=BUDGET_SCHEMA,
    )
    op.drop_table("cdc_budget_spending_bridge_rule_registry", schema=BUDGET_SCHEMA)

    op.drop_index(
        "cdc_budget_spending_bridge_v1_budget_anchor_idx",
        table_name="cdc_budget_spending_bridge_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spending_bridge_v1_match_rule_code_idx",
        table_name="cdc_budget_spending_bridge_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spending_bridge_v1_budget_program_key_idx",
        table_name="cdc_budget_spending_bridge_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spending_bridge_v1_source_record_idx",
        table_name="cdc_budget_spending_bridge_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spending_bridge_v1_review_status_idx",
        table_name="cdc_budget_spending_bridge_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spending_bridge_v1_confidence_band_idx",
        table_name="cdc_budget_spending_bridge_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spending_bridge_v1_match_tier_idx",
        table_name="cdc_budget_spending_bridge_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spending_bridge_v1_regular_idx",
        table_name="cdc_budget_spending_bridge_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spending_bridge_v1_category_idx",
        table_name="cdc_budget_spending_bridge_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spending_bridge_v1_system_name_idx",
        table_name="cdc_budget_spending_bridge_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spending_bridge_v1_fiscal_year_idx",
        table_name="cdc_budget_spending_bridge_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_table("cdc_budget_spending_bridge_v1", schema=BUDGET_SCHEMA)
