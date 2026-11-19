# Task V4b (Codex): chart revisions after the staging review

Assigned by Claude, 2026-11-19. Work in `/home/john/chip-codex-viz` on branch `codex/profile-viz`. Claude has committed your V3+V4 work on `claude/profile-viz` and deployed it to staging.

**Before you start:** run `git merge --ff-only claude/profile-viz` and confirm your tree is clean. Then follow the same ownership, commands, and rules as [V3V4-codex.md](V3V4-codex.md): no commit, push, merge to beta, deploy, or sudo.

Read the v1.1 amendments in section 1 of [CHART_CONTRACT.md](../CHART_CONTRACT.md) first.

The review found the charts correct in their data, but too busy and hard to read. John asked that profiles not overwhelm the reader, and his reference is a sorted dot-and-interval chart with value labels. You can see staging screenshots in `.review-shots/` (untracked; leave it uncommitted); `greene-1365-band1.png` and `greene-health-1365.png` are the clearest. If you can't open them, the problems are described below.

## Fixes

1. **Fewer controls.** Remove the two full-size buttons under every row.
   - Each row gets one compact line of text buttons, for example "Over time · Compare counties", showing only the ones that apply. They look like links, but each keeps a 44 px tap target through padding.
   - "Show as table" appears once per group, not once per row. The group table lists each row's area value, interval, state value, U.S. value, and period.
   - The trend panel keeps its own single "Show as table" link.
2. **Axes.**
   - Use rounded tick values ("nice" ticks): 3 to 5 labelled ticks per axis.
   - A percent or proportion axis never goes below 0, and never above 100 (or 1 for a proportion).
   - The axis maximum is the rounded-up maximum of every value, interval end, marker, and peer value shown on that axis.
   - Currency labels are short, for example `$0`, `$40k`, `$80k`.
   - No label shows more than one decimal place. "-3.87%" and "$85,446.72" must never appear.
3. **Value labels.**
   - Print the area's value next to its dot, as in John's reference.
   - Under each row, write the comparison values as text with their marker shapes, for example "◆ Alabama 59,674 · ■ United States 80,734".
4. **One scale per row.** The `PeerStrip` must use exactly the same x scale as the dot row above it, so the area's position matches on both. Draw the strip directly under the dot on the same axis.
5. **`PeerList` as a chart.** Replace the coloured table with an SVG dot-and-interval chart in the style of John's reference:
   - One row per area: the name on the left, a dot with its 95% CI line, and the value on the right.
   - A light shaded band marks this area's CI across the whole chart.
   - Rows whose interval overlaps this area's are blue (#0277BD); the rest are grey (#78909C).
   - Rows are sorted highest first, and this area is in bold.
   - The default view shows this area, its 15 nearest areas by value, and then, after a dashed rule, the lowest and highest areas labelled "(lowest)" and "(highest)" when they are not already shown. "Show all N" lists every area.
   - The legend uses drawn swatches: blue dot, grey dot, shaded band.
   - Keep the "display aid, not a test of statistical difference" note.
   - On phones, the name column takes about 38% of the width, and long names are truncated with an ellipsis. Full names stay in the table and the `aria-label`.
6. **Trend charts.**
   - Add a value axis with 3 rounded tick labels.
   - Label the first and last published values. On screens 640 px and wider, also label every `dots_ci` dot.
   - Follow the v1.1 rules:
     - connect neighbouring published periods, and break only at a missing or unavailable period;
     - delete the "Boundary changed; line breaks here" captions;
     - show `trend.note` as the only caption;
     - put the per-period notes, boundary vintages, and release labels in a collapsed `<details>` titled "About these years", and in the table.
   - `release_label` for the current period is the product name, never `source_release_id`; "2025-12-12" must not appear. Fix this in `backend/app/community/charts.py`.
7. **Sparklines** (trend-only rows): show the latest value as a label, the first and last period as small labels, and a y range scaled to the data.
8. **Legends** at the top of a band and in trend panels use drawn marker swatches (circle, diamond, square), not text alone.
9. **ACS period labels.** On the axis, shorten them to the end year. Split on both `-` and `–` (the data uses an en dash).
10. **Walkthrough.** `npm run test:beta` stops at `visit('/explore/map', 'PLACES 2025 pilot')`: the heading isn't found on staging. This failure predates your work.
    - Find out what the page shows now. Update the expectation to the current heading only if the page changed on purpose. Otherwise report it.
    - Don't weaken the other checks.
    - Add chart assertions:
      - no axis label matches `/^-/`;
      - no label has more than one decimal place;
      - the default `PeerList` has at most 18 rows;
      - no row has more than 2 visible controls.

## Tests

- **vitest:**
  - nice-tick output for percent, currency, and proportion;
  - no negative percent axis;
  - the strip and dot share one scale;
  - the `PeerList` subset and fringe rows;
  - a trend that crosses a vintage-label change draws a continuous line, while a missing period breaks it;
  - the current `release_label` is not a date.
- **backend:** update `tests/test_community_charts_api.py` for the release label.
- **Commands:** the backend and frontend commands from V3V4. You may run the walkthrough against staging on port 8080, which serves your V3+V4 work, but your changes are not deployed there. To check them in a browser, run your own build and dev backend on port 8002.

## Done when

- All tests pass, and the existing payload hashes from V3V4 are still unchanged.
- `docs/profile-viz/status/codex.md` has a V4b row and a `## V4b diary facts — <ISO timestamp with timezone>` section.

Finish with a report of 12 lines or fewer.
