# CHIP project diary

Reverse chronological handoff record. Timestamps use ISO 8601 with an explicit timezone. Entries describe verified actions; guide-only history is labeled. Keep current state in [the handbook](PROJECT_HANDBOOK.md), not here. Preserve entries and add corrections when evidence changes.

## 2026-11-14T22:55:00+00:00 — USDA FEA commit and push (Claude)

- Commit `cd21d55` (application, migration, tests, operator guide, inventory, handbook, diary) pushed as new branch `origin/claude/usda-food-environment-atlas` without force; `git diff --cached --check` passed. No application, data, or deployment changes in this step. Not merged to `main`. The authenticated browser check remains pending.

## 2026-11-14T22:50:00+00:00 — USDA Food Environment Atlas five county measures published and deployed (Claude)

- **Objective/outcome:** Added the USDA ERS Food Environment Atlas as the independent shared area product `usda_ers_food_environment_atlas`. It has five county-only measures and its own release pointer, and is published and deployed at `/area/usda-fea`.
  - The legacy `usda_food_env.*` integration was inspected and not run. Its tables and `/api/usda/food-environment/*` routes are unchanged; only the main-map option label changed, to "legacy import, all variables".
  - The weekly timer, backups, access controls, and funding methodology were not changed. The Codex sibling worktree was not touched.
  - **Not completed:** the authenticated browser check. See *Verification* below.
- **Source verified:**
  - The downloads page's "Current Version" CSV ZIP is `/media/5570/food-environment-atlas-csv-files.zip?v=40916`, "Last Updated 7/30/2025". The readme says the "original release date of this file is July 2025", and the ZIP member timestamps are 2025-07-30.
  - The landing page ("Updated 8/12/2026") and the documentation page ("Updated 7/28/2026") are page revisions, not a new data release.
  - ZIP SHA-256 `99750f54…3b8d` (6,501,079 bytes); `StateAndCountyData.csv` `03aa52c9…cd`: 957,753 rows and 304 variables.
  - The files contain no state rows. State-level `*` variables repeat on county rows.
  - Documentation confirms `-9999`/N/A (not available) and `-8888` (county did not exist), and the 5-year boundary policy with CT and Valdez-Cordova exceptions.
- **Measures and periods:**
  - `PCT_LACCESS_LOWI19` (2019): the denominator is the total county population, not low-income residents.
  - `SNAPSPTH23` (2023).
  - `WICSPTH22` (2022).
  - `FMRKTPTH18` (2018).
  - `PCT_LACCESS_HHNV19` (2019): housing units; substituted for grocery density.
  - **Substitution reason:** `GROCPTH20` duplicates the published CLH `CCBP_SOGS_RATE` (same CBP NAICS 445110 per-1,000 concept, 2023), and 909 of 3,144 counties are `-9999`. `DSPTH20` is mislabelled "Dollar stores" (it covers NAICS 452319) and was not used.
