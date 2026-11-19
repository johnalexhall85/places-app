# Profile charts and trends

John approved this plan on 2026-11-19. Claude Code is project manager. The [chart contract](CHART_CONTRACT.md) defines endpoints, comparability, and groups. Task files are in [tasks/](tasks/); status is in [status/](status/).

## Decisions with John (2026-11-19)

| Question | Decision |
|---|---|
| PLACES across years | One dot with its 95% CI for each data year, labelled with its release. No connecting line and no computed change. A fixed note says the years are separate model runs. |
| County PLACES comparison | Other counties in the same state (same model, same release). By default each measure gets a compact strip. A "Compare counties" toggle opens a sorted dot-and-interval list. The BRFSS state figure stays a separate labelled note and never shares the PLACES axis. |
| U.S. values | Add ACS 5-year U.S. values for every window CHIP holds, and keep CMS national values for every year. There is no BRFSS national figure, because the median of states is not an estimate. |
| Autonomy | Act between gates. John approves Gate A (staging tryout) and Gate B (promotion to live). |

## Design

- **Section band.** Each profile section opens with one compact panel that groups related measures. Existing indicator cards stay below it, unchanged.
- **Trends.** Each band row has an "Over time" toggle. Trends are closed by default.
- **Phones.**
  - Charts are responsive SVG that use the full container width.
  - Below 640 px, each row stacks with its label above the bar.
  - Peer lists show the area, its 15 nearest peers, and the lowest and highest values, with a "show all" option.
  - Nothing may be wider than the viewport.
- **Brand.**
  - Colours: area #0277BD (circle), state #F0B97D (diamond), U.S. #009688 (square). The shapes keep the charts readable in greyscale.
  - Gridlines on the value axis only, a source line under every chart, and a "Show as table" option on each chart.
- **Charting.** Hand-built SVG React components. No new charting library.
- **What stays the same.**
  - Existing profile endpoints and the `docs/beta/contract-examples` snapshots stay byte-identical.
  - History reaches profiles only through the new `/charts` and `/peers` endpoints.
- **Refinement (2026-11-19, Claude, during V0).** U.S. values go into a new table `area_pilot.observation_national` under the dataset pointer `chip_national_reference`. The approved plan had a `us` level in the ACS registries instead. The change:
  - leaves current ACS and CMS releases and the history `level` CHECK constraint untouched;
  - uses the level name `national` with GEOID `US`, which is what the CMS current table already uses.

## Ownership

- **Claude:**
  - `backend/app/area_pilot/**` except the parser paths
  - `backend/alembic/**`, `infra/**`
  - `docs/profile-viz/**` except the other agents' status files
  - the handbook
  - every ingest and publication
- **Codex:**
  - `backend/app/community/**`, `frontend/**`
  - `backend/tests/test_community_charts_*`
  - `docs/profile-viz/status/codex.md`
  - Worktree: `/home/john/chip-codex-viz`
- **Antigravity:**
  - `backend/app/area_pilot/history/parsers/cms_gv.py`
  - `backend/tests/test_history_parsers_cms_gv*`
  - `backend/tests/test_profile_charts_audit.py`
  - `deliverables/profile-viz/**`
  - `docs/profile-viz/status/antigravity.md`
  - Worktree: `/home/john/chip-agy-viz`

## Packages

| WP | Owner | Content | Depends on | Status |
|---|---|---|---|---|
| V0 | Claude | Plan, contract, AGENTS.md section, task files, status files | none | done |
| V1 | Claude | `comparability.json`; `lookup.area_series_many`, `lookup.comparability`, `lookup.national_series`; `observation_national` migration and builder; ACS U.S. ingest into staging | V0 | done (staging) |
| V2 | Antigravity | CMS parser `parse_national()` for national rows 2019–2023, with tests | V0 | done |
| V3 | Codex | `/charts` and `/peers` endpoints, `chart_groups.json`, tests, snapshot byte-identity test | V1, V2 | done |
| V4 | Codex | Frontend charts, section bands, toggles, table fallbacks, vitest, overflow check in the walkthrough at 375 and 390 px | V3 | done (V4b revisions) |
| V5 | Antigravity | Independent audit test of chart payloads and rules; user guide `reading-the-charts.md` | V3 | done |
| V6 | Claude | Review, merge to `beta`, staging deploy and walkthrough, Gate A, runbook, Gate B, handbook and diary | V2–V5 | staging deployed; Gate A pending |

## Verification

- **Backend tests:** `tests/test_community_*`, `tests/test_area_series_many.py`, `tests/test_history_parsers_cms_gv*`, and `tests/test_profile_charts_audit.py` pass.
- **No change to existing profiles:**
  - `git diff --exit-code docs/beta/contract-examples` is clean.
  - Existing profile JSON from staging for 01055, 01, 5401 and 54039 is unchanged before and after.
- **Frontend:** `npm test`, `npm run build`, and `npm run test:beta` all pass. The walkthrough's overflow assertion holds at 375 and 390 px.
- **Gate A walk:**
  - Greene County AL: PLACES strip, peer list, and dots.
  - Etowah County AL: ACS and CMS state and U.S. markers, and trends.
  - Alabama: BRFSS peer states, BRFSS trend, ACS U.S. marker.
  - WV-01: ACS state marker; no trend toggle.
- **MCP eval:** stays at 54/54. The MCP server is untouched.
