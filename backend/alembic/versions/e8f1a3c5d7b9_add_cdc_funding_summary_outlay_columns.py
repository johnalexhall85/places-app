"""add cdc funding summary outlay columns

Revision ID: e8f1a3c5d7b9
Revises: e6b4c2a9d7f1
Create Date: 2026-07-27 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e8f1a3c5d7b9"
down_revision: Union[str, None] = "e6b4c2a9d7f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CDC_FUNDING_SCHEMA = "cdc_funding"
MONEY = sa.Numeric(precision=24, scale=2)
PERIOD_TABLES = (
    "cdc_funding_account_monthly",
    "cdc_funding_account_quarterly",
    "cdc_funding_category_monthly",
    "cdc_funding_category_quarterly",
)


def upgrade() -> None:
    for table_name in PERIOD_TABLES:
        op.add_column(
            table_name,
            sa.Column("numeric_outlay_rows", sa.Integer(), nullable=True),
            schema=CDC_FUNDING_SCHEMA,
        )
        op.add_column(
            table_name,
            sa.Column(
                "gross_outlay_amount_fyb_to_period_end",
                MONEY,
                nullable=True,
            ),
            schema=CDC_FUNDING_SCHEMA,
        )
    op.add_column(
        "cdc_funding_category_comparison",
        sa.Column("usaspending_outlays", MONEY, nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )


def downgrade() -> None:
    op.drop_column(
        "cdc_funding_category_comparison",
        "usaspending_outlays",
        schema=CDC_FUNDING_SCHEMA,
    )
    for table_name in reversed(PERIOD_TABLES):
        op.drop_column(
            table_name,
            "gross_outlay_amount_fyb_to_period_end",
            schema=CDC_FUNDING_SCHEMA,
        )
        op.drop_column(
            table_name,
            "numeric_outlay_rows",
            schema=CDC_FUNDING_SCHEMA,
        )
