# Task V3+V4 (Codex): chart endpoints and profile charts

Assigned by Claude, 2026-11-19. Work in `/home/john/chip-codex-viz` on branch `codex/profile-viz`, which is already checked out. Its `backend/.env` points at `places_staging`.

- Python: `cd backend && PYTHONPATH=. /home/john/chip-codex/backend/.venv/bin/python ...`. The community tests need this venv because it has reportlab.
- Dev backend: port 8002.
- Frontend: run `npm ci` in `frontend/` first.

**You own:**
- `backend/app/community/**`
- `frontend/**`
- `backend/tests/test_community_charts_*`
- `docs/profile-viz/status/codex.md`

Do not commit, push, merge, deploy, or use sudo. Network calls are allowed only for npm and localhost. Record your facts in your status file and stop.

## Read first

1. [PLAN.md](../PLAN.md) and the whole of [CHART_CONTRACT.md](../CHART_CONTRACT.md). The contract is binding: shapes, comparability rules, groups.
2. `backend/app/area_pilot/lookup.py`, the section "profile charts" at the end:
   - `comparability(product, measure_id)`
   - `area_series_many`
   - `national_series`

   Also read `measure_values_within`, `area_values`, `area_info`, and `state_survey_companions`. Use these functions. Write no SQL of your own against `area_pilot`.
3. `backend/app/community/router.py`, to see how the county endpoint builds `state_values` and `survey_companions`. Reuse that logic for the BRFSS `side_note`.
4. In the frontend:
   - `frontend/src/community/CommunityPages.jsx` (`SECTIONS`, `sectionFor`, `Indicator`)
   - `CommunityState.jsx`, `CommunityDistrict.jsx`, `community.css`, `tokens.css`
   - `frontend/src/branding/pdoBrand.js`
   - `frontend/scripts/beta-walkthrough.mjs`

## V3: backend

1. Put the builder in a new module, `backend/app/community/charts.py`, with groups in `backend/app/community/chart_groups.json` exactly as in contract section 4.
   - Section keys must match the page `SECTIONS`.
   - The state page uses the BRFSS measures named in the contract. Districts use only the ACS groups.
2. Add these routes to `router.py`, behind the same access control as the existing profile routes:
   - `GET /community/county/{geoid}/charts`
   - `GET /community/state/{geoid}/charts`
   - `GET /community/district/{geoid}/charts`
   - `GET /community/county/{geoid}/peers?measure=`
   - `GET /community/state/{geoid}/peers?measure=`
3. **Do not change any existing route, payload, helper output, CSV, or PDF.** Before you edit anything, save the JSON of these existing endpoints from a dev backend on port 8002 to `/tmp/codex-viz-before/`:
   - `/community/county/01055`
   - `/community/county/01063`
   - `/community/state/01`
   - `/community/district/5401`
   - `/community/catalog`

   After your changes, prove they are byte-identical. Record the `sha256sum` of each file, before and after, in your status file.
4. Take every marker, peer list, and trend style from `lookup.comparability(product, measure_id)` and the requested level. Never hard-code product names in the chart logic. The only exception is the BRFSS `side_note` for county PLACES rows, which pairs measures the way `survey_companions` already does.
   - The `state` and `national` marker values come from `area_values` at the state level and from the last row of `national_series`, matched to the same period. When the periods differ, set the marker to `null`.
   - The `trend` for a level not in `trend_levels` is `null`, and districts never get one.
   - `state_series` and `national_series` are filled only where the matching marker is allowed.
   - `peers.values` contains published values only. `min` and `max` give GEOID, name, and value.
5. Performance:
   - Use `area_series_many`, one call per area and level.
   - The county `/charts` call must respond in under 1.5 s warm on staging. Report the cold and warm times.
   - You may cache the payload in-process, keyed by (level, geoid, the `active_releases` fingerprint).
6. Tests in `backend/tests/test_community_charts_api.py`, using the staging DB with a skip if it isn't staging:
   - **Shapes:** for 01063, 01055, 01, and 5401, every key in the contract is present.
   - **No PLACES or BRFSS state or national markers:** no `places` or `brfss` row has a non-null `comparisons.state` or `comparisons.national`.
   - **No markers on count measures:** count measures have no markers.
   - **Districts:** every district `trend` is `null`.
   - **PLACES trends:** every `places` trend has style `dots_ci`.
   - **ACS values:** values equal `area_values` for the same area and measure.
   - **State peers:** the state `brfss` peer count is at least 50.
   - **County peers:** `/peers` for 01063 diabetes returns 67 Alabama counties.
   - **Peers not allowed:** `/peers` for a product without peers returns 400.
   - **Missing values:** a missing value keeps `status_text` and never becomes 0.

