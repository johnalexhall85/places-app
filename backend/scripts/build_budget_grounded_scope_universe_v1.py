from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from app.db import DEFAULT_DB_URL
from app.db_fqtn import budget_table

DEFAULT_SCOPE_UNIVERSE_VERSION = "v1_budget_grounded_scope_universe"
TARGET_TABLE = budget_table("cdc_budget_grounded_scope_universe_v1")

TARGET_COLUMNS = [
    "scope_universe_version",
    "built_at",
    "resolution_id",
    "resolution_version",
    "bridge_version",
    "bridge_id",
    "budget_anchor_id",
    "classification_id",
    "raw_budget_id",
    "unique_id",
    "fiscal_year",
    "budget_agency",
    "budget_sub_agency",
    "budget_program",
    "budget_sub_program",
    "budget_sub_program_2",
    "budget_sub_program_3",
    "budget_program_key",
    "appropriation_category",
    "appropriation_subtype",
    "classification_confidence",
    "primary_rule_code",
    "system_name",
    "source_record_id",
    "source_parent_record_id",
    "source_fiscal_year",
    "match_tier",
    "match_type",
    "match_score",
    "match_confidence",
    "confidence_band",
    "resolution_status",
    "allocation_pct",
    "allocation_method",
    "resolution_method",
    "resolution_confidence",
    "analyst_reviewed",
    "auto_seeded",
    "resolution_reason_code",
    "reviewer_name",
    "reviewed_at",
    "analyst_review_state",
    "allocation_balance_status",
    "spending_program_name",
    "spending_assistance_listing_title",
    "spending_aln",
    "spending_can_code",
    "spending_program_office",
    "spending_award_title",
    "spending_award_description",
    "spending_appropriation_type",
    "discretionary_mandatory_type",
    "emergency_flag",
    "supplemental_flag",
    "pphf_flag",
    "transfer_flag",
    "non_add_flag",
    "include_in_master_universe",
    "inclusion_reason",
    "double_count_exclusion_flag",
    "double_count_exclusion_reason",
    "effective_allocation_pct",
    "scoped_amount_multiplier",
    "effective_scope_weight",
    "trusted_auto_seed_flag",
    "category_display_label",
    "filter_bucket",
    "budget_amount_dollars",
    "budget_amount_millions",
    "allocated_budget_amount_dollars",
    "allocated_budget_amount_millions",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the budget-grounded master scope universe from current resolved bridge rows.",
    )
    parser.add_argument(
        "--scope-universe-version",
        default=DEFAULT_SCOPE_UNIVERSE_VERSION,
        help=f"Version label stored in {TARGET_TABLE}.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Delete the targeted version slice before rebuilding it.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Accepted for CLI symmetry; table builds always refresh the targeted slice.",
    )
    parser.add_argument(
        "--fiscal-year",
        type=int,
        default=None,
        help="Optional fiscal year filter for partial rebuilds.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and summarize the build rows without writing to the target table.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or the local development DSN).",
    )
    return parser.parse_args()


