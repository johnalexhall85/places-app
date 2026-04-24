\echo '1. Total current analyst action rows'
SELECT COUNT(*) AS total_current_analyst_action_rows
FROM budget.cdc_budget_spending_bridge_analyst_action_v1
WHERE action_version = 'v1_analyst_bridge_actions'
  AND is_current = TRUE;

\echo '2. Count by analyst_action'
SELECT analyst_action, COUNT(*) AS row_count
FROM budget.cdc_budget_spending_bridge_analyst_action_v1
WHERE action_version = 'v1_analyst_bridge_actions'
  AND is_current = TRUE
GROUP BY analyst_action
ORDER BY analyst_action;

\echo '3. Count by reviewer_name'
SELECT reviewer_name, COUNT(*) AS row_count
FROM budget.cdc_budget_spending_bridge_analyst_action_v1
WHERE action_version = 'v1_analyst_bridge_actions'
  AND is_current = TRUE
GROUP BY reviewer_name
ORDER BY row_count DESC, reviewer_name
LIMIT 100;

\echo '4. Count by appropriation_category and analyst_action'
SELECT appropriation_category, analyst_action, COUNT(*) AS row_count
FROM budget.cdc_budget_spending_bridge_analyst_action_v1
WHERE action_version = 'v1_analyst_bridge_actions'
  AND is_current = TRUE
GROUP BY appropriation_category, analyst_action
ORDER BY appropriation_category, analyst_action;

\echo '5. Count of current analyst-reviewed resolution rows'
SELECT COUNT(*) AS current_analyst_reviewed_resolution_rows
FROM budget.v_cdc_budget_spending_bridge_resolution_current_v1
WHERE analyst_reviewed = TRUE;

\echo '6. Count of anchors touched by analyst actions'
SELECT COUNT(DISTINCT budget_anchor_id) AS anchors_touched_by_analyst_actions
FROM budget.cdc_budget_spending_bridge_analyst_action_v1
WHERE action_version = 'v1_analyst_bridge_actions'
  AND is_current = TRUE;

\echo '7. Count of anchors fully reviewed single winner'
SELECT COUNT(*) AS anchors_fully_reviewed_single_winner
FROM budget.v_cdc_budget_spending_anchor_review_state_v1
WHERE analyst_review_state = 'fully_reviewed_single_winner';

\echo '8. Count of anchors fully reviewed split'
SELECT COUNT(*) AS anchors_fully_reviewed_split
FROM budget.v_cdc_budget_spending_anchor_review_state_v1
WHERE analyst_review_state = 'fully_reviewed_split';

\echo '9. Count of anchors partially reviewed'
SELECT COUNT(*) AS anchors_partially_reviewed
FROM budget.v_cdc_budget_spending_anchor_review_state_v1
WHERE analyst_review_state = 'partially_reviewed';

\echo '10. Count of anchors with only auto-seeded rows'
SELECT COUNT(*) AS anchors_with_only_auto_seeded_rows
FROM budget.v_cdc_budget_spending_anchor_review_state_v1
WHERE has_auto_seed_only = TRUE;

\echo '11. Allocation sum by anchor for analyst-reviewed accepted rows'
SELECT
    budget_anchor_id,
    fiscal_year,
    appropriation_category,
    budget_program,
    budget_sub_program,
    current_accepted_count,
    current_accepted_partial_count,
    accepted_allocation_sum,
    allocation_balance_status,
    analyst_review_state
FROM budget.v_cdc_budget_spending_anchor_review_state_v1
WHERE has_analyst_review = TRUE
  AND accepted_allocation_sum > 0
ORDER BY accepted_allocation_sum DESC, budget_anchor_id
LIMIT 200;

\echo '12. Anchors under-allocated'
SELECT *
FROM budget.v_cdc_budget_spending_review_queue_under_allocated_v1
ORDER BY is_regular_appropriation DESC, highest_current_confidence DESC, budget_anchor_id
LIMIT 100;

\echo '13. Anchors over-allocated'
SELECT *
FROM budget.v_cdc_budget_spending_review_queue_over_allocated_v1
ORDER BY is_regular_appropriation DESC, highest_current_confidence DESC, budget_anchor_id
LIMIT 100;

