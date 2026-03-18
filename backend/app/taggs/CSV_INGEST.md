# TAGGS Redo CSV Rebuild

CHIP now rebuilds the TAGGS raw/source layer from CSV exports in `data/taggs/redo`.

This step is intentionally limited to raw ingestion plus core TAGGS support tables. It does not run CDC-profile-assisted CAN mapping, funding-stream inference, or final normalization.

## Source Directory

- `data/taggs/redo`
- The ingest scans the full directory for `*.csv`, sorts files deterministically, validates the effective headers, and writes a machine-readable rebuild summary to `data/taggs/redo/taggs_redo_ingestion_summary.json`.

The current redo set contains multiple OPDIV/state-scope exports, including:

- `CDC-*`
- `ACF-*`
- `HRSA-*`
- `ASPR.csv`
- `HHS-OS.csv`
- `SAMSHA-*`

## File Shape

The parser is built for TAGGS export quirks:

- metadata banner rows can be one line or multiple lines before the true header row
- the actual header row is discovered by structure, not by fixed line number
- a main award row can be followed by one or more description-only rows
- description rows have only the first column populated and are paired to the immediately preceding main row
- description rows never create separate raw records
- repeated description rows append to `award_description` with newline separators and are logged as anomalies

Two reconciled header families are currently observed in `data/taggs/redo`:

- city-based files such as CDC / ASPR
- ZIP + congressional-district files such as ACF / HHS-OS / parts of HRSA / SAMHSA

Minor schema variation is accepted as long as required TAGGS fields are still mappable into the canonical ingest layer.

## Rebuilt Tables

The redo ingest rebuilds these tables in schema `taggs`:

- `taggs.raw_awards`
- `taggs.award_funding_summary`
- `taggs.state_funding_summary`
- `taggs.can_classification`
- `taggs.ingestion_runs`

### `taggs.raw_awards`

Purpose:

- immutable row-level storage after description pairing
- source metadata and raw header/row JSON preserved for audit/debug work

Notes:

- raw rows are not deduplicated
- CAN is preserved as a first-class field
- raw header variation is preserved in `raw_header_json`
- the original main row plus paired description rows are preserved in `raw_row_json`

### `taggs.award_funding_summary`

Purpose:

- report/map-ready award aggregation layer

Grain:

- `award_number`
- `funding_fiscal_year`
- `opdiv`
- `can_code`
- `legal_entity_state_normalized`
- `legal_entity_county_normalized`
- `program_office`
- `aln`

### `taggs.state_funding_summary`

Purpose:

- fast state rollups for map/report work

Grain:

- `funding_fiscal_year`
- `legal_entity_state_normalized`
- `opdiv`
- `can_code`
- `program_office`
- `aln`

### `taggs.can_classification`

Purpose:

- clean CAN inventory foundation for later mapping/classification work

This rebuild populates only the observed/dominant inventory fields:

- `observed_first_fy`
- `observed_last_fy`
- `observed_row_count`
- `observed_total_funding`
- `dominant_opdiv`
- `dominant_program_office`
- `dominant_aln`
- `dominant_assistance_listing_title`

Future-use fields remain in the schema for later steps.

## Rebuild Command

From `backend/`:

```bash
python scripts/ingest_taggs_redo.py \
  --input-dir ../data/taggs/redo \
  --drop-and-recreate \
  --rebuild-summaries \
  --rebuild-can-table \
  --verbose
```

Optional flags:

- `--dry-run`
- `--limit-files N`
- `--no-rebuild-summaries`
- `--no-rebuild-can-table`

## Validation Output

The rebuild summary JSON includes:

- files processed
- total raw main rows parsed
- description rows paired
- orphan description rows
- funding fiscal year coverage
- total distinct award numbers
- total distinct CAN codes
- total funding by fiscal year
- total funding by OPDIV
- total funding by state
- header discrepancies
- file-level anomalies

## What Happens Later

Later TAGGS steps remain separate from this redo ingest:

- CDC-profile-assisted CAN mapping
- funding-stream interpretation
- final CDC-profile alignment / normalization

Those later steps can rebuild on top of the redo raw/source tables after this ingest has succeeded.
