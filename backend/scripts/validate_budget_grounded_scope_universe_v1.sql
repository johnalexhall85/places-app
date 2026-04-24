\echo '1. Total rows in the budget-grounded scope universe'
SELECT COUNT(*) AS total_rows
FROM budget.v_cdc_budget_grounded_scope_universe_v1;

\echo '2. Rows included vs excluded'
SELECT
    include_in_master_universe,
    COUNT(*) AS row_count
FROM budget.v_cdc_budget_grounded_scope_universe_v1
GROUP BY include_in_master_universe
ORDER BY include_in_master_universe DESC;

\echo '3. Included rows by appropriation_category'
SELECT
    appropriation_category,
    COUNT(*) AS row_count,
    COALESCE(SUM(allocated_budget_amount_dollars), 0) AS allocated_budget_amount_dollars
FROM budget.v_cdc_budget_grounded_scope_universe_included_v1
GROUP BY appropriation_category
ORDER BY allocated_budget_amount_dollars DESC, appropriation_category;

\echo '4. Included rows by discretionary_mandatory_type'
SELECT
    discretionary_mandatory_type,
    COUNT(*) AS row_count,
    COALESCE(SUM(allocated_budget_amount_dollars), 0) AS allocated_budget_amount_dollars
FROM budget.v_cdc_budget_grounded_scope_universe_included_v1
GROUP BY discretionary_mandatory_type
ORDER BY discretionary_mandatory_type;

\echo '5. Included rows by emergency_flag'
SELECT
    emergency_flag,
    COUNT(*) AS row_count,
    COALESCE(SUM(allocated_budget_amount_dollars), 0) AS allocated_budget_amount_dollars
FROM budget.v_cdc_budget_grounded_scope_universe_included_v1
GROUP BY emergency_flag
ORDER BY emergency_flag DESC;

\echo '6. Included rows by supplemental_flag'
SELECT
    supplemental_flag,
    COUNT(*) AS row_count,
    COALESCE(SUM(allocated_budget_amount_dollars), 0) AS allocated_budget_amount_dollars
FROM budget.v_cdc_budget_grounded_scope_universe_included_v1
GROUP BY supplemental_flag
ORDER BY supplemental_flag DESC;

\echo '7. Included rows by pphf_flag'
SELECT
    pphf_flag,
    COUNT(*) AS row_count,
    COALESCE(SUM(allocated_budget_amount_dollars), 0) AS allocated_budget_amount_dollars
FROM budget.v_cdc_budget_grounded_scope_universe_included_v1
GROUP BY pphf_flag
ORDER BY pphf_flag DESC;

\echo '8. Included rows by transfer_flag'
SELECT
    transfer_flag,
    COUNT(*) AS row_count,
    COALESCE(SUM(allocated_budget_amount_dollars), 0) AS allocated_budget_amount_dollars
FROM budget.v_cdc_budget_grounded_scope_universe_included_v1
GROUP BY transfer_flag
ORDER BY transfer_flag DESC;

\echo '9. Included rows by analyst_reviewed vs auto_seeded'
SELECT
    analyst_reviewed,
    auto_seeded,
    COUNT(*) AS row_count,
    COALESCE(SUM(allocated_budget_amount_dollars), 0) AS allocated_budget_amount_dollars
FROM budget.v_cdc_budget_grounded_scope_universe_included_v1
GROUP BY analyst_reviewed, auto_seeded
ORDER BY analyst_reviewed DESC, auto_seeded DESC;

\echo '10. Included rows by trusted_auto_seed_flag'
SELECT
    trusted_auto_seed_flag,
    COUNT(*) AS row_count,
    COALESCE(SUM(allocated_budget_amount_dollars), 0) AS allocated_budget_amount_dollars
FROM budget.v_cdc_budget_grounded_scope_universe_included_v1
GROUP BY trusted_auto_seed_flag
ORDER BY trusted_auto_seed_flag DESC;

\echo '11. Excluded rows by double_count_exclusion_reason'
SELECT
    COALESCE(double_count_exclusion_reason, 'not_double_count_excluded') AS double_count_exclusion_reason,
    COUNT(*) AS row_count
FROM budget.v_cdc_budget_grounded_scope_universe_excluded_v1
GROUP BY COALESCE(double_count_exclusion_reason, 'not_double_count_excluded')
ORDER BY row_count DESC, double_count_exclusion_reason;

\echo '12. Excluded rows by inclusion_reason'
SELECT
    inclusion_reason,
    COUNT(*) AS row_count
FROM budget.v_cdc_budget_grounded_scope_universe_excluded_v1
GROUP BY inclusion_reason
ORDER BY row_count DESC, inclusion_reason;

\echo '13. Count of unbalanced anchors excluded'
SELECT
    COUNT(DISTINCT budget_anchor_id) AS unbalanced_anchor_count
FROM budget.v_cdc_budget_grounded_scope_universe_excluded_v1
WHERE double_count_exclusion_reason = 'unbalanced_allocation';

\echo '14. Scan for duplicate included rows by anchor/source combination'
SELECT
    budget_anchor_id,
    system_name,
    source_record_id,
    COUNT(*) AS included_row_count
FROM budget.v_cdc_budget_grounded_scope_universe_included_v1
GROUP BY budget_anchor_id, system_name, source_record_id
HAVING COUNT(*) > 1
ORDER BY included_row_count DESC, budget_anchor_id, system_name, source_record_id;

\echo '15. Confirm invalid categories are not included'
SELECT
    appropriation_category,
    COUNT(*) AS included_row_count
