# CMS Original Medicare Geographic Variation, 2024 (states and counties)

Operator guide for the `cms_om_geographic_variation` shared area product (registry [`cms_om_gv.json`](../app/area_pilot/registry/cms_om_gv.json)). Claude implemented and published it on 2026-11-14. Recheck live pointers before operating.

Scope: five published measures for observation year 2024. The age category is `All` (dictionary label "All Beneficiaries"). Values are CMS-published at state and county level, with the national row kept for reference. Other age groups, historical years, more measures, legacy retirement, and any geographic derivation are out of scope.

## Release versus observation year

| Item | Verified value (2026-11-14) |
| --- | --- |
| Landing page | https://data.cms.gov/summary-statistics-on-use-and-payments/medicare-geographic-comparisons/medicare-geographic-variation-by-national-state-county (JavaScript app; metadata read from the catalog) |
| Catalog record | `https://data.cms.gov/data.json`, series `6219697b-8f6c-4164-bed4-cd9317c58ebc`, title "Medicare Geographic Variation - by National, State & County : 2024-01-01", `modified` 2026-05-15, temporal 2024-01-01 to 2024-12-31, `accrualPeriodicity` annually, `accessLevel` public |
| CHIP release label | `OM GV PUF May 2026 update (2014-2024 CSV)`. The methods paper is titled "May 2026 Update" and says it "includes data for 2007-2024". |
| CSV | `2014-2024 Original Medicare Geographic Variation Public Use File.csv` (catalog URL under `/2026-04/cc600d1e-…/`); 57,865,948 bytes; HTTP Last-Modified 2026-04-29; SHA-256 `10c8304012da34da3ecfe4caf4548927095f693383814d0e79ce6711b6806fad`; 246 columns; 36,994 rows for 2014–2024. Years 2007–2013 are a separate historical ZIP and are not used. |
| Dictionary | `2014-2024 Original Medicare Geographic Variation Data Dictionary.pdf` (modified 2026-05-05), SHA-256 `75a8d4bef07d1900a50732c78a2aec688ba3ca132dad1dc6cab1a9243d55109f` |
| Methods paper | `Original Medicare Geographic Variation Public Use File Methods Paper.pdf` (2026-05-11), SHA-256 `e7c6ca8a3cb4cd761f44ee5d5e4ee78a379479a73cd93f69fb116c860a9944ca` |
| Observation year | 2024. This is the latest `YEAR` in the CSV and equals the catalog temporal end. The data API reported 0 rows for 2025. |
| Data API cross-check | `/data-api/v1/dataset/6219697b-…/data/stats`: 36,994 total and 3,253 for YEAR=2024, `BENE_AGE_LVL`=All, both equal to the CSV. Seven sampled cells (US, CA, PR, 06037, 09110, 02013, 48301) match the CSV exactly. |

The release (May 2026 update) and the observation year (2024) are different things. A future CMS update could revise 2024 values under a new or the same file. That is a revision of the same observation year, not a new year.

## Population and payment standardization

- **Population.** The study population is people with both Part A and Part B who are fully enrolled in Original Medicare (fee-for-service) for all entitled months. Medicare Advantage enrollees and people with only Part A or only Part B are excluded. The methods paper reports 27,732,177 OM beneficiaries in 2024, 39.0% of all Medicare beneficiaries. People who died during the year are included.
- **Ages.** `All` includes people under 65 who qualify through disability or ESRD and people 65 and older. Age-stratified rows (`<65`, `>=65`) exist for national and state levels only. They are counted during validation and never combined or stored.
- **Not all residents.** None of these measures describes all residents of an area, only people aged 65+, or Medicare Advantage enrollees.
- **Standardized payment.** The dictionary defines it as "adjusted for geographic differences in payment rates". The methods paper says CMS uses the MSPB standardization methodology and that Medicare pays different amounts for the same service in different areas, for example for local wages or input costs. The catalog description adds that extra payments such as direct and indirect medical education and disproportionate-share hospital payments are removed.
  - Values are nominal 2024 dollars, **not inflation-adjusted**.
  - **Documented conflict:** the methods paper contains the sentence "By standardizing payment amounts and adjusting for differences in beneficiaries' health status…". The CMS catalog states "Standardization does not adjust for differences in beneficiaries' health status." The file has no risk-score field, and the dictionary describes only geographic payment-rate adjustment.
  - CHIP therefore **does not label this measure health-risk-adjusted**. The conflict is recorded in the registry (`documentation_conflicts`) and in every release's metadata payload.

## Measures

