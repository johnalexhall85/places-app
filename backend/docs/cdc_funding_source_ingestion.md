# CDC Funding Source Ingestion

This ingestion layer loads verified USAspending account-level CDC funding outputs into isolated source-of-truth tables. It does not change the CDC Funding Map, existing map queries, map classifications, frontend components, public API routes, or dashboard pages.

## Architecture

The backend is FastAPI with SQLAlchemy 2 and Alembic. Database configuration comes from `app.db`, using `DATABASE_URL` or the local PostgreSQL default `postgresql+psycopg://places:places@localhost:5432/places`. Alembic migrations live in `backend/alembic/versions`; ingestion commands are ordinary Python scripts under `backend/scripts` that call application modules.

The production/local supported database engine is PostgreSQL. The loader uses SQLAlchemy Core with chunked executemany bulk inserts so the 239 MB award CSV is streamed instead of held entirely in memory.

## Tables

All tables live in the existing `cdc_funding` schema and use the `cdc_funding_*` table-name prefix.

- `cdc_funding_import_runs`: one row per attempted load, skipped duplicate, or failed attempt.
- `cdc_funding_import_files`: per-file size, SHA-256 checksum, row counts, and load status.
- `cdc_funding_awards`: all 82 award source columns plus fiscal year and row provenance.
- `cdc_funding_account_annual`: annual account summary source rows.
- `cdc_funding_account_monthly`: monthly account summary source rows.
- `cdc_funding_account_quarterly`: quarterly account summary source rows.
- `cdc_funding_category_comparison`: CFP reference category comparison rows.
- `cdc_funding_category_monthly`: monthly category totals.
- `cdc_funding_category_quarterly`: quarterly category totals.
- `cdc_funding_category_mapping`: mapping-detail rows, including valid `No match` rows with null account fields.
- `cdc_funding_unmapped_accounts`: account-summary rows not mapped to CFP categories.
- `cdc_funding_audits`: complete JSON audit and validation payloads.

Award rows do not use `award_unique_key` as a unique key because the verified FY2023 file legitimately repeats award keys across periods and account records. The row-level uniqueness rule is `fiscal_year, source_file_name, source_row_number`.

## Data Types

Money columns use fixed-precision `NUMERIC(24,2)`. Percentages use `NUMERIC(12,4)`. Date-looking source columns are parsed to `DATE`. Identifiers, account symbols, codes, ZIP codes, congressional districts, UEIs, DUNS values, CFDA numbers, NAICS codes, office codes, permalinks, and descriptions are stored as text so formatting and leading zeroes are preserved. Blank CSV cells become SQL `NULL`; explicit zeroes remain zero; negative obligations remain negative.

The importer normalizes column names to snake case but does not rewrite source values, recompute CFP categories, collapse `Emergency`/`NonEmergency`, infer award types from `Grant`/`Contract`, or follow historical Windows paths embedded in JSON payloads.

`gross_outlay_amount_FYB_to_period_end` is the cumulative gross outlay amount from the beginning of the fiscal year through the applicable submission period or quarter end. It is stored exactly as supplied; it is not quarterly activity, and the importer does not difference or sum cumulative snapshots. `numeric_outlay_rows` records the number of source rows with numeric outlays in that summary group. `usaspending_outlays` is the mapped category's cumulative USAspending outlay value. These fields are nullable `NUMERIC(24,2)` or nullable integer counts. Blank values remain `NULL`, explicit zeroes remain zero, and negative values are preserved.

## Folder Convention

Each fiscal year is loaded from a directory like:

```bash
data/chipfunding/FY2023
data/chipfunding/FY2024
```

The file names must follow the FY-prefixed names validated in `app.cdc_funding.source_ingest`. FY2020-FY2023 use the original `FY####_CFP_*` category comparison/mapping/unmapped names. FY2024 and later may use the newer `FY####_category_summary.csv`, `FY####_category_mapping_detail.csv`, `FY####_category_unmapped_accounts.csv`, `FY####_category_summary_audit.json`, and `FY####_category_reference_validation.json` names; these load into the same isolated tables with nullable columns for the newer source fields.

