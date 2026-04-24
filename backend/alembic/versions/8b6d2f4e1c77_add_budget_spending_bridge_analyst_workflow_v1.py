"""add budget spending bridge analyst workflow v1

Revision ID: 8b6d2f4e1c77
Revises: 7d3c8e1f2a44
Create Date: 2026-04-06 00:05:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "8b6d2f4e1c77"
down_revision: Union[str, None] = "7d3c8e1f2a44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BUDGET_SCHEMA = "budget"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {BUDGET_SCHEMA}")

    op.create_table(
        "cdc_budget_spending_bridge_analyst_action_v1",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("action_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_version", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("bridge_id", sa.BigInteger(), nullable=False),
        sa.Column("resolution_version", sa.Text(), nullable=False),
        sa.Column("bridge_version", sa.Text(), nullable=False),
        sa.Column("budget_anchor_id", sa.Text(), nullable=False),
        sa.Column("classification_id", sa.BigInteger(), nullable=False),
        sa.Column("raw_budget_id", sa.BigInteger(), nullable=False),
        sa.Column("unique_id", sa.Text(), nullable=False),
        sa.Column("system_name", sa.Text(), nullable=False),
        sa.Column("source_record_id", sa.Text(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("budget_program", sa.Text(), nullable=True),
        sa.Column("budget_sub_program", sa.Text(), nullable=True),
        sa.Column("budget_program_key", sa.Text(), nullable=True),
        sa.Column("appropriation_category", sa.Text(), nullable=False),
        sa.Column("is_regular_appropriation", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("match_tier", sa.Text(), nullable=False),
        sa.Column("match_type", sa.Text(), nullable=False),
        sa.Column("match_confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("confidence_band", sa.Text(), nullable=False),
        sa.Column("analyst_action", sa.Text(), nullable=False),
        sa.Column("allocation_pct", sa.Numeric(precision=8, scale=6), nullable=True),
        sa.Column("scope_include_flag", sa.Boolean(), nullable=True),
        sa.Column("action_reason_code", sa.Text(), nullable=False),
        sa.Column("action_explanation", sa.Text(), nullable=False),
        sa.Column("action_priority", sa.Integer(), nullable=True),
        sa.Column("action_is_final", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("reviewer_name", sa.Text(), nullable=False),
        sa.Column("reviewer_email", sa.Text(), nullable=True),
        sa.Column("reviewer_team", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("import_source", sa.Text(), nullable=True),
        sa.Column("anchor_review_group", sa.Text(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("supersedes_action_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "system_name IN ('usaspending', 'taggs')",
            name="ck_cdc_budget_spend_bridge_act_v1_system",
        ),
        sa.CheckConstraint(
            "match_tier IN ('TIER_A_DETERMINISTIC', 'TIER_B_STRUCTURED', 'TIER_C_FUZZY_CANDIDATE')",
            name="ck_cdc_budget_spend_bridge_act_v1_tier",
        ),
        sa.CheckConstraint(
            "confidence_band IN ('HIGH', 'MEDIUM', 'LOW')",
            name="ck_cdc_budget_spend_bridge_act_v1_band",
        ),
        sa.CheckConstraint(
            "analyst_action IN ("
            "'accept_full', 'accept_partial', 'reject', "
            "'leave_unresolved', 'supersede_prior', 'mark_needs_followup'"
            ")",
            name="ck_cdc_budget_spend_bridge_act_v1_action",
        ),
        sa.CheckConstraint(
            "match_confidence >= 0 AND match_confidence <= 1",
            name="ck_cdc_budget_spend_bridge_act_v1_conf",
        ),
        sa.CheckConstraint(
            "allocation_pct IS NULL OR (allocation_pct >= 0 AND allocation_pct <= 1)",
            name="ck_cdc_budget_spend_bridge_act_v1_alloc",
        ),
        sa.CheckConstraint(
            "analyst_action <> 'accept_full' OR allocation_pct = 1",
            name="ck_cdc_budget_spend_bridge_act_v1_full_alloc",
        ),
        sa.CheckConstraint(
            "analyst_action <> 'accept_partial' "
            "OR (allocation_pct IS NOT NULL AND allocation_pct > 0 AND allocation_pct < 1)",
            name="ck_cdc_budget_spend_bridge_act_v1_partial_alloc",
        ),
        sa.CheckConstraint(
            "analyst_action NOT IN ('reject', 'leave_unresolved', 'supersede_prior', 'mark_needs_followup') "
            "OR allocation_pct IS NULL",
            name="ck_cdc_budget_spend_bridge_act_v1_no_alloc",
        ),
        sa.ForeignKeyConstraint(
            ["bridge_id"],
            [f"{BUDGET_SCHEMA}.cdc_budget_spending_bridge_v1.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_action_id"],
            [f"{BUDGET_SCHEMA}.cdc_budget_spending_bridge_analyst_action_v1.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "uq_cdc_budget_spend_bridge_act_v1_current",
        "cdc_budget_spending_bridge_analyst_action_v1",
        ["action_version", "bridge_id"],
        unique=True,
        schema=BUDGET_SCHEMA,
        postgresql_where=sa.text("is_current"),
    )
    op.create_index(
        "cdc_budget_spend_bridge_act_v1_anchor_idx",
        "cdc_budget_spending_bridge_analyst_action_v1",
        ["budget_anchor_id"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spend_bridge_act_v1_action_idx",
        "cdc_budget_spending_bridge_analyst_action_v1",
        ["analyst_action"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spend_bridge_act_v1_reviewer_idx",
        "cdc_budget_spending_bridge_analyst_action_v1",
        ["reviewer_name"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spend_bridge_act_v1_reviewer_email_idx",
        "cdc_budget_spending_bridge_analyst_action_v1",
        ["reviewer_email"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spend_bridge_act_v1_category_idx",
        "cdc_budget_spending_bridge_analyst_action_v1",
        ["appropriation_category"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spend_bridge_act_v1_regular_idx",
        "cdc_budget_spending_bridge_analyst_action_v1",
        ["is_regular_appropriation"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spend_bridge_act_v1_fy_idx",
        "cdc_budget_spending_bridge_analyst_action_v1",
        ["fiscal_year"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spend_bridge_act_v1_system_idx",
        "cdc_budget_spending_bridge_analyst_action_v1",
        ["system_name"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )

    op.create_table(
        "cdc_budget_spending_bridge_analyst_reason_registry",
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("action_version", sa.Text(), nullable=False),
        sa.Column("analyst_action", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("requires_allocation", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("scope_include_default", sa.Boolean(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "analyst_action IN ("
            "'accept_full', 'accept_partial', 'reject', "
            "'leave_unresolved', 'supersede_prior', 'mark_needs_followup'"
            ")",
            name="ck_cdc_budget_spend_bridge_reason_v1_action",
        ),
        sa.PrimaryKeyConstraint("reason_code"),
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spend_bridge_reason_v1_ver_action_idx",
        "cdc_budget_spending_bridge_analyst_reason_registry",
        ["action_version", "analyst_action"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_spend_bridge_reason_v1_active_idx",
        "cdc_budget_spending_bridge_analyst_reason_registry",
        ["is_active"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_spending_anchor_review_state_v1 AS
        WITH resolution_base AS (
            SELECT
                r.budget_anchor_id,
                MIN(r.classification_id) AS classification_id,
                MIN(r.raw_budget_id) AS raw_budget_id,
                MIN(r.unique_id) AS unique_id,
                MIN(r.fiscal_year) AS fiscal_year,
                MAX(r.appropriation_category) AS appropriation_category,
                BOOL_OR(r.is_regular_appropriation) AS is_regular_appropriation,
                MAX(r.budget_program) AS budget_program,
                MAX(r.budget_sub_program) AS budget_sub_program,
                COUNT(*) AS total_candidate_count,
                COUNT(*) FILTER (WHERE r.resolution_status = 'accepted') AS current_accepted_count,
                COUNT(*) FILTER (WHERE r.resolution_status = 'accepted_partial') AS current_accepted_partial_count,
                COUNT(*) FILTER (WHERE r.resolution_status = 'rejected') AS current_rejected_count,
                COUNT(*) FILTER (WHERE r.resolution_status = 'unresolved') AS current_unresolved_count,
                COALESCE(
                    SUM(r.allocation_pct) FILTER (
                        WHERE r.resolution_status IN ('accepted', 'accepted_partial')
                          AND r.scope_include_flag = TRUE
                    ),
                    0::numeric
                ) AS accepted_allocation_sum,
                MAX(r.match_confidence) AS highest_current_confidence,
                ARRAY_AGG(DISTINCT r.system_name ORDER BY r.system_name) AS systems_represented,
                COUNT(*) FILTER (WHERE r.analyst_reviewed = TRUE) AS analyst_reviewed_resolution_count,
                COUNT(*) FILTER (WHERE r.auto_seeded = TRUE) AS auto_seeded_resolution_count
            FROM {BUDGET_SCHEMA}.v_cdc_budget_spending_bridge_resolution_current_v1 AS r
            GROUP BY r.budget_anchor_id
        ),
        action_current AS (
            SELECT *
            FROM {BUDGET_SCHEMA}.cdc_budget_spending_bridge_analyst_action_v1
            WHERE action_version = 'v1_analyst_bridge_actions'
              AND is_current = TRUE
        ),
        action_base AS (
            SELECT
                a.budget_anchor_id,
                COUNT(*) AS current_analyst_action_count,
                COUNT(*) FILTER (WHERE a.analyst_action = 'mark_needs_followup') AS needs_followup_count
            FROM action_current AS a
            GROUP BY a.budget_anchor_id
        ),
        latest_action AS (
            SELECT DISTINCT ON (a.budget_anchor_id)
                a.budget_anchor_id,
                a.reviewed_at AS last_reviewed_at,
                a.reviewer_name AS last_reviewer_name
            FROM action_current AS a
            ORDER BY a.budget_anchor_id, a.reviewed_at DESC, a.id DESC
        )
        SELECT
            rb.budget_anchor_id,
            rb.unique_id,
            rb.fiscal_year,
            rb.appropriation_category,
            rb.is_regular_appropriation,
            rb.budget_program,
            rb.budget_sub_program,
            rb.total_candidate_count,
            rb.current_accepted_count,
            rb.current_accepted_partial_count,
            rb.current_rejected_count,
            rb.current_unresolved_count,
            rb.accepted_allocation_sum,
            CASE
                WHEN rb.accepted_allocation_sum = 0 THEN 'no_allocations'
                WHEN rb.accepted_allocation_sum > 1.000001 THEN 'over_allocated'
                WHEN rb.accepted_allocation_sum < 0.999999 THEN 'under_allocated'
                ELSE 'balanced'
            END AS allocation_balance_status,
            CASE
                WHEN COALESCE(ab.current_analyst_action_count, 0) = 0 THEN 'unreviewed'
                WHEN COALESCE(ab.needs_followup_count, 0) > 0 THEN 'needs_followup'
                WHEN rb.accepted_allocation_sum > 1.000001 OR rb.current_accepted_count > 1 THEN 'conflicting'
                WHEN rb.current_accepted_count = 1
                  AND rb.current_accepted_partial_count = 0
                  AND rb.current_unresolved_count = 0
                  AND rb.accepted_allocation_sum BETWEEN 0.999999 AND 1.000001
                    THEN 'fully_reviewed_single_winner'
                WHEN rb.current_accepted_partial_count > 0
                  AND rb.current_unresolved_count = 0
                  AND rb.accepted_allocation_sum BETWEEN 0.999999 AND 1.000001
                    THEN 'fully_reviewed_split'
                ELSE 'partially_reviewed'
            END AS analyst_review_state,
            (COALESCE(ab.current_analyst_action_count, 0) > 0) AS has_analyst_review,
            (
                COALESCE(ab.current_analyst_action_count, 0) = 0
                AND rb.auto_seeded_resolution_count > 0
            ) AS has_auto_seed_only,
            rb.highest_current_confidence,
            rb.systems_represented,
            la.last_reviewed_at,
            la.last_reviewer_name
        FROM resolution_base AS rb
        LEFT JOIN action_base AS ab
          ON ab.budget_anchor_id = rb.budget_anchor_id
        LEFT JOIN latest_action AS la
          ON la.budget_anchor_id = rb.budget_anchor_id
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_spending_review_queue_unresolved_v1 AS
        SELECT
            *,
            CASE
                WHEN is_regular_appropriation THEN 1
                WHEN appropriation_category = 'PPHF' THEN 2
                ELSE 3
            END AS queue_priority
        FROM {BUDGET_SCHEMA}.v_cdc_budget_spending_anchor_review_state_v1
        WHERE current_unresolved_count > 0
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_spending_review_queue_split_needed_v1 AS
        SELECT *
        FROM {BUDGET_SCHEMA}.v_cdc_budget_spending_anchor_review_state_v1
        WHERE total_candidate_count > 1
          AND has_analyst_review = TRUE
          AND (
                current_accepted_partial_count > 0
             OR current_unresolved_count > 0
          )
          AND allocation_balance_status <> 'balanced'
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_spending_review_queue_under_allocated_v1 AS
        SELECT *
        FROM {BUDGET_SCHEMA}.v_cdc_budget_spending_anchor_review_state_v1
        WHERE has_analyst_review = TRUE
          AND allocation_balance_status = 'under_allocated'
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_spending_review_queue_over_allocated_v1 AS
        SELECT *
        FROM {BUDGET_SCHEMA}.v_cdc_budget_spending_anchor_review_state_v1
        WHERE has_analyst_review = TRUE
          AND allocation_balance_status = 'over_allocated'
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_spending_review_queue_high_priority_regular_v1 AS
        SELECT *
        FROM {BUDGET_SCHEMA}.v_cdc_budget_spending_anchor_review_state_v1
        WHERE is_regular_appropriation = TRUE
          AND analyst_review_state IN ('unreviewed', 'partially_reviewed', 'needs_followup', 'conflicting')
        """
    )


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_spending_review_queue_high_priority_regular_v1")
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_spending_review_queue_over_allocated_v1")
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_spending_review_queue_under_allocated_v1")
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_spending_review_queue_split_needed_v1")
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_spending_review_queue_unresolved_v1")
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_spending_anchor_review_state_v1")

    op.drop_index(
        "cdc_budget_spend_bridge_reason_v1_active_idx",
        table_name="cdc_budget_spending_bridge_analyst_reason_registry",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spend_bridge_reason_v1_ver_action_idx",
        table_name="cdc_budget_spending_bridge_analyst_reason_registry",
        schema=BUDGET_SCHEMA,
    )
    op.drop_table("cdc_budget_spending_bridge_analyst_reason_registry", schema=BUDGET_SCHEMA)

    op.drop_index(
        "cdc_budget_spend_bridge_act_v1_system_idx",
        table_name="cdc_budget_spending_bridge_analyst_action_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spend_bridge_act_v1_fy_idx",
        table_name="cdc_budget_spending_bridge_analyst_action_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spend_bridge_act_v1_regular_idx",
        table_name="cdc_budget_spending_bridge_analyst_action_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spend_bridge_act_v1_category_idx",
        table_name="cdc_budget_spending_bridge_analyst_action_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spend_bridge_act_v1_reviewer_email_idx",
        table_name="cdc_budget_spending_bridge_analyst_action_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spend_bridge_act_v1_reviewer_idx",
        table_name="cdc_budget_spending_bridge_analyst_action_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spend_bridge_act_v1_action_idx",
        table_name="cdc_budget_spending_bridge_analyst_action_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "cdc_budget_spend_bridge_act_v1_anchor_idx",
        table_name="cdc_budget_spending_bridge_analyst_action_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_index(
        "uq_cdc_budget_spend_bridge_act_v1_current",
        table_name="cdc_budget_spending_bridge_analyst_action_v1",
        schema=BUDGET_SCHEMA,
    )
    op.drop_table("cdc_budget_spending_bridge_analyst_action_v1", schema=BUDGET_SCHEMA)
