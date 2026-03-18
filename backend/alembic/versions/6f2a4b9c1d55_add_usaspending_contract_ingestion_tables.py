"""add usaspending contract ingestion tables

Revision ID: 6f2a4b9c1d55
Revises: 4c2f6d8e9b11
Create Date: 2026-03-14 20:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "6f2a4b9c1d55"
down_revision: Union[str, None] = "4c2f6d8e9b11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

USASPENDING_SCHEMA = "usaspending"


def _create_enriched_view() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE VIEW {USASPENDING_SCHEMA}.contract_transactions_enriched AS
        WITH ranked_rules AS (
            SELECT
                raw.id AS raw_id,
                rules.rule_id,
                rules.priority,
                rules.match_field,
                rules.match_type,
                rules.match_value,
                rules.assigned_category,
                rules.notes,
                ROW_NUMBER() OVER (
                    PARTITION BY raw.id
                    ORDER BY rules.priority ASC, rules.rule_id ASC
                ) AS rn
            FROM {USASPENDING_SCHEMA}.contract_transactions_raw AS raw
            JOIN {USASPENDING_SCHEMA}.contract_category_rules AS rules
                ON rules.is_active = TRUE
               AND rules.match_field IN (
                    'award_description',
                    'awarding_agency_name',
                    'contract_award_type',
                    'contract_transaction_type',
                    'federal_account_symbol',
                    'funding_agency_name',
                    'naics_code',
                    'naics_description',
                    'normalized_federal_account_symbol',
                    'product_or_service_code',
                    'product_or_service_code_description'
               )
               AND CASE
                    WHEN rules.match_type = 'contains'
                        THEN LOWER(
                            CASE rules.match_field
                                WHEN 'award_description' THEN COALESCE(raw.award_description, '')
                                WHEN 'product_or_service_code' THEN COALESCE(raw.product_or_service_code, '')
                                WHEN 'product_or_service_code_description' THEN COALESCE(raw.product_or_service_code_description, '')
                                WHEN 'naics_code' THEN COALESCE(raw.naics_code, '')
                                WHEN 'naics_description' THEN COALESCE(raw.naics_description, '')
                                WHEN 'federal_account_symbol' THEN COALESCE(raw.federal_account_symbol, '')
                                WHEN 'normalized_federal_account_symbol' THEN COALESCE(raw.normalized_federal_account_symbol, '')
                                WHEN 'funding_agency_name' THEN COALESCE(raw.funding_agency_name, '')
                                WHEN 'awarding_agency_name' THEN COALESCE(raw.awarding_agency_name, '')
                                WHEN 'contract_award_type' THEN COALESCE(raw.contract_award_type, '')
                                WHEN 'contract_transaction_type' THEN COALESCE(raw.contract_transaction_type, '')
                                ELSE ''
                            END
                        ) LIKE '%' || LOWER(rules.match_value) || '%'
                    WHEN rules.match_type = 'equals'
                        THEN LOWER(
                            CASE rules.match_field
                                WHEN 'award_description' THEN COALESCE(raw.award_description, '')
                                WHEN 'product_or_service_code' THEN COALESCE(raw.product_or_service_code, '')
                                WHEN 'product_or_service_code_description' THEN COALESCE(raw.product_or_service_code_description, '')
                                WHEN 'naics_code' THEN COALESCE(raw.naics_code, '')
                                WHEN 'naics_description' THEN COALESCE(raw.naics_description, '')
                                WHEN 'federal_account_symbol' THEN COALESCE(raw.federal_account_symbol, '')
                                WHEN 'normalized_federal_account_symbol' THEN COALESCE(raw.normalized_federal_account_symbol, '')
                                WHEN 'funding_agency_name' THEN COALESCE(raw.funding_agency_name, '')
                                WHEN 'awarding_agency_name' THEN COALESCE(raw.awarding_agency_name, '')
                                WHEN 'contract_award_type' THEN COALESCE(raw.contract_award_type, '')
                                WHEN 'contract_transaction_type' THEN COALESCE(raw.contract_transaction_type, '')
                                ELSE ''
                            END
                        ) = LOWER(rules.match_value)
                    WHEN rules.match_type = 'starts_with'
                        THEN LOWER(
                            CASE rules.match_field
                                WHEN 'award_description' THEN COALESCE(raw.award_description, '')
                                WHEN 'product_or_service_code' THEN COALESCE(raw.product_or_service_code, '')
                                WHEN 'product_or_service_code_description' THEN COALESCE(raw.product_or_service_code_description, '')
                                WHEN 'naics_code' THEN COALESCE(raw.naics_code, '')
                                WHEN 'naics_description' THEN COALESCE(raw.naics_description, '')
                                WHEN 'federal_account_symbol' THEN COALESCE(raw.federal_account_symbol, '')
                                WHEN 'normalized_federal_account_symbol' THEN COALESCE(raw.normalized_federal_account_symbol, '')
                                WHEN 'funding_agency_name' THEN COALESCE(raw.funding_agency_name, '')
                                WHEN 'awarding_agency_name' THEN COALESCE(raw.awarding_agency_name, '')
                                WHEN 'contract_award_type' THEN COALESCE(raw.contract_award_type, '')
                                WHEN 'contract_transaction_type' THEN COALESCE(raw.contract_transaction_type, '')
                                ELSE ''
                            END
                        ) LIKE LOWER(rules.match_value) || '%'
                    WHEN rules.match_type = 'regex'
                        THEN CASE rules.match_field
                                WHEN 'award_description' THEN COALESCE(raw.award_description, '')
                                WHEN 'product_or_service_code' THEN COALESCE(raw.product_or_service_code, '')
                                WHEN 'product_or_service_code_description' THEN COALESCE(raw.product_or_service_code_description, '')
                                WHEN 'naics_code' THEN COALESCE(raw.naics_code, '')
                                WHEN 'naics_description' THEN COALESCE(raw.naics_description, '')
                                WHEN 'federal_account_symbol' THEN COALESCE(raw.federal_account_symbol, '')
                                WHEN 'normalized_federal_account_symbol' THEN COALESCE(raw.normalized_federal_account_symbol, '')
                                WHEN 'funding_agency_name' THEN COALESCE(raw.funding_agency_name, '')
                                WHEN 'awarding_agency_name' THEN COALESCE(raw.awarding_agency_name, '')
                                WHEN 'contract_award_type' THEN COALESCE(raw.contract_award_type, '')
                                WHEN 'contract_transaction_type' THEN COALESCE(raw.contract_transaction_type, '')
                                ELSE ''
                             END ~* rules.match_value
                    ELSE FALSE
               END
        ),
        matched_rule AS (
            SELECT *
            FROM ranked_rules
            WHERE rn = 1
        )
        SELECT
            raw.*,
            matched_rule.rule_id AS matched_rule_id,
            matched_rule.priority AS matched_rule_priority,
            matched_rule.match_field AS matched_rule_field,
            matched_rule.match_type AS matched_rule_type,
            matched_rule.match_value AS matched_rule_value,
            matched_rule.notes AS matched_rule_notes,
            COALESCE(
                matched_rule.assigned_category,
                CASE
                    WHEN COALESCE(raw.award_description, raw.product_or_service_code, raw.product_or_service_code_description,
                                  raw.naics_code, raw.naics_description, raw.normalized_federal_account_symbol,
                                  raw.funding_agency_name, raw.awarding_agency_name) IS NOT NULL
                        THEN 'other_contract'
                    ELSE 'unknown'
                END
            ) AS contract_category_guess,
            (
                COALESCE(
                    matched_rule.assigned_category,
                    CASE
                        WHEN COALESCE(raw.award_description, raw.product_or_service_code, raw.product_or_service_code_description,
                                      raw.naics_code, raw.naics_description, raw.normalized_federal_account_symbol,
                                      raw.funding_agency_name, raw.awarding_agency_name) IS NOT NULL
                            THEN 'other_contract'
                        ELSE 'unknown'
                    END
                ) = 'likely_vfc_vaccine_purchase'
            ) AS likely_profile_relevant,
            CASE
                WHEN COALESCE(matched_rule.assigned_category, '') = 'likely_vfc_vaccine_purchase'
                    THEN 'Matched a conservative VFC-focused contract category rule.'
                WHEN matched_rule.rule_id IS NOT NULL
                    THEN 'Matched a first-pass deterministic contract category rule.'
                WHEN COALESCE(raw.award_description, raw.product_or_service_code, raw.product_or_service_code_description,
                              raw.naics_code, raw.naics_description, raw.normalized_federal_account_symbol,
                              raw.funding_agency_name, raw.awarding_agency_name) IS NULL
                    THEN 'Insufficient award description, PSC, NAICS, or account detail for classification.'
                ELSE 'No active rule matched; defaulted to other_contract.'
            END AS profile_relevance_reason
        FROM {USASPENDING_SCHEMA}.contract_transactions_raw AS raw
        LEFT JOIN matched_rule
            ON matched_rule.raw_id = raw.id
        """
    )


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {USASPENDING_SCHEMA}")

    op.create_table(
        "contract_transactions_raw",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_file", sa.Text(), nullable=False),
        sa.Column("source_filename", sa.Text(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=True),
        sa.Column("raw_row_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("contract_transaction_unique_key", sa.Text(), nullable=True),
        sa.Column("contract_award_unique_key", sa.Text(), nullable=True),
        sa.Column("generated_unique_award_id", sa.Text(), nullable=True),
        sa.Column("award_id_piid", sa.Text(), nullable=True),
        sa.Column("parent_award_id_piid", sa.Text(), nullable=True),
        sa.Column("modification_number", sa.Text(), nullable=True),
        sa.Column("transaction_number", sa.Text(), nullable=True),
        sa.Column("action_date", sa.Date(), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("transaction_obligated_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("total_dollars_obligated", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("current_total_value_of_award", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("potential_total_value_of_award", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("recipient_name", sa.Text(), nullable=True),
        sa.Column("recipient_state_code", sa.Text(), nullable=True),
        sa.Column("recipient_state_name", sa.Text(), nullable=True),
        sa.Column("recipient_county_name", sa.Text(), nullable=True),
        sa.Column("recipient_city_name", sa.Text(), nullable=True),
        sa.Column("recipient_country_code", sa.Text(), nullable=True),
        sa.Column("recipient_country_name", sa.Text(), nullable=True),
        sa.Column("recipient_zip", sa.Text(), nullable=True),
        sa.Column("awarding_agency_name", sa.Text(), nullable=True),
        sa.Column("awarding_sub_agency_name", sa.Text(), nullable=True),
        sa.Column("funding_agency_name", sa.Text(), nullable=True),
        sa.Column("funding_sub_agency_name", sa.Text(), nullable=True),
        sa.Column("federal_account_symbol", sa.Text(), nullable=True),
        sa.Column("treasury_account_symbol", sa.Text(), nullable=True),
        sa.Column("federal_accounts_funding_this_award", sa.Text(), nullable=True),
        sa.Column("treasury_accounts_funding_this_award", sa.Text(), nullable=True),
        sa.Column("object_classes_funding_this_award", sa.Text(), nullable=True),
        sa.Column("program_activities_funding_this_award", sa.Text(), nullable=True),
        sa.Column("disaster_emergency_fund_code", sa.Text(), nullable=True),
        sa.Column("appropriation_account", sa.Text(), nullable=True),
        sa.Column("appropriation_type", sa.Text(), nullable=True),
        sa.Column("award_description", sa.Text(), nullable=True),
        sa.Column("transaction_description", sa.Text(), nullable=True),
        sa.Column("prime_award_base_transaction_description", sa.Text(), nullable=True),
        sa.Column("product_or_service_code", sa.Text(), nullable=True),
        sa.Column("product_or_service_code_description", sa.Text(), nullable=True),
        sa.Column("naics_code", sa.Text(), nullable=True),
        sa.Column("naics_description", sa.Text(), nullable=True),
        sa.Column("contract_award_type", sa.Text(), nullable=True),
        sa.Column("contract_transaction_type", sa.Text(), nullable=True),
        sa.Column("award_type", sa.Text(), nullable=True),
        sa.Column("action_type", sa.Text(), nullable=True),
        sa.Column("idv_type", sa.Text(), nullable=True),
        sa.Column("idv_reference", sa.Text(), nullable=True),
        sa.Column("legal_entity_country_code", sa.Text(), nullable=True),
        sa.Column("legal_entity_state_code", sa.Text(), nullable=True),
        sa.Column("normalized_recipient_state", sa.Text(), nullable=True),
        sa.Column("normalized_federal_account_symbol", sa.Text(), nullable=True),
        sa.Column("usaspending_permalink", sa.Text(), nullable=True),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_filename",
            "row_number",
            name="uq_usaspending_contract_transactions_raw_source_row",
        ),
        schema=USASPENDING_SCHEMA,
    )
    op.create_index(
        "usaspending_contract_transactions_raw_fiscal_year_idx",
        "contract_transactions_raw",
        ["fiscal_year"],
        unique=False,
        schema=USASPENDING_SCHEMA,
    )
    op.create_index(
        "usaspending_contract_transactions_raw_recipient_state_code_idx",
        "contract_transactions_raw",
        ["recipient_state_code"],
        unique=False,
        schema=USASPENDING_SCHEMA,
    )
    op.create_index(
        "usp_ct_raw_fas_idx",
        "contract_transactions_raw",
        ["federal_account_symbol"],
        unique=False,
        schema=USASPENDING_SCHEMA,
    )
    op.create_index(
        "usp_ct_raw_defc_idx",
        "contract_transactions_raw",
        ["disaster_emergency_fund_code"],
        unique=False,
        schema=USASPENDING_SCHEMA,
    )
    op.create_index(
        "usp_ct_raw_guid_idx",
        "contract_transactions_raw",
        ["generated_unique_award_id"],
        unique=False,
        schema=USASPENDING_SCHEMA,
    )
    op.create_index(
        "usaspending_contract_transactions_raw_award_id_piid_idx",
        "contract_transactions_raw",
        ["award_id_piid"],
        unique=False,
        schema=USASPENDING_SCHEMA,
    )
    op.create_index(
        "usaspending_contract_transactions_raw_awarding_agency_name_idx",
        "contract_transactions_raw",
        ["awarding_agency_name"],
        unique=False,
        schema=USASPENDING_SCHEMA,
    )
    op.create_index(
        "usaspending_contract_transactions_raw_funding_agency_name_idx",
        "contract_transactions_raw",
        ["funding_agency_name"],
        unique=False,
        schema=USASPENDING_SCHEMA,
    )
    op.create_index(
        "usp_ct_raw_psc_idx",
        "contract_transactions_raw",
        ["product_or_service_code"],
        unique=False,
        schema=USASPENDING_SCHEMA,
    )
    op.create_index(
        "usaspending_contract_transactions_raw_contract_tx_key_idx",
        "contract_transactions_raw",
        ["contract_transaction_unique_key"],
        unique=False,
        schema=USASPENDING_SCHEMA,
    )
    op.create_index(
        "usaspending_contract_transactions_raw_raw_row_json_gin_idx",
        "contract_transactions_raw",
        ["raw_row_json"],
        unique=False,
        schema=USASPENDING_SCHEMA,
        postgresql_using="gin",
    )

    op.create_table(
        "contract_state_year_summary",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("recipient_state_code", sa.Text(), nullable=True),
        sa.Column("federal_account_symbol", sa.Text(), nullable=True),
        sa.Column("funding_agency_name", sa.Text(), nullable=True),
        sa.Column("awarding_agency_name", sa.Text(), nullable=True),
        sa.Column("contract_category_guess", sa.Text(), nullable=True),
        sa.Column(
            "total_transaction_obligated_amount",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("transaction_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("unique_award_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        schema=USASPENDING_SCHEMA,
    )
    op.create_index(
        "usaspending_contract_state_year_summary_fiscal_year_idx",
        "contract_state_year_summary",
        ["fiscal_year"],
        unique=False,
        schema=USASPENDING_SCHEMA,
    )
    op.create_index(
        "usaspending_contract_state_year_summary_state_fiscal_year_idx",
        "contract_state_year_summary",
        ["recipient_state_code", "fiscal_year"],
        unique=False,
        schema=USASPENDING_SCHEMA,
    )
    op.create_index(
        "usaspending_contract_state_year_summary_category_idx",
        "contract_state_year_summary",
        ["contract_category_guess"],
        unique=False,
        schema=USASPENDING_SCHEMA,
    )

    op.create_table(
        "contract_federal_account_inventory",
        sa.Column("federal_account_symbol", sa.Text(), nullable=False),
        sa.Column("treasury_account_symbol", sa.Text(), nullable=True),
        sa.Column("appropriation_type", sa.Text(), nullable=True),
        sa.Column("first_fiscal_year", sa.Integer(), nullable=True),
        sa.Column("last_fiscal_year", sa.Integer(), nullable=True),
        sa.Column("total_transaction_obligated_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("transaction_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("unique_award_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("federal_account_symbol"),
        schema=USASPENDING_SCHEMA,
    )
    op.create_index(
        "usaspending_contract_federal_account_inventory_first_fy_idx",
        "contract_federal_account_inventory",
        ["first_fiscal_year"],
        unique=False,
        schema=USASPENDING_SCHEMA,
    )
    op.create_index(
        "usaspending_contract_federal_account_inventory_last_fy_idx",
        "contract_federal_account_inventory",
        ["last_fiscal_year"],
        unique=False,
        schema=USASPENDING_SCHEMA,
    )

    op.create_table(
        "contract_category_rules",
        sa.Column("rule_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("match_field", sa.Text(), nullable=False),
        sa.Column("match_type", sa.Text(), nullable=False),
        sa.Column("match_value", sa.Text(), nullable=False),
        sa.Column("assigned_category", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("rule_id"),
        sa.UniqueConstraint(
            "match_field",
            "match_type",
            "match_value",
            "assigned_category",
            name="uq_usaspending_contract_category_rules_match",
        ),
        schema=USASPENDING_SCHEMA,
    )
    op.create_index(
        "usaspending_contract_category_rules_priority_idx",
        "contract_category_rules",
        ["priority"],
        unique=False,
        schema=USASPENDING_SCHEMA,
    )
    op.create_index(
        "usaspending_contract_category_rules_active_idx",
        "contract_category_rules",
        ["is_active"],
        unique=False,
        schema=USASPENDING_SCHEMA,
    )

    op.create_table(
        "ingestion_runs",
        sa.Column("run_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pipeline_name", sa.Text(), nullable=False),
        sa.Column("input_dir", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("files_discovered", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("files_matched", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("rows_loaded", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("options_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint("run_id"),
        schema=USASPENDING_SCHEMA,
    )
    op.create_index(
        "usaspending_ingestion_runs_started_at_idx",
        "ingestion_runs",
        ["started_at"],
        unique=False,
        schema=USASPENDING_SCHEMA,
    )
    op.create_index(
        "usaspending_ingestion_runs_status_idx",
        "ingestion_runs",
        ["status"],
        unique=False,
        schema=USASPENDING_SCHEMA,
    )

    rules_table = sa.table(
        "contract_category_rules",
        sa.column("priority", sa.Integer()),
        sa.column("match_field", sa.Text()),
        sa.column("match_type", sa.Text()),
        sa.column("match_value", sa.Text()),
        sa.column("assigned_category", sa.Text()),
        sa.column("notes", sa.Text()),
        schema=USASPENDING_SCHEMA,
    )
    op.bulk_insert(
        rules_table,
        [
            {
                "priority": 10,
                "match_field": "award_description",
                "match_type": "contains",
                "match_value": "vaccines for children",
                "assigned_category": "likely_vfc_vaccine_purchase",
                "notes": "Explicit VFC award-description reference.",
            },
            {
                "priority": 20,
                "match_field": "award_description",
                "match_type": "contains",
                "match_value": "immunization",
                "assigned_category": "likely_immunization_related",
                "notes": "Immunization-related description keyword.",
            },
            {
                "priority": 22,
                "match_field": "award_description",
                "match_type": "contains",
                "match_value": "vaccine",
                "assigned_category": "likely_immunization_related",
                "notes": "General vaccine-related description keyword.",
            },
            {
                "priority": 24,
                "match_field": "product_or_service_code_description",
                "match_type": "contains",
                "match_value": "biological",
                "assigned_category": "likely_immunization_related",
                "notes": "PSC description suggests biologics or vaccines.",
            },
            {
                "priority": 40,
                "match_field": "award_description",
                "match_type": "contains",
                "match_value": "laboratory",
                "assigned_category": "likely_lab_or_testing",
                "notes": "Laboratory-related description keyword.",
            },
            {
                "priority": 42,
                "match_field": "award_description",
                "match_type": "contains",
                "match_value": "testing",
                "assigned_category": "likely_lab_or_testing",
                "notes": "Testing-related description keyword.",
            },
            {
                "priority": 44,
                "match_field": "award_description",
                "match_type": "contains",
                "match_value": "surveillance",
                "assigned_category": "likely_lab_or_testing",
                "notes": "Surveillance-related description keyword.",
            },
            {
                "priority": 60,
                "match_field": "award_description",
                "match_type": "contains",
                "match_value": "software",
                "assigned_category": "likely_it_or_data",
                "notes": "Software-related description keyword.",
            },
            {
                "priority": 62,
                "match_field": "award_description",
                "match_type": "contains",
                "match_value": "informatics",
                "assigned_category": "likely_it_or_data",
                "notes": "Informatics-related description keyword.",
            },
            {
                "priority": 80,
                "match_field": "award_description",
                "match_type": "contains",
                "match_value": "janitorial",
                "assigned_category": "likely_admin_or_operations",
                "notes": "Janitorial support contract.",
            },
            {
                "priority": 82,
                "match_field": "award_description",
                "match_type": "contains",
                "match_value": "custodial",
                "assigned_category": "likely_admin_or_operations",
                "notes": "Custodial support contract.",
            },
            {
                "priority": 100,
                "match_field": "award_description",
                "match_type": "contains",
                "match_value": "research",
                "assigned_category": "likely_research_or_evaluation",
                "notes": "Research-related description keyword.",
            },
            {
                "priority": 102,
                "match_field": "award_description",
                "match_type": "contains",
                "match_value": "evaluation",
                "assigned_category": "likely_research_or_evaluation",
                "notes": "Evaluation-related description keyword.",
            },
        ],
        multiinsert=False,
    )

    _create_enriched_view()


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {USASPENDING_SCHEMA}.contract_transactions_enriched")
    op.drop_index(
        "usaspending_ingestion_runs_status_idx",
        table_name="ingestion_runs",
        schema=USASPENDING_SCHEMA,
    )
    op.drop_index(
        "usaspending_ingestion_runs_started_at_idx",
        table_name="ingestion_runs",
        schema=USASPENDING_SCHEMA,
    )
    op.drop_table("ingestion_runs", schema=USASPENDING_SCHEMA)

    op.drop_index(
        "usaspending_contract_category_rules_active_idx",
        table_name="contract_category_rules",
        schema=USASPENDING_SCHEMA,
    )
    op.drop_index(
        "usaspending_contract_category_rules_priority_idx",
        table_name="contract_category_rules",
        schema=USASPENDING_SCHEMA,
    )
    op.drop_table("contract_category_rules", schema=USASPENDING_SCHEMA)

    op.drop_index(
        "usaspending_contract_federal_account_inventory_last_fy_idx",
        table_name="contract_federal_account_inventory",
        schema=USASPENDING_SCHEMA,
    )
    op.drop_index(
        "usaspending_contract_federal_account_inventory_first_fy_idx",
        table_name="contract_federal_account_inventory",
        schema=USASPENDING_SCHEMA,
    )
    op.drop_table("contract_federal_account_inventory", schema=USASPENDING_SCHEMA)

    op.drop_index(
        "usaspending_contract_state_year_summary_category_idx",
        table_name="contract_state_year_summary",
        schema=USASPENDING_SCHEMA,
    )
    op.drop_index(
        "usaspending_contract_state_year_summary_state_fiscal_year_idx",
        table_name="contract_state_year_summary",
        schema=USASPENDING_SCHEMA,
    )
    op.drop_index(
        "usaspending_contract_state_year_summary_fiscal_year_idx",
        table_name="contract_state_year_summary",
        schema=USASPENDING_SCHEMA,
    )
    op.drop_table("contract_state_year_summary", schema=USASPENDING_SCHEMA)

    op.drop_index(
        "usaspending_contract_transactions_raw_raw_row_json_gin_idx",
        table_name="contract_transactions_raw",
        schema=USASPENDING_SCHEMA,
    )
    op.drop_index(
        "usaspending_contract_transactions_raw_contract_tx_key_idx",
        table_name="contract_transactions_raw",
        schema=USASPENDING_SCHEMA,
    )
    op.drop_index(
        "usp_ct_raw_psc_idx",
        table_name="contract_transactions_raw",
        schema=USASPENDING_SCHEMA,
    )
    op.drop_index(
        "usaspending_contract_transactions_raw_funding_agency_name_idx",
        table_name="contract_transactions_raw",
        schema=USASPENDING_SCHEMA,
    )
    op.drop_index(
        "usaspending_contract_transactions_raw_awarding_agency_name_idx",
        table_name="contract_transactions_raw",
        schema=USASPENDING_SCHEMA,
    )
    op.drop_index(
        "usaspending_contract_transactions_raw_award_id_piid_idx",
        table_name="contract_transactions_raw",
        schema=USASPENDING_SCHEMA,
    )
    op.drop_index(
        "usp_ct_raw_guid_idx",
        table_name="contract_transactions_raw",
        schema=USASPENDING_SCHEMA,
    )
    op.drop_index(
        "usp_ct_raw_defc_idx",
        table_name="contract_transactions_raw",
        schema=USASPENDING_SCHEMA,
    )
    op.drop_index(
        "usp_ct_raw_fas_idx",
        table_name="contract_transactions_raw",
        schema=USASPENDING_SCHEMA,
    )
    op.drop_index(
        "usaspending_contract_transactions_raw_recipient_state_code_idx",
        table_name="contract_transactions_raw",
        schema=USASPENDING_SCHEMA,
    )
    op.drop_index(
        "usaspending_contract_transactions_raw_fiscal_year_idx",
        table_name="contract_transactions_raw",
        schema=USASPENDING_SCHEMA,
    )
    op.drop_table("contract_transactions_raw", schema=USASPENDING_SCHEMA)
