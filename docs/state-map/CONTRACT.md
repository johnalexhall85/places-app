# State funding map contract, v1 (2026-11-20)

Owner: Claude. Codex implements §1–§4, and Antigravity audits against §5. Any change needs a dated amendment here, written by Claude.

The map reads the active `state_funding` build through `app.state_funding.lookup`, with the filters and rules of the [state funding contract](../state-funding/CONTRACT.md) and its Amendments 1–2. Nothing here changes the state page, its API, or the MCP tools.

## 1. Lookup (`app.state_funding.lookup`, or a new `map.py` in that package)

`state_map(db, fy, filters, build)` returns one row per state code with any obligation row for **grants** in that fiscal year under the filters, including `'__'`.

- Filters: `funding_type` (`all|regular|supplemental`) and `category` (a `category_code` or None). `award_type` is fixed to `grant`; `recipient_type` is `all`.
- Use the same `where()` and join as `summary()`, so that for every state, `total`, `regular`, `supplemental`, `award_count`, and `recipient_count` equal `summary()` for that state and filters. One set-based query; no per-state loop.
- `state_shapes(db)` returns `app.area_pilot.lookup.area_info(db, 'state', <all 2-digit FIPS>, geometry=True)` keyed by postal code. Use a fixed postal-code ↔ FIPS table in the package (the 50 states, DC, PR, GU 66, VI 78, AS 60, MP 69). Do not query `area_pilot` tables directly.

## 2. HTTP API (on the existing `/state-funding/v1` router, behind the demo-access gate)

### `GET /map`
Parameters: `fy` (default: the latest fiscal year), `funding_type` (default `all`), `category` (default none). A bad value returns 422; `award_type`, `account`, and `recipient_type` are rejected with 422.

```jsonc
{ "fiscal_year": 2026, "period": "FY2026 P12",
  "filters": { "funding_type": "all", "category": null, "award_type": "grant" },
  "categories_available": [ { "code": "…", "name": "…", "basis": "…" } ],  // categories with grant rows in this FY, all states, sorted by category_order
  "states": [ { "code": "CA", "fips": "06", "name": "California",
                "total": 0.0, "regular": 0.0, "supplemental": 0.0,
                "award_count": 0, "recipient_count": 0,
                "has_shape": true, "indicators_geoid": "06" } ],         // sorted by name
  "unattributed": { "total": 0.0, "award_count": 0 },                   // the '__' row, or zeros
  "national": { "total": 0.0, "award_count": 0 },                       // all codes including '__'
  "citation": "…", "notes": [ "…" ] }
```
- `indicators_geoid` is the FIPS when `app.area_pilot.lookup.states(db)` lists that state (the community state profile exists), else null.
- `national.award_count` counts distinct awards, so it can be less than the sum of the states.
- `notes` carries the state-funding sentence about negative supplemental amounts when any state's `supplemental < 0`, and: "Grants are counted in the state of the recipient's address. Money a recipient passes on to sub-recipients in other states is not moved."
- Amounts are rounded to cents. Response under 60 KB.

### `GET /map/shapes`
`{ "states": { "CA": { "fips": "06", "name": "California", "geometry": {…} }, … }, "boundary_vintage": "TIGER/Line 2024" }`. Send `Cache-Control: public, max-age=86400`. Under 400 KB uncompressed; if it is larger, raise the simplification tolerance inside `state_funding`, not in `area_pilot`.

## 3. Page (`/cdc-funding/map`)

Files: `frontend/src/pages/CdcFundingMap.{jsx,css,test.jsx}`, API functions in `frontend/src/api/stateFunding.js`, and the route in `utils/routeResolver.js` and `main.jsx`. Brand and format rules follow the state page (tokens, header, eyebrow "CDC funding · National map", compact KPI dollars, whole dollars elsewhere, U+2212 minus, no wrapping amounts).

