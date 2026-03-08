"""add cdc prime transaction county allocated summary table

Revision ID: b8e1c4d7a2f3
Revises: a7b2c4d9e1f0
Create Date: 2026-03-07 19:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b8e1c4d7a2f3"
down_revision: Union[str, None] = "a7b2c4d9e1f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CDC_FUNDING_SCHEMA = "cdc_funding"


def upgrade() -> None:
    op.create_table(
        "prime_transaction_county_summary_allocated",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("geography_id", sa.String(length=5), nullable=False),
        sa.Column("geography_name", sa.Text(), nullable=True),
        sa.Column("state_code", sa.String(length=2), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("assistance_type_description", sa.Text(), nullable=True),
        sa.Column("awarding_sub_agency_name", sa.Text(), nullable=True),
        sa.Column("funding_sub_agency_name", sa.Text(), nullable=True),
        sa.Column("awarding_office_name", sa.Text(), nullable=True),
        sa.Column("funding_office_name", sa.Text(), nullable=True),
        sa.Column(
            "fy_obligated_amount",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "fy_outlayed_amount_estimated",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("transaction_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("distinct_award_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("id"),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_county_alloc_summary_geography_idx",
        "prime_transaction_county_summary_allocated",
        ["geography_id"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_county_alloc_summary_state_code_idx",
        "prime_transaction_county_summary_allocated",
        ["state_code"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_county_alloc_summary_fiscal_year_idx",
        "prime_transaction_county_summary_allocated",
        ["fiscal_year"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_county_alloc_summary_assistance_type_idx",
        "prime_transaction_county_summary_allocated",
        ["assistance_type_description"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_county_alloc_summary_awarding_office_idx",
        "prime_transaction_county_summary_allocated",
        ["awarding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_county_alloc_summary_funding_office_idx",
        "prime_transaction_county_summary_allocated",
        ["funding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_county_alloc_summary_awarding_sub_agency_idx",
        "prime_transaction_county_summary_allocated",
        ["awarding_sub_agency_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "cdc_prime_tx_county_alloc_summary_awarding_sub_agency_idx",
        table_name="prime_transaction_county_summary_allocated",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_county_alloc_summary_funding_office_idx",
        table_name="prime_transaction_county_summary_allocated",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_county_alloc_summary_awarding_office_idx",
        table_name="prime_transaction_county_summary_allocated",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_county_alloc_summary_assistance_type_idx",
        table_name="prime_transaction_county_summary_allocated",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_county_alloc_summary_fiscal_year_idx",
        table_name="prime_transaction_county_summary_allocated",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_county_alloc_summary_state_code_idx",
        table_name="prime_transaction_county_summary_allocated",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_county_alloc_summary_geography_idx",
        table_name="prime_transaction_county_summary_allocated",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_table("prime_transaction_county_summary_allocated", schema=CDC_FUNDING_SCHEMA)
