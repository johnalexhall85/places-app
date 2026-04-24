\echo '1. Total current resolved rows in the scope master universe relation'
SELECT COUNT(*) AS total_scope_master_rows
FROM budget.v_cdc_budget_scope_master_universe_v1;

\echo '2. Included vs excluded rows'
SELECT
    include_in_master_universe,
    COUNT(*) AS row_count
FROM budget.v_cdc_budget_scope_master_universe_v1
GROUP BY include_in_master_universe
ORDER BY include_in_master_universe DESC;

\echo '3. Count by appropriation_category and include flag'
SELECT
    appropriation_category,
    include_in_master_universe,
    COUNT(*) AS row_count
FROM budget.v_cdc_budget_scope_master_universe_v1
GROUP BY appropriation_category, include_in_master_universe
ORDER BY appropriation_category, include_in_master_universe DESC;

\echo '4. Double-count exclusion reasons'
SELECT
    COALESCE(double_count_exclusion_reason, 'included_or_not_double_count_excluded') AS exclusion_reason,
    COUNT(*) AS row_count
FROM budget.v_cdc_budget_scope_master_universe_v1
GROUP BY COALESCE(double_count_exclusion_reason, 'included_or_not_double_count_excluded')
ORDER BY row_count DESC, exclusion_reason;

\echo '5. Included allocated dollars by fiscal_year and appropriation_category'
SELECT
    fiscal_year,
    appropriation_category,
    SUM(total_allocated_amount_dollars) AS allocated_dollars
FROM budget.v_cdc_budget_scope_master_summary_v1
GROUP BY fiscal_year, appropriation_category
ORDER BY fiscal_year NULLS LAST, appropriation_category;

\echo '6. Included allocated dollars by UI flags and analyst provenance'
SELECT
    fiscal_year,
    discretionary_mandatory_type,
    emergency_flag,
    supplemental_flag,
    pphf_flag,
    transfer_flag,
    analyst_reviewed,
    auto_seeded,
    SUM(total_allocated_amount_dollars) AS allocated_dollars
FROM budget.v_cdc_budget_scope_master_summary_v1
GROUP BY
    fiscal_year,
    discretionary_mandatory_type,
    emergency_flag,
    supplemental_flag,
    pphf_flag,
    transfer_flag,
    analyst_reviewed,
    auto_seeded
ORDER BY fiscal_year NULLS LAST, discretionary_mandatory_type, analyst_reviewed DESC, auto_seeded DESC;

\echo '7. Anchors excluded because of double-count risk'
SELECT
    budget_anchor_id,
    fiscal_year,
    appropriation_category,
    budget_program,
    budget_sub_program,
    current_resolved_row_count,
    included_row_count,
    double_count_excluded_row_count,
    included_allocation_sum,
    anchor_accepted_allocation_sum,
    double_count_exclusion_reasons
FROM budget.v_cdc_budget_scope_master_anchor_summary_v1
WHERE double_count_excluded_row_count > 0
ORDER BY fiscal_year NULLS LAST, budget_anchor_id;

\echo '8. Check that included anchors never exceed 100 percent included allocation'
SELECT
    budget_anchor_id,
    included_allocation_sum
FROM budget.v_cdc_budget_scope_master_anchor_summary_v1
WHERE included_allocation_sum > 1.000001
ORDER BY included_allocation_sum DESC, budget_anchor_id;

\echo '9. Sample included accepted_partial rows with allocation applied'
SELECT
    budget_anchor_id,
    fiscal_year,
    appropriation_category,
    system_name,
    source_record_id,
    resolution_status,
    effective_allocation_pct,
    budget_amount_dollars,
    allocated_amount_dollars,
    analyst_reviewed,
    auto_seeded
FROM budget.v_cdc_budget_scope_master_included_v1
WHERE resolution_status = 'accepted_partial'
ORDER BY fiscal_year NULLS LAST, budget_anchor_id, system_name, source_record_id
LIMIT 100;
