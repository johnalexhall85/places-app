\echo '1. Total current resolution rows'
SELECT COUNT(*) AS total_current_resolution_rows
FROM budget.v_cdc_budget_spending_bridge_resolution_current_v1;

\echo '2. Count by resolution_status'
SELECT resolution_status, COUNT(*) AS row_count
FROM budget.v_cdc_budget_spending_bridge_resolution_current_v1
GROUP BY resolution_status
ORDER BY resolution_status;

\echo '3. Count by system_name and resolution_status'
SELECT system_name, resolution_status, COUNT(*) AS row_count
FROM budget.v_cdc_budget_spending_bridge_resolution_current_v1
GROUP BY system_name, resolution_status
ORDER BY system_name, resolution_status;

\echo '4. Count by appropriation_category and resolution_status'
SELECT appropriation_category, resolution_status, COUNT(*) AS row_count
FROM budget.v_cdc_budget_spending_bridge_resolution_current_v1
GROUP BY appropriation_category, resolution_status
ORDER BY appropriation_category, resolution_status;

\echo '5. Count of auto_seeded vs analyst_reviewed'
SELECT auto_seeded, analyst_reviewed, COUNT(*) AS row_count
FROM budget.v_cdc_budget_spending_bridge_resolution_current_v1
GROUP BY auto_seeded, analyst_reviewed
ORDER BY auto_seeded DESC, analyst_reviewed DESC;

\echo '6. Count of current accepted rows'
SELECT COUNT(*) AS accepted_row_count
FROM budget.v_cdc_budget_spending_bridge_resolution_accepted_v1;

\echo '7. Count of current unresolved rows'
SELECT COUNT(*) AS unresolved_row_count
FROM budget.v_cdc_budget_spending_bridge_resolution_unresolved_v1;

\echo '8. Count of anchors with at least one accepted row'
SELECT COUNT(*) AS anchors_with_accepted_rows
FROM budget.v_cdc_budget_spending_anchor_resolution_summary_v1
WHERE accepted_count > 0;

\echo '9. Count of anchors with only unresolved rows'
SELECT COUNT(*) AS anchors_with_only_unresolved_rows
FROM budget.v_cdc_budget_spending_anchor_resolution_summary_v1
WHERE unresolved_count > 0
  AND accepted_count = 0
  AND rejected_count = 0;

\echo '10. Count of anchors with mixed accepted and unresolved rows'
SELECT COUNT(*) AS anchors_with_mixed_accepted_and_unresolved
FROM budget.v_cdc_budget_spending_anchor_resolution_summary_v1
WHERE accepted_count > 0
  AND unresolved_count > 0;

\echo '11. Allocation sum by budget_anchor_id for accepted/current rows'
SELECT
    budget_anchor_id,
    fiscal_year,
    appropriation_category,
    budget_program,
    budget_sub_program,
    accepted_count,
    accepted_allocation_sum
FROM budget.v_cdc_budget_spending_anchor_resolution_summary_v1
WHERE accepted_count > 0
ORDER BY accepted_allocation_sum DESC, budget_anchor_id
LIMIT 200;

\echo '12. Anchors where accepted allocation sum > 1.0'
SELECT
    budget_anchor_id,
    fiscal_year,
    appropriation_category,
    budget_program,
    budget_sub_program,
    accepted_count,
    accepted_allocation_sum
FROM budget.v_cdc_budget_spending_anchor_resolution_summary_v1
WHERE accepted_allocation_sum > 1.000001
ORDER BY accepted_allocation_sum DESC, budget_anchor_id;

\echo '13. Anchors where accepted allocation sum < 1.0 but have accepted rows'
SELECT
    budget_anchor_id,
    fiscal_year,
    appropriation_category,
    budget_program,
    budget_sub_program,
    accepted_count,
    unresolved_count,
    accepted_allocation_sum,
    review_state
FROM budget.v_cdc_budget_spending_anchor_resolution_summary_v1
WHERE accepted_count > 0
  AND accepted_allocation_sum < 0.999999
ORDER BY accepted_allocation_sum, budget_anchor_id;