## V4: frontend

1. **Components** go in `frontend/src/community/charts/`, as hand-built SVG. Do not add a charting dependency.
   - `ChartBand` (one per section, above the cards)
   - `DotIntervalRow`
   - `PeerStrip`
   - `PeerList`
   - `TrendChart` (styles: `line_band`, `line`, `dots_ci`, `dots`)
   - `Sparkline`
   - `ChartTable` ("Show as table")
   - a small `scale.js`
2. **Data fetch.** Each profile page fetches `/charts` after the main profile loads. If the fetch fails or is slow, the page renders exactly as today, with no band and no error banner.
3. **Rendering rules:**
   - **Marker shapes and colours:**
     - area: circle, #0277BD, with an interval bar
     - state: diamond, #F0B97D
     - U.S.: square, #009688
   - **Legend:** each band has a legend that names the area, the state, and the United States.
   - **Gridlines:** on the value axis only, light grey.
   - **Source line:** under each band, from the rows' `source` and `citation`.
   - **Scales:** a group with `shared_axis: false` scales each row on its own.
   - **Trend-only rows** show a `Sparkline` in place of the dot.
   - **PLACES row:**
     - The dot and interval sit above a `PeerStrip`: faint ticks for every peer value, with the area highlighted.
     - The caption reads "Alabama counties (67): lowest 11.2% Shelby County, highest 27.1% Greene County".
     - The `side_note` is a separate line of text, not drawn on the axis.
     - A "Compare counties" button fetches `/peers` and opens a `PeerList` sorted by value, highest first. The list shows this county, its 15 nearest counties by value, and the lowest and highest, separated by a dashed rule, with "Show all N". Rows whose interval overlaps this area's are blue; all other rows are grey.
     - The legend says: "Interval overlaps [area]'s · Other counties · [area]'s 95% CI". Add the note: "Overlapping intervals are a display aid, not a test of statistical difference."
     - No rank numbers.
   - **"Over time" toggle.** Each row with a non-null `trend` has one, closed by default. It opens a `TrendChart` inline:
     - `dots_ci`: dots and CI bars with no connecting line. Show `trend.note` as a visible caption.
     - `line` and `line_band`: break the line where `boundary_vintage` changes between neighbouring points. List those periods' notes under the chart.
     - Overlay `state_series` and `national_series` with their markers.
     - Show periods in `unavailable_periods` as gaps, with the reason in the table view.
     - Never draw a change label, an arrow, or a percentage change.
   - **Missing values** show `status_text` in place of a dot. Never draw them as 0.
4. **Mobile:**
   - Every SVG uses `viewBox` and `width: 100%`, and measures its container (ResizeObserver) instead of assuming a fixed width.
   - At 640 px and below, a row's label sits above its chart.
   - Shorten ACS period labels on the axis to the end year, keeping full labels in the table.
   - No element may cause horizontal page scroll at 375 or 390 px.
   - Tap targets are at least 44 px.
5. **Print:** `@media print` hides the bands and the toggles, so PDF exports are unchanged.
6. **Accessibility:**
   - Each SVG has `role="img"` and an `aria-label` that states the values.
   - Toggles are `<button aria-expanded>`.
   - Nothing depends on hover alone.
   - Text contrast meets WCAG AA. The walkthrough already checks it.
7. **Tests:**
   - vitest tests next to the components:
     - `dots_ci` renders no line path;
     - no state marker is rendered when `comparisons.state` is null;
     - the peer-list subset is correct (15 nearest plus lowest and highest);
     - the table toggle works;
     - a missing value renders its `status_text`;
     - a page renders without a band when `/charts` fails.
   - Extend `frontend/scripts/beta-walkthrough.mjs` to visit `/community/county/01063`, `/community/state/01`, and `/district/cd/5401` at 1365, 390, and 375 px. On each, fail if `document.documentElement.scrollWidth > window.innerWidth`, open one "Over time" toggle and one "Compare counties", and screenshot when `CHIP_BETA_SCREENSHOT_DIR` is set. Claude runs this walkthrough against staging after deploying.

## Commands

- `cd backend && PYTHONPATH=. /home/john/chip-codex/backend/.venv/bin/python -m pytest -q tests/test_community_*.py`
- `cd frontend && npm test && npm run build && git diff --check`

## Done when

- Every test passes.
- The before and after hashes of the existing payloads match.
- `docs/profile-viz/status/codex.md` has rows for V3 and V4 and a `## V3V4 diary facts — <ISO timestamp with timezone>` section covering:
  - objective and outcome
  - files and verification, including timings and hashes
  - open questions and the next action for Claude
- You have written in the status file any change you needed outside your paths. Do not make that change yourself.

Finish with a report of 12 lines or fewer.
