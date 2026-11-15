# Data contract: `app.area_pilot.lookup`

This is the only way the product track reads published shared data. Claude owns the module and this document; Codex calls the functions and does not query `area_pilot` tables directly. If a field is missing, ask for it in `docs/beta/status/codex.md`.

All functions take a SQLAlchemy session (`db`) as the first argument and read only the **active published release** of each product. Real output for Etowah County, Alabama (`01055`) is in [contract-examples](contract-examples/); use those files as test fixtures.

## Functions

| Function | Returns | Example file |
|---|---|---|
| `catalog(db)` | Every product and measure, the levels each is published at, the active release, product limitations, and `status_text` | `catalog.json` |
| `area_info(db, level, geoids)` | Name, state, county, bounding box, and a point inside each area (2024 boundaries). Unknown GEOIDs are left out. | `area_info_county_01055.json` |
| `area_values(db, level, geoids, products=None, measure_ids=None)` | One row per area and measure published at exactly that level | `area_values_county_01055.json`, `area_values_state_01.json`, `area_values_county_edge_cases.json` |
| `national_reference(db)` | National values the source itself publishes (CMS only) | `national_reference.json` |
| `county_tract_values(db, county_geoid, product, measure_id)` | Every tract row of one measure in one county, without geometry | `county_tract_values_01055_places_access2.json` |
| `area_facilities(db, level, geoid)` | Health center sites, nursing homes, and TRI reporting facilities located in a state, county, or district | `area_facilities_county_01055.json` |
| `active_releases(db)` | Active release per `dataset_id`, including the three point products | |

`level` is `state` (2-digit GEOID), `county` (5), `tract` (11), or `cd` (4: state FIPS plus district code, 119th Congress). At most 200 GEOIDs per call. Invalid input raises `lookup.LookupError_`; turn it into HTTP 400.

Product keys: `places` (13 measures), `acs` (median income), `acs_profile` (seven community characteristics), `ahrf`, `clh`, `cms_gv`, `epa_aqi`, `usda_fea`: 46 measures on staging since 2026-11-15.

The files directly in `contract-examples/` are the original 28-measure payloads. Current payloads are in `contract-examples/after-c1/` (13 PLACES measures) and `contract-examples/after-c3/` (46 measures, districts).

## Congressional districts (119th Congress)

| Function | Returns | Example file (`after-c3/`) |
|---|---|---|
| `area_info(db, 'cd', geoids)` | District name, state, bounding box, point | `area_info_cd_5401.json` |
| `area_values(db, 'cd', geoids)` | The seven `acs_profile` measures, which are the only district-level values CHIP has | `area_values_cd_5401.json` |
| `area_facilities(db, 'cd', geoid)` | Facilities located inside the district | `area_facilities_cd_5401.json` |
| `district_counties(db, district_geoid)` | Counties overlapping the district, with area shares | `district_counties_5401.json` |
| `county_districts(db, county_geoid)` | Districts overlapping a county | `county_districts_06019.json` |
| `state_districts(db, state_geoid)` | All districts of a state, for search and navigation | `state_districts_54.json` |

Rules for the district briefing:

- Only `acs_profile` rows at level `cd` are district estimates. Label them "district estimate (Census Bureau)".
- Anything read for an overlapping county (`area_values(db, 'county', …)`) is **context**. Show it under its county's name and never merge, average, or weight it into a district figure.
- `county_area_share_in_district` and `district_area_share_in_county` are area shares from the boundaries, not population shares. Show the function's `note`. `county_wholly_in_district` tells you whether a county lies entirely inside.
- District codes `00` (at-large) and `98` (DC and Puerto Rico delegates) are real districts. There are 437 in total.
- A GEOID that does not exist returns rows with status `not_in_release`; validate with `area_info` first.

`acs_profile` rows use `uncertainty.kind` `moe90`. State and county population totals have `moe` null with the label "No sampling margin: the estimate is controlled to official population totals"; show that text, not a zero margin. The ACS `uninsured_pct` (all ages, survey) and the PLACES `access2_crudeprev` (adults 18–64, modeled) must not be presented as the same measure.

Maps for `acs_profile` use `dataset_id=census_acs5_2024_community_profile` on `/api/area/{catalog,map,legend,table}` with `geography` `state`, `county`, `tract`, or `cd`. The map and legend responses include `legend_breaks`, `label`, `unit`, and `kind`. No frontend page exists for this product yet.

## The value row

```json
{
  "product": "places", "dataset_id": "cdc_places_county_2025_pilot",
  "measure_id": "access2_crudeprev", "label": "Current lack of health insurance",
  "unit": "percent", "kind": null, "storage_scale": null,
  "period": "2023", "population": "adults aged 18-64", "value_type": "crude_prevalence",
  "level": "county", "geoid": "01055",
  "value": 10.8, "status": "available", "status_text": "Published value", "stored": true,
  "uncertainty": {"kind": "ci95", "low": 8.5, "high": 13.6, "label": "95% confidence interval"},
  "notes": {},
  "release_id": "f735c524-…", "source_release_id": "2025-12-12",
  "boundary_vintage": "TIGER/Line 2023 county"
}
```

| Field | Meaning and rule for display |
|---|---|
| `value` | The stored published value, or `null`. Never treat `null` as zero. |
| `status`, `status_text` | Show `status_text` when `value` is `null`. `true_zero` is a published zero and has `value` 0. |
| `stored` | `false` means the release has no row for this area and `status` was assigned at read time, the same way the product's map does it (`no_reported_value`, `not_published`, `not_covered`, `boundary_not_comparable`, `not_in_source`, or `not_in_release`). |
| `uncertainty.kind` | `ci95` (PLACES: `low`, `high`), `moe90` (ACS: `moe`), or `none`. Keep the three visibly different; show `label`. |
| `unit`, `kind`, `storage_scale` | Format from these. `storage_scale` `proportion_0_1` (CMS readmission rate) is stored 0–1: multiply by 100 for display only. `kind` `currency` is nominal US dollars. |
| `period`, `population` | Show both with every value. They differ between measures in the same product. |
| `notes` | Source extras: `source_value` (exact source text), `value_note`, `days_with_aqi`, ACS `estimate_annotation` and `moe_annotation`, `source_code`. |
| `release_id`, `source_release_id` | Cite `source_release_id` in the source line. Pass `release_id` to the map API when linking to a map. |

