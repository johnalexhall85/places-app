# Task H2i (Antigravity): AHRQ CLH history parser

Follow [H2-antigravity.md](H2-antigravity.md). Product key `clh`.

- **Registry:** `backend/app/area_pilot/registry/history/clh.json`. It has 5 measures and file years 2018–2022.
  - The three `ACS_*` measures are at county and tract level, with ACS-window periods (e.g. `2018–2022`).
  - The two `CCBP_*` measures are county only, with year periods.
  - Locators give `file_year`, `column`, and `label`.

  Some `sha256` values may read `PENDING` while downloads finish. That does not affect your tests, which pass files directly.
- **Source roles:** `clh<YYYY>_county` and `clh<YYYY>_tract` (XLSX with sheets `Layout` and `Data`).
- **Fixtures:** `backend/tests/fixtures/history/clh/clh_2018_county_sample.xlsx` and `clh_2022_county_sample.xlsx`. They hold the real Layout sheet and the real Data rows for Connecticut and Delaware. The 2022 file has blank former-Connecticut-county rows and valued planning-region rows.

## Rules specific to CLH

- **Reuse the current adapter:**
  - Use `app.area_pilot.clh.parse_value(raw, unit)` for every cell, taking the unit from the current registry (`app.area_pilot.clh.load_registry()`) by `measure_id`.
  - Follow `app.area_pilot.clh.parse_file`'s checks:
    - the sheet names are exactly `Layout`, `Data`
    - each Layout row for the measure has `row[1] == label` and `row[2] == 'num'`
    - unique Data headers
    - every `YEAR` cell equals the locator's `file_year`
    - the GEOID is a 5- or 11-digit string
    - no formula cells
    - tract `COUNTYFIPS` equals the GEOID prefix
    - no duplicate GEOIDs

    `parse_file` itself hard-codes 2023 and the row counts, so implement those checks in your parser instead of calling it.
- **Streaming:** use `openpyxl.load_workbook(path, read_only=True, data_only=False)` and stream the rows. The real tract files hold about 85,000 rows.
- **Values:** convert with `Decimal(str(raw))` after `parse_value` accepts the cell, and never round. `source_value` is `str(raw)`, or `''` when blank.
- **Territories:** rows whose GEOID starts with `60`, `66`, `69`, or `78` are counted and dropped. Every other row is emitted, including blank cells as `missing`.
- **Parts:** one per (file year, level), e.g. `y2018_tract`.
- **Tests:**
  - Exact counts per (measure, period, level).
  - Two hand-checked values: `09110` 2022 `ACS_PCT_HU_NO_VEH` = 9.51, and a 2018 Delaware county.
  - A 2022 former Connecticut county is stored as `missing` with vintage `2024`, and a 2018 `09001` row gets vintage `2020`.
  - A Layout label change raises.
  - A wrong `YEAR` raises.
  - The CCBP measures produce no tract rows.
