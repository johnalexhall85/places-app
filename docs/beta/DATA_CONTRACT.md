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
| `area_facilities(db, level, geoid)` | Health center sites, nursing homes, and TRI reporting facilities located in a state or county | `area_facilities_county_01055.json` |
| `active_releases(db)` | Active release per `dataset_id`, including the three point products | |

`level` is `state` (2-digit GEOID), `county` (5), or `tract` (11). At most 200 GEOIDs per call. Invalid input raises `lookup.LookupError_`; turn it into HTTP 400.

Product keys: `places`, `acs`, `ahrf`, `clh`, `cms_gv`, `epa_aqi`, `usda_fea`. More measures and a `cd` (congressional district) level arrive with work packages C1–C3. They appear in `catalog` without a change to the row shape.

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
