"""add cdc funding schema tables

Revision ID: c2a8b1f4d9e0
Revises: b9f24d31a8e1
Create Date: 2026-03-07 10:45:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c2a8b1f4d9e0"
down_revision: Union[str, None] = "b9f24d31a8e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CDC_FUNDING_SCHEMA = "cdc_funding"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {CDC_FUNDING_SCHEMA}")

    op.create_table(
        "prime_awards",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("unique_key", sa.Text(), nullable=False),
        sa.Column("fain", sa.Text(), nullable=True),
        sa.Column("uri", sa.Text(), nullable=True),
        sa.Column("recipient_name", sa.Text(), nullable=True),
        sa.Column("recipient_state_code", sa.String(length=2), nullable=True),
        sa.Column("recipient_state_name", sa.Text(), nullable=True),
        sa.Column("recipient_county_name", sa.Text(), nullable=True),
        sa.Column("recipient_county_fips", sa.String(length=5), nullable=True),
        sa.Column("primary_place_of_performance_state_name", sa.Text(), nullable=True),
        sa.Column("primary_place_of_performance_county_name", sa.Text(), nullable=True),
        sa.Column("primary_place_of_performance_county_fips", sa.String(length=5), nullable=True),
        sa.Column("assistance_type_description", sa.Text(), nullable=True),
        sa.Column("total_funding_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("total_obligated_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("total_outlayed_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("award_base_action_date", sa.Date(), nullable=True),
        sa.Column("award_latest_action_date", sa.Date(), nullable=True),
        sa.Column("award_latest_action_date_fiscal_year", sa.Integer(), nullable=True),
        sa.Column("awarding_sub_agency_name", sa.Text(), nullable=True),
        sa.Column("funding_sub_agency_name", sa.Text(), nullable=True),
        sa.Column("awarding_office_name", sa.Text(), nullable=True),
        sa.Column("funding_office_name", sa.Text(), nullable=True),
        sa.Column("cfda_program_num", sa.Text(), nullable=True),
        sa.Column("cfda_program_title", sa.Text(), nullable=True),
        sa.Column("cfda_numbers_and_titles", sa.Text(), nullable=True),
        sa.Column("prime_award_base_transaction_description", sa.Text(), nullable=True),
        sa.Column("usaspending_permalink", sa.Text(), nullable=True),
        sa.Column("recipient_state_fips_code", sa.String(length=2), nullable=True),
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
        sa.UniqueConstraint("unique_key", name="uq_cdc_prime_awards_unique_key"),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_awards_fain_idx",
        "prime_awards",
        ["fain"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_awards_recipient_state_code_idx",
        "prime_awards",
        ["recipient_state_code"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_awards_recipient_county_fips_idx",
        "prime_awards",
        ["recipient_county_fips"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_awards_fiscal_year_idx",
        "prime_awards",
        ["award_latest_action_date_fiscal_year"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_awards_assistance_type_idx",
        "prime_awards",
        ["assistance_type_description"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_awards_awarding_office_idx",
        "prime_awards",
        ["awarding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_awards_funding_office_idx",
        "prime_awards",
        ["funding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_awards_awarding_sub_agency_idx",
        "prime_awards",
        ["awarding_sub_agency_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_awards_funding_sub_agency_idx",
        "prime_awards",
        ["funding_sub_agency_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_awards_raw_gin_idx",
        "prime_awards",
        ["raw"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
        postgresql_using="gin",
    )
    op.create_index(
        "cdc_prime_awards_searchable_text_idx",
        "prime_awards",
        ["searchable_text"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )

    op.create_table(
        "subawards",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("prime_award_unique_key", sa.Text(), nullable=False),
        sa.Column("prime_award_fain", sa.Text(), nullable=True),
        sa.Column("subaward_number", sa.Text(), nullable=True),
        sa.Column("subaward_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("subaward_action_date", sa.Date(), nullable=True),
        sa.Column("subaward_action_date_fiscal_year", sa.Integer(), nullable=True),
        sa.Column("subawardee_name", sa.Text(), nullable=True),
        sa.Column("subawardee_state_code", sa.String(length=2), nullable=True),
        sa.Column("subawardee_state_name", sa.Text(), nullable=True),
        sa.Column("subawardee_city_name", sa.Text(), nullable=True),
        sa.Column("subawardee_county_fips", sa.String(length=5), nullable=True),
        sa.Column("subaward_primary_place_of_performance_state_code", sa.String(length=2), nullable=True),
        sa.Column("subaward_primary_place_of_performance_state_name", sa.Text(), nullable=True),
        sa.Column("subaward_description", sa.Text(), nullable=True),
        sa.Column("prime_award_awarding_sub_agency_name", sa.Text(), nullable=True),
        sa.Column("prime_award_funding_sub_agency_name", sa.Text(), nullable=True),
        sa.Column("prime_award_awarding_office_name", sa.Text(), nullable=True),
        sa.Column("prime_award_funding_office_name", sa.Text(), nullable=True),
        sa.Column("prime_award_base_transaction_description", sa.Text(), nullable=True),
        sa.Column("usaspending_permalink", sa.Text(), nullable=True),
        sa.Column("prime_award_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("prime_award_total_outlayed_amount", sa.Numeric(precision=18, scale=2), nullable=True),
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
            "prime_award_unique_key",
            "subaward_number",
            "subaward_action_date",
            "subaward_amount",
            "subawardee_name",
            name="uq_cdc_subawards_row",
        ),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subawards_prime_award_unique_key_idx",
        "subawards",
        ["prime_award_unique_key"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subawards_prime_award_fain_idx",
        "subawards",
        ["prime_award_fain"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subawards_state_code_idx",
        "subawards",
        ["subawardee_state_code"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subawards_county_fips_idx",
        "subawards",
        ["subawardee_county_fips"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subawards_fiscal_year_idx",
        "subawards",
        ["subaward_action_date_fiscal_year"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subawards_awarding_office_idx",
        "subawards",
        ["prime_award_awarding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subawards_funding_office_idx",
        "subawards",
        ["prime_award_funding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subawards_awarding_sub_agency_idx",
        "subawards",
        ["prime_award_awarding_sub_agency_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subawards_funding_sub_agency_idx",
        "subawards",
        ["prime_award_funding_sub_agency_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subawards_raw_gin_idx",
        "subawards",
        ["raw"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
        postgresql_using="gin",
    )
    op.create_index(
        "cdc_subawards_searchable_text_idx",
        "subawards",
        ["searchable_text"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )

    op.create_table(
        "prime_state_summary",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("geography_id", sa.String(length=2), nullable=False),
        sa.Column("geography_name", sa.Text(), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("assistance_type_description", sa.Text(), nullable=True),
        sa.Column("awarding_sub_agency_name", sa.Text(), nullable=True),
        sa.Column("funding_sub_agency_name", sa.Text(), nullable=True),
        sa.Column("awarding_office_name", sa.Text(), nullable=True),
        sa.Column("funding_office_name", sa.Text(), nullable=True),
        sa.Column("total_funding_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("total_obligated_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("total_outlayed_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("award_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("id"),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_state_summary_geography_idx",
        "prime_state_summary",
        ["geography_id"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_state_summary_fiscal_year_idx",
        "prime_state_summary",
        ["fiscal_year"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_state_summary_assistance_type_idx",
        "prime_state_summary",
        ["assistance_type_description"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_state_summary_awarding_office_idx",
        "prime_state_summary",
        ["awarding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_state_summary_funding_office_idx",
        "prime_state_summary",
        ["funding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_state_summary_awarding_sub_agency_idx",
        "prime_state_summary",
        ["awarding_sub_agency_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )

    op.create_table(
        "prime_county_summary",
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
        sa.Column("total_funding_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("total_obligated_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("total_outlayed_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("award_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("id"),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_county_summary_geography_idx",
        "prime_county_summary",
        ["geography_id"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_county_summary_state_code_idx",
        "prime_county_summary",
        ["state_code"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_county_summary_fiscal_year_idx",
        "prime_county_summary",
        ["fiscal_year"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_county_summary_assistance_type_idx",
        "prime_county_summary",
        ["assistance_type_description"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_county_summary_awarding_office_idx",
        "prime_county_summary",
        ["awarding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_county_summary_funding_office_idx",
        "prime_county_summary",
        ["funding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_county_summary_awarding_sub_agency_idx",
        "prime_county_summary",
        ["awarding_sub_agency_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )

    op.create_table(
        "subaward_state_summary",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("geography_id", sa.String(length=2), nullable=False),
        sa.Column("geography_name", sa.Text(), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("awarding_sub_agency_name", sa.Text(), nullable=True),
        sa.Column("funding_sub_agency_name", sa.Text(), nullable=True),
        sa.Column("awarding_office_name", sa.Text(), nullable=True),
        sa.Column("funding_office_name", sa.Text(), nullable=True),
        sa.Column("total_funding_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("total_obligated_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("total_outlayed_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("award_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_subaward_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("subaward_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("id"),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subaward_state_summary_geography_idx",
        "subaward_state_summary",
        ["geography_id"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subaward_state_summary_fiscal_year_idx",
        "subaward_state_summary",
        ["fiscal_year"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subaward_state_summary_awarding_office_idx",
        "subaward_state_summary",
        ["awarding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subaward_state_summary_funding_office_idx",
        "subaward_state_summary",
        ["funding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subaward_state_summary_awarding_sub_agency_idx",
        "subaward_state_summary",
        ["awarding_sub_agency_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )

    op.create_table(
        "subaward_county_summary",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("geography_id", sa.String(length=5), nullable=False),
        sa.Column("geography_name", sa.Text(), nullable=True),
        sa.Column("state_code", sa.String(length=2), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("awarding_sub_agency_name", sa.Text(), nullable=True),
        sa.Column("funding_sub_agency_name", sa.Text(), nullable=True),
        sa.Column("awarding_office_name", sa.Text(), nullable=True),
        sa.Column("funding_office_name", sa.Text(), nullable=True),
        sa.Column("total_funding_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("total_obligated_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("total_outlayed_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("award_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_subaward_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("subaward_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("id"),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subaward_county_summary_geography_idx",
        "subaward_county_summary",
        ["geography_id"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subaward_county_summary_state_code_idx",
        "subaward_county_summary",
        ["state_code"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subaward_county_summary_fiscal_year_idx",
        "subaward_county_summary",
        ["fiscal_year"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subaward_county_summary_awarding_office_idx",
        "subaward_county_summary",
        ["awarding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subaward_county_summary_funding_office_idx",
        "subaward_county_summary",
        ["funding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subaward_county_summary_awarding_sub_agency_idx",
        "subaward_county_summary",
        ["awarding_sub_agency_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "cdc_subaward_county_summary_awarding_sub_agency_idx",
        table_name="subaward_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_subaward_county_summary_funding_office_idx",
        table_name="subaward_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_subaward_county_summary_awarding_office_idx",
        table_name="subaward_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_subaward_county_summary_fiscal_year_idx",
        table_name="subaward_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_subaward_county_summary_state_code_idx",
        table_name="subaward_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_subaward_county_summary_geography_idx",
        table_name="subaward_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_table("subaward_county_summary", schema=CDC_FUNDING_SCHEMA)

    op.drop_index(
        "cdc_subaward_state_summary_awarding_sub_agency_idx",
        table_name="subaward_state_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_subaward_state_summary_funding_office_idx",
        table_name="subaward_state_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_subaward_state_summary_awarding_office_idx",
        table_name="subaward_state_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_subaward_state_summary_fiscal_year_idx",
        table_name="subaward_state_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_subaward_state_summary_geography_idx",
        table_name="subaward_state_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_table("subaward_state_summary", schema=CDC_FUNDING_SCHEMA)

    op.drop_index(
        "cdc_prime_county_summary_awarding_sub_agency_idx",
        table_name="prime_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_county_summary_funding_office_idx",
        table_name="prime_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_county_summary_awarding_office_idx",
        table_name="prime_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_county_summary_assistance_type_idx",
        table_name="prime_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_county_summary_fiscal_year_idx",
        table_name="prime_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_county_summary_state_code_idx",
        table_name="prime_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_county_summary_geography_idx",
        table_name="prime_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_table("prime_county_summary", schema=CDC_FUNDING_SCHEMA)

    op.drop_index(
        "cdc_prime_state_summary_awarding_sub_agency_idx",
        table_name="prime_state_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_state_summary_funding_office_idx",
        table_name="prime_state_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_state_summary_awarding_office_idx",
        table_name="prime_state_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_state_summary_assistance_type_idx",
        table_name="prime_state_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_state_summary_fiscal_year_idx",
        table_name="prime_state_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_state_summary_geography_idx",
        table_name="prime_state_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_table("prime_state_summary", schema=CDC_FUNDING_SCHEMA)

    op.drop_index("cdc_subawards_searchable_text_idx", table_name="subawards", schema=CDC_FUNDING_SCHEMA)
    op.drop_index("cdc_subawards_raw_gin_idx", table_name="subawards", schema=CDC_FUNDING_SCHEMA)
    op.drop_index("cdc_subawards_funding_sub_agency_idx", table_name="subawards", schema=CDC_FUNDING_SCHEMA)
    op.drop_index("cdc_subawards_awarding_sub_agency_idx", table_name="subawards", schema=CDC_FUNDING_SCHEMA)
    op.drop_index("cdc_subawards_funding_office_idx", table_name="subawards", schema=CDC_FUNDING_SCHEMA)
    op.drop_index("cdc_subawards_awarding_office_idx", table_name="subawards", schema=CDC_FUNDING_SCHEMA)
    op.drop_index("cdc_subawards_fiscal_year_idx", table_name="subawards", schema=CDC_FUNDING_SCHEMA)
    op.drop_index("cdc_subawards_county_fips_idx", table_name="subawards", schema=CDC_FUNDING_SCHEMA)
    op.drop_index("cdc_subawards_state_code_idx", table_name="subawards", schema=CDC_FUNDING_SCHEMA)
    op.drop_index("cdc_subawards_prime_award_fain_idx", table_name="subawards", schema=CDC_FUNDING_SCHEMA)
    op.drop_index("cdc_subawards_prime_award_unique_key_idx", table_name="subawards", schema=CDC_FUNDING_SCHEMA)
    op.drop_table("subawards", schema=CDC_FUNDING_SCHEMA)

    op.drop_index("cdc_prime_awards_searchable_text_idx", table_name="prime_awards", schema=CDC_FUNDING_SCHEMA)
    op.drop_index("cdc_prime_awards_raw_gin_idx", table_name="prime_awards", schema=CDC_FUNDING_SCHEMA)
    op.drop_index("cdc_prime_awards_funding_sub_agency_idx", table_name="prime_awards", schema=CDC_FUNDING_SCHEMA)
    op.drop_index("cdc_prime_awards_awarding_sub_agency_idx", table_name="prime_awards", schema=CDC_FUNDING_SCHEMA)
    op.drop_index("cdc_prime_awards_funding_office_idx", table_name="prime_awards", schema=CDC_FUNDING_SCHEMA)
    op.drop_index("cdc_prime_awards_awarding_office_idx", table_name="prime_awards", schema=CDC_FUNDING_SCHEMA)
    op.drop_index("cdc_prime_awards_assistance_type_idx", table_name="prime_awards", schema=CDC_FUNDING_SCHEMA)
    op.drop_index("cdc_prime_awards_fiscal_year_idx", table_name="prime_awards", schema=CDC_FUNDING_SCHEMA)
    op.drop_index("cdc_prime_awards_recipient_county_fips_idx", table_name="prime_awards", schema=CDC_FUNDING_SCHEMA)
    op.drop_index("cdc_prime_awards_recipient_state_code_idx", table_name="prime_awards", schema=CDC_FUNDING_SCHEMA)
    op.drop_index("cdc_prime_awards_fain_idx", table_name="prime_awards", schema=CDC_FUNDING_SCHEMA)
    op.drop_table("prime_awards", schema=CDC_FUNDING_SCHEMA)

    op.execute(f"DROP SCHEMA IF EXISTS {CDC_FUNDING_SCHEMA}")
