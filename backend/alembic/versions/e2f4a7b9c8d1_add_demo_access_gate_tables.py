"""add demo access gate tables

Revision ID: e2f4a7b9c8d1
Revises: d6c8b1e4f2a7
Create Date: 2026-04-19 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e2f4a7b9c8d1"
down_revision: Union[str, None] = "d6c8b1e4f2a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "demo_access_codes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("code_label", sa.Text(), nullable=False),
        sa.Column("recipient_name", sa.Text(), nullable=True),
        sa.Column("recipient_email", sa.Text(), nullable=True),
        sa.Column("organization", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", sa.Text(), nullable=False, server_default=sa.text("'system'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("current_use_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("current_use_count >= 0", name="ck_demo_access_codes_use_count_nonnegative"),
        sa.CheckConstraint("max_uses IS NULL OR max_uses > 0", name="ck_demo_access_codes_max_uses_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash", name="uq_demo_access_codes_code_hash"),
    )
    op.create_index("idx_demo_access_codes_active", "demo_access_codes", ["is_active"], unique=False)
    op.create_index(
        "idx_demo_access_codes_recipient_email",
        "demo_access_codes",
        ["recipient_email"],
        unique=False,
    )
    op.create_index(
        "idx_demo_access_codes_last_used_at",
        "demo_access_codes",
        ["last_used_at"],
        unique=False,
    )

    op.create_table(
        "demo_access_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("access_code_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("session_id", sa.Text(), nullable=True),
        sa.Column("request_path", sa.Text(), nullable=True),
        sa.Column("referrer", sa.Text(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["access_code_id"], ["demo_access_codes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_demo_access_events_code_time",
        "demo_access_events",
        ["access_code_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "idx_demo_access_events_type_time",
        "demo_access_events",
        ["event_type", "occurred_at"],
        unique=False,
    )
    op.create_index("idx_demo_access_events_session", "demo_access_events", ["session_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_demo_access_events_session", table_name="demo_access_events")
    op.drop_index("idx_demo_access_events_type_time", table_name="demo_access_events")
    op.drop_index("idx_demo_access_events_code_time", table_name="demo_access_events")
    op.drop_table("demo_access_events")

    op.drop_index("idx_demo_access_codes_last_used_at", table_name="demo_access_codes")
    op.drop_index("idx_demo_access_codes_recipient_email", table_name="demo_access_codes")
    op.drop_index("idx_demo_access_codes_active", table_name="demo_access_codes")
    op.drop_table("demo_access_codes")

