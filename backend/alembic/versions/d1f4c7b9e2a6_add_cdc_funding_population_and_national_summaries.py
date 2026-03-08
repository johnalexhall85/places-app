"""add cdc funding population and national summaries

Revision ID: d1f4c7b9e2a6
Revises: f6a2b9d4c8e1
Create Date: 2026-03-08 10:15:00.000000

"""

from __future__ import annotations

import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d1f4c7b9e2a6"
down_revision: Union[str, None] = "f6a2b9d4c8e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CDC_FUNDING_SCHEMA = "cdc_funding"
PLACES_SCHEMA = os.getenv("PLACES_SCHEMA", "public").strip() or "public"
POPULATION_VIEW_NAME = "v_geography_population"


def upgrade() -> None:
    # Reuse existing dim_county population denominators for county/state/nation.
    op.execute(
        f"""
        CREATE OR REPLACE VIEW {PLACES_SCHEMA}.{POPULATION_VIEW_NAME} AS
        WITH county_population AS (
            SELECT
                c.location_id AS county_fips,
                c.state_abbr,
                c.total_population::numeric AS population
            FROM {PLACES_SCHEMA}.dim_county AS c
            WHERE c.location_id ~ '^[0-9]{{5}}$'
              AND c.total_population IS NOT NULL
              AND c.total_population > 0
        ),
        state_population AS (
            SELECT
                SUBSTRING(cp.county_fips FROM 1 FOR 2) AS state_fips,
                MAX(cp.state_abbr) AS state_abbr,
                SUM(cp.population)::numeric AS population
            FROM county_population AS cp
            GROUP BY SUBSTRING(cp.county_fips FROM 1 FOR 2)
        ),
        nation_population AS (
            SELECT SUM(cp.population)::numeric AS population
            FROM county_population AS cp
        )
        SELECT
            'nation'::text AS geography_type,
            'US'::text AS geography_id,
            np.population,
            NULL::integer AS source_year,
            'Derived from dim_county.total_population'::text AS source_label,
            NULL::text AS state_abbr
        FROM nation_population AS np
        UNION ALL
        SELECT
            'state'::text AS geography_type,
            sp.state_fips AS geography_id,
            sp.population,
            NULL::integer AS source_year,
            'Derived from dim_county.total_population'::text AS source_label,
            sp.state_abbr
        FROM state_population AS sp
        UNION ALL
        SELECT
            'county'::text AS geography_type,
            cp.county_fips AS geography_id,
            cp.population,
            NULL::integer AS source_year,
            'Derived from dim_county.total_population'::text AS source_label,
            cp.state_abbr
        FROM county_population AS cp
        """
    )

    for table_name in (
        "prime_transaction_state_summary",
        "prime_transaction_county_summary",
        "prime_transaction_county_summary_allocated",
    ):
        op.add_column(
            table_name,
            sa.Column("population", sa.Numeric(18, 0), nullable=True),
            schema=CDC_FUNDING_SCHEMA,
        )
        op.add_column(
            table_name,
            sa.Column(
                "total_funding_amount",
                sa.Numeric(18, 2),
                nullable=False,
                server_default=sa.text("0"),
            ),
            schema=CDC_FUNDING_SCHEMA,
        )
        op.add_column(
            table_name,
            sa.Column("funding_per_capita", sa.Numeric(18, 6), nullable=True),
            schema=CDC_FUNDING_SCHEMA,
        )
        op.add_column(
            table_name,
            sa.Column("fy_obligated_per_capita", sa.Numeric(18, 6), nullable=True),
            schema=CDC_FUNDING_SCHEMA,
        )
        op.add_column(
            table_name,
            sa.Column("fy_outlayed_amount_estimated_per_capita", sa.Numeric(18, 6), nullable=True),
            schema=CDC_FUNDING_SCHEMA,
        )

    for table_name in (
        "subaward_state_summary",
        "subaward_county_summary",
    ):
        op.add_column(
            table_name,
            sa.Column("population", sa.Numeric(18, 0), nullable=True),
            schema=CDC_FUNDING_SCHEMA,
        )
        op.add_column(
            table_name,
            sa.Column("funding_per_capita", sa.Numeric(18, 6), nullable=True),
            schema=CDC_FUNDING_SCHEMA,
        )
        op.add_column(
            table_name,
            sa.Column("total_subaward_per_capita", sa.Numeric(18, 6), nullable=True),
            schema=CDC_FUNDING_SCHEMA,
        )

    op.create_table(
        "prime_transaction_national_summary",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("geography_id", sa.String(length=2), nullable=False),
        sa.Column("geography_name", sa.Text(), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("assistance_type_description", sa.Text(), nullable=True),
        sa.Column("awarding_sub_agency_name", sa.Text(), nullable=True),
        sa.Column("funding_sub_agency_name", sa.Text(), nullable=True),
        sa.Column("awarding_office_name", sa.Text(), nullable=True),
        sa.Column("funding_office_name", sa.Text(), nullable=True),
        sa.Column("appropriation_type", sa.String(length=32), nullable=True),
        sa.Column("population", sa.Numeric(18, 0), nullable=True),
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
        sa.Column(
            "total_funding_amount",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("transaction_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("distinct_award_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("funding_per_capita", sa.Numeric(18, 6), nullable=True),
        sa.Column("fy_obligated_per_capita", sa.Numeric(18, 6), nullable=True),
        sa.Column("fy_outlayed_amount_estimated_per_capita", sa.Numeric(18, 6), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_national_summary_geography_idx",
        "prime_transaction_national_summary",
        ["geography_id"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_national_summary_fiscal_year_idx",
        "prime_transaction_national_summary",
        ["fiscal_year"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_national_summary_assistance_type_idx",
        "prime_transaction_national_summary",
        ["assistance_type_description"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_national_summary_awarding_office_idx",
        "prime_transaction_national_summary",
        ["awarding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_national_summary_funding_office_idx",
        "prime_transaction_national_summary",
        ["funding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_national_summary_awarding_sub_agency_idx",
        "prime_transaction_national_summary",
        ["awarding_sub_agency_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_national_summary_appropriation_type_idx",
        "prime_transaction_national_summary",
        ["appropriation_type"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )

    op.create_table(
        "subaward_national_summary",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("geography_id", sa.String(length=2), nullable=False),
        sa.Column("geography_name", sa.Text(), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("awarding_sub_agency_name", sa.Text(), nullable=True),
        sa.Column("funding_sub_agency_name", sa.Text(), nullable=True),
        sa.Column("awarding_office_name", sa.Text(), nullable=True),
        sa.Column("funding_office_name", sa.Text(), nullable=True),
        sa.Column("appropriation_type", sa.String(length=32), nullable=True),
        sa.Column("population", sa.Numeric(18, 0), nullable=True),
        sa.Column(
            "total_funding_amount",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total_obligated_amount",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total_outlayed_amount",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("award_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "total_subaward_amount",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("subaward_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("funding_per_capita", sa.Numeric(18, 6), nullable=True),
        sa.Column("total_subaward_per_capita", sa.Numeric(18, 6), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subaward_national_summary_geography_idx",
        "subaward_national_summary",
        ["geography_id"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subaward_national_summary_fiscal_year_idx",
        "subaward_national_summary",
        ["fiscal_year"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subaward_national_summary_awarding_office_idx",
        "subaward_national_summary",
        ["awarding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subaward_national_summary_funding_office_idx",
        "subaward_national_summary",
        ["funding_office_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subaward_national_summary_awarding_sub_agency_idx",
        "subaward_national_summary",
        ["awarding_sub_agency_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subaward_national_summary_appropriation_type_idx",
        "subaward_national_summary",
        ["appropriation_type"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "cdc_subaward_national_summary_appropriation_type_idx",
        table_name="subaward_national_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_subaward_national_summary_awarding_sub_agency_idx",
        table_name="subaward_national_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_subaward_national_summary_funding_office_idx",
        table_name="subaward_national_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_subaward_national_summary_awarding_office_idx",
        table_name="subaward_national_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_subaward_national_summary_fiscal_year_idx",
        table_name="subaward_national_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_subaward_national_summary_geography_idx",
        table_name="subaward_national_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_table("subaward_national_summary", schema=CDC_FUNDING_SCHEMA)

    op.drop_index(
        "cdc_prime_tx_national_summary_appropriation_type_idx",
        table_name="prime_transaction_national_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_national_summary_awarding_sub_agency_idx",
        table_name="prime_transaction_national_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_national_summary_funding_office_idx",
        table_name="prime_transaction_national_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_national_summary_awarding_office_idx",
        table_name="prime_transaction_national_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_national_summary_assistance_type_idx",
        table_name="prime_transaction_national_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_national_summary_fiscal_year_idx",
        table_name="prime_transaction_national_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_prime_tx_national_summary_geography_idx",
        table_name="prime_transaction_national_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_table("prime_transaction_national_summary", schema=CDC_FUNDING_SCHEMA)

    for table_name in (
        "subaward_county_summary",
        "subaward_state_summary",
    ):
        op.drop_column(table_name, "total_subaward_per_capita", schema=CDC_FUNDING_SCHEMA)
        op.drop_column(table_name, "funding_per_capita", schema=CDC_FUNDING_SCHEMA)
        op.drop_column(table_name, "population", schema=CDC_FUNDING_SCHEMA)

    for table_name in (
        "prime_transaction_county_summary_allocated",
        "prime_transaction_county_summary",
        "prime_transaction_state_summary",
    ):
        op.drop_column(table_name, "fy_outlayed_amount_estimated_per_capita", schema=CDC_FUNDING_SCHEMA)
        op.drop_column(table_name, "fy_obligated_per_capita", schema=CDC_FUNDING_SCHEMA)
        op.drop_column(table_name, "funding_per_capita", schema=CDC_FUNDING_SCHEMA)
        op.drop_column(table_name, "total_funding_amount", schema=CDC_FUNDING_SCHEMA)
        op.drop_column(table_name, "population", schema=CDC_FUNDING_SCHEMA)

    op.execute(f"DROP VIEW IF EXISTS {PLACES_SCHEMA}.{POPULATION_VIEW_NAME}")