\echo '14. Duplicate check on current analyst action uniqueness'
SELECT
    action_version,
    bridge_id,
    COUNT(*) AS duplicate_count
FROM budget.cdc_budget_spending_bridge_analyst_action_v1
WHERE action_version = 'v1_analyst_bridge_actions'
  AND is_current = TRUE
GROUP BY action_version, bridge_id
HAVING COUNT(*) > 1;

\echo '15. Duplicate check on current resolution uniqueness after analyst apply'
SELECT
    resolution_version,
    bridge_id,
    COUNT(*) AS duplicate_count
FROM budget.cdc_budget_spending_bridge_resolution_v1
WHERE resolution_version = 'v1_bridge_resolution'
  AND is_current = TRUE
GROUP BY resolution_version, bridge_id
HAVING COUNT(*) > 1;

\echo '16. Sample accepted_full analyst rows'
SELECT
    a.budget_anchor_id,
    a.bridge_id,
    a.reviewer_name,
    a.reviewed_at,
    a.appropriation_category,
    a.budget_program,
    a.budget_sub_program,
    a.system_name,
    a.source_record_id,
    a.action_reason_code,
    a.action_explanation,
    r.resolution_status,
    r.allocation_pct
FROM budget.cdc_budget_spending_bridge_analyst_action_v1 AS a
JOIN budget.v_cdc_budget_spending_bridge_resolution_current_v1 AS r
  ON r.bridge_id = a.bridge_id
WHERE a.action_version = 'v1_analyst_bridge_actions'
  AND a.is_current = TRUE
  AND a.analyst_action = 'accept_full'
ORDER BY a.reviewed_at DESC, a.bridge_id
LIMIT 50;

\echo '17. Sample accepted_partial split rows'
SELECT
    a.budget_anchor_id,
    a.bridge_id,
    a.reviewer_name,
    a.reviewed_at,
    a.appropriation_category,
    a.budget_program,
    a.system_name,
    a.source_record_id,
    a.action_reason_code,
    a.action_explanation,
    r.resolution_status,
    r.allocation_pct
FROM budget.cdc_budget_spending_bridge_analyst_action_v1 AS a
JOIN budget.v_cdc_budget_spending_bridge_resolution_current_v1 AS r
  ON r.bridge_id = a.bridge_id
WHERE a.action_version = 'v1_analyst_bridge_actions'
  AND a.is_current = TRUE
  AND a.analyst_action = 'accept_partial'
ORDER BY a.reviewed_at DESC, a.budget_anchor_id, a.bridge_id
LIMIT 50;

\echo '18. Sample rejected rows'
SELECT
    a.budget_anchor_id,
    a.bridge_id,
    a.reviewer_name,
    a.appropriation_category,
    a.budget_program,
    a.system_name,
    a.source_record_id,
    a.action_reason_code,
    a.action_explanation,
    r.resolution_status
FROM budget.cdc_budget_spending_bridge_analyst_action_v1 AS a
JOIN budget.v_cdc_budget_spending_bridge_resolution_current_v1 AS r
  ON r.bridge_id = a.bridge_id
WHERE a.action_version = 'v1_analyst_bridge_actions'
  AND a.is_current = TRUE
  AND a.analyst_action = 'reject'
ORDER BY a.reviewed_at DESC, a.bridge_id
LIMIT 50;

\echo '19. Sample needs_followup rows'
SELECT
    a.budget_anchor_id,
    a.bridge_id,
    a.reviewer_name,
    a.appropriation_category,
    a.budget_program,
    a.system_name,
    a.source_record_id,
    a.action_reason_code,
    a.action_explanation,
    r.resolution_status
FROM budget.cdc_budget_spending_bridge_analyst_action_v1 AS a
JOIN budget.v_cdc_budget_spending_bridge_resolution_current_v1 AS r
  ON r.bridge_id = a.bridge_id
WHERE a.action_version = 'v1_analyst_bridge_actions'
  AND a.is_current = TRUE
  AND a.analyst_action = 'mark_needs_followup'
ORDER BY a.reviewed_at DESC, a.bridge_id
LIMIT 50;

