# USAspending Federal Account Ingestion

## Purpose

This layer ingests USAspending Federal Account custom downloads for FY2020 through FY2026 into a parallel schema named `usaspending_fed_account`.

The design is account anchored:

- Federal accounts are the classification anchor.
- Account balances are the reconciliation and control totals.
- Award-level rows are the spending and geography bridge.
- PA/OC rows describe program activity and object class use.
- Unlinked award breakdown rows are preserved as `award_source_type = 'unlinked'`.

This does not replace the current CHIP funding model or CDC funding map. It creates a separate ingestion and reconciliation layer for CHIP funding model v2 work.

## Source Folder

Default source folder:

```bash
/home/john/places-app/data/usaspending/fed_account_data
```

The script walks the folder for CSV files and ignores generated files under an `outputs/` subdirectory.

## File Patterns

Files are discovered by fiscal year and dataset type rather than hard-coded timestamps.

Examples:

- `FY2020Q1-P12_075_FA_Assistance_AccountBreakdownByAward_*.csv`
- `FY2020Q1-P12_075_FA_Contracts_AccountBreakdownByAward_*.csv`
- `FY2020Q1-P12_075_FA_Unlinked_AccountBreakdownByAward_*.csv`
- `FY2020Q1-P12_075_FA_AccountBalances_*.csv`
- `FY2020Q1-P12_075_FA_AccountBreakdownByPA-OC_*.csv`

The loader infers:

- fiscal year from `FY2020`, `FY2021`, etc.
- source agency code from filename fragments such as `_075_FA_`
- period label from the leading filename segment
- download timestamp from filename fragments such as `2026-04-23_H15M46S14`

## Tables

`usaspending_fed_account.raw_file_registry`

Tracks each ingested file, including fiscal year, dataset type, path, hash, row count, and ingest time. File hash and file path are unique so repeated runs can skip already loaded files.

`usaspending_fed_account.dim_federal_account`

One row per normalized federal account identity. The normalized account key prioritizes treasury account symbol, then federal account symbol, then agency/main/sub account parts, then an agency plus account-name fallback.

`usaspending_fed_account.fact_account_balance`

Account balance/control total rows by fiscal year and account. Raw rows are preserved in JSONB and unmapped amount-like columns are retained in `other_amount_json`.

`usaspending_fed_account.fact_account_pa_oc`

Program activity and object class rows by fiscal year and account. Raw rows and amount-like columns are preserved.

`usaspending_fed_account.fact_award_account_breakdown`

Award-level account breakdown rows from assistance, contracts, and unlinked files. These rows carry recipient and place-of-performance geography for later mapping.

`usaspending_fed_account.v_account_reconciliation`

Live SQL view that compares balance obligations to award obligations and PA/OC obligations by fiscal year and normalized federal account.

## Running The Migration

```bash
cd /home/john/places-app/backend
alembic upgrade head
```

## Dry Run

Dry run discovers and parses the files without opening a database connection or writing rows.

```bash
cd /home/john/places-app/backend
python scripts/ingest_usaspending_federal_accounts.py --dry-run --years 2020 2021 2022 2023 2024 2025 2026
```

For a faster parsing smoke test:

```bash
python scripts/ingest_usaspending_federal_accounts.py --dry-run --years 2020 --limit-rows 1000
```

## Full Ingest

```bash
cd /home/john/places-app/backend
python scripts/ingest_usaspending_federal_accounts.py --years 2020 2021 2022 2023 2024 2025 2026 --rebuild-reconciliation
```

The loader is idempotent by file path and file hash. It skips already ingested files unless `--force` is supplied. With `--force`, prior fact rows for the matching registry entries are removed before the file is loaded again.

## Reconciliation Report

The ingest command with `--rebuild-reconciliation` writes:

```bash
/home/john/places-app/data/usaspending/fed_account_data/outputs/federal_account_reconciliation_fy2020_2026.csv
```

The report contains one account-year row per record returned by `usaspending_fed_account.v_account_reconciliation`.

To verify the view after ingest:

```bash
cd /home/john/places-app/backend
python scripts/verify_usaspending_federal_accounts.py --years 2020 2021 2022 2023 2024 2025 2026
```

## Why This Shape

USAspending account balances are the fiscal control totals. They answer how much obligation and outlay activity belongs to each federal account in a fiscal year.

Award breakdown rows answer where those obligations can be geographically mapped and which awards, recipients, agencies, descriptions, ALNs, PSCs, and NAICS codes are involved.

PA/OC rows sit between those two layers. They explain what program activities and object classes account obligations flowed through, which helps classify account spending before mapping it to places.

Keeping these tables separate lets us reconcile first, then decide how CHIP funding v2 should use award-level geography without losing the original federal account accounting context.

