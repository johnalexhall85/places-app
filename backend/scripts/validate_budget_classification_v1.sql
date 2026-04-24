-- Budget classification v1 validation queries
-- Run with:
--   psql postgresql://places:places@localhost:5432/places -f backend/scripts/validate_budget_classification_v1.sql

-- 1. Total classified rows
SELECT COUNT(*) AS total_classified_rows
FROM budget.cdc_budget_classification_v1
WHERE classification_version = 'v1_regular_appropriations';

-- 2. Counts by appropriation_category
SELECT
    appropriation_category,
    COUNT(*) AS row_count
FROM budget.cdc_budget_classification_v1
WHERE classification_version = 'v1_regular_appropriations'
GROUP BY 1
ORDER BY row_count DESC, appropriation_category;

-- 3. Counts by appropriation_subtype
SELECT
    appropriation_subtype,
    COUNT(*) AS row_count
FROM budget.cdc_budget_classification_v1
WHERE classification_version = 'v1_regular_appropriations'
GROUP BY 1
ORDER BY row_count DESC, appropriation_subtype;

-- 4. Counts by primary_rule_code
SELECT
    primary_rule_code,
    COUNT(*) AS row_count
FROM budget.cdc_budget_classification_v1
WHERE classification_version = 'v1_regular_appropriations'
GROUP BY 1
ORDER BY row_count DESC, primary_rule_code;

-- 5. Sum(amount_dollars) by fiscal_year and appropriation_category
SELECT
    fiscal_year,
    appropriation_category,
    SUM(amount_dollars)::numeric(20, 2) AS amount_dollars
FROM budget.cdc_budget_classification_v1
WHERE classification_version = 'v1_regular_appropriations'
GROUP BY 1, 2
ORDER BY 1, 2;

-- 6. Sum(amount_dollars) for regular appropriations by fiscal_year
SELECT
    fiscal_year,
    SUM(amount_dollars)::numeric(20, 2) AS regular_amount_dollars
FROM budget.cdc_budget_classification_v1
WHERE classification_version = 'v1_regular_appropriations'
  AND is_regular_appropriation = TRUE
GROUP BY 1
ORDER BY 1;

-- 7. Count and dollar sum for UNKNOWN by fiscal_year
SELECT
    fiscal_year,
    COUNT(*) AS unknown_rows,
    SUM(amount_dollars)::numeric(20, 2) AS unknown_amount_dollars
FROM budget.cdc_budget_classification_v1
WHERE classification_version = 'v1_regular_appropriations'
  AND appropriation_category = 'UNKNOWN'
GROUP BY 1
ORDER BY 1;

-- 8. Count and dollar sum for NON_ADD by fiscal_year
SELECT
    fiscal_year,
    COUNT(*) AS non_add_rows,
    SUM(amount_dollars)::numeric(20, 2) AS non_add_amount_dollars
FROM budget.cdc_budget_classification_v1
WHERE classification_version = 'v1_regular_appropriations'
  AND appropriation_category = 'NON_ADD'
GROUP BY 1
ORDER BY 1;

-- 9. Count and dollar sum for PPHF by fiscal_year
SELECT
    fiscal_year,
    COUNT(*) AS pphf_rows,
    SUM(amount_dollars)::numeric(20, 2) AS pphf_amount_dollars
FROM budget.cdc_budget_classification_v1
WHERE classification_version = 'v1_regular_appropriations'
  AND appropriation_category = 'PPHF'
GROUP BY 1
ORDER BY 1;

-- 10. Count and dollar sum for SUPPLEMENTAL by fiscal_year
SELECT
    fiscal_year,
    COUNT(*) AS supplemental_rows,
    SUM(amount_dollars)::numeric(20, 2) AS supplemental_amount_dollars
FROM budget.cdc_budget_classification_v1
WHERE classification_version = 'v1_regular_appropriations'
  AND appropriation_category = 'SUPPLEMENTAL'
GROUP BY 1
ORDER BY 1;

-- 11. Sample 50 REGULAR rows for CDC
SELECT
    raw_budget_id,
    unique_id,
    fiscal_year,
    agency,
    sub_agency,
    program,
    sub_program,
    sub_program_2,
    sub_program_3,
    budget_source,
    budget_stage,
    granularity,
    amount_millions,
    amount_dollars,
    funding_type,
    appropriation_category,
    appropriation_subtype,
    classification_confidence,
    primary_rule_code,
    rule_explanation,
    source_id,
    source_page
FROM budget.cdc_budget_classification_v1
WHERE classification_version = 'v1_regular_appropriations'
  AND is_regular_appropriation = TRUE
  AND LOWER(COALESCE(sub_agency, '')) = 'cdc'
ORDER BY fiscal_year, raw_budget_id
LIMIT 50;

-- 12. Sample 50 UNKNOWN rows with signal fields shown
SELECT
    raw_budget_id,
    unique_id,
    fiscal_year,
    sub_agency,
    program,
    sub_program,
    budget_source,
    budget_stage,
    funding_type,
    amount_dollars,
    primary_rule_code,
    signal_budget_stage_enacted,
    signal_budget_stage_operating_plan,
    signal_budget_stage_request,
    signal_funding_type_discretionary,
    signal_funding_type_mandatory,
    signal_non_add,
    signal_keyword_pphf,
    signal_keyword_supplemental,
    signal_keyword_emergency,
    signal_keyword_transfer,
    signal_keyword_reprogramming,
    signal_keyword_total,
    signal_keyword_subtotal,
    signal_keyword_base,
    signal_keyword_prevention_fund,
    signal_keyword_covid,
    signal_keyword_arp,
    signal_keyword_cares,
    signal_keyword_rescue_plan,
    signal_keyword_nonrecurring,
    signal_program_has_substructure,
    signal_record_is_leaf_like,
    signal_program_repeats_across_years,
    rule_explanation
FROM budget.cdc_budget_classification_v1
WHERE classification_version = 'v1_regular_appropriations'
  AND appropriation_category = 'UNKNOWN'
ORDER BY fiscal_year, raw_budget_id
LIMIT 50;

-- 13. Duplicate check on raw_budget_id + classification_version
SELECT
    raw_budget_id,
    classification_version,
    COUNT(*) AS dup_count
FROM budget.cdc_budget_classification_v1
GROUP BY 1, 2
HAVING COUNT(*) > 1
ORDER BY dup_count DESC, raw_budget_id;

-- 14. Distribution of confidence values
SELECT
    classification_confidence,
    COUNT(*) AS row_count
FROM budget.cdc_budget_classification_v1
WHERE classification_version = 'v1_regular_appropriations'
GROUP BY 1
ORDER BY 1 DESC;

-- 15. Suspicious REGULAR scan for transfer/supplemental/covid keywords
SELECT
    raw_budget_id,
    unique_id,
    fiscal_year,
    sub_agency,
    program,
    sub_program,
    budget_source,
    budget_stage,
    funding_type,
    amount_dollars,
    primary_rule_code,
    classification_confidence
FROM budget.cdc_budget_classification_v1
WHERE classification_version = 'v1_regular_appropriations'
  AND is_regular_appropriation = TRUE
  AND (
      signal_keyword_transfer
      OR signal_keyword_supplemental
      OR signal_keyword_covid
      OR signal_keyword_arp
      OR signal_keyword_cares
      OR signal_keyword_rescue_plan
  )
ORDER BY fiscal_year, raw_budget_id;