## Commands

Run migrations first:

```bash
cd backend
./.venv/bin/alembic upgrade head
```

Dry run:

```bash
cd backend
./.venv/bin/python scripts/ingest_cdc_funding_source.py \
  --fiscal-year 2023 \
  --source-dir /home/john/places-app/data/chipfunding/FY2023 \
  --dry-run
```

Import:

```bash
cd backend
./.venv/bin/python scripts/ingest_cdc_funding_source.py \
  --fiscal-year 2023 \
  --source-dir /home/john/places-app/data/chipfunding/FY2023
```

Replace a changed fiscal-year dataset:

```bash
cd backend
./.venv/bin/python scripts/ingest_cdc_funding_source.py \
  --fiscal-year 2023 \
  --source-dir /home/john/places-app/data/chipfunding/FY2023 \
  --replace-fiscal-year
```

## Idempotence

The loader calculates SHA-256 checksums for all 15 required files. If a completed import for the fiscal year already has the same file/checksum manifest, the command records a skipped run and inserts no source rows. If checksums differ, the command aborts unless `--replace-fiscal-year` is supplied. Replacement deletes and reloads the complete fiscal-year dataset in one transaction, so a failed replacement preserves the previously valid data.

## FY2023 Controls

FY2023 dry run and import enforce these verified controls:

- Awards: `146293`
- Annual account rows: `72`
- Monthly account rows: `701`
- Quarterly account rows: `262`
- Category comparison rows: `17`
- Category monthly rows: `165`
- Category quarterly rows: `60`
- Mapping rows: `19`
- Unmapped account rows: `55`
- Audit JSON rows: `6`
- Award obligations: `18654414464.47`
- Annual account obligations: `18654414464.47`
- Mapped obligations: `15319611532.00`
- Unmapped obligations: `3334802932.47`
- Quarterly totals: Q1 `4509072828.31`, Q2 `2633431434.13`, Q3 `6085957664.86`, Q4 `5425952537.17`

## Building a Fiscal-Year Bundle

FY2020–FY2025 bundles and the FY2026 P10 bundle were built outside this repository by a Windows pipeline (`pipeline_version 1`, paths under `D:\DataProject\Budget\...` in each audit JSON). From FY2026 P12, [build_cdc_funding_bundle.py](../scripts/build_cdc_funding_bundle.py) builds the same 15 files on this host from a USAspending federal account download (`data/usaspending/fed_account_data/`). It follows the method recorded in `FY####_pipeline_audit.json`:

- Assistance award rows are `Grant`, Contracts award rows are `Contract`, and Unlinked rows are excluded.
- It keeps rows whose `awarding_subagency_name` is CDC **and** whose federal account symbol starts with `075-`. That account filter preserves the scope of the earlier HHS-only (`075`) downloads when the download covers all agencies (`_All_FA_`).
- `Emergency` is NonEmergency when `disaster_emergency_fund_name` is blank or contains "nonemergency", and Emergency otherwise. Award values are copied unchanged, and negative values are kept.
- It carries the reviewed category crosswalk forward unchanged from the previous bundle's `FY####_category_mapping_detail.csv`.
- It writes the three `*_validation.json` files by re-reading the written CSVs and recomputing every control. Any failed check sets `passed: false`, and the importer then refuses the bundle.

A download's cumulative outlay column (`gross_outlay_amount_FYB_to_period_end`) is populated only for its final submission period. A P12 bundle therefore carries full-year outlays at P12 and zero outlays for earlier months. That matches the earlier bundles.

