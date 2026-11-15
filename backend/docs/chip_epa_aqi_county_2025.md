# EPA AirData annual AQI by county, 2025

Operator guide for the `epa_airdata_aqi_county_2025` shared area product. Implemented by Claude on 2026-11-14. The published and deployed state recorded here was verified that day; recheck live pointers before operating.

## Source and year

| Item | Verified value |
| --- | --- |
| Download page | https://aqs.epa.gov/aqsweb/airdata/download_files.html (HTTP Last-Modified 2026-07-13) |
| Data file | `annual_aqi_by_county_2025.zip` → single member `annual_aqi_by_county_2025.csv`; ZIP SHA-256 `72b022b3828c611007df5ededcb5933b0bce877077573dbd66a0c1c66d467130`, CSV `473ad542aa3106ff56230ce587933a3263dbcb9b93c5f24d90e612d42923fc01` |
| Build date | `file_list.csv` "Created" 2026-06-25 (985 rows); ZIP member timestamp 2026-06-26 |
| Definitions | https://www.epa.gov/outdoor-air-quality-data/about-airdata-reports ("Air Quality Index Report" section, page last updated 2026-04-01) |
| County identifiers | `aqs_sites.zip` (AirData site listing, same build) supplies EPA State Code + County Code for each State Name + County Name |
| Advisory | `Data_Advisory_PM25_88101_Pregen_Files.pdf` (posted 2024-08-26) |
| Boundaries | Existing `area_pilot.acs_boundary_2024` county layer; names from the archived `tl_2024_us_county.zip` (SHA-256 `04e668d3…cb97b`), the same file that loaded the layer |

**Year rule.** The adapter takes the latest year listed in `file_list.csv` that is earlier than the retrieval year (2025 on 2026-11-14) and skips the partial current-year file (`2026`, 827 rows). It also requires the file's build date to fall on or after May 1 of the following year, because EPA documents current-year data as preliminary until then. The 2025 file was built 2026-06-25. That is a necessary condition only. Completing a calendar year does **not** mean monitoring coverage is complete or that values are final; EPA regenerates these files.

The registry is pinned to 2025. When a later completed year appears, the candidate is held with a message to review definitions and add a new registry. No backfill or multi-year series is loaded.

## Measures

All five are published integer fields in the file. None is derived.

| `measure_id` | Source column | Unit | Official definition (EPA) |
| --- | --- | --- | --- |
| `median_aqi` | `Median AQI` | AQI index value | Half of daily AQI values during the year were less than or equal to the median value, and half equaled or exceeded it. |
| `p90_aqi` | `90th Percentile AQI` | AQI index value | 90 percent of daily AQI values during the year were less than or equal to the 90th percentile value. **A distribution statistic, not a confidence interval or margin of error.** |
| `max_aqi` | `Max AQI` | AQI index value | The highest daily AQI value in the year. |
| `days_with_aqi` | `Days with AQI` | days | Number of days in the year having an AQI value: days on which measurements from any monitoring site in the county were reported to AQS. |
| `good_days` | `Good Days` | days | Number of days in the year having an AQI value 0 through 50. |

`days_with_aqi` is stored on **every** observation row and returned with every map feature and table row. Good-day counts must be read against it. The product does not compute percentages, annualized counts, ranks, or state values. No CI or MOE exists in the source, and none is invented.

**Values above 500.** Eight 2025 counties have `Max AQI` above 500, up to 2122 in El Paso County, Texas. Values above 500 are beyond the AQI scale. They are published unchanged with `value_note = above_500_beyond_aqi_scale` and labelled in the UI.

**Missing, unavailable, and zero.** No blanks occur in the five fields, and blanks are undocumented, so a blank makes the parser hold the candidate. A numeric `0` is stored as `true_zero`; no 2025 county had zero Good days. A county absent from the EPA file has **no stored observation**. The read API left-joins 2024 boundaries and returns `no_reported_value` for such counties. This is not a measurement of clean air.

## Validation (fails or holds the candidate)

The checks are:

