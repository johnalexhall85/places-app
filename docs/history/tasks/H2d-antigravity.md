# Task H2d (Antigravity): EPA AirData annual AQI history parser

Follow [H2-antigravity.md](H2-antigravity.md). Product key `epa_aqi`.

- **Registry:** `backend/app/area_pilot/registry/history/epa_aqi.json`, which has 5 county measures × 2020–2024.
- **Source roles:**
  - `county_zip_<YYYY>` (each holds `annual_aqi_by_county_<YYYY>.csv`)
  - `site_listing_zip` (holds `aqs_sites.csv`)
  - `tiger_county_2020` and `tiger_state_2024` (TIGER shapefile ZIPs; read their attributes only)
- **Fixtures** in `backend/tests/fixtures/history/epa_aqi/`:
  - the real `annual_aqi_by_county_2021.zip` and `annual_aqi_by_county_2024.zip`
  - the real `aqs_sites.zip`
  - `tl_2020_us_county_attrs.zip` and `tl_2024_us_state_attrs.zip`: the real TIGER attributes with point geometry, so they stay small

  In tests, give the parser a registry copy whose `measures[].periods` and `sources` cover only 2021 and 2024, using `copy.deepcopy` and rebuilding `_index` as `registry.load_history_registry` does.

## Rules specific to EPA

- **Read ZIP members in memory** with `zipfile`; write nothing. Check that the member name equals the locator's `member`.
- **Reuse the current adapter:** `app.area_pilot.epa_aqi.validate_row(row, config, year)`, `observation_values(record, config)`, `parse_site_listing(path, config, wanted)`, and `map_counties(records, site_codes, counties, states, config)`. Read them first.
  - **Config:** pass a config built from the current registry (`app.area_pilot.epa_aqi.load_registry()`), with `expected_header`, `reviewed_state_variants`, `reviewed_name_variants`, and `boundary.independent_city_lsad` taken from the history registry's `selection`.
  - **Site listing:** `parse_site_listing` takes a path. Extract `aqs_sites.csv` to a `tempfile.TemporaryDirectory()` that you delete afterwards. This is the only allowed temporary write.
  - **TIGER lookups:** build `counties` and `states` exactly as `load_lookup` does, but from `files['tiger_county_2020']` and `files['tiger_state_2024']`. Do not call `load_lookup`, which reads the 2024 county file.
- **Mapping outcomes:**
  - A row whose mapping has a `geoid` becomes a county row for that GEOID.
  - A row listed in `selection.exclusions` is dropped and counted.
  - Any other unmapped row raises `ValueError`, naming the (State, County) pairs and their `method`. Claude will review them and add reviewed variants to the registry.
- **Values:** statuses come from `observation_values`. There is no missing status; values are counts or AQI numbers, and a zero is `true_zero`.
- **Duplicates:** a GEOID that appears twice in one year raises.
- **Parts:** one part per year, named `year_<YYYY>`.
- **Tests:**
  - Count rows per year.
  - Connecticut's `09001` appears in both years.
  - Sonora and USVI rows are dropped.
  - Hand-check one county's median AQI against the CSV.
  - A missing or renamed member raises.
  - An unmapped county name not on the exclusion list raises.