FROM budget.v_cdc_budget_grounded_scope_universe_included_v1
WHERE appropriation_category IN ('NON_ADD', 'REQUEST_ONLY', 'TOTAL_OR_SUBTOTAL', 'UNKNOWN')
GROUP BY appropriation_category
ORDER BY appropriation_category;

\echo '16. Sample included rows'
SELECT
    scope_universe_version,
    resolution_id,
    fiscal_year,
    budget_anchor_id,
    appropriation_category,
    discretionary_mandatory_type,
    system_name,
    source_record_id,
    analyst_reviewed,
    auto_seeded,
    trusted_auto_seed_flag,
    effective_allocation_pct,
    allocated_budget_amount_dollars,
    inclusion_reason
FROM budget.v_cdc_budget_grounded_scope_universe_included_v1
ORDER BY fiscal_year NULLS LAST, budget_anchor_id, system_name, source_record_id
LIMIT 100;

\echo '17. Sample excluded rows'
SELECT
    scope_universe_version,
    resolution_id,
    fiscal_year,
    budget_anchor_id,
    appropriation_category,
    system_name,
    source_record_id,
    analyst_reviewed,
    auto_seeded,
    trusted_auto_seed_flag,
    double_count_exclusion_reason,
    inclusion_reason
FROM budget.v_cdc_budget_grounded_scope_universe_excluded_v1
ORDER BY fiscal_year NULLS LAST, budget_anchor_id, system_name, source_record_id
LIMIT 100;

\echo '18. Suspicious included REGULAR rows with emergency/covid/supplemental spending hints'
SELECT
    fiscal_year,
    budget_anchor_id,
    source_record_id,
    appropriation_category,
    spending_appropriation_type,
    spending_program_name,
    spending_award_title,
    spending_award_description
FROM budget.v_cdc_budget_grounded_scope_universe_included_v1
WHERE appropriation_category = 'REGULAR'
  AND (
        LOWER(COALESCE(spending_appropriation_type, '')) LIKE '%emergency%'
     OR LOWER(COALESCE(spending_appropriation_type, '')) LIKE '%covid%'
     OR LOWER(COALESCE(spending_program_name, '')) LIKE '%emergency%'
     OR LOWER(COALESCE(spending_program_name, '')) LIKE '%covid%'
     OR LOWER(COALESCE(spending_award_title, '')) LIKE '%supplemental%'
     OR LOWER(COALESCE(spending_award_description, '')) LIKE '%supplemental%'
  )
ORDER BY fiscal_year NULLS LAST, budget_anchor_id, source_record_id
LIMIT 100;

\echo '19. Coverage summary by fiscal_year'
SELECT
    fiscal_year,
    COUNT(*) AS included_row_count,
    COUNT(DISTINCT budget_anchor_id) AS included_anchor_count,
    COALESCE(SUM(allocated_budget_amount_dollars), 0) AS allocated_budget_amount_dollars
FROM budget.v_cdc_budget_grounded_scope_universe_included_v1
GROUP BY fiscal_year
ORDER BY fiscal_year NULLS LAST;

\echo '20. Coverage summary by review_mode logic'
WITH included AS (
    SELECT *
    FROM budget.v_cdc_budget_grounded_scope_universe_included_v1
)
SELECT
    'analyst_only'::text AS review_mode,
    COUNT(*) FILTER (WHERE analyst_reviewed = TRUE) AS row_count,
    COALESCE(SUM(allocated_budget_amount_dollars) FILTER (WHERE analyst_reviewed = TRUE), 0) AS allocated_budget_amount_dollars
FROM included
UNION ALL
SELECT
    'trusted_auto'::text AS review_mode,
    COUNT(*) FILTER (WHERE analyst_reviewed = TRUE OR trusted_auto_seed_flag = TRUE) AS row_count,
    COALESCE(SUM(allocated_budget_amount_dollars) FILTER (WHERE analyst_reviewed = TRUE OR trusted_auto_seed_flag = TRUE), 0) AS allocated_budget_amount_dollars
FROM included
UNION ALL
SELECT
    'all_master_universe'::text AS review_mode,
    COUNT(*) AS row_count,
    COALESCE(SUM(allocated_budget_amount_dollars), 0) AS allocated_budget_amount_dollars
FROM included
ORDER BY review_mode;

\echo '21. Likely API slice: default budget_grounded_v1 filters'
SELECT
    fiscal_year,
    COUNT(*) AS row_count,
    COALESCE(SUM(allocated_budget_amount_dollars), 0) AS allocated_budget_amount_dollars
FROM budget.v_cdc_budget_grounded_scope_universe_included_v1
WHERE (analyst_reviewed = TRUE OR trusted_auto_seed_flag = TRUE)
  AND COALESCE(emergency_flag, FALSE) = FALSE
  AND COALESCE(supplemental_flag, FALSE) = FALSE
GROUP BY fiscal_year
ORDER BY fiscal_year NULLS LAST;

\echo '22. Likely API slice: include emergency + supplemental + mandatory'
SELECT
    fiscal_year,
    COUNT(*) AS row_count,
    COALESCE(SUM(allocated_budget_amount_dollars), 0) AS allocated_budget_amount_dollars
FROM budget.v_cdc_budget_grounded_scope_universe_included_v1
WHERE analyst_reviewed = TRUE OR trusted_auto_seed_flag = TRUE
GROUP BY fiscal_year
ORDER BY fiscal_year NULLS LAST;
