"""add chip v1 funding map materialized views

Revision ID: 5a9d7c2e4b18
Revises: 2a7c9d0e5f61
Create Date: 2026-04-26 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "5a9d7c2e4b18"
down_revision: Union[str, None] = "2a7c9d0e5f61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "usaspending_fed_account"


def _classified_awards_cte() -> str:
    return f"""
        WITH classified_awards AS (
            SELECT
                award.id AS award_row_id,
                award.fiscal_year,
                award.award_source_type,
                COALESCE(
                    award.generated_unique_award_id,
                    award.award_id,
                    award.fain,
                    award.piid,
                    award.uri,
                    award.id::text
                ) AS award_key,
                COALESCE(award.obligation_amount, award.transaction_obligated_amount, 0)::numeric AS obligation_amount,
                classification.federal_account_id,
                classification.normalized_account_key,
                classification.review_status,
                classification.classification_version,
                COALESCE(
                    NULLIF(UPPER(BTRIM(award.place_of_performance_state_code)), ''),
                    NULLIF(UPPER(BTRIM(award.recipient_state_code)), '')
                ) AS state_code,
                COALESCE(
                    CASE
                        WHEN regexp_replace(COALESCE(award.place_of_performance_county_fips, ''), '[^0-9]', '', 'g') ~ '^[0-9]{{1,5}}$'
                            THEN LPAD(regexp_replace(COALESCE(award.place_of_performance_county_fips, ''), '[^0-9]', '', 'g'), 5, '0')
                        ELSE NULL
                    END,
                    CASE
                        WHEN regexp_replace(COALESCE(award.recipient_county_fips, ''), '[^0-9]', '', 'g') ~ '^[0-9]{{1,5}}$'
                            THEN LPAD(regexp_replace(COALESCE(award.recipient_county_fips, ''), '[^0-9]', '', 'g'), 5, '0')
                        ELSE NULL
                    END
                ) AS county_fips
            FROM {SCHEMA}.fact_award_account_breakdown AS award
            LEFT JOIN {SCHEMA}.dim_federal_account AS dim
              ON dim.id = award.federal_account_id
            JOIN {SCHEMA}.chip_account_classification AS classification
             ON classification.fiscal_year = award.fiscal_year
             AND (
                    classification.normalized_account_key = dim.normalized_account_key
                 OR (
                        classification.federal_account_id IS NOT NULL
                    AND classification.federal_account_id = award.federal_account_id
                 )
             )
            WHERE classification.is_cdc_related IS TRUE
              AND classification.review_status IS DISTINCT FROM 'rejected'
              AND (
                    classification.include_in_public_map IS TRUE
                 OR classification.include_in_chip_baseline IS TRUE
              )
              AND award.award_source_type IN ('assistance', 'contracts', 'unlinked')
        )
    """


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS chip_account_classification_map_lookup_idx
        ON {SCHEMA}.chip_account_classification (
            classification_version,
            fiscal_year,
            normalized_account_key
        )
        WHERE is_cdc_related IS TRUE
          AND review_status IS DISTINCT FROM 'rejected'
          AND (
                include_in_public_map IS TRUE
             OR include_in_chip_baseline IS TRUE
          )
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS chip_account_classification_map_account_id_idx
        ON {SCHEMA}.chip_account_classification (
            classification_version,
            fiscal_year,
            federal_account_id
        )
        WHERE federal_account_id IS NOT NULL
          AND is_cdc_related IS TRUE
          AND review_status IS DISTINCT FROM 'rejected'
          AND (
                include_in_public_map IS TRUE
             OR include_in_chip_baseline IS TRUE
          )
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ufa_award_fy_account_source_chip_map_idx
        ON {SCHEMA}.fact_award_account_breakdown (
            fiscal_year,
            federal_account_id,
            award_source_type
        )
        """
    )
    op.execute(
        f"""
        CREATE MATERIALIZED VIEW {SCHEMA}.mv_chip_v1_state_funding_map AS
        {_classified_awards_cte()}
        SELECT
            fiscal_year,
            state_code,
            'chip_account_classification_v1'::text AS funding_model,
            classification_version,
            'CDC Baseline/Public Map'::text AS funding_scope_label,
            COALESCE(SUM(obligation_amount), 0)::numeric(20, 2) AS total_obligations,
            COALESCE(SUM(obligation_amount) FILTER (WHERE award_source_type = 'assistance'), 0)::numeric(20, 2)
                AS assistance_obligations,
            COALESCE(SUM(obligation_amount) FILTER (WHERE award_source_type = 'contracts'), 0)::numeric(20, 2)
                AS contracts_obligations,
            COALESCE(SUM(obligation_amount) FILTER (WHERE award_source_type = 'unlinked'), 0)::numeric(20, 2)
                AS unlinked_obligations,
            COALESCE(SUM(obligation_amount) FILTER (WHERE review_status = 'needs_review'), 0)::numeric(20, 2)
                AS needs_review_obligations,
            COALESCE(SUM(obligation_amount) FILTER (WHERE review_status IS DISTINCT FROM 'needs_review'), 0)::numeric(20, 2)
                AS reviewed_obligations,
            0::numeric(20, 2) AS rejected_obligations,
            COUNT(DISTINCT award_key)::bigint AS award_count,
            COUNT(DISTINCT award_key) FILTER (WHERE review_status = 'needs_review')::bigint
                AS needs_review_award_count,
            COUNT(DISTINCT normalized_account_key)::bigint AS included_account_count,
            COUNT(DISTINCT normalized_account_key) FILTER (WHERE review_status = 'needs_review')::bigint
                AS needs_review_account_count,
            now() AS updated_at
        FROM classified_awards
        WHERE state_code IS NOT NULL
          AND state_code <> ''
        GROUP BY fiscal_year, state_code, classification_version
        WITH NO DATA
        """
    )
    op.execute(
        f"""
        CREATE MATERIALIZED VIEW {SCHEMA}.mv_chip_v1_county_funding_map AS
        {_classified_awards_cte()}
        SELECT
            fiscal_year,
            state_code,
            county_fips,
            'chip_account_classification_v1'::text AS funding_model,
            classification_version,
            'CDC Baseline/Public Map'::text AS funding_scope_label,
            COALESCE(SUM(obligation_amount), 0)::numeric(20, 2) AS total_obligations,
            COALESCE(SUM(obligation_amount) FILTER (WHERE award_source_type = 'assistance'), 0)::numeric(20, 2)
                AS assistance_obligations,
            COALESCE(SUM(obligation_amount) FILTER (WHERE award_source_type = 'contracts'), 0)::numeric(20, 2)
                AS contracts_obligations,
            COALESCE(SUM(obligation_amount) FILTER (WHERE award_source_type = 'unlinked'), 0)::numeric(20, 2)
                AS unlinked_obligations,
            COALESCE(SUM(obligation_amount) FILTER (WHERE review_status = 'needs_review'), 0)::numeric(20, 2)
                AS needs_review_obligations,
            COALESCE(SUM(obligation_amount) FILTER (WHERE review_status IS DISTINCT FROM 'needs_review'), 0)::numeric(20, 2)
                AS reviewed_obligations,
            COUNT(DISTINCT award_key)::bigint AS award_count,
            COUNT(DISTINCT award_key) FILTER (WHERE review_status = 'needs_review')::bigint
                AS needs_review_award_count,
            COUNT(DISTINCT normalized_account_key)::bigint AS included_account_count,
            COUNT(DISTINCT normalized_account_key) FILTER (WHERE review_status = 'needs_review')::bigint
                AS needs_review_account_count,
            now() AS updated_at
        FROM classified_awards
        WHERE county_fips IS NOT NULL
          AND county_fips ~ '^[0-9]{{5}}$'
        GROUP BY fiscal_year, state_code, county_fips, classification_version
        WITH NO DATA
        """
    )
    op.execute(
        f"""
        CREATE MATERIALIZED VIEW {SCHEMA}.mv_chip_v1_unmapped_funding_map AS
        {_classified_awards_cte()}
        SELECT
            fiscal_year,
            geography_level,
            'chip_account_classification_v1'::text AS funding_model,
            classification_version,
            'CDC Baseline/Public Map'::text AS funding_scope_label,
            COALESCE(SUM(obligation_amount), 0)::numeric(20, 2) AS unmapped_award_total,
            COALESCE(SUM(obligation_amount) FILTER (WHERE award_source_type = 'unlinked'), 0)::numeric(20, 2)
                AS unmapped_unlinked_total,
            COUNT(DISTINCT award_key)::bigint AS unmapped_award_count,
            now() AS updated_at
        FROM (
            SELECT classified_awards.*, 'state'::text AS geography_level
            FROM classified_awards
            WHERE state_code IS NULL
               OR state_code = ''
            UNION ALL
            SELECT classified_awards.*, 'county'::text AS geography_level
            FROM classified_awards
            WHERE county_fips IS NULL
               OR county_fips !~ '^[0-9]{{5}}$'
        ) AS unmapped
        GROUP BY fiscal_year, geography_level, classification_version
        WITH NO DATA
        """
    )

    for index_sql in (
        f"CREATE INDEX IF NOT EXISTS mv_chip_v1_state_fy_idx ON {SCHEMA}.mv_chip_v1_state_funding_map (fiscal_year)",
        f"CREATE INDEX IF NOT EXISTS mv_chip_v1_state_code_idx ON {SCHEMA}.mv_chip_v1_state_funding_map (state_code)",
        f"CREATE INDEX IF NOT EXISTS mv_chip_v1_state_model_idx ON {SCHEMA}.mv_chip_v1_state_funding_map (funding_model)",
        f"CREATE INDEX IF NOT EXISTS mv_chip_v1_state_version_idx ON {SCHEMA}.mv_chip_v1_state_funding_map (classification_version)",
        f"CREATE INDEX IF NOT EXISTS mv_chip_v1_state_lookup_idx ON {SCHEMA}.mv_chip_v1_state_funding_map (classification_version, fiscal_year, state_code)",
        f"CREATE INDEX IF NOT EXISTS mv_chip_v1_county_fy_idx ON {SCHEMA}.mv_chip_v1_county_funding_map (fiscal_year)",
        f"CREATE INDEX IF NOT EXISTS mv_chip_v1_county_state_idx ON {SCHEMA}.mv_chip_v1_county_funding_map (state_code)",
        f"CREATE INDEX IF NOT EXISTS mv_chip_v1_county_fips_idx ON {SCHEMA}.mv_chip_v1_county_funding_map (county_fips)",
        f"CREATE INDEX IF NOT EXISTS mv_chip_v1_county_model_idx ON {SCHEMA}.mv_chip_v1_county_funding_map (funding_model)",
        f"CREATE INDEX IF NOT EXISTS mv_chip_v1_county_version_idx ON {SCHEMA}.mv_chip_v1_county_funding_map (classification_version)",
        f"CREATE INDEX IF NOT EXISTS mv_chip_v1_county_lookup_idx ON {SCHEMA}.mv_chip_v1_county_funding_map (classification_version, fiscal_year, county_fips)",
        f"CREATE INDEX IF NOT EXISTS mv_chip_v1_unmapped_lookup_idx ON {SCHEMA}.mv_chip_v1_unmapped_funding_map (classification_version, fiscal_year, geography_level)",
    ):
        op.execute(index_sql)


def downgrade() -> None:
    op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {SCHEMA}.mv_chip_v1_unmapped_funding_map")
    op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {SCHEMA}.mv_chip_v1_county_funding_map")
    op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {SCHEMA}.mv_chip_v1_state_funding_map")
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.ufa_award_fy_account_source_chip_map_idx")
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.chip_account_classification_map_account_id_idx")
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.chip_account_classification_map_lookup_idx")
