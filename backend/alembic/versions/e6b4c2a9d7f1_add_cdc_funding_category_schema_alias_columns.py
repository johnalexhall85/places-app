"""add cdc funding category schema alias columns

Revision ID: e6b4c2a9d7f1
Revises: e5c7a9d1b3f0
Create Date: 2026-07-19 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e6b4c2a9d7f1"
down_revision: Union[str, None] = "e5c7a9d1b3f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CDC_FUNDING_SCHEMA = "cdc_funding"


def upgrade() -> None:
    op.add_column(
        "cdc_funding_category_comparison",
        sa.Column("data_status", sa.Text(), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "cdc_funding_category_comparison",
        sa.Column("as_of_period", sa.Text(), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "cdc_funding_category_comparison",
        sa.Column("methodology_note", sa.Text(), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "cdc_funding_category_mapping",
        sa.Column("expected_account_name", sa.Text(), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "cdc_funding_category_mapping",
        sa.Column("actual_account_name", sa.Text(), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "cdc_funding_category_mapping",
        sa.Column("account_name_match", sa.Boolean(), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("cdc_funding_category_mapping", "account_name_match", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("cdc_funding_category_mapping", "actual_account_name", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("cdc_funding_category_mapping", "expected_account_name", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("cdc_funding_category_comparison", "methodology_note", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("cdc_funding_category_comparison", "as_of_period", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("cdc_funding_category_comparison", "data_status", schema=CDC_FUNDING_SCHEMA)
