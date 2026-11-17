# Task H2g (Antigravity): CDC PLACES county and tract history parser

Follow [H2-antigravity.md](H2-antigravity.md). Product key `places`.

- **Registry:** `backend/app/area_pilot/registry/history/places.json`, which has 13 measures and 59 measure-years.
  - Each period's locator gives `release` (`2020`–`2024`), `measureid` (CDC's upper-case ID, e.g. `DIABETES`), and `year` (the BRFSS data year).
  - Levels are county and tract.
- **Source roles:** `places<release>_county` and `places<release>_tract`, both Socrata CSV exports already filtered to `datavaluetypeid='CrdPrv'` and the 13 measure IDs.
  - The **2020 county file has no `locationid`**, only `stateabbr` and `locationname` (county name).
  - The 2020 tract file adds `countyfips` and `countyname`.
- **Fixtures** in `backend/tests/fixtures/history/places/`: real exports for all five releases, filtered to Connecticut and Delaware.

## Rules specific to PLACES

- **Selection:** a source row is used only when its (release, `measureid`, `year`) equals a declared locator. Rows for the same measure and year from an older release (a duplicate data year) are skipped and counted in evidence, as are any other undeclared (measure, year) rows. A row whose `datavaluetypeid` is not `CrdPrv` raises.
- **GEOIDs:**
  - County rows use `locationid`, which must be 5 digits.
  - For the 2020 county file, build a map `(stateabbr, countyname) → countyfips` from that release's own tract file, then map each county row's `(stateabbr, locationname)`. A name that maps to zero or to several codes raises with the names listed. Record the mapping count in evidence.
  - Tract rows use `locationid`, which must be 11 digits.
  - Rows for states, the US, or any other non-county/tract location raise unless they can be clearly identified, for example a `locationid` of `59` or `US`. Count them in evidence and drop them.
- **Values and statuses:**
  - A `data_value` present means `available` (or `true_zero` at 0). It needs both confidence limits, and `low ≤ value ≤ high`; otherwise raise.
  - A blank value with a footnote symbol means `suppressed`.
  - A blank value with no footnote means `missing`.
  - Any CI on a blank value raises. Values must be in 0–100.
  - Uncertainty is `ci95`. `source_value` is the raw `data_value`.
- **Duplicates:** the same (level, GEOID, measure, year) twice from the declared release raises.
- **Parts:** one per (release, level), e.g. `r2023_tract`. These are large on the real data (about 940,000 rows per tract file), so stream the CSV with `csv.DictReader` and do not hold more than one part at a time.
- **Tests** (on the fixture):
  - Exact row counts per (measure, period, level).
  - Fairfield, CT 2018 `ACCESS2` = 10.0 (8.5–11.6), from the 2020 release, mapped to `09001`.
  - `dental_crudeprev` 2020 comes from the 2023 release, and the 2022 release's dental 2020 rows are skipped and counted.
  - A 2024-release Connecticut county row (`09110`…) gets vintage `2024`; a 2023-release row (`09001`) gets `2020`; its tracts get `2019`.
  - An ambiguous county name raises.
  - A CI outside the value raises.
