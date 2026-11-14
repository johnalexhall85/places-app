# USDA ERS Food Environment Atlas, July 2025 release (five county measures)

Shared area product `usda_ers_food_environment_atlas`, page `/area/usda-fea`. It has its own release pointer and is independent of the legacy `usda_food_env.*` import (see [Relationship to the legacy integration](#relationship-to-the-legacy-integration)). This product is the county-oriented **Food Environment Atlas**. It is not the tract-level Food Access Research Atlas (`usda_food_access.*`, inventory rows `usda-lram-2019` and `usda-sram-2025`).

Code: [registry](../app/area_pilot/registry/usda_fea_2025.json), [source module](../app/area_pilot/usda_fea.py), [CLI](../app/area_pilot/usda_fea_cli.py), [read API](../app/area_pilot/usda_fea_api.py), and [migration `c8f1e4a7d3b6`](../alembic/versions/c8f1e4a7d3b6_add_usda_fea_area.py). Tests: [unit](../tests/test_area_usda_fea.py) and [PostGIS lifecycle](../tests/test_area_usda_fea_postgis.py).

## Release versus observation periods

- **Data release:** the "July 2025" release. The downloads page lists the "Current Version" CSV ZIP (`/media/5570/food-environment-atlas-csv-files.zip?v=40916`) as "Last Updated 7/30/2025". `ReadMeFile2025.txt` says "The original release date of this file is July 2025", and the ZIP member timestamps are 2025-07-30.
- **Page revisions are not data releases.** On 2026-11-14 the landing page said "Updated: 8/12/2026" and the documentation page "Updated: 7/28/2026". No newer data file was linked. Each run checks the current link and its Last Updated date. Any change holds the candidate (`USDA FEA current CSV release changed`) until the registry is reviewed.
- **Observation periods differ by measure.** No measure is labelled with the release year:

| Measure ID | USDA variable | Observation | Unit | Denominator |
| --- | --- | --- | --- | --- |
| `low_income_low_access_pct` | `PCT_LACCESS_LOWI19` | 2019 | % of **total** county population | All residents (2010 Census block population); the numerator is low-income residents only |
| `snap_stores_per_1000` | `SNAPSPTH23` | 2023 | stores per 1,000 residents | County residents (Census population estimates); stores are a monthly average |
| `wic_stores_per_1000` | `WICSPTH22` | 2022 | stores per 1,000 residents | County population |
| `farmers_markets_per_1000` | `FMRKTPTH18` | 2018 | markets per 1,000 residents | County residents |
| `no_car_low_access_households_pct` | `PCT_LACCESS_HHNV19` | 2019 | % of county housing units | All housing units (USDA's label says "households"; its definition says housing units) |

Definitions, contributing sources, and interpretation notes are in the registry and shown on the page. Highlights:
- **Low access.** Distance to a supermarket or large grocery store: SNAP-authorized stores merged with NielsenIQ TDLinx, with at least $2 million in sales and all major food departments. Low income means family income at or below 200% of the poverty threshold, using 2014–18 ACS income. The no-car measure uses a single 1-mile distance for every county.
- **SNAP.** USDA FNS store authorizations, excluding meal service providers. All retailer types count, including convenience stores.
- **WIC.** USDA FNS store authorizations. Mississippi direct-distribution centers are not stores.
- **Farmers' markets.** The AMS National Farmers Market Directory, which is voluntary and self-reported. Zero means no market was listed.

The page never calls limited-access areas "food deserts", never equates retailer presence with diet quality, and states that these are historical indicators, not a current store directory.

## Measure selection and substitution

| Target | Decision |
| --- | --- |
| Low-income population with limited store access | `PCT_LACCESS_LOWI19` |
| SNAP-authorized retailers | `SNAPSPTH23` |
| WIC-authorized retailers | `WICSPTH22` |
| Farmers' markets | `FMRKTPTH18` |
| Grocery-store availability | **Substituted** by `PCT_LACCESS_HHNV19`. `GROCPTH20` (County Business Patterns 2020, NAICS 445110, per 1,000) duplicates the published AHRQ CLH measure `CCBP_SOGS_RATE`, which uses the same CBP NAICS 445110 per-1,000 concept and is newer (2023). In this file 909 of 3,144 counties are `-9999` for 2020, and `GROC20` has no zeros, so the gaps cannot be read as zero. |

**Not used.** `DSPTH20` is labelled "Dollar stores" in the variable list, but USDA's documentation defines it as all NAICS 452319 general merchandise stores. State-level `*` variables, such as `PCT_SNAP22` and `FOODINSEC_21_23`, are repeated on every county row and are not county values.

Only directly published rates are used. No rate is recalculated, and no percent-change variable is shown.

## Missingness and status

| USDA value | Stored status | Meaning |
| --- | --- | --- |
| number > 0 | `available` | Published value, stored exactly (`numeric`) with the original text |
| `0` | `true_zero` | Published zero |
| `-9999`, `N/A`, blank | `not_available` | Not available, not applicable, or suppressed |
| `-8888` | `did_not_exist` | County did not exist in the referenced year |
| *(no USDA row)* | `boundary_not_comparable` | Connecticut planning region (09110–09190) for the 2019, 2022, and 2023 measures. Read time only. |
| *(no USDA row)* | `not_covered` | Puerto Rico (outside the Atlas). Read time only. |

Values outside a measure's plausible range (0–100 for percentages, 0–50 for per-1,000 rates) and any undocumented text hold the candidate. Map, legend, and table give zero and every non-numeric status a distinct colour and text.

## Geography and boundaries

USDA documentation says county boundaries are applied at 5-year intervals (2010, 2015, and 2020 Census updates), plus 2023 Connecticut planning regions where the source data provide them. CHIP stores FIPS as text and joins it exactly to TIGER/Line 2024 county GEOIDs (`area_pilot.acs_boundary_2024`). It never reassigns, splits, or merges counties.

**Connecticut.** The 2019, 2022, and 2023 values exist only for the eight former counties (09001–09015). SNAP 2023 and WIC 2022 are `-9999` there anyway. These rows are staged as `legacy_ct_county_no_compatible_2024_boundary`, and the nine planning regions read `boundary_not_comparable`. For farmers' markets 2018, the former counties carry values and are also staged as exceptions. USDA lists the planning regions as `-8888`, which CHIP shows as `did_not_exist`.

**Alaska and other changes.**
- Valdez-Cordova (02261) is `-8888` for the 2019–2023 measures.
- For 2018, Valdez-Cordova has a value that cannot be placed on the 2024 boundaries, because the area was split into Chugach (02063) and Copper River (02066). Those two are `-8888` for 2018.
- For 2019, Chugach and Copper River are `-9999`, with the value note `valdez_cordova_split_no_data`, per USDA documentation.
- For 2018, the old codes 02270 (Wade Hampton), 46113 (Shannon), and 51515 (Bedford city) are `-8888` and staged as exceptions. Five FIPS-less Alaska agricultural "Area" rows (`N/A`) are also `-8888`.

**Coverage per measure.**
- Matched counties: 3,135 for four measures and 3,144 for farmers' markets.
- Boundary counties without a USDA row: 78 in Puerto Rico, plus the 9 Connecticut planning regions for four measures.
- Any other unmatched source row or boundary county holds the candidate as `geography_mismatch`.

**No state or tract values.** The July 2025 files contain no state rows. The selected variables are not marked as State-level (`*`), and the XLSX has no state sheet. The API rejects `geography=state` and `geography=tract` with 400. The page shows counties at every zoom: "State values are not published for this measure; counties are shown at the national view." At tract zoom it says no tract values exist. Counties are never averaged or summed.

## Validation (7 checks; any failure holds)

1. `source_totals`: 957,753 rows and 304 variables.
2. `variable_lookup_matches_registry`: the exact variable name (including the year), category, subcategory, and units; no `*`.
3. `values_and_sentinels_documented`.
4. `unique_geography_measure_keys`.
5. `boundary_join_explained`.
6. `documented_exceptions_present`: every registry exception is present with its expected sentinel.
7. `row_accounting`.

Retrieval also verifies:
- the current CSV link and its Last Updated date;
- 15 exact documentation sentences (definitions, denominators, sentinel codes, and boundary rules) from the downloads and documentation pages;
- the readme sentinel and State-level notes;
- the exact ZIP member list.

The ZIP is extracted safely: no absolute paths, `..`, subdirectories, symlinks, or encryption; per-member, total-size, and compression-ratio caps; temporary files; and a disk guard. Downloads are bounded (32 MB ZIP, 4 MB pages) with 3 retries. The CSV is streamed with a row cap.

**Checksums.**
- **Raw:** a SHA-256 for every archived file.
- **Semantic:** the selected variables' rows (FIPS or name key, state, county, value) plus their variable-lookup rows.
- **Schema:** headers, sentinels, measure definitions, and documentation phrases.
- **Metadata:** release markers, URLs, boundary rules, exceptions, and the mapping digest.
- **Keyset.**

**Revisions.** Identical content records a duplicate run. Changed content under the same release label is held as `same_label_semantic_revision` until `release-reviewed-hold`. A change elsewhere in the 957,753-row file that leaves the selected rows unchanged still fails `source_totals` if the row or variable count changes.

## Storage and API

**Tables.**
- `area_pilot.stage_usda_fea`: every source row of the five variables, including exceptions with their reason.
- `area_pilot.observation_usda_fea`: matched counties only. It keeps the source text, the value, the status, a value note, and the USDA name.

Both have the published-immutability trigger. Neither table touches the legacy schema.

**API.** `/api/area/{catalog,map,legend,table}?dataset_id=usda_ers_food_environment_atlas…`, through the shared router. It has the same 5,000-county viewport cap (413), a 500-row table cap, explicit release, measure, period, and population, and the demo-access gate (anonymous 401). Map and table list every 2024 boundary county in view. The frontend reuses the shared response cache keyed by release and selection, request cancellation, and the stale-response guard.

## Relationship to the legacy integration

**What the legacy import does.** `app/usda_food_env/ingest.py` upserts all 304 variables of the same July 2025 files into `usda_food_env.{variable_lookup,county_values,state_values,dataset_meta}`, with no release pointer. Its "state" rows copy State-level `*` variables from county rows. Its missing-token list (`-9999`, `-8888`, `N/A`) merges "did not exist" with "not available".

**Status.** The legacy importer was **not run** for this work, and its tables, `/api/usda/food-environment/*` routes, and main-map option are unchanged. The only change is the option label, now "USDA Food Environment (legacy import, all variables)". A new main-map option links to `/area/usda-fea`. All 15,684 selected values in the shared release equal the legacy raw values, so both read the same file.

Retiring the legacy integration is a separate decision.

## Manual operations (from `backend/`)

```bash
.venv/bin/python -m app.area_pilot.usda_fea_cli fetch-stage-validate          # candidate + report (prints digests)
.venv/bin/python -m app.area_pilot.usda_fea_cli review <candidate_id>         # re-hash archive, re-derive every observation
.venv/bin/python -m app.area_pilot.usda_fea_cli approve-publish <candidate_id> \
  --semantic-sha256 <…> --schema-sha256 <…> --metadata-sha256 <…>            # checksum-bound; moves only this pointer
.venv/bin/python -m app.area_pilot.usda_fea_cli release-reviewed-hold <candidate_id> \
  --semantic-sha256 <…> --schema-sha256 <…> --metadata-sha256 <…> --operator-note "<why>"   # same-label revisions only
.venv/bin/python -m app.area_pilot.usda_fea_cli rollback <published_release_id>
.venv/bin/python -m app.area_pilot.usda_fea_cli deactivate                    # hides this product only
```

- **Schedule and size.** The product is not on the weekly timer and `auto_publish` is false. Each fetch archives about 47 MB under `data/ingest/usda_food_environment_atlas/<run>/`: three HTML pages, the 6.5 MB ZIP, and the 40 MB extracted CSV, variable list, and readme. A run takes about 3 s.
- **When ERS posts a new release,** retrieval holds with "current CSV release changed". Before staging:
  1. Review the new variable list and documentation.
  2. Choose the latest observation for each target.
  3. Update the registry: variables, periods, release markers, row and variable totals, exceptions, and legend breaks.
  4. Update the tests.

## 2026-11-14 publication and deployment (Claude)

**Migration and candidate.**
- Migration `b7e3c5a9d2f4` → `c8f1e4a7d3b6` was applied.
- Candidate `28a4824f-d403-454b-bc85-998fdd64bf92` passed 7/7 checks in 3.4 s: 15,737 staged rows and 15,684 observations.
- A second fetch recorded a duplicate.

**Archive** (SHA-256):

| File | Size (bytes) | SHA-256 |
| --- | --- | --- |
| ZIP | 6,501,079 | `99750f549a3dd84222934dae77767724968a86b36f2cf15b3985bb6f0e863b8d` |
| `StateAndCountyData.csv` | 39,831,292 | `03aa52c9b2069dabab9e03467ad59df5811c5710d78bc2d589dc573fa1feefcd` |
| `VariableList.csv` | — | `3844f6a0c6b5d914f49665f36a712c89f47891419eb35b3f4fe5d466f54ce59f` |
| Readme | — | `04fc08acebfa0dd05a60dbbf13bd2e7b555f168a4d2c340299e85ddf16f2dece` |

**Status counts for matched counties:**

| Measure | Available | True zero | Not available | Did not exist |
| --- | --- | --- | --- | --- |
| Low-income & low access | 3,094 | 39 | 2 | — |
| SNAP | 3,114 | — | 21 | — |
| WIC | 3,028 | — | 107 | — |
| Farmers' markets | 2,259 | 872 | 2 | 11 |
| No-car & low access | 3,121 | 12 | 2 | — |

**Review.**
- `review` verified the 14 archive files from both runs and re-derived every observation.
- An independent check of 54 cells (50 random plus 4 sentinel and zero cases) had 0 mismatches against both the CSV and the separate XLSX workbook.
- All 15,684 values equal the legacy raw values.

**Publication.** Published at 2026-11-14T22:28:55Z with these digests:
- semantic `d15804aa59b971ee7eac941a733d617c98fb1bdbea46a98988d09c5e65523343`
- schema `23b4ddb152195aa24ecabfaaa9553680f3809361e71f9f36dc6bef499e8c56d9`
- metadata `8972238900339e876726169947b127f93f37e691da7744bd48059cbd22b68ed6`
- keyset `fda5a05652c5012cfbdc5c2e3ba82306ba989de23c861d80de4a9d489af8a4d3`

**Pointer drill.** `deactivate`, then a refused rollback to the CMS GV release, then `rollback 28a4824f…`. All ten pointers were identical before and after, and an update to a published row was refused.

**Deployment.**
- Webroot backed up to `data/deploy-recovery/usda-fea-20261114/webroot-before/`, then `rsync -a --delete frontend/dist/ /var/www/places/`.
- `sudo -n systemctl restart places-backend` at 22:29:13Z.
- Anonymous `/api/area/*` requests for this dataset return 401 through Nginx.

**Benchmarks** (in-process router, warm, median of 3):

| View | Map | Legend | Table |
| --- | --- | --- | --- |
| National desktop viewport (3,206 counties) | 3.3 s, 1.8 MB | 0.18–0.20 s | 0.12 s |
| Chicago, rural Kansas, Connecticut | 15–37 ms | — | — |

These national timings are comparable to the CMS GV and EPA AQI national county views.

**Authenticated browser check: pending.** The scripted check (temporary demo code, deactivated afterwards) was blocked by this session's permission policy because it needed the backend secrets to mint a code. An operator should open `/area/usda-fea` with a demo session and check:
- all five measures, with their period text and county map;
- the national-view message;
- the zoom-in tract message;
- the CT, PR, and Alaska statuses;
- a county popup;
- overlay toggles;
- a 390-pixel layout.
