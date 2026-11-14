# CMS Nursing Home Provider Information point overlay

This is an optional facility overlay on every CHIP area map. It has its own registry, staged raw rows, typed point table, release pointer, and manual review. It does not populate area observations or alter the legacy CMS Geographic Variation and Shared Savings Program integrations.

## Official source and scope

Verified 2026-11-14 UTC from the CMS Provider Data Catalog:

| Item | Reviewed value |
| --- | --- |
| Dataset | Provider Information, identifier 4pq5-n9py; https://data.cms.gov/provider-data/dataset/4pq5-n9py |
| Machine metadata | https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items/4pq5-n9py |
| Full source | The metadata distribution downloadURL, currently https://data.cms.gov/provider-data/sites/default/files/resources/0970c657767e40f8521187d02ba8d0ed_1792181744/NH_ProviderInfo_Oct2026.csv |
| Dictionary | https://data.cms.gov/provider-data/sites/default/files/data_dictionaries/nursing_home/NH_Data_Dictionary.pdf, updated October 2026 |
| Access | CMS metadata marks the dataset public. No API key or additional use restriction is stated. CMS is credited in the product. |
| Source dates | Modified/processing date 2026-10-01; released 2026-10-28; planned update 2026-12-02. Retrieval time is separately recorded for every archived file. |
| Archived complete CSV | 9,218,563 bytes; SHA-256 ab70309ae6f0ee86b19fe9acb61a6d2953f970d3b09e80bb9b090e4b19ce35a2. The CMS API count also returned 14,686. |

The ingest follows the official complete CSV distribution named by current machine metadata. The API is used only for an independent row count; it is not paginated for records. The CSV has 102 columns and 14,686 rows in this release. The dictionary says one row per nursing home. The six-character CMS Certification Number is stored as text, including leading zeroes and valid letters. It identifies the published provider row, not necessarily every campus or physical building of an organization. Duplicate CCNs, including conflicting records, block staging.

The five numeric attributes are Number of Certified Beds (number of federally certified beds), Overall Rating, Health Inspection Rating, Staffing Rating, and QM Rating (quality measure rating). The four ratings are CMS published 1–5 star categories, never percentages or averages. A blank rating stays null and its separate CMS footnote code and explanation are retained; zero is invalid for a rating. Certified beds can be zero, but they do not say how many beds are vacant. No vacancies are calculated. The processing date means the date CMS retrieved data, not a shared observation year for every rating component. The Provider Information file does not publish a common rating observation period per facility; the dictionary points to a separate Nursing Home Data Collection Intervals file for some underlying staffing and quality measures. This integration does not join those measures or inspection histories.

Provider name, public address, provider type, ownership type, county name, published coordinates, geocoding footnote, processing date, four rating footnotes, and certified beds are kept in the typed read model. The full 102-column source row remains in the immutable raw staging table and original archived CSV. The SSA county code is not treated as Census FIPS or used for a geography join.

## Location and rating limitations

Only valid decimal-degree latitude/longitude pairs with a blank CMS Geocoding Footnote are rendered as EPSG:4326 points. CMS footnote 22 says the street address could not be matched and the coordinates are based on the ZIP code. Those records are retained with location status zip_based_coordinate and excluded from the map, table, and detail endpoints for mapped facilities. Missing and invalid pairs have their own retained statuses. No address is geocoded and no ZIP or county centroid is substituted.

| Status | October 2026 rows |
| --- | ---: |
| Source | 14,686 |
| Mapped | 13,878 |
| ZIP based, excluded | 808 |
| Missing or invalid coordinates | 0 |

The source covers all 50 states, DC, Puerto Rico (9 rows), and Guam (1 row). There are 91 groups of distinct mapped CCNs at identical published coordinates; colocated facilities remain separate. The source has 126 unrated overall, 126 missing health inspection, 203 missing staffing, and 198 missing quality measure ratings. Eleven bed counts are missing. CMS footnotes 1, 2, 18, 20, 23, 24, and 25 explain the rating states seen in this release; geocoding footnote 22 explains excluded ZIP locations. Unrated is an explicit overall-rating filter. A missing rating never appears as zero stars.

