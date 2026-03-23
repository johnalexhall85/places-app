"""add analytics chip emergency classification layer

Revision ID: 7c1e4a2b9d60
Revises: 6c9e5d4b8a21
Create Date: 2026-03-22 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7c1e4a2b9d60"
down_revision: Union[str, None] = "6c9e5d4b8a21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ANALYTICS_SCHEMA = "analytics"
RECON_SCHEMA = "recon"
PLACES_SCHEMA = "public"

MODEL_VERSION = "v1_1_emergency_classification"
METHODOLOGY_VERSION = "v1.1"
ROLLOUT_STATUS = "partial_raw_total_only"
STATE_PROFILE_SOURCE_VERSION = "chip_state_profile_v1_1_emergency_classification"
NORMALIZATION_SOURCE_VERSION = "v1_normalized_state_funding"
RULE_SET_VERSION = "rules_v1"


def _normalized_name_sql(expr: str) -> str:
    return (
        "NULLIF(BTRIM(REGEXP_REPLACE("
        "REGEXP_REPLACE("
        f"REGEXP_REPLACE(UPPER(COALESCE({expr}, '')), '[^A-Z0-9]+', ' ', 'g'), "
        "'(^| )(INCORPORATED|INC|LLC|LTD|CORPORATION|CORP|CO)( |$)', ' ', 'g'"
        "), "
        "'\\s+', ' ', 'g'"
        ")), '')"
    )


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {ANALYTICS_SCHEMA}")

    op.create_table(
        "chip_recipient_classification_curated_v11_ec",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("recipient_name_raw", sa.Text(), nullable=False),
        sa.Column("recipient_name_normalized", sa.Text(), nullable=False),
        sa.Column("entity_group_name", sa.Text(), nullable=True),
        sa.Column("recipient_type", sa.Text(), nullable=True),
        sa.Column("is_state_like", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_local_public_health_like", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_public_university_like", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_intermediary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("classification_source", sa.Text(), nullable=False),
        sa.Column("match_source", sa.Text(), nullable=False),
        sa.Column("override_priority", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Text(), nullable=True),
        sa.Column("active_flag", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("effective_start_date", sa.Date(), nullable=True),
        sa.Column("effective_end_date", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema=ANALYTICS_SCHEMA,
    )
    op.create_index(
        "analytics_chip_recipient_curated_raw_idx",
        "chip_recipient_classification_curated_v11_ec",
        ["recipient_name_raw"],
        unique=False,
        schema=ANALYTICS_SCHEMA,
    )
    op.create_index(
        "analytics_chip_recipient_curated_normalized_idx",
        "chip_recipient_classification_curated_v11_ec",
        ["recipient_name_normalized"],
        unique=False,
        schema=ANALYTICS_SCHEMA,
    )

    op.create_table(
        "chip_recipient_classification_rules_v11_ec",
        sa.Column("rule_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("rule_name", sa.Text(), nullable=False),
        sa.Column("match_type", sa.Text(), nullable=False),
        sa.Column("match_value", sa.Text(), nullable=False),
        sa.Column("assigned_recipient_type", sa.Text(), nullable=True),
        sa.Column("assigned_state_like", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("assigned_local_public_health_like", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("assigned_public_university_like", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("assigned_intermediary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("rule_priority", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("rule_notes", sa.Text(), nullable=True),
        sa.Column("active_flag", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("rule_id"),
        schema=ANALYTICS_SCHEMA,
    )
    op.create_index(
        "analytics_chip_recipient_rules_active_idx",
        "chip_recipient_classification_rules_v11_ec",
        ["active_flag"],
        unique=False,
        schema=ANALYTICS_SCHEMA,
    )
    op.create_index(
        "analytics_chip_recipient_rules_priority_idx",
        "chip_recipient_classification_rules_v11_ec",
        ["rule_priority"],
        unique=False,
        schema=ANALYTICS_SCHEMA,
    )

    op.execute(
        sa.text(
            f"""
            INSERT INTO {ANALYTICS_SCHEMA}.chip_recipient_classification_curated_v11_ec (
                recipient_name_raw,
                recipient_name_normalized,
                entity_group_name,
                recipient_type,
                is_state_like,
                is_local_public_health_like,
                is_public_university_like,
                is_intermediary,
                classification_source,
                match_source,
                override_priority,
                review_notes,
                confidence,
                active_flag,
                effective_start_date,
                effective_end_date
            ) VALUES
                (
                    'PUBLIC HEALTH FOUNDATION ENTERPRISES, INC.',
                    'PUBLIC HEALTH FOUNDATION ENTERPRISES',
                    'PHFE',
                    'intermediary',
                    FALSE,
                    FALSE,
                    FALSE,
                    TRUE,
                    'manual_override',
                    'exact_name',
                    1000,
                    'Centralized fiscal agent / intermediary. Recipient location is not treated as final use geography for state-profile totals.',
                    'high',
                    TRUE,
                    NULL,
                    NULL
                ),
                (
                    'PUBLIC HEALTH FOUNDATION ENTERPRISES INC',
                    'PUBLIC HEALTH FOUNDATION ENTERPRISES',
                    'PHFE',
                    'intermediary',
                    FALSE,
                    FALSE,
                    FALSE,
                    TRUE,
                    'manual_override',
                    'exact_name',
                    1000,
                    'Centralized fiscal agent / intermediary. Recipient location is not treated as final use geography for state-profile totals.',
                    'high',
                    TRUE,
                    NULL,
                    NULL
                ),
                (
                    'PHFE MANAGEMENT SOLUTIONS LLC',
                    'PHFE MANAGEMENT SOLUTIONS',
                    'PHFE',
                    'intermediary',
                    FALSE,
                    FALSE,
                    FALSE,
                    TRUE,
                    'manual_override',
                    'exact_name',
                    1000,
                    'PHFE-related management entity treated as centralized intermediary pending explicit review evidence to the contrary.',
                    'high',
                    TRUE,
                    NULL,
                    NULL
                )
            """
        )
    )

    op.execute(
        sa.text(
            f"""
            INSERT INTO {ANALYTICS_SCHEMA}.chip_recipient_classification_rules_v11_ec (
                rule_name,
                match_type,
                match_value,
                assigned_recipient_type,
                assigned_state_like,
                assigned_local_public_health_like,
                assigned_public_university_like,
                assigned_intermediary,
                rule_priority,
                rule_notes,
                active_flag
            ) VALUES
                (
                    'intermediary_management_solutions',
                    'regex',
                    '(fiscal agent|management solutions|foundation enterprises)',
                    'intermediary',
                    FALSE,
                    FALSE,
                    FALSE,
                    TRUE,
                    400,
                    'Fallback intermediary heuristic kept intentionally narrow.',
                    TRUE
                ),
                (
                    'state_health_department_regex',
                    'regex',
                    '(state of |commonwealth of |department of health|department of public health|state health)',
                    'state_government',
                    TRUE,
                    FALSE,
                    FALSE,
                    FALSE,
                    300,
                    'State-like implementer heuristic.',
                    TRUE
                ),
                (
                    'local_public_health_regex',
                    'regex',
                    '(county|city of |parish|borough|municipal|public health district|local health department|health department)',
                    'local_public_health',
                    FALSE,
                    TRUE,
                    FALSE,
                    FALSE,
                    200,
                    'Local public health heuristic.',
                    TRUE
                ),
                (
                    'public_university_candidate_regex',
                    'regex',
                    '(state university|university of |college of medicine|school of public health)',
                    'university_candidate',
                    FALSE,
                    FALSE,
                    TRUE,
                    FALSE,
                    100,
                    'University heuristic is intentionally treated as candidate-only and can be overridden by curated intermediary entries.',
                    TRUE
                )
            """
        )
    )

    normalized_recipient_name = _normalized_name_sql("tx.recipient_name")
    normalized_source_recipient_name = _normalized_name_sql("tx.recipient_name")

    op.execute(
        f"""
        CREATE VIEW {ANALYTICS_SCHEMA}.chip_funding_account_classification_v11_ec AS
        WITH combo_rows AS (
            SELECT
                tx.federal_account_combination_key,
                BOOL_OR(POSITION('075-0140' IN COALESCE(tx.federal_account_combination_key, '')) > 0) AS contains_075_0140,
                BOOL_OR(COALESCE(tx.mixed_scope_contains_emergency, false)) AS has_mixed_scope_emergency,
                BOOL_OR(COALESCE(tx.effective_funding_scope, '') = 'emergency_public_health') AS has_emergency_scope_match
            FROM {RECON_SCHEMA}.profile_scope_transactions AS tx
            WHERE NULLIF(BTRIM(tx.federal_account_combination_key), '') IS NOT NULL
            GROUP BY tx.federal_account_combination_key
        )
        SELECT
            combo_rows.federal_account_combination_key,
            combo_rows.contains_075_0140,
            (
                combo_rows.contains_075_0140
                OR combo_rows.has_mixed_scope_emergency
                OR combo_rows.has_emergency_scope_match
            ) AS chip_emergency_flag,
            CASE
                WHEN combo_rows.contains_075_0140 THEN 'phssef_emergency_fund'
                WHEN combo_rows.has_emergency_scope_match THEN 'profile_scope_emergency_indicator'
                WHEN combo_rows.has_mixed_scope_emergency THEN 'mixed_scope_emergency_indicator'
                ELSE 'none'
            END AS chip_emergency_type,
            CASE
                WHEN combo_rows.contains_075_0140 THEN 'account_key_contains_075_0140'
                WHEN combo_rows.has_emergency_scope_match THEN 'effective_funding_scope_marked_emergency_public_health'
                WHEN combo_rows.has_mixed_scope_emergency THEN 'mixed_scope_contains_emergency'
                ELSE 'no_emergency_indicator_detected'
            END AS chip_classification_reason,
            CASE
                WHEN combo_rows.contains_075_0140 THEN 'high'
                WHEN combo_rows.has_emergency_scope_match OR combo_rows.has_mixed_scope_emergency THEN 'medium'
                ELSE 'high'
            END AS chip_classification_confidence,
            CASE
                WHEN combo_rows.contains_075_0140 THEN 'Explicit emergency detection rule from federal_account_combination_key.'
                WHEN combo_rows.has_emergency_scope_match OR combo_rows.has_mixed_scope_emergency THEN 'Fallback emergency indicator retained for future extensibility.'
                ELSE 'Default non-emergency account combination.'
            END AS chip_classification_notes
        FROM combo_rows
        """
    )

    op.execute(
        f"""
        CREATE VIEW {ANALYTICS_SCHEMA}.chip_recipient_classification_resolved_v11_ec AS
        WITH source_recipients AS (
            SELECT DISTINCT
                tx.recipient_name AS recipient_name_raw,
                {normalized_source_recipient_name} AS recipient_name_normalized
            FROM {RECON_SCHEMA}.profile_scope_transactions AS tx
            WHERE NULLIF(BTRIM(tx.recipient_name), '') IS NOT NULL
        ),
        curated_exact_candidates AS (
            SELECT
                sr.recipient_name_raw,
                sr.recipient_name_normalized,
                c.id,
                c.entity_group_name,
                c.recipient_type,
                c.is_state_like,
                c.is_local_public_health_like,
                c.is_public_university_like,
                c.is_intermediary,
                c.classification_source,
                c.match_source,
                c.review_notes,
                c.confidence,
                ROW_NUMBER() OVER (
                    PARTITION BY sr.recipient_name_raw, sr.recipient_name_normalized
                    ORDER BY c.override_priority DESC, c.id ASC
                ) AS rn
            FROM source_recipients AS sr
            JOIN {ANALYTICS_SCHEMA}.chip_recipient_classification_curated_v11_ec AS c
              ON c.active_flag IS TRUE
             AND UPPER(BTRIM(c.recipient_name_raw)) = UPPER(BTRIM(sr.recipient_name_raw))
             AND (c.effective_start_date IS NULL OR c.effective_start_date <= CURRENT_DATE)
             AND (c.effective_end_date IS NULL OR c.effective_end_date >= CURRENT_DATE)
        ),
        curated_exact AS (
            SELECT *
            FROM curated_exact_candidates
            WHERE rn = 1
        ),
        curated_normalized_candidates AS (
            SELECT
                sr.recipient_name_raw,
                sr.recipient_name_normalized,
                c.id,
                c.entity_group_name,
                c.recipient_type,
                c.is_state_like,
                c.is_local_public_health_like,
                c.is_public_university_like,
                c.is_intermediary,
                c.classification_source,
                c.match_source,
                c.review_notes,
                c.confidence,
                ROW_NUMBER() OVER (
                    PARTITION BY sr.recipient_name_raw, sr.recipient_name_normalized
                    ORDER BY c.override_priority DESC, c.id ASC
                ) AS rn
            FROM source_recipients AS sr
            JOIN {ANALYTICS_SCHEMA}.chip_recipient_classification_curated_v11_ec AS c
              ON c.active_flag IS TRUE
             AND c.recipient_name_normalized = sr.recipient_name_normalized
             AND (c.effective_start_date IS NULL OR c.effective_start_date <= CURRENT_DATE)
             AND (c.effective_end_date IS NULL OR c.effective_end_date >= CURRENT_DATE)
        ),
        curated_normalized AS (
            SELECT *
            FROM curated_normalized_candidates
            WHERE rn = 1
        ),
        heuristic_candidates AS (
            SELECT
                sr.recipient_name_raw,
                sr.recipient_name_normalized,
                r.rule_id,
                r.rule_name,
                r.assigned_recipient_type,
                r.assigned_state_like,
                r.assigned_local_public_health_like,
                r.assigned_public_university_like,
                r.assigned_intermediary,
                r.rule_notes,
                ROW_NUMBER() OVER (
                    PARTITION BY sr.recipient_name_raw, sr.recipient_name_normalized
                    ORDER BY r.rule_priority DESC, r.rule_id ASC
                ) AS rn
            FROM source_recipients AS sr
            JOIN {ANALYTICS_SCHEMA}.chip_recipient_classification_rules_v11_ec AS r
              ON r.active_flag IS TRUE
             AND CASE
                    WHEN r.match_type = 'exact' THEN UPPER(BTRIM(sr.recipient_name_raw)) = UPPER(BTRIM(r.match_value))
                    WHEN r.match_type = 'normalized_exact' THEN sr.recipient_name_normalized = { _normalized_name_sql("r.match_value") }
                    WHEN r.match_type = 'contains' THEN sr.recipient_name_normalized LIKE '%' || UPPER(BTRIM(r.match_value)) || '%'
                    WHEN r.match_type = 'prefix' THEN sr.recipient_name_normalized LIKE UPPER(BTRIM(r.match_value)) || '%'
                    WHEN r.match_type = 'regex' THEN LOWER(COALESCE(sr.recipient_name_raw, '')) ~ LOWER(r.match_value)
                    ELSE FALSE
                 END
        ),
        heuristic_match AS (
            SELECT *
            FROM heuristic_candidates
            WHERE rn = 1
        )
        SELECT
            sr.recipient_name_raw,
            sr.recipient_name_normalized,
            COALESCE(ce.entity_group_name, cn.entity_group_name, hm.rule_name, 'unresolved') AS entity_group_name,
            COALESCE(ce.recipient_type, cn.recipient_type, hm.assigned_recipient_type, 'unclassified') AS recipient_type,
            COALESCE(ce.is_state_like, cn.is_state_like, hm.assigned_state_like, false) AS is_state_like,
            COALESCE(ce.is_local_public_health_like, cn.is_local_public_health_like, hm.assigned_local_public_health_like, false) AS is_local_public_health_like,
            COALESCE(ce.is_public_university_like, cn.is_public_university_like, hm.assigned_public_university_like, false) AS is_public_university_like,
            COALESCE(ce.is_intermediary, cn.is_intermediary, hm.assigned_intermediary, false) AS is_intermediary,
            CASE
                WHEN ce.id IS NOT NULL THEN COALESCE(ce.classification_source, 'manual_override')
                WHEN cn.id IS NOT NULL THEN COALESCE(cn.classification_source, 'curated_normalized')
                WHEN hm.rule_id IS NOT NULL THEN 'heuristic_pattern'
                ELSE 'heuristic_fallback'
            END AS classification_source,
            CASE
                WHEN ce.id IS NOT NULL THEN COALESCE(ce.match_source, 'exact_name')
                WHEN cn.id IS NOT NULL THEN COALESCE(cn.match_source, 'normalized_name')
                WHEN hm.rule_id IS NOT NULL THEN 'pattern_rule'
                ELSE 'inherited_default'
            END AS match_source,
            COALESCE(ce.id, cn.id, hm.rule_id) AS recipient_match_rule_id,
            COALESCE(ce.review_notes, cn.review_notes, hm.rule_notes, 'No curated recipient match. Review recommended before broadening intermediary or university coverage.') AS review_notes,
            COALESCE(ce.confidence, cn.confidence, CASE WHEN hm.rule_id IS NOT NULL THEN 'medium' ELSE 'low' END) AS confidence,
            CASE
                WHEN ce.id IS NOT NULL AND COALESCE(ce.classification_source, '') = 'manual_override' THEN 'reviewed_override'
                WHEN ce.id IS NOT NULL OR cn.id IS NOT NULL THEN 'seeded'
                WHEN hm.rule_id IS NOT NULL THEN 'heuristic_only'
                ELSE 'needs_review'
            END AS recipient_review_status,
            CASE
                WHEN ce.id IS NOT NULL OR cn.id IS NOT NULL THEN 'curated'
                WHEN hm.rule_id IS NOT NULL THEN 'heuristic'
                ELSE 'unresolved'
            END AS chip_recipient_classification_tier
        FROM source_recipients AS sr
        LEFT JOIN curated_exact AS ce
          ON ce.recipient_name_raw = sr.recipient_name_raw
         AND ce.recipient_name_normalized = sr.recipient_name_normalized
        LEFT JOIN curated_normalized AS cn
          ON cn.recipient_name_raw = sr.recipient_name_raw
         AND cn.recipient_name_normalized = sr.recipient_name_normalized
         AND ce.id IS NULL
        LEFT JOIN heuristic_match AS hm
          ON hm.recipient_name_raw = sr.recipient_name_raw
         AND hm.recipient_name_normalized = sr.recipient_name_normalized
         AND ce.id IS NULL
         AND cn.id IS NULL
        """
    )

    op.execute(
        f"""
        CREATE VIEW {ANALYTICS_SCHEMA}.chip_funding_classification_v11_ec AS
        WITH source_meta AS (
            SELECT TO_CHAR(COALESCE(MAX(refreshed_at), NOW()), 'YYYYMMDD') AS source_snapshot_date
            FROM {RECON_SCHEMA}.profile_scope_transactions
        ),
        run_meta AS (
            SELECT
                'chip_ec_v1_1_' || source_snapshot_date || '_{RULE_SET_VERSION}' AS run_id
            FROM source_meta
        ),
        base AS (
            SELECT
                tx.source_system,
                tx.source_transaction_id,
                tx.fiscal_year,
                tx.state_code,
                state_dim.state_fips,
                COALESCE(state_dim.state_name, state_dim.state_abbr, tx.state_code) AS state,
                tx.raw_amount,
                tx.include_in_profile_scope,
                tx.inclusion_reason,
                tx.confidence_label,
                tx.federal_account_symbol,
                tx.federal_account_combination_key,
                tx.effective_funding_scope,
                tx.mixed_scope_contains_emergency,
                tx.conservative_inclusion_reason,
                tx.manual_review_recommended,
                tx.methodology_version AS source_methodology_version,
                tx.recipient_name AS recipient_name_raw,
                {normalized_recipient_name} AS recipient_name_normalized,
                COALESCE(acc.chip_emergency_flag, false) AS chip_emergency_flag,
                COALESCE(acc.chip_emergency_type, 'none') AS chip_emergency_type,
                COALESCE(acc.chip_classification_reason, 'no_emergency_indicator_detected') AS account_classification_reason,
                COALESCE(acc.chip_classification_confidence, 'high') AS account_classification_confidence,
                COALESCE(acc.chip_classification_notes, 'No account classification notes.') AS account_classification_notes,
                COALESCE(rec.entity_group_name, 'unresolved') AS entity_group_name,
                COALESCE(rec.recipient_type, 'unclassified') AS recipient_type,
                COALESCE(rec.is_state_like, false) AS chip_recipient_is_state_like,
                COALESCE(rec.is_local_public_health_like, false) AS chip_recipient_is_local_public_health_like,
                COALESCE(rec.is_public_university_like, false) AS chip_recipient_is_public_university_like,
                COALESCE(rec.is_intermediary, false) AS chip_recipient_is_intermediary_like,
                COALESCE(rec.is_intermediary, false) AS chip_intermediary_flag,
                COALESCE(rec.classification_source, 'heuristic_fallback') AS recipient_classification_source,
                COALESCE(rec.match_source, 'inherited_default') AS recipient_match_source,
                rec.recipient_match_rule_id,
                COALESCE(rec.recipient_review_status, 'needs_review') AS recipient_review_status,
                COALESCE(rec.chip_recipient_classification_tier, 'unresolved') AS chip_recipient_classification_tier,
                COALESCE(rec.review_notes, tx.conservative_inclusion_reason) AS recipient_review_notes,
                COALESCE(rec.confidence, 'low') AS recipient_match_confidence
            FROM {RECON_SCHEMA}.profile_scope_transactions AS tx
            LEFT JOIN {ANALYTICS_SCHEMA}.chip_funding_account_classification_v11_ec AS acc
              ON acc.federal_account_combination_key = tx.federal_account_combination_key
            LEFT JOIN {ANALYTICS_SCHEMA}.chip_recipient_classification_resolved_v11_ec AS rec
              ON rec.recipient_name_raw = tx.recipient_name
             AND rec.recipient_name_normalized = {normalized_recipient_name}
            LEFT JOIN {PLACES_SCHEMA}.dim_state_boundary AS state_dim
              ON state_dim.state_abbr = tx.state_code
        ),
        decision AS (
            SELECT
                base.*,
                (
                    base.chip_recipient_is_state_like
                    OR base.chip_recipient_is_local_public_health_like
                    OR (
                        base.chip_recipient_is_public_university_like
                        AND base.chip_intermediary_flag IS FALSE
                        AND base.recipient_review_status <> 'needs_review'
                    )
                ) AS chip_state_relevant_recipient_candidate
            FROM base
        )
        SELECT
            '{MODEL_VERSION}'::text AS chip_model_version,
            '{METHODOLOGY_VERSION}'::text AS chip_methodology_version,
            '{ROLLOUT_STATUS}'::text AS chip_rollout_status,
            '{STATE_PROFILE_SOURCE_VERSION}'::text AS chip_state_profile_source_version,
            '{NORMALIZATION_SOURCE_VERSION}'::text AS chip_normalization_source_version,
            run_meta.run_id,
            decision.source_system,
            decision.source_transaction_id,
            decision.fiscal_year,
            decision.state_code,
            decision.state_fips,
            decision.state,
            decision.raw_amount,
            decision.federal_account_symbol,
            decision.federal_account_combination_key,
            decision.recipient_name_raw,
            decision.recipient_name_normalized,
            decision.entity_group_name,
            decision.recipient_type,
            decision.recipient_classification_source,
            decision.recipient_match_source,
            decision.recipient_match_rule_id,
            decision.recipient_review_status,
            decision.chip_recipient_classification_tier,
            decision.chip_recipient_is_state_like,
            decision.chip_recipient_is_local_public_health_like,
            decision.chip_recipient_is_public_university_like,
            decision.chip_recipient_is_intermediary_like,
            decision.chip_intermediary_flag,
            decision.chip_emergency_flag,
            decision.chip_emergency_type,
            CASE
                WHEN decision.chip_emergency_flag IS FALSE AND decision.include_in_profile_scope IS TRUE THEN 'core_cdc_program'
                WHEN decision.chip_emergency_flag IS TRUE AND decision.chip_intermediary_flag IS TRUE THEN 'emergency_centralized'
                WHEN decision.chip_emergency_flag IS TRUE AND decision.chip_state_relevant_recipient_candidate IS TRUE THEN 'emergency_distributed'
                WHEN decision.chip_emergency_flag IS TRUE THEN 'emergency_unresolved_excluded'
                ELSE 'other_explicitly_excluded'
            END AS chip_funding_category,
            CASE
                WHEN decision.chip_emergency_flag IS FALSE AND decision.include_in_profile_scope IS TRUE THEN TRUE
                WHEN decision.chip_emergency_flag IS TRUE AND decision.chip_state_relevant_recipient_candidate IS TRUE AND decision.chip_intermediary_flag IS FALSE THEN TRUE
                ELSE FALSE
            END AS chip_include_in_state_profile,
            CASE
                WHEN decision.chip_emergency_flag IS FALSE AND decision.include_in_profile_scope IS TRUE THEN COALESCE(NULLIF(BTRIM(decision.confidence_label), ''), 'medium')
                WHEN decision.chip_emergency_flag IS TRUE AND decision.chip_intermediary_flag IS TRUE AND decision.chip_recipient_classification_tier = 'curated' THEN 'high'
                WHEN decision.chip_emergency_flag IS TRUE AND decision.chip_intermediary_flag IS TRUE THEN 'medium'
                WHEN decision.chip_emergency_flag IS TRUE AND decision.chip_state_relevant_recipient_candidate IS TRUE AND decision.chip_recipient_classification_tier = 'curated' THEN 'high'
                WHEN decision.chip_emergency_flag IS TRUE AND decision.chip_state_relevant_recipient_candidate IS TRUE THEN 'medium'
                WHEN decision.chip_emergency_flag IS TRUE THEN 'low'
                ELSE COALESCE(NULLIF(BTRIM(decision.confidence_label), ''), 'medium')
            END AS chip_classification_confidence,
            CASE
                WHEN decision.chip_emergency_flag IS FALSE AND decision.include_in_profile_scope IS TRUE THEN 'Existing CHIP profile-scope row retained as core CDC program funding.'
                WHEN decision.chip_emergency_flag IS TRUE AND decision.chip_intermediary_flag IS TRUE THEN 'Emergency row excluded from the state profile because the recipient is classified as a centralized intermediary.'
                WHEN decision.chip_emergency_flag IS TRUE AND decision.chip_state_relevant_recipient_candidate IS TRUE THEN 'Emergency row included in the state profile because the recipient is classified as a state-relevant implementer.'
                WHEN decision.chip_emergency_flag IS TRUE THEN 'Emergency row excluded from the state profile because recipient geography is unresolved or low-confidence.'
                ELSE 'Existing non-emergency row remains outside the state profile under the prior CHIP profile-scope rules.'
            END AS chip_classification_reason,
            CONCAT_WS(
                '; ',
                'account_reason=' || decision.account_classification_reason,
                'recipient_source=' || decision.recipient_classification_source,
                'recipient_match=' || decision.recipient_match_source,
                decision.account_classification_notes,
                decision.recipient_review_notes
            ) AS chip_classification_notes,
            CASE
                WHEN decision.chip_emergency_flag IS TRUE AND decision.chip_intermediary_flag IS TRUE THEN 'centralized_intermediary_excluded_from_state_profile'
                WHEN decision.chip_emergency_flag IS TRUE AND decision.chip_state_relevant_recipient_candidate IS FALSE THEN 'low_confidence_emergency_recipient_excluded_from_state_profile'
                WHEN decision.chip_emergency_flag IS FALSE AND decision.include_in_profile_scope IS FALSE THEN COALESCE(NULLIF(BTRIM(decision.inclusion_reason), ''), 'existing_profile_scope_excluded')
                WHEN decision.chip_emergency_flag IS FALSE AND decision.include_in_profile_scope IS NULL THEN 'existing_profile_scope_unresolved'
                ELSE NULL
            END AS chip_profile_exclusion_reason,
            COALESCE(decision.recipient_review_notes, decision.conservative_inclusion_reason) AS review_notes,
            decision.include_in_profile_scope AS existing_profile_scope_flag,
            decision.inclusion_reason AS existing_profile_scope_reason,
            decision.source_methodology_version
        FROM decision
        CROSS JOIN run_meta
        """
    )

    op.execute(
        f"""
        CREATE VIEW {ANALYTICS_SCHEMA}.chip_state_funding_profile_v11_ec AS
        SELECT
            c.state_code,
            c.state_fips,
            c.state,
            c.fiscal_year,
            COUNT(*)::integer AS transaction_count,
            COALESCE(SUM(c.raw_amount), 0)::numeric(18, 2) AS total_state_relevant_funding,
            COALESCE(SUM(c.raw_amount) FILTER (WHERE c.chip_funding_category = 'core_cdc_program'), 0)::numeric(18, 2) AS core_cdc_program_funding,
            COALESCE(SUM(c.raw_amount) FILTER (WHERE c.chip_funding_category = 'emergency_distributed'), 0)::numeric(18, 2) AS emergency_distributed_funding,
            MAX(c.chip_model_version) AS model_version,
            MAX(c.chip_methodology_version) AS methodology_version,
            MAX(c.chip_rollout_status) AS chip_rollout_status,
            MAX(c.chip_state_profile_source_version) AS chip_state_profile_source_version,
            MAX(c.chip_normalization_source_version) AS chip_normalization_source_version,
            MAX(c.run_id) AS run_id
        FROM {ANALYTICS_SCHEMA}.chip_funding_classification_v11_ec AS c
        WHERE c.chip_include_in_state_profile IS TRUE
        GROUP BY
            c.state_code,
            c.state_fips,
            c.state,
            c.fiscal_year
        """
    )

    op.execute(
        f"""
        CREATE VIEW {ANALYTICS_SCHEMA}.chip_centralized_funding_v11_ec AS
        SELECT *
        FROM {ANALYTICS_SCHEMA}.chip_funding_classification_v11_ec
        WHERE chip_funding_category = 'emergency_centralized'
        """
    )

    op.execute(
        f"""
        CREATE VIEW {ANALYTICS_SCHEMA}.chip_funding_classification_summary_v11_ec AS
        SELECT
            fiscal_year,
            chip_funding_category,
            chip_include_in_state_profile,
            chip_classification_confidence,
            recipient_classification_source,
            chip_emergency_flag,
            COUNT(*)::integer AS row_count,
            COALESCE(SUM(raw_amount), 0)::numeric(18, 2) AS total_amount
        FROM {ANALYTICS_SCHEMA}.chip_funding_classification_v11_ec
        GROUP BY
            fiscal_year,
            chip_funding_category,
            chip_include_in_state_profile,
            chip_classification_confidence,
            recipient_classification_source,
            chip_emergency_flag
        """
    )

    op.execute(
        f"""
        CREATE VIEW {ANALYTICS_SCHEMA}.chip_transaction_conservation_validation_v11_ec AS
        WITH base AS (
            SELECT
                COALESCE(fiscal_year::text, 'all_years') AS scope_key,
                raw_amount,
                chip_funding_category,
                chip_include_in_state_profile
            FROM {ANALYTICS_SCHEMA}.chip_funding_classification_v11_ec
            UNION ALL
            SELECT
                'all_years' AS scope_key,
                raw_amount,
                chip_funding_category,
                chip_include_in_state_profile
            FROM {ANALYTICS_SCHEMA}.chip_funding_classification_v11_ec
        )
        SELECT
            scope_key AS fiscal_year_scope,
            COUNT(*)::integer AS total_classified_rows,
            COALESCE(SUM(raw_amount), 0)::numeric(18, 2) AS total_classified_amount,
            COUNT(*) FILTER (WHERE chip_include_in_state_profile IS TRUE)::integer AS included_in_profile_rows,
            COALESCE(SUM(raw_amount) FILTER (WHERE chip_include_in_state_profile IS TRUE), 0)::numeric(18, 2) AS included_in_profile_amount,
            COUNT(*) FILTER (WHERE chip_funding_category = 'emergency_centralized')::integer AS emergency_centralized_excluded_rows,
            COALESCE(SUM(raw_amount) FILTER (WHERE chip_funding_category = 'emergency_centralized'), 0)::numeric(18, 2) AS emergency_centralized_excluded_amount,
            COUNT(*) FILTER (WHERE chip_funding_category IN ('other_explicitly_excluded', 'emergency_unresolved_excluded'))::integer AS other_explicitly_excluded_rows,
            COALESCE(SUM(raw_amount) FILTER (WHERE chip_funding_category IN ('other_explicitly_excluded', 'emergency_unresolved_excluded')), 0)::numeric(18, 2) AS other_explicitly_excluded_amount,
            COUNT(*) FILTER (WHERE chip_funding_category = 'emergency_unresolved_excluded')::integer AS unresolved_low_confidence_rows,
            COALESCE(SUM(raw_amount) FILTER (WHERE chip_funding_category = 'emergency_unresolved_excluded'), 0)::numeric(18, 2) AS unresolved_low_confidence_amount,
            (
                COALESCE(SUM(raw_amount), 0)
                - COALESCE(SUM(raw_amount) FILTER (WHERE chip_include_in_state_profile IS TRUE), 0)
                - COALESCE(SUM(raw_amount) FILTER (WHERE chip_funding_category = 'emergency_centralized'), 0)
                - COALESCE(SUM(raw_amount) FILTER (WHERE chip_funding_category IN ('other_explicitly_excluded', 'emergency_unresolved_excluded')), 0)
            )::numeric(18, 2) AS residual_amount
        FROM base
        GROUP BY scope_key
        """
    )

    op.execute(
        f"""
        CREATE VIEW {ANALYTICS_SCHEMA}.chip_state_funding_profile_validation_v11_ec AS
        SELECT
            COALESCE(v11.state_code, v1.state_code) AS state_code,
            COALESCE(v11.state_fips, state_dim.state_fips) AS state_fips,
            COALESCE(v11.state, state_dim.state_name, v1.state_code) AS state,
            COALESCE(v11.fiscal_year, v1.fiscal_year) AS fiscal_year,
            v1.raw_amount AS v1_raw_total_funding,
            v1.normalized_amount AS v1_normalized_total_funding,
            v11.total_state_relevant_funding,
            v11.core_cdc_program_funding,
            v11.emergency_distributed_funding,
            (COALESCE(v11.total_state_relevant_funding, 0) - COALESCE(v1.raw_amount, 0))::numeric(18, 2) AS raw_total_delta_amount,
            CASE
                WHEN COALESCE(v1.raw_amount, 0) = 0 THEN NULL
                ELSE ((COALESCE(v11.total_state_relevant_funding, 0) - COALESCE(v1.raw_amount, 0)) / NULLIF(v1.raw_amount, 0))::numeric(12, 6)
            END AS raw_total_delta_pct,
            v11.transaction_count,
            v11.model_version,
            v11.methodology_version,
            v11.run_id
        FROM {ANALYTICS_SCHEMA}.chip_state_funding_profile_v11_ec AS v11
        FULL OUTER JOIN {RECON_SCHEMA}.normalized_state_funding AS v1
          ON v1.source_system = 'usaspending'
         AND v1.state_code = v11.state_code
         AND v1.fiscal_year = v11.fiscal_year
        LEFT JOIN {PLACES_SCHEMA}.dim_state_boundary AS state_dim
          ON state_dim.state_abbr = COALESCE(v11.state_code, v1.state_code)
        """
    )

    op.execute(
        f"""
        CREATE VIEW {ANALYTICS_SCHEMA}.chip_recipient_review_queue_v11_ec AS
        SELECT
            recipient_name_normalized,
            MIN(recipient_name_raw) AS recipient_name_raw,
            MAX(state_code) AS sample_state_code,
            MAX(state) AS sample_state,
            MAX(recipient_classification_source) AS recipient_classification_source,
            MAX(recipient_match_source) AS recipient_match_source,
            MAX(recipient_review_status) AS recipient_review_status,
            MAX(chip_recipient_classification_tier) AS chip_recipient_classification_tier,
            MAX(review_notes) AS review_notes,
            COUNT(*)::integer AS transaction_count,
            COALESCE(SUM(raw_amount), 0)::numeric(18, 2) AS total_amount,
            COALESCE(SUM(raw_amount) FILTER (WHERE chip_emergency_flag IS TRUE), 0)::numeric(18, 2) AS emergency_amount
        FROM {ANALYTICS_SCHEMA}.chip_funding_classification_v11_ec
        WHERE recipient_review_status IN ('needs_review', 'heuristic_only')
           OR chip_funding_category = 'emergency_unresolved_excluded'
        GROUP BY recipient_name_normalized
        """
    )


def downgrade() -> None:
    for view_name in [
        "chip_recipient_review_queue_v11_ec",
        "chip_state_funding_profile_validation_v11_ec",
        "chip_transaction_conservation_validation_v11_ec",
        "chip_funding_classification_summary_v11_ec",
        "chip_centralized_funding_v11_ec",
        "chip_state_funding_profile_v11_ec",
        "chip_funding_classification_v11_ec",
        "chip_recipient_classification_resolved_v11_ec",
        "chip_funding_account_classification_v11_ec",
    ]:
        op.execute(f"DROP VIEW IF EXISTS {ANALYTICS_SCHEMA}.{view_name}")

    op.drop_index(
        "analytics_chip_recipient_rules_priority_idx",
        table_name="chip_recipient_classification_rules_v11_ec",
        schema=ANALYTICS_SCHEMA,
    )
    op.drop_index(
        "analytics_chip_recipient_rules_active_idx",
        table_name="chip_recipient_classification_rules_v11_ec",
        schema=ANALYTICS_SCHEMA,
    )
    op.drop_table("chip_recipient_classification_rules_v11_ec", schema=ANALYTICS_SCHEMA)

    op.drop_index(
        "analytics_chip_recipient_curated_normalized_idx",
        table_name="chip_recipient_classification_curated_v11_ec",
        schema=ANALYTICS_SCHEMA,
    )
    op.drop_index(
        "analytics_chip_recipient_curated_raw_idx",
        table_name="chip_recipient_classification_curated_v11_ec",
        schema=ANALYTICS_SCHEMA,
    )
    op.drop_table("chip_recipient_classification_curated_v11_ec", schema=ANALYTICS_SCHEMA)
