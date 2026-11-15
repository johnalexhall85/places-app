# CHIP: one header, brand-consistent maps, and legacy map behaviour on the new maps

## Context

The beta is live. Two generations of pages now sit side by side:

- **Newer pages** (home, profiles, compare, topics, districts, About) use `CommunityShell` in `frontend/src/community/CommunityPages.jsx`: navy header, home-page links, brand tokens.
- **Older pages** use `frontend/src/components/Header.jsx` (white header, pop-up panels): the legacy map `/explore/map` (`App.jsx`), all nine `/area/*` maps (`pages/Places2025Pilot.jsx`), `/cdc-funding`, `/cdc-funding/state/*`, `/funding-model-builder`, and `/profile/*`.

The `/area/*` maps also lack what the legacy map has: a hover tooltip, a legend that shows the selected area, a selection highlight, the Map Tools bar, and a search. They show values only in a click popup, and profile pages open them at the national view.

John asked for these to be made consistent. Decisions made with John on 2026-11-15:

| Question | Decision |
|---|---|
| Who builds it | Claude, including `frontend/**` and `backend/app/community/**`, which are normally Codex's. One-off exception for this package. |
| Brand scope on maps | Brand chrome on all maps, **and** recolour the CMS, USDA, and EPA AQI value ramps on the `/area/*` maps to the brand Blues scale. Legacy-map data ramps stay. This reverses the plan's "existing map legends are not recoloured" for those three maps. |
| Header extras | One shared header with the home-page links, plus Log out and (when enabled) Funding Model Builder. Funding methodology text moves to `/methodology`. Data Sources, Download, and Help pop-ups are retired. |
| Map tools on new maps | Home, Zoom In, Zoom Out, Zoom to selected, Clear Selection (Esc), Open Profile, Base map. No "Analyze this area". |
| Ramp contrast (added by John after approval, 2026-11-15) | Outliers must not wash out the map. Classes for PLACES, ACS income, AHRF, and CLH become quintiles instead of equal-width slices; the shared ramp gets evenly spaced steps. |

## Where the work happens

- Worktree `/home/john/chip-claude`, new branch `claude/map-consistency` from `beta` (`33925a0`; all worktrees were clean when checked).
- Staging through `infra/staging/deploy-staging.sh claude/map-consistency`. **No live change** until John reviews staging and approves.
- No migration, no data release, no pointer change.
- Before the first edit: recheck `git status` in `/home/john/chip-codex` so no Codex frontend work is in flight.

## Step 0: record the plan (first commit)

- Add `docs/beta/MAP_CONSISTENCY_PLAN.md` (this plan, same form as `BRFSS_STATE_PLAN.md`).
- `docs/beta/EXECUTION_PLAN.md`: add a dated note recording the ownership exception and the ramp-recolour reversal (add, do not rewrite).
- `docs/beta/status/claude.md`: new package table M1–M6 (below). Add a short note for Codex in the same file that Claude is editing frontend paths for this package.
- `docs/PROJECT_DIARY.md`: entry for the decisions. A second entry at the end with outcomes.

## M1: one header on every page

- New `frontend/src/components/SiteHeader.jsx` and `SiteHeader.css`: move the header markup out of `CommunityShell` and its rules (`.community-header`, `.community-brand`, skip link) out of `community.css`, so pages that do not load `community.css` get them.
  - Links: Home, Topics, Compare, Districts, Explore data, Funding, About; then Funding Model Builder when `isFundingModelBuilderEnabled()` and Log out when `useDemoAccess().hasAccess`.
- `CommunityShell` renders `SiteHeader`. `components/Header.jsx` becomes a thin wrapper around `SiteHeader`, so the six legacy call sites need no edit. Delete the pop-up code and the `.chip-header*` / `.chip-nav-modal*` rules in `index.css`.
- Move the funding methodology text (the `sections` under `NAV_ITEMS` "methodology") into a "CDC funding methodology" section of `CommunityMethodology` in `community/CommunityInfo.jsx`. Wording unchanged.
- Remove the floating `chip-brand-line` pill from `App.jsx` and `Places2025Pilot.jsx`; the header now carries the brand.
- Map pages size themselves with `--chip-header-height` (74 px; the new header is 88 px and wraps on phones). Change `.app` on map pages to a flex column so the map fills what is left, instead of `calc(100vh - …)`. Check `mapViewportHeight` in `App.jsx` and `.pilot-content` in `Places2025Pilot.css`.
- Update `Header.test.jsx` (link is now "Funding").