- **File and schema:** an exact 18-column header; exactly one ZIP member with no traversal, symlink, or encryption; size caps.
- **Keys and year:** unique (State, County) keys; `Year` equal to the selected year.
- **Integers and calendar:** integer values only; `1 ≤ Days with AQI ≤` the calendar length (366 only in leap years).
- **Category sums:** the six category day counts sum exactly to `Days with AQI`; `Good Days ≤ Days with AQI`.
- **Main pollutants:** the main-pollutant day counts sum to at most `Days with AQI`. They equal it for every 2025 row, but EPA dropped SO₂ in 2021, so only `≤` is enforced.
- **Ordering:** `Median ≤ 90th percentile ≤ Max`.
- **Max against categories:** the category containing `Max AQI` has at least one day, and every higher category has zero.
- **Counts:** the row count equals both `file_list.csv` and the registry (985).
- **Documentation:** the eight registry definition phrases are present on the EPA documentation page.
- **Geography:** the identifier cross-check and the exclusion set must match the registry exactly.

The 2025 candidate passed every check. 539 mapped counties reported fewer than 365 days, and 33 source rows reported fewer than 100.

## County identifiers and coverage

The file contains only EPA state and county **names**. GEOIDs come from EPA's own published codes, never from similarity matching:

1. **EPA code.** Find the AirData site-listing rows whose exact `State Name` and `County Name` equal the annual row, trailing spaces included; several Alaska names carry them. That pair must resolve to exactly one `State Code`+`County Code`. All 985 pairs did.
2. **TIGER cross-check.** The code must exist in TIGER 2024, and the EPA name must agree with that county under one of three rules. Folding removes accents, trims and collapses whitespace, and ignores case; nothing else.
   - `namelsad`: the folded name equals the folded NAMELSAD, reading "X (City)" as "X city". 13 rows.
   - `unique_name`: the folded name equals a NAME that is unique in the state. 952 rows.
   - `county_not_city`: the NAME is shared only with independent cities (LSAD 25), and the EPA name has no city suffix. Baltimore, Fairfax, and Roanoke: 3 rows.
3. **Reviewed variants.** Eight known spellings are listed in the registry, each bound to its EPA code and TIGER NAMELSAD: Saint Clair IL, Saint Louis MN, Saint Charles MO, Saint Louis MO (county 29189, distinct from St. Louis City 29510), Sainte Genevieve MO, Virginia "Charles" (Charles City County 51036), Puerto Rico "Mayagnez" (Mayagüez 72097), and USVI "St John". An unused variant, an unregistered disagreement, a duplicate GEOID, or an unlisted unmatched row holds the candidate.

Three Puerto Rico and New Mexico names matched only after accent folding: Bayamon, Catano, and Dona Ana.

| Coverage (2025) | Count |
| --- | --- |
| Source rows / unique source counties | 985 / 985 |
| Mapped to 2024 boundary counties | 975 (4,875 observations) |
| Source rows without compatible boundary (retained in `stage_epa_aqi` with reason) | 10 |
| 2024 boundary counties without an EPA summary (`no_reported_value` at read) | 2,247 of 3,222 |

The ten exclusions:

| Source rows | EPA code(s) | Reason |
| --- | --- | --- |
| 8 Connecticut legacy counties (Fairfield … Windham) | 09001–09015 | `legacy_ct_county_no_compatible_2024_boundary`. AQS still reports by the pre-2022 counties; they are **not** reassigned to the nine 2024 planning regions, which show no reported value. |
| Country Of Mexico / SONORA | 80026 | `non_us_jurisdiction` |
| Virgin Islands / St John | 78020 | `territory_outside_chip_2024_boundary_layer` (code verified as TIGER "St. John Island"; the CHIP 2024 layer has 50 states, DC, and PR only) |

Territory coverage: all 8 Puerto Rico source rows map; the other 70 municipios have no summary. Guam, American Samoa, and the Northern Mariana Islands have no rows in the 2025 file.

## Limitations shown in the UI and API

