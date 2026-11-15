# PLACES 2025 county pilot: operator guide

This is the bounded county pilot for the official [CDC Socrata view i46a-9kgh](https://data.cdc.gov/d/i46a-9kgh). It is separate from legacy PLACES tables. The curated fields are `dental_crudeprev` (2022, adults) and `access2_crudeprev` (2023, adults 18–64), with their corresponding `*_crude95ci` fields. County values are published estimates, not aggregates. Kentucky and Pennsylvania's absent 2023 insurance cells are represented as `not_published` observations. The checked 2025 source schema SHA-256 is pinned in `app/area_pilot/registry/places_county_2025.json`.

## Lifecycle

From `backend/` after `alembic upgrade head`:

```bash
.venv/bin/python -m app.area_pilot.cli fetch-stage-validate
.venv/bin/python -m app.area_pilot.cli review CANDIDATE_UUID
.venv/bin/python -m app.area_pilot.cli approve-publish CANDIDATE_UUID \
  --semantic-sha256 REVIEWED_SEMANTIC_SHA256 \
  --schema-sha256 REVIEWED_SCHEMA_SHA256 \
  --metadata-sha256 REVIEWED_METADATA_SHA256
.venv/bin/python -m app.area_pilot.cli rollback RETAINED_PUBLISHED_RELEASE_UUID
.venv/bin/python -m app.area_pilot.cli deactivate
```

The first candidate requires explicit supervised approval. A rerun with the same semantic content, schema, relevant metadata, and keyset returns the existing candidate and stores a new run and raw-file provenance. No scheduler or automatic publication is installed. Rollback only changes the active pointer to an already published, retained release. For the first publication, `deactivate` removes the active pointer so the catalog and UI show no active pilot. Both actions retain published observations and metadata for release-pinned requests.

`fetch-stage-validate` writes original response bytes under `data/ingest/places_county_2025/<run UUID>/` using atomic temporary-file renames. A `checkpoint.json` records verified page paths and checksums. To resume an interrupted run, pass `--resume-directory PATH`; pages are reused only if the source revision, schema, and complete county keyset still match. Use `--directory PATH` to choose a different ingest root.

## Source checks and checksums

The adapter obtains source view metadata, source `count(*)` and `count(distinct countyfips)`, and a complete ordered FIPS list before and after retrieval. It then gets all source fields with `countyfips ASC` keyset pages of at most 1,000 records, where each page starts after the prior page's last FIPS. It validates page order and uniqueness, exact retrieved FIPS equality to both source lists, expected 3,143 counties, source schema/field definitions, and the local 2023 county boundary join. The pre/post metadata comparison includes view ID, row update timestamp, view modification timestamp, and publication timestamp. A change during retrieval leaves a held candidate and never changes the active pointer.

Every original HTTP response has its own SHA-256, URL, byte count, retrieval time, and role in `area_pilot.source_file`. The semantic SHA-256 is calculated from **all** source columns (not only curated fields): records sorted by county FIPS; fields sorted by source field name; missing or empty fields as JSON null; finite numeric fields normalized with `Decimal` to plain strings (zero as `"0"`); text preserved exactly; compact UTF-8 JSON with sorted keys. The schema SHA-256 uses sorted `fieldName`, `name`, `dataTypeName`, and `description` entries. The metadata SHA-256 covers revision fields, title, description, and schema. The keyset SHA-256 covers the sorted FIPS list. JSON whitespace and source row order cannot change the semantic digest.

Socrata does not provide a transactional snapshot for this API. A value could theoretically change and revert between metadata checks without a revision signal; that cannot be ruled out by this process. An unexpected schema or definition halts staging, preserving downloaded bytes for inspection. An identical import does not replace a published release. Changed content, coverage, metadata, or schema needs review before publication; changed schema or unexpected coverage also fails the pinned validation gate.

The approval command locks the candidate and active pointer transactionally, checks the exact reviewed SHA-256 values, reruns the staged-content and read-model comparison, verifies all validation checks and expected counts, then marks the candidate published and switches the pointer in one transaction. Retained published releases remain queryable after a later switch.

## Read API and UI

The external API URL is `/api/area`; nginx strips `/api` and FastAPI handles `/area`. The catalog shows the active release and retained published release IDs. Map, legend, and table each require explicit `dataset_id`, `release_id`, `measure_id`, `period`, `population`, `value_type`, `geography=county`, and `bbox`. Map additionally accepts `simplify`; table uses deterministic county FIPS order and `limit`/`offset` pagination. Both map and table use the same county geometry intersection (`&&` plus `ST_Intersects`). A viewport over 5,000 counties returns HTTP 413 with a zoom instruction; there is no silent truncation. The 5,000 cap accommodates the verified 3,143-county national source.

The React pilot route is `/area/places-2025`, linked from the main map source selector. It resolves the active release once from the catalog and sends that ID on all three data requests. Cache keys include dataset, release, measure, period, population, value type, geography, bbox, and map simplification, plus table pagination. Pending publication is shown explicitly. The table is keyboard accessible and includes unavailable counties, values, statuses, and CIs.

## Published pilot (2026-11-13)

Candidate `2300772b-59f0-4e8f-a92b-fe3a967c4953` was reviewed, approved, and published. Four source pages supplied 3,143 unique counties and 6,286 observations. All seven validation checks passed, and this release is the active pointer. The reviewed digests are:

- Semantic: `5cdc0b6404ec5fb5ef269694b3571d704e4259d94f9447703ec516ba149edea5`
- Schema: `728eda33c40df4ba3dbbea46d69499d6848181ae1bdae160ed431a93d2d764dc`
- Metadata: `ae469fd6a9c93ef741bfef47f06d71ef704ee9a747ec67a1d3bdcad7f262fb28`
- First original page: `dde0da7dd989c98c430cb6d31e4e8648c4672e8f013b539c32b37dcade39c9ba` (4,933,311 bytes)

The candidate has 3,143 dental values and 2,956 insurance values, plus 187 `not_published` insurance cells (120 Kentucky, 67 Pennsylvania). A read-only direct candidate query returned map/table parity for county keys, values, statuses, periods and CIs. A national query returned 3,143 counties in 4.54 s with about 1.0 MB simplified map-like JSON; a seven-county local query took 0.017 s with about 2.5 KB. These were candidate query measurements.

The deployed API was checked through Nginx with an authenticated session. Both national maps returned 3,143 features, all seven 500-row table pages matched map keys/values/statuses/CIs, and catalog/map/legend/table used the same release ID. National map responses were about 1.48 MB and took 4.3 seconds each in this local check. An authenticated Chromium run verified the county-only message, 2022/2023 measure changes, keyboard table pagination, zoom retrieval, stable release ID, and no browser page errors. The frontend bundle was copied to `/var/www/places`; `places-backend` was restarted once. Systemd and Nginx configuration files were unchanged. Legacy PLACES, SVI, FEMA, and CDC funding read endpoints returned 200 before and after deployment, and baseline table counts did not change.

### First-release recovery

The predeployment web root and version manifest are retained at `data/deploy-recovery/places-2025-20261113T154425Z/`. To hide the pilot while preserving its data and provenance:

```bash
cd /home/john/places-app/backend
.venv/bin/python -m app.area_pilot.cli deactivate
```

To restore the prior frontend build if needed:

```bash
# Verify the exact recovery contents and destination before any application restore; see the Phase 4 operations guide.
```

The prior backend `app/main.py` entry point is also backed up as `main.pre-pilot.py` in that recovery directory. If the new route import itself causes a backend failure, restore that file to `backend/app/main.py` and restart `places-backend`; retain a copy of the current entry point first. A retained published release can be made active again with `rollback <release UUID>`, including after `deactivate`.

During browser verification, the pilot was deactivated while table pagination and stale-result handling were corrected. The retained release was then reactivated through `rollback`; the final active pointer and browser/API checks passed. This exercised the first-release recovery path without deleting candidate data.

### Wide-screen map correction (2026-11-13)

The first deployed pilot page used a fixed 450 px map and passed Leaflet's raw bounds to the API. At a 2,560 px browser width, its initial bounds extended beyond −180° longitude and the API correctly rejected the request with `Invalid bbox bounds`. The frontend now uses the CHIP header and full map layout, chooses a width-aware initial zoom, constrains panning to canonical map bounds, and clamps requested viewport coordinates to the API's valid longitude and latitude range. The same normalized viewport string is used for map, legend, and table requests. The legend's five available-value bands use equal intervals over the selected viewport's available range, with unavailable cells shown separately.

The frontend was rebuilt and copied to `/var/www/places`; no backend restart or Nginx change was needed. The prior frontend web root is retained at `data/deploy-recovery/places-2025-wide-map-fix-20261113/`. At 2,560×1,392, authenticated Chromium returned a complete 3,128-county initial viewport, matching table total and release ID, with no page errors. Zooming fetched a complete new 3,096-county viewport, and switching to insurance displayed its 2023 period and all 187 unavailable observations in that view. The original map still rendered. The active release pointer was deactivated during the correction and restored to the same reviewed release after verification.

If this frontend correction needs to be reverted, first deactivate the pilot with the command above, then restore the previous frontend assets:

```bash
# Verify the exact recovery contents and destination before any application restore; see the Phase 4 operations guide.
```

## Phase 2: official census tracts

The tract source is the official [CDC 2025 GIS friendly tract view `yjkw-uj5s`](https://data.cdc.gov/d/yjkw-uj5s), retrieved from `https://data.cdc.gov/resource/yjkw-uj5s.json`. Its reviewed schema digest is `93a997e5427db4d348cf979b382bfdf192f97b2f06b441be17558d7c1c75af34`. The source has 83,522 unique eleven digit `tractfips` values, one per row, and the curated measures produce 167,044 release keyed observations. Dental visits are 2022 crude prevalence among adults with `dental_crude95ci`; lack of health insurance is 2023 crude prevalence among adults aged 18–64 with `access2_crude95ci`. The 4,707 absent insurance cells occur in Kentucky (1,299) and Pennsylvania (3,408), matching the [CDC release notes](https://www.cdc.gov/places/current-release-notes/index.html). They are stored as `not_published`, with null value and CI.

The candidate is a **combined county and tract release**. It copies the 3,143 staged county source rows and 6,286 county observations from its retained published parent, then stages the tract source and observations under the same new release ID. The parent release ID is stored on the candidate; approval requires that exact parent to remain active. The active pointer switches only after all checks and exact reviewed digests pass in one transaction. Both releases remain queryable by explicit release ID, and rollback switches the pointer to the retained county release. The database prevents inserts, updates, or deletes of published observation and staging rows, and changes to published release metadata.

The source uses 2020 Census tract geography with Connecticut planning region tract IDs. CHIP's legacy `tract_shapes` table contains older Connecticut county tract IDs. All 876 Connecticut source IDs match the official [2023 Connecticut TIGER tract file](https://www2.census.gov/geo/tiger/TIGER2023/TRACT/tl_2023_09_tract.zip), pinned to byte SHA-256 `1543bc035ab9934bf495b43f063facf29c5dc5a2676ff7ff6493f2222f4734a9`. The 884 file shapes are in an isolated pilot boundary table; eight have no source observation. All non-Connecticut source IDs join the legacy 2020 shapes. The legacy tract table is unchanged. Any unexplained unmatched source tract holds the candidate.

Run `fetch-stage-validate --geography tract` from `backend/`; `--resume-directory PATH` is supported. Retrieval uses pre/post source revision metadata, schema, count, distinct count, and complete ordered tract key lists, plus 1,000 row keyset pages. It rejects duplicate or missing keys and unexpected fields, and preserves original response bytes with individual SHA-256 values. Semantic normalization is the same as the county pilot, with records ordered by `tractfips`. The `review` action verifies every retained source page byte checksum and checks first, middle, and last records of each page against staging and both observations. Its result is a required validation before `approve-publish`. A repeated identical import records a duplicate run and returns the existing candidate without copying rows again. Socrata does not offer a transactional snapshot; an unreported value change followed by reversion between pre/post checks remains a limitation.

The API uses the same explicit release and selection contract for county and tract. A tract viewport returns at most 5,000 features. The count query stops at 5,001; larger requests return HTTP 413 and the UI visibly falls back to counties with a zoom instruction. Map, legend, and paginated table use the same indexed `&&` plus `ST_Intersects` rule. The map starts at county level and switches to tracts at zoom 10, matching the main CHIP tract threshold. The release, measure, period, population, and value type remain pinned across transitions. The national view remains county level; no nationwide tract geometry is fetched there.

### Reviewed Phase 2 candidate

Candidate `f735c524-3fd4-4848-bfe3-1049cbc514dd` was staged from the source revision with `rowsUpdatedAt=1764844763`, `publicationDate=1764844851`, and `viewLastModified=1790119380`; all three values were identical before and after retrieval. The reviewed digests are:

- Semantic: `2eebfa924bc5b9e6730394d57c69460b7d8a8a21e2d02df3b6c718d0ae16ca34`
- Schema: `93a997e5427db4d348cf979b382bfdf192f97b2f06b441be17558d7c1c75af34`
- Metadata: `c329052927df9db67b3751485df799df76ef59da2973919e86d8ee13f9fc02ac`
- Tract keyset: `eda9869ef1b98994470fd4e5ff90904cd7ad63f3d2dec37fa9e639fa5ee7ffc1`

All ten validation checks passed, including original byte verification and source to database parity for 252 sampled tracts across 84 source pages (209,917,627 page bytes). A repeated import returned the same candidate ID and no new observations. Before publication, a rolled back transaction temporarily exposed the candidate to direct read API functions: map, legend, and every table page matched on keys, values, statuses, periods, and CIs in Atlanta, Kentucky, and Hartford. Indexed viewport benchmarks on this VM were: Atlanta 1,026 tracts, count 14 ms, geometry query 129 ms, 253,548 geometry bytes; New York City 3,220 tracts, 45 ms, 121 ms, 537,399 bytes; Hartford 407 tracts, 10 ms, 62 ms, 108,722 bytes. A deliberately nationwide tract request returned HTTP 413 in 160 ms. These timings are database query timings, not browser network timings.

To revert the published Phase 2 pilot to the verified county release without deleting tract data:

```bash
cd /home/john/places-app/backend
.venv/bin/python -m app.area_pilot.cli rollback 2300772b-59f0-4e8f-a92b-fe3a967c4953
```

The predeployment frontend is retained at `data/deploy-recovery/places-2025-tract-phase2-20261113/webroot/`. For application recovery, verify exact source and destination contents as described in [the Phase 4 operations guide](chip_area_phase4_operations.md). Pointer recovery needs no frontend synchronization or migration downgrade.

### Published and deployed Phase 2 result (2026-11-13)

The reviewed candidate above was published with the exact three approval digests and is active as release `f735c524-3fd4-4848-bfe3-1049cbc514dd`. The backend service was restarted once and the built frontend was copied to `/var/www/places/`; the Nginx and systemd configuration checksums stayed unchanged. The production database is at Alembic revision `d128ba7f4c30`. The retained county release was activated and checked at 3,143 complete county features, then the combined release was restored through the documented rollback command. This demonstrates pointer recovery without deleting tract data.

Authenticated API verification returned matching release IDs for catalog, map, legend, and table. A national county request returned 3,143 complete features and a table total of 3,143. An Atlanta tract request returned 1,026 features and the same table total, with first-page GEOID parity; a Kentucky insurance viewport returned 161 tracts, including 159 `not_published` cells with null values and CIs. A nationwide tract request returned HTTP 413. Existing PLACES, SVI, FEMA, and CDC funding read endpoints all returned 200 through the authenticated proxy. An unauthenticated catalog request returned 401.

Postpublication direct API function timings and compact JSON response sizes were: Atlanta 1,026 tracts, 169 ms and 500,926 bytes; New York City 3,220 tracts, 201 ms and 1,306,792 bytes; Hartford 407 tracts, 75 ms and 206,770 bytes. These include database retrieval and Python response construction, and exclude browser network transfer and rendering.

Authenticated Chromium verified the initial county layer, tract switching after zoom, the same release across transitions, 2022 dental and 2023 insurance metadata and CIs, keyboard table expansion, and rapid measure changes settling on the final choice. The tract screenshot is retained in the Phase 2 recovery directory as `zoom-ui.png`. No browser page errors occurred. The UI initially displayed 3,127 counties intersecting its 1,600 px viewport; the explicit nationwide API query verified the complete 3,143 county coverage.

The final focused backend and CDC funding regression run passed 28 tests. The complete frontend suite passed 112 tests across 14 files, and the production frontend build succeeded. The only test warning was the existing `requests` dependency version warning; it did not affect source retrieval or validation.

## Measure-set expansion for the funder beta (2026-11-15; staging only until promoted)

The registries now list 13 measures at county and tract level: the original two plus diagnosed diabetes, high blood pressure, obesity, coronary heart disease, stroke, COPD, current asthma, depression, frequent mental distress, current cigarette smoking, and routine checkup. All eleven additions are crude prevalence among adults with 2023 data and a 95% confidence interval, read from the same two GIS-friendly files (`i46a-9kgh`, `yjkw-uj5s`) and the same source releases.

**Source check (2026-11-15, CDC metadata and data API):** each added column and its `_crude95ci` companion exists in both files with a definition ending "among adults, 2023". For every added measure the value is blank in all 120 Kentucky and 67 Pennsylvania counties and all 1,299 Kentucky and 3,408 Pennsylvania tracts, and nowhere else. These are stored as `not_published`, exactly like the insurance measure. `expected_unavailable_tract_count` is therefore 4,707 × 12 = 56,484.

**Release identity.** The source bytes do not change when CHIP reads more columns, so source digests alone would treat a wider registry as a duplicate of the published release. Each candidate now records `measure_set_sha256` (measure IDs, periods, populations, source fields, unavailable states, value type) in its report, and a run is a duplicate only when the source digests and the measure set both match. Releases staged before this change have no recorded value and are treated as the original two-measure set.

**Approval.** For a candidate that records a measure set, `approve-publish` also requires `--measure-set-sha256` with the reviewed value, and refuses if the registry's current measure set differs from the candidate's:

```bash
.venv/bin/python -m app.area_pilot.cli approve-publish CANDIDATE_UUID \
  --semantic-sha256 … --schema-sha256 … --metadata-sha256 … --measure-set-sha256 …
```

**Order of operations.** Publish the county candidate first, then stage and publish the tract candidate. The tract candidate requires the active county parent to carry the same measure set (`county_parent_measure_set` check). Between the two publications the active release is county-only, so tract values are briefly unavailable.

**Rollback.** Rolling back to an older two-measure release keeps the pointer mechanics unchanged. The eleven added measures then have no rows: maps for them are empty and `app.area_pilot.lookup` reports `not_in_release`. Roll forward again by selecting the wider release.

**Staging browser follow-up (2026-11-15):** An authenticated Chromium session through staging Nginx selected all 13 county measures on `/area/places-2025`; each rendered county polygons and a table without page errors. At zoom 11 near Person County, the diabetes tract layer rendered polygons and 49 tracts in the viewport table. This closes the C1 measure-switch browser check on staging only; it is not a new live check.
