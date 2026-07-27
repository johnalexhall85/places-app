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

## Adding Another Fiscal Year

Create the next folder, for example `data/chipfunding/FY2024`, with the same 15-file structure. Run the dry run first. If headers have changed, the importer fails with the missing, unexpected, or reordered columns; update the explicit header contract and migration only after intentionally accepting a new source schema.

Future read-only API and informational dashboard work should query these new tables as source-of-truth inputs rather than mutating source data or changing current map classifications.