```bash
cd backend
S=/home/john/places-app/data/usaspending/fed_account_data
./.venv/bin/python -I scripts/build_cdc_funding_bundle.py --fiscal-year 2026 \
  --assistance $S/FY2026P01-P12_All_FA_Assistance_AccountBreakdownByAward_2026-11-18_H15M49S09_01.csv \
               $S/FY2026P01-P12_All_FA_Assistance_AccountBreakdownByAward_2026-11-18_H15M49S09_02.csv \
  --contracts  $S/FY2026P01-P12_All_FA_Contracts_AccountBreakdownByAward_2026-11-18_H15M49S09_01.csv \
  --crosswalk  /home/john/places-app/data/chipfunding/FY2026/FY2026_category_mapping_detail.csv \
  --output-dir /home/john/places-app/data/chipfunding/FY2026_P12_candidate
```

The full FY2026 build takes about 20 seconds. To check the builder against an older bundle, add `--max-period N` and compare the summary files by natural key. On 2026-11-18, `--max-period 10` reproduced the P10 bundle exactly for all grants, every category file, and the crosswalk. The only differences were 75 contract rows in 7 accounts, caused by USAspending revisions. On five of the six dropped awards, the awarding sub-agency had been changed from CDC to HHS's financial office (ASFR); three of those were confirmed in the raw file. One award was newly attributed to CDC. Then run the importer `--dry-run` on the output folder, then `--replace-fiscal-year`.

## Adding Another Fiscal Year

Create the next folder, for example `data/chipfunding/FY2024`, with the same 15-file structure (use the builder above). Run the dry run first. If headers have changed, the importer fails with the missing, unexpected, or reordered columns; update the explicit header contract and migration only after intentionally accepting a new source schema.

Future read-only API and informational dashboard work should query these new tables as source-of-truth inputs rather than mutating source data or changing current map classifications.

## Targeted Outlay Backfill

Updated FY2021-FY2026 summaries live under `data/chipfunding/with_outlays/FY####`. The original files under `data/chipfunding/FY####` remain the canonical baseline for all non-outlay values.

The backfill compares each updated file with the original file by its table's unique natural key. It requires identical row counts, key sets, and original column values, then verifies the database against the original file before updating only outlay columns. Newly supplied `data_status` and `as_of_period` columns are allowed metadata for FY2024 and FY2025 but are deliberately ignored; the command never writes them. Any other added non-outlay column fails validation.

Natural keys are:

- Annual and unmapped accounts: fiscal year, grant/contract classification, emergency classification, and federal account symbol.
- Monthly accounts: fiscal year, submission period, grant/contract classification, emergency classification, and federal account symbol.
- Quarterly accounts: fiscal year, fiscal quarter, grant/contract classification, emergency classification, and federal account symbol.
- Category comparison: fiscal year and category.
- Monthly categories: fiscal year, submission period, and category.
- Quarterly categories: fiscal year, fiscal quarter, and category.

Run the coordinated validation before applying the migration:

```bash
cd backend
./.venv/bin/python scripts/backfill_cdc_funding_outlays.py \
  --original-root /home/john/places-app/data/chipfunding \
  --updated-root /home/john/places-app/data/chipfunding/with_outlays \
  --fiscal-years 2021-2026 \
  --dry-run
```

Apply the migration and backfill:

```bash
cd backend
./.venv/bin/alembic upgrade head
./.venv/bin/python scripts/backfill_cdc_funding_outlays.py \
  --original-root /home/john/places-app/data/chipfunding \
  --updated-root /home/john/places-app/data/chipfunding/with_outlays \
  --fiscal-years 2021-2026
```

An identical rerun is idempotent and updates zero rows. If an existing non-null outlay differs from the verified source, the command aborts unless `--replace-existing-outlays` is supplied. That flag still updates only outlay columns and runs the same source, key, database, and reconciliation checks first.

Completed backfills use `import_mode=outlay_backfill` and record updated-file checksums and validation results without replacing original import runs or audit payloads. API and frontend behavior are outside this storage-only operation.
