"""add cdc prime transactions and transaction fy summaries

Revision ID: f3c1d9a7b2e4
Revises: e1b3d2f4a6c1
Create Date: 2026-03-07 15:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f3c1d9a7b2e4"
down_revision: Union[str, None] = "e1b3d2f4a6c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CDC_FUNDING_SCHEMA = "cdc_funding"


def upgrade() -> None:
    op.create_table(
        "prime_transactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("assistance_transaction_unique_key", sa.Text(), nullable=False),
        sa.Column("assistance_award_unique_key", sa.Text(), nullable=True),
        sa.Column("award_id_fain", sa.Text(), nullable=True),
        sa.Column("modification_number", sa.Text(), nullable=True),
        sa.Column("award_id_uri", sa.Text(), nullable=True),
        sa.Column("federal_action_obligation", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("total_obligated_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("total_outlayed_amount_for_overall_award", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("action_date", sa.Date(), nullable=True),
        sa.Column("action_date_fiscal_year", sa.Integer(), nullable=True),
        sa.Column("awarding_sub_agency_name", sa.Text(), nullable=True),
        sa.Column("funding_sub_agency_name", sa.Text(), nullable=True),
        sa.Column("awarding_office_name", sa.Text(), nullable=True),
        sa.Column("funding_office_name", sa.Text(), nullable=True),
        sa.Column("recipient_name", sa.Text(), nullable=True),
        sa.Column("recipient_city_name", sa.Text(), nullable=True),
        sa.Column("recipient_county_name", sa.Text(), nullable=True),
        sa.Column("prime_award_transaction_recipient_county_fips_code", sa.String(length=5), nullable=True),
        sa.Column("recipient_state_code", sa.String(length=2), nullable=True),
        sa.Column("recipient_state_name", sa.Text(), nullable=True),
        sa.Column("primary_place_of_performance_county_name", sa.Text(), nullable=True),
        sa.Column("prime_award_transaction_place_of_performance_county_fips_code", sa.String(length=5), nullable=True),
        sa.Column("primary_place_of_performance_state_name", sa.Text(), nullable=True),
        sa.Column("assistance_type_description", sa.Text(), nullable=True),
        sa.Column("transaction_description", sa.Text(), nullable=True),
        sa.Column("prime_award_base_transaction_description", sa.Text(), nullable=True),
        sa.Column("cfda_number", sa.Text(), nullable=True),
        sa.Column("cfda_title", sa.Text(), nullable=True),
        sa.Column("usaspending_permalink", sa.Text(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("searchable_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assistance_transaction_unique_key",
            name="uq_cdc_prime_transactions_assistance_transaction_unique_key",
        ),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_transactions_award_unique_key_idx",
        "prime_transactions",
        ["assistance_award_unique_key"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_transactions_transaction_unique_key_idx",
        "prime_transactions",
        ["assistance_transaction_unique_key"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_transactions_award_fain_idx",
        "prime_transactions",
        ["award_id_fain"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_transactions_fiscal_year_idx",
        "prime_transactions",
        ["action_date_fiscal_year"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_transactions_recipient_state_code_idx",
        "prime_transactions",
        ["recipient_state_code"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_transactions_recipient_county_fips_idx",
        "prime_transactions",
        ["prime_award_transaction_recipient_county_fips_code"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_transactions_assistance_type_idx",
        "prime_transactions",
        ["assistance_type_description"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_transactions_awarding_office_idx",
        "prime_transactions",
        ["awarding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_transactions_funding_office_idx",
        "prime_transactions",
        ["funding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_transactions_raw_gin_idx",
        "prime_transactions",
        ["raw"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
        postgresql_using="gin",
    )

    op.create_table(
        "prime_transaction_state_summary",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("geography_id", sa.String(length=2), nullable=False),
        sa.Column("geography_name", sa.Text(), nullable=True),
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
        "cdc_prime_tx_state_summary_geography_idx",
        "prime_transaction_state_summary",
        ["geography_id"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_state_summary_fiscal_year_idx",
        "prime_transaction_state_summary",
        ["fiscal_year"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_state_summary_assistance_type_idx",
        "prime_transaction_state_summary",
        ["assistance_type_description"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_state_summary_awarding_office_idx",
        "prime_transaction_state_summary",
        ["awarding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_state_summary_funding_office_idx",
        "prime_transaction_state_summary",
        ["funding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_state_summary_awarding_sub_agency_idx",
        "prime_transaction_state_summary",
        ["awarding_sub_agency_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )

    op.create_table(
        "prime_transaction_county_summary",
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
        "cdc_prime_tx_county_summary_geography_idx",
        "prime_transaction_county_summary",
        ["geography_id"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_county_summary_state_code_idx",
        "prime_transaction_county_summary",
        ["state_code"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_county_summary_fiscal_year_idx",
        "prime_transaction_county_summary",
        ["fiscal_year"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_county_summary_assistance_type_idx",
        "prime_transaction_county_summary",
        ["assistance_type_description"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_county_summary_awarding_office_idx",
        "prime_transaction_county_summary",
        ["awarding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_county_summary_funding_office_idx",
        "prime_transaction_county_summary",
        ["funding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_county_summary_awarding_sub_agency_idx",
        "prime_transaction_county_summary",
        ["awarding_sub_agency_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "cdc_prime_tx_county_summary_awarding_sub_agency_idx",
        table_name="prime_transaction_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_county_summary_funding_office_idx",
        table_name="prime_transaction_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_county_summary_awarding_office_idx",
        table_name="prime_transaction_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_county_summary_assistance_type_idx",
        table_name="prime_transaction_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_county_summary_fiscal_year_idx",
        table_name="prime_transaction_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_county_summary_state_code_idx",
        table_name="prime_transaction_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_county_summary_geography_idx",
        table_name="prime_transaction_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_table("prime_transaction_county_summary", schema=CDC_FUNDING_SCHEMA)

    op.drop_index(
        "cdc_prime_tx_state_summary_awarding_sub_agency_idx",
        table_name="prime_transaction_state_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_state_summary_funding_office_idx",
        table_name="prime_transaction_state_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_state_summary_awarding_office_idx",
        table_name="prime_transaction_state_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_state_summary_assistance_type_idx",
        table_name="prime_transaction_state_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_state_summary_fiscal_year_idx",
        table_name="prime_transaction_state_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_state_summary_geography_idx",
        table_name="prime_transaction_state_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_table("prime_transaction_state_summary", schema=CDC_FUNDING_SCHEMA)

    op.drop_index(
        "cdc_prime_transactions_raw_gin_idx",
        table_name="prime_transactions",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_transactions_funding_office_idx",
        table_name="prime_transactions",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_transactions_awarding_office_idx",
        table_name="prime_transactions",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_transactions_assistance_type_idx",
        table_name="prime_transactions",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_transactions_recipient_county_fips_idx",
        table_name="prime_transactions",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_transactions_recipient_state_code_idx",
        table_name="prime_transactions",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_transactions_fiscal_year_idx",
        table_name="prime_transactions",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_transactions_award_fain_idx",
        table_name="prime_transactions",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_transactions_transaction_unique_key_idx",
        table_name="prime_transactions",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_transactions_award_unique_key_idx",
        table_name="prime_transactions",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_table("prime_transactions", schema=CDC_FUNDING_SCHEMA)
