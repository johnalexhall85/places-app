\echo '1. Total bridge rows'
SELECT COUNT(*) AS total_bridge_rows
FROM budget.v_cdc_budget_spending_bridge_v1;

\echo '2. Count by system_name'
SELECT system_name, COUNT(*) AS row_count
FROM budget.v_cdc_budget_spending_bridge_v1
GROUP BY system_name
ORDER BY system_name;

\echo '3. Count by match_tier and system_name'
SELECT system_name, match_tier, COUNT(*) AS row_count
FROM budget.v_cdc_budget_spending_bridge_v1
GROUP BY system_name, match_tier
ORDER BY system_name, match_tier;

\echo '4. Count by confidence_band and system_name'
SELECT system_name, confidence_band, COUNT(*) AS row_count
FROM budget.v_cdc_budget_spending_bridge_v1
GROUP BY system_name, confidence_band
ORDER BY system_name, confidence_band;

\echo '5. Count by appropriation_category and system_name'
SELECT system_name, appropriation_category, COUNT(*) AS row_count
FROM budget.v_cdc_budget_spending_bridge_v1
GROUP BY system_name, appropriation_category
ORDER BY system_name, appropriation_category;

\echo '6. Count of distinct budget_anchor_id matched by system_name'
SELECT system_name, COUNT(DISTINCT budget_anchor_id) AS distinct_anchor_count
FROM budget.v_cdc_budget_spending_bridge_v1
GROUP BY system_name
ORDER BY system_name;

\echo '7. Count of anchors with no candidates'
WITH systems AS (
    SELECT 'usaspending'::text AS system_name
    UNION ALL
    SELECT 'taggs'::text AS system_name
)
SELECT
    s.system_name,
    COUNT(*) AS anchors_with_no_candidates
FROM budget.v_cdc_budget_anchor_v1 AS a
CROSS JOIN systems AS s
LEFT JOIN budget.v_cdc_budget_spending_bridge_v1 AS b
  ON b.budget_anchor_id = a.budget_anchor_id
 AND b.system_name = s.system_name
WHERE b.id IS NULL
GROUP BY s.system_name
ORDER BY s.system_name;

\echo '8. Average candidates per anchor by system_name'
SELECT
    system_name,
    AVG(candidate_count)::numeric(12, 4) AS avg_candidates_per_anchor
FROM (
    SELECT
        system_name,
        budget_anchor_id,
        COUNT(*) AS candidate_count
    FROM budget.v_cdc_budget_spending_bridge_v1
    GROUP BY system_name, budget_anchor_id
) AS counts
GROUP BY system_name
ORDER BY system_name;

\echo '9. Count of HIGH-confidence candidates by appropriation_category'
SELECT
    system_name,
    appropriation_category,
    COUNT(*) AS high_confidence_count
FROM budget.v_cdc_budget_spending_bridge_v1
WHERE confidence_band = 'HIGH'
GROUP BY system_name, appropriation_category
ORDER BY system_name, appropriation_category;

\echo '10. Count of anchors with more than 5 candidates'
SELECT
    system_name,
    COUNT(*) AS anchor_count_over_five
FROM (
    SELECT
        system_name,
        budget_anchor_id,
        COUNT(*) AS candidate_count
    FROM budget.v_cdc_budget_spending_bridge_v1
    GROUP BY system_name, budget_anchor_id
    HAVING COUNT(*) > 5
) AS crowded
GROUP BY system_name
ORDER BY system_name;

\echo '11. Top 100 ambiguous anchors by candidate count'
SELECT
    system_name,
    budget_anchor_id,
    fiscal_year,
    appropriation_category,
    budget_program,
    budget_sub_program,
    COUNT(*) AS candidate_count
FROM budget.v_cdc_budget_spending_bridge_v1
GROUP BY
    system_name,
    budget_anchor_id,
    fiscal_year,
    appropriation_category,
    budget_program,
    budget_sub_program