## M2: brand guide on the maps

- **Tokens:** `index.css` `:root` still holds pre-brand values that `community/tokens.css` overrides by import order. Make `index.css` carry the guide values directly and drop the `--chip-legacy-*` colours.
- **Legacy map chrome** (`App.jsx`, `SearchBar.jsx`, `components/AskMapChat.jsx`): about 210 inline uses of old colours (`#123247`, `#627A90`, `#BFD0E1`, `#E7EEF5`, `#3576BA`, `#0F2D46`…). Replace with guide colours by a fixed mapping (text `#1A2F3F`, headings `#003F61`, muted `#546E7A`, borders `#CFD8DC`, actions `#0277BD`). Selection outline changes from `orange` to the shared highlight below. Legacy data ramps (`COLORS`, FEMA, HPSA, SVI) are **not** changed.
- **New maps** (`Places2025Pilot.jsx`/`.css`): panel headings Arial Bold navy, title in Roboto Slab, 8 px spacing, buttons as on the home page.
- **Ramps:** one shared Blues ramp in a new `frontend/src/branding/mapColors.js`, light to Deep Navy `#003F61`, taken from `BLUES` in `community/TractPatternMap.jsx` (which then imports it). Replace `gvColors`, `feaColors`, `aqiColors`, and `prevalenceColors`. Status styles stay distinct and non-blue: suppressed, missing, not published (dashed), open-ended, USDA published zero (peach), did-not-exist. Breaks and class labels do not change.
- Update the colour assertions in `Places2025Pilot.test.jsx`, the AQI comment about neutral shading, and the legend sentences that mention colours.

## M2b: class breaks that outliers cannot skew

Found in the code: the PLACES, ACS income, AHRF, and CLH legends return only the minimum and maximum of the values in view, and the page cuts five equal-width classes between them. One extreme county puts most counties in the lightest classes. The other products (CMS, USDA, AQI, BRFSS, ACS community) use fixed breaks from their registries.

- `backend/app/area_pilot/router.py`, `acs_api.py`, `ahrf_api.py`, `clh_api.py`: each legend also returns `quantile_breaks`, the 20th, 40th, 60th, and 80th percentiles of the published values for that release, measure, and geography level across the whole release (not the viewport), so colours do not change while panning. Published zeros count as values; suppressed, missing, and open-ended rows do not.
- The page uses those breaks for map, legend, and table, and labels the legend "Quintiles of published <level> values". Equal-width breaks are removed.
- Shared ramp with evenly spaced lightness steps, ending at Deep Navy.
- For the fixed-break products, count areas per class on staging (read-only) and report any lopsided measure. Registry breaks are not changed in this package, because the registry is part of each release's reviewed metadata.

## M3: read layer for "find this area"

- `backend/app/area_pilot/lookup.py`: `area_info(..., geometry=False)`. With `geometry=True`, also return a simplified GeoJSON outline (`ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, tol))`). It already returns `bbox` and `point` for state, county, tract, and `cd`.
- `backend/app/community/router.py`: `GET /community/area/{level}/{geoid}` returning that record; 404 for unknown, 400 for a bad level. Behind the access code like the rest.
- Tests in `backend/tests/test_area_lookup.py` and `test_community_api.py`. Add the shape to `docs/beta/DATA_CONTRACT.md`.

## M4: legacy map behaviour on the `/area/*` maps

All in `pages/Places2025Pilot.jsx`, with new small modules under `frontend/src/pages/areaMap/` to keep that file from growing.

