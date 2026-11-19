# Task V7 (Antigravity): one small chart per indicator card

Assigned by Claude, 2026-11-19. Work in `/home/john/chip-agy-viz` on branch `agy/profile-viz`. It has already been fast-forwarded to `claude/profile-viz`, and `frontend/node_modules` is in place. John has reassigned Codex's frontend and community paths to you for this package (see AGENTS.md, "Profile charts and trends").

**You own:**
- `frontend/**`
- `backend/app/community/**`
- `backend/tests/test_community_charts_*`
- your existing V5 paths

Do not commit, deploy, or use sudo. Make no network calls. Record your facts in `docs/profile-viz/status/antigravity.md` and stop.

## Why

John reviewed the staging charts and said there are too many visualizations and they are too complicated. He wants small, simple charts that sit **with each indicator**, with the county, state, and national values together. No filters, and no dashboard bands for now.

His example is a set of small panels side by side. Each panel has:
- a title, which is the measure name and unit;
- a y axis with about 5 rounded ticks and light horizontal gridlines;
- years on the x axis;
- three lines: county solid with dots, the second line dashed, and the state dotted;
- one legend above all the panels;
- one source note below them.

## Build

1. **Remove the section bands.** On all three profile pages, stop rendering `ChartBand`: the county page (`CommunityPages.jsx`), the state page (`CommunityState.jsx`), and the district page (`CommunityDistrict.jsx`). Delete the components that are no longer used: the peer strip, the peer list, the group tables, and the "Over time" and "Compare" toggles. Keep `useCharts` and the `/charts` endpoint, and leave the backend payload as it is.
2. **Pass the chart rows to the cards.** On each page, build a map from `product:measure_id` to the chart row out of `charts.sections[].groups[].rows[]`, and pass the matching row to each `Indicator` as a new optional prop, `chart`. `Indicator` renders `<IndicatorChart row={chart} />` directly below the value line and above the uncertainty and source text. Without a `chart` prop, the card looks exactly as it does today.
3. **New file `frontend/src/community/charts/IndicatorChart.jsx`.** It holds a small SVG built from scratch. Do not add a charting library.
   - **When the row has a `trend`** with at least 2 published points, draw a small line chart:
     - **Size:** the full card width (use ResizeObserver) and 120 px tall.
     - **Lines:**

       | Series | Source | Colour | Line |
       |---|---|---|---|
       | Area | `trend.series` | `#0277BD` | solid, 2 px, 4 px dots |
       | State | `trend.state_series`, if present | `#C77700` | dashed 5 3, 2 px, 3.5 px dots |
       | U.S. | `trend.national_series`, if present | `#2BA48A` | dotted 1.5 3, 2 px, 3.5 px dots |

       These three colours pass the dataviz skill's palette validator; do not change them.
     - **PLACES (`style: "dots_ci"`):** dots only, with thin vertical CI whiskers and **no connecting line**. PLACES never has a state or U.S. series.
     - **Other styles** (`line_band`, `line`, `dots`): plain lines with no shaded band. `dots` means dots only.
     - **Gaps:** break a line only at a missing period (`value == null`) or at a period listed in `trend.unavailable_periods`.
     - **Y axis:** 3 or 4 rounded ticks, as short labels such as `20%`, `$12k`, or `250`, with light gridlines.
       - Percent axes start at 0 unless every value is above 40; then they start at a rounded value below the minimum.
       - Use `storage_scale` to show proportions as percent.
     - **X axis:** show the first and last labels, plus the middle labels when the width allows. ACS periods show their end year, splitting on `-` or `–`.
     - **Hover and tap:** the nearest period shows a small tooltip with the period and each series' value, formatted like the card value. Draw it in SVG or HTML inside the card, and keep it within the card.
     - **Caption:** `trend.note` as one line of small muted text under the chart. If it is longer than 140 characters, truncate it with `…`; the full text goes in the `title` attribute and in the hidden table.
   - **When there is no `trend`** but the row has `comparisons.state` or `comparisons.national` (district rows, for example), draw up to 3 short horizontal bars for area, state, and U.S.:
     - Bars start at 0 and are 10 px tall.
     - Each has a label on the left ("This district", the state name, "United States") and its value on the right.
     - Use the same colours as the lines.
   - **Otherwise** render nothing.
   - **Accessibility:**
     - The SVG has `role="img"` and an `aria-label` listing the series and their latest values.
     - A visually hidden `<table>` gives every period and value.
     - Nothing depends on colour alone: the lines differ in dash pattern, and the legend names each series.
4. **One legend per section.** Add it to the section heading on each profile page, not to each card. It is a small inline legend showing each line style with its name:
   - county page: the county name (for example "Greene County"), the state name, "United States";
   - state page: the state name and "United States";
   - district page: "This district", the state name, "United States".

   It lists only the series that appear in that section, and it is hidden when the section has no chart.
5. **Mobile.**
   - The cards are already 1 column at 640 px and below, and the chart fills the card.
   - Nothing may overflow at 375 or 390 px.
   - At least 3 y-tick labels must fit, with no overlapping text.
6. **Print:** hide `IndicatorChart` and the legends.
7. **Remove the CSS** for the deleted band, peer, and toggle classes.

## Tests

- **Update the vitest tests in `frontend/src/community/charts/`.** Delete the tests of deleted components and add these:
  - an ACS row draws 3 paths with different dash arrays;
  - a PLACES row draws no `path` with a stroke and draws whiskers;
  - a district row with no trend draws 3 bars;
  - a row with no trend and no comparisons renders nothing;
  - a missing period breaks the line;
  - an `Indicator` without a `chart` prop renders the same markup as before (use a snapshot or check its text);
  - the y ticks for percent start at 0.
- **Update `frontend/scripts/beta-walkthrough.mjs`.** Replace the chart checks with these, at 1365, 390, and 375 px, on `/community/county/01055`, `/community/state/01`, and `/district/cd/5401`:
  - at least one `.indicator-chart` is present;
  - there is no `.chart-band`;
  - there is no document overflow;
  - no axis label starts with `-`;
  - take a screenshot when `CHIP_BETA_SCREENSHOT_DIR` is set.

  You cannot run the walkthrough yourself; Claude runs it on staging.
- **Commands:**
  - `cd frontend && npm test && npm run build`
  - `cd backend && PYTHONPATH=. /home/john/chip-agy/backend/.venv-mcp/bin/python -m pytest -q tests/test_profile_charts_audit.py` (this skips without the environment variables; that is fine)
  - `git diff --check`

## Done when

- The tests and the build pass.
- `docs/profile-viz/status/antigravity.md` has a V7 row and a `## V7 diary facts — <ISO timestamp with timezone>` section listing:
  - the files you changed;
  - the test counts;
  - anything you could not verify.

Finish with a report of 10 lines or fewer.