- Annual historical summary for 2025, not current or forecast conditions.
- Coverage reflects where monitors reported to AQS. 975 of 3,222 boundary counties have a value.
- No reported value means no published summary, not clean air.
- Reporting days vary by county; Good-day counts need that context.
- A county's AQI reflects only the pollutants it measures. EPA notes many areas monitor some, but not all, pollutants.
- **PM2.5 advisory:** AQS retains original Teledyne T640/T640X PM2.5 data (method codes 236/238) alongside corrected codes 736/738, and EPA recommends excluding the originals. The county AQI file has no method field, so this product cannot apply that recommendation. Values are shown as published, and the advisory is recorded in each candidate report.
- The EPA documentation reviewed does not say how exceptional-event days are treated in this summary. CHIP makes no claim either way.

Map shading is a neutral five-step sequential palette with fixed breaks from the registry: AQI 0–25 / 26–50 / 51–100 / 101–150 / 151+; Max AQI 0–50 / 51–100 / 101–150 / 151–300 / 301+; days 0–73 / 74–146 / 147–219 / 220–292 / 293+. EPA's daily health-category colors are deliberately **not** used, because these are annual statistics, and the legend says so. Counties with no reported value have a white fill and dashed outline.

## Storage and API

Migration `d3a7e5c1b9f2` (additive; down-revision `c9f76d3a51e2`) creates two tables:

- `area_pilot.stage_epa_aqi`: every source row with its raw record, EPA code, GEOID, match method, boundary status, exclusion reason, and mapping evidence.
- `area_pilot.observation_epa_aqi`: matched counties only.

Both tables reject INSERT, UPDATE, and DELETE for published releases through the shared trigger. The pointer is the independent `area_pilot.active_release` row for `epa_airdata_aqi_county_2025`.

The read API is the shared `/api/area/{catalog,map,legend,table}` with `dataset_id=epa_airdata_aqi_county_2025`, `geography=county`, and `period=2025`, at `value_type=annual_aqi_summary`. Tract, state, other periods, and unpublished releases return 400 or 404. The viewport cap is 5,000 (413), the table page cap is 500, and access is behind the demo session (anonymous requests return 401). The frontend route is `/area/epa-aqi`; it is also listed in both data-source selectors.

## Manual operations

Run from `backend/`. Every command takes the per-product lock `data/ingest/epa_aqi_county_2025/ingest.lock`. Nothing is scheduled. The weekly timer covers only PLACES and ACS.

```bash
.venv/bin/python -m app.area_pilot.epa_aqi_cli fetch-stage-validate
.venv/bin/python -m app.area_pilot.epa_aqi_cli review <candidate_id>
.venv/bin/python -m app.area_pilot.epa_aqi_cli approve-publish <candidate_id> \
  --semantic-sha256 <sha> --schema-sha256 <sha> --metadata-sha256 <sha>
.venv/bin/python -m app.area_pilot.epa_aqi_cli release-reviewed-hold <candidate_id> \
  --semantic-sha256 <sha> --schema-sha256 <sha> --metadata-sha256 <sha> --operator-note "<what was reviewed>"
.venv/bin/python -m app.area_pilot.epa_aqi_cli rollback <published_release_id>
.venv/bin/python -m app.area_pilot.epa_aqi_cli deactivate
```

**Fetch.** Each fetch archives the download page, `file_list.csv`, the documentation page, the PM2.5 advisory, the county ZIP and extracted CSV, and the site-listing ZIP and CSV under `data/ingest/epa_aqi_county_2025/<run UUID>/`. It records SHA-256, byte counts, retrieval times, and HTTP `Last-Modified`/`ETag` in `area_pilot.source_file` and the candidate report, and references the two archived TIGER lookup files. Downloads use 10 s connect and 60 s read timeouts, three attempts with backoff, byte caps, `.part` temporary files, and a disk-headroom check (`AREA_INGEST_MIN_FREE_GIB`, default 5).

**Checksums.**

- The semantic checksum covers all 985 raw source rows, sorted by (State, County).
- The metadata checksum covers the registry contract and a digest of the full mapping table. It deliberately excludes the volatile build date, so an identical regeneration is a duplicate.
- The schema checksum covers header, definitions, and documentation phrases.

**Review rules.**

- Identical content records a `duplicate` run against the existing release.
- Changed content under the same `source_release_id` is held as `same_label_semantic_revision`. Release it with `release-reviewed-hold` only after comparing the changed rows.
- Any other hold, such as `identifier_mismatch`, a changed definition, a new year, or a retrieval failure, needs a code or registry change and a new candidate. Do not release it.
- A failed fetch leaves the active pointer untouched.

