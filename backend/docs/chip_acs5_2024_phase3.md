# ACS 2020–2024 median household income: Phase 3 operator guide

This release publishes one [2020–2024 ACS 5-year Detailed Tables](https://www.census.gov/programs-surveys/acs/news/data-releases/2024/release.html) measure, B19013_001E, from the [official Census API](https://api.census.gov/data/2024/acs/acs5). The observation period is **January 1, 2020–December 31, 2024**, the published income values are **2024 inflation-adjusted dollars**, and the universe is **households**. The measure is median household income in the past 12 months. B19013_001M is the corresponding margin of error, with B19013_001EA and B19013_001MA as annotation fields. The Census Bureau publishes ACS MOEs at **90% confidence**; these are not PLACES 95% intervals. No state or county value is derived from smaller geographies, and the aggregation policy is `none`.

The Census [2024 geography documentation](https://www.census.gov/programs-surveys/acs/geography-acs/geography-boundaries-by-year/2024.html) dates state and county boundaries to January 1, 2024 and census tracts to the 2020 Census, with updates for legal-area changes. This release uses isolated TIGER/Line 2024 state, county, and state-partitioned tract shapefiles. It does not change legacy boundary tables. Connecticut uses nine planning regions as county equivalents. Puerto Rico is published at all three levels. American Samoa, Guam, Northern Mariana Islands, and U.S. Virgin Islands are unsupported by this ACS product and have no fabricated observations.

Official [annotation notes](https://www.census.gov/data/developers/data-sets/acs-1year/notes-on-acs-estimate-and-annotation-values.html) explain the negative numeric sentinels and their annotation strings. The parser stores unavailable estimates as null while preserving annotation and status. A numeric zero remains distinct. A published open-ended median (for example `250,000+`) retains its raw numeric code, receives `open_ended` status, and displays the annotation rather than an exact dollar value. A valid estimate with annotated unavailable MOE remains publishable. The UI does not calculate confidence intervals.

## Secure key and supervised commands

Put the Census API key as one line in `/home/john/.config/places/census-api-key` with directory mode `700` and file mode `600`. The CLI can alternatively read `CENSUS_API_KEY` or a file named by `CENSUS_API_KEY_FILE`. Do not place the key in the repository. The client removes it from archived request URLs and error messages. Query strings in the database contain only `get`, `for`, and `in` parameters.

From `backend/`:

```bash
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m app.area_pilot.acs_cli load-boundaries
.venv/bin/python -m app.area_pilot.acs_cli fetch-stage-validate
.venv/bin/python -m app.area_pilot.acs_cli review CANDIDATE_UUID
.venv/bin/python -m app.area_pilot.acs_cli approve-publish CANDIDATE_UUID \
  --semantic-sha256 REVIEWED_SEMANTIC_SHA \
  --schema-sha256 REVIEWED_SCHEMA_SHA \
  --metadata-sha256 REVIEWED_METADATA_SHA
.venv/bin/python -m app.area_pilot.acs_cli rollback RETAINED_ACS_PUBLISHED_RELEASE_UUID
.venv/bin/python -m app.area_pilot.acs_cli deactivate
```

`fetch-stage-validate` checks that no newer ACS 5-year endpoint exists, verifies official B19013 definitions and geography metadata, retrieves state estimates and each state's county and tract estimates, validates every response header and key, checks all 52 state partitions, and compares all source keys to isolated boundaries. It preserves raw response bytes, SHA-256, redacted URL, role, size, and time. The semantic digest is over all returned records sorted by level and GEOID. Pre/post source metadata are checked, but Census does not provide a transactional snapshot across API partitions; an unannounced edit and reversion between checks could escape detection. A changed source with the same release label becomes a distinct candidate. Repeated equal content is recorded as a duplicate run. A filesystem lock serializes CLI actions and the database advisory lock serializes dataset pointer changes.

The first release requires the exact candidate review and three reviewed SHA-256 values. The approval transaction rechecks archived bytes, staged values, observations, checks, and candidate identity before setting the ACS active pointer. It cannot change the PLACES pointer. A failed or held candidate leaves active data intact. Rollback switches only the ACS pointer to another retained published ACS release. `deactivate` hides a first release while preserving its data and provenance.

## Verified candidate and coverage

Candidate `c1baba8e-ad3d-409f-b390-d312dbf19686` was retrieved on November 13, 2026. The official 2024 ACS 5-year product remained the latest released 5-year product; `/data/2025/acs/acs5.json` returned 404 during preflight. The source includes 52 state equivalents, including DC and Puerto Rico; 3,222 counties; and 85,382 tracts, for 88,656 observations. Puerto Rico contributes one state, 78 municipios, and 981 tracts. The isolated TIGER 2024 tables contain 52 states, 3,222 counties, and 85,396 tracts. All **88,656 source geographies** join their matching boundary; no unmatched source geographies were waived. Fourteen Suffolk County, New York TIGER tracts have no source row in the B19013 API and remain unfilled. Their exact GEOIDs are pinned in the registry and checked at review. Connecticut has nine planning-region county rows.

Status counts: states 52 available; counties 3,221 available and one missing (`35011`, estimate annotation `-`, MOE annotation `**`); tracts 83,266 available, 1,554 missing, and 562 open-ended. The review verified 163 archived files and all 88,656 staged-observation pairs. Validation checks for source stability, metadata, partition coverage, boundary archive, source-boundary joins, and annotation parsing all passed.

Reviewed digests:

```text
semantic c064954713e6549e895f8c25b26a85e1a6c7f25ea3314dd51a367c96f77e2746
schema   3eb478bde94f4830afa0cce4b6b57531505ae0984c94dd647b0aa87cd6ed04c9
metadata ee3d58db5dd8dc1ed8d53bd2d88eec9565b6399f965b8aabc94a84cb50c59727
keyset   aada4065ac8fea5dfc8ef6aa40b093a1683aecf825d13de413444fca652422e6
```

The area map, legend, and table share the exact dataset, measure, period, universe, value type, geography, bbox, and release selection. National states (52), Atlanta counties (42), Atlanta tracts (838), and a rural Wyoming tract viewport (9) matched across all three API read models, including values, MOEs, and statuses. A national tract viewport returned the expected HTTP 413 cap. Direct local processing benchmarks, excluding network and browser rendering, were: national states 22 ms cap check plus 545 ms geometry/response (72,186 JSON bytes); Atlanta counties 13 + 51 ms (20,132 bytes); Atlanta tracts 8 + 113 ms (430,313 bytes); Wyoming tracts 2 + 23 ms (24,830 bytes).

## Publication and deployment, November 13, 2026

The reviewed candidate was published as ACS release `c1baba8e-ad3d-409f-b390-d312dbf19686`. An identical full rerun returned that candidate as a semantic duplicate and created no new observation release. The repeated run added a second set of 163 raw-file provenance records; approval reverified them. Alembic head is `e32ac2024b19`. The frontend was built and copied to `/var/www/places/`, and `places-backend` was restarted. Nginx and systemd configuration files were unchanged. The previous frontend is retained at `data/deploy-recovery/acs-phase3-20261113/webroot/`.

The final focused backend run passed 37 tests across ACS, PLACES, demo access, and CDC funding. The full frontend run passed 115 tests in 14 files, and the production build succeeded. Authenticated Nginx requests returned 200 for the ACS catalog, map, legend, and table with one release ID and matching state count; a nationwide tract request returned 413 and an anonymous ACS request returned 401. Existing PLACES, SVI, FEMA, ACS non-medical-factor, and CDC funding read routes returned 200. The PLACES pointer remained `f735c524-3fd4-4848-bfe3-1049cbc514dd`.

Authenticated Chromium showed state → county → tract transitions with the same ACS release and 2020–2024 period, household universe, value type, and 2024 dollar units. It then switched to PLACES and back to ACS without changing either dataset's release. No page errors were recorded. Browser fetch timings through local Nginx, including network transfer and browser text decoding but excluding map rendering, were 562 ms for 52 national states, 74 ms for 42 Atlanta counties, 177 ms for 838 Atlanta tracts, and 42 ms for nine rural Wyoming tracts. The national state map was also measured as 758 ms through a full browser page load with 72,035 decoded bytes. These timings are distinct from the direct server timings above.

The first-release recovery path was exercised: `deactivate` removed only the ACS pointer, and `rollback c1baba8e-ad3d-409f-b390-d312dbf19686` restored it. The PLACES pointer stayed unchanged throughout. A temporary access code used for browser verification was disabled and its local plaintext file removed.

## Recovery

The ACS dataset pointer is independent of `cdc_places_county_2025_pilot`. For a first release, run `deactivate` above to hide ACS without touching PLACES. For a later ACS release, run `rollback` with the retained ACS release UUID. For application recovery, verify exact recovery contents and destination as described in [the Phase 4 operations guide](chip_area_phase4_operations.md); pointer recovery needs no frontend synchronization. Keep the additive migration and source archives for diagnosis.

Exact first-release rollback commands, from the repository root:

```bash
cd /home/john/places-app/backend
.venv/bin/python -m app.area_pilot.acs_cli deactivate
cd /home/john/places-app
# Inspect the exact saved webroot and current destination before any application restore.
test -f /home/john/places-app/data/deploy-recovery/acs-phase3-20261113/webroot/index.html
test -d /home/john/places-app/data/deploy-recovery/acs-phase3-20261113/webroot/assets
```

To restore the reviewed ACS release after deactivation:

```bash
cd /home/john/places-app/backend
.venv/bin/python -m app.area_pilot.acs_cli rollback c1baba8e-ad3d-409f-b390-d312dbf19686
```
