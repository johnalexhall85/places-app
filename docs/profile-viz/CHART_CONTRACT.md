# Profile chart contract (v1, 2026-11-19)

This contract governs the profile chart work in [PLAN.md](PLAN.md). Claude owns this file. Codex and Antigravity record any change they need in their status files.

## 1. Comparability rules

The registry `backend/app/area_pilot/registry/comparability.json` holds these rules, and `lookup.comparability(product)` returns them. Endpoints must read the registry, never hard-code product names.

| Product | `state` marker | `national` marker | `peers` | `trend.style` | Fixed trend note |
|---|---|---|---|---|---|
| `acs` | county, cd | state, county, cd | none | `line_band` | "Each 5-year window is inflation-adjusted to its own final year. Windows overlap, so neighbouring periods share survey years." |
| `acs_profile` | county, cd | state, county, cd | none | `line_band` (none for cd) | "5-year windows overlap, so neighbouring periods share survey years." |
| `cms_gv` | county | state, county | none | `line` | "2020 reflects the COVID-19 pandemic. Dollars are nominal." |
| `places` | never | never | county in same state, same period | `dots_ci` | "Each year is a separate PLACES model run from a different release; CDC advises comparing across releases with caution." |
| `brfss` | n/a | never | state (all states and DC), same period | `line_band` | "Direct survey estimates; each year uses the same question wording as the current year." |
| `ahrf`, `clh`, `epa_aqi`, `usda_fea` | none | none | none | `line`, or `dots` when there are 2 or fewer points | the history `note` of each period |

Measures where `kind == 'count'`, or whose unit is a count (people, beneficiaries, physicians, dentists, hospitals, beds, days), **never** get state or national markers, because their scales differ. These are `total_population`, `om_beneficiaries`, every AHRF measure, and `days_with_aqi` and `good_days`.

Rules that apply everywhere:
- No ranks, change values, percentage change, composites, or averages.
- A peer list may be sorted by value and may label its lowest and highest rows. It may not show rank numbers.
- "Interval overlaps this area's" is a display aid. The UI must say that overlap is not a significance test.
- When `boundary_vintage` changes between neighbouring periods, the line breaks there and the period's note is shown.
- A missing value shows its `status_text`. It never becomes zero and is never interpolated.

## 2. Endpoints

Codex adds these in `backend/app/community/`. Existing endpoints do not change.

### `GET /community/{county|state|district}/{geoid}/charts`

```jsonc
{
  "level": "county", "geoid": "01063", "name": "Greene County, Alabama",
  "state": {"geoid": "01", "name": "Alabama"},
  "sections": [{
    "key": "health",                       // same keys as the page SECTIONS
    "groups": [{
      "key": "chronic_conditions", "title": "Chronic conditions",
      "unit": "percent", "shared_axis": true,  // false => each row is scaled on its own
      "rows": [{
        "product": "places", "measure_id": "diabetes_crudeprev", "label": "Diagnosed diabetes",
        "unit": "percent", "kind": null, "period": "2023", "population": "...",
        "value": 27.1, "status": "published", "status_text": "...",
        "uncertainty": {"kind": "ci95", "low": 23.9, "high": 30.3, "label": "95% CI"},
        "comparisons": {
          "state":    null,  // or {"geoid","name","value","uncertainty","period"}
          "national": null,  // same shape; geoid "US"
          "side_note": {"label": "Alabama state survey estimate (BRFSS 2023)", "value": 15.9,
                        "uncertainty": {...}, "text": "Direct survey estimate; not on this chart's scale of comparison."}
        },
        "peers": {"level": "county", "parent_geoid": "01", "period": "2023", "count": 67,
                  "values": [11.2, 12.0, ...],             // published values only, unsorted ticks
                  "min": {"geoid": "01117", "name": "Shelby County", "value": 11.2},
                  "max": {"geoid": "01063", "name": "Greene County", "value": 27.1},
                  "peers_url": "/community/county/01063/peers?measure=places:diabetes_crudeprev"},
        "trend": {"style": "dots_ci", "note": "...",
                  "series": [{"period": "2018", "value": 25.0, "low": 22.1, "high": 28.0, "status": "published",
                              "status_text": "...", "note": "...", "boundary_vintage": "2010",
                              "release_label": "PLACES 2020 release", "current_period": false}],
                  "state_series": null, "national_series": null,  // same shape; only where markers allowed
                  "unavailable_periods": [{"period": "2019", "reason": "..."}]},
        "source": {"publisher": "...", "product_name": "...", "credit": "..."},
        "citation": "..."
      }]
    }]
  }]
}
```