\echo '20. Analyst-reviewed REGULAR rows linked to emergency/covid/supplemental spending signals'
SELECT
    r.budget_anchor_id,
    r.bridge_id,
    r.system_name,
    r.fiscal_year,
    r.budget_program,
    r.budget_sub_program,
    r.source_record_id,
    r.match_confidence,
    r.spending_program_name,
    r.spending_award_title,
    r.spending_award_description,
    r.spending_assistance_listing_title,
    r.spending_appropriation_type
FROM budget.v_cdc_budget_spending_bridge_resolution_current_v1 AS r
WHERE r.analyst_reviewed = TRUE
  AND r.appropriation_category = 'REGULAR'
  AND LOWER(
        COALESCE(r.spending_program_name, '') || ' ' ||
        COALESCE(r.spending_award_title, '') || ' ' ||
        COALESCE(r.spending_award_description, '') || ' ' ||
        COALESCE(r.spending_assistance_listing_title, '') || ' ' ||
        COALESCE(r.spending_appropriation_type, '')
      ) SIMILAR TO '%(covid|pandemic|supplemental|emergency|american rescue|cares|arp)%'
ORDER BY r.match_confidence DESC, r.budget_anchor_id, r.system_name
LIMIT 100;

\echo '21. Coverage summary for REGULAR anchors'
SELECT
    COUNT(*) AS total_regular_anchors,
    COUNT(*) FILTER (WHERE analyst_review_state = 'unreviewed') AS unreviewed_regular_anchors,
    COUNT(*) FILTER (WHERE analyst_review_state = 'fully_reviewed_single_winner') AS fully_reviewed_single_winner_regular,
    COUNT(*) FILTER (WHERE analyst_review_state = 'fully_reviewed_split') AS fully_reviewed_split_regular,
    COUNT(*) FILTER (WHERE analyst_review_state = 'partially_reviewed') AS partially_reviewed_regular,
    COUNT(*) FILTER (WHERE analyst_review_state = 'needs_followup') AS needs_followup_regular,
    COUNT(*) FILTER (WHERE analyst_review_state = 'conflicting') AS conflicting_regular
FROM budget.v_cdc_budget_spending_anchor_review_state_v1
WHERE appropriation_category = 'REGULAR';

\echo '22. Coverage summary for PPHF anchors'
SELECT
    COUNT(*) AS total_pphf_anchors,
    COUNT(*) FILTER (WHERE analyst_review_state = 'unreviewed') AS unreviewed_pphf_anchors,
    COUNT(*) FILTER (WHERE analyst_review_state = 'fully_reviewed_single_winner') AS fully_reviewed_single_winner_pphf,
    COUNT(*) FILTER (WHERE analyst_review_state = 'fully_reviewed_split') AS fully_reviewed_split_pphf,
    COUNT(*) FILTER (WHERE analyst_review_state = 'partially_reviewed') AS partially_reviewed_pphf,
    COUNT(*) FILTER (WHERE analyst_review_state = 'needs_followup') AS needs_followup_pphf,
    COUNT(*) FILTER (WHERE analyst_review_state = 'conflicting') AS conflicting_pphf
FROM budget.v_cdc_budget_spending_anchor_review_state_v1
WHERE appropriation_category = 'PPHF';

\echo '23. Count of anchors where analyst decisions superseded auto-seeded rows'
SELECT COUNT(DISTINCT analyst_rows.budget_anchor_id) AS anchors_where_analyst_superseded_auto_rows
FROM budget.cdc_budget_spending_bridge_resolution_v1 AS analyst_rows
JOIN budget.cdc_budget_spending_bridge_resolution_v1 AS prior_rows
  ON prior_rows.id = analyst_rows.supersedes_resolution_id
WHERE analyst_rows.analyst_reviewed = TRUE
  AND prior_rows.auto_seeded = TRUE;

\echo '24. Idempotency helper: current analyst rows with more than one historical version'
SELECT
    bridge_id,
    COUNT(*) AS historical_version_count,
    COUNT(*) FILTER (WHERE is_current = TRUE) AS current_version_count
FROM budget.cdc_budget_spending_bridge_analyst_action_v1
WHERE action_version = 'v1_analyst_bridge_actions'
GROUP BY bridge_id
HAVING COUNT(*) > 1
ORDER BY historical_version_count DESC, bridge_id
LIMIT 100;