ORDER BY candidate_count DESC, system_name, budget_anchor_id
LIMIT 100;

\echo '12. Sample deterministic USAspending matches'
SELECT
    budget_anchor_id,
    fiscal_year,
    appropriation_category,
    budget_program,
    budget_sub_program,
    source_record_id,
    source_parent_record_id,
    match_rule_code,
    match_type,
    match_confidence,
    spending_assistance_listing_title,
    spending_aln,
    spending_federal_account_symbols
FROM budget.v_cdc_budget_spending_bridge_v1
WHERE system_name = 'usaspending'
  AND match_tier = 'TIER_A_DETERMINISTIC'
ORDER BY match_confidence DESC, budget_anchor_id, source_record_id
LIMIT 50;

\echo '13. Sample deterministic TAGGS matches'
SELECT
    budget_anchor_id,
    fiscal_year,
    appropriation_category,
    budget_program,
    budget_sub_program,
    source_record_id,
    source_parent_record_id,
    match_rule_code,
    match_type,
    match_confidence,
    spending_program_name,
    spending_program_office,
    spending_aln,
    spending_can_code
FROM budget.v_cdc_budget_spending_bridge_v1
WHERE system_name = 'taggs'
  AND match_tier = 'TIER_A_DETERMINISTIC'
ORDER BY match_confidence DESC, budget_anchor_id, source_record_id
LIMIT 50;

\echo '14. Sample fuzzy candidates'
SELECT
    system_name,
    budget_anchor_id,
    fiscal_year,
    appropriation_category,
    budget_program,
    budget_sub_program,
    source_record_id,
    match_rule_code,
    match_type,
    match_score,
    match_confidence,
    spending_program_name,
    spending_award_title
FROM budget.v_cdc_budget_spending_bridge_v1
WHERE match_tier = 'TIER_C_FUZZY_CANDIDATE'
ORDER BY match_confidence DESC, system_name, budget_anchor_id
LIMIT 50;

\echo '15. Duplicate check on unique bridge key'
SELECT
    bridge_version,
    budget_anchor_id,
    system_name,
    source_record_id,
    match_type,
    COUNT(*) AS duplicate_count
FROM budget.cdc_budget_spending_bridge_v1
WHERE bridge_version = 'v1_budget_spending_bridge'
GROUP BY bridge_version, budget_anchor_id, system_name, source_record_id, match_type
HAVING COUNT(*) > 1;

\echo '16. Count of auto-accepted rows'
SELECT system_name, COUNT(*) AS auto_accepted_count
FROM budget.v_cdc_budget_spending_bridge_v1
WHERE is_auto_accepted = TRUE
GROUP BY system_name
ORDER BY system_name;

\echo '17. Count of rows by review_status'
SELECT system_name, review_status, COUNT(*) AS row_count
FROM budget.v_cdc_budget_spending_bridge_v1
GROUP BY system_name, review_status
ORDER BY system_name, review_status;

\echo '18. Candidate matches for REGULAR anchors only'
SELECT
    system_name,
    match_tier,
    confidence_band,
    COUNT(*) AS row_count
FROM budget.v_cdc_budget_spending_bridge_v1
WHERE appropriation_category = 'REGULAR'
GROUP BY system_name, match_tier, confidence_band
ORDER BY system_name, match_tier, confidence_band;

\echo '19. Candidate matches for PPHF anchors only'
SELECT
    system_name,
    match_tier,
    confidence_band,
    COUNT(*) AS row_count
FROM budget.v_cdc_budget_spending_bridge_v1
WHERE appropriation_category = 'PPHF'
GROUP BY system_name, match_tier, confidence_band
ORDER BY system_name, match_tier, confidence_band;

\echo '20. Suspicious candidates: REGULAR anchors with emergency/covid/supplemental spending text'
SELECT
    system_name,
    budget_anchor_id,
    fiscal_year,
    budget_program,
    budget_sub_program,
    source_record_id,
    match_rule_code,
    match_confidence,
    spending_program_name,
    spending_award_title,
    spending_award_description
