"""add assistance account normalization bridge and summary tables

Revision ID: 5f3a1b7c9d22
Revises: ab7e3f1c92d4
Create Date: 2026-03-15 12:30:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5f3a1b7c9d22"
down_revision: Union[str, None] = "ab7e3f1c92d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RECON_SCHEMA = "recon"
CDC_FUNDING_SCHEMA = "cdc_funding"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {RECON_SCHEMA}")
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.assistance_transaction_accounts")

    op.create_table(
        "assistance_transaction_accounts",
        sa.Column("source_transaction_id", sa.Text(), nullable=False),
        sa.Column("federal_account_symbol", sa.Text(), nullable=False),
        sa.Column("account_position", sa.Integer(), nullable=False),
        sa.Column("source_row_id", sa.Integer(), nullable=True),
        sa.Column("award_key", sa.Text(), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("state_code", sa.Text(), nullable=True),
        sa.Column("transaction_obligated_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("awarding_agency_name", sa.Text(), nullable=True),
        sa.Column("funding_agency_name", sa.Text(), nullable=True),
        sa.Column("treasury_account_symbol", sa.Text(), nullable=True),
        sa.Column("appropriation_type", sa.Text(), nullable=True),
        sa.Column("appropriation_subtype", sa.Text(), nullable=True),
        sa.Column("raw_emergency_code", sa.Text(), nullable=True),
        sa.Column("psc_or_aln", sa.Text(), nullable=True),
        sa.Column("psc_or_aln_description", sa.Text(), nullable=True),
        sa.Column("award_description", sa.Text(), nullable=True),
        sa.Column("transaction_description", sa.Text(), nullable=True),
        sa.Column("prime_award_base_transaction_description", sa.Text(), nullable=True),
        sa.Column("naics_description", sa.Text(), nullable=True),
        sa.Column("program_activity_name", sa.Text(), nullable=True),
        sa.Column("raw_federal_account_symbol", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "source_transaction_id",
            "federal_account_symbol",
            "account_position",
            name="pk_recon_assistance_transaction_accounts",
        ),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_assistance_transaction_accounts_symbol_idx",
        "assistance_transaction_accounts",
        ["federal_account_symbol"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_assistance_transaction_accounts_fy_idx",
        "assistance_transaction_accounts",
        ["fiscal_year"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_assistance_transaction_accounts_state_idx",
        "assistance_transaction_accounts",
        ["state_code"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_assistance_transaction_accounts_tx_idx",
        "assistance_transaction_accounts",
        ["source_transaction_id"],
        unique=False,
        schema=RECON_SCHEMA,
    )

    op.create_table(
        "assistance_transaction_account_summary",
        sa.Column("source_transaction_id", sa.Text(), nullable=False),
        sa.Column("account_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("distinct_account_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("joined_account_symbols", sa.Text(), nullable=True),
        sa.Column("has_regular_account", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("has_emergency_account", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("has_arpa_account", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("has_profile_relevant_account", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("has_unknown_account", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("has_transfer_or_special_account", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("has_procurement_account", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("has_non_profile_relevant_account", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("effective_funding_stream", sa.Text(), nullable=True),
        sa.Column("effective_scope_guess", sa.Text(), nullable=True),
        sa.Column("effective_profile_relevant", sa.Boolean(), nullable=True),
        sa.Column("effective_classification_method", sa.Text(), nullable=True),
        sa.Column("classification_notes", sa.Text(), nullable=True),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "source_transaction_id",
            name="pk_recon_assistance_transaction_account_summary",
        ),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_assistance_account_summary_stream_idx",
        "assistance_transaction_account_summary",
        ["effective_funding_stream"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_assistance_account_summary_profile_idx",
        "assistance_transaction_account_summary",
        ["effective_profile_relevant"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_assistance_account_summary_unknown_idx",
        "assistance_transaction_account_summary",
        ["has_unknown_account"],
        unique=False,
        schema=RECON_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "recon_assistance_account_summary_unknown_idx",
        table_name="assistance_transaction_account_summary",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_assistance_account_summary_profile_idx",
        table_name="assistance_transaction_account_summary",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_assistance_account_summary_stream_idx",
        table_name="assistance_transaction_account_summary",
        schema=RECON_SCHEMA,
    )
    op.drop_table("assistance_transaction_account_summary", schema=RECON_SCHEMA)

    op.drop_index(
        "recon_assistance_transaction_accounts_tx_idx",
        table_name="assistance_transaction_accounts",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_assistance_transaction_accounts_state_idx",
        table_name="assistance_transaction_accounts",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_assistance_transaction_accounts_fy_idx",
        table_name="assistance_transaction_accounts",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_assistance_transaction_accounts_symbol_idx",
        table_name="assistance_transaction_accounts",
        schema=RECON_SCHEMA,
    )
    op.drop_table("assistance_transaction_accounts", schema=RECON_SCHEMA)

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