- **Geography and coverage:**
  - Matched 2024 TIGER counties: 3,135 (3,144 for farmers' markets).
  - Documented source-only rows, staged with reasons: the 8 former CT counties, Valdez-Cordova, and for 2018 also Wade Hampton, Shannon, Bedford city, and 5 FIPS-less Alaska "Area" rows.
  - Read-time statuses: 9 CT planning regions as `boundary_not_comparable` for four measures, and 78 PR municipios as `not_covered`. No unexplained mismatches.
  - Status counts:
    - Low-income access: available 3,094, zero 39, n/a 2.
    - SNAP: 3,114 and 21.
    - WIC: 3,028 and 107.
    - Farmers' markets: 2,259, zero 872, n/a 2, did-not-exist 11.
    - No-car access: 3,121, zero 12, n/a 2.
- **Changes:**
  - Registry `usda_fea_2025.json`; modules `usda_fea.py`, `usda_fea_cli.py`, `usda_fea_api.py`; router dispatch.
  - Additive migration `c8f1e4a7d3b6` (`stage_usda_fea`, `observation_usda_fea`, immutability triggers).
  - Frontend: `/area/usda-fea` branch in `Places2025Pilot.jsx` and CSS, route, main-map option and relabel.
  - Unit and PostGIS lifecycle tests; frontend tests.
  - Operator guide `backend/docs/chip_usda_food_environment_atlas.md`; inventory child record `usda-food-environment-atlas` (now 98 records); handbook.
- **State-changing commands:**
  - `alembic upgrade head` (`b7e3c5a9d2f4` → `c8f1e4a7d3b6`).
  - `usda_fea_cli fetch-stage-validate` twice: ready candidate `28a4824f-d403-454b-bc85-998fdd64bf92` (7/7 checks, 15,684 observations), then a duplicate.
  - `review`, then `approve-publish` at 22:28:55Z (semantic `d15804aa…3343`, schema `23b4ddb1…56d9`, metadata `89722389…8ed6`).
  - Pointer drill: `deactivate`, a refused rollback to the CMS GV release, then `rollback 28a4824f…`. All ten pointers were identical afterwards.
  - Webroot backed up to `data/deploy-recovery/usda-fea-20261114/webroot-before/`, then `rsync -a --delete frontend/dist/ /var/www/places/`.
  - `sudo -n systemctl restart places-backend` at 22:29:13Z.
- **Verification:**
  - Backend:
    - 24 unit tests covering sentinels, lookup changes, ZIP safety, parsing, boundary classification, and API selection.
    - 1 isolated PostGIS lifecycle test covering idempotency, failed retrieval, unexplained geography, undocumented values, source-total change, same-label revision hold and release, publication isolation, rollback and deactivate, immutability, the 413 cap, and map/legend/table parity.
    - Focused area tests 175/175. Full suite: 643 passed, 1 failed (the known `test_all_six_real_source_years_match_acceptance_totals`).
  - Frontend: 141/141, including sentinel colours and text, county-at-national-view, exact selection across zooms, and map/table parity. The build passed with the existing chunk-size warning.
  - Review re-derived all observations. An independent check of 54 cells against both the archived CSV and the separate XLSX had 0 mismatches. All 15,684 values equal the legacy raw values.
  - In-process router checks: 32/33. The single failure was my wrong expected literal (`13.02099800`); the CSV text is `13.020998`, which is what is stored. They covered:
    - all five measures with national parity;
    - state, tract, and release-year requests refused;
    - CT, PR, and Alaska statuses;
    - Kalawao not available rather than zero;
    - the full world view of 3,222 counties within the cap.
  - Regression: 21/21. All ten catalogs are on unchanged pointers; HRSA, TRI, and nursing-home maps work; CMS GV and AQI work; legacy USDA variables, map, legend, and county detail work; funding map and legend return 200.
  - Nginx: anonymous FEA catalog, map, legend, and table return 401; pages return 200; the deployed bundle contains the new product.
  - Benchmarks: national desktop viewport map 3.3 s / 1.8 MB, legend about 0.2 s, table 0.12 s; local views 15–37 ms.
  - **The authenticated browser check was not performed.** The scripted run, which would mint a temporary demo code from backend secrets and deactivate it afterwards, was blocked by this session's permission classifier. No code was created.
- **Git/next action:** Committed on new branch `claude/usda-food-environment-atlas` (from `75df32a`) and pushed without force; see the next entry for the push outcome. Not merged to `main`.
  - Next: an operator runs the authenticated browser checklist in the guide.
  - Separately: add USDA FEA to a fresh recovery set; decide on historical backfill, tract products, and legacy retirement.

## 2026-11-14T22:01:00+00:00 — CMS OM GV commit and push (Claude)

- Commit `3a98647` (application, migration, tests, operator guide, inventory, handbook, diary) pushed as new branch `origin/claude/cms-geographic-variation` without force; `git diff --cached --check` passed. No application, data, or deployment changes in this step. Not merged to `main`.

## 2026-11-14T21:58:00+00:00 — CMS Original Medicare Geographic Variation 2024 shared product published and deployed (Claude)

- **Objective/outcome:** Added CMS Original Medicare Geographic Variation (OM GV) as an independent shared area product, `cms_om_geographic_variation`. It has five 2024 measures at state and county level for the `All` age category, with its own release pointer. Published, deployed, and browser-verified. The legacy `cms.gv_*` integration was inspected and not run; its tables, routes, and behavior are unchanged, and only the main-map selector label changed. The weekly timer, backups, access controls, and funding methodology were not changed. The Codex sibling worktree was not touched.
- **Source verified:**
  - CMS catalog series `6219697b-…`, modified 2026-05-15, temporal 2024; methods paper "May 2026 Update" (data 2007–2024).
  - CSV `2014-2024 … Public Use File.csv`: 57,865,948 bytes, SHA-256 `10c83040…6fad`, 36,994 rows, latest `YEAR` 2024. The data API showed no 2025 rows; its totals (36,994; 3,253 for 2024/All) and 7 sampled cells match the CSV.
  - Dictionary and methods PDFs archived with checksums.
- **Variables:** `BENES_OM_CNT`, `TOT_MDCR_STDZD_PYMT_PC`, `IP_CVRD_STAYS_PER_1000_BENES`, `ER_VISITS_PER_1000_BENES` (CMS term "Emergency Room"), and `ACUTE_HOSP_READMSN_PCT`. The readmission denominator is index admissions discharged alive.
  - `_PCT` fields are 0–1, verified from methods tables: female 54.6% ↔ `0.546`, OM count 27,732,177. Values are stored as published and multiplied by 100 only for display.
  - The suppression code is `*` (<11). The earlier inventory note about "." was not supported and was corrected.
  - **Documentation conflict:** the methods paper mentions health-status adjustment; the catalog says standardization does not adjust for health status. CHIP never labels the measure risk- or inflation-adjusted.
- **Geography:**
  - Matched 52 states (50, DC, PR) and 3,143 counties (CT planning regions already in source); the national row is reference only.
  - Excluded: VI state and 3 VI counties (no CHIP boundary), the `Territory` and `ZZ` state aggregates, and 51 `XX000` unknown-county rows.
  - DC county 11001 and 78 PR municipios have no CMS county row and show "not published". No unexplained mismatches.
  - Suppressed matched-county values per measure: 2/2/13/3/146. Six true-zero county readmission rates.
- **Changes:**
  - Registry `cms_om_gv.json`; modules `cms_gv.py`, `cms_gv_cli.py`, `cms_gv_api.py`; router dispatch.
  - Additive migration `b7e3c5a9d2f4` (`stage_cms_gv`, `observation_cms_gv`, immutability triggers).
  - Frontend `/area/cms-gv`: state below zoom 6, counties from zoom 6, an explicit no-tract message, a national reference line, and distinct status swatches. Main-map selector: a new entry plus the legacy option relabelled "legacy import, through 2023".
  - Tests; operator guide `backend/docs/chip_cms_om_geographic_variation.md`; inventory row `cms-original-medicare-gv` updated in place (still 97 records); handbook.
- **State-changing commands:**
  - `alembic upgrade head` (`a4d9e7c2b6f1` → `b7e3c5a9d2f4`).
  - `cms_gv_cli fetch-stage-validate` twice: ready candidate `73d93c74-7d59-4723-a862-25ecf7a6bc92` (12/12 checks), then a duplicate.
  - `review`, then `approve-publish` at 21:47:59Z (semantic `1b5e4e68…5800`, schema `48209de5…325b`, metadata `25a54bab…9fc1`).
  - Pointer drill: `deactivate`, a refused rollback to the AQI release, then `rollback 73d93c74…`. All nine pointers were rechecked.
  - Webroot backed up to `data/deploy-recovery/cms-om-gv-20261114/webroot-before/`, then `rsync -a --delete frontend/dist/ /var/www/places/`.
  - `sudo -n systemctl restart places-backend` at 21:48:25Z.
  - Three temporary demo codes (ids 19–21, `agent-verification-cms-gv-20261114`) were created and deactivated, each used once; no plaintext was printed or stored.
- **Verification:**
  - Backend: 16 unit tests and 1 isolated PostGIS lifecycle test covering idempotency, same-label revision hold and release, failed and unexplained candidates, pointer isolation, rollback, immutability, and API parity. 153/153 focused area and CMS tests passed. Full suite: 618 passed, 1 failed (the known `test_all_six_real_source_years_match_acceptance_totals`).
  - Frontend: 139/139; the build passed with the existing chunk-size warning.
  - Review re-derived all 15,980 observations; an independent CSV-to-DB check of 50 cells had 0 mismatches. An update to a published row was refused.
  - Authenticated Nginx browser check: 88/88. It covered all five measures at both levels, legacy CMS selector and routes, the HRSA, TRI, and nursing-home overlays, six shared catalogs, and the 390-pixel layout. Funding map/legend returned 200, and anonymous CMS GV routes returned 401.
  - Benchmarks: national states 0.55–0.61 s; national counties 3.1–4.3 s / 1.8 MB, comparable to the AQI national county view at 3.1 s; local county views 16–18 ms.
- **Git/next action:** Committed on new branch `claude/cms-geographic-variation` (from `ed42254`) and pushed to `origin` without force; the push outcome is recorded in the next entry. Not merged to `main`. Next: decide on merging the stacked branches, add GV to a fresh recovery set, and decide on legacy CMS retirement separately.

## 2026-11-14T20:39:45+00:00 — CMS nursing-home integration commit and push (Codex)

- **Objective/outcome:** Complete the requested Git handoff for the CMS nursing-home integration documented below. Commit `115733d` includes application, migration, tests, source inventory, operator guide, handbook, and diary; pushed to `origin/claude/epa-tri-facilities` without force. No new application, database, or deployment changes were made in this handoff step.
- **Verification/next action:** Staged diff passed `git diff --cached --check`; the push succeeded. This diary outcome entry follows that commit and will be pushed separately. The published release and deployed service are unchanged. Future refreshes remain manual with reviewed checksums; merging the branch is a separate decision.

## 2026-11-14T20:37:30+00:00 — CMS Nursing Home Provider Information integrated, published, and deployed (Codex)

- **Objective:** Add CMS nursing homes as an independent optional point overlay with certified beds, four published star ratings, facility characteristics, filters, accessible table/detail, and source limitations. No geographic averages, vacancy estimates, inspections, penalties, staffing-hour measures, timer, backups policy, access controls, or funding methodology changed.
- **Official source:** CMS Provider Information dataset 4pq5-n9py; metadata identifies the complete October 2026 CSV, released 2026-10-28 with processing/modified date 2026-10-01. Archived 9,218,563-byte CSV SHA-256 ab70309ae6f0ee86b19fe9acb61a6d2953f970d3b09e80bb9b090e4b19ce35a2, metadata JSON, CMS API count, and October 2026 dictionary PDF. The PDF defines CCN as six-character text and one row per nursing home. CCN is preserved with leading zeroes. Public access is recorded in CMS metadata.
- **Coverage and semantics:** 14,686 unique CCNs across 50 states, DC, Puerto Rico (9), and Guam (1). 13,878 points mapped; 808 CMS footnote-22 ZIP-based coordinates retained but excluded. There are 91 colocated mapped coordinate groups. Overall/health inspection/staffing/QM missing ratings: 126/126/203/198, with CMS footnotes retained; 11 certified-bed values missing. Stars remain 1–5 or unrated, never zero or averaged. The processing date is not a common observation year; certified beds do not imply vacancy. SSA county code is not treated as Census FIPS.
- **Changes:** Registry cms_nursing_homes.json; source, CLI, and read API modules; additive migration a4d9e7c2b6f1 with staged raw rows, typed point rows, indexes, and published immutability triggers; route include; NursingHomes.jsx, area-map integration, CSS, tests, source-inventory child record (97 records now), CMS operator guide, and handbook. The independent active release pointer is cms_nursing_home_provider_info.
- **Publication:** Migration applied. Candidate 13e56c1b-320f-4217-8955-8bb813055216 passed six checks, full four-archive/raw/read-model review, and checksum-bound publication at 20:11:30Z. Semantic/schema/metadata/keyset SHA-256 respectively: fa4830eddcf4b5923058aa134b1bd27f54ea3301b7e64304a156bde4cb20c765 / 20436b3a028cdb5150065366040fe53c6a6c8487e1e4a302ae3e88e4736cca52 / e635990727468df71b3b96f07312f3e13bda95c4cfd75fe29c12fb560b1dfe72 / 556beb0dc75aa275a5ef9be4b8a3a648ba2873c081da89b5f79efb8d1baa0e9b. Re-fetch recorded a duplicate. A live deactivate/rollback drill restored the exact eight pointers; cross-product rollback and published-row mutation were refused.
- **Tests:** Focused backend suite 84/84 including isolated PostGIS idempotency, same-label semantic and metadata holds, failed-candidate preservation, and pointer recovery. Full frontend suite 136/136, including rapid-filter debounce regression. Production build passed with the existing bundle-size warning. Git diff check passed. Authenticated Nginx browser verified rated and unrated details, all five attributes, footnotes, Care Compare link, ownership/provider/overall filters, cluster click to points, keyboard table detail and focus, rapid overlay switching, 390-pixel layout, and no page errors. CMS map/table parity: unrated national 118; NYC points 589; filtered Los Angeles 35. High-zoom national request returned 413. Anonymous CMS routes returned 401. Existing five area catalogs, HRSA/TRI catalogs and maps, PLACES map, and funding map/legend returned 200 on unchanged pointers. Warm local CMS national clusters: 67 ms, 8.5 KB; Los Angeles points: 34 ms, 318 KB.
- **Deployment and fixes:** Backed up the previous webroot to data/deploy-recovery/cms-nursing-homes-20261114/webroot-before, installed the build under /var/www/places, and restarted places-backend. The initial restart without sudo failed for interactive authentication; sudo noninteractive restart succeeded. Browser inspection exposed a collapsed wide table; fixed panel scrolling and redeployed. A rapid 14-checkbox sequence then temporarily exhausted the backend database pool and caused 500s; added 400 ms filter debounce and explicit CMS API session close, redeployed, and restarted. The repeated sequence sent two map requests total, resolved to 4,223 filtered facilities and 50 table rows, and left health at 200 with no new pool errors. Temporary demo verification codes were deactivated; no credentials were committed.
- **Git/next action:** Intended code and documentation commit and push are pending at this entry. After push, record its outcome. On the next CMS release, refresh manually with the operator guide; keep auto-publish off and review any hold before moving this product's pointer.

## 2026-11-14T19:16:00+00:00 — EPA TRI reporting-facility point overlay integrated, published, and deployed (Claude)

- **Agent/objective:** Claude implemented CHIP's second point layer, EPA Toxics Release Inventory reporting facilities with reported chemicals, reusing the HRSA point-layer framework. The Codex sibling worktree (`codex/ahrf-county-five-measures`) was not touched.
- **Source/year/status:**
  - EPA TRI basic data file, national, **reporting year 2024**; the page states forms "processed as of November 5, 2025" (page last updated 2026-01-28).
  - The RY2025 URL returned HTTP 404. EPA's preliminary-dataset page also calls 2024 the most current year.
  - Treated as the latest complete annual basic file, subject to EPA revision, and **not** the frozen National Analysis dataset.
  - CSV SHA-256 `06dfa3a6…1506` (60,550,684 bytes); retrieved 19:01:48Z.
  - The documentation PDF is the August 2024 edition ("Updated for RY 2023"); the RY2024 header was reviewed exactly.
- **Grain and findings:**
  - 77,295 forms (unique `DOC_CTRL_NUM`; 68,567 Form R, 8,728 Form A) and 21,482 facilities (TRIFD).
  - 562 chemical IDs and 76,381 facility-chemical relationships. 637 pairs have more than one form; these are distinct submissions, and all are kept.
  - Facility attributes conflict for 0 facilities. Industry sector is form-level (41 multi-sector facilities), so facilities carry a set of sectors.
  - 15 chemical IDs have more than one published name; all names are kept.
  - All facilities are mapped (6-decimal FRS coordinates). `HORIZONTAL DATUM` is blank on every row, so the coordinates are drawn as EPSG:4326 without transformation.
  - Boundary checks: 2 points lie outside the reported state (FL/GA and KS/MO state lines) and 19 lie in island areas outside the CHIP layer. All stay mapped, with the derived county stored separately.
  - 213 colocated coordinate groups (472 facilities) are kept distinct.
  - No revision or withdrawal flag exists in the file; refresh change reports count forms that are no longer present.
- **Changes:**
  - Registry `epa_tri_facilities.json`; modules `tri.py`, `tri_cli.py`, `tri_api.py`; one router include in `main.py`.
  - Additive migration `f2c8d4a6b1e3` (`stage_tri_report`, `tri_report`, `tri_chemical`, `tri_facility`, `tri_facility_chemical`, with immutability triggers).
  - Frontend `TriFacilities.jsx`, wired into `Places2025Pilot.jsx`. The HRSA and TRI panels now stack in a shared `.pilot-overlays` column.
  - Tests; operator guide `backend/docs/chip_epa_tri_facilities.md`; inventory row `epa-tri-facilities` updated in place (still 96 records); handbook.
- **State-changing commands:**
  - `alembic upgrade head` (`e9b3f6a2c4d8` → `f2c8d4a6b1e3`).
  - `tri_cli fetch-stage-validate` twice: candidate `3b6ecfb1-bf58-4122-a71f-432027994bd7` ready with 11/11 checks, then a duplicate run.
  - `review`, then `approve-publish` at 19:03:10Z (semantic `b0d831fc…f0ae`, schema `5a37e707…e143`, metadata `71b6ea27…a77`).
  - Pointer drill: `deactivate`, then a refused rollback to the HRSA release, then `rollback 3b6ecfb1…`.
  - Webroot backed up to `data/deploy-recovery/tri-facilities-20261114/`, then `rsync -a --delete frontend/dist/ /var/www/places/` three times (two layout fixes); the final webroot matches the build by SHA-256.
  - `sudo -n systemctl restart places-backend` at 19:04:11Z.
  - For verification: six temporary demo access codes (label `agent-verification-tri-20261114`, 2 uses, 30-minute expiry; 6 runs, three of which stopped at the marker-click step before the script fix), each deactivated by the script in a `finally` block. A DB check confirmed all 6 are inactive with one use each. The plaintext was never printed or stored.
- **Verification:**
  - Backend: 21 unit tests and 7 PostGIS integration tests (scratch DB `chip_tri_facilities_test`, created and dropped by the tests). They cover multi-form pairs, revision and withdrawal holds, colocated facilities, coordinate conflicts, missing locations, chemical and sector filters, cluster and table parity, caps and 413s, publication isolation, failed candidates, authentication, and tamper detection.
  - Full backend suite: 595 passed, 1 failed (the known `test_all_six_real_source_years_match_acceptance_totals`).
  - Frontend: 133/133 tests (7 new: chemical filter, sector filter, keyboard detail, stale responses during rapid switching, release mismatch, simultaneous overlays). The build succeeds with the existing chunk-size warning.
  - `review` re-verified 3 archives and every staged and read-model row plus the geometries. An independent raw-CSV comparison matched for 3 facilities.
  - Benchmarks: national clusters 88 ms in-process (95–110 ms through Nginx), urban points ≤3 ms (Houston 323, Chicago 449), rural ≤10 ms. Details are in the guide.
  - Anonymous requests to all `/api/area/tri/*` routes return 401.
- **Authenticated browser check (real session through Nginx, 23/23):**
  - Clusters, then points, then a marker detail with the FRS link and no area popup.
  - Keyboard detail focus.
  - TRI and HRSA shown together.
  - Ethylene-oxide filter (no HRSA refetch).
  - Rapid sector switching.
  - Measure switching that refetches only the area map.
  - `/area/epa-aqi` and `/area/acs-2024` with both overlays.
  - All area catalogs and the HRSA catalog on unchanged pointers.
  - Funding map and legend returning 200.
  - No page errors; mobile without horizontal scroll.
  - Two layout bugs found by screenshot were fixed: an open panel collapsed and spilled below the map, and a long detail label squeezed the values.
- **Not done / limits:**
  - No release quantities, totals, toxicity, risk, aggregates, distance zones, historical years, or enforcement joins (deferred by design).
  - HRSA marker detail and HRSA filters were not exercised in the authenticated run.
  - On narrow screens the overlay column overlaps the open area table, as the HRSA toggle did before this change.
  - The timer and backup configuration were not changed. TRI is not in the recovery set.
- **Git:** committed on new branch `claude/epa-tri-facilities`, created from `claude/hrsa-health-center-sites` (`9666f71`) because the deployed tree contains both overlays. Pushed to `origin` without force. `main` contains neither. Raw source files, archives, and the webroot backup (`data/`) are gitignored and not committed.
- **Next action:** an operator decides whether to merge the HRSA and TRI branches into `main`, then refreshes the recovery set to include the site and TRI tables.

## 2026-11-14T18:21:16+00:00 — HRSA health center site point overlay integrated, published, and deployed (Claude)

- **Objective:** CHIP's first point layer: HRSA Health Center Service Delivery and Look-Alike Sites as an optional overlay on the area maps. The Codex sibling worktree was not touched.
- **Source:** HRSA BPHC/Data Warehouse HCSD CSV plus metadata XLSX. Usage limitations: "None"; refreshed daily.
  - Snapshot 2026-11-14, from `Data Warehouse Record Create Date`; retrieval was 18:07Z.
  - CSV SHA-256 `08b01537…a436`.
  - CMS FQHC ownership records and UDS organization-level data were not used.
- **Product rules:**
  - Key: `BPHC Assigned Number` (19,616 unique site IDs). Organizations (1,593 health center numbers) are attributes and are never merged with sites.
  - Default filter: Active service-delivery sites, so administrative-only sites are opt-in.
  - Location statuses: 19,200 mapped (19,186 inside their published county; 14 island-area points without a CHIP boundary).
  - Excluded from the map: 14 domestic-violence locations (suppressed by HRSA policy; no coordinates, address, or phone kept in the read model), 363 rows with no coordinates, 38 shared place-level geocodes (AS, FM, MH, PW), and 1 coarse coordinate.
  - Colocated sites are retained (up to 15 at one point).
  - The "Site Added to Scope" date is marked Restricted in HRSA metadata and is never exposed.
- **Changes:**
  - Registry `hrsa_hc_sites.json`; modules `hrsa_sites.py`, `hrsa_sites_cli.py`, `hrsa_sites_api.py`; one router include in `main.py`.
  - Additive migration `e9b3f6a2c4d8` (`stage_hrsa_site`, `site_hrsa` with PostGIS points, GiST index, constraints, and the published-immutability trigger).
  - Frontend `HealthCenterSites.jsx`, wired into `Places2025Pilot.jsx` and CSS.
  - Tests; operator guide `backend/docs/chip_hrsa_health_center_sites.md`; inventory record 96; handbook.
- **State-changing commands:**
  - `alembic upgrade head` (`d3a7e5c1b9f2` → `e9b3f6a2c4d8`).
  - `fetch-stage-validate` three times:
    - Run 1 was held (`38f71065…`) because my new Content-Length check misread a gzip-encoded page. This was a code bug, fixed; the held row is kept.
    - Run 2 produced `e5cdea05-6518-454c-9418-353410c2309d`, ready with all 8 checks passing.
    - Run 3 was recorded as a duplicate.
  - `review`, then `approve-publish e5cdea05…` (semantic `31859595…b90a`, schema `2096dab1…e0ab`, metadata `2cb368bf…48d2f9`).
  - Pointer drill: `deactivate`, then a refused cross-product rollback, then `rollback e5cdea05…`.
  - Webroot backed up to `data/deploy-recovery/hrsa-sites-20261114/`, then `rsync -a --delete frontend/dist/ /var/www/places/` (repeated twice for a layout fix), then `systemctl restart places-backend`.
- **Verification:**
  - Backend: 23 unit tests, plus 7 PostGIS integration tests in a scratch DB (`chip_hrsa_sites_test`, created and dropped by the tests). The full suite had 567 passed and 1 failed; the failure is the known `test_all_six_real_source_years_match_acceptance_totals`.
  - Frontend: 126/126 tests (7 new); build OK with the existing bundle-size warning.
  - Review rechecked 4 archives and all 19,616 rows, plus 19,200 geometries to 1e-9.
  - Map and table totals were equal in 8 benchmark views:

    | View | Result | Time |
    | --- | --- | --- |
    | National clusters | 53 clusters | ~70–90 ms, ~10 KB |
    | Los Angeles, zoom 11 | 347 points | ≤15 ms, ~200 KB |
    | NYC, zoom 9 | 543 points | ~300 KB |
    | Rural views | points | ≤4 ms |

  - Through Nginx, all site routes return 401 anonymously, and published site rows reject writes.
  - Area regression: all five area catalogs resolve unchanged pointers, and an AQI map read returns 200.
  - Funding regression: public map and legend return 200 through Nginx. The map took 25.8 s cold after the restart and 4.9 s warm. Four funding v1 routes return 200 in-process.
- **Browser check:** headless Chromium loaded the deployed bundle against a loopback-only verification backend (live DB, gate off, port 8765, stopped). It covered:
  - Clusters, then points, and colocated lists.
  - Marker clicks without area popups, while polygon popups still work in every mode.
  - Keyboard detail from the table.
  - Filters.
  - Measure switching with no site refetch.
  - Persistence across PLACES, EPA AQI, and ACS.
  - A layout fix so the site panel no longer covers the legend on desktop; it starts collapsed on mobile.
- **Not done:**
  - No authenticated real-session browser check: creating a temporary demo access code was denied by the session permission policy.
  - Timer, backups, access controls, funding code, and other facility datasets were not changed.
- **Git:** committed on new branch `claude/hrsa-health-center-sites` (based on `e35aee2`) and pushed to `origin` without force; `main` is unchanged. The deployed webroot and backend correspond to this branch's tree. Raw source files and archives (`data/`) are gitignored and not committed.
- **Next action:** an operator runs an authenticated browser check of the overlay on `/area/places-2025` and `/area/epa-aqi`, then refreshes the recovery set to include the site tables.

## 2026-11-14T17:45:20+00:00 — EPA AQI branch merged to main (Claude)

- **Outcome:** At the user's request, local `main` was fast-forwarded from `d45fed6` to `a17cf77` (branch `claude/epa-aqi-county-2025`) and pushed to `origin/main` without force. `origin/main` had not moved since the branch was created. This entry and the handbook Git-status line are a follow-up documentation commit. They correct the earlier entry's statement that `main` was unchanged.
- **Deployment:** No new deployment, data, pointer, or service change. The deployed webroot and backend already correspond to this code.

## 2026-11-14T16:55:41+00:00 — EPA AirData annual county AQI integrated, published, and deployed (Claude)

- **Agent/objective:** Claude implemented the EPA AirData annual AQI-by-county product in the shared area pipeline, as assigned. Codex's sibling worktree (`codex/ahrf-county-five-measures`) was not touched.
- **Source/year:** `annual_aqi_by_county_2025.zip` (EPA build 2026-06-25; ZIP SHA-256 `72b022b3…7130`) is the latest completed calendar year. The partial 2026 file was skipped. Definitions come from EPA's About AirData Reports page.
- **Measures:** five published fields: Median, 90th percentile, and Max AQI; Days with AQI; Good days. Days with AQI is stored on every observation row. Nothing is derived, and no CI or MOE is invented.
- **Identifiers:** the file has names only. GEOIDs come from EPA's site-listing State+County codes and are cross-checked against TIGER 2024 names by documented rules, with 8 reviewed spelling variants. No fuzzy matching is used.
- **Coverage:** 985 source rows; 975 mapped. 10 excluded with reasons: 8 legacy Connecticut counties not forced onto planning regions, Sonora (Mexico), and USVI St. John. 2,247 of 3,222 boundary counties are shown as `no_reported_value` at read time; no rows are stored for them. Eight beyond-scale maxima (>500) are kept and flagged.
- **Changes:**
  - Registry `epa_aqi_county_2025.json`; modules `epa_aqi.py`, `epa_aqi_cli.py`, and `epa_aqi_api.py`.
  - Additive migration `d3a7e5c1b9f2`.
  - Narrow branches in the shared `router.py`.
  - Frontend `/area/epa-aqi`, with a neutral legend (no daily health-category colors), Days with AQI in popups and the table, visible limitations, and selector entries.
  - Tests; operator guide `backend/docs/chip_epa_aqi_county_2025.md`; inventory row 44; handbook.
- **State-changing commands:**
  - `alembic upgrade head` (`c9f76d3a51e2` → `d3a7e5c1b9f2`).
  - `epa_aqi_cli fetch-stage-validate` twice: the first run was ready with all six checks passing; the second was a duplicate.
  - `review` and `approve-publish 70e78172-da21-4782-91e2-d3b97896863f` (semantic `d29d432f…da54`, schema `e753e547…577e`, metadata `c71d063d…fd17`).
  - Pointer drill: `deactivate`, then `rollback` to the same release. A cross-product rollback was refused.
  - Webroot backed up to `data/deploy-recovery/epa-aqi-20261114/`, then `rsync -a --delete frontend/dist/ /var/www/places/`.
  - `systemctl restart places-backend`.
- **Verification:**
  - New AQI tests: 29 backend and 2 frontend.
  - Focused backend suite: 308 passed, 1 failed. The failure is `test_all_six_real_source_years_match_acceptance_totals`, a FY2026 CDC account-summary natural-key change in local data. It fails identically on pre-task `d45fed6`, so it is pre-existing and unrelated.
  - Frontend: 119/119 tests; production build OK (existing bundle-size warning).
  - Review re-hashed 20 archived files and matched all 4,875 observations; spot checks matched the raw CSV.
  - In-process API checks against the live release covered all five measures in four viewports with map, table, and legend parity. The national view returned 3,109 counties in ~1.6 MB in ~3.1 s. Tract and 2026 requests returned 400.
  - Through Nginx, the anonymous catalog returned 401. PLACES, ACS, AHRF, and CLH reads and three funding v1 reads returned 200, with pointers unchanged. Published AQI rows reject writes.
- **Not done:** no authenticated browser check. Creating a temporary demo access code was denied by the session's permission policy. The timer, backups, access controls, funding methodology, and legacy integrations were not changed.
- **Discrepancies found:**
  - The deployed webroot before this task matched neither `89fc4d8` nor `d45fed6` byte-for-byte; it was built from the pre-commit tree. This deploy therefore also shipped the committed `main` funding and demo-access code.
  - `frontend/src/config/apiBase.js` is git-ignored, so a clean checkout cannot build.
  - Nginx `/health` serves the SPA; use `/api/health`.
  - The handbook's "72-row" inventory is 95 records.
- **Git:** committed on new branch `claude/epa-aqi-county-2025`, based on `d45fed6`, and pushed to `origin` without force. `main` is unchanged; merging is a separate decision. The deployed webroot and backend correspond to this branch's tree.
- **Next action:** an operator with access performs the authenticated browser check of `/area/epa-aqi`, covering Baltimore city (data), a CT planning region (no value), and Mayagüez (exception). Then refresh the recovery set.

## 2026-11-14T16:30:31+00:00 — Main branch push completed

- **Objective/outcome:** All 30 nonignored pending paths were committed as `23b79c6` on `claude/improvements`. Local `main` fast-forwarded from `b1a0eba` to `23b79c6`; `git push origin main` succeeded without force. The push carried the branch's 14 commits beyond the former `origin/main`, including earlier CHIP work and the new consolidated commit. The existing sibling AHRF branch was not merged: its AHRF source and guide files matched the integrated versions, while its history lacked the later CLH work.
- **Verification:** The staged diff passed `git diff --check` and a scan of staged files found no private-key or token patterns. Focused backend tests passed 50/50 after the import-path correction, frontend tests passed 117/117, production frontend build passed with a bundle-size warning, and Bash/Python syntax plus PowerPoint archive integrity passed. No full backend suite, deployed browser check, data publication, migration, service restart, or production deployment was performed.
- **Files and next action:** Main now contains the funding trend/API/UI changes, demo startup fix, dossier and recovery scripts, presentation, agent notes, and project documentation. Git ignores source data, caches, environments, and generated frontend assets; they were not forced into version control. This entry and the handbook branch-status correction are the final documentation follow-up. A fresh AHRF/CLH-inclusive recovery set and off-host copy remain outstanding.

## 2026-11-14T16:28:50+00:00 — Consolidate approved work onto main

- **Objective/outcome:** User approved committing all pending work and asked for the current branch to become `main` and be pushed. `origin/main` is an ancestor of `claude/improvements`, so a fast-forward is available; commit and push remain pending at this entry's creation.
- **Changes reviewed for commit:** CDC funding API outlay trends and frontend redesign/tests, demo-access session handling and demo startup readiness check, recipient dossier/subawardee report scripts, local recovery helpers, a hypothetical CHIP use-case deck and notes, Claude orientation, and the prior uncommitted diary entry. Updated this handbook for the new code and recovery-helper status. Dataset pointers, migrations, services, timers, storage, and deployed assets were not changed by this task.
- **Verification:** Read the branch and remote history after `git fetch origin`; `origin/main` had zero commits outside current `HEAD`. Focused backend tests passed 50/50 with `PYTHONPATH=. .venv/bin/python -m pytest`; the first direct `.venv/bin/pytest` invocation failed collection because `app` was not on its import path. Frontend tests passed 117/117 and `npm run build` succeeded with a bundle-size warning. Bash syntax, Python compilation, and PowerPoint ZIP integrity checks passed. No data import or destructive recovery command was run. Full backend suite and deployed browser verification were not run.
- **Publication/next action:** Commit all nonignored work, fast-forward local `main`, push `origin/main` without force, then record the final branch and push result. The older local recovery set still predates AHRF/CLH and requires a new isolated restore plus independent copy.

## 2026-11-14T16:24:34+00:00 — Claude Code orientation alongside Codex

- **Objective/outcome:** Read-only orientation for Claude Code. No application code, data, migration, pointer, service, or deployment change. Added root `CLAUDE.md`, which imports `@AGENTS.md` (none existed before), and this entry; both are uncommitted.
- **Verified state:** Host `chip-app`, user `john`, repo `/home/john/places-app`, branch `claude/improvements` at `0b9372b`, level with `origin/claude/improvements`. Uncommitted funding/demo-access edits, `backend/scripts/chip_recovery/`, three other untracked scripts, `backend/docs/chip_phase1_next_codex_prompt.md`, and `deliverables/` were left untouched. Only root `AGENTS.md` exists in-repo; no nested instruction files. Codex app-server was running; Codex also uses its global `~/.codex/AGENTS.md`, which matches this workflow. `places-backend`, Nginx, and `chip-area-refresh.timer` were active.
- **Discrepancy:** Sibling worktree `/home/john/places-app-ahrf-push` holds `codex/ahrf-county-five-measures` (`ec6dddd`). Its two commits are not ancestors of `HEAD`, but AHRF code is on this branch through `89fc4d8`. Treat that branch as superseded unless someone confirms otherwise. This is unverified at the content level.
- **Next action:** Unchanged from the handbook priorities. Commit `CLAUDE.md` with the next authorized documentation commit.

## 2026-11-14T16:11:48+00:00 — Documentation publication handoff

- **Objective/outcome:** Committed the handbook, diary, root `AGENTS.md`, and three supporting operator documents as `0b03cc8`; pushed `claude/improvements` to `origin` successfully without force. The push also carried four pre-existing local commits already ahead of the branch upstream. This follow-up diary record is a separate documentation-only change.
- **Verification:** `git diff --cached --check` passed before the first commit; all handbook and supporting-document local links resolved, and documented Python command targets existed. The push reported `5b4dcda..0b03cc8`. No application tests, deployment, data import, migration, pointer change, or service restart occurred for the documentation task.
- **Next action:** Push this diary follow-up entry, then inspect final branch/working-tree status. A new recovery set and off-host copy, CLH source retry, and the untracked recovery helpers remain separate work.

## 2026-11-14T16:07:50+00:00 — Central documentation and agent workflow

- **Objective/outcome:** Created the canonical handbook and this diary, plus root `AGENTS.md` task-start and handoff rules. No application code, data, release pointer, service, timer, or deployed asset was changed for this request.
- **Files and decisions:** `docs/PROJECT_HANDBOOK.md` records current architecture, per-integration inventory, shared versus legacy/funding boundaries, commands, decisions, and gaps. `docs/PROJECT_DIARY.md` starts the evidence-backed history. `AGENTS.md` requires future agents to read and maintain them. Existing untracked audit, pipeline-plan, and local-recovery guides were included so handbook references resolve in Git; the maintained broader source inventory remains `backend/docs/chip_source_inventory.csv`.
- **Verification:** Inspected repository manifests, registries, migrations, routes, operator guides, and git state. Read-only `area_pilot` queries showed four independent published pointers and DB revision `c9f76d3a51e2`; budget, federal-account, and TAGGS table counts were also read. `app.area_pilot.operations status` showed PLACES/ACS content checks current; `systemctl` showed backend, Nginx, and weekly area timer active/enabled. Local and Nginx health returned 200; anonymous area catalog returned 401. All local Markdown links and documented command target files resolved; the four shared CLI `--help` entry points succeeded. Bare `python` was unavailable in the host shell, so subsequent checks used `python3` or `backend/.venv/bin/python`; a pre-existing `requests` dependency warning appeared. No full ingestion, migration, build, or test suite was run because this is a documentation-only change.
- **Deployment/publication:** No deployment or data publication. Commit and push are pending at this entry's creation.
- **Issue/next action:** Earlier local recovery set predates active AHRF/CLH releases and must be refreshed and copied off-host. Its helper scripts are untracked and unavailable from a clean remote checkout. CLH source re-fetch had held HTTP 202 responses per its guide. Review the staged documentation diff, then commit only intended documentation and push without force. Preserve unrelated working-tree changes.

## 2026-11-14T15:55:10+00:00 — CLH integration milestone (Git evidence)

- **Objective/outcome:** Commit `89fc4d8` adds curated AHRQ CLH to the shared area pipeline. The [CLH guide](../backend/docs/chip_clh_2023_curated.md) reports checksum-bound publication and deployment on November 14, with authenticated browser/API checks and a supervised pointer recovery; the author-time timestamp here is from Git, not the deployment time.
- **Files/data:** `backend/app/area_pilot/clh*`, the CLH registry/migration, shared area routes and UI, and five curated indicators from September 2025 v2.0 files. Live read-only DB inspection at this diary's creation found active CLH release `168ec07d-c7ef-4e46-b01a-ec72c00c3d88` and three held CLH candidates.
- **Issue/next action:** The guide records empty HTTP 202 responses on repeat source fetch; replay of archived workbooks matched published content. Recheck source availability before a new candidate. Existing weekly timer does not include CLH.

## 2026-11-13T23:46:15.861150+00:00 — Shared area releases (ACS publication time from live DB)

- **Objective/outcome:** [PLACES](../backend/docs/chip_places_2025_pilot.md) and [ACS](../backend/docs/chip_acs5_2024_phase3.md) guides report published/deployed releases, release-pinned map/legend/table parity, authenticated browser checks, and pointer recovery. Live DB publication times were 2026-11-13T23:14:56.930499+00:00 for combined PLACES and the heading timestamp for ACS. The [operations guide](../backend/docs/chip_area_phase4_operations.md) records a weekly PLACES/ACS verification timer and supervised full-content checks completed early November 14. These are historical actions, not operations performed for this diary.
- **Files/data:** `area_pilot` releases, 2023/2020 PLACES-compatible boundaries, isolated 2024 ACS boundaries, raw archives, API and React area page. Live pointers were rechecked on November 14; see handbook for current values.
- **Issue/next action:** No automatic publication. Source endpoint/schema drift and archive growth need operator review. The [local recovery guide](../backend/docs/chip_current_recovery_set.md) reports an isolated restore of a pre-AHRF/CLH snapshot; its proposed nightly schedule has not been commissioned.

## 2026-08-22T21:21:41+00:00 — Funding trend code milestone (Git evidence)

- **Objective/outcome:** Commit `ad3a667` added CDC funding trend analysis. Earlier commits `a3de3b1` and `e309a0d` on July 27 added summary outlay backfill and restored the all-account overview; `04efb55` on July 3 added the v1 funding map model. This summary establishes code history only; corresponding deployment dates and full data validation were not reconstructed here.
- **Files/data:** [CDC funding API guide](../backend/docs/cdc_funding_api_v1.md), [source ingestion guide](../backend/docs/cdc_funding_source_ingestion.md), funding database/schema and frontend funding pages. Later uncommitted funding edits were present at this diary's creation and remain outside this documentation task.

## 2026-04-24T14:31:30+00:00 — Demo access and funding base (Git evidence)

- **Objective/outcome:** Commit `ec97672` added demo access and budget-grounded funding; `9b71dd1` later that day added USAspending federal-account ingestion. March 2026 commits introduced CMS, USDA, FEMA, CDC funding, and model components. Dates are commit author times; ingestion/publication completeness for those legacy products is described cautiously in the [November 13 audit](../backend/docs/chip_federal_data_current_state_audit.md).
- **Files/data:** [access middleware](../backend/app/demo_access/middleware.py), funding and legacy importers, migrations, and [scripts guide](../backend/scripts/README.md). The shared area release system did not apply to these earlier integrations.