| CHIP measure | CMS variable | Definition (dictionary, verbatim excerpt) | Denominator | Stored scale / display |
| --- | --- | --- | --- | --- |
| `om_beneficiaries` | `BENES_OM_CNT` | "Count of Medicare beneficiaries who were enrolled in Part A and Part B, as well as Original Medicare coverage for all Medicare entitled months…" | none (count) | integer count |
| `std_payment_per_capita` | `TOT_MDCR_STDZD_PYMT_PC` | "Actual per capita Original Medicare payment for beneficiaries, adjusted for geographic differences in payment rates." | OM beneficiaries (per capita) | US dollars, 2024 nominal; display rounded to whole dollars |
| `ip_stays_per_1000` | `IP_CVRD_STAYS_PER_1000_BENES` | "Number of Hospital Inpatient covered stays per 1,000 OM beneficiaries." | all OM beneficiaries, not only users | per 1,000 |
| `er_visits_per_1000` | `ER_VISITS_PER_1000_BENES` | "Number of inpatient or hospital outpatient Emergency Room (ER) visits per 1,000 OM beneficiaries." | all OM beneficiaries | per 1,000 |
| `readmission_rate` | `ACUTE_HOSP_READMSN_PCT` | "Percentage of inpatient readmissions within 30 days of an acute hospital stay during the reference period, regardless of whether the readmission was planned or unplanned." | acute admissions where the beneficiary was discharged alive (methods paper), **not beneficiaries** | stored 0–1 as published; display ×100 |

- **Emergency visits.** The request named "emergency department visits"; CMS publishes these as Emergency Room (ER) visits, and CHIP uses the CMS term. Both inpatient and outpatient ER visits are counted.
- **Inpatient.** Hospital inpatient covers IPPS, CAH, IPF, and other inpatient Part A services, counting Medicare-covered stays only.
- **Readmission.** The rate is all-cause and not risk-adjusted. It is not the Hospital Readmissions Reduction Program measure.
- **Percentage scale was verified, not guessed.** The national `All` row stores `BENE_FEML_PCT` = `0.546`, and methods Table 4 reports 54.6% female for 2024. `BENES_OM_CNT` = 27,732,177 equals methods Table 2. Both phrases are checked on every fetch (`percentage_scale_0_1`). CHIP stores the CMS value unchanged (national readmission `0.1807`) and shows 18.07%.

## Suppression and status

The dictionary note says: "All variables are suppressed where the count of beneficiaries or count of users is less than 11. Suppressed variables are marked with '*'." No other token is documented. The earlier inventory claim that "." means missing was not supported by the 2024 dictionary and was corrected.

| Status | Meaning | Stored |
| --- | --- | --- |
| `available` | Published number | value + source string |
| `true_zero` | Published `0` (6 county readmission rates: 31007, 38007, 46063, 48263, 48269, 48443) | value 0 |
| `suppressed` | CMS `*` | NULL value, source `*` |
| `missing` | Blank cell; none exist in 2024. A blank fails `suppression_and_missing_codes` and holds the candidate. | NULL |
| `not_published` | Boundary area with no CMS row at that level; read time only, never stored | — |

Any other token holds the candidate. Suppressed values are never estimated from totals or related fields.

Counts of 2024 suppressed values among matched counties (out of 3,143): beneficiaries 2, payment 2, IP stays 13, ER visits 3, readmission 146. The two fully suppressed matched counties include 48301 (Loving, TX). State values: none suppressed.

## Geography and coverage

The join is an exact FIPS join to TIGER/Line 2024 (`area_pilot.acs_boundary_2024`). CMS level codes are used as published (`National`, `State`, `County`), and leading zeros are preserved.

| Source (2024, All) | Rows | Outcome |
| --- | --- | --- |
| National | 1 | `national_reference` (geoid `US`); returned as `legend.national_reference`, never a map feature |
| State, FIPS | 53 | 52 matched (50 states, DC, PR); VI (78) excluded: `territory_outside_chip_2024_boundary_layer` |
| State, blank code `Territory`, `ZZ` | 2 | excluded `non_fips_state_aggregate` (fully suppressed) |
| County, FIPS | 3,197 | 3,143 matched; 51 `XX000 "-UNKNOWN"` rows are `unknown_county_of_residence`; 3 VI counties excluded as territory |

