# Backend Script Notes

## Schema Mapping Env Vars

Defaults:
- `PLACES_SCHEMA=public`
- `ACS_SCHEMA=public`
- `SVI_SCHEMA=public`
- `HRSA_SCHEMA=public`
- `CMS_SCHEMA=cms`
- `USDA_FOOD_ACCESS_SCHEMA=usda_food_access`
- `USDA_FOOD_ENV_SCHEMA=usda_food_env`
- `FEMA_NRI_SCHEMA=fema_nri`
- `CDC_FUNDING_SCHEMA=cdc_funding`
- `USASPENDING_SCHEMA=usaspending`
- `TAGGS_SCHEMA=taggs`
- `CDC_PROFILES_SCHEMA=cdc_profiles`
- `RECON_SCHEMA=recon`
- `ANALYTICS_SCHEMA=analytics`

Verify resolved mapping and table access:

```bash
python backend/scripts/verify_schema_mapping.py
```

## CMS Ingestion (Schema `cms`)

CMS tables are isolated in schema `cms` (controlled by `CMS_SCHEMA`, default `cms`).

Ingest Geographic Variation PUF:

```bash
python backend/scripts/ingest_cms_gv.py \
  --path "./data/2014-2023 Medicare Fee-for-Service Geographic Variation Public Use File.csv"
```

Ingest SSP County FFS PUF:

```bash
python backend/scripts/ingest_cms_ssp.py \
  --path "./data/County_Level_FFS_Data_for_Shared_Savings_Program_Benchmark_PUF_2024_01_01_Offset_Assignables_2025 Starters.csv"
```

Verify CMS tables exist:

```bash
python backend/scripts/verify_cms_tables.py
```

Equivalent module entrypoints:

```bash
cd backend
python -m app.cms.ingest.gv_ingest --path "../data/2014-2023 Medicare Fee-for-Service Geographic Variation Public Use File.csv"
python -m app.cms.ingest.ssp_ingest --path "../data/County_Level_FFS_Data_for_Shared_Savings_Program_Benchmark_PUF_2024_01_01_Offset_Assignables_2025 Starters.csv"

# USDA Food Access Research Atlas ingest (tract-level)
python -m app.usda_food_access.ingest

# USDA Food Environment Atlas ingest (county/state, July 2025)
python -m app.usda_food_env.ingest

# FEMA National Risk Index ingest (county + tract, December 2025)
# (run migrations first: cd backend && ./.venv/bin/alembic upgrade head)
python -m app.fema_nri.ingest --replace
```

## Ingest SVI Multiple Years (2018, 2020, 2022)

`ingest_svi_years.py` loads county and tract SVI CSVs into:
- `svi_measures`
- `svi_estimates_county`
- `svi_estimates_tract`

It supports chunked ingest, canonical year-specific column normalization, and idempotent upserts.

### Examples

Ingest 2018 + 2020 for both county and tract:

```bash
python backend/scripts/ingest_svi_years.py --years 2018 2020 --level both
```

Ingest tract only:

```bash
python backend/scripts/ingest_svi_years.py --years 2018 2020 --level tract
```

Re-run including 2022:

```bash
python backend/scripts/ingest_svi_years.py --years 2018 2020 2022 --level both
```

Use an explicit data directory and DB URL:

```bash
python backend/scripts/ingest_svi_years.py \
  --years 2018 2020 \
  --level county \
  --data-dir /data \
  --db-url "$DATABASE_URL"
```

## Ingest HRSA HPSA (PC/MH/DH) + rebuild county summary

Load designation-level files and rebuild `county_hpsa_summary`:

```bash
python backend/scripts/ingest_hpsa.py \
  --pc /mnt/data/BCD_HPSA_FCT_DET_PC.csv \
  --mh /mnt/data/BCD_HPSA_FCT_DET_MH.csv \
  --dh /mnt/data/BCD_HPSA_FCT_DET_DH.csv \
  --rebuild-summary
```

Optional flags:

```bash
# clear existing raw staging table before loading
python backend/scripts/ingest_hpsa.py ... --truncate-staging

# skip summary rebuild
python backend/scripts/ingest_hpsa.py ... --no-rebuild-summary
```

`county_hpsa_summary` includes coverage percentages (`*_coverage_pct`) computed as:
- denominator: county adult 18+ population when available, otherwise total population
- source: `v_county_population` view (from `dim_county`)
- formula: `(population_covered / denominator) * 100`, rounded to 3 decimals, clamped to `[0, 100]`
- aggregation method: `MAX` designated population per county/type (conservative for overlap risk)
- method metadata fields: denominator source/type, overlap caveat, pct definition, and per-type method text

