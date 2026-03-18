"""add profile scope reconstruction layer

Revision ID: 4a6d2c8b1e90
Revises: 3c4d5e6f7a8b
Create Date: 2026-03-14 01:45:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4a6d2c8b1e90"
down_revision: Union[str, None] = "3c4d5e6f7a8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RECON_SCHEMA = "recon"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {RECON_SCHEMA}")

    op.create_table(
        "profile_scope_rules",
        sa.Column("rule_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("match_field", sa.Text(), nullable=False),
        sa.Column("match_type", sa.Text(), nullable=False),
        sa.Column("match_value", sa.Text(), nullable=False),
        sa.Column("include_in_profile_scope", sa.Boolean(), nullable=True),
        sa.Column("inclusion_weight", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("assigned_reason", sa.Text(), nullable=True),
        sa.Column("confidence_label", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("rule_id"),
        sa.UniqueConstraint(
            "priority",
            "source_system",
            "match_field",
            "match_type",
            "match_value",
            name="uq_recon_profile_scope_rule_match",
        ),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_profile_scope_rules_priority_idx",
        "profile_scope_rules",
        ["priority"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_profile_scope_rules_source_idx",
        "profile_scope_rules",
        ["source_system"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_profile_scope_rules_active_idx",
        "profile_scope_rules",
        ["is_active"],
        unique=False,
        schema=RECON_SCHEMA,
    )

    op.create_table(
        "assistance_transactions_profile_enriched",
        sa.Column("source_transaction_id", sa.Text(), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False, server_default=sa.text("'assistance'")),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("state_code", sa.Text(), nullable=True),
        sa.Column("recipient_name", sa.Text(), nullable=True),
        sa.Column("recipient_country_name", sa.Text(), nullable=True),
        sa.Column("awarding_agency_name", sa.Text(), nullable=True),
        sa.Column("funding_agency_name", sa.Text(), nullable=True),
        sa.Column("assistance_listing_number", sa.Text(), nullable=True),
        sa.Column("assistance_listing_title", sa.Text(), nullable=True),
        sa.Column("program_activity_name", sa.Text(), nullable=True),
        sa.Column("federal_account_symbol", sa.Text(), nullable=True),
        sa.Column("treasury_account_symbol", sa.Text(), nullable=True),
        sa.Column("appropriation_type", sa.Text(), nullable=True),
        sa.Column("disaster_emergency_fund_code", sa.Text(), nullable=True),
        sa.Column("transaction_obligated_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("effective_funding_stream", sa.Text(), nullable=True),
        sa.Column("effective_scope_guess", sa.Text(), nullable=True),
        sa.Column("federal_account_profile_relevant", sa.Boolean(), nullable=True),
        sa.Column("include_in_profile_scope", sa.Boolean(), nullable=True),
        sa.Column("inclusion_weight", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("inclusion_reason", sa.Text(), nullable=True),
        sa.Column("exclusion_reason", sa.Text(), nullable=True),
        sa.Column("confidence_label", sa.Text(), nullable=True),
        sa.Column("likely_domestic", sa.Boolean(), nullable=True),
        sa.Column("likely_special_transfer", sa.Boolean(), nullable=True),
        sa.Column("likely_regular_assistance", sa.Boolean(), nullable=True),
        sa.Column("likely_emergency_related", sa.Boolean(), nullable=True),
        sa.Column("likely_arpa_related", sa.Boolean(), nullable=True),
        sa.Column("decision_context", sa.Text(), nullable=True),
        sa.Column("matched_rule_id", sa.BigInteger(), nullable=True),
        sa.Column("methodology_version", sa.Text(), nullable=True),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("source_transaction_id"),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_assistance_profile_enriched_fy_idx",
        "assistance_transactions_profile_enriched",
        ["fiscal_year"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_assistance_profile_enriched_state_idx",
        "assistance_transactions_profile_enriched",
        ["state_code"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_assistance_profile_enriched_account_idx",
        "assistance_transactions_profile_enriched",
        ["federal_account_symbol"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_assistance_profile_enriched_stream_idx",
        "assistance_transactions_profile_enriched",
        ["effective_funding_stream"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_assistance_profile_enriched_include_idx",
        "assistance_transactions_profile_enriched",
        ["include_in_profile_scope"],
        unique=False,
        schema=RECON_SCHEMA,
    )

    op.create_table(
        "contract_transactions_profile_enriched",
        sa.Column("source_transaction_id", sa.Text(), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False, server_default=sa.text("'contracts'")),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("state_code", sa.Text(), nullable=True),
        sa.Column("recipient_name", sa.Text(), nullable=True),
        sa.Column("recipient_country_name", sa.Text(), nullable=True),
        sa.Column("awarding_agency_name", sa.Text(), nullable=True),
        sa.Column("funding_agency_name", sa.Text(), nullable=True),
        sa.Column("federal_account_symbol", sa.Text(), nullable=True),
        sa.Column("treasury_account_symbol", sa.Text(), nullable=True),
        sa.Column("appropriation_type", sa.Text(), nullable=True),
        sa.Column("disaster_emergency_fund_code", sa.Text(), nullable=True),
        sa.Column("award_description", sa.Text(), nullable=True),
        sa.Column("product_or_service_code", sa.Text(), nullable=True),
        sa.Column("transaction_obligated_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("contract_category_guess", sa.Text(), nullable=True),
        sa.Column("likely_profile_relevant_contract", sa.Boolean(), nullable=True),
        sa.Column("effective_funding_stream", sa.Text(), nullable=True),
        sa.Column("effective_scope_guess", sa.Text(), nullable=True),
        sa.Column("federal_account_profile_relevant", sa.Boolean(), nullable=True),
        sa.Column("include_in_profile_scope", sa.Boolean(), nullable=True),
        sa.Column("inclusion_weight", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("inclusion_reason", sa.Text(), nullable=True),
        sa.Column("exclusion_reason", sa.Text(), nullable=True),
        sa.Column("confidence_label", sa.Text(), nullable=True),
        sa.Column("likely_vfc_related", sa.Boolean(), nullable=True),
        sa.Column("likely_immunization_related", sa.Boolean(), nullable=True),
        sa.Column("likely_emergency_related", sa.Boolean(), nullable=True),
        sa.Column("decision_context", sa.Text(), nullable=True),
        sa.Column("matched_rule_id", sa.BigInteger(), nullable=True),
        sa.Column("methodology_version", sa.Text(), nullable=True),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("source_transaction_id"),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_contract_profile_enriched_fy_idx",
        "contract_transactions_profile_enriched",
        ["fiscal_year"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_contract_profile_enriched_state_idx",
        "contract_transactions_profile_enriched",
        ["state_code"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_contract_profile_enriched_account_idx",
        "contract_transactions_profile_enriched",
        ["federal_account_symbol"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_contract_profile_enriched_stream_idx",
        "contract_transactions_profile_enriched",
        ["effective_funding_stream"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_contract_profile_enriched_include_idx",
        "contract_transactions_profile_enriched",
        ["include_in_profile_scope"],
        unique=False,
        schema=RECON_SCHEMA,
    )

    op.create_table(
        "profile_scope_transactions",
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("source_transaction_id", sa.Text(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("state_code", sa.Text(), nullable=True),
        sa.Column("recipient_name", sa.Text(), nullable=True),
        sa.Column("federal_account_symbol", sa.Text(), nullable=True),
        sa.Column("effective_funding_stream", sa.Text(), nullable=True),
        sa.Column("include_in_profile_scope", sa.Boolean(), nullable=True),
        sa.Column("inclusion_weight", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("inclusion_reason", sa.Text(), nullable=True),
        sa.Column("confidence_label", sa.Text(), nullable=True),
        sa.Column("raw_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("normalized_profile_scope_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("methodology_version", sa.Text(), nullable=True),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("source_system", "source_transaction_id"),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_profile_scope_transactions_fy_idx",
        "profile_scope_transactions",
        ["fiscal_year"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_profile_scope_transactions_state_idx",
        "profile_scope_transactions",
        ["state_code"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_profile_scope_transactions_source_idx",
        "profile_scope_transactions",
        ["source_system"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_profile_scope_transactions_include_idx",
        "profile_scope_transactions",
        ["include_in_profile_scope"],
        unique=False,
        schema=RECON_SCHEMA,
    )

    op.create_table(
        "profile_scope_state_year_summary",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("state_code", sa.Text(), nullable=False),
        sa.Column("raw_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("profile_scope_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("transaction_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("included_transaction_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("methodology_version", sa.Text(), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_system",
            "fiscal_year",
            "state_code",
            name="uq_recon_profile_scope_state_year_source",
        ),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_profile_scope_state_year_summary_fy_idx",
        "profile_scope_state_year_summary",
        ["fiscal_year"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_profile_scope_state_year_summary_state_idx",
        "profile_scope_state_year_summary",
        ["state_code"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_profile_scope_state_year_summary_source_idx",
        "profile_scope_state_year_summary",
        ["source_system"],
        unique=False,
        schema=RECON_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "recon_profile_scope_state_year_summary_source_idx",
        table_name="profile_scope_state_year_summary",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_profile_scope_state_year_summary_state_idx",
        table_name="profile_scope_state_year_summary",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_profile_scope_state_year_summary_fy_idx",
        table_name="profile_scope_state_year_summary",
        schema=RECON_SCHEMA,
    )
    op.drop_table("profile_scope_state_year_summary", schema=RECON_SCHEMA)

    op.drop_index(
        "recon_profile_scope_transactions_include_idx",
        table_name="profile_scope_transactions",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_profile_scope_transactions_source_idx",
        table_name="profile_scope_transactions",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_profile_scope_transactions_state_idx",
        table_name="profile_scope_transactions",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_profile_scope_transactions_fy_idx",
        table_name="profile_scope_transactions",
        schema=RECON_SCHEMA,
    )
    op.drop_table("profile_scope_transactions", schema=RECON_SCHEMA)

    op.drop_index(
        "recon_contract_profile_enriched_include_idx",
        table_name="contract_transactions_profile_enriched",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_contract_profile_enriched_stream_idx",
        table_name="contract_transactions_profile_enriched",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_contract_profile_enriched_account_idx",
        table_name="contract_transactions_profile_enriched",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_contract_profile_enriched_state_idx",
        table_name="contract_transactions_profile_enriched",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_contract_profile_enriched_fy_idx",
        table_name="contract_transactions_profile_enriched",
        schema=RECON_SCHEMA,
    )
    op.drop_table("contract_transactions_profile_enriched", schema=RECON_SCHEMA)

    op.drop_index(
        "recon_assistance_profile_enriched_include_idx",
        table_name="assistance_transactions_profile_enriched",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_assistance_profile_enriched_stream_idx",
        table_name="assistance_transactions_profile_enriched",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_assistance_profile_enriched_account_idx",
        table_name="assistance_transactions_profile_enriched",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_assistance_profile_enriched_state_idx",
        table_name="assistance_transactions_profile_enriched",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_assistance_profile_enriched_fy_idx",
        table_name="assistance_transactions_profile_enriched",
        schema=RECON_SCHEMA,
    )
    op.drop_table("assistance_transactions_profile_enriched", schema=RECON_SCHEMA)

    op.drop_index(
        "recon_profile_scope_rules_active_idx",
        table_name="profile_scope_rules",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_profile_scope_rules_source_idx",
        table_name="profile_scope_rules",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_profile_scope_rules_priority_idx",
        table_name="profile_scope_rules",
        schema=RECON_SCHEMA,
    )
    op.drop_table("profile_scope_rules", schema=RECON_SCHEMA)