- **Selection state** (`useAreaSelection.js`): `{level, geoid, name, bbox, geometry, properties}`. The map layer is rebuilt on every pan, so selection is state, not a Leaflet layer reference. An outline layer in its own pane draws the selected geometry (white casing under a Deep Navy line), so the highlight survives panning and geography switches (a county outline over tracts, a state outline over counties).
- **Click** a state, county, tract, or district: selects it, highlights it, shows its details in the legend. The click popup is removed. Esc clears.
- **Hover tooltip:** same Leaflet options and `pdo-map-tooltip` class as the legacy map (`COUNTY_HOVER_TOOLTIP_OPTIONS`, `App.jsx:369`), same three lines: area name, measure, value · period, then one explanation line. Skipped on touch pointers, as in legacy. Move the options and `formatTooltipMetaLine`/`formatTooltipExplanationLine` into a shared `utils/mapTooltip.js` used by both maps.
- **Legend:** minimise button (+/−) like the legacy legend; under the swatches, a "Selected area" block with everything the popup showed (value, CI or MOE, status text, source name, release). The existing `aqiPopup`, `gvPopup`, `feaPopup`, `brfssPopup` builders become the source for this block and the tooltip; their escaping tests stay. If the selected area is a different level from what is drawn (a state selected on a county-only map), the block names the area and says which level the values on the map are for. No value is computed for it.
- **Map Tools bar** (`areaMap/MapTools.jsx`): Home, Zoom In, Zoom Out, Zoom to selected, Clear Selection (Esc), Open Profile (county → `/community/county/{fips}`, state → `/community/state/{fips}`, district → `/district/cd/{geoid}`; disabled for tracts), Base map (reuse `BASE_MAP_OPTIONS`, moved from `App.jsx` to a shared module). Same button classes as legacy.
- **Search:** extract `PlaceSearch` from `CommunityPages.jsx` into `components/PlaceSearch.jsx` with an `onSelect` prop. The home page keeps "go to profile". On maps, choosing a county or state calls `focusArea(level, geoid)`.
- **`focusArea`:** fetch `/community/area/{level}/{geoid}`, `fitBounds(bbox)`, set the selection. Zoom is capped so the map still draws that level where the product has it (county below the tract switch; state below the county switch on ACS, CMS, BRFSS).
- **Panel layout:** controls left, legend right, tools and search along the bottom as on the legacy map; check against the three overlay panels and at 390 px.

## M5: open maps already zoomed to the place

- URL parameter `focus=<level>:<geoid>` on `/area/*`. On load it runs `focusArea` and takes precedence over `lat/lon/zoom`. It is written back to the URL, so "Copy map link" keeps the selection.
- Add it to every map link on a profile: `Indicator` "Open source map" and the tract "Open full map" in `CommunityPages.jsx` (county), the same `Indicator` on `CommunityState.jsx` (state) and `CommunityDistrict.jsx` (`focus=cd:…` with `geography=cd`), and the district "Open district source map" link. `Indicator` gets the area from its parent.
- Legacy map: the county profile's "additional context on the legacy map" link passes `focus=county:<fips>`; `App.jsx` uses its existing search-selection path (`handleCountySearchSelection` plus `setView`). States on the legacy map: fit bounds only.
- Topic-page map links have no place and stay national.

## M6: verify, deploy to staging, document

- `cd frontend && npm test && npm run build`; backend `PYTHONPATH=. .venv/bin/python -m pytest tests/test_area_lookup.py tests/test_community_*.py`, then the area suite.
- New tests: selection survives a viewport change; `focus` parameter fits and selects; tooltip text per product; legend selected block keeps suppressed, missing, not published, and zero distinct; header renders the same links on a community page, a map, and the funding page.
- `frontend/scripts/beta-walkthrough.mjs`: replace popup checks with tooltip/legend checks; add a leg: Person County profile → Open source map → map is zoomed to the county, outlined, legend shows its value; same for North Carolina and WV-01; search "Kanawha" on a map; header contrast check on a map and on `/cdc-funding`.
- Deploy to staging, run `npm run test:beta`, and check by eye at 1365 and 390 px: header on all six legacy page types, each of the nine `/area/*` maps, overlays with tools and search visible.
- Handbook: update "Map and interpretation contract" (selection, tooltip, focus parameter, recoloured ramps) and the beta section. Final diary entry and status file. State clearly: staging only, not live.
- Then stop for John's review. Promotion follows the existing runbook's application-only path (webroot and backend restart, rollback pair recorded); no data steps.

## Risks

- **`App.jsx` is 11,700 lines.** The colour swap is mechanical but wide; I will do it by exact-value mapping and review the diff, and leave data ramps alone. The legacy map gets no behaviour change apart from the `focus` link.
- **Ramp recolour** changes how three published maps look. Class breaks and status categories are unchanged, and the five-class ramp must stay readable in greyscale (guide rule); I will check that on staging.
- **Small states and large counties** can cross a zoom threshold when fitted. The zoom cap and the independent outline layer handle this; the walkthrough covers DC or Rhode Island and Fresno.
- **Retired pop-ups:** the "Download" and "Help" text disappears. If any of it is wanted, it goes on the About page.