def build_select_sql() -> str:
    return f"""
        WITH current_resolution AS (
            SELECT *
            FROM budget.v_cdc_budget_spending_bridge_resolution_current_v1
        ),
        anchor_context AS (
            SELECT
                budget_anchor_id,
                COUNT(*) FILTER (WHERE analyst_reviewed = TRUE) AS analyst_reviewed_current_count
            FROM current_resolution
            GROUP BY budget_anchor_id
        ),
        base AS (
            SELECT
                CAST(:scope_universe_version AS text) AS scope_universe_version,
                NOW() AS built_at,
                r.id AS resolution_id,
                r.resolution_version,
                r.bridge_version,
                r.bridge_id,
                r.budget_anchor_id,
                r.classification_id,
                r.raw_budget_id,
                r.unique_id,
                r.fiscal_year,
                r.budget_agency,
                r.budget_sub_agency,
                r.budget_program,
                r.budget_sub_program,
                r.budget_sub_program_2,
                r.budget_sub_program_3,
                r.budget_program_key,
                r.appropriation_category,
                r.appropriation_subtype,
                COALESCE(r.classification_confidence, c.classification_confidence) AS classification_confidence,
                COALESCE(r.primary_rule_code, c.primary_rule_code) AS primary_rule_code,
                r.system_name,
                r.source_record_id,
                r.source_parent_record_id,
                r.source_fiscal_year,
                r.match_tier,
                r.match_type,
                r.match_score,
                r.match_confidence,
                r.confidence_band,
                r.resolution_status,
                r.allocation_pct,
                r.allocation_method,
                r.resolution_method,
                r.resolution_confidence,
                r.analyst_reviewed,
                r.auto_seeded,
                r.resolution_reason_code,
                r.reviewer_name,
                r.reviewed_at,
                review_state.analyst_review_state,
                review_state.allocation_balance_status,
                r.spending_program_name,
                r.spending_assistance_listing_title,
                r.spending_aln,
                r.spending_can_code,
                r.spending_program_office,
                r.spending_award_title,
                r.spending_award_description,
                r.spending_appropriation_type,
                c.amount_dollars AS budget_amount_dollars,
                c.amount_millions AS budget_amount_millions,
                c.signal_funding_type_mandatory,
                c.signal_non_add,
                c.is_non_add,
                c.signal_keyword_emergency,
                c.signal_keyword_covid,
                c.signal_keyword_arp,
                c.signal_keyword_cares,
                c.signal_keyword_rescue_plan,
                COALESCE(anchor_context.analyst_reviewed_current_count, 0) AS analyst_reviewed_current_count,
                COALESCE(r.allocation_pct, 1.000000::numeric) AS effective_allocation_pct
            FROM current_resolution AS r
            JOIN budget.cdc_budget_classification_v1 AS c
              ON c.id = r.classification_id
            LEFT JOIN budget.v_cdc_budget_spending_anchor_review_state_v1 AS review_state
              ON review_state.budget_anchor_id = r.budget_anchor_id
            LEFT JOIN anchor_context
              ON anchor_context.budget_anchor_id = r.budget_anchor_id
            WHERE r.resolution_status IN ('accepted', 'accepted_partial')
              AND r.scope_include_flag = TRUE
              AND (CAST(:fiscal_year AS integer) IS NULL OR r.fiscal_year = CAST(:fiscal_year AS integer))
        ),
        derived AS (
            SELECT
                base.*,
                base.effective_allocation_pct AS scoped_amount_multiplier,
                base.effective_allocation_pct AS effective_scope_weight,
                CASE
                    WHEN COALESCE(base.appropriation_category, '') IN ('NON_ADD', 'REQUEST_ONLY', 'TOTAL_OR_SUBTOTAL', 'UNKNOWN', '')
                        THEN 'unknown'
                    WHEN base.appropriation_category = 'MANDATORY'
                      OR COALESCE(base.signal_funding_type_mandatory, FALSE)
                        THEN 'mandatory'
                    ELSE 'discretionary'
                END AS discretionary_mandatory_type,
                CASE
                    WHEN base.appropriation_category = 'SUPPLEMENTAL'
                     AND (
                            LOWER(COALESCE(base.appropriation_subtype, '')) LIKE '%emergency%'
                         OR LOWER(COALESCE(base.appropriation_subtype, '')) LIKE '%covid%'
                         OR COALESCE(base.signal_keyword_emergency, FALSE)
                         OR COALESCE(base.signal_keyword_covid, FALSE)
                         OR COALESCE(base.signal_keyword_arp, FALSE)
                         OR COALESCE(base.signal_keyword_cares, FALSE)
                         OR COALESCE(base.signal_keyword_rescue_plan, FALSE)
                         OR LOWER(COALESCE(base.spending_appropriation_type, '')) IN ('covid_emergency', 'other_emergency', 'emergency')
                     )
                        THEN TRUE
                    ELSE FALSE
                END AS emergency_flag,
                CASE
                    WHEN base.appropriation_category = 'PPHF'
                      OR LOWER(COALESCE(base.appropriation_subtype, '')) LIKE '%prevention%'
                        THEN TRUE
                    ELSE FALSE
                END AS pphf_flag,
                CASE
                    WHEN base.appropriation_category = 'TRANSFER'
                      OR LOWER(COALESCE(base.appropriation_subtype, '')) LIKE '%transfer%'
                        THEN TRUE
                    ELSE FALSE
                END AS transfer_flag,
                CASE
                    WHEN base.appropriation_category = 'NON_ADD'
                      OR COALESCE(base.signal_non_add, FALSE)
                      OR LOWER(COALESCE(base.is_non_add, '')) IN ('1', 'true', 't', 'yes', 'y')
                        THEN TRUE
                    ELSE FALSE
                END AS non_add_flag,
                CASE
                    WHEN base.resolution_status = 'accepted'
                      AND base.auto_seeded = TRUE
                      AND base.analyst_reviewed = FALSE
                      AND base.match_tier = 'TIER_A_DETERMINISTIC'
                      AND base.confidence_band = 'HIGH'
                      AND COALESCE(base.analyst_reviewed_current_count, 0) = 0
                        THEN TRUE
                    ELSE FALSE
                END AS trusted_auto_seed_flag
            FROM base
        ),
        classified AS (
            SELECT
                derived.*,
                CASE
                    WHEN derived.appropriation_category = 'SUPPLEMENTAL'
                     AND derived.emergency_flag = FALSE
                        THEN TRUE
                    ELSE FALSE
                END AS supplemental_flag,
                COUNT(*) OVER (
                    PARTITION BY derived.budget_anchor_id, derived.system_name, derived.source_record_id
                ) AS duplicate_source_record_count,
                ROW_NUMBER() OVER (
                    PARTITION BY derived.budget_anchor_id, derived.system_name, derived.source_record_id
                    ORDER BY
                        derived.analyst_reviewed DESC,
                        derived.trusted_auto_seed_flag DESC,
                        CASE WHEN derived.resolution_status = 'accepted' THEN 0 ELSE 1 END,
                        COALESCE(derived.allocation_pct, 1.000000::numeric) DESC,
                        COALESCE(derived.resolution_confidence, derived.match_confidence, 0::numeric) DESC,
                        COALESCE(derived.match_confidence, 0::numeric) DESC,
                        derived.resolution_id DESC
                ) AS duplicate_source_record_rank
            FROM derived
        ),
        finalized AS (
            SELECT
                classified.scope_universe_version,
                classified.built_at,
                classified.resolution_id,
                classified.resolution_version,
                classified.bridge_version,
                classified.bridge_id,
                classified.budget_anchor_id,
                classified.classification_id,
                classified.raw_budget_id,
                classified.unique_id,
                classified.fiscal_year,
                classified.budget_agency,
                classified.budget_sub_agency,
                classified.budget_program,
                classified.budget_sub_program,
                classified.budget_sub_program_2,
                classified.budget_sub_program_3,
                classified.budget_program_key,
                classified.appropriation_category,
                classified.appropriation_subtype,
                classified.classification_confidence,
                classified.primary_rule_code,
                classified.system_name,
                classified.source_record_id,
                classified.source_parent_record_id,
                classified.source_fiscal_year,
                classified.match_tier,
                classified.match_type,
                classified.match_score,
                classified.match_confidence,
                classified.confidence_band,
                classified.resolution_status,
                classified.allocation_pct,
                classified.allocation_method,
                classified.resolution_method,
                classified.resolution_confidence,
                classified.analyst_reviewed,
                classified.auto_seeded,
                classified.resolution_reason_code,
                classified.reviewer_name,
                classified.reviewed_at,
                classified.analyst_review_state,
                classified.allocation_balance_status,
                classified.spending_program_name,
                classified.spending_assistance_listing_title,
                classified.spending_aln,
                classified.spending_can_code,
                classified.spending_program_office,
                classified.spending_award_title,
                classified.spending_award_description,
                classified.spending_appropriation_type,
                classified.discretionary_mandatory_type,
                classified.emergency_flag,
                classified.supplemental_flag,
                classified.pphf_flag,
                classified.transfer_flag,
                classified.non_add_flag,
                CASE
                    WHEN COALESCE(classified.allocation_balance_status, '') <> 'balanced' THEN FALSE
                    WHEN classified.duplicate_source_record_count > 1 AND classified.duplicate_source_record_rank > 1 THEN FALSE
                    WHEN classified.non_add_flag THEN FALSE
                    WHEN classified.appropriation_category IN ('REQUEST_ONLY', 'TOTAL_OR_SUBTOTAL', 'UNKNOWN') THEN FALSE
                    WHEN classified.auto_seeded = TRUE AND classified.trusted_auto_seed_flag = FALSE THEN FALSE
                    ELSE TRUE
                END AS include_in_master_universe,
                CASE
                    WHEN COALESCE(classified.allocation_balance_status, '') <> 'balanced' THEN
                        'Excluded because current accepted in-scope allocations for the anchor are not balanced.'
                    WHEN classified.duplicate_source_record_count > 1 AND classified.duplicate_source_record_rank > 1 THEN
                        'Excluded duplicate anchor/source representation to avoid double counting; only the canonical row is eligible.'
                    WHEN classified.non_add_flag THEN
                        'Excluded because accepted scope rows should not carry non add.'
                    WHEN classified.appropriation_category = 'REQUEST_ONLY' THEN
                        'Excluded because accepted scope rows should not carry request only.'
                    WHEN classified.appropriation_category = 'TOTAL_OR_SUBTOTAL' THEN
                        'Excluded because accepted scope rows should not carry total or subtotal.'
                    WHEN classified.appropriation_category = 'UNKNOWN' THEN
                        'Excluded because accepted scope rows should not carry unknown.'
                    WHEN classified.auto_seeded = TRUE AND classified.trusted_auto_seed_flag = FALSE THEN
                        'Excluded auto-seeded row because it does not meet the trusted deterministic auto-seed rules.'
                    WHEN classified.analyst_reviewed = TRUE AND classified.resolution_status = 'accepted_partial' THEN
                        'Included analyst-reviewed accepted_partial row with allocation_pct applied to budget-grounded dollars.'
                    WHEN classified.analyst_reviewed = TRUE THEN
                        'Included analyst-reviewed accepted row in the budget-grounded master universe.'
                    WHEN classified.trusted_auto_seed_flag = TRUE THEN
                        'Included trusted deterministic auto-seeded accepted row in the budget-grounded master universe.'
                    ELSE
                        'Included curated non-auto accepted scope row in the budget-grounded master universe.'
                END AS inclusion_reason,
                CASE
                    WHEN COALESCE(classified.allocation_balance_status, '') <> 'balanced' THEN TRUE
                    WHEN classified.duplicate_source_record_count > 1 AND classified.duplicate_source_record_rank > 1 THEN TRUE
                    ELSE FALSE
                END AS double_count_exclusion_flag,
                CASE
                    WHEN COALESCE(classified.allocation_balance_status, '') <> 'balanced' THEN 'unbalanced_allocation'
                    WHEN classified.duplicate_source_record_count > 1 AND classified.duplicate_source_record_rank > 1 THEN 'duplicate_anchor_source_noncanonical'
                    ELSE NULL::text
                END AS double_count_exclusion_reason,
                classified.effective_allocation_pct,
                classified.scoped_amount_multiplier,
                classified.effective_scope_weight,
                classified.trusted_auto_seed_flag,
                CASE
                    WHEN classified.pphf_flag THEN 'PPHF'
                    WHEN classified.transfer_flag THEN 'Transfers'
                    WHEN classified.emergency_flag THEN 'Emergency supplemental'
                    WHEN classified.supplemental_flag THEN 'Other supplemental'
                    WHEN classified.discretionary_mandatory_type = 'mandatory' THEN 'Mandatory'
                    WHEN classified.discretionary_mandatory_type = 'discretionary' THEN 'Regular discretionary'
                    ELSE 'Unknown'
                END AS category_display_label,
                CASE
                    WHEN classified.pphf_flag THEN 'pphf'
                    WHEN classified.transfer_flag THEN 'transfer'
                    WHEN classified.emergency_flag THEN 'emergency_supplemental'
                    WHEN classified.supplemental_flag THEN 'other_supplemental'
                    WHEN classified.discretionary_mandatory_type = 'mandatory' THEN 'mandatory'
                    WHEN classified.discretionary_mandatory_type = 'discretionary' THEN 'regular_discretionary'
                    ELSE 'unknown'
                END AS filter_bucket,
                classified.budget_amount_dollars,
                classified.budget_amount_millions,
                CASE
                    WHEN classified.budget_amount_dollars IS NULL THEN NULL::numeric
                    ELSE classified.budget_amount_dollars * classified.effective_allocation_pct
                END AS allocated_budget_amount_dollars,
                CASE
                    WHEN classified.budget_amount_millions IS NULL THEN NULL::numeric
                    ELSE classified.budget_amount_millions * classified.effective_allocation_pct
                END AS allocated_budget_amount_millions
            FROM classified
        )
        SELECT
            {", ".join(TARGET_COLUMNS)}
        FROM finalized
    """


