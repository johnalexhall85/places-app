"""add usaspending funding map rebuild tables

Revision ID: a8f3c2d1e9b4
Revises: 5a9d7c2e4b18
Create Date: 2026-07-03 22:15:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a8f3c2d1e9b4"
down_revision: Union[str, None] = "5a9d7c2e4b18"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "cdc_funding"

RAW_TABLES = (
    "raw_usaspending_assistance_prime_transactions",
    "raw_usaspending_assistance_subawards",
    "raw_usaspending_contracts_prime_transactions",
    "raw_usaspending_contracts_subawards",
)


def _create_raw_table(table_name: str, prefix: str) -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.{table_name} (
            id bigserial PRIMARY KEY,
            source_fiscal_year integer NOT NULL,
            source_file_type text NOT NULL,
            source_file_path text NOT NULL,
            source_file_name text NOT NULL,
            source_row_number integer NOT NULL,
            row_hash text NOT NULL,
            ingested_at timestamptz NOT NULL DEFAULT now(),
            raw_record jsonb NOT NULL,
            CONSTRAINT {prefix}_source_row_uq UNIQUE (
                source_fiscal_year,
                source_file_type,
                source_file_name,
                source_row_number
            )
        )
        """
    )
    op.execute(f"CREATE INDEX {prefix}_row_hash_idx ON {SCHEMA}.{table_name} (row_hash)")


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    _create_raw_table("raw_usaspending_assistance_prime_transactions", "raw_usa_asst_prime")
    _create_raw_table("raw_usaspending_assistance_subawards", "raw_usa_asst_sub")
    _create_raw_table("raw_usaspending_contracts_prime_transactions", "raw_usa_cont_prime")
    _create_raw_table("raw_usaspending_contracts_subawards", "raw_usa_cont_sub")

    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.fact_cdc_funding_prime_transaction (
            id bigserial PRIMARY KEY,
            source_raw_table text NOT NULL,
            source_raw_id bigint NOT NULL,
            source_fiscal_year integer NOT NULL,
            source_file_type text NOT NULL,
            source_file_name text,
            source_row_number integer,
            row_hash text,

            funding_mechanism text NOT NULL,
            transaction_unique_key text,
            award_unique_key text,
            generated_unique_award_id text,
            award_id_piid text,
            parent_award_id text,
            modification_number text,

            federal_action_obligation numeric,
            action_date date,
            action_date_fiscal_year integer,

            funding_agency_name text,
            funding_sub_agency_name text,
            funding_office_name text,
            awarding_agency_name text,
            awarding_sub_agency_name text,
            awarding_office_name text,

            recipient_uei text,
            recipient_name text,
            recipient_parent_uei text,
            recipient_parent_name text,
            recipient_country_code text,
            recipient_state_code text,
            recipient_state_name text,
            recipient_county_name text,
            recipient_county_fips text,
            recipient_zip text,

            pop_country_code text,
            pop_state_code text,
            pop_state_name text,
            pop_county_name text,
            pop_county_fips text,
            pop_zip text,

            map_state_code text,
            map_state_name text,
            map_county_name text,
            map_county_fips text,
            map_geography_source text NOT NULL,

            federal_accounts_funding_this_award text,
            treasury_accounts_funding_this_award text,
            object_classes_funding_this_award text,
            program_activities_funding_this_award text,

            assistance_listing_number text,
            assistance_listing_title text,

            award_type_code text,
            award_type_description text,
            assistance_type_code text,
            assistance_type_description text,

            naics_code text,
            naics_description text,
            product_or_service_code text,
            product_or_service_code_description text,
            national_interest_action_code text,
            national_interest_action text,

            transaction_description text,
            prime_award_base_transaction_description text,
            usaspending_permalink text,
            last_modified_date timestamp NULL,

            covid_supplemental_obligated_amount numeric DEFAULT 0,
            iija_supplemental_obligated_amount numeric DEFAULT 0,
            other_supplemental_obligated_amount numeric DEFAULT 0,
            is_covid_or_emergency_supplemental boolean NOT NULL DEFAULT false,

            is_positive_obligation boolean NOT NULL DEFAULT false,
            is_cdc_funded boolean NOT NULL DEFAULT false,
            is_prime_award boolean NOT NULL DEFAULT true,
            is_default_map_eligible boolean NOT NULL DEFAULT false,

            skip_reason text,
            raw_record jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT fact_cdc_funding_prime_source_uq UNIQUE (source_raw_table, source_raw_id),
            CONSTRAINT fact_cdc_funding_prime_mechanism_ck CHECK (
                funding_mechanism IN ('grants_cooperative_agreements', 'contracts')
            ),
            CONSTRAINT fact_cdc_funding_prime_geo_source_ck CHECK (
                map_geography_source IN ('place_of_performance', 'recipient_fallback', 'unmapped')
            )
        )
        """
    )

    for column in (
        "source_fiscal_year",
        "funding_mechanism",
        "map_county_fips",
        "map_state_code",
        "federal_action_obligation",
        "is_default_map_eligible",
        "is_covid_or_emergency_supplemental",
        "assistance_listing_number",
        "recipient_name",
        "award_unique_key",
        "transaction_unique_key",
        "row_hash",
    ):
        op.execute(
            f"CREATE INDEX fact_cdc_funding_prime_{column}_idx "
            f"ON {SCHEMA}.fact_cdc_funding_prime_transaction ({column})"
        )

    op.execute(
        f"""
        CREATE MATERIALIZED VIEW {SCHEMA}.mv_cdc_funding_map_county AS
        SELECT
            source_fiscal_year,
            funding_mechanism,
            map_state_code,
            map_state_name,
            map_county_fips,
            map_county_name,
            assistance_listing_number,
            assistance_listing_title,
            is_covid_or_emergency_supplemental,
            SUM(COALESCE(federal_action_obligation, 0)) AS total_obligations,
            COUNT(*)::bigint AS transaction_count,
            COUNT(DISTINCT COALESCE(
                NULLIF(award_unique_key, ''),
                NULLIF(generated_unique_award_id, ''),
                NULLIF(award_id_piid, ''),
                source_raw_table || ':' || source_raw_id::text
            ))::bigint AS award_count,
            COUNT(DISTINCT COALESCE(
                NULLIF(recipient_uei, ''),
                NULLIF(recipient_name, '')
            ))::bigint AS recipient_count
        FROM {SCHEMA}.fact_cdc_funding_prime_transaction
        WHERE is_default_map_eligible IS TRUE
        GROUP BY
            source_fiscal_year,
            funding_mechanism,
            map_state_code,
            map_state_name,
            map_county_fips,
            map_county_name,
            assistance_listing_number,
            assistance_listing_title,
            is_covid_or_emergency_supplemental
        WITH NO DATA
        """
    )

    for column in (
        "source_fiscal_year",
        "funding_mechanism",
        "map_county_fips",
        "map_state_code",
        "assistance_listing_number",
    ):
        op.execute(
            f"CREATE INDEX mv_cdc_funding_map_county_{column}_idx "
            f"ON {SCHEMA}.mv_cdc_funding_map_county ({column})"
        )


def downgrade() -> None:
    op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {SCHEMA}.mv_cdc_funding_map_county")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.fact_cdc_funding_prime_transaction")
    for table_name in reversed(RAW_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.{table_name}")
