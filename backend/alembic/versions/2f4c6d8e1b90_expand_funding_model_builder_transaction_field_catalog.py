"""expand funding model builder transaction field catalog

Revision ID: 2f4c6d8e1b90
Revises: 0ab1c2d3e4f5
Create Date: 2026-03-23 03:40:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "2f4c6d8e1b90"
down_revision: Union[str, None] = "0ab1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ANALYTICS_SCHEMA = "analytics"
CDC_FUNDING_SCHEMA = "cdc_funding"
RECON_SCHEMA = "recon"
TAGGS_SCHEMA = "taggs"
USASPENDING_SCHEMA = "usaspending"

ASSISTANCE_VIEW = f"{ANALYTICS_SCHEMA}.funding_model_builder_assistance_v1"
CONTRACT_VIEW = f"{ANALYTICS_SCHEMA}.funding_model_builder_contract_v1"
BASE_VIEW = f"{ANALYTICS_SCHEMA}.funding_model_builder_base_v1"

ASSISTANCE_ONLY_COLUMNS: list[tuple[str, str, str]] = [
    ("assistance_assistance_transaction_unique_key", "text", "tx.assistance_transaction_unique_key"),
    ("assistance_assistance_award_unique_key", "text", "tx.assistance_award_unique_key"),
    ("assistance_award_id_fain", "text", "tx.award_id_fain"),
    ("assistance_award_id_uri", "text", "tx.award_id_uri"),
    ("assistance_federal_action_obligation", "numeric", "tx.federal_action_obligation"),
    ("assistance_total_obligated_amount", "numeric", "tx.total_obligated_amount"),
    ("assistance_total_outlayed_amount_for_overall_award", "numeric", "tx.total_outlayed_amount_for_overall_award"),
    (
        "assistance_prime_award_transaction_recipient_county_fips_code",
        "text",
        "tx.prime_award_transaction_recipient_county_fips_code",
    ),
    (
        "assistance_primary_place_of_performance_county_name",
        "text",
        "tx.primary_place_of_performance_county_name",
    ),
    (
        "assistance_prime_award_transaction_place_of_performance_county_fips_code",
        "text",
        "tx.prime_award_transaction_place_of_performance_county_fips_code",
    ),
    (
        "assistance_primary_place_of_performance_state_name",
        "text",
        "tx.primary_place_of_performance_state_name",
    ),
    ("assistance_disaster_emergency_fund_codes_raw", "text", "tx.disaster_emergency_fund_codes_raw"),
    ("assistance_appropriation_subtype", "text", "tx.appropriation_subtype"),
    ("assistance_appropriation_reason_code", "text", "tx.appropriation_reason_code"),
    (
        "assistance_appropriation_classification_source",
        "text",
        "tx.appropriation_classification_source",
    ),
    (
        "assistance_appropriation_classifier_version",
        "text",
        "tx.appropriation_classifier_version",
    ),
    ("assistance_source_file_name", "text", "tx.source_file_name"),
    ("assistance_source_import_batch_id", "text", "tx.source_import_batch_id"),
    ("assistance_source_imported_at", "timestamp", "tx.source_imported_at"),
]

CONTRACT_ONLY_COLUMNS: list[tuple[str, str, str]] = [
    ("contract_source_file", "text", "tx.source_file"),
    ("contract_source_filename", "text", "tx.source_filename"),
    ("contract_row_number", "integer", "tx.row_number"),
    ("contract_contract_transaction_unique_key", "text", "tx.contract_transaction_unique_key"),
    ("contract_contract_award_unique_key", "text", "tx.contract_award_unique_key"),
    ("contract_generated_unique_award_id", "text", "tx.generated_unique_award_id"),
    ("contract_award_id_piid", "text", "tx.award_id_piid"),
    ("contract_parent_award_id_piid", "text", "tx.parent_award_id_piid"),
    ("contract_transaction_number", "text", "tx.transaction_number"),
    ("contract_transaction_obligated_amount", "numeric", "tx.transaction_obligated_amount"),
    ("contract_total_dollars_obligated", "numeric", "tx.total_dollars_obligated"),
    ("contract_current_total_value_of_award", "numeric", "tx.current_total_value_of_award"),
    ("contract_potential_total_value_of_award", "numeric", "tx.potential_total_value_of_award"),
    ("contract_recipient_country_code", "text", "tx.recipient_country_code"),
    ("contract_recipient_country_name", "text", "tx.recipient_country_name"),
    ("contract_recipient_zip", "text", "tx.recipient_zip"),
    ("contract_federal_account_symbol", "text", "tx.federal_account_symbol"),
    ("contract_treasury_account_symbol", "text", "tx.treasury_account_symbol"),
    (
        "contract_federal_accounts_funding_this_award",
        "text",
        "tx.federal_accounts_funding_this_award",
    ),
    (
        "contract_treasury_accounts_funding_this_award",
        "text",
        "tx.treasury_accounts_funding_this_award",
    ),
    (
        "contract_object_classes_funding_this_award",
        "text",
        "tx.object_classes_funding_this_award",
    ),
    (
        "contract_program_activities_funding_this_award",
        "text",
        "tx.program_activities_funding_this_award",
    ),
    ("contract_disaster_emergency_fund_code", "text", "tx.disaster_emergency_fund_code"),
    ("contract_appropriation_account", "text", "tx.appropriation_account"),
    ("contract_award_description", "text", "tx.award_description"),
    ("contract_product_or_service_code", "text", "tx.product_or_service_code"),
    (
        "contract_product_or_service_code_description",
        "text",
        "tx.product_or_service_code_description",
    ),
    ("contract_naics_code", "text", "tx.naics_code"),
    ("contract_naics_description", "text", "tx.naics_description"),
    ("contract_contract_award_type", "text", "tx.contract_award_type"),
    ("contract_contract_transaction_type", "text", "tx.contract_transaction_type"),
    ("contract_action_type", "text", "tx.action_type"),
    ("contract_idv_type", "text", "tx.idv_type"),
    ("contract_idv_reference", "text", "tx.idv_reference"),
    ("contract_legal_entity_country_code", "text", "tx.legal_entity_country_code"),
    ("contract_legal_entity_state_code", "text", "tx.legal_entity_state_code"),
    ("contract_normalized_recipient_state", "text", "tx.normalized_recipient_state"),
    (
        "contract_normalized_federal_account_symbol",
        "text",
        "tx.normalized_federal_account_symbol",
    ),
]


def _render_source_columns(columns: list[tuple[str, str, str]]) -> str:
    return ",\n            ".join(f"{expression} AS {alias}" for alias, _type_name, expression in columns)


def _render_null_columns(columns: list[tuple[str, str, str]]) -> str:
    return ",\n            ".join(f"NULL::{type_name} AS {alias}" for alias, type_name, _expression in columns)


def _assistance_view_sql() -> str:
    return f"""
        CREATE OR REPLACE VIEW {ASSISTANCE_VIEW} AS
        SELECT
            CONCAT('assistance_tx:', COALESCE(NULLIF(BTRIM(tx.assistance_transaction_unique_key), ''), tx.id::text)) AS record_key,
            'usaspending_assistance_transactions'::text AS dataset_key,
            'usaspending_assistance'::text AS source_system,
            tx.action_date AS action_date,
            tx.action_date_fiscal_year AS fiscal_year,
            tx.modification_number AS modification_number,
            COALESCE(enrich.awarding_agency_name, tx.awarding_sub_agency_name) AS awarding_agency_name,
            tx.awarding_sub_agency_name AS awarding_subagency_name,
            tx.awarding_office_name AS awarding_office_name,
            COALESCE(enrich.funding_agency_name, tx.funding_sub_agency_name) AS funding_agency_name,
            tx.funding_sub_agency_name AS funding_subagency_name,
            tx.funding_office_name AS funding_office_name,
            tx.recipient_name AS recipient_name,
            tx.recipient_city_name AS recipient_city_name,
            COALESCE(tx.recipient_state_code, enrich.state_code) AS recipient_state_code,
            tx.recipient_state_name AS recipient_state_name,
            tx.prime_award_transaction_recipient_county_fips_code AS recipient_county_fips,
            tx.recipient_county_name AS recipient_county_name,
            tx.assistance_type_description AS award_type,
            COALESCE(tx.cfda_title, enrich.assistance_listing_title) AS assistance_listing,
            COALESCE(tx.cfda_number, enrich.assistance_listing_number) AS cfda_number,
            COALESCE(enrich.program_activity_name, tx.prime_award_base_transaction_description, tx.transaction_description) AS program_activity,
            tx.transaction_description AS transaction_description,
            tx.prime_award_base_transaction_description AS prime_award_base_transaction_description,
            enrich.treasury_account_symbol AS treasury_account,
            NULL::text AS object_class,
            COALESCE(enrich.disaster_emergency_fund_code, tx.disaster_emergency_fund_codes_raw) AS disaster_emergency_fund_code,
            'transaction'::text AS transaction_type,
            COALESCE(enrich.transaction_obligated_amount, tx.federal_action_obligation, 0)::numeric AS obligation_amount,
            (
                COALESCE(tx.appropriation_type, '') ILIKE '%emergency%'
                OR COALESCE(enrich.disaster_emergency_fund_code, tx.disaster_emergency_fund_codes_raw, '') <> ''
            ) AS is_emergency_funding,
            tx.appropriation_type AS appropriation_type,
            COALESCE(enrich.effective_funding_stream, tx.assistance_type_description) AS funding_mechanism,
            COALESCE(
                enrich.effective_funding_scope,
                enrich.effective_funding_stream,
                tx.assistance_type_description,
                'USAspending Assistance Transactions'
            ) AS program_area,
            COALESCE(enrich.effective_funding_stream, tx.assistance_type_description) AS mechanism,
            NULL::text AS recipient_type,
            COALESCE(enrich.effective_funding_scope, 'USAspending Assistance Transactions') AS category,
            COALESCE(
                enrich.effective_funding_stream,
                tx.cfda_title,
                tx.prime_award_base_transaction_description,
                'Unclassified'
            ) AS subcategory,
            COALESCE(
                tx.cfda_title,
                tx.transaction_description,
                tx.prime_award_base_transaction_description,
                'Unclassified'
            ) AS project_title,
            tx.usaspending_permalink AS usaspending_permalink,
            TRUE AS is_finalized,
            (COALESCE(enrich.transaction_obligated_amount, tx.federal_action_obligation, 0) < 0) AS is_deobligation,
            FALSE AS is_pass_through,
            {_render_source_columns(ASSISTANCE_ONLY_COLUMNS)},
            {_render_null_columns(CONTRACT_ONLY_COLUMNS)}
        FROM {CDC_FUNDING_SCHEMA}.prime_transactions AS tx
        LEFT JOIN {RECON_SCHEMA}.assistance_transactions_profile_enriched AS enrich
          ON enrich.source_transaction_id = COALESCE(NULLIF(BTRIM(tx.assistance_transaction_unique_key), ''), tx.id::text)
        """


def _contract_view_sql() -> str:
    return f"""
        CREATE OR REPLACE VIEW {CONTRACT_VIEW} AS
        SELECT
            CONCAT('contract_tx:', COALESCE(NULLIF(BTRIM(tx.contract_transaction_unique_key), ''), tx.id::text)) AS record_key,
            'usaspending_contract_transactions'::text AS dataset_key,
            'usaspending_contracts'::text AS source_system,
            tx.action_date AS action_date,
            tx.fiscal_year AS fiscal_year,
            tx.modification_number AS modification_number,
            tx.awarding_agency_name AS awarding_agency_name,
            tx.awarding_sub_agency_name AS awarding_subagency_name,
            NULL::text AS awarding_office_name,
            tx.funding_agency_name AS funding_agency_name,
            tx.funding_sub_agency_name AS funding_subagency_name,
            NULL::text AS funding_office_name,
            tx.recipient_name AS recipient_name,
            tx.recipient_city_name AS recipient_city_name,
            COALESCE(tx.recipient_state_code, tx.normalized_recipient_state) AS recipient_state_code,
            tx.recipient_state_name AS recipient_state_name,
            NULL::text AS recipient_county_fips,
            tx.recipient_county_name AS recipient_county_name,
            COALESCE(tx.award_type, 'contract') AS award_type,
            NULL::text AS assistance_listing,
            NULL::text AS cfda_number,
            COALESCE(tx.program_activities_funding_this_award, tx.award_description, tx.transaction_description) AS program_activity,
            tx.transaction_description AS transaction_description,
            tx.prime_award_base_transaction_description AS prime_award_base_transaction_description,
            COALESCE(tx.treasury_account_symbol, tx.treasury_accounts_funding_this_award) AS treasury_account,
            COALESCE(tx.object_classes_funding_this_award, tx.product_or_service_code) AS object_class,
            tx.disaster_emergency_fund_code AS disaster_emergency_fund_code,
            'transaction'::text AS transaction_type,
            COALESCE(enrich.transaction_obligated_amount, tx.transaction_obligated_amount, 0)::numeric AS obligation_amount,
            (
                COALESCE(tx.appropriation_type, '') ILIKE '%emergency%'
                OR COALESCE(tx.disaster_emergency_fund_code, '') <> ''
            ) AS is_emergency_funding,
            tx.appropriation_type AS appropriation_type,
            COALESCE(enrich.effective_funding_stream, tx.contract_award_type, tx.contract_transaction_type, tx.award_type) AS funding_mechanism,
            COALESCE(
                enrich.effective_funding_scope,
                enrich.effective_funding_stream,
                tx.contract_award_type,
                'USAspending Contract Transactions'
            ) AS program_area,
            COALESCE(enrich.effective_funding_stream, tx.contract_award_type, tx.contract_transaction_type, tx.award_type) AS mechanism,
            NULL::text AS recipient_type,
            COALESCE(enrich.effective_funding_scope, 'USAspending Contract Transactions') AS category,
            COALESCE(
                enrich.effective_funding_stream,
                tx.product_or_service_code_description,
                tx.award_description,
                'Unclassified'
            ) AS subcategory,
            COALESCE(tx.award_description, tx.transaction_description, 'Unclassified') AS project_title,
            tx.usaspending_permalink AS usaspending_permalink,
            TRUE AS is_finalized,
            (COALESCE(enrich.transaction_obligated_amount, tx.transaction_obligated_amount, 0) < 0) AS is_deobligation,
            FALSE AS is_pass_through,
            {_render_null_columns(ASSISTANCE_ONLY_COLUMNS)},
            {_render_source_columns(CONTRACT_ONLY_COLUMNS)}
        FROM {USASPENDING_SCHEMA}.contract_transactions_raw AS tx
        LEFT JOIN {RECON_SCHEMA}.contract_transactions_profile_enriched AS enrich
          ON enrich.source_transaction_id = COALESCE(NULLIF(BTRIM(tx.contract_transaction_unique_key), ''), tx.id::text)
        """


def _base_view_sql() -> str:
    return f"""
        CREATE OR REPLACE VIEW {BASE_VIEW} AS
        SELECT
            CONCAT('award:', COALESCE(prime.unique_key, prime.id::text)) AS record_key,
            'usaspending_awards'::text AS dataset_key,
            'usaspending'::text AS source_system,
            prime.award_latest_action_date AS action_date,
            prime.award_latest_action_date_fiscal_year AS fiscal_year,
            NULL::text AS modification_number,
            NULL::text AS awarding_agency_name,
            prime.awarding_sub_agency_name AS awarding_subagency_name,
            prime.awarding_office_name AS awarding_office_name,
            NULL::text AS funding_agency_name,
            prime.funding_sub_agency_name AS funding_subagency_name,
            prime.funding_office_name AS funding_office_name,
            prime.recipient_name AS recipient_name,
            NULL::text AS recipient_city_name,
            prime.recipient_state_code AS recipient_state_code,
            prime.recipient_state_name AS recipient_state_name,
            prime.recipient_county_fips AS recipient_county_fips,
            prime.recipient_county_name AS recipient_county_name,
            prime.assistance_type_description AS award_type,
            prime.cfda_program_title AS assistance_listing,
            prime.cfda_program_num AS cfda_number,
            prime.prime_award_base_transaction_description AS program_activity,
            NULL::text AS transaction_description,
            prime.prime_award_base_transaction_description AS prime_award_base_transaction_description,
            NULL::text AS treasury_account,
            NULL::text AS object_class,
            prime.disaster_emergency_fund_codes_raw AS disaster_emergency_fund_code,
            'award'::text AS transaction_type,
            COALESCE(prime.total_obligated_amount, prime.total_funding_amount, 0)::numeric AS obligation_amount,
            (
                COALESCE(prime.appropriation_type, '') ILIKE '%emergency%'
                OR COALESCE(prime.disaster_emergency_fund_codes_raw, '') <> ''
            ) AS is_emergency_funding,
            prime.appropriation_type AS appropriation_type,
            prime.assistance_type_description AS funding_mechanism,
            COALESCE(prime.awarding_sub_agency_name, prime.funding_sub_agency_name, 'USAspending Awards') AS program_area,
            prime.assistance_type_description AS mechanism,
            NULL::text AS recipient_type,
            COALESCE(prime.awarding_sub_agency_name, prime.funding_sub_agency_name, 'USAspending Awards') AS category,
            COALESCE(prime.cfda_program_title, prime.prime_award_base_transaction_description, 'Unclassified') AS subcategory,
            prime.prime_award_base_transaction_description AS project_title,
            prime.usaspending_permalink AS usaspending_permalink,
            TRUE AS is_finalized,
            (COALESCE(prime.total_obligated_amount, prime.total_funding_amount, 0) < 0) AS is_deobligation,
            FALSE AS is_pass_through,
            {_render_null_columns(ASSISTANCE_ONLY_COLUMNS)},
            {_render_null_columns(CONTRACT_ONLY_COLUMNS)}
        FROM {CDC_FUNDING_SCHEMA}.prime_awards AS prime

        UNION ALL

        SELECT
            CONCAT('subaward:', COALESCE(sub.subaward_unique_key, sub.id::text)) AS record_key,
            'usaspending_subawards'::text AS dataset_key,
            'usaspending'::text AS source_system,
            sub.subaward_action_date AS action_date,
            sub.subaward_action_date_fiscal_year AS fiscal_year,
            NULL::text AS modification_number,
            NULL::text AS awarding_agency_name,
            sub.prime_award_awarding_sub_agency_name AS awarding_subagency_name,
            sub.prime_award_awarding_office_name AS awarding_office_name,
            NULL::text AS funding_agency_name,
            sub.prime_award_funding_sub_agency_name AS funding_subagency_name,
            sub.prime_award_funding_office_name AS funding_office_name,
            sub.subawardee_name AS recipient_name,
            sub.subawardee_city_name AS recipient_city_name,
            sub.subawardee_state_code AS recipient_state_code,
            sub.subawardee_state_name AS recipient_state_name,
            sub.subawardee_county_fips AS recipient_county_fips,
            NULL::text AS recipient_county_name,
            sub.subaward_description AS award_type,
            NULL::text AS assistance_listing,
            NULL::text AS cfda_number,
            sub.prime_award_base_transaction_description AS program_activity,
            NULL::text AS transaction_description,
            sub.prime_award_base_transaction_description AS prime_award_base_transaction_description,
            NULL::text AS treasury_account,
            NULL::text AS object_class,
            sub.prime_award_disaster_emergency_fund_codes_raw AS disaster_emergency_fund_code,
            'subaward'::text AS transaction_type,
            COALESCE(sub.subaward_amount, 0)::numeric AS obligation_amount,
            (
                COALESCE(sub.appropriation_type, '') ILIKE '%emergency%'
                OR COALESCE(sub.prime_award_disaster_emergency_fund_codes_raw, '') <> ''
            ) AS is_emergency_funding,
            sub.appropriation_type AS appropriation_type,
            sub.subaward_description AS funding_mechanism,
            COALESCE(
                sub.prime_award_awarding_sub_agency_name,
                sub.prime_award_funding_sub_agency_name,
                'USAspending Subawards'
            ) AS program_area,
            sub.subaward_description AS mechanism,
            NULL::text AS recipient_type,
            COALESCE(
                sub.prime_award_awarding_sub_agency_name,
                sub.prime_award_funding_sub_agency_name,
                'USAspending Subawards'
            ) AS category,
            COALESCE(sub.prime_award_base_transaction_description, sub.subaward_description, 'Unclassified') AS subcategory,
            sub.subaward_description AS project_title,
            sub.usaspending_permalink AS usaspending_permalink,
            TRUE AS is_finalized,
            (COALESCE(sub.subaward_amount, 0) < 0) AS is_deobligation,
            FALSE AS is_pass_through,
            {_render_null_columns(ASSISTANCE_ONLY_COLUMNS)},
            {_render_null_columns(CONTRACT_ONLY_COLUMNS)}
        FROM {CDC_FUNDING_SCHEMA}.subawards AS sub

        UNION ALL

        SELECT * FROM {ASSISTANCE_VIEW}

        UNION ALL

        SELECT * FROM {CONTRACT_VIEW}

        UNION ALL

        SELECT
            CONCAT('taggs:', COALESCE(taggs.award_number, taggs.id::text), ':', taggs.funding_fiscal_year::text) AS record_key,
            'taggs'::text AS dataset_key,
            'taggs'::text AS source_system,
            NULL::date AS action_date,
            taggs.funding_fiscal_year AS fiscal_year,
            NULL::text AS modification_number,
            taggs.opdiv AS awarding_agency_name,
            taggs.program_office AS awarding_subagency_name,
            NULL::text AS awarding_office_name,
            taggs.opdiv AS funding_agency_name,
            NULL::text AS funding_subagency_name,
            NULL::text AS funding_office_name,
            taggs.legal_entity_name AS recipient_name,
            NULL::text AS recipient_city_name,
            taggs.legal_entity_state_normalized AS recipient_state_code,
            NULL::text AS recipient_state_name,
            NULL::text AS recipient_county_fips,
            taggs.legal_entity_county_normalized AS recipient_county_name,
            taggs.award_title AS award_type,
            taggs.assistance_listing_title AS assistance_listing,
            taggs.aln AS cfda_number,
            taggs.program_office AS program_activity,
            taggs.award_description AS transaction_description,
            taggs.award_description AS prime_award_base_transaction_description,
            taggs.can_code AS treasury_account,
            NULL::text AS object_class,
            NULL::text AS disaster_emergency_fund_code,
            'award'::text AS transaction_type,
            COALESCE(taggs.total_sum_of_actions, 0)::numeric AS obligation_amount,
            (COALESCE(taggs.appropriation_type, '') ILIKE '%emergency%') AS is_emergency_funding,
            taggs.appropriation_type AS appropriation_type,
            taggs.funding_stream AS funding_mechanism,
            COALESCE(taggs.effective_category, taggs.program_office, 'TAGGS') AS program_area,
            taggs.funding_stream AS mechanism,
            NULL::text AS recipient_type,
            COALESCE(taggs.effective_category, 'TAGGS') AS category,
            COALESCE(taggs.effective_subcategory, taggs.effective_program_name, 'Unclassified') AS subcategory,
            COALESCE(taggs.award_title, taggs.award_description, 'Unclassified') AS project_title,
            NULL::text AS usaspending_permalink,
            TRUE AS is_finalized,
            (COALESCE(taggs.total_sum_of_actions, 0) < 0) AS is_deobligation,
            FALSE AS is_pass_through,
            {_render_null_columns(ASSISTANCE_ONLY_COLUMNS)},
            {_render_null_columns(CONTRACT_ONLY_COLUMNS)}
        FROM {TAGGS_SCHEMA}.award_funding_summary AS taggs
        """


def upgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {BASE_VIEW}")
    op.execute(f"DROP VIEW IF EXISTS {ASSISTANCE_VIEW}")
    op.execute(f"DROP VIEW IF EXISTS {CONTRACT_VIEW}")
    op.execute(_assistance_view_sql())
    op.execute(_contract_view_sql())
    op.execute(_base_view_sql())


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for the expanded funding model builder field catalog.")
