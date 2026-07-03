"""add chip account classification layer

Revision ID: 2a7c9d0e5f61
Revises: f4a9c2d7e6b1
Create Date: 2026-04-24 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2a7c9d0e5f61"
down_revision: Union[str, None] = "f4a9c2d7e6b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "usaspending_fed_account"


def _create_classified_views() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE VIEW {SCHEMA}.v_chip_account_classified_reconciliation AS
        SELECT
            reconciliation.fiscal_year,
            reconciliation.federal_account_id,
            reconciliation.normalized_account_key,
            reconciliation.federal_account_name,
            dim.account_title,
            dim.agency_name,
            dim.bureau_name,
            reconciliation.balance_obligations,
            reconciliation.award_obligations_total,
            reconciliation.assistance_award_obligations,
            reconciliation.contracts_award_obligations,
            reconciliation.unlinked_award_obligations,
            reconciliation.pa_oc_obligations_total,
            reconciliation.balance_minus_awards,
            reconciliation.balance_minus_pa_oc,
            reconciliation.award_match_percent_of_balance,
            reconciliation.pa_oc_match_percent_of_balance,
            reconciliation.record_count_awards,
            reconciliation.record_count_pa_oc,
            classification.id AS classification_id,
            classification.federal_account_id AS classification_federal_account_id,
            classification.normalized_account_key AS classification_normalized_account_key,
            classification.federal_account_name AS classification_federal_account_name,
            classification.agency_name AS classification_agency_name,
            classification.bureau_name AS classification_bureau_name,
            classification.is_cdc_related,
            classification.cdc_scope_category,
            classification.funding_scope,
            classification.include_in_chip_baseline,
            classification.include_in_chip_emergency,
            classification.include_in_chip_total,
            classification.include_in_public_map,
            classification.review_status,
            classification.confidence,
            classification.classification_reason,
            classification.notes,
            classification.source,
            classification.classification_version,
            classification.created_at AS classification_created_at,
            classification.updated_at AS classification_updated_at
        FROM {SCHEMA}.v_account_reconciliation AS reconciliation
        LEFT JOIN {SCHEMA}.dim_federal_account AS dim
            ON dim.id = reconciliation.federal_account_id
        LEFT JOIN {SCHEMA}.chip_account_classification AS classification
            ON classification.fiscal_year = reconciliation.fiscal_year
           AND classification.normalized_account_key = reconciliation.normalized_account_key
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {SCHEMA}.v_chip_cdc_account_universe AS
        SELECT *
        FROM {SCHEMA}.v_chip_account_classified_reconciliation
        WHERE is_cdc_related IS TRUE
          AND review_status IN ('reviewed', 'candidate', 'needs_review')
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE VIEW {SCHEMA}.v_chip_cdc_baseline_accounts AS
        SELECT *
        FROM {SCHEMA}.v_chip_account_classified_reconciliation
        WHERE include_in_chip_baseline IS TRUE
          AND is_cdc_related IS TRUE
          AND review_status IS DISTINCT FROM 'rejected'
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE VIEW {SCHEMA}.v_chip_cdc_emergency_accounts AS
        SELECT *
        FROM {SCHEMA}.v_chip_account_classified_reconciliation
        WHERE include_in_chip_emergency IS TRUE
          AND is_cdc_related IS TRUE
          AND review_status IS DISTINCT FROM 'rejected'
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE VIEW {SCHEMA}.v_chip_cdc_public_map_accounts AS
        SELECT *
        FROM {SCHEMA}.v_chip_account_classified_reconciliation
        WHERE include_in_public_map IS TRUE
          AND is_cdc_related IS TRUE
          AND review_status IS DISTINCT FROM 'rejected'
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE VIEW {SCHEMA}.v_chip_cdc_excluded_accounts AS
        SELECT *
        FROM {SCHEMA}.v_chip_account_classified_reconciliation
        WHERE COALESCE(is_cdc_related, false) IS FALSE
           OR review_status = 'rejected'
           OR (
                COALESCE(include_in_chip_baseline, false) IS FALSE
            AND COALESCE(include_in_chip_emergency, false) IS FALSE
            AND COALESCE(include_in_chip_total, false) IS FALSE
            AND COALESCE(include_in_public_map, false) IS FALSE
           )
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE VIEW {SCHEMA}.v_chip_cdc_funding_reconciliation_by_year AS
        SELECT
            fiscal_year,
            classification_version,
            SUM(COALESCE(balance_obligations, 0))::numeric(18, 2)
                AS total_balance_obligations,
            SUM(COALESCE(award_obligations_total, 0))::numeric(18, 2)
                AS total_award_obligations,
            SUM(COALESCE(assistance_award_obligations, 0))::numeric(18, 2)
                AS total_assistance_awards,
            SUM(COALESCE(contracts_award_obligations, 0))::numeric(18, 2)
                AS total_contract_awards,
            SUM(COALESCE(unlinked_award_obligations, 0))::numeric(18, 2)
                AS total_unlinked_awards,
            SUM(COALESCE(pa_oc_obligations_total, 0))::numeric(18, 2)
                AS total_pa_oc_obligations,
            SUM(
                CASE
                    WHEN include_in_chip_baseline IS TRUE
                     AND is_cdc_related IS TRUE
                     AND review_status IS DISTINCT FROM 'rejected'
                    THEN COALESCE(balance_obligations, 0)
                    ELSE 0
                END
            )::numeric(18, 2) AS baseline_balance_obligations,
            SUM(
                CASE
                    WHEN include_in_chip_baseline IS TRUE
                     AND is_cdc_related IS TRUE
                     AND review_status IS DISTINCT FROM 'rejected'
                    THEN COALESCE(award_obligations_total, 0)
                    ELSE 0
                END
            )::numeric(18, 2) AS baseline_award_obligations,
            SUM(
                CASE
                    WHEN include_in_chip_emergency IS TRUE
                     AND is_cdc_related IS TRUE
                     AND review_status IS DISTINCT FROM 'rejected'
                    THEN COALESCE(balance_obligations, 0)
                    ELSE 0
                END
            )::numeric(18, 2) AS emergency_balance_obligations,
            SUM(
                CASE
                    WHEN include_in_chip_emergency IS TRUE
                     AND is_cdc_related IS TRUE
                     AND review_status IS DISTINCT FROM 'rejected'
                    THEN COALESCE(award_obligations_total, 0)
                    ELSE 0
                END
            )::numeric(18, 2) AS emergency_award_obligations,
            SUM(
                CASE
                    WHEN include_in_public_map IS TRUE
                     AND is_cdc_related IS TRUE
                     AND review_status IS DISTINCT FROM 'rejected'
                    THEN COALESCE(award_obligations_total, 0)
                    ELSE 0
                END
            )::numeric(18, 2) AS public_map_award_obligations,
            SUM(
                CASE
                    WHEN COALESCE(is_cdc_related, false) IS FALSE
                      OR review_status = 'rejected'
                      OR (
                            COALESCE(include_in_chip_baseline, false) IS FALSE
                        AND COALESCE(include_in_chip_emergency, false) IS FALSE
                        AND COALESCE(include_in_chip_total, false) IS FALSE
                        AND COALESCE(include_in_public_map, false) IS FALSE
                      )
                    THEN COALESCE(balance_obligations, 0)
                    ELSE 0
                END
            )::numeric(18, 2) AS excluded_balance_obligations,
            SUM(
                CASE
                    WHEN cdc_scope_category = 'unknown_review'
                      OR review_status = 'needs_review'
                      OR classification_version IS NULL
                    THEN COALESCE(balance_obligations, 0)
                    ELSE 0
                END
            )::numeric(18, 2) AS unknown_review_balance_obligations,
            COUNT(
                DISTINCT CASE
                    WHEN is_cdc_related IS TRUE
                     AND review_status IS DISTINCT FROM 'rejected'
                    THEN normalized_account_key
                END
            )::integer AS cdc_account_count,
            COUNT(
                DISTINCT CASE
                    WHEN include_in_chip_baseline IS TRUE
                     AND is_cdc_related IS TRUE
                     AND review_status IS DISTINCT FROM 'rejected'
                    THEN normalized_account_key
                END
            )::integer AS baseline_account_count,
            COUNT(
                DISTINCT CASE
                    WHEN include_in_chip_emergency IS TRUE
                     AND is_cdc_related IS TRUE
                     AND review_status IS DISTINCT FROM 'rejected'
                    THEN normalized_account_key
                END
            )::integer AS emergency_account_count,
            COUNT(
                DISTINCT CASE
                    WHEN cdc_scope_category = 'unknown_review'
                      OR review_status = 'needs_review'
                      OR classification_version IS NULL
                    THEN normalized_account_key
                END
            )::integer AS unknown_review_account_count
        FROM {SCHEMA}.v_chip_account_classified_reconciliation
        GROUP BY fiscal_year, classification_version
        """
    )


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    op.create_table(
        "chip_account_classification",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("federal_account_id", sa.Integer(), nullable=True),
        sa.Column("normalized_account_key", sa.Text(), nullable=False),
        sa.Column("federal_account_name", sa.Text(), nullable=True),
        sa.Column("agency_name", sa.Text(), nullable=True),
        sa.Column("bureau_name", sa.Text(), nullable=True),
        sa.Column("is_cdc_related", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "cdc_scope_category",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'unknown_review'"),
        ),
        sa.Column("funding_scope", sa.Text(), nullable=False, server_default=sa.text("'unknown'")),
        sa.Column("include_in_chip_baseline", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("include_in_chip_emergency", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("include_in_chip_total", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("include_in_public_map", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("review_status", sa.Text(), nullable=False, server_default=sa.text("'candidate'")),
        sa.Column("confidence", sa.Numeric(), nullable=True),
        sa.Column("classification_reason", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'rule_based_candidate'")),
        sa.Column(
            "classification_version",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'chip_account_classification_v1'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "cdc_scope_category IN ("
            "'cdc_core', 'cdc_transfer', 'cdc_emergency', 'cdc_business_support', "
            "'cdc_atdsr', 'cdc_niosh', 'non_cdc_hhs', 'unknown_review'"
            ")",
            name="ck_chip_account_classification_cdc_scope_category",
        ),
        sa.CheckConstraint(
            "funding_scope IN ("
            "'regular_appropriation', 'emergency_supplemental', 'pphf', 'transfer', "
            "'mandatory', 'business_support', 'reimbursable', 'unknown'"
            ")",
            name="ck_chip_account_classification_funding_scope",
        ),
        sa.CheckConstraint(
            "review_status IN ('candidate', 'needs_review', 'reviewed', 'rejected')",
            name="ck_chip_account_classification_review_status",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_chip_account_classification_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["federal_account_id"],
            [f"{SCHEMA}.dim_federal_account.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "fiscal_year",
            "normalized_account_key",
            "classification_version",
            name="uq_chip_account_classification_year_key_version",
        ),
        schema=SCHEMA,
    )

    op.create_index(
        "chip_account_classification_fy_idx",
        "chip_account_classification",
        ["fiscal_year"],
        schema=SCHEMA,
    )
    op.create_index(
        "chip_account_classification_key_idx",
        "chip_account_classification",
        ["normalized_account_key"],
        schema=SCHEMA,
    )
    op.create_index(
        "chip_account_classification_is_cdc_idx",
        "chip_account_classification",
        ["is_cdc_related"],
        schema=SCHEMA,
    )
    op.create_index(
        "chip_account_classification_cdc_scope_idx",
        "chip_account_classification",
        ["cdc_scope_category"],
        schema=SCHEMA,
    )
    op.create_index(
        "chip_account_classification_funding_scope_idx",
        "chip_account_classification",
        ["funding_scope"],
        schema=SCHEMA,
    )
    op.create_index(
        "chip_account_classification_baseline_idx",
        "chip_account_classification",
        ["include_in_chip_baseline"],
        schema=SCHEMA,
    )
    op.create_index(
        "chip_account_classification_public_map_idx",
        "chip_account_classification",
        ["include_in_public_map"],
        schema=SCHEMA,
    )
    op.create_index(
        "chip_account_classification_review_status_idx",
        "chip_account_classification",
        ["review_status"],
        schema=SCHEMA,
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ufa_award_desc_fy_account_id_chip_idx
        ON {SCHEMA}.fact_award_account_breakdown (
            fiscal_year,
            federal_account_id,
            id
        )
        WHERE award_description IS NOT NULL
          AND BTRIM(award_description) <> ''
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ufa_award_aln_fy_account_id_chip_idx
        ON {SCHEMA}.fact_award_account_breakdown (
            fiscal_year,
            federal_account_id,
            id
        )
        WHERE assistance_listing_number IS NOT NULL
           OR cfda_title IS NOT NULL
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ufa_award_industry_fy_account_id_chip_idx
        ON {SCHEMA}.fact_award_account_breakdown (
            fiscal_year,
            federal_account_id,
            id
        )
        WHERE naics_code IS NOT NULL
           OR naics_description IS NOT NULL
           OR psc_code IS NOT NULL
           OR psc_description IS NOT NULL
        """
    )

    _create_classified_views()


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {SCHEMA}.v_chip_cdc_funding_reconciliation_by_year")
    op.execute(f"DROP VIEW IF EXISTS {SCHEMA}.v_chip_cdc_excluded_accounts")
    op.execute(f"DROP VIEW IF EXISTS {SCHEMA}.v_chip_cdc_public_map_accounts")
    op.execute(f"DROP VIEW IF EXISTS {SCHEMA}.v_chip_cdc_emergency_accounts")
    op.execute(f"DROP VIEW IF EXISTS {SCHEMA}.v_chip_cdc_baseline_accounts")
    op.execute(f"DROP VIEW IF EXISTS {SCHEMA}.v_chip_cdc_account_universe")
    op.execute(f"DROP VIEW IF EXISTS {SCHEMA}.v_chip_account_classified_reconciliation")
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.ufa_award_industry_fy_account_id_chip_idx")
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.ufa_award_aln_fy_account_id_chip_idx")
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.ufa_award_desc_fy_account_id_chip_idx")
    op.drop_table("chip_account_classification", schema=SCHEMA)
