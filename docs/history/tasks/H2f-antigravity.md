# Task H2f (Antigravity): Census ACS community characteristics history parser

Follow [H2-antigravity.md](H2-antigravity.md), and H2e for the shared ACS pattern. Product key `acs_profile`.

- **Registry:** `backend/app/area_pilot/registry/history/acs_profile.json`. It has 7 measures × 5 periods (`2015–2019` … `2019–2023`) at state, county, and tract level only; there are no districts. Locators give `vintage` and `variable`.
- **Source roles:** `acsp<V>_state`, `acsp<V>_county_<SS>`, `acsp<V>_tract_<SS>`. These are subject-table API JSON with `NAME` plus E, M, EA, and MA for each variable.
- **Fixtures** in `backend/tests/fixtures/history/acs_profile/`: vintages 2019 and 2023, states `09` and `11`.

## Rules specific to the ACS community product

- **Reuse the current adapter:** `app.area_pilot.acs_profile.parse_response(payload, level, config, state)` validates every row and returns `(records, excluded)`. Use `parse_observation(row, measure)` for each measure.
  - Pass the current registry (`app.area_pilot.acs_profile.load_registry()`) as `config`.
  - Before parsing, check that each history locator's `variable` equals the current measure's `variable`, and raise otherwise.
- **Excluded rows:** `excluded` only occurs for `cd`, which history does not request. Raise if it is ever non-empty.
- **Values and uncertainty:** values and statuses come from `parse_observation`, with uncertainty `moe90`. `source_value` is the raw estimate plus `|` plus its annotation, or the estimate alone when there is no annotation.
- **Parts:** one per (vintage, level), e.g. `v2023_county`.
- **Tests:**
  - Row counts per (measure, period, level).
  - Two hand-checked values with MOE from the fixture JSON (one county, one tract).
  - Connecticut county vintages `2020`/`2024` as in H2e.
  - A variable mismatch between the registry and the current registry raises.
  - A missing role raises.
