# AHRQ CLH 2023 curated community conditions

The [AHRQ CLH download page](https://www.ahrq.gov/data/innovations/clh-data.html) identifies the **September 2025 v2.0 release** as the latest release, with files through 2023. The curated CHIP product is `ahrq_clh_2023_curated`. It is independent of the older AHRQ SDOH database and of existing PLACES, ACS income, AHRF, USDA, and funding integrations. The [2023 codebook](https://www.ahrq.gov/sites/default/files/wysiwyg/sdoh/clh_2023_codebook_2_0.xlsx) and [source documentation](https://www.ahrq.gov/sites/default/files/wysiwyg/data/clh/CLH-Data-Sources-Documentation-2025.pdf) support the definitions below. AHRQ distributes this compilation; Census Bureau products contribute the selected values.

| CLH variable and official label | CHIP label | Unit, universe, numerator / denominator | Actual observation period; contributing source | Available geography | Interpretation and overlap |
| --- | --- | --- | --- | --- | --- |
| `ACS_PCT_HH_BROADBAND_ANY`: Percentage of households with broadband of any type | Households with broadband of any type | Percent of all households; ACS B28002_004 / B28002_001 | 2019–2023 ACS five-year; Census Bureau | County, tract | Includes any broadband type, including cellular plans. Digital connectivity is not affordability or speed. Existing ACS income uses 2020–2024 B19013, so it is a different definition and period. |
| `ACS_PCT_HU_NO_VEH`: Percentage of housing units with no vehicle available | Occupied housing units without a vehicle | Percent of occupied housing units; ACS B25044_003 + B25044_010 / B25044_001 | 2019–2023 ACS five-year; Census Bureau | County, tract | Vehicle availability is a household condition, not individual mobility. |
| `ACS_PCT_RENTER_HU_COST_30PCT`: Percentage of renter-occupied housing units with rent equal to 30 percent or more of household income | Renter housing cost burden, at least 30% of income | Percent of renter-occupied units with computed ratio; ACS B25070_007 through B25070_010 / (B25070_001 minus B25070_011 not computed) | 2019–2023 ACS five-year; Census Bureau | County, tract | Excludes units where ratio is not computed. Not all household housing costs. |
| `CCBP_SOGS_RATE`: Total number of supermarkets and other grocery (except convenience) stores per 1,000 people | Supermarkets and grocery stores per 1,000 residents | Paid-employee NAICS 445110 establishments / county resident population × 1,000 | 2023 County Business Patterns and Census population estimate; Census Bureau | County only | Store density is a food-environment proxy; it does not measure distance, transport, price, or personal food access. Distinct from CHIP's older USDA food-environment releases. |
| `CCBP_FCRSC_RATE`: Total number of fitness centers and recreational sports centers per 1,000 people | Fitness and recreational sports centers per 1,000 residents | Paid-employee NAICS 713940 establishments / county resident population × 1,000 | 2023 County Business Patterns and Census population estimate; Census Bureau | County only | Facility density is an exercise-environment proxy; it omits parks, free opportunities, and individual access. |

The three ACS measures are 2019–2023 **five-year estimates** even though the workbook filename ends in 2023. CLH does not supply ACS margins of error. CCBP supplies no margins of error. No uncertainty field is synthesized. All selected cells are numeric or blank. Numeric zero is `true_zero`, blank is `missing`, and an unexpected token or formula holds ingestion. For CCBP since 2017, a blank can mean zero or fewer than three establishments because the source cannot distinguish them. CHIP never turns those blanks into zeros or claims suppression when the specific reason is unavailable. Source values are not rolled up to county or state.

The official workbooks have `Layout` and `Data` sheets. Their worksheet dimension advertises 1,048,576 rows, but the 2023 codebook documents 3,234 county and 85,433 tract source rows. The reader checks both sheets, selected headers, numeric types, formulas, GEOIDs, counts, codebook definitions, published codebook missingness, and ranges. It reads only selected cells in bounded memory. The first parse took 4.5 seconds for counties and 64.8 seconds for tracts, with about 95 MB peak RSS in the parser process; first ingestion completed in 85.61 seconds. A separate 40-cell readback across Alabama, California, Connecticut, Nebraska, and Puerto Rico matched archived source values to observations.

## Boundary coverage and exclusions

CLH 2023 source identifiers join exactly to the existing 2024 TIGER/Line county-equivalent and tract boundary tables. This preserves the established county-to-tract zoom behavior for the three supported measures. No legacy boundary layer is changed. The source has 3,234 county rows; 3,222 match current county polygons. The source has 85,433 tract rows; 85,396 match current tract polygons. Every current boundary has a source row at both levels.

Twelve county source records have no compatible polygon: eight retired Connecticut county codes (`09001`, `09003`, `09005`, `09007`, `09009`, `09011`, `09013`, `09015`) and four American Samoa county codes (`60010`, `60020`, `60030`, `60040`). The old Connecticut records are blank for all five selected measures; the nine current Connecticut planning-region source records join directly and have values. Thirty-seven source tracts in American Samoa (1), Guam (15), Northern Mariana Islands (5), and U.S. Virgin Islands (16) have no boundary in the existing 2024 table. All 49 excluded rows are retained in `area_pilot.stage_clh` with `boundary_status='source_only'` and `exclusion_reason='no_exact_2024_boundary'`. The registry pins their exact GEOIDs. An unexpected source-only or boundary-only mismatch holds a future candidate.

The published selection has 3,222 county observations for each of five measures (16,110 total), and 85,396 tract observations for each of three measures (256,188 total); 272,298 observations overall. `available`, `true_zero`, and `missing` counts after compatible boundary matching are:

| Measure | County available / zero / missing | Tract available / zero / missing |
| --- | ---: | ---: |
| `ACS_PCT_HH_BROADBAND_ANY` | 3,222 / 0 / 0 | 84,269 / 15 / 1,112 |
| `ACS_PCT_HU_NO_VEH` | 3,212 / 10 / 0 | 79,131 / 5,153 / 1,112 |
| `ACS_PCT_RENTER_HU_COST_30PCT` | 3,211 / 9 / 2 | 81,934 / 1,920 / 1,542 |
| `CCBP_SOGS_RATE` | 2,201 / 0 / 1,021 | Unavailable |
| `CCBP_FCRSC_RATE` | 1,314 / 0 / 1,908 | Unavailable |

The original 2023 county and tract files, codebook, source documentation, and landing page are archived under `data/ingest/clh_2023/<run-id>/` and recorded with retrieval timestamps, URLs, byte counts, and raw SHA-256 in `area_pilot.source_file`. These raw files are excluded from Git. The reviewed release has semantic SHA-256 `0b7fe44e9e44045042d24b6b8eddcf9deedeb1caaf2376a5ee07dfa36e3e8e63`, schema SHA-256 `5dbd510f963e0527f68047b850daad797e2ebff90ad875be210eca5782210eef`, metadata SHA-256 `46bd1345ff989b7aee60602d13411f6650713104db3bc91452d675a411a2d8b0`, and source-key SHA-256 `a158d8801acea656b6aa697d57514a1e1dff853192c9e3def9e86651bbc4a628`.

The raw SHA-256 digests of the reviewed files are: landing `31004db175b6914736067e523992ee4712522f9dbe92e7c3548d806ae2c71d6e`, codebook `c74b2e9ad85e20fd91c9e323113192f745c0f69fa53796c683e4646ba7963a9f`, documentation `94f955921455171f163b61aae5cc26f6fdf85e94651460c5d35e1353d7b7fa8d`, county `8807d69d57fec807e7bfe5f7f6f62bbae7354e78c6f3039d7f4e1717675241c7`, and tract `fd811c6fc9c723da7296c47d9749ef17c3d42c0750d1869b8faefb149f524c29`.

## Manual operations

From `backend/`, with the configured application database and adequate disk space:

```bash
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m app.area_pilot.clh_cli fetch-stage-validate
.venv/bin/python -m app.area_pilot.clh_cli review CANDIDATE_UUID
.venv/bin/python -m app.area_pilot.clh_cli approve-publish CANDIDATE_UUID --semantic-sha256 REVIEWED_SEMANTIC_SHA --schema-sha256 REVIEWED_SCHEMA_SHA --metadata-sha256 REVIEWED_METADATA_SHA
.venv/bin/python -m app.area_pilot.clh_cli deactivate
.venv/bin/python -m app.area_pilot.clh_cli rollback RETAINED_CLH_PUBLISHED_UUID
```

The `review` command hashes every original file, recomputes the staged semantic and keyset hashes, and compares every staged observation with its source cell, status, period, and universe. `approve-publish` reruns review inside the publication transaction and requires the three exact checksums. A held candidate cannot be published. Identical content records a duplicate run; changed content under the same label holds for a new review path and registry update. `deactivate` removes only the CLH active pointer; `rollback` accepts only a retained published CLH release. Neither action changes PLACES, ACS income, AHRF, or funding pointers.

`auto_publish` is false. CLH is not in the weekly area timer. A future scheduled refresh needs release discovery, full-file download and archive budgeting (about 160 MB per full check), a documented retention policy, and explicit authorization to add CLH to that timer. The current timer is unchanged.

## Source use

The [CLH Data Use Agreement](https://www.ahrq.gov/sites/default/files/wysiwyg/data/clh/CLH-Data-Sources-Documentation-2025.pdf) permits research, analysis, and aggregate statistical reporting, requires AHRQ CLH attribution, and prohibits attempting to identify people or establishments or publishing data that could identify establishments by inference. Keep raw files in the restricted archive; avoid bulk export or attempts to reconstruct establishment identities. CHIP displays only the five selected aggregate indicators, with AHRQ as distributor and Census as contributing publisher. Interpret CCBP blanks, ACS sampling uncertainty, and 2024 boundary joins as stated above.

## November 14, 2026 publication and deployment

Published CLH release **`168ec07d-c7ef-4e46-b01a-ec72c00c3d88`** passed all five staging gates and full checksum review of 88,667 staged source rows and 272,298 observations. The initial publication attempt failed inside a rolled-back transaction because streamed review left the SQL connection in server-cursor mode; the reviewer now resets that mode. No pointer changed on the failed attempt. The successful checksum-bound publish switched only the CLH pointer. PLACES, ACS income, and AHRF pointers remained `f735c524-3fd4-4848-bfe3-1049cbc514dd`, `c1baba8e-ad3d-409f-b390-d312dbf19686`, and `a034595f-45d3-46a0-90c9-c12c131d532a`.

The frontend was built and mirrored to `/var/www/places/`, with the previous webroot archived at `data/deploy-recovery/clh-20261114/webroot/`. `places-backend` was restarted, direct `/health` and Nginx `/api/health` returned 200, and unauthenticated area catalog access returned 401. An authenticated Chromium session selected all five measures and showed the correct periods and units. Broadband switched to tracts at the established zoom threshold; the county-only supermarket measure stayed at counties with an explanation. All observed area browser requests returned 200, with no page errors. The temporary verification code was deactivated afterward.

The focused backend area suite passed 39 tests, the area frontend suite passed 14 tests, and the production frontend build succeeded. National counties returned 3,222 features in 3,330 ms with a 1,620,641-byte map response. A Los Angeles viewport returned 2,074 tracts in 248 ms with a 911,086-byte map response; a rural Nebraska viewport returned six tracts in 14 ms with a 3,758-byte response. Map feature counts, legend status totals, and table totals agreed in all three viewports. Full table pages agreed with their corresponding map features. National tract requests hit the 5,000-feature cap with 413; unsupported county-only tract selection returned 400; PLACES, ACS income, AHRF, and funding authenticated read checks returned 200.

After publication, a fresh identical-content check could not complete because the AHRQ CloudFront endpoint returned empty HTTP 202 responses. Three attempted runs produced held audit records; the first retained its empty landing response as source evidence. The active release stayed intact. A fresh source fetch remains necessary when AHRQ serves the files again. Deterministic replay of the retained original workbooks matched the published semantic SHA-256 exactly in 70.6 seconds, peaking at 149 MB RSS in that replay process. The downloader now rejects zero-length and non-200 responses; it never interprets them as a new release. This source availability issue does not affect the published archive or map.

A supervised `deactivate` followed by `rollback 168ec07d-c7ef-4e46-b01a-ec72c00c3d88` restored the CLH pointer. The three other area product pointers were unchanged.

First-release pointer rollback:

```bash
cd /home/john/places-app/backend
.venv/bin/python -m app.area_pilot.clh_cli deactivate
```

Restore this reviewed publication:

```bash
cd /home/john/places-app/backend
.venv/bin/python -m app.area_pilot.clh_cli rollback 168ec07d-c7ef-4e46-b01a-ec72c00c3d88
```

To restore the previous frontend, mirror `data/deploy-recovery/clh-20261114/webroot/` back to `/var/www/places/` and restart `places-backend` after reverting the code. Keep the database migration and archived source evidence in place; neither pointer rollback nor webroot restoration requires destructive migration downgrade.