The Care Compare detail URL uses the CCN and the official Medicare nursing-home detail route. The route was checked for CCN 015009 on 2026-11-14. Ratings are published CMS measures, not a guarantee of individual care or a live assessment. There is no CHIP recommendation, geographic rating average, derived statistic, vacancy estimate, inspection history, penalty, staffing-hour measure, or clinical outcome in this product.

## Storage, API, and controls

Registry: ../app/area_pilot/registry/cms_nursing_homes.json. Modules: cms_nursing_homes.py, cms_nursing_homes_cli.py, cms_nursing_homes_api.py. Additive migration a4d9e7c2b6f1 adds area_pilot.stage_cms_nursing_home and area_pilot.cms_nursing_home, with a mapped-only PostGIS point, spatial/filter indexes, and published-release immutability triggers. The existing release, run, source_file, validation, and active_release tables supply shared publication controls. The auto_publish setting is false; the weekly timer does not run this product.

The protected routes are /api/area/nursing-homes/catalog, map, table, and detail. Map and table take the same explicit published release_id, bbox, provider_type, ownership, and overall filters. Detail takes the CCN plus the same selection. At zoom 8 or higher and at most 2,000 facilities, map returns all individual points; otherwise it returns 64-pixel grid clusters whose counts must equal the table total. More than 3,000 clusters returns 413. The table paginates at no more than 200 rows per request; the UI uses 50. The overlay is off by default and independently selectable from area maps and HRSA/TRI; it uses its own bounded cache, request cancellation, a 400 ms filter debounce, and stale-response checks. Nursing-home endpoints close database sessions before response serialization. The table offers keyboard Details buttons, the detail heading receives focus, stars have accessible text, and marker color is described with symbols and text.

Each fetch archives metadata JSON, API count JSON, dictionary PDF, and the full CSV under data/ingest/cms_nursing_home_provider_info/RUN_ID. Downloads use temporary files, bounded retries, timeouts, byte caps, and a disk-space guard. Raw SHA-256 evidence is stored in source_file. Semantic SHA-256 hashes all 102 source fields sorted by CCN; keyset, reviewed schema/dictionary, and metadata/location hashes are separate. Review re-hashes every archive, reparses every row, and compares staging, typed values, and geometry. An unchanged re-fetch is recorded as a duplicate. Any semantic, schema, or metadata change under the same processing-date label is held for explicit review. More than 10% of CCNs added, removed, or changed versus the active release is also held. Failed candidates never move the active pointer.

## Operations

Run from backend/ with the backend virtual environment:

    .venv/bin/alembic current
    .venv/bin/alembic upgrade head
    .venv/bin/python -m app.area_pilot.cms_nursing_homes_cli fetch-stage-validate
    .venv/bin/python -m app.area_pilot.cms_nursing_homes_cli review CANDIDATE_ID
    .venv/bin/python -m app.area_pilot.cms_nursing_homes_cli approve-publish CANDIDATE_ID --semantic-sha256 SEMANTIC --schema-sha256 SCHEMA --metadata-sha256 METADATA

Before publishing, compare the review output and the candidate's count, dates, source URLs, footnotes, exclusions, and change report. Only after explaining a same-label or large-change hold, release it with the same reviewed checksums and a substantive note:

    .venv/bin/python -m app.area_pilot.cms_nursing_homes_cli release-reviewed-hold CANDIDATE_ID --semantic-sha256 SEMANTIC --schema-sha256 SCHEMA --metadata-sha256 METADATA --operator-note "Reviewed source change and explanation"