FROM budget.v_cdc_budget_spending_bridge_v1
WHERE appropriation_category = 'REGULAR'
  AND LOWER(
        COALESCE(spending_program_name, '') || ' ' ||
        COALESCE(spending_award_title, '') || ' ' ||
        COALESCE(spending_award_description, '') || ' ' ||
        COALESCE(spending_assistance_listing_title, '') || ' ' ||
        COALESCE(spending_appropriation_type, '')
      ) SIMILAR TO '%(covid|pandemic|supplemental|emergency|american rescue|cares|arp)%'
ORDER BY match_confidence DESC, system_name, budget_anchor_id
LIMIT 100;

\echo '21. Spending records linked to many budget anchors'
SELECT
    system_name,
    source_record_id,
    COUNT(DISTINCT budget_anchor_id) AS anchor_count,
    COUNT(DISTINCT budget_program_key) AS distinct_budget_program_keys,
    ARRAY_AGG(DISTINCT budget_program_key ORDER BY budget_program_key) AS budget_program_keys
FROM budget.v_cdc_budget_spending_bridge_v1
GROUP BY system_name, source_record_id
HAVING COUNT(DISTINCT budget_anchor_id) >= 5
ORDER BY anchor_count DESC, system_name, source_record_id
LIMIT 100;

\echo '22. Coverage summary by fiscal_year'
WITH anchors AS (
    SELECT fiscal_year, COUNT(*) AS total_anchors
    FROM budget.v_cdc_budget_anchor_v1
    GROUP BY fiscal_year
),
matched AS (
    SELECT fiscal_year, COUNT(DISTINCT budget_anchor_id) AS matched_anchors
    FROM budget.v_cdc_budget_spending_bridge_v1
    GROUP BY fiscal_year
)
SELECT
    a.fiscal_year,
    a.total_anchors,
    COALESCE(m.matched_anchors, 0) AS matched_anchors,
    a.total_anchors - COALESCE(m.matched_anchors, 0) AS unmatched_anchors
FROM anchors AS a
LEFT JOIN matched AS m
  ON m.fiscal_year = a.fiscal_year
ORDER BY a.fiscal_year;

\echo '23. Coverage summary with HIGH vs only MEDIUM/LOW vs none'
WITH anchor_system AS (
    SELECT a.budget_anchor_id, a.fiscal_year, s.system_name
    FROM budget.v_cdc_budget_anchor_v1 AS a
    CROSS JOIN (SELECT 'usaspending'::text AS system_name UNION ALL SELECT 'taggs'::text) AS s
),
bridge_flags AS (
    SELECT
        budget_anchor_id,
        system_name,
        BOOL_OR(confidence_band = 'HIGH' AND is_excluded = FALSE) AS has_high,
        BOOL_OR(confidence_band IN ('MEDIUM', 'LOW') AND is_excluded = FALSE) AS has_medium_or_low
    FROM budget.v_cdc_budget_spending_bridge_v1
    GROUP BY budget_anchor_id, system_name
)
SELECT
    anchor_system.system_name,
    COUNT(*) AS total_anchors,
    COUNT(*) FILTER (WHERE bridge_flags.has_high) AS anchors_with_high_candidate,
    COUNT(*) FILTER (WHERE NOT COALESCE(bridge_flags.has_high, FALSE) AND COALESCE(bridge_flags.has_medium_or_low, FALSE)) AS anchors_with_only_medium_or_low,
    COUNT(*) FILTER (WHERE bridge_flags.budget_anchor_id IS NULL) AS anchors_with_no_candidates
FROM anchor_system
LEFT JOIN bridge_flags
  ON bridge_flags.budget_anchor_id = anchor_system.budget_anchor_id
 AND bridge_flags.system_name = anchor_system.system_name
GROUP BY anchor_system.system_name
ORDER BY anchor_system.system_name;
