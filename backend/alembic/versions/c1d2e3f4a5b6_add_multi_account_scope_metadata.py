"""add multi-account scope metadata columns

Revision ID: c1d2e3f4a5b6
Revises: 9b5f1d7c3a44
Create Date: 2026-03-16 17:10:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "9b5f1d7c3a44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RECON_SCHEMA = "recon"

TABLES = (
    "assistance_transaction_account_summary",
    "assistance_transactions_profile_enriched",
    "contract_transactions_profile_enriched",
    "profile_scope_transactions",
)


def _add_multi_account_columns(table_name: str) -> None:
    op.add_column(table_name, sa.Column("funding_scope_method", sa.Text(), nullable=True), schema=RECON_SCHEMA)
    op.add_column(
        table_name,
        sa.Column("federal_account_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        table_name,
        sa.Column("federal_account_combination_key", sa.Text(), nullable=True),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        table_name,
        sa.Column("federal_account_titles_combined", sa.Text(), nullable=True),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        table_name,
        sa.Column("component_account_scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        table_name,
        sa.Column("component_scope_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        table_name,
        sa.Column("has_mixed_scopes", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema=RECON_SCHEMA,
    )
    op.add_column(table_name, sa.Column("account_structure_type", sa.Text(), nullable=True), schema=RECON_SCHEMA)
    op.add_column(
        table_name,
        sa.Column("multi_account_interpretation", sa.Text(), nullable=True),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        table_name,
        sa.Column("conservative_inclusion_reason", sa.Text(), nullable=True),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        table_name,
        sa.Column("manual_review_recommended", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        table_name,
        sa.Column("mixed_scope_contains_core", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        table_name,
        sa.Column("mixed_scope_contains_emergency", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        table_name,
        sa.Column("mixed_scope_contains_transfer", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        table_name,
        sa.Column("mixed_scope_contains_procurement", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        table_name,
        sa.Column("mixed_scope_contains_research", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        table_name,
        sa.Column("mixed_scope_contains_international", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        table_name,
        sa.Column("mixed_scope_contains_special_transfer", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        table_name,
        sa.Column("mixed_scope_contains_unknown", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema=RECON_SCHEMA,
    )


def _drop_multi_account_columns(table_name: str) -> None:
    for column_name in (
        "mixed_scope_contains_unknown",
        "mixed_scope_contains_special_transfer",
        "mixed_scope_contains_international",
        "mixed_scope_contains_research",
        "mixed_scope_contains_procurement",
        "mixed_scope_contains_transfer",
        "mixed_scope_contains_emergency",
        "mixed_scope_contains_core",
        "manual_review_recommended",
        "conservative_inclusion_reason",
        "multi_account_interpretation",
        "account_structure_type",
        "has_mixed_scopes",
        "component_scope_count",
        "component_account_scopes",
        "federal_account_titles_combined",
        "federal_account_combination_key",
        "federal_account_count",
        "funding_scope_method",
    ):
        op.drop_column(table_name, column_name, schema=RECON_SCHEMA)


def upgrade() -> None:
    for table_name in TABLES:
        _add_multi_account_columns(table_name)


def downgrade() -> None:
    for table_name in reversed(TABLES):
        _drop_multi_account_columns(table_name)