`review` re-hashes every archived file and recomputes every observation from the staged source. `approve-publish` repeats that inside the publish transaction and moves only this product's pointer. `rollback` accepts only a retained **published** EPA AQI release. `deactivate` removes this product's pointer; the release, data, and archives remain.

**Application recovery.** The pre-deployment webroot is kept at `data/deploy-recovery/epa-aqi-20261114/webroot/`, with `webroot.sha256` beside it. The backend before this task was commit `d45fed6`. An application rollback must pair that webroot with a backend checkout that lacks the AQI router branch, then restart `places-backend`. Pointer recovery needs no deployment copy and no migration downgrade.

## 2026-11-14 publication and deployment (Claude)

The published release is `70e78172-da21-4782-91e2-d3b97896863f` (source label `AirData annual_aqi_by_county_2025`), published 2026-11-14T16:48:32Z. Its checksums:

| Checksum | Value |
| --- | --- |
| Semantic | `d29d432fed1e0ebabc138a44d53ec8032bbd4f507225adae3659a9f1781fda54` |
| Schema | `e753e547bfb1270ba530b53412d4236e9601789e399cbbd3c1d819e2a86a577e` |
| Metadata | `c71d063dbc9a3ad3c554569a46e041ac40d3dfd482204fc4ac641718b704fd17` |
| Keyset | `d3eeb2585b7220314a6603fe7a021ade1dd073dd373d108242f8f12b6db38e76` |

**Candidate and review.** Fetch, stage, and validate took 3.7 s, and all six checks passed. A second fetch recorded `duplicate` against the same candidate. Review verified 20 archived files, 985 staged rows, and 4,875 observations. Spot checks against the raw CSV matched:

| County (GEOID) | Measure | Value | Days with AQI |
| --- | --- | --- | --- |
| Pinal AZ (04021) | Max AQI | 1215 | — |
| El Paso TX (48141) | Max AQI | 2122 | — |
| Baltimore city (24510) | Median AQI | 43 | 364 |
| Mayagüez (72097) | Days with AQI | 227 | 227 |
| Saint Louis MO (29189) | Good days | 268 | — |
| Virginia "Charles" (51036) | 90th percentile AQI | 51 | — |

**Server-side verification.** This ran in-process with the deployed code against the live release, without a browser. All five measures had identical map, full-table, and legend totals in four viewports:

| Viewport | Counties | With value | No reported value | Map response |
| --- | --- | --- | --- | --- |
| Continental national | 3,109 | 956 | 2,153 | ~1.61 MB, ~3.1 s |
| Maryland/DC | 35 | — | — | 19 KB, 84 ms |
| Connecticut | 21 | 11 (neighboring states) | 10, including all CT planning regions | 12 KB, 26 ms |
| Puerto Rico | 77 | 8 | 69 | 34 KB, 62 ms |

Tract and 2026 requests returned 400, another product's release ID returned 404, and `limit=501` returned 422.

**Pointer drill.** `deactivate` cleared only this pointer; the four others stayed. `rollback 70e78172…` restored it, and a rollback to the AHRF release ID was refused. Writes to published AQI rows were blocked.

**Deployment.** The frontend was built and mirrored to `/var/www/places/` after the backup above, and `places-backend` was restarted. Anonymous `/api/area/catalog?dataset_id=epa_airdata_aqi_county_2025` through Nginx returned 401, and `/area/epa-aqi` served the app. **No authenticated browser check was performed**: creating a temporary access code was not permitted in this session. An operator with access should open `/area/epa-aqi` and select each measure, checking Baltimore city (data), any Connecticut planning region (no reported value), and Mayagüez, PR (name exception).

**Staging follow-up, 2026-11-15:** A headless Chromium session authenticated through staging Nginx checked all five measures, county polygons and table, and 390 px layout without document overflow. The table showed Baltimore city `24510` median AQI 43 with 364 days, Capitol planning region `09110` as no reported value, and Mayagüez `72097` as median AQI 9 with 227 days and source name “Mayagnez, Puerto Rico.” This closes the requested staging browser check; it is not a new live check.