\echo '14. Anchors with no current resolution rows'
WITH candidate_anchors AS (
    SELECT DISTINCT budget_anchor_id
    FROM budget.v_cdc_budget_spending_bridge_v1
)
SELECT COUNT(*) AS anchors_with_no_current_resolution_rows
FROM candidate_anchors AS c
LEFT JOIN budget.v_cdc_budget_spending_anchor_resolution_summary_v1 AS s
  ON s.budget_anchor_id = c.budget_anchor_id
WHERE s.budget_anchor_id IS NULL;

\echo '15. Sample accepted auto-seeded rows'
SELECT
    budget_anchor_id,
    bridge_id,
    system_name,
    fiscal_year,
    appropriation_category,
    budget_program,
    budget_sub_program,
    source_record_id,
    match_rule_code,
    resolution_rule_code,
    resolution_status,
    allocation_pct,
    resolution_reason_code,
    resolution_explanation
FROM budget.v_cdc_budget_spending_bridge_resolution_current_v1
WHERE resolution_status IN ('accepted', 'accepted_partial')
  AND auto_seeded = TRUE
ORDER BY resolution_confidence DESC NULLS LAST, budget_anchor_id, system_name
LIMIT 50;

\echo '16. Sample unresolved review-queue rows'
SELECT
    budget_anchor_id,
    fiscal_year,
    appropriation_category,
    budget_program,
    budget_sub_program,
    total_candidate_count,
    unresolved_candidate_count,
    highest_match_confidence,
    highest_unresolved_match_confidence,
    spans_both_systems,
    conflicting_candidates_across_systems,
    has_any_high_confidence_candidate,
    has_high_confidence_unresolved,
    review_state,
    review_queue_priority
FROM budget.v_cdc_budget_spending_bridge_resolution_review_queue_v1
ORDER BY
    review_queue_priority,
    high_confidence_unresolved_count DESC,
    unresolved_candidate_count DESC,
    highest_unresolved_match_confidence DESC NULLS LAST,
    budget_anchor_id
LIMIT 50;

\echo '17. Duplicate check on current resolution unique constraint'
SELECT
    resolution_version,
    bridge_id,
    COUNT(*) AS duplicate_count
FROM budget.cdc_budget_spending_bridge_resolution_v1
WHERE resolution_version = 'v1_bridge_resolution'
  AND is_current = TRUE
GROUP BY resolution_version, bridge_id
HAVING COUNT(*) > 1;

\echo '18. Count of analyst-reviewed rows that would have been overwritten if not protected'
SELECT COUNT(*) AS protected_current_analyst_rows
FROM budget.v_cdc_budget_spending_bridge_resolution_current_v1
WHERE analyst_reviewed = TRUE;

\echo '19. Coverage summary for REGULAR anchors only'
SELECT
    COUNT(*) AS total_regular_anchors,
    COUNT(*) FILTER (WHERE review_state = 'fully_resolved') AS fully_resolved_regular_anchors,
    COUNT(*) FILTER (WHERE review_state = 'partially_resolved') AS partially_resolved_regular_anchors,
    COUNT(*) FILTER (WHERE review_state = 'unresolved') AS unresolved_regular_anchors,
    COUNT(*) FILTER (WHERE review_state = 'over_allocated') AS over_allocated_regular_anchors,
    COUNT(*) FILTER (WHERE review_state = 'under_allocated') AS under_allocated_regular_anchors
FROM budget.v_cdc_budget_spending_anchor_resolution_summary_v1
WHERE appropriation_category = 'REGULAR';

\echo '20. Coverage summary for PPHF anchors only'
SELECT
    COUNT(*) AS total_pphf_anchors,
    COUNT(*) FILTER (WHERE review_state = 'fully_resolved') AS fully_resolved_pphf_anchors,
    COUNT(*) FILTER (WHERE review_state = 'partially_resolved') AS partially_resolved_pphf_anchors,
    COUNT(*) FILTER (WHERE review_state = 'unresolved') AS unresolved_pphf_anchors,
    COUNT(*) FILTER (WHERE review_state = 'over_allocated') AS over_allocated_pphf_anchors,
    COUNT(*) FILTER (WHERE review_state = 'under_allocated') AS under_allocated_pphf_anchors
FROM budget.v_cdc_budget_spending_anchor_resolution_summary_v1
WHERE appropriation_category = 'PPHF';

