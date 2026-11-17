# Task H2e (Antigravity): Census ACS median household income history parser

Follow [H2-antigravity.md](H2-antigravity.md). Product key `acs`.

- **Registry:** `backend/app/area_pilot/registry/history/acs.json`. It has one measure, `B19013_001E`, with five periods `2015–2019` … `2019–2023`; each locator gives `vintage` (`2019` … `2023`). The registry's `state_fips` lists the supported states.
- **Source roles** (Census Data API JSON, saved one file per request):
  - `acs<V>_state`
  - `acs<V>_county_<SS>`
  - `acs<V>_tract_<SS>`

  `<V>` is the vintage and `<SS>` each state in `state_fips`. In tests, give the parser a registry copy restricted to the fixture's states and vintages.
- **Fixtures** in `backend/tests/fixtures/history/acs/`: real responses for vintages 2019 and 2023, states `09` (Connecticut) and `11` (DC). The 2019 Connecticut files use the former counties (`09001` …); the 2023 files use planning regions (`09110` …).

## Rules specific to ACS

- **Reuse the current adapter:** call `app.area_pilot.acs.parse_response(payload, level, state)` for each file; it checks the header, partition, duplicates, and every annotation rule. Then call `parse_observation(row)` for the value, MOE, and status. Do not reimplement either.
- **Roles and coverage:** every role the registry implies (after per-state expansion) must be present in `files` with at least one row; otherwise raise. A response for a state outside `state_fips` raises.
- **Rows:** `value` is the estimate (open-ended rows keep their published value and `open_ended` status), `moe` is the MOE, and the uncertainty kind is `moe90`. `source_value` is the raw estimate text together with its annotation, e.g. `250001|250,000+`.
- **Parts:** one part per (vintage, level), e.g. `v2019_tract`. The tract parts are the large ones.
- **Evidence:** per vintage and level, the row counts, the status counts, and the number of open-ended rows.
- **Tests:**
  - Row counts per (period, level) for the fixture.
  - One open-ended tract row.
  - One sentinel or missing row, if the fixture has one; if not, use a constructed copy of one row with `-666666666`/`-666666666`.
  - Connecticut 2019 county `09001` gets boundary vintage `2020`, and 2023 county `09110` gets `2024`.
  - DC 2019 tracts get vintage `2019`.
  - A response whose header lacks `B19013_001MA` raises.
  - A missing role raises.
