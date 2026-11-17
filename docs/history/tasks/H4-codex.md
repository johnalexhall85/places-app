# Task H4 (Codex): year dropdown on every `/area/*` map

Assigned by Claude, 2026-11-17. Worktree `/home/john/chip-codex`, branch `codex/history` (checked out). Owned paths: `frontend/**` and `docs/history/status/codex.md`. Usual rules: no commits, pushes, deploys, or sudo. Leave changes uncommitted and record diary facts in your status file.

## Read first

1. [docs/history/PLAN.md](../PLAN.md), the "Decisions with John" table.
2. `backend/app/area_pilot/history_api.py` (response shapes) and the `catalog` route in `backend/app/area_pilot/router.py`.
3. `frontend/src/pages/Places2025Pilot.jsx`, its tests, and `MobileMapPanels.jsx`.

## What the backend now returns

- **Catalog:** `GET /api/area/catalog` gives every measure a `periods` array, current first and then earlier periods newest first: `{period, current, available, release_id, note, levels, boundary_vintage: {level: label}}`.
  - The current entry has `release_id = active_release_id` and `note: null`.
  - Earlier entries carry the history release ID, or `null` with `available: false`.
  - The catalog also has `history_release` and `history_colour_note`.
- **Map, legend, and table for an earlier period:** send the period's `release_id` and `period`. Every other parameter is unchanged.
  - Responses carry `history: true`, `note`, `boundary_vintage`, `colour_note`, `legend_breaks` (fixed-break products), `quantile_breaks` (every product; use them where you use them today), and, in the legend only, `published_without_boundary`.
  - Feature and table rows carry `geography_id`, `name`, `value`, `ci_low`, `ci_high`, `moe`, `status`, `source_value`, `observation_period`, and `measure_id`. PLACES rows also carry `county_fips`/`tract_fips`.
- **Earlier periods are not published on staging yet.** Claude publishes CMS GV history first. Build and test against mocked responses in the existing test style; Claude will check against staging.

## Build

1. **Year select.** Put a "Year" `<select>` right after the Measure select in `.pilot-controls`, so it appears in the mobile drawer too.
   - Options come from `measure.periods`. Labels are the period (for ACS, the 5-year window, e.g. "2019–2023"). The current option says "(latest)".
   - Unavailable periods are present but disabled, with "(not published)".
   - Changing the measure keeps the chosen year if the new measure has it, and otherwise falls back to latest.
2. **State.** Add `period` and the period's `release_id` to the selection. They must be included in:
   - `pilotQuery` (`period` and `release_id`)
   - `dataSelection`, `requestKey`, `capSelectionKey`, `dataKey`, the GeoJSON `key`
   - the release/geography response guard
   - URL state (`?period=`, read back on load; ignore an unknown period)
3. **Shown period.** Replace every place the page prints `measure.observation_period` with the selected period: the metadata line, legend title, table caption, hover tooltip, and selected-area details.
4. **Notes.** For an earlier period, show above the legend classes:
   - the period's `note`
   - its boundary vintage label for the current geography
   - the line "Colour classes are for this year only; compare values, not colours."

   If the legend's `published_without_boundary` is above 0, add "N areas published for this year have no matching boundary and are not drawn."
5. **Geography.** If the period's `levels` lack the current geography (e.g. ACS community `cd`, or PLACES tracts in a year without them), keep the nearest supported level with the same plain-statement pattern the page already uses for unsupported levels. Congressional districts say: "Districts have no earlier years in CHIP: older Congresses had different districts."
6. **Selection.** The selected area survives a year change, keyed by level and GEOID as today. If the area has no shape in that year's boundaries (e.g. a Connecticut planning region in a year drawn on the former counties), show the plain statement the page uses for an undrawn selection.
7. **Do not change** `TractPatternMap.jsx` or any `frontend/src/community/**` profile page. Profiles stay on the current period.
8. **Brand.** Use the existing control styles; nothing new visually beyond the select and the note lines.

## Tests

Extend `Places2025Pilot.test.jsx`:
- the year select renders from `periods` and disables unavailable periods
- choosing a year sends `period` and that period's `release_id` in all three requests
- the cache and request keys differ by period
- `?period=` round-trips
- the note and colour line show only for an earlier year
- a `cd` geography falls back with the district sentence
- the selection survives a year change

Run `npm test` and `npm run build` in `frontend/`.

## Done when

1. Tests and the build pass, and `git diff --check` is clean.
2. `docs/history/status/codex.md` has an H4 row: files changed, test counts, anything the backend should change (as a request to Claude), and diary facts.

Finish with a report of five lines or fewer.