\echo '21. Candidate-to-resolution conversion summary'
WITH bridge_counts AS (
    SELECT
        system_name,
        COUNT(*) AS candidate_row_count,
        COUNT(DISTINCT budget_anchor_id) AS candidate_anchor_count
    FROM budget.v_cdc_budget_spending_bridge_v1
    GROUP BY system_name
),
resolution_counts AS (
    SELECT
        system_name,
        COUNT(*) AS current_resolution_row_count,
        COUNT(DISTINCT budget_anchor_id) AS resolved_anchor_count,
        COUNT(*) FILTER (WHERE resolution_status IN ('accepted', 'accepted_partial')) AS accepted_row_count,
        COUNT(*) FILTER (WHERE resolution_status = 'unresolved') AS unresolved_row_count,
        COUNT(*) FILTER (WHERE resolution_status = 'rejected') AS rejected_row_count
    FROM budget.v_cdc_budget_spending_bridge_resolution_current_v1
    GROUP BY system_name
)
SELECT
    b.system_name,
    b.candidate_row_count,
    b.candidate_anchor_count,
    COALESCE(r.current_resolution_row_count, 0) AS current_resolution_row_count,
    COALESCE(r.resolved_anchor_count, 0) AS resolved_anchor_count,
    COALESCE(r.accepted_row_count, 0) AS accepted_row_count,
    COALESCE(r.unresolved_row_count, 0) AS unresolved_row_count,
    COALESCE(r.rejected_row_count, 0) AS rejected_row_count
FROM bridge_counts AS b
LEFT JOIN resolution_counts AS r
  ON r.system_name = b.system_name
ORDER BY b.system_name;

\echo '22. High-confidence unresolved rows that deserve quick analyst review'
SELECT
    budget_anchor_id,
    bridge_id,
    system_name,
    fiscal_year,
    appropriation_category,
    budget_program,
    budget_sub_program,
    source_record_id,
    match_rule_code,
    match_type,
    match_confidence,
    confidence_band,
    spending_program_name,
    spending_award_title,
    resolution_reason_code,
    resolution_explanation
FROM budget.v_cdc_budget_spending_bridge_resolution_current_v1
WHERE resolution_status = 'unresolved'
  AND confidence_band = 'HIGH'
ORDER BY match_confidence DESC, budget_anchor_id, system_name
LIMIT 100;

\echo '23. Scan for accepted REGULAR rows linked to emergency/covid/supplemental spending text'
SELECT
    budget_anchor_id,
    bridge_id,
    system_name,
    fiscal_year,
    budget_program,
    budget_sub_program,
    source_record_id,
    match_confidence,
    spending_program_name,
    spending_award_title,
    spending_award_description,
    spending_assistance_listing_title,
    spending_appropriation_type
FROM budget.v_cdc_budget_spending_bridge_resolution_accepted_v1
WHERE appropriation_category = 'REGULAR'
  AND LOWER(
        COALESCE(spending_program_name, '') || ' ' ||
        COALESCE(spending_award_title, '') || ' ' ||
        COALESCE(spending_award_description, '') || ' ' ||
        COALESCE(spending_assistance_listing_title, '') || ' ' ||
        COALESCE(spending_appropriation_type, '')
      ) SIMILAR TO '%(covid|pandemic|supplemental|emergency|american rescue|cares|arp)%'
ORDER BY match_confidence DESC, budget_anchor_id, system_name
LIMIT 100;

\echo '24. Summary by total anchors and review_state'
SELECT
    COUNT(*) AS total_anchors,
    COUNT(*) FILTER (WHERE review_state = 'fully_resolved') AS fully_resolved_anchors,
    COUNT(*) FILTER (WHERE review_state = 'partially_resolved') AS partially_resolved_anchors,
    COUNT(*) FILTER (WHERE review_state = 'unresolved') AS unresolved_anchors,
    COUNT(*) FILTER (WHERE review_state = 'over_allocated') AS over_allocated_anchors,
    COUNT(*) FILTER (WHERE review_state = 'under_allocated') AS under_allocated_anchors
FROM budget.v_cdc_budget_spending_anchor_resolution_summary_v1;
