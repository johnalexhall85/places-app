"""add usaspending federal account ingestion layer

Revision ID: f4a9c2d7e6b1
Revises: e2f4a7b9c8d1
Create Date: 2026-04-24 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f4a9c2d7e6b1"
down_revision: Union[str, None] = "e2f4a7b9c8d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "usaspending_fed_account"


def _create_reconciliation_view() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE VIEW {SCHEMA}.v_account_reconciliation AS
        WITH balance AS (
            SELECT
                fiscal_year,
                federal_account_id,
                SUM(COALESCE(obligations_incurred_amount, 0))::numeric(18, 2) AS balance_obligations
            FROM {SCHEMA}.fact_account_balance
            GROUP BY fiscal_year, federal_account_id
        ),
        awards AS (
            SELECT
                fiscal_year,
                federal_account_id,
                SUM(COALESCE(obligation_amount, transaction_obligated_amount, 0))::numeric(18, 2)
                    AS award_obligations_total,
                SUM(
                    CASE WHEN award_source_type = 'assistance'
                        THEN COALESCE(obligation_amount, transaction_obligated_amount, 0)
                        ELSE 0
                    END
                )::numeric(18, 2) AS assistance_award_obligations,
                SUM(
                    CASE WHEN award_source_type = 'contracts'
                        THEN COALESCE(obligation_amount, transaction_obligated_amount, 0)
                        ELSE 0
                    END
                )::numeric(18, 2) AS contracts_award_obligations,
                SUM(
                    CASE WHEN award_source_type = 'unlinked'
                        THEN COALESCE(obligation_amount, transaction_obligated_amount, 0)
                        ELSE 0
                    END
                )::numeric(18, 2) AS unlinked_award_obligations,
                COUNT(*)::integer AS record_count_awards
            FROM {SCHEMA}.fact_award_account_breakdown
            GROUP BY fiscal_year, federal_account_id
        ),
        pa_oc AS (
            SELECT
                fiscal_year,
                federal_account_id,
                SUM(COALESCE(obligations_incurred_amount, 0))::numeric(18, 2) AS pa_oc_obligations_total,
                COUNT(*)::integer AS record_count_pa_oc
            FROM {SCHEMA}.fact_account_pa_oc
            GROUP BY fiscal_year, federal_account_id
        ),
        account_years AS (
            SELECT fiscal_year, federal_account_id FROM balance
            UNION
            SELECT fiscal_year, federal_account_id FROM awards
            UNION
            SELECT fiscal_year, federal_account_id FROM pa_oc
        )
        SELECT
            account_years.fiscal_year,
            account_years.federal_account_id,
            dim.normalized_account_key,
            dim.federal_account_name,
            COALESCE(balance.balance_obligations, 0)::numeric(18, 2) AS balance_obligations,
            COALESCE(awards.award_obligations_total, 0)::numeric(18, 2) AS award_obligations_total,
            COALESCE(awards.assistance_award_obligations, 0)::numeric(18, 2)
                AS assistance_award_obligations,
            COALESCE(awards.contracts_award_obligations, 0)::numeric(18, 2)
                AS contracts_award_obligations,
            COALESCE(awards.unlinked_award_obligations, 0)::numeric(18, 2)
                AS unlinked_award_obligations,
            COALESCE(pa_oc.pa_oc_obligations_total, 0)::numeric(18, 2) AS pa_oc_obligations_total,
            (
                COALESCE(balance.balance_obligations, 0)
                - COALESCE(awards.award_obligations_total, 0)
            )::numeric(18, 2) AS balance_minus_awards,
            (
                COALESCE(balance.balance_obligations, 0)
                - COALESCE(pa_oc.pa_oc_obligations_total, 0)
            )::numeric(18, 2) AS balance_minus_pa_oc,
            CASE
                WHEN NULLIF(balance.balance_obligations, 0) IS NULL THEN NULL
                ELSE ROUND(
                    (COALESCE(awards.award_obligations_total, 0) / NULLIF(balance.balance_obligations, 0)) * 100,
                    4
                )
            END AS award_match_percent_of_balance,
            CASE
                WHEN NULLIF(balance.balance_obligations, 0) IS NULL THEN NULL
                ELSE ROUND(
                    (COALESCE(pa_oc.pa_oc_obligations_total, 0) / NULLIF(balance.balance_obligations, 0)) * 100,
                    4
                )
            END AS pa_oc_match_percent_of_balance,
            COALESCE(awards.record_count_awards, 0)::integer AS record_count_awards,
            COALESCE(pa_oc.record_count_pa_oc, 0)::integer AS record_count_pa_oc
        FROM account_years
        LEFT JOIN {SCHEMA}.dim_federal_account AS dim
            ON dim.id = account_years.federal_account_id
        LEFT JOIN balance
            ON balance.fiscal_year = account_years.fiscal_year
           AND balance.federal_account_id IS NOT DISTINCT FROM account_years.federal_account_id
        LEFT JOIN awards
            ON awards.fiscal_year = account_years.fiscal_year
           AND awards.federal_account_id IS NOT DISTINCT FROM account_years.federal_account_id
        LEFT JOIN pa_oc
            ON pa_oc.fiscal_year = account_years.fiscal_year
           AND pa_oc.federal_account_id IS NOT DISTINCT FROM account_years.federal_account_id
        """
    )


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.raw_file_registry (
            id serial PRIMARY KEY,
            fiscal_year integer NOT NULL,
            file_path text NOT NULL,
            file_name text NOT NULL,
            dataset_type text NOT NULL,
            source_agency_code text,
            period_label text,
            downloaded_at_from_filename timestamptz,
            row_count integer,
            file_hash text NOT NULL,
            ingested_at timestamptz NOT NULL DEFAULT now(),
            notes text,
            CONSTRAINT ck_ufa_raw_file_registry_dataset_type CHECK (
                dataset_type IN (
                    'assistance_award_breakdown',
                    'contracts_award_breakdown',
                    'unlinked_award_breakdown',
                    'account_balances',
                    'pa_oc_breakdown',
                    'unknown'
                )
            ),
            CONSTRAINT uq_ufa_raw_file_registry_file_hash UNIQUE (file_hash),
            CONSTRAINT uq_ufa_raw_file_registry_file_path UNIQUE (file_path)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.dim_federal_account (
            id serial PRIMARY KEY,
            agency_identifier text,
            allocation_transfer_agency_identifier text,
            main_account_code text,
            sub_account_code text,
            treasury_account_symbol text,
            federal_account_symbol text,
            federal_account_name text,
            account_title text,
            agency_name text,
            bureau_name text,
            normalized_account_key text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_ufa_dim_account_key UNIQUE (normalized_account_key)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.fact_account_balance (
            id bigserial PRIMARY KEY,
            fiscal_year integer NOT NULL,
            federal_account_id integer NOT NULL REFERENCES {SCHEMA}.dim_federal_account(id) ON DELETE CASCADE,
            raw_file_id integer NOT NULL REFERENCES {SCHEMA}.raw_file_registry(id) ON DELETE CASCADE,
            budget_authority_amount numeric(18, 2),
            obligations_incurred_amount numeric(18, 2),
            outlay_amount numeric(18, 2),
            unobligated_balance_amount numeric(18, 2),
            gross_outlay_amount numeric(18, 2),
            total_budgetary_resources_amount numeric(18, 2),
            other_amount_json jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            raw_row_json jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.fact_account_pa_oc (
            id bigserial PRIMARY KEY,
            fiscal_year integer NOT NULL,
            federal_account_id integer NOT NULL REFERENCES {SCHEMA}.dim_federal_account(id) ON DELETE CASCADE,
            raw_file_id integer NOT NULL REFERENCES {SCHEMA}.raw_file_registry(id) ON DELETE CASCADE,
            program_activity_code text,
            program_activity_name text,
            object_class_code text,
            object_class_name text,
            direct_or_reimbursable text,
            obligations_incurred_amount numeric(18, 2),
            outlay_amount numeric(18, 2),
            raw_amount_json jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            raw_row_json jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.fact_award_account_breakdown (
            id bigserial PRIMARY KEY,
            fiscal_year integer NOT NULL,
            federal_account_id integer REFERENCES {SCHEMA}.dim_federal_account(id) ON DELETE SET NULL,
            raw_file_id integer NOT NULL REFERENCES {SCHEMA}.raw_file_registry(id) ON DELETE CASCADE,
            award_source_type text NOT NULL,
            award_id text,
            generated_unique_award_id text,
            piid text,
            fain text,
            uri text,
            assistance_listing_number text,
            recipient_name text,
            recipient_uei text,
            recipient_state_code text,
            recipient_county_name text,
            recipient_county_fips text,
            place_of_performance_state_code text,
            place_of_performance_county_name text,
            place_of_performance_county_fips text,
            awarding_agency_code text,
            awarding_agency_name text,
            funding_agency_code text,
            funding_agency_name text,
            awarding_subagency_name text,
            funding_subagency_name text,
            obligation_amount numeric(18, 2),
            outlay_amount numeric(18, 2),
            transaction_obligated_amount numeric(18, 2),
            action_date date,
            period_of_performance_start_date date,
            period_of_performance_current_end_date date,
            cfda_title text,
            award_description text,
            naics_code text,
            naics_description text,
            psc_code text,
            psc_description text,
            raw_amount_json jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            raw_row_json jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_ufa_award_account_source_type CHECK (
                award_source_type IN ('assistance', 'contracts', 'unlinked')
            )
        )
        """
    )

    for index_sql in (
        f"CREATE INDEX IF NOT EXISTS ufa_raw_file_registry_fy_idx ON {SCHEMA}.raw_file_registry (fiscal_year)",
        f"CREATE INDEX IF NOT EXISTS ufa_raw_file_registry_type_idx ON {SCHEMA}.raw_file_registry (dataset_type)",
        f"CREATE INDEX IF NOT EXISTS ufa_dim_federal_account_symbol_idx ON {SCHEMA}.dim_federal_account (federal_account_symbol)",
        f"CREATE INDEX IF NOT EXISTS ufa_dim_federal_account_name_idx ON {SCHEMA}.dim_federal_account (federal_account_name)",
        f"CREATE INDEX IF NOT EXISTS ufa_balance_fy_idx ON {SCHEMA}.fact_account_balance (fiscal_year)",
        f"CREATE INDEX IF NOT EXISTS ufa_balance_account_idx ON {SCHEMA}.fact_account_balance (federal_account_id)",
        f"CREATE INDEX IF NOT EXISTS ufa_balance_raw_file_idx ON {SCHEMA}.fact_account_balance (raw_file_id)",
        f"CREATE INDEX IF NOT EXISTS ufa_pa_oc_fy_idx ON {SCHEMA}.fact_account_pa_oc (fiscal_year)",
        f"CREATE INDEX IF NOT EXISTS ufa_pa_oc_account_idx ON {SCHEMA}.fact_account_pa_oc (federal_account_id)",
        f"CREATE INDEX IF NOT EXISTS ufa_pa_oc_raw_file_idx ON {SCHEMA}.fact_account_pa_oc (raw_file_id)",
        f"CREATE INDEX IF NOT EXISTS ufa_pa_oc_program_idx ON {SCHEMA}.fact_account_pa_oc (program_activity_code)",
        f"CREATE INDEX IF NOT EXISTS ufa_pa_oc_object_idx ON {SCHEMA}.fact_account_pa_oc (object_class_code)",
        f"CREATE INDEX IF NOT EXISTS ufa_award_fy_idx ON {SCHEMA}.fact_award_account_breakdown (fiscal_year)",
        f"CREATE INDEX IF NOT EXISTS ufa_award_account_idx ON {SCHEMA}.fact_award_account_breakdown (federal_account_id)",
        f"CREATE INDEX IF NOT EXISTS ufa_award_guid_idx ON {SCHEMA}.fact_award_account_breakdown (generated_unique_award_id)",
        f"CREATE INDEX IF NOT EXISTS ufa_award_fain_idx ON {SCHEMA}.fact_award_account_breakdown (fain)",
        f"CREATE INDEX IF NOT EXISTS ufa_award_piid_idx ON {SCHEMA}.fact_award_account_breakdown (piid)",
        f"CREATE INDEX IF NOT EXISTS ufa_award_recipient_state_idx ON {SCHEMA}.fact_award_account_breakdown (recipient_state_code)",
        f"CREATE INDEX IF NOT EXISTS ufa_award_recipient_county_idx ON {SCHEMA}.fact_award_account_breakdown (recipient_county_fips)",
        f"CREATE INDEX IF NOT EXISTS ufa_award_pop_state_idx ON {SCHEMA}.fact_award_account_breakdown (place_of_performance_state_code)",
        f"CREATE INDEX IF NOT EXISTS ufa_award_pop_county_idx ON {SCHEMA}.fact_award_account_breakdown (place_of_performance_county_fips)",
        f"CREATE INDEX IF NOT EXISTS ufa_award_source_type_idx ON {SCHEMA}.fact_award_account_breakdown (award_source_type)",
        f"CREATE INDEX IF NOT EXISTS ufa_award_raw_file_idx ON {SCHEMA}.fact_award_account_breakdown (raw_file_id)",
    ):
        op.execute(index_sql)

    _create_reconciliation_view()


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {SCHEMA}.v_account_reconciliation")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.fact_award_account_breakdown")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.fact_account_pa_oc")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.fact_account_balance")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.dim_federal_account")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.raw_file_registry")
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")