`hpsa_domain_quartiles` is also rebuilt for `pc`, `mh`, and `dh` using only designated
counties with non-null `*_hpsa_score_max`, storing `q25`, `q50`, `q75`, `n_counties`,
and `as_of_date` for deterministic choropleth tiering.

## Rebuild TAGGS from Redo CSV Exports (Schema `taggs`)

TAGGS now ingests from the multi-OPDIV redo CSV exports in `data/taggs/redo`.

Run migrations first:

```bash
cd backend
./.venv/bin/alembic upgrade head
```

Run:

```bash
cd backend
python scripts/ingest_taggs_redo.py \
  --input-dir ../data/taggs/redo \
  --drop-and-recreate \
  --rebuild-summaries \
  --rebuild-can-table \
  --verbose
```

Outputs:

- `taggs.raw_awards`
- `taggs.award_funding_summary`
- `taggs.state_funding_summary`
- `taggs.can_classification`
- `taggs.ingestion_runs`
- validation summary JSON at `data/taggs/redo/taggs_redo_ingestion_summary.json`

Legacy TAGGS scrape-era tables replaced by the rebuild:

- `taggs.award_funding_year_summary`
- `taggs.scrape_runs`
- `taggs.raw_web_rows`
- `taggs.award_actions_canonical`

Reference:

- `backend/app/taggs/CSV_INGEST.md`

Notes:

- raw rows remain immutable after description-row pairing
- CAN is preserved as a first-class field in raw and summary layers
- this rebuild refreshes raw/source, summary, and CAN inventory layers only
- CDC-profile-assisted CAN mapping and final normalization remain separate later steps
- `--drop-and-recreate` is a local schema-reset utility that recreates TAGGS tables from the current ORM definitions; it does not advance `alembic_version` and should not be treated as a migration mechanism

## Build CDC-Profile-Assisted TAGGS CAN Mapping

After CDC Funding Profiles and TAGGS raw tables are loaded, rebuild the CAN dictionary using CDC Funding Profiles FY2020-FY2023 as the primary reference dataset:

```bash
cd backend
python scripts/build_can_profile_mapping.py \
  --export-review-csv ../data/taggs/review/can_profile_mapping_review.csv \
  --verbose
```

Outputs:

- `taggs.can_classification` (profile-assisted and fallback CAN mapping)
- `taggs.can_profile_match_audit`
- `data/taggs/review/can_profile_mapping_review.csv`
- compatibility views:
  - `cdc_profiles.profile_detail_rows`
  - `cdc_profiles.profile_state_totals`

## Review Uncertain Profile-Scope Transactions

Build a read-only review pack for transactions where `include_in_profile_scope IS NULL`:

```bash
cd backend
./.venv/bin/python scripts/review_profile_scope_uncertain.py
```

Optional flags:

```bash
cd backend
./.venv/bin/python scripts/review_profile_scope_uncertain.py \
  --family-limit 15 \
  --row-limit 75 \
  --output-dir ../data/recon/profile_scope_review_pack
```

Outputs:

## Export CHIP v1.1 Emergency Classification

After the analytics migration is applied, export the additive emergency-classification layer:

```bash
cd backend
export CDC_STATE_PROFILE_RAW_SOURCE_VERSION=v1_1_emergency_classification
python scripts/export_chip_emergency_classification.py \
  --output-dir ../exports/chip_v11_emergency
```

Files written:

- `chip_v11_emergency_classification_all.csv`
- `chip_v11_emergency_state_profile_included.csv`
- `chip_v11_emergency_centralized.csv`

These exports query the `analytics` views directly instead of re-implementing classification rules in Python.

- `data/recon/profile_scope_review_pack/README.md`
- `data/recon/profile_scope_review_pack/review_summary.json`
- `data/recon/profile_scope_review_pack/uncertain_totals_by_year.csv`
- `data/recon/profile_scope_review_pack/top_uncertain_decision_contexts.csv`
- `data/recon/profile_scope_review_pack/top_uncertain_buckets.csv`
- `data/recon/profile_scope_review_pack/top_uncertain_families.csv`
- family drilldown CSVs under `data/recon/profile_scope_review_pack/families/`

## Rebuild TAGGS Summaries from CAN Mapping

Refresh downstream TAGGS layers without re-running raw TAGGS CSV ingestion:

```bash
cd backend
python scripts/rebuild_taggs_from_can_mapping.py --rebuild-normalization
```