Catalog measure entries add `product_name`, `publisher`, `landing_page`, `levels`, `definition`, `denominator`, `interpretation`, and `underlying_source` (null where the registry has none).

## What the caller must not do

- Do not sum, average, rank, or rescale values across areas, and do not fill a missing level from another level. A state value exists only where `area_values(db, 'state', …)` returns one (ACS and CMS today).
- Do not compare values of different measures or populations as if they were the same thing. CMS rows describe Original Medicare beneficiaries, not residents.
- Do not present tract rows as a county figure, or facility counts as capacity, access, exposure, or quality. Show each facility block's `method` and `limitations`.
- Facility blocks list at most 200 rows (`truncated` tells you). `count` is always the full count of mapped records.

## Linking to maps

Profile maps reuse the existing viewport API (`/api/area/map`, `/legend`, `/table`) with the area's `bbox` from `area_info` and the `release_id`, `measure_id`, `period`, `population`, and `value_type` from the value row. Existing pages are `/area/places-2025`, `/area/acs-2024`, `/area/ahrf`, `/area/clh`, `/area/epa-aqi`, `/area/cms-gv`, and `/area/usda-fea`.

## Routing

Register the community router with the FastAPI prefix `/community`. Through Nginx it is reached at `/api/community/*`: the general `/api/` block strips `/api`, the same way `/api/area/*` reaches `/area/*`. The demo-access middleware protects it like every other route.

## Source credit (added 2026-11-15)

Every catalog measure and value row carries `source_credit`: a string naming a third-party copyright owner whose data the publisher redistributes, or `null`. Today only the five AHRF measures have one (AMA, ADA, AHA). Pages and exports must show it beside the source line. It is attribution only.

## BRFSS state estimates and state profiles (added 2026-11-15)

Plan: [BRFSS_STATE_PLAN.md](BRFSS_STATE_PLAN.md). Real output from staging is in [contract-examples/after-brfss/](contract-examples/after-brfss/). The catalog now has 66 measures; county and district output is unchanged.

**New product key `brfss`** (dataset `cdc_brfss_state_prevalence`): 20 CDC BRFSS crude-prevalence measures, **state level only**, 2023 except dental visits (2022). It appears in `area_values(db, 'state', …)` like any other product. Uncertainty is `ci95` (CDC's 95% confidence limits). `notes.sample_size` is the number of respondents who gave the published response, not the survey denominator.

| Function | Returns |
|---|---|
| `area_values(db, 'state', [fips])` | Every state-published row: `acs` (1), `acs_profile` (7), `brfss` (20), `cms_gv` (5). 33 rows per state. |
| `state_survey_companions(db, state_fips)` | `companions[places_measure_id]` → that state's BRFSS row, for the 13 PLACES measures. Use this on county and tract profiles. |
| `brfss_medians(db)` | CDC's "All States and DC (median)" per measure. `reference_kind` is `median_of_states_and_dc`; no confidence interval. |
| `state_counties(db, state_fips)` | County GEOIDs and names in the state, for navigation. |
| `state_districts(db, state_fips)` | Existing: 119th Congress districts in the state. |
| `states(db)` | The 52 state-level areas CHIP can name (50 states, DC, Puerto Rico), for search. |
| `area_facilities(db, 'state', fips)` | Existing: facility counts and rows inside the state. |
| `area_info(db, 'state', [fips])` | Existing: name, bounding box, point. |

**Pairing.** Each catalog measure has `paired_measure`: `{product, measure_id}` or `null`. The 13 PLACES measures point at their BRFSS measure and back. Seven BRFSS measures (binge drinking, no leisure-time physical activity, fair or poor health, frequent physical distress, arthritis, kidney disease, cost barrier) have no pair and belong on state pages only.

**Rules for pages and exports:**

- On a county or tract card, label the companion "State survey estimate (BRFSS)" and show its own year, confidence interval, and source line (CDC · BRFSS state survey estimates · year · release). Never present it as a target, rank, or difference from the county figure. The county figure is modeled; the state figure is a direct survey estimate.
- A companion or state row with status `not_published` means CDC has no result for that state and year (Kentucky and Pennsylvania in 2023). Show the status text; do not fall back to another year or to the median.
- Never compute a state figure from counties, and never show a PLACES value as a state value.
- The median is "median of states and DC", not "U.S." or "national".
- Three insurance measures now exist and stay separate: `acs_profile.uninsured_pct` (all ages), `places.access2_crudeprev` (18–64, modeled, county and tract), `brfss.uninsured_18_64` (18–64, state survey).
- A state profile has no workforce, food, air-quality, or community-condition section: those sources are published for counties only in CHIP. Say so; do not sum counties.

**Map API** (`/api/area/catalog|map|legend|table` with `dataset_id=cdc_brfss_state_prevalence`, `geography=state`): the same parameters as the other source maps. `map` and `table` return all 52 state shapes; a state without a result has `status: not_published` and `value: null`. Properties carry `ci_low`, `ci_high`, `sample_size`. `table` adds `reference.median` (two CDC median rows) and `reference.source_only` (Guam and the Virgin Islands, which CHIP has no boundary for). `legend_breaks` are per measure.
