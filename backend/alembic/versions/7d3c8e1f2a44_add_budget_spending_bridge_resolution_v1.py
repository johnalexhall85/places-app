"""add budget spending bridge resolution v1

Revision ID: 7d3c8e1f2a44
Revises: 6a1d9c4b2e88
Create Date: 2026-04-05 22:10:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "7d3c8e1f2a44"
down_revision: Union[str, None] = "6a1d9c4b2e88"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BUDGET_SCHEMA = "budget"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {BUDGET_SCHEMA}")

    op.create_table(
        "cdc_budget_spending_bridge_resolution_v1",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("resolution_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resolution_version", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("bridge_id", sa.BigInteger(), nullable=False),
        sa.Column("resolution_rule_code", sa.Text(), nullable=True),
        sa.Column("bridge_version", sa.Text(), nullable=False),
        sa.Column("budget_anchor_id", sa.Text(), nullable=False),
        sa.Column("classification_id", sa.BigInteger(), nullable=False),
        sa.Column("raw_budget_id", sa.BigInteger(), nullable=False),
        sa.Column("unique_id", sa.Text(), nullable=False),
        sa.Column("system_name", sa.Text(), nullable=False),
        sa.Column("source_record_id", sa.Text(), nullable=False),
        sa.Column("match_tier", sa.Text(), nullable=False),
        sa.Column("match_type", sa.Text(), nullable=False),
        sa.Column("match_score", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("match_confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("confidence_band", sa.Text(), nullable=False),
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
        sa.Column("resolution_status", sa.Text(), nullable=False),
        sa.Column("scope_include_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("allocation_pct", sa.Numeric(precision=8, scale=6), nullable=True),
        sa.Column("allocation_method", sa.Text(), nullable=True),
        sa.Column("resolution_method", sa.Text(), nullable=False),
        sa.Column("resolution_confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("resolution_priority", sa.Integer(), nullable=True),
        sa.Column("auto_seeded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("analyst_reviewed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("resolution_reason_code", sa.Text(), nullable=True),
        sa.Column("resolution_explanation", sa.Text(), nullable=False),
        sa.Column("reviewer_name", sa.Text(), nullable=True),
        sa.Column("reviewer_email", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("supersedes_resolution_id", sa.BigInteger(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint(
            "system_name IN ('usaspending', 'taggs')",
            name="ck_cdc_budget_spend_bridge_res_v1_system",
        ),
        sa.CheckConstraint(
            "match_tier IN ('TIER_A_DETERMINISTIC', 'TIER_B_STRUCTURED', 'TIER_C_FUZZY_CANDIDATE')",
            name="ck_cdc_budget_spend_bridge_res_v1_tier",
        ),
        sa.CheckConstraint(
            "confidence_band IN ('HIGH', 'MEDIUM', 'LOW')",
            name="ck_cdc_budget_spend_bridge_res_v1_band",
        ),
        sa.CheckConstraint(
            "resolution_status IN ('accepted', 'rejected', 'accepted_partial', 'superseded', 'unresolved')",
            name="ck_cdc_budget_spend_bridge_res_v1_status",
        ),
        sa.CheckConstraint(
            "resolution_method IN ('analyst', 'auto_seed', 'overlay', 'manual_sql')",
            name="ck_cdc_budget_spend_bridge_res_v1_method",
        ),
        sa.CheckConstraint(
            "match_score >= 0 AND match_score <= 1",
            name="ck_cdc_budget_spend_bridge_res_v1_match_score",
        ),
        sa.CheckConstraint(
            "match_confidence >= 0 AND match_confidence <= 1",
            name="ck_cdc_budget_spend_bridge_res_v1_match_conf",
        ),
        sa.CheckConstraint(
            "resolution_confidence IS NULL OR (resolution_confidence >= 0 AND resolution_confidence <= 1)",
            name="ck_cdc_budget_spend_bridge_res_v1_res_conf",
        ),
        sa.CheckConstraint(
            "allocation_pct IS NULL OR (allocation_pct >= 0 AND allocation_pct <= 1)",
            name="ck_cdc_budget_spend_bridge_res_v1_alloc",
        ),
        sa.CheckConstraint(
            "(resolution_status = 'accepted' AND allocation_pct IS NOT NULL) "
            "OR (resolution_status <> 'accepted' AND allocation_pct IS NULL) "
            "OR resolution_status = 'accepted_partial'",
            name="ck_cdc_budget_spend_bridge_res_v1_accept_alloc",
        ),
        sa.CheckConstraint(
            "resolution_status <> 'accepted_partial' "
            "OR (allocation_pct IS NOT NULL AND allocation_pct > 0 AND allocation_pct < 1)",
            name="ck_cdc_budget_spend_bridge_res_v1_partial_alloc",
        ),
        sa.CheckConstraint(
            "resolution_status <> 'accepted' OR allocation_pct = 1",
            name="ck_cdc_budget_spend_bridge_res_v1_full_alloc",
        ),
        sa.CheckConstraint(
            "(resolution_status IN ('accepted', 'accepted_partial') AND scope_include_flag = TRUE) "
            "OR (resolution_status NOT IN ('accepted', 'accepted_partial') AND scope_include_flag = FALSE)",
            name="ck_cdc_budget_spend_bridge_res_v1_scope_flag",
        ),
        sa.ForeignKeyConstraint(
            ["bridge_id"],
            [f"{BUDGET_SCHEMA}.cdc_budget_spending_bridge_v1.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_resolution_id"],
            [f"{BUDGET_SCHEMA}.cdc_budget_spending_bridge_resolution_v1.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "uq_cdc_budget_spend_bridge_res_v1_current",
        "cdc_budget_spending_bridge_resolution_v1",
        ["resolution_version", "bridge_id"],
        unique=True,
        schema=BUDGET_SCHEMA,
        postgresql_where=sa.text("is_current"),
    )
    op.create_index(
        "cdc_budget_spend_bridge_res_v1_current_idx",
        "cdc_budget_spending_bridge_resolution_v1",
        ["resolution_version", "is_current"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spend_bridge_res_v1_bridge_idx",
        "cdc_budget_spending_bridge_resolution_v1",
        ["bridge_id"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spend_bridge_res_v1_anchor_idx",
        "cdc_budget_spending_bridge_resolution_v1",
        ["budget_anchor_id"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spend_bridge_res_v1_system_idx",
        "cdc_budget_spending_bridge_resolution_v1",
        ["system_name"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spend_bridge_res_v1_category_idx",
        "cdc_budget_spending_bridge_resolution_v1",
        ["appropriation_category"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spend_bridge_res_v1_scope_idx",
        "cdc_budget_spending_bridge_resolution_v1",
        ["scope_include_flag"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spend_bridge_res_v1_status_idx",
        "cdc_budget_spending_bridge_resolution_v1",
        ["resolution_status"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spend_bridge_res_v1_analyst_idx",
        "cdc_budget_spending_bridge_resolution_v1",
        ["analyst_reviewed"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spend_bridge_res_v1_auto_idx",
        "cdc_budget_spending_bridge_resolution_v1",
        ["auto_seeded"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spend_bridge_res_v1_fy_idx",
        "cdc_budget_spending_bridge_resolution_v1",
        ["fiscal_year"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spend_bridge_res_v1_source_idx",
        "cdc_budget_spending_bridge_resolution_v1",
        ["source_record_id"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )

    op.create_table(
        "cdc_budget_spending_bridge_resolution_rule_registry",
        sa.Column("rule_code", sa.Text(), nullable=False),
        sa.Column("resolution_version", sa.Text(), nullable=False),
        sa.Column("rule_group", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("resolution_status_output", sa.Text(), nullable=True),
        sa.Column("scope_include_output", sa.Boolean(), nullable=True),
        sa.Column("default_allocation_pct", sa.Numeric(precision=8, scale=6), nullable=True),
        sa.Column("resolution_method_output", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "resolution_status_output IS NULL OR "
            "resolution_status_output IN ('accepted', 'rejected', 'accepted_partial', 'superseded', 'unresolved')",
            name="ck_cdc_budget_spend_bridge_res_rule_v1_status",
        ),
        sa.CheckConstraint(
            "default_allocation_pct IS NULL OR (default_allocation_pct >= 0 AND default_allocation_pct <= 1)",
            name="ck_cdc_budget_spend_bridge_res_rule_v1_alloc",
        ),
        sa.CheckConstraint(
            "resolution_method_output IS NULL OR "
            "resolution_method_output IN ('analyst', 'auto_seed', 'overlay', 'manual_sql')",
            name="ck_cdc_budget_spend_bridge_res_rule_v1_method",
        ),
        sa.PrimaryKeyConstraint("rule_code"),
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spend_bridge_res_rule_v1_ver_pri_idx",
        "cdc_budget_spending_bridge_resolution_rule_registry",
        ["resolution_version", "priority"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spend_bridge_res_rule_v1_active_idx",
        "cdc_budget_spending_bridge_resolution_rule_registry",
        ["is_active"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_spending_bridge_resolution_v1 AS
        SELECT
            r.id,
            r.resolution_batch_id,
            r.resolution_version,
            r.created_at,
            r.updated_at,
            r.bridge_id,
            r.resolution_rule_code,
            r.bridge_version,
            r.budget_anchor_id,
            r.classification_id,
            r.raw_budget_id,
            r.unique_id,
            r.system_name,
            r.source_record_id,
            r.match_tier,
            r.match_type,
            r.match_score,
            r.match_confidence,
            r.confidence_band,
            r.fiscal_year,
            r.budget_agency,
            r.budget_sub_agency,
            r.budget_program,
            r.budget_sub_program,
            r.budget_sub_program_2,
            r.budget_sub_program_3,
            r.budget_program_key,
            r.appropriation_category,
            r.appropriation_subtype,
            r.is_regular_appropriation,
            r.classification_confidence,
            r.primary_rule_code,
            r.resolution_status,
            r.scope_include_flag,
            r.allocation_pct,
            r.allocation_method,
            r.resolution_method,
            r.resolution_confidence,
            r.resolution_priority,
            r.auto_seeded,
            r.analyst_reviewed,
            r.resolution_reason_code,
            r.resolution_explanation,
            r.reviewer_name,
            r.reviewer_email,
            r.reviewed_at,
            r.review_notes,
            r.supersedes_resolution_id,
            r.is_current,
            b.source_table,
            b.source_parent_record_id,
            b.source_fiscal_year,
            b.match_rule_code,
            b.is_auto_accepted AS bridge_is_auto_accepted,
            b.is_excluded AS bridge_is_excluded,
            b.exclusion_reason AS bridge_exclusion_reason,
            b.match_explanation,
            b.matched_on_fields,
            b.review_status AS bridge_review_status,
            b.review_notes AS bridge_review_notes,
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
        FROM {BUDGET_SCHEMA}.cdc_budget_spending_bridge_resolution_v1 AS r
        JOIN {BUDGET_SCHEMA}.cdc_budget_spending_bridge_v1 AS b
          ON b.id = r.bridge_id
        WHERE r.resolution_version = 'v1_bridge_resolution'
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_spending_bridge_resolution_current_v1 AS
        SELECT *
        FROM {BUDGET_SCHEMA}.v_cdc_budget_spending_bridge_resolution_v1
        WHERE is_current = TRUE
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_spending_bridge_resolution_accepted_v1 AS
        SELECT *
        FROM {BUDGET_SCHEMA}.v_cdc_budget_spending_bridge_resolution_current_v1
        WHERE resolution_status IN ('accepted', 'accepted_partial')
          AND scope_include_flag = TRUE
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_spending_bridge_resolution_unresolved_v1 AS
        SELECT *
        FROM {BUDGET_SCHEMA}.v_cdc_budget_spending_bridge_resolution_current_v1
        WHERE resolution_status = 'unresolved'
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_spending_anchor_resolution_summary_v1 AS
        WITH base AS (
            SELECT
                budget_anchor_id,
                MIN(classification_id) AS classification_id,
                MIN(raw_budget_id) AS raw_budget_id,
                MIN(unique_id) AS unique_id,
                MIN(fiscal_year) AS fiscal_year,
                MAX(budget_agency) AS budget_agency,
                MAX(budget_sub_agency) AS budget_sub_agency,
                MAX(budget_program) AS budget_program,
                MAX(budget_sub_program) AS budget_sub_program,
                MAX(budget_sub_program_2) AS budget_sub_program_2,
                MAX(budget_sub_program_3) AS budget_sub_program_3,
                MAX(budget_program_key) AS budget_program_key,
                MAX(appropriation_category) AS appropriation_category,
                MAX(appropriation_subtype) AS appropriation_subtype,
                BOOL_OR(is_regular_appropriation) AS is_regular_appropriation,
                MAX(classification_confidence) AS classification_confidence,
                MAX(primary_rule_code) AS primary_rule_code,
                COUNT(*) AS total_current_resolution_count,
                COUNT(*) FILTER (WHERE resolution_status IN ('accepted', 'accepted_partial')) AS accepted_count,
                COUNT(*) FILTER (WHERE resolution_status = 'rejected') AS rejected_count,
                COUNT(*) FILTER (WHERE resolution_status = 'unresolved') AS unresolved_count,
                COUNT(*) FILTER (WHERE auto_seeded) AS auto_seeded_count,
                COUNT(*) FILTER (WHERE analyst_reviewed) AS analyst_reviewed_count,
                COALESCE(
                    SUM(allocation_pct) FILTER (
                        WHERE resolution_status IN ('accepted', 'accepted_partial')
                          AND scope_include_flag = TRUE
                    ),
                    0::numeric
                ) AS accepted_allocation_sum,
                COUNT(DISTINCT system_name) AS candidate_system_count,
                ARRAY_AGG(DISTINCT system_name ORDER BY system_name) AS system_names,
                BOOL_OR(confidence_band = 'HIGH') AS has_any_high_confidence_candidate,
                BOOL_OR(confidence_band = 'HIGH' AND resolution_status = 'unresolved') AS has_high_confidence_unresolved,
                BOOL_OR(system_name = 'usaspending') AS has_usaspending_candidate,
                BOOL_OR(system_name = 'taggs') AS has_taggs_candidate
            FROM {BUDGET_SCHEMA}.v_cdc_budget_spending_bridge_resolution_current_v1
            GROUP BY budget_anchor_id
        )
        SELECT
            base.*,
            (base.accepted_allocation_sum BETWEEN 0.999999 AND 1.000001) AS allocation_totals_to_one,
            (base.candidate_system_count > 1) AS spans_both_systems,
            (base.candidate_system_count > 1 AND base.unresolved_count > 0) AS conflicting_candidates_across_systems,
            CASE
                WHEN base.accepted_allocation_sum > 1.000001 THEN 'over_allocated'
                WHEN base.accepted_count > 0 AND base.accepted_allocation_sum < 0.999999 THEN 'under_allocated'
                WHEN base.accepted_count > 0
                  AND base.unresolved_count = 0
                  AND base.accepted_allocation_sum BETWEEN 0.999999 AND 1.000001
                    THEN 'fully_resolved'
                WHEN base.accepted_count > 0 THEN 'partially_resolved'
                ELSE 'unresolved'
            END AS review_state
        FROM base
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_spending_bridge_resolution_review_queue_v1 AS
        SELECT
            s.budget_anchor_id,
            s.classification_id,
            s.raw_budget_id,
            s.unique_id,
            s.fiscal_year,
            s.budget_agency,
            s.budget_sub_agency,
            s.budget_program,
            s.budget_sub_program,
            s.budget_sub_program_2,
            s.budget_sub_program_3,
            s.budget_program_key,
            s.appropriation_category,
            s.appropriation_subtype,
            s.is_regular_appropriation,
            s.classification_confidence,
            s.primary_rule_code,
            s.total_current_resolution_count AS total_candidate_count,
            s.accepted_count,
            s.rejected_count,
            s.unresolved_count,
            s.auto_seeded_count,
            s.analyst_reviewed_count,
            s.accepted_allocation_sum,
            s.allocation_totals_to_one,
            s.review_state,
            s.candidate_system_count,
            s.system_names,
            s.spans_both_systems,
            s.conflicting_candidates_across_systems,
            s.has_any_high_confidence_candidate,
            s.has_high_confidence_unresolved,
            MAX(r.match_confidence) AS highest_match_confidence,
            MAX(r.match_confidence) FILTER (
                WHERE r.resolution_status = 'unresolved'
            ) AS highest_unresolved_match_confidence,
            COUNT(*) FILTER (
                WHERE r.resolution_status = 'unresolved'
            ) AS unresolved_candidate_count,
            COUNT(*) FILTER (
                WHERE r.resolution_status = 'unresolved'
                  AND r.confidence_band = 'HIGH'
            ) AS high_confidence_unresolved_count,
            CASE
                WHEN s.has_high_confidence_unresolved THEN 1
                WHEN s.conflicting_candidates_across_systems THEN 2
                WHEN s.unresolved_count >= 3 THEN 3
                WHEN s.review_state IN ('under_allocated', 'over_allocated') THEN 4
                ELSE 5
            END AS review_queue_priority
        FROM {BUDGET_SCHEMA}.v_cdc_budget_spending_anchor_resolution_summary_v1 AS s
        JOIN {BUDGET_SCHEMA}.v_cdc_budget_spending_bridge_resolution_current_v1 AS r
          ON r.budget_anchor_id = s.budget_anchor_id
        WHERE s.review_state <> 'fully_resolved'
           OR s.unresolved_count > 0
        GROUP BY
            s.budget_anchor_id,
            s.classification_id,
            s.raw_budget_id,
            s.unique_id,
            s.fiscal_year,
            s.budget_agency,
            s.budget_sub_agency,
            s.budget_program,
            s.budget_sub_program,
            s.budget_sub_program_2,
            s.budget_sub_program_3,
            s.budget_program_key,
            s.appropriation_category,
            s.appropriation_subtype,
            s.is_regular_appropriation,
            s.classification_confidence,
            s.primary_rule_code,
            s.total_current_resolution_count,
            s.accepted_count,
            s.rejected_count,
            s.unresolved_count,
            s.auto_seeded_count,
            s.analyst_reviewed_count,
            s.accepted_allocation_sum,
            s.allocation_totals_to_one,
            s.review_state,
            s.candidate_system_count,
            s.system_names,
            s.spans_both_systems,
            s.conflicting_candidates_across_systems,
            s.has_any_high_confidence_candidate,
            s.has_high_confidence_unresolved
        """
    )


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_spending_bridge_resolution_review_queue_v1")
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_spending_anchor_resolution_summary_v1")
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_spending_bridge_resolution_unresolved_v1")
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_spending_bridge_resolution_accepted_v1")
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_spending_bridge_resolution_current_v1")
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_spending_bridge_resolution_v1")

    op.drop_index(
        "cdc_budget_spend_bridge_res_rule_v1_active_idx",
        table_name="cdc_budget_spending_bridge_resolution_rule_registry",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spend_bridge_res_rule_v1_ver_pri_idx",
        table_name="cdc_budget_spending_bridge_resolution_rule_registry",
        schema=BUDGET_SCHEMA,
    )
    op.drop_table("cdc_budget_spending_bridge_resolution_rule_registry", schema=BUDGET_SCHEMA)

    op.drop_index(
        "cdc_budget_spend_bridge_res_v1_source_idx",
        table_name="cdc_budget_spending_bridge_resolution_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spend_bridge_res_v1_fy_idx",
        table_name="cdc_budget_spending_bridge_resolution_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spend_bridge_res_v1_auto_idx",
        table_name="cdc_budget_spending_bridge_resolution_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spend_bridge_res_v1_analyst_idx",
        table_name="cdc_budget_spending_bridge_resolution_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spend_bridge_res_v1_status_idx",
        table_name="cdc_budget_spending_bridge_resolution_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spend_bridge_res_v1_scope_idx",
        table_name="cdc_budget_spending_bridge_resolution_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spend_bridge_res_v1_category_idx",
        table_name="cdc_budget_spending_bridge_resolution_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spend_bridge_res_v1_system_idx",
        table_name="cdc_budget_spending_bridge_resolution_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spend_bridge_res_v1_anchor_idx",
        table_name="cdc_budget_spending_bridge_resolution_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spend_bridge_res_v1_bridge_idx",
        table_name="cdc_budget_spending_bridge_resolution_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spend_bridge_res_v1_current_idx",
        table_name="cdc_budget_spending_bridge_resolution_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "uq_cdc_budget_spend_bridge_res_v1_current",
        table_name="cdc_budget_spending_bridge_resolution_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_table("cdc_budget_spending_bridge_resolution_v1", schema=BUDGET_SCHEMA)