- **Title:** "CDC grants to recipients by state", with the FY and period under it.
- **Controls** (one row on desktop, stacked on phones): Fiscal year; Budget category ("All categories" plus `categories_available`); Funding type ("All funding", "Regular", "Supplemental"). The query string keeps `fy`, `funding_type`, `category`, and `state` (the open panel).
- **Map:** inline SVG with `d3-geo` (add it as a dependency; no tile layer, no Leaflet). `geoAlbersUsa` for the 50 states and DC; Puerto Rico in its own inset next to Hawaii. Tiles in a row under the map for DC, PR, GU, VI, AS, and MP, colored like the map. States with no grant rows are light gray and labeled "No grants" in the tooltip.
- **Color:** a diverging, classed scale. Positive totals: 5 quantile classes over the positive values, light to dark blue ending at `--chip-navy` through `--pdo-primary`. Negative totals: up to 3 quantile classes over the absolute negative values in Peach/orange, starting from `--pdo-accent`. Exactly 0 is gray. The legend shows each class's range in compact dollars and labels the negative side "Net reduction". `'__'` is never colored.
- **Tooltip** (hover and keyboard focus): state name, amount in whole dollars, and "N grants" (singular "1 grant"). On touch, tap opens the panel instead.
- **Panel** on click, Enter, or a tile:
  - state name and the filter summary ("FY2026 · All categories · All funding");
  - total, regular, and supplemental in whole dollars; number of grants; number of recipients;
  - when the category filter is "All categories", up to 5 largest budget categories by absolute total, from `GET /states/{code}/summary` with the same filters and `award_type=grant`;
  - links: **"State indicators"** → `/community/state/{indicators_geoid}` (omitted when null) and **"State funding profile"** → `/cdc-funding/state/{code}?fy=…&funding_type=…&category=…&award_type=grant`;
  - a close button; Escape closes it. On phones the panel is a bottom sheet.
- **Below the map:** the national total and grant count; the unattributed note ("$X in N grants has no recipient state and is not mapped."), the notes, and the citation line; and a `<details>` "Table of states" (state, amount, grants), sortable by name or amount, which is the accessible equivalent of the map.
- **Links in:** `/cdc-funding` and `/cdc-funding/state/{code}` get a "National map" link near their titles.
- No ranks, shares, or per-capita values anywhere.

## 4. Tests

- **Backend** (`tests/test_state_map_api.py`): parameter validation and 422s; one state's row equals `summary()` under the same filters, for each funding type and one category; the `__` row lands in `unattributed`; `indicators_geoid` null for a territory without a profile; shapes keyed by code with `Cache-Control`; one staging test (skips when unreachable) that FY2026 all-funding `national.total` equals $2,903,439,520 ± $1.
- **Vitest:** render with mocked data; the dropdowns update the query string and refetch; the tooltip shows "N grants"; negative and zero classes; the panel shows both links with the filters and omits the indicators link when null; the DC and territory tiles; the table sort.
- **Walkthrough** (`frontend/scripts/beta-walkthrough.mjs`): visit `/cdc-funding/map`, change each dropdown, open the California panel, check both link targets, and check 375 px has no page overflow. Run `node --check`.

## 5. Audit invariants (Antigravity's `tests/test_state_map_audit.py`, on `places_staging`)

For every fiscal year × funding type, with no category, and for 3 categories in FY2026:
1. The sum of `states[].total` plus `unattributed.total` equals `national.total`, within $0.01, and equals the sum of `obligation.amount` for grants under the same filters.
2. For 10 sampled states, `total`, `regular`, `supplemental`, `award_count`, and `recipient_count` equal `/states/{code}/summary` with `award_type=grant` and the same filters.
3. `regular + supplemental = total` for every state row.
4. Every code with `has_shape = false` is GU, VI, AS, or MP, and every code with `has_shape = true` is in `/map/shapes`.
5. No state row has `award_count = 0`.
