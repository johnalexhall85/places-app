# Task H2h (Antigravity): HRSA AHRF history parser

Follow [H2-antigravity.md](H2-antigravity.md). Product key `ahrf`. AHRF is never exposed by the MCP server; this feeds the signed-in maps only.

- **Registry:** `backend/app/area_pilot/registry/history/ahrf.json`, with 5 county measures. Two kinds of locator:
  - `{"file": "current_hp"|"current_hf", "column": "<name>_22"}`: a column in the current AHRF 2024–2025 CSVs (period 2022).
  - `{"file": "ahrf2122_zip", "field": "f…", "start": N, "width": W, "label": …, "sublabel": …}`: a fixed-width field in `DATA/ahrf2022.asc` inside the AHRF 2021–2022 ZIP. `start` is the 1-based SAS `@` column.
- **Source roles:**
  - `current_hp` and `current_hf` (CSV, UTF-8 with BOM, key column `fips_st_cnty`)
  - `ahrf2122_zip` (members `DATA/ahrf2022.asc` and `DOC/AHRF2021-2022.sas`)
- **Fixtures** in `backend/tests/fixtures/history/ahrf/`:
  - `AHRF2025hp_sample.csv` and `AHRF2025hf_sample.csv`: real rows, selected columns only.
  - `ahrf2022_sample.asc`: 10 real lines.
  - `AHRF2021-2022.sas`: the full real layout.

  For tests, build a small ZIP in a `tmp_path` holding those two members under their real names.

## Rules specific to AHRF

- **Read the fixed-width file as Latin-1,** not UTF-8: it contains non-UTF-8 bytes. Slice by character, `line[start-1:start-1+width]`. Read ZIP members in memory, and stream the `.asc` line by line.
- **Verify the layout before reading values.** Parse each locator's `field` line in the `.sas` file, which looks like `@00567    f1467520    04.  /*Phys,Primary Care, Patient Care  Non-Fed;Excl Hsp Res & 75+ Yrs  */`. Check that its start, width, and comment text (label and sublabel, whitespace-collapsed) equal the locator. Do the same for the FIPS field (`selection.fips_field`). On any difference, raise.
- **GEOIDs:** the GEOID is the FIPS slice. A FIPS ending in `000` is a state or US row: count it and drop it. A malformed or duplicate FIPS raises.
- **Values:** reuse `app.area_pilot.ahrf.parse_count(raw)` for every cell, CSV and fixed-width, after `.strip()`. Blank means `missing`, 0 means `true_zero`, and a non-digit raises.
- **Current CSVs:** use `parse_count` the same way, with the GEOID from `fips_st_cnty`.
- **Parts:** `current_2022`, then one per year from the old file, e.g. `ahrf2122_2020`.
- **Tests:**
  - Exact counts.
  - Two hand-checked fixed-width values, computed from the fixture line by slicing in the test with the same positions.
  - A deliberately shifted `start` raises.
  - A changed label in a copy of the `.sas` raises.
  - Connecticut `09001` gets vintage `2020` (old file), and `09110` gets `2024` (current CSV).
  - A blank cell becomes `missing`.