Outputs:
- `taggs.award_funding_summary`
- `taggs.state_funding_summary`
- `recon.normalized_state_funding`
- `recon.taggs_vs_cdc_profiles`
- `recon.normalization_methodology_log`

## Export CHIP Funding Audit Package

Build the dated transaction-audit package used to review CHIP inclusion, exclusion, unresolved rows, and source provenance:

```bash
cd backend
python scripts/export_chip_funding_audit.py --overwrite
```

Output directory:

- `exports/chip_funding_audit_export_<YYYYMMDD>/`

Artifacts:

- `chip_model_transactions_included.csv`
- `chip_model_transactions_excluded.csv`
- `chip_model_transactions_null_inclusion.csv`
- `chip_model_data_dictionary.csv`
- `chip_model_readme_methodology.md`
- `chip_model_validation_summary.csv`

## Ingest USAspending CDC Contract Prime Transactions (Schema `usaspending`)

USAspending contract CSVs live in `data/usaspending/contracts`.

This ingest is intentionally broader than CDC Funding Profiles scope:

- all CDC contract prime transaction rows are loaded faithfully into raw storage
- CDC Funding Profiles generally exclude contracts, but the profile documentation explicitly calls out vaccine purchases provided through the Vaccines for Children (VFC) program
- CHIP therefore preserves all raw contract rows, then adds a separate derived classification layer to flag likely VFC procurement and other potentially relevant contract categories for later normalization work

Run:

```bash
cd backend
python scripts/ingest_usaspending_contracts.py \
  --input-dir ../data/usaspending/contracts \
  --drop-and-recreate \
  --rebuild-summaries \
  --verbose
```

Useful flags:

- `--truncate` clears previously loaded contract raw/summary rows before loading
- `--dry-run` validates files and writes the JSON summary without touching the database
- `--limit-files N` deterministically caps discovered CSVs after sorting

Outputs:

- `usaspending.contract_transactions_raw`
- `usaspending.contract_transactions_enriched` (view)
- `usaspending.contract_state_year_summary`
- `usaspending.contract_federal_account_inventory`
- `usaspending.contract_category_rules`
- `usaspending.ingestion_runs`
- validation and ingestion summary JSON at `data/usaspending/contracts/contracts_ingestion_summary.json`

## Build CDC Profile-Scope Reconstruction Layer

After the assistance layer, USAspending contract ingest, and federal-account lookup layer are loaded, build the additive CDC profile-scope candidate universe:

```bash
cd backend
./.venv/bin/alembic upgrade head
python scripts/build_profile_scope_layer.py --verbose
```

Outputs:

- `recon.profile_scope_rules`
- `recon.assistance_transactions_profile_enriched`
- `recon.contract_transactions_profile_enriched`
- `recon.profile_scope_transactions`
- `recon.profile_scope_state_year_summary`
- `data/recon/profile_scope_build_summary.json`

Method notes:

- this layer is additive only and does not mutate raw USAspending, TAGGS, or CDC Profiles source tables
- assistance and contracts are treated differently on purpose:
  - domestic CDC assistance on regular appropriations is generally included
  - emergency, ARPA, and special-transfer assistance only move in-scope when a deterministic rule supports them
  - contracts stay excluded by default except conservative VFC-like procurement cases
- multi-account USAspending assistance rows are normalized into ordered transaction-to-account links before assistance profile-scope decisions are made
- federal-account lookup fields (`effective_funding_stream`, `effective_scope_guess`, `effective_profile_relevant`, and VFC/emergency flags) drive the default decision framework
- uncertain rows are preserved with `include_in_profile_scope = NULL` rather than being forced into an overconfident binary classification
- the methodology version is currently `profile_scope_v2_assistance_account_normalization`

This is a reconstruction layer for later calibration against CDC Funding Profiles FY2020-FY2023. It is not a raw source table and it does not copy CDC Funding Profile amounts into USAspending totals.

## Build Observed Federal Account Lookup / Classification Layer

After USAspending contracts are loaded, and CDC assistance transactions are loaded when available, build the additive federal account lookup layer seeded only from account symbols CHIP actually observes:

```bash
cd backend
python scripts/build_federal_account_lookup.py \
  --reseed-from-observed \
  --rebuild-observations \
  --rebuild-classification \
  --export-review-csv \
  --verbose
```

Useful flags:

- `--dry-run` computes lookup, observation, classification, and review payloads without writing DB rows
- `--review-csv-path /path/to/file.csv` overrides the default review export path
- `--account-metadata-path /path/to/account_metadata.csv` supplies an optional local metadata CSV for titles / parsed account fields

Outputs:

