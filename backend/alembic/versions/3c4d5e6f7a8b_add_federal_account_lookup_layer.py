"""add federal account lookup and observation layer

Revision ID: 3c4d5e6f7a8b
Revises: 9d4e6b2f1c33
Create Date: 2026-03-14 00:30:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "3c4d5e6f7a8b"
down_revision: Union[str, None] = "9d4e6b2f1c33"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RECON_SCHEMA = "recon"
USASPENDING_SCHEMA = "usaspending"
CDC_FUNDING_SCHEMA = "cdc_funding"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {RECON_SCHEMA}")

    op.create_table(
        "federal_account_lookup",
        sa.Column("federal_account_symbol", sa.Text(), nullable=False),
        sa.Column("agency_identifier", sa.Text(), nullable=True),
        sa.Column("main_account_code", sa.Text(), nullable=True),
        sa.Column("sub_account_code", sa.Text(), nullable=True),
        sa.Column("account_title", sa.Text(), nullable=True),
        sa.Column("account_title_normalized", sa.Text(), nullable=True),
        sa.Column("treasury_account_group_hint", sa.Text(), nullable=True),
        sa.Column("source_metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("observed_in_contracts", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("observed_in_assistance", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("first_fiscal_year", sa.Integer(), nullable=True),
        sa.Column("last_fiscal_year", sa.Integer(), nullable=True),
        sa.Column("observed_transaction_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("observed_total_obligations", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("funding_stream_guess", sa.Text(), nullable=True),
        sa.Column("appropriations_scope_guess", sa.Text(), nullable=True),
        sa.Column("likely_profile_relevant", sa.Boolean(), nullable=True),
        sa.Column("likely_vfc_related", sa.Boolean(), nullable=True),
        sa.Column("likely_emergency_related", sa.Boolean(), nullable=True),
        sa.Column("likely_arpa_related", sa.Boolean(), nullable=True),
        sa.Column("likely_regular_appropriation", sa.Boolean(), nullable=True),
        sa.Column("classification_confidence", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("classification_method", sa.Text(), nullable=True),
        sa.Column("classification_notes", sa.Text(), nullable=True),
        sa.Column("manual_funding_stream", sa.Text(), nullable=True),
        sa.Column("manual_scope_guess", sa.Text(), nullable=True),
        sa.Column("manual_profile_relevant", sa.Boolean(), nullable=True),
        sa.Column("manual_notes", sa.Text(), nullable=True),
        sa.Column("is_manually_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("effective_funding_stream", sa.Text(), nullable=True),
        sa.Column("effective_scope_guess", sa.Text(), nullable=True),
        sa.Column("effective_profile_relevant", sa.Boolean(), nullable=True),
        sa.Column("effective_classification_method", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("federal_account_symbol"),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_federal_account_lookup_first_fy_idx",
        "federal_account_lookup",
        ["first_fiscal_year"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_federal_account_lookup_last_fy_idx",
        "federal_account_lookup",
        ["last_fiscal_year"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_federal_account_lookup_stream_idx",
        "federal_account_lookup",
        ["effective_funding_stream"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_federal_account_lookup_profile_idx",
        "federal_account_lookup",
        ["effective_profile_relevant"],
        unique=False,
        schema=RECON_SCHEMA,
    )

    op.create_table(
        "federal_account_observations",
        sa.Column("federal_account_symbol", sa.Text(), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("transaction_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_obligations", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("awarding_agency_name", sa.Text(), nullable=True),
        sa.Column("funding_agency_name", sa.Text(), nullable=True),
        sa.Column("top_psc_or_aln", sa.Text(), nullable=True),
        sa.Column("top_description_hint", sa.Text(), nullable=True),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint(
            "federal_account_symbol",
            "source_system",
            "fiscal_year",
            name="pk_recon_federal_account_observations",
        ),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_federal_account_observations_source_idx",
        "federal_account_observations",
        ["source_system"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_federal_account_observations_fy_idx",
        "federal_account_observations",
        ["fiscal_year"],
        unique=False,
        schema=RECON_SCHEMA,
    )

    op.create_table(
        "federal_account_classification_rules",
        sa.Column("rule_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("match_field", sa.Text(), nullable=False),
        sa.Column("match_type", sa.Text(), nullable=False),
        sa.Column("match_value", sa.Text(), nullable=False),
        sa.Column("assigned_funding_stream", sa.Text(), nullable=True),
        sa.Column("assigned_scope_guess", sa.Text(), nullable=True),
        sa.Column("assigned_profile_relevant", sa.Boolean(), nullable=True),
        sa.Column("assigned_vfc_related", sa.Boolean(), nullable=True),
        sa.Column("assigned_emergency_related", sa.Boolean(), nullable=True),
        sa.Column("assigned_arpa_related", sa.Boolean(), nullable=True),
        sa.Column("assigned_regular_appropriation", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("rule_id"),
        sa.UniqueConstraint(
            "priority",
            "match_field",
            "match_type",
            "match_value",
            name="uq_recon_federal_account_classification_rule_match",
        ),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_federal_account_classification_rules_priority_idx",
        "federal_account_classification_rules",
        ["priority"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_federal_account_classification_rules_active_idx",
        "federal_account_classification_rules",
        ["is_active"],
        unique=False,
        schema=RECON_SCHEMA,
    )

    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.federal_account_review_export")
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.assistance_transaction_accounts")
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.contract_transaction_accounts")

    op.execute(
        f"""
        CREATE VIEW {RECON_SCHEMA}.contract_transaction_accounts AS
        SELECT
            'contracts'::text AS source_system,
            tx.id AS source_row_id,
            NULLIF(BTRIM(account_symbol), '') AS federal_account_symbol,
            tx.contract_transaction_unique_key AS transaction_unique_key,
            COALESCE(tx.generated_unique_award_id, tx.contract_award_unique_key, tx.award_id_piid) AS award_key,
            tx.fiscal_year,
            COALESCE(tx.transaction_obligated_amount, 0)::numeric(18, 2) AS obligation_amount,
            tx.awarding_agency_name,
            tx.funding_agency_name,
            tx.treasury_account_symbol,
            tx.appropriation_type,
            NULL::text AS appropriation_subtype,
            tx.disaster_emergency_fund_code AS raw_emergency_code,
            tx.product_or_service_code AS psc_or_aln,
            tx.product_or_service_code_description AS psc_or_aln_description,
            tx.award_description,
            tx.transaction_description,
            tx.prime_award_base_transaction_description,
            tx.naics_description,
            NULL::text AS program_activity_name
        FROM {USASPENDING_SCHEMA}.contract_transactions_raw AS tx
        CROSS JOIN LATERAL regexp_split_to_table(
            COALESCE(tx.normalized_federal_account_symbol, tx.federal_account_symbol, ''),
            E'\\s*[;,|]\\s*'
        ) AS account_symbol
        WHERE NULLIF(BTRIM(account_symbol), '') IS NOT NULL
        """
    )
    op.execute(
        f"""
        CREATE VIEW {RECON_SCHEMA}.assistance_transaction_accounts AS
        SELECT
            'assistance'::text AS source_system,
            tx.id AS source_row_id,
            NULLIF(BTRIM(account_symbol), '') AS federal_account_symbol,
            tx.assistance_transaction_unique_key AS transaction_unique_key,
            COALESCE(tx.assistance_award_unique_key, tx.award_id_fain) AS award_key,
            tx.action_date_fiscal_year AS fiscal_year,
            COALESCE(tx.federal_action_obligation, 0)::numeric(18, 2) AS obligation_amount,
            COALESCE(NULLIF(BTRIM(tx.awarding_sub_agency_name), ''), NULLIF(BTRIM(tx.awarding_office_name), ''))
                AS awarding_agency_name,
            COALESCE(NULLIF(BTRIM(tx.funding_sub_agency_name), ''), NULLIF(BTRIM(tx.funding_office_name), ''))
                AS funding_agency_name,
            COALESCE(
                NULLIF(BTRIM(tx.raw ->> 'treasury_account_symbol'), ''),
                NULLIF(BTRIM(tx.raw ->> 'treasury_account_identifier'), ''),
                NULLIF(BTRIM(p.raw ->> 'treasury_account_symbol'), ''),
                NULLIF(BTRIM(p.raw ->> 'treasury_account_identifier'), '')
            ) AS treasury_account_symbol,
            tx.appropriation_type,
            tx.appropriation_subtype,
            tx.disaster_emergency_fund_codes_raw AS raw_emergency_code,
            COALESCE(NULLIF(BTRIM(tx.cfda_number), ''), NULLIF(BTRIM(p.cfda_program_num), '')) AS psc_or_aln,
            COALESCE(NULLIF(BTRIM(tx.cfda_title), ''), NULLIF(BTRIM(p.cfda_program_title), ''))
                AS psc_or_aln_description,
            NULL::text AS award_description,
            tx.transaction_description,
            tx.prime_award_base_transaction_description,
            NULL::text AS naics_description,
            COALESCE(
                NULLIF(BTRIM(tx.raw ->> 'program_activity_name'), ''),
                NULLIF(BTRIM(tx.raw ->> 'program_activity'), ''),
                NULLIF(BTRIM(p.raw ->> 'program_activity_name'), ''),
                NULLIF(BTRIM(p.raw ->> 'program_activity'), '')
            ) AS program_activity_name
        FROM {CDC_FUNDING_SCHEMA}.prime_transactions AS tx
        LEFT JOIN {CDC_FUNDING_SCHEMA}.prime_awards AS p
          ON p.unique_key = tx.assistance_award_unique_key
        CROSS JOIN LATERAL regexp_split_to_table(
            COALESCE(
                NULLIF(BTRIM(tx.raw ->> 'federal_account_symbol'), ''),
                NULLIF(BTRIM(tx.raw ->> 'federal_account_identifier'), ''),
                NULLIF(BTRIM(tx.raw ->> 'federal_accounts_funding_this_award'), ''),
                NULLIF(BTRIM(p.raw ->> 'federal_account_symbol'), ''),
                NULLIF(BTRIM(p.raw ->> 'federal_account_identifier'), ''),
                NULLIF(BTRIM(p.raw ->> 'federal_accounts_funding_this_award'), ''),
                ''
            ),
            E'\\s*[;,|]\\s*'
        ) AS account_symbol
        WHERE NULLIF(BTRIM(account_symbol), '') IS NOT NULL
        """
    )
    op.execute(
        f"""
        CREATE VIEW {RECON_SCHEMA}.federal_account_review_export AS
        SELECT
            federal_account_symbol,
            account_title,
            observed_in_contracts,
            observed_in_assistance,
            first_fiscal_year,
            last_fiscal_year,
            observed_transaction_count,
            observed_total_obligations,
            funding_stream_guess,
            appropriations_scope_guess,
            likely_profile_relevant,
            likely_vfc_related,
            likely_emergency_related,
            likely_arpa_related,
            likely_regular_appropriation,
            classification_confidence,
            classification_method,
            is_manually_verified,
            effective_funding_stream,
            effective_scope_guess,
            effective_profile_relevant,
            effective_classification_method
        FROM {RECON_SCHEMA}.federal_account_lookup
        ORDER BY
            observed_total_obligations DESC NULLS LAST,
            classification_confidence ASC NULLS FIRST,
            federal_account_symbol
        """
    )


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.federal_account_review_export")
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.assistance_transaction_accounts")
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.contract_transaction_accounts")

    op.drop_index(
        "recon_federal_account_classification_rules_active_idx",
        table_name="federal_account_classification_rules",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_federal_account_classification_rules_priority_idx",
        table_name="federal_account_classification_rules",
        schema=RECON_SCHEMA,
    )
    op.drop_table("federal_account_classification_rules", schema=RECON_SCHEMA)

    op.drop_index(
        "recon_federal_account_observations_fy_idx",
        table_name="federal_account_observations",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_federal_account_observations_source_idx",
        table_name="federal_account_observations",
        schema=RECON_SCHEMA,
    )
    op.drop_table("federal_account_observations", schema=RECON_SCHEMA)

    op.drop_index(
        "recon_federal_account_lookup_profile_idx",
        table_name="federal_account_lookup",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_federal_account_lookup_stream_idx",
        table_name="federal_account_lookup",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_federal_account_lookup_last_fy_idx",
        table_name="federal_account_lookup",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_federal_account_lookup_first_fy_idx",
        table_name="federal_account_lookup",
        schema=RECON_SCHEMA,
    )
    op.drop_table("federal_account_lookup", schema=RECON_SCHEMA)