- `trend` is `null` when the measure has fewer than 2 published periods for that level, and always for districts.
- `peers` is `null` unless the registry allows peers for the product.
- Rows appear in group order and keep every published measure. A measure whose value is missing still has a row, with its `status_text`.

### `GET /community/county/{geoid}/peers?measure=product:measure_id` and `GET /community/state/{geoid}/peers?measure=...`

```jsonc
{"measure": {...meta...}, "period": "2023", "area_geoid": "01063",
 "values": [{"geoid", "name", "value", "uncertainty", "status", "status_text"}]}  // GEOID order; the client sorts
```

The endpoint reads `lookup.measure_values_within` and returns 400 when peers are not allowed for the product.

## 3. Lookup functions (Claude, V1)

- `lookup.comparability(product) -> dict` returns the registry entry for one product.
- `lookup.area_series_many(db, level, geoid, measure_keys) -> {"product:measure_id": <area_measure_series result>}`. Each result has the same shape as `area_measure_series`, but reads history with one query per product.
- `lookup.national_series(db, product, measure_id) -> {"series": [...rows oldest first...], "unavailable_periods": [...]}`. Rows have the `area_values` row shape with `level: "national"` and `geoid: "US"`. The source is `observation_national`; the current CMS period is also there.

## 4. Groups (`backend/app/community/chart_groups.json`, Codex)

`shared_axis` is true only when every row in a group has the same unit.

| Section | Group | Measures |
|---|---|---|
| people | Income | acs B19013_001E |
| people | Age | acs_profile age_under_18_pct, age_65_plus_pct |
| people | Poverty, disability, coverage, language | acs_profile poverty_pct, disability_pct, uninsured_pct, limited_english_pct |
| people | Population | acs_profile total_population (trend only) |
| health | Chronic conditions | places diabetes, bphigh, obesity, chd, stroke, copd, casthma (state: the matching brfss measures) |
| health | Mental health | places depression, mhlth (state: depression, frequent_mental_distress) |
| health | Health status (state only) | brfss fair_or_poor_health, frequent_physical_distress, arthritis, kidney_disease |
| prevention | Prevention and coverage | places checkup, dental, access2 (state: routine_checkup, dental_visit, uninsured_18_64, cost_barrier_to_care) |
| prevention | Health behaviors | places csmoking (state: current_smoking, binge_drinking, no_leisure_physical_activity) |
| care | Health workforce | ahrf primary care, dentists, psychiatrists (trend only; `shared_axis` false) |
| care | Hospitals | ahrf hosp_23, hosp_beds_23 (trend only) |
| conditions | Housing, transport, broadband | clh broadband, no vehicle, renter burden |
| conditions | Recreation | clh fitness centers per 1,000 |
| food | Food access | usda_fea low_income_low_access_pct, no_car_low_access_households_pct |
| food | Food retailers per 1,000 | usda_fea snap, wic, farmers markets; clh supermarkets |
| environment | Air quality index | epa_aqi median, p90, max |
| environment | AQI days | epa_aqi days_with_aqi, good_days (trend only) |
| medicare | Medicare use and spending | cms_gv std_payment_per_capita, ip_stays, er_visits, readmission_rate (`shared_axis` false); om_beneficiaries (trend only) |

A "trend only" row shows a sparkline in the band instead of a dot, because it has no comparison to show.
