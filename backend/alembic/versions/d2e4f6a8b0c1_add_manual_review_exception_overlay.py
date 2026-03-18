"""add manual review exception overlay table

Revision ID: d2e4f6a8b0c1
Revises: c1d2e3f4a5b6
Create Date: 2026-03-16 19:05:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d2e4f6a8b0c1"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RECON_SCHEMA = "recon"
TABLE_NAME = "manual_review_exception_overlay"


def upgrade() -> None:
    op.create_table(
        TABLE_NAME,
        sa.Column("review_id", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("apply_in_production", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("assistance_only", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("contracts_only", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("state_code", sa.String(length=2), nullable=True),
        sa.Column("aln", sa.Text(), nullable=True),
        sa.Column("award_family", sa.Text(), nullable=True),
        sa.Column("federal_account_combination_key", sa.Text(), nullable=True),
        sa.Column("current_multi_account_interpretation", sa.Text(), nullable=True),
        sa.Column(
            "recommended_review_disposition",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'manual_review_only'"),
        ),
        sa.Column("analyst_notes", sa.Text(), nullable=True),
        sa.Column("evidence_source", sa.Text(), nullable=True),
        sa.Column("methodology_version", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("review_id", name="pk_recon_manual_review_exception_overlay"),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_manual_review_exception_overlay_fy_idx",
        TABLE_NAME,
        ["fiscal_year"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_manual_review_exception_overlay_state_idx",
        TABLE_NAME,
        ["state_code"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_manual_review_exception_overlay_aln_idx",
        TABLE_NAME,
        ["aln"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_manual_review_exception_overlay_family_idx",
        TABLE_NAME,
        ["award_family"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_manual_review_exception_overlay_combo_idx",
        TABLE_NAME,
        ["federal_account_combination_key"],
        unique=False,
        schema=RECON_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "recon_manual_review_exception_overlay_combo_idx",
        table_name=TABLE_NAME,
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_manual_review_exception_overlay_family_idx",
        table_name=TABLE_NAME,
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_manual_review_exception_overlay_aln_idx",
        table_name=TABLE_NAME,
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_manual_review_exception_overlay_state_idx",
        table_name=TABLE_NAME,
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_manual_review_exception_overlay_fy_idx",
        table_name=TABLE_NAME,
        schema=RECON_SCHEMA,
    )
    op.drop_table(TABLE_NAME, schema=RECON_SCHEMA)