- `recon.federal_account_lookup`
- `recon.federal_account_observations`
- `recon.federal_account_classification_rules`
- `recon.contract_transaction_accounts` (view)
- `recon.assistance_transaction_accounts` (table)
- `recon.assistance_transaction_account_summary` (table)
- `recon.federal_account_review_export` (view)
- optional review export at `data/usaspending/review/federal_account_review.csv`

Notes:

- this workflow does not ingest the full public federal account universe; it starts from the observed CHIP USAspending symbol set
- semicolon-delimited USAspending assistance account fields are split into additive transaction-to-account links before the lookup is reseeded
- raw `usaspending.*` and `taggs.*` tables are not altered
- if no local account metadata source exists yet, the lookup still builds from observed symbols alone and leaves enrichment fields nullable for later refinement
- this step prepares later normalization work; it does not perform final CDC-profile-aligned normalization by itself

## Rebuild USAspending Assistance Multi-Account Fix

After the federal-account lookup, profile-scope layer, and calibration layer migrations are applied, run the structural assistance-account normalization rebuild:

```bash
cd backend
python scripts/rebuild_assistance_multi_account_fix.py \
  --export-review-csv \
  --verbose
```

Outputs:

- refreshed `recon.assistance_transaction_accounts`
- refreshed `recon.assistance_transaction_account_summary`
- rebuilt `recon.federal_account_lookup`
- rebuilt `recon.assistance_transactions_profile_enriched`
- rebuilt `recon.profile_scope_transactions`
- rebuilt `recon.profile_scope_state_year_summary`
- rebuilt `recon.profile_reconciliation_state_year`
- rebuilt `recon.profile_reconciliation_driver_breakdown`
- rebuilt `recon.normalized_state_funding`
- rebuilt `recon.profile_reconciliation_summary`
- diagnostics summary at `data/recon/assistance_multi_account_fix_summary.json`

## Unified TAGGS CAN Pipeline

```bash
cd backend
python scripts/rebuild_taggs_can_pipeline.py \
  --use-cdc-profiles \
  --rebuild-summaries \
  --rebuild-normalization \
  --rebuild-profiles \
  --export-review-csv \
  --verbose
```

Validate that the derived TAGGS summaries actually contain interpreted CAN labels:

```bash
cd backend
python scripts/validate_taggs_can_mapping.py --min-mapped-ratio 0.60
```

## Ingest CDC Funding Profiles Reference Data (Schema `cdc_profiles`)

CDC Funding Profiles FY2020-FY2023 are ingested as a calibration reference for TAGGS and USA Spending normalization.

Run:

```bash
cd backend
python scripts/ingest_cdc_profiles.py \
  --data-dir ../data/cdcfundingprofiles \
  --truncate
```

Outputs:

- `cdc_profiles.raw_profile_rows`
- `cdc_profiles.state_year_totals`
- `cdc_profiles.methodology_documents`

## Build CDC Funding Profiles Calibration Layer (Schema `recon`)

After CDC Funding Profiles, USAspending/profile-scope, and optional TAGGS support tables are loaded, rebuild the additive calibration and reconciliation layer:

```bash
cd backend
python scripts/build_profile_calibration_layer.py \
  --fiscal-years 2020 2021 2022 2023 2024 2025 2026 \
  --source-system usaspending \
  --include-taggs \
  --rebuild-normalized-table \
  --export-summary \
  --verbose
```

What this step does:

- uses `cdc_profiles.state_year_totals` as the observed FY2020-FY2023 CDC profile reference layer
- uses `recon.profile_scope_transactions` and `recon.profile_scope_*_enriched` as the reconstructed USAspending comparator
- measures state-year residuals instead of forcing equality
- writes driver-level diagnostics for included, excluded, and uncertain funding streams
- refreshes `recon.normalized_state_funding` with observed calibration years and later-year estimate metadata
- exports `data/recon/profile_calibration_summary.json`

Outputs:

- `recon.profile_calibration_cdc_reference` (view)
- `recon.profile_scope_transaction_diagnostics` (view)
- `recon.profile_calibration_usaspending_state_year_support` (view)
- `recon.profile_calibration_taggs_state_year_support` (view)
- `recon.profile_reconciliation_state_year`
- `recon.profile_reconciliation_driver_breakdown`
- `recon.profile_reconciliation_summary`
- `recon.normalized_state_funding`

Notes:

- raw CDC Funding, USAspending, and TAGGS tables remain unchanged
- normalized totals remain reconstructed amounts; CDC Funding Profile totals are not injected into map totals
- FY2020-FY2023 are observed calibration years
- FY2024-FY2026 remain profile-aligned estimates when rebuilt