def create_temp_build_table(connection: Connection, *, scope_universe_version: str, fiscal_year: int | None) -> None:
    connection.execute(text("DROP TABLE IF EXISTS tmp_budget_grounded_scope_universe_build"))
    connection.execute(
        text(
            f"""
            CREATE TEMP TABLE tmp_budget_grounded_scope_universe_build ON COMMIT DROP AS
            {build_select_sql()}
            """
        ),
        {
            "scope_universe_version": scope_universe_version,
            "fiscal_year": fiscal_year,
        },
    )


def sync_target_table(
    connection: Connection,
    *,
    scope_universe_version: str,
    fiscal_year: int | None,
    truncate: bool,
) -> None:
    delete_params = {"scope_universe_version": scope_universe_version, "fiscal_year": fiscal_year}
    if truncate:
        if fiscal_year is None:
            connection.execute(
                text(
                    f"""
                    DELETE FROM {TARGET_TABLE}
                    WHERE scope_universe_version = :scope_universe_version
                    """
                ),
                delete_params,
            )
        else:
            connection.execute(
                text(
                    f"""
                    DELETE FROM {TARGET_TABLE}
                    WHERE scope_universe_version = :scope_universe_version
                      AND fiscal_year = :fiscal_year
                    """
                ),
                delete_params,
            )
    else:
        if fiscal_year is None:
            connection.execute(
                text(
                    f"""
                    DELETE FROM {TARGET_TABLE} AS target
                    WHERE target.scope_universe_version = :scope_universe_version
                      AND NOT EXISTS (
                          SELECT 1
                          FROM tmp_budget_grounded_scope_universe_build AS source
                          WHERE source.scope_universe_version = target.scope_universe_version
                            AND source.resolution_id = target.resolution_id
                      )
                    """
                ),
                delete_params,
            )
        else:
            connection.execute(
                text(
                    f"""
                    DELETE FROM {TARGET_TABLE} AS target
                    WHERE target.scope_universe_version = :scope_universe_version
                      AND target.fiscal_year = :fiscal_year
                      AND NOT EXISTS (
                          SELECT 1
                          FROM tmp_budget_grounded_scope_universe_build AS source
                          WHERE source.scope_universe_version = target.scope_universe_version
                            AND source.resolution_id = target.resolution_id
                      )
                    """
                ),
                delete_params,
            )

    upsert_assignments = ", ".join(
        f"{column} = EXCLUDED.{column}"
        for column in TARGET_COLUMNS
        if column not in {"scope_universe_version", "resolution_id"}
    )
    connection.execute(
        text(
            f"""
            INSERT INTO {TARGET_TABLE} ({", ".join(TARGET_COLUMNS)})
            SELECT {", ".join(TARGET_COLUMNS)}
            FROM tmp_budget_grounded_scope_universe_build
            ON CONFLICT (scope_universe_version, resolution_id)
            DO UPDATE SET {upsert_assignments}
            """
        )
    )