- **Connecticut.** The 2024 source already uses the nine planning regions (09110–09190), which match TIGER 2024. There are no legacy CT county codes.
- **Alaska.** Codes 02063 Chugach and 02066 Copper River match TIGER 2024.
- **Boundary areas without a source row (79, all explained).** One is DC county 11001 (`cms_publishes_dc_at_state_level_only`). The other 78 are Puerto Rico municipios (`cms_publishes_puerto_rico_at_state_level_only`). CMS publishes DC and PR at state level only. These areas show "Not published by CMS at this level"; the state value is never substituted.
- **Holds.** Any unexplained source row or boundary gap, or any change in the expected exclusion counts, holds the candidate (`geography_mismatch`). Exclusion evidence is kept in `stage_cms_gv` and in the release report.

## Validation (12 checks; any failure holds)

1. `schema_and_definitions`: the header digest equals the registry, and the dictionary, methods, and catalog phrases are present (whitespace-insensitive) or retrieval holds.
2. `latest_year_selected`: the latest CSV year equals the registry year, which equals the catalog temporal end.
3. `age_level_filter`: only documented age codes appear, and exactly the `All` rows were selected at each level.
4. `row_counts_by_level`: 1 national, 55 state, 3,197 county.
5. `unique_geography_keys`: (level, code, name) is unique, and no GEOID is matched twice.
6. `suppression_and_missing_codes`: no blank cells (only `*` is documented).
7. `numeric_ranges`: counts are integers ≥ 11, proportions are between 0 and 1, and payments and rates are within broad bounds.
8. `percentage_scale_0_1`: the methods-table evidence above holds.
9. `source_geography_accounting`: every unmatched source row is a documented exclusion with the expected count.
10. `boundary_coverage_explained`: every boundary area without a row is explained, with the expected count.
11. `api_cross_check`: CMS API counts and sampled cells equal the CSV.
12. `observation_count`: (matched + national) × 5 observations.

Distribution URL changes, a new catalog year, or changed definitions hold retrieval for registry review. Same-label revised content is held as `same_label_semantic_revision` and needs `release-reviewed-hold`. Identical content records a `duplicate` run.

## Storage and API

- **Migration.** `b7e3c5a9d2f4` (additive; does not touch `cms.gv_*`). It creates `area_pilot.stage_cms_gv`, which holds every selected source row as raw JSONB with its boundary status and exclusion reason. It also creates `area_pilot.observation_cms_gv`, which holds level, GEOID, measure, value `numeric(18,4)`, raw `source_value`, and status. Check constraints keep status and value consistent. Published releases are immutable through `prevent_published_data_change`.
- **Archive.** `data/ingest/cms_om_gv/<run UUID>/` holds the catalog, resources listing, CSV, dictionary, methods, and API evidence. Checksums are in `area_pilot.source_file`. Nothing is deleted automatically.
- **API.** Protected routes `/api/area/{catalog,map,legend,table}?dataset_id=cms_om_geographic_variation` accept `geography=state|county`. A tract request returns 400 with an explanation. The viewport cap is 5,000 areas, with 413 beyond it.
  - Every response carries the release, period, population, value type, geography, unit, storage scale, and the fixed `legend_breaks` for the level.
  - The legend also returns status counts and the national reference.

## Map and table

- **Route and switching.** The page is `/area/cms-gv`. It starts at state level, switches to counties at zoom ≥ 6 (`state_to_county_zoom`, the ACS threshold), and keeps counties at finer zoom with the message "CMS publishes no tract estimates". Measure, release, year, and population persist across transitions.
- **Shading.** Display classes are fixed in the registry: one set per rate measure across both levels, and level-specific classes for the beneficiary count. They are not statistics. Suppressed, missing, and not-published areas have distinct swatches and text.
- **Table.** It lists the GEOID, name, formatted value, raw CMS source value, and status.
- **Selectors.** On the main map, the selector now lists "CMS Original Medicare 2024, states and counties (published release)", which opens this page. The legacy option is relabelled "CMS Medicare Fee-for-Service (legacy import, through 2023)" and still uses `/cms/gv/*` unchanged.

## Relationship to the legacy integration

`app/cms/ingest/gv_ingest.py` upserts every column, year, and age into `cms.geo_dim`, `cms.gv_measure_dim`, and `cms.gv_fact`, with no release pointer. That data runs through 2023, and the importer was **not run**. Its useful parts were checked and reused as knowledge: the dimension columns, the level and code normalization, and the `*` suppression token. Its unverified tokens (`.`, `NA`, `<n>`) were not carried over, because the 2024 dictionary documents only `*`.

Retiring the legacy integration is a separate decision.

## Manual operations (from `backend/`)