To restore an older retained published release or hide the overlay:

    .venv/bin/python -m app.area_pilot.cms_nursing_homes_cli rollback PUBLISHED_RELEASE_ID
    .venv/bin/python -m app.area_pilot.cms_nursing_homes_cli deactivate

The pointer actions affect only this product. Published rows remain queryable by release ID; archives are never deleted automatically. Application rollback restores the backed-up webroot and previous code, restarts places-backend, and leaves the additive migration in place. For a data-only issue, deactivate or roll back the pointer first. Do not downgrade the migration for routine rollback.

## 2026-11-14 publication

The published release is 13e56c1b-320f-4217-8955-8bb813055216, label NH Provider Information processed 2026-10-01. It passed six candidate checks and full archive/read-model review. A second fetch was recorded as a duplicate. Checksums:

| Digest | SHA-256 |
| --- | --- |
| Semantic | fa4830eddcf4b5923058aa134b1bd27f54ea3301b7e64304a156bde4cb20c765 |
| Schema | 20436b3a028cdb5150065366040fe53c6a6c8487e1e4a302ae3e88e4736cca52 |
| Metadata | e635990727468df71b3b96f07312f3e13bda95c4cfd75fe29c12fb560b1dfe72 |
| Keyset | 556beb0dc75aa275a5ef9be4b8a3a648ba2873c081da89b5f79efb8d1baa0e9b |

## Deployment and verification, 2026-11-14

- The current webroot was copied to data/deploy-recovery/cms-nursing-homes-20261114/webroot-before before installing the production build. The built assets and installed webroot match by directory diff. places-backend restarted at 20:19:53Z; health endpoints returned 200, and all four CMS routes returned 401 without a demo session.
- The authenticated browser run used a temporary one-use demo code, deactivated afterward. It verified broad clusters, cluster click and zoom to individual points, a rated detail, an unrated facility with CMS footnote 18, all five attributes, a CCN-specific Care Compare link, keyboard table Details and focus, provider/ownership and overall filters, rapid point-overlay switching, and three independent overlay panes. No page errors were observed.
- In the browser, the unrated national map and table each counted 118 mapped facilities. The 8 other unrated source rows were excluded by location quality. A New York City viewport returned 589 points, matching its table total. A filtered Los Angeles viewport returned 35 on both routes. An overwide high-zoom national request returned 413, not a truncated list. All five area catalogs, the HRSA and TRI catalogs, and funding map and legend returned 200 through Nginx on unchanged pointers. A PLACES area map, HRSA map, and TRI map each returned 200.
- Performance through local Nginx with an authenticated session: CMS national clusters 67 ms and 8.5 KB; Los Angeles points 34 ms and 318 KB; filtered Los Angeles 12 ms and 20 KB. These are warm local timings, not public-network service-level guarantees.
- A first browser run exposed a collapsed wide table inside the overlay panel; its scrolling was corrected and the build redeployed. A later rapid 14-checkbox filter sequence briefly exhausted the backend database pool and caused 500s. The filter debounce and early nursing-home API session close were added, then the build redeployed and the backend restarted. The repeated sequence sent two map requests total (initial and final), produced 4,223 filtered facilities in the browser with 50 table rows, no page errors, and a healthy backend afterward. The final desktop and 390-pixel mobile checks passed; mobile had no page-level horizontal scroll.
- Focused backend tests, including isolated PostGIS lifecycle checks, passed 84/84. Full frontend tests passed 136/136. Production build passed with the existing bundle-size warning. Re-review of the published archive passed after deployment. A live pointer drill deactivated and restored the CMS release; a cross-product rollback and a write to a published nursing-home row were refused. All eight active pointers matched their pre-drill values.

For application rollback on this host, first deactivate this product if necessary, restore the backed-up webroot from the path above to /var/www/places, check out the prior application commit in an isolated deployment workflow, and restart places-backend. The additive tables may remain in place. The user-facing release can be restored with the rollback command above when the compatible application version is running.