def print_summary(connection: Connection, relation: str, *, scope_universe_version: str, fiscal_year: int | None) -> None:
    filters = ["scope_universe_version = :scope_universe_version"]
    params: dict[str, object] = {"scope_universe_version": scope_universe_version}
    if fiscal_year is not None:
        filters.append("fiscal_year = :fiscal_year")
        params["fiscal_year"] = fiscal_year
    where_sql = " AND ".join(filters)

    total_row = connection.execute(
        text(f"SELECT COUNT(*)::bigint AS row_count FROM {relation} WHERE {where_sql}"),
        params,
    ).mappings().one()
    included_row = connection.execute(
        text(
            f"""
            SELECT
                COUNT(*) FILTER (WHERE include_in_master_universe = TRUE)::bigint AS included_count,
                COUNT(*) FILTER (WHERE include_in_master_universe = FALSE)::bigint AS excluded_count
            FROM {relation}
            WHERE {where_sql}
            """
        ),
        params,
    ).mappings().one()

    print(f"evaluated_rows={int(total_row['row_count'] or 0)}")
    print(f"included_rows={int(included_row['included_count'] or 0)}")
    print(f"excluded_rows={int(included_row['excluded_count'] or 0)}")

    print("rows_by_appropriation_category:")
    for row in connection.execute(
        text(
            f"""
            SELECT appropriation_category, COUNT(*)::bigint AS row_count
            FROM {relation}
            WHERE {where_sql}
            GROUP BY appropriation_category
            ORDER BY appropriation_category
            """
        ),
        params,
    ).mappings():
        print(f"  {row['appropriation_category']}: {int(row['row_count'] or 0)}")

    print("rows_by_discretionary_mandatory_type:")
    for row in connection.execute(
        text(
            f"""
            SELECT discretionary_mandatory_type, COUNT(*)::bigint AS row_count
            FROM {relation}
            WHERE {where_sql}
            GROUP BY discretionary_mandatory_type
            ORDER BY discretionary_mandatory_type
            """
        ),
        params,
    ).mappings():
        print(f"  {row['discretionary_mandatory_type']}: {int(row['row_count'] or 0)}")

    print("rows_by_ui_flags:")
    for row in connection.execute(
        text(
            f"""
            SELECT
                emergency_flag,
                supplemental_flag,
                pphf_flag,
                transfer_flag,
                COUNT(*)::bigint AS row_count
            FROM {relation}
            WHERE {where_sql}
            GROUP BY emergency_flag, supplemental_flag, pphf_flag, transfer_flag
            ORDER BY emergency_flag DESC, supplemental_flag DESC, pphf_flag DESC, transfer_flag DESC
            """
        ),
        params,
    ).mappings():
        print(
            "  "
            f"emergency={row['emergency_flag']} supplemental={row['supplemental_flag']} "
            f"pphf={row['pphf_flag']} transfer={row['transfer_flag']}: {int(row['row_count'] or 0)}"
        )

    print("rows_by_review_provenance:")
    for row in connection.execute(
        text(
            f"""
            SELECT
                analyst_reviewed,
                auto_seeded,
                trusted_auto_seed_flag,
                COUNT(*)::bigint AS row_count
            FROM {relation}
            WHERE {where_sql}
            GROUP BY analyst_reviewed, auto_seeded, trusted_auto_seed_flag
            ORDER BY analyst_reviewed DESC, auto_seeded DESC, trusted_auto_seed_flag DESC
            """
        ),
        params,
    ).mappings():
        print(
            "  "
            f"analyst_reviewed={row['analyst_reviewed']} auto_seeded={row['auto_seeded']} "
            f"trusted_auto_seed_flag={row['trusted_auto_seed_flag']}: {int(row['row_count'] or 0)}"
        )


def main() -> None:
    args = parse_args()
    engine = create_engine(args.db_url)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            create_temp_build_table(
                connection,
                scope_universe_version=args.scope_universe_version,
                fiscal_year=args.fiscal_year,
            )
            if args.dry_run:
                print_summary(
                    connection,
                    "tmp_budget_grounded_scope_universe_build",
                    scope_universe_version=args.scope_universe_version,
                    fiscal_year=args.fiscal_year,
                )
                transaction.rollback()
                return

            sync_target_table(
                connection,
                scope_universe_version=args.scope_universe_version,
                fiscal_year=args.fiscal_year,
                truncate=bool(args.truncate),
            )
            print_summary(
                connection,
                TARGET_TABLE,
                scope_universe_version=args.scope_universe_version,
                fiscal_year=args.fiscal_year,
            )
            transaction.commit()
        except Exception:
            transaction.rollback()
            raise


if __name__ == "__main__":
    main()