```bash
.venv/bin/python -m app.area_pilot.cms_gv_cli fetch-stage-validate          # candidate + report (prints digests)
.venv/bin/python -m app.area_pilot.cms_gv_cli review <candidate_id>         # re-hash archive, re-derive every observation
.venv/bin/python -m app.area_pilot.cms_gv_cli approve-publish <candidate_id> \
  --semantic-sha256 <…> --schema-sha256 <…> --metadata-sha256 <…>          # checksum-bound; moves only this pointer
.venv/bin/python -m app.area_pilot.cms_gv_cli release-reviewed-hold <candidate_id> \
  --semantic-sha256 <…> --schema-sha256 <…> --metadata-sha256 <…> --operator-note "<why>"   # same-label revisions only
.venv/bin/python -m app.area_pilot.cms_gv_cli rollback <published_release_id>
.venv/bin/python -m app.area_pilot.cms_gv_cli deactivate                    # hides this product only
```

- **Not on the weekly timer.** Each fetch archives about 77 MB: an 18 MB catalog, the 58 MB CSV, two PDFs, and small API files. The disk guard requires about 300 MB of headroom plus the configured minimum before starting.
- **When CMS publishes 2025 data,** retrieval holds with "registry is pinned to 2024". Review the new dictionary and definitions, update the registry year, URLs, and expected counts, and run the tests before staging.

## 2026-11-14 publication and deployment (Claude)

- **Migration and candidate.** Migration `a4d9e7c2b6f1` → `b7e3c5a9d2f4` was applied. Candidate `73d93c74-7d59-4723-a862-25ecf7a6bc92` passed 12/12 checks in 7.0 s. A second fetch recorded a duplicate.
- **Review.** `review` verified 28 archive files (two runs), 3,253 staged rows, and 15,980 observations. An independent CSV-to-DB comparison of 50 cells had 0 mismatches.
- **Publication.** Published at 2026-11-14T21:47:59Z with these digests:
  - semantic `1b5e4e688fb2eacb4cbb3a3088c4dddea2c17583987df0d155ea49a028ca5800`
  - schema `48209de589f3745807d5fcf51679dbb3d20826c9287f1bd2ac2e0206f5ab325b`
  - metadata `25a54bab83e0b94512571a20476d70e0e8e57fb0178dcc10ee22b92bfab99fc1`
  - keyset `a2f1b5dc7a6edfcfbe1b612013fe00ab2786921ede71dbf2623baad3074beaa6`
- **Live pointer drill.** `deactivate` ran, a cross-product rollback to the AQI release was refused, and `rollback 73d93c74…` restored the pointer. All nine pointers were rechecked. An update to a published row was refused by the trigger.
- **Deployment.** The previous webroot was backed up to `data/deploy-recovery/cms-om-gv-20261114/webroot-before/` and the build installed with `rsync -a --delete`; the webroot matches the build. `places-backend` was restarted at 21:48:25Z. Health returned 200, and anonymous catalog and map requests returned 401.
- **Authenticated browser check, 88/88 passed (real demo session through Nginx).**
  - All five measures at state and county level: header, value format (counts, $, per 1,000, %), map/legend/table parity, polygons drawn, national reference, and release/period pinning.
  - The national row is never a feature, and readmission stays selected through the state→county switch.
  - County popup, tract-zoom county retention, rapid switching across six measures, and the HRSA, TRI, and nursing-home overlays.
  - Six shared catalogs, the legacy `/api/cms/gv/{years,measures,geo}` routes, and the legacy main-map selector loading legacy data.
  - The 390-pixel layout has no horizontal scroll, and there were no page errors.
  - Three temporary codes (`agent-verification-cms-gv-20261114`, 2 uses, 30 minutes) were created and deactivated by the wrapper, each used once; the plaintext was never printed.
- **Benchmarks (in-process, warm, live DB).**

  | View | Areas | Map | Legend | Table |
  | --- | --- | --- | --- | --- |
  | National states | 52 | 0.55–0.61 s, 77 KB | — | — |
  | National counties | 3,222 | 3.1–4.3 s, 1.8 MB | 0.18–0.26 s | 0.09–0.17 s |
  | Chicago-area counties | 11 | 16 ms | — | — |
  | Los Angeles-area counties | 8 | 18 ms | — | — |

  The existing EPA AQI national county view on the same geometry measured 3.1 s. The UI requests counties only at zoom ≥ 6.

**Rollback:** `rollback <earlier published id>` when one exists. For this first release, use `deactivate`. Application rollback means restoring the backed-up webroot and the previous commit. Do not downgrade the migration to recover a pointer.
