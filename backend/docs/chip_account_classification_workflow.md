# CHIP Account Classification Workflow

This workflow adds an auditable classification layer on top of the USAspending
federal-account ingestion. It does not replace the current CHIP funding model or
change existing funding map endpoints. It creates a parallel CHIP funding model
v2 scoping layer that can turn the broad HHS federal-account universe into a
reviewed CDC account universe.

## Purpose

The federal account ingestion loads FY2020-FY2026 account balances, PA/object
class rows, award-account breakdowns, and an account reconciliation view. The
new `usaspending_fed_account.chip_account_classification` table stores one
reviewed classification decision per fiscal year, normalized federal account key,
and classification version.

The classification layer answers:

- Which HHS 075 federal accounts are CDC-related?
- Which CDC-related accounts are regular baseline funding?
- Which accounts are emergency, PPHF, transfer, business support, excluded, or
  still unknown-review?
- Which accounts should be included in the public map bridge?

## Control Totals And Geography Bridge

Account balances are the control totals. They are the account-level fiscal year
obligation totals that should anchor any CHIP v2 account universe.

Award rows are the map/geography bridge. They provide recipient/place geography,
assistance listings, contract NAICS/PSC context, and award descriptions. Award
rows help allocate or inspect account funding geographically, but they should not
replace account balances as the top-line control total.

All HHS 075 accounts are not CDC accounts. HHS includes CMS, NIH, HRSA, SAMHSA,
FDA, ACF, IHS, ASPR, departmental accounts, emergency funds, and other accounts
that can appear in the same USAspending federal-account universe.

## Rule-Based Pre-Classifier

The exporter runs a conservative pre-classifier over identity fields, top
program activities, and top object classes:

- CDC positive signals include CDC, Centers for Disease Control and Prevention,
  disease control, preparedness, chronic disease, injury prevention, NIOSH,
  ATSDR, global health, immunization, birth defects, and similar terms.
- Non-CDC HHS exclusion signals include CMS, Medicare, Medicaid, NIH, HRSA,
  SAMHSA, FDA, ACF, IHS, ASPR, Provider Relief Fund, child care, TANF, and
  similar terms.
- Emergency terms such as COVID, Coronavirus, CARES, ARP, emergency,
  supplemental, response activities, and pandemic are classified as emergency
  supplemental when CDC-related.
- PPHF terms are classified as PPHF/CDC transfer funding.
- Transfer terms or allocation transfer agency identities are classified as
  transfer funding.
- Business/admin terms such as Business Services Support, Program Support
  Center, Office of the Secretary, Buildings and Facilities, Rent, and Working
  Capital Fund are classified as business support.
- Unknown rows are intentionally kept visible as `unknown_review` and
  `needs_review`.

Human-reviewed CSV values override the rule-based candidate values when
ingested. The `classification_version` is preserved so a later v2 rule set can
coexist with v1 decisions.

## Classification Fields

- `is_cdc_related`: whether the account-year belongs in the CDC-scoped universe.
- `cdc_scope_category`: one of `cdc_core`, `cdc_transfer`, `cdc_emergency`,
  `cdc_business_support`, `cdc_atdsr`, `cdc_niosh`, `non_cdc_hhs`, or
  `unknown_review`.
- `funding_scope`: one of `regular_appropriation`, `emergency_supplemental`,
  `pphf`, `transfer`, `mandatory`, `business_support`, `reimbursable`, or
  `unknown`.
- `include_in_chip_baseline`: include in regular CHIP baseline totals.
- `include_in_chip_emergency`: include in CHIP emergency totals.
- `include_in_chip_total`: include in the broader CHIP CDC total.
- `include_in_public_map`: include in the public map bridge by default.
- `review_status`: `candidate`, `needs_review`, `reviewed`, or `rejected`.
- `confidence`: rule or reviewer confidence from 0 to 1.
- `classification_reason`: plain-language explanation of the decision.
- `notes`: free-form human review notes.
- `source`: provenance, defaulting to `rule_based_candidate`.
- `classification_version`: version label, defaulting to
  `chip_account_classification_v1`.

## Commands

Run migration:

```bash
cd /home/john/places-app/backend
alembic upgrade head
```

Export candidates:

```bash
python scripts/export_chip_account_classification_candidates.py \
  --years 2020 2021 2022 2023 2024 2025 2026
```

Manually review:

Open:

```text
/home/john/places-app/data/usaspending/fed_account_data/outputs/chip_account_classification_candidates_fy2020_2026_v1.csv
```

Review each row, especially `needs_review`, low confidence, transfer, PPHF,
business support, and any unusually large account-year. Do not delete unknowns
just to make totals cleaner; classify them explicitly or leave them visible as
`unknown_review`.

Ingest reviewed file:

```bash
python scripts/ingest_chip_account_classification.py \
  --input /home/john/places-app/data/usaspending/fed_account_data/outputs/chip_account_classification_candidates_fy2020_2026_v1.csv \
  --classification-version chip_account_classification_v1 \
  --replace-version \
  --allow-candidates
```

Export classified reconciliation:

```bash
python scripts/export_chip_classified_reconciliation.py \
  --years 2020 2021 2022 2023 2024 2025 2026 \
  --classification-version chip_account_classification_v1
```

Optional verification:

```bash
python scripts/verify_chip_account_classification.py \
  --years 2020 2021 2022 2023 2024 2025 2026 \
  --classification-version chip_account_classification_v1
```

Use `--skip-db` on the verification script to run only the classifier smoke
checks.

## Query Views

The migration creates these views in `usaspending_fed_account`:

- `v_chip_account_classified_reconciliation`: account reconciliation joined to
  classification decisions.
- `v_chip_cdc_account_universe`: CDC-related rows that are not rejected.
- `v_chip_cdc_baseline_accounts`: CDC baseline account-years.
- `v_chip_cdc_emergency_accounts`: CDC emergency account-years.
- `v_chip_cdc_public_map_accounts`: CDC account-years included in the public map
  bridge.
- `v_chip_cdc_excluded_accounts`: non-CDC, rejected, or all-flags-false rows.
- `v_chip_cdc_funding_reconciliation_by_year`: fiscal-year rollup by
  classification version.

Example:

```sql
SELECT fiscal_year,
       classification_version,
       baseline_balance_obligations,
       emergency_balance_obligations,
       public_map_award_obligations,
       unknown_review_balance_obligations
FROM usaspending_fed_account.v_chip_cdc_funding_reconciliation_by_year
WHERE classification_version = 'chip_account_classification_v1'
ORDER BY fiscal_year;
```
