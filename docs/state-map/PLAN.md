# CDC state funding map: plan

Requested by John on 2026-11-20. The contract is [CONTRACT.md](CONTRACT.md); task files are in [tasks/](tasks/), and each agent's status is in [status/](status/). Claude manages the work as it does the MCP server work.

## Goal

A national map of CDC **grant** money to recipients in each state, at `/cdc-funding/map`:

- dropdowns for **fiscal year**, **budget category**, and **funding type** (all, regular, supplemental);
- a tooltip on each state with its amount and **number of grants**;
- a click panel with the state's figures, plus links to its **indicators page** (`/community/state/{fips}`) and its **state funding page** (`/cdc-funding/state/{code}`), carrying the selected filters.

## Decisions (Claude, 2026-11-20, under John's gates-only rule)

| Question | Decision |
|---|---|
| Which money | Grants only (`award_type=grant`), the same default as the state page (state-funding Amendment 2). Contracts are not offered. |
| Data | The active `state_funding` build. No new table, build, or migration. |
| Number of grants | `award_count` as the state page defines it: distinct grant awards with any obligation row under the filters. |
| Measure | Dollars as reported. No per-capita rate, rank, or share. Per capita is a question for John at Gate A. |
| Negative totals | Shown, in their own color class. In FY2026, 5 states are net negative for all funding and 55 of 57 codes for supplemental. |
| Areas without a shape | DC gets a tile because it is too small to click. GU, VI, AS, and MP have no boundary and get tiles. Unattributed (`__`) money is stated in a note, not mapped. |
| Indicators link | `/community/state/{fips}` for areas with a community state profile. Other areas show no link. |
| MCP | No new tool. `get_state_funding` already covers one state. |

## Facts checked on `places_staging` (Claude, 2026-11-20)

- FY2026 grants: 57 codes, $2,903,439,520 in total, including `__` at $152,619,342.
- `area_pilot.acs_boundary_2024` has 52 state-level shapes (50 states, DC, PR). `app.area_pilot.lookup.area_info(db, 'state', geoids, geometry=True)` already returns simplified outlines.
- Regular totals are never negative in any year. All-funding totals are negative for 3 to 16 states in FY2022 and FY2024–FY2026.

## Packages

| WP | Owner | Content | Depends on | Status |
|---|---|---|---|---|
| M0 | Claude | Plan, contract, AGENTS.md section, task files, branches | none | done |
| M1 | Codex | Map API, page, links, tests, walkthrough step; M1b: "Exclude deobligations" check box (Amendment 1) | M0 | dispatched |
| M2 | Antigravity | Reconciliation audit and walkthrough checklist | M1 API | dispatched after M1 |
| M3 | Claude | Review, screenshots at 1280 and 375 px, commit, PR to `beta`, staging deploy; **Gate A** | M1, M2 | |
| M4 | Claude | **Gate B**: rollback pair, fast-forward `main`, frontend build, restart `places-backend`, verify, handbook, diary, push | Gate A | |

## Ownership

- **Claude:** `docs/state-map/**` (except the other agents' status files), `backend/alembic/**`, `infra/**`, and the handbook. Claude does every deploy.
- **Codex** works in `/home/john/chip-codex-state` on branch `codex/state-map`. It owns `backend/app/state_funding/**`, `backend/tests/test_state_map_*` and `backend/tests/test_state_funding_*` (except the audit files), `frontend/**`, and `docs/state-map/status/codex.md`.
- **Antigravity** works in `/home/john/chip-agy-state` on branch `agy/state-map`. It owns `backend/tests/test_state_map_audit.py`, `deliverables/state-map/**`, and `docs/state-map/status/antigravity.md`.

Codex and Antigravity do not commit, push, merge, deploy, or use sudo.

## Verification

- Backend state funding and map tests pass; frontend `npm test` and `npm run build` pass; `docs/beta/contract-examples` and `backend/app/community` are unchanged.
- The audit (contract §5) passes on `places_staging`.
- Staging browser walk at 1280 and 375 px with no horizontal page scroll: each dropdown, a tooltip, a click panel, both links, a negative state, a territory tile, and an anonymous API request returning 401.
