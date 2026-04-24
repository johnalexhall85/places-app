"""add cdc canonical funding fact v1

Revision ID: d6c8b1e4f2a7
Revises: c4d8e2f1a9b7
Create Date: 2026-04-07 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d6c8b1e4f2a7"
down_revision: Union[str, None] = "c4d8e2f1a9b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CDC_FUNDING_SCHEMA = "cdc_funding"
BUDGET_SCHEMA = "budget"
RECON_SCHEMA = "recon"
USASPENDING_SCHEMA = "usaspending"
PLACES_SCHEMA = "public"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE VIEW {CDC_FUNDING_SCHEMA}.canonical_funding_fact_v1 AS
        WITH contract_county_lookup AS (
            SELECT
                contract.id,
                county.location_id AS county_fips,
                county.county_name,
                county.state_abbr,
                county.state_desc
            FROM {USASPENDING_SCHEMA}.contract_transactions_enriched AS contract
            LEFT JOIN {PLACES_SCHEMA}.dim_county AS county
                ON county.state_abbr = COALESCE(
                    NULLIF(TRIM(contract.recipient_state_code), ''),
                    NULLIF(TRIM(contract.normalized_recipient_state), '')
                )
               AND UPPER(REGEXP_REPLACE(COALESCE(county.county_name, ''), '[^A-Za-z0-9]', '', 'g'))
                    = UPPER(REGEXP_REPLACE(COALESCE(contract.recipient_county_name, ''), '[^A-Za-z0-9]', '', 'g'))
        ),
        budget_grounded_rows AS (
            SELECT
                CONCAT('budget_grounded:', universe.resolution_id::text) AS canonical_row_id,
                universe.fiscal_year,
                CASE
                    WHEN COALESCE(funding.recipient_county_fips, '') ~ '^[0-9]{{5}}$' THEN 'county'
                    ELSE 'state'
                END AS geography_type,
                COALESCE(
                    NULLIF(funding.recipient_county_fips, ''),
                    NULLIF(funding.recipient_state_code, ''),
                    universe.source_record_id
                ) AS geography_id,
                COALESCE(
                    NULLIF(funding.recipient_county_name, ''),
                    NULLIF(funding.recipient_state_name, ''),
                    universe.source_record_id
                ) AS geography_name,
                NULLIF(funding.recipient_county_fips, '') AS county_fips,
                NULLIF(funding.recipient_county_name, '') AS county_name,
                NULLIF(funding.recipient_state_code, '') AS state_abbr,
                NULLIF(funding.recipient_state_name, '') AS state_name,
                CASE
                    WHEN universe.system_name = 'taggs' THEN 'taggs'
                    ELSE 'usaspending'
                END AS source_system,
                'budget_grounded'::text AS classification_basis,
                universe.scope_universe_version AS classification_version,
                universe.bridge_version,
                universe.resolution_version,
                COALESCE(universe.allocated_budget_amount_dollars, 0)::numeric AS total_funding_amount,
                COALESCE(universe.effective_allocation_pct, 1.000000::numeric) AS effective_allocation_pct,
                TRUE AS already_allocated_flag,
                CASE
                    WHEN LOWER(COALESCE(universe.discretionary_mandatory_type, '')) IN ('discretionary', 'mandatory')
                        THEN LOWER(universe.discretionary_mandatory_type)
                    ELSE 'unknown'
                END AS discretionary_mandatory_type,
                CASE
                    WHEN COALESCE(universe.pphf_flag, FALSE) THEN 'pphf'
                    WHEN COALESCE(universe.transfer_flag, FALSE) THEN 'transfer'
                    WHEN COALESCE(universe.emergency_flag, FALSE) OR COALESCE(universe.supplemental_flag, FALSE)
                        THEN 'supplemental'
                    WHEN UPPER(COALESCE(universe.appropriation_category, '')) = 'MANDATORY'
                        OR LOWER(COALESCE(universe.discretionary_mandatory_type, '')) = 'mandatory'
                        THEN 'mandatory'
                    WHEN UPPER(COALESCE(universe.appropriation_category, '')) = 'REGULAR'
                        THEN 'regular'
                    ELSE LOWER(COALESCE(NULLIF(universe.appropriation_category, ''), 'unknown'))
                END AS appropriation_category,
                NULLIF(universe.appropriation_subtype, '') AS appropriation_subtype,
                COALESCE(universe.emergency_flag, FALSE) AS emergency_flag,
                COALESCE(universe.supplemental_flag, FALSE) AS supplemental_flag,
                COALESCE(universe.pphf_flag, FALSE) AS pphf_flag,
                COALESCE(universe.transfer_flag, FALSE) AS transfer_flag,
                COALESCE(universe.non_add_flag, FALSE) AS non_add_flag,
                COALESCE(universe.double_count_exclusion_flag, FALSE) AS double_count_excluded_flag,
                (
                    COALESCE(universe.include_in_master_universe, FALSE)
                    AND NULLIF(funding.recipient_state_code, '') IS NOT NULL
                ) AS include_in_canonical_universe,
                COALESCE(universe.analyst_reviewed, FALSE) AS analyst_reviewed,
                COALESCE(universe.trusted_auto_seed_flag, FALSE) AS trusted_auto_seed_flag,
                universe.classification_confidence,
                COALESCE(universe.analyst_reviewed, FALSE) AS review_mode_eligible_analyst_only,
                (
                    COALESCE(universe.analyst_reviewed, FALSE)
                    OR COALESCE(universe.trusted_auto_seed_flag, FALSE)
                ) AS review_mode_eligible_trusted_auto,
                (
                    COALESCE(universe.include_in_master_universe, FALSE)
                    AND NULLIF(funding.recipient_state_code, '') IS NOT NULL
                ) AS review_mode_eligible_all_universe,
                universe.inclusion_reason,
                CASE
                    WHEN COALESCE(universe.include_in_master_universe, FALSE)
                         AND NULLIF(funding.recipient_state_code, '') IS NOT NULL
                        THEN NULL::text
                    ELSE COALESCE(universe.double_count_exclusion_reason, universe.inclusion_reason)
                END AS exclusion_reason,
                NULLIF(universe.budget_program, '') AS budget_program,
                NULLIF(universe.budget_sub_program, '') AS budget_sub_program,
                universe.source_record_id,
                universe.budget_anchor_id,
                universe.source_parent_record_id,
                funding.dataset_key AS record_type,
                NULL::date AS latest_action_date,
                COALESCE(
                    NULLIF(funding.project_title, ''),
                    NULLIF(universe.budget_program, ''),
                    'CDC budget-grounded scope row'
                ) AS project_title,
                NULLIF(funding.recipient_name, '') AS recipient_name,
                funding.usaspending_permalink,
                COALESCE(NULLIF(universe.category_display_label, ''), 'Unknown') AS category_label,
                COALESCE(
                    NULLIF(universe.budget_program, ''),
                    NULLIF(universe.budget_sub_program, ''),
                    NULLIF(universe.appropriation_subtype, ''),
                    'Unspecified budget program'
                ) AS subcategory_label,
                universe.source_record_id AS source_award_key
            FROM {BUDGET_SCHEMA}.cdc_budget_grounded_scope_universe_v1 AS universe
            LEFT JOIN {BUDGET_SCHEMA}.v_cdc_budget_grounded_scope_funding_records_v1 AS funding
                ON funding.resolution_id = universe.resolution_id
            WHERE universe.scope_universe_version = 'v1_budget_grounded_scope_universe'
        ),
        budget_grounded_award_keys AS (
            SELECT DISTINCT
                fiscal_year,
                source_award_key
            FROM budget_grounded_rows
            WHERE source_system = 'usaspending'
              AND source_award_key IS NOT NULL
        ),
        assistance_geo AS (
            SELECT
                COALESCE(NULLIF(TRIM(tx.assistance_transaction_unique_key), ''), tx.id::text) AS source_transaction_id,
                COALESCE(
                    NULLIF(TRIM(tx.assistance_award_unique_key), ''),
                    NULLIF(TRIM(prime.unique_key), ''),
                    NULLIF(TRIM(tx.award_id_fain), ''),
                    tx.id::text
                ) AS source_award_key,
                tx.action_date_fiscal_year::integer AS fiscal_year,
                COALESCE(
                    NULLIF(TRIM(tx.recipient_state_code), ''),
                    NULLIF(TRIM(prime.recipient_state_code), '')
                ) AS state_abbr,
                COALESCE(
                    NULLIF(TRIM(prime.recipient_state_name), ''),
                    NULLIF(TRIM(state_dim.state_name), ''),
                    COALESCE(NULLIF(TRIM(tx.recipient_state_code), ''), NULLIF(TRIM(prime.recipient_state_code), ''))
                ) AS state_name,
                COALESCE(
                    NULLIF(TRIM(tx.prime_award_transaction_recipient_county_fips_code), ''),
                    NULLIF(TRIM(prime.recipient_county_fips), '')
                ) AS county_fips,
                county.county_name,
                COALESCE(
                    NULLIF(TRIM(tx.recipient_name), ''),
                    NULLIF(TRIM(prime.recipient_name), ''),
                    'Unknown recipient'
                ) AS recipient_name,
                COALESCE(
                    NULLIF(TRIM(tx.cfda_title), ''),
                    NULLIF(TRIM(prime.cfda_program_title), ''),
                    NULLIF(TRIM(tx.transaction_description), ''),
                    'CDC assistance'
                ) AS project_title,
                tx.action_date AS latest_action_date,
                COALESCE(
                    NULLIF(TRIM(tx.appropriation_type), ''),
                    NULLIF(TRIM(prime.appropriation_type), ''),
                    'unknown'
                ) AS appropriation_type,
                prime.usaspending_permalink
            FROM {CDC_FUNDING_SCHEMA}.prime_transactions AS tx
            LEFT JOIN {CDC_FUNDING_SCHEMA}.prime_awards AS prime
                ON prime.unique_key = tx.assistance_award_unique_key
            LEFT JOIN {PLACES_SCHEMA}.dim_state_boundary AS state_dim
                ON state_dim.state_abbr = COALESCE(
                    NULLIF(TRIM(tx.recipient_state_code), ''),
                    NULLIF(TRIM(prime.recipient_state_code), '')
                )
            LEFT JOIN {PLACES_SCHEMA}.dim_county AS county
                ON county.location_id = COALESCE(
                    NULLIF(TRIM(tx.prime_award_transaction_recipient_county_fips_code), ''),
                    NULLIF(TRIM(prime.recipient_county_fips), '')
                )
        ),
        contract_geo AS (
            SELECT
                COALESCE(NULLIF(TRIM(contract.contract_transaction_unique_key), ''), contract.id::text) AS source_transaction_id,
                COALESCE(
                    NULLIF(TRIM(contract.generated_unique_award_id), ''),
                    NULLIF(TRIM(contract.contract_award_unique_key), ''),
                    NULLIF(TRIM(contract.award_id_piid), ''),
                    contract.id::text
                ) AS source_award_key,
                contract.fiscal_year::integer AS fiscal_year,
                COALESCE(
                    NULLIF(TRIM(contract.recipient_state_code), ''),
                    NULLIF(TRIM(contract.normalized_recipient_state), '')
                ) AS state_abbr,
                COALESCE(
                    NULLIF(TRIM(state_dim.state_name), ''),
                    COALESCE(
                        NULLIF(TRIM(contract.recipient_state_code), ''),
                        NULLIF(TRIM(contract.normalized_recipient_state), '')
                    )
                ) AS state_name,
                county_lookup.county_fips,
                county_lookup.county_name,
                COALESCE(NULLIF(TRIM(contract.recipient_name), ''), 'Unknown recipient') AS recipient_name,
                COALESCE(
                    NULLIF(TRIM(contract.award_description), ''),
                    NULLIF(TRIM(contract.product_or_service_code_description), ''),
                    NULLIF(TRIM(contract.transaction_description), ''),
                    'CDC contract'
                ) AS project_title,
                contract.action_date AS latest_action_date,
                COALESCE(NULLIF(TRIM(contract.appropriation_type), ''), 'unknown') AS appropriation_type,
                NULL::text AS usaspending_permalink
            FROM {USASPENDING_SCHEMA}.contract_transactions_enriched AS contract
            LEFT JOIN contract_county_lookup AS county_lookup
                ON county_lookup.id = contract.id
            LEFT JOIN {PLACES_SCHEMA}.dim_state_boundary AS state_dim
                ON state_dim.state_abbr = COALESCE(
                    NULLIF(TRIM(contract.recipient_state_code), ''),
                    NULLIF(TRIM(contract.normalized_recipient_state), '')
                )
        ),
        provisional_rows AS (
            SELECT
                CONCAT('provisional:', scope.source_system, ':', scope.source_transaction_id) AS canonical_row_id,
                scope.fiscal_year,
                CASE
                    WHEN COALESCE(assistance.county_fips, contract.county_fips, '') ~ '^[0-9]{{5}}$' THEN 'county'
                    ELSE 'state'
                END AS geography_type,
                COALESCE(
                    NULLIF(assistance.county_fips, ''),
                    NULLIF(contract.county_fips, ''),
                    NULLIF(scope.state_code, ''),
                    scope.source_transaction_id
                ) AS geography_id,
                COALESCE(
                    NULLIF(assistance.county_name, ''),
                    NULLIF(contract.county_name, ''),
                    NULLIF(assistance.state_name, ''),
                    NULLIF(contract.state_name, ''),
                    NULLIF(scope.state_code, ''),
                    scope.source_transaction_id
                ) AS geography_name,
                COALESCE(NULLIF(assistance.county_fips, ''), NULLIF(contract.county_fips, '')) AS county_fips,
                COALESCE(NULLIF(assistance.county_name, ''), NULLIF(contract.county_name, '')) AS county_name,
                NULLIF(scope.state_code, '') AS state_abbr,
                COALESCE(
                    NULLIF(assistance.state_name, ''),
                    NULLIF(contract.state_name, ''),
                    NULLIF(scope.state_code, '')
                ) AS state_name,
                CASE
                    WHEN scope.source_system = 'contracts' THEN 'usaspending_contracts'
                    ELSE 'usaspending_assistance'
                END AS source_system,
                'provisional_recon'::text AS classification_basis,
                scope.methodology_version AS classification_version,
                NULL::text AS bridge_version,
                NULL::text AS resolution_version,
                COALESCE(scope.normalized_profile_scope_amount, 0)::numeric AS total_funding_amount,
                CASE
                    WHEN COALESCE(scope.raw_amount, 0) = 0 THEN 1.000000::numeric
                    ELSE COALESCE(scope.normalized_profile_scope_amount, 0)::numeric / NULLIF(scope.raw_amount, 0)::numeric
                END AS effective_allocation_pct,
                TRUE AS already_allocated_flag,
                CASE
                    WHEN scope.effective_funding_scope IN ('federal_health_transfer', 'special_transfer') THEN 'mandatory'
                    WHEN scope.effective_funding_stream IN ('regular_appropriation', 'other_emergency_or_disaster') THEN 'discretionary'
                    ELSE 'unknown'
                END AS discretionary_mandatory_type,
                CASE
                    WHEN scope.effective_funding_scope IN ('federal_health_transfer', 'special_transfer') THEN 'transfer'
                    WHEN (
                        scope.effective_funding_scope = 'emergency_public_health'
                        OR COALESCE(assistance.appropriation_type, contract.appropriation_type, 'unknown')
                            IN ('covid_emergency', 'other_emergency')
                    ) THEN 'supplemental'
                    ELSE 'regular'
                END AS appropriation_category,
                COALESCE(
                    NULLIF(assistance.appropriation_type, ''),
                    NULLIF(contract.appropriation_type, ''),
                    NULLIF(scope.effective_funding_stream, ''),
                    NULLIF(scope.effective_funding_scope, '')
                ) AS appropriation_subtype,
                (
                    scope.effective_funding_scope = 'emergency_public_health'
                    OR COALESCE(assistance.appropriation_type, contract.appropriation_type, 'unknown')
                        IN ('covid_emergency', 'other_emergency')
                ) AS emergency_flag,
                FALSE AS supplemental_flag,
                FALSE AS pphf_flag,
                (
                    scope.effective_funding_scope IN ('federal_health_transfer', 'special_transfer')
                    OR scope.effective_funding_stream = 'transfer_or_special'
                ) AS transfer_flag,
                FALSE AS non_add_flag,
                FALSE AS double_count_excluded_flag,
                (
                    scope.include_in_profile_scope = TRUE
                    AND NULLIF(scope.state_code, '') IS NOT NULL
                ) AS include_in_canonical_universe,
                FALSE AS analyst_reviewed,
                (
                    scope.include_in_profile_scope = TRUE
                    AND COALESCE(scope.confidence_label, '') IN ('high', 'medium')
                ) AS trusted_auto_seed_flag,
                CASE COALESCE(scope.confidence_label, '')
                    WHEN 'high' THEN 0.950::numeric
                    WHEN 'medium' THEN 0.750::numeric
                    WHEN 'low' THEN 0.500::numeric
                    ELSE NULL::numeric
                END AS classification_confidence,
                FALSE AS review_mode_eligible_analyst_only,
                (
                    scope.include_in_profile_scope = TRUE
                    AND COALESCE(scope.confidence_label, '') IN ('high', 'medium')
                ) AS review_mode_eligible_trusted_auto,
                (
                    scope.include_in_profile_scope = TRUE
                    AND NULLIF(scope.state_code, '') IS NOT NULL
                ) AS review_mode_eligible_all_universe,
                CASE
                    WHEN scope.include_in_profile_scope = TRUE THEN scope.inclusion_reason
                    ELSE NULL::text
                END AS inclusion_reason,
                CASE
                    WHEN scope.include_in_profile_scope = TRUE THEN NULL::text
                    ELSE scope.inclusion_reason
                END AS exclusion_reason,
                NULL::text AS budget_program,
                NULL::text AS budget_sub_program,
                scope.source_transaction_id AS source_record_id,
                NULL::text AS budget_anchor_id,
                COALESCE(assistance.source_award_key, contract.source_award_key) AS source_parent_record_id,
                CASE
                    WHEN scope.source_system = 'contracts' THEN 'provisional_contract'
                    ELSE 'provisional_assistance'
                END AS record_type,
                COALESCE(assistance.latest_action_date, contract.latest_action_date) AS latest_action_date,
                COALESCE(assistance.project_title, contract.project_title, 'CDC provisional funding row') AS project_title,
                COALESCE(assistance.recipient_name, contract.recipient_name, 'Unknown recipient') AS recipient_name,
                COALESCE(assistance.usaspending_permalink, contract.usaspending_permalink) AS usaspending_permalink,
                CASE
                    WHEN (
                        scope.effective_funding_scope IN ('federal_health_transfer', 'special_transfer')
                        OR scope.effective_funding_stream = 'transfer_or_special'
                    ) THEN 'Transfers'
                    WHEN (
                        scope.effective_funding_scope = 'emergency_public_health'
                        OR COALESCE(assistance.appropriation_type, contract.appropriation_type, 'unknown')
                            IN ('covid_emergency', 'other_emergency')
                    ) THEN 'Emergency supplemental'
                    WHEN scope.effective_funding_scope IN ('federal_health_transfer', 'special_transfer') THEN 'Mandatory'
                    ELSE 'Regular discretionary'
                END AS category_label,
                COALESCE(
                    NULLIF(scope.effective_funding_scope, ''),
                    NULLIF(scope.effective_funding_stream, ''),
                    NULLIF(assistance.project_title, ''),
                    NULLIF(contract.project_title, ''),
                    'Unspecified program'
                ) AS subcategory_label,
                COALESCE(assistance.source_award_key, contract.source_award_key, scope.source_transaction_id) AS source_award_key
            FROM {RECON_SCHEMA}.profile_scope_transactions AS scope
            LEFT JOIN assistance_geo AS assistance
                ON scope.source_system = 'assistance'
               AND assistance.source_transaction_id = scope.source_transaction_id
            LEFT JOIN contract_geo AS contract
                ON scope.source_system = 'contracts'
               AND contract.source_transaction_id = scope.source_transaction_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM budget_grounded_award_keys AS grounded
                WHERE grounded.fiscal_year = scope.fiscal_year
                  AND grounded.source_award_key = COALESCE(
                      assistance.source_award_key,
                      contract.source_award_key,
                      scope.source_transaction_id
                  )
            )
        )
        SELECT
            CONCAT(
                classification_basis,
                ':',
                fiscal_year::text,
                ':',
                COALESCE(geography_type, 'unknown'),
                ':',
                COALESCE(geography_id, 'unknown'),
                ':',
                COALESCE(source_record_id, 'unknown'),
                ':',
                COALESCE(budget_anchor_id, 'no-anchor')
            ) AS canonical_row_id,
            fiscal_year,
            geography_type,
            geography_id,
            geography_name,
            county_fips,
            county_name,
            state_abbr,
            state_name,
            source_system,
            classification_basis,
            classification_version,
            bridge_version,
            resolution_version,
            total_funding_amount,
            effective_allocation_pct,
            already_allocated_flag,
            discretionary_mandatory_type,
            appropriation_category,
            appropriation_subtype,
            emergency_flag,
            supplemental_flag,
            pphf_flag,
            transfer_flag,
            non_add_flag,
            double_count_excluded_flag,
            include_in_canonical_universe,
            analyst_reviewed,
            trusted_auto_seed_flag,
            classification_confidence,
            review_mode_eligible_analyst_only,
            review_mode_eligible_trusted_auto,
            review_mode_eligible_all_universe,
            inclusion_reason,
            exclusion_reason,
            budget_program,
            budget_sub_program,
            source_record_id,
            budget_anchor_id,
            source_parent_record_id,
            record_type,
            latest_action_date,
            project_title,
            recipient_name,
            usaspending_permalink,
            category_label,
            subcategory_label
        FROM budget_grounded_rows
        UNION ALL
        SELECT
            CONCAT(
                classification_basis,
                ':',
                fiscal_year::text,
                ':',
                COALESCE(geography_type, 'unknown'),
                ':',
                COALESCE(geography_id, 'unknown'),
                ':',
                COALESCE(source_record_id, 'unknown'),
                ':',
                COALESCE(budget_anchor_id, 'no-anchor')
            ) AS canonical_row_id,
            fiscal_year,
            geography_type,
            geography_id,
            geography_name,
            county_fips,
            county_name,
            state_abbr,
            state_name,
            source_system,
            classification_basis,
            classification_version,
            bridge_version,
            resolution_version,
            total_funding_amount,
            effective_allocation_pct,
            already_allocated_flag,
            discretionary_mandatory_type,
            appropriation_category,
            appropriation_subtype,
            emergency_flag,
            supplemental_flag,
            pphf_flag,
            transfer_flag,
            non_add_flag,
            double_count_excluded_flag,
            include_in_canonical_universe,
            analyst_reviewed,
            trusted_auto_seed_flag,
            classification_confidence,
            review_mode_eligible_analyst_only,
            review_mode_eligible_trusted_auto,
            review_mode_eligible_all_universe,
            inclusion_reason,
            exclusion_reason,
            budget_program,
            budget_sub_program,
            source_record_id,
            budget_anchor_id,
            source_parent_record_id,
            record_type,
            latest_action_date,
            project_title,
            recipient_name,
            usaspending_permalink,
            category_label,
            subcategory_label
        FROM provisional_rows
        """
    )


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {CDC_FUNDING_SCHEMA}.canonical_funding_fact_v1")
